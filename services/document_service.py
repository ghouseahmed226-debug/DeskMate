"""Document ingestion, parsing, chunking, and per-user RAG retrieval service."""

from __future__ import annotations

import csv
import hashlib
import io
import re
from pathlib import Path
from typing import Any, Dict, List

from openpyxl import load_workbook
from pypdf import PdfReader
from docx import Document as DocxDocument
from sqlalchemy.orm import Session

from core.security import scan_prompt_injection
from db.models import DocumentChunk, DocumentRecord


class DocumentProcessingError(Exception):
    """Raised when a document cannot be parsed or read reliably."""


def _tokenize(text: str) -> List[str]:
    words = re.findall(r"[a-z0-9]{3,}", text.lower())
    stop = {"the", "and", "for", "with", "that", "this", "from", "are", "was", "have", "your"}
    seen: List[str] = []
    for w in words:
        if w not in stop and w not in seen:
            seen.append(w)
    return seen[:40]


def extract_text_from_bytes(filename: str, content: bytes) -> str:
    """Parses PDF, DOCX, CSV, XLSX, TXT, or Markdown bytes. Fails explicitly on unreadable files."""
    ext = Path(filename).suffix.lower()
    if not content:
        raise DocumentProcessingError(f"File '{filename}' is empty (0 bytes).")

    try:
        if ext == ".pdf":
            reader = PdfReader(io.BytesIO(content))
            pages = [page.extract_text() or "" for page in reader.pages]
            text = "\n\n".join(p.strip() for p in pages if p.strip())
            if not text:
                raise DocumentProcessingError(
                    f"PDF '{filename}' contains no extractable text (may be image-scanned without OCR)."
                )
            return text

        if ext == ".docx":
            doc = DocxDocument(io.BytesIO(content))
            paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
            text = "\n".join(paragraphs)
            if not text:
                raise DocumentProcessingError(f"DOCX '{filename}' contains no readable paragraph text.")
            return text

        if ext in {".csv"}:
            decoded = content.decode("utf-8", errors="replace")
            rows = list(csv.reader(io.StringIO(decoded)))
            if not rows:
                raise DocumentProcessingError(f"CSV '{filename}' has no rows.")
            lines = [" | ".join(r) for r in rows[:200]]
            return f"CSV Summary ({len(rows)} rows):\n" + "\n".join(lines)

        if ext in {".xlsx", ".xlsm"}:
            wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
            sheets_text: List[str] = []
            for sheet in wb.sheetnames[:5]:
                ws = wb[sheet]
                row_lines = []
                for idx, row in enumerate(ws.iter_rows(values_only=True)):
                    if idx >= 100:
                        break
                    vals = [str(c) if c is not None else "" for c in row]
                    if any(vals):
                        row_lines.append(" | ".join(vals))
                if row_lines:
                    sheets_text.append(f"Sheet [{sheet}]:\n" + "\n".join(row_lines))
            if not sheets_text:
                raise DocumentProcessingError(f"Spreadsheet '{filename}' contains no populated cells.")
            return "\n\n".join(sheets_text)

        if ext in {".txt", ".md", ".markdown", ".json", ".log"}:
            text = content.decode("utf-8", errors="strict").strip()
            if not text:
                raise DocumentProcessingError(f"Text file '{filename}' is empty.")
            return text

        raise DocumentProcessingError(f"Unsupported file format '{ext}'. Supported: .pdf, .docx, .txt, .md, .csv, .xlsx.")
    except DocumentProcessingError:
        raise
    except Exception as exc:
        raise DocumentProcessingError(f"Failed to parse '{filename}': {type(exc).__name__}") from exc


def chunk_text(text: str, chunk_size: int = 800, overlap: int = 120) -> List[str]:
    clean = re.sub(r"\n{3,}", "\n\n", text.strip())
    if len(clean) <= chunk_size:
        return [clean]
    chunks: List[str] = []
    start = 0
    while start < len(clean):
        end = min(len(clean), start + chunk_size)
        chunks.append(clean[start:end].strip())
        if end == len(clean):
            break
        start = max(start + 1, end - overlap)
    return chunks


def ingest_document(
    session: Session,
    *,
    user_id: str,
    filename: str,
    content_type: str,
    raw_bytes: bytes,
) -> DocumentRecord:
    text = extract_text_from_bytes(filename, raw_bytes)
    injection_flagged, patterns = scan_prompt_injection(text)
    chunks = chunk_text(text)
    digest = hashlib.sha256(raw_bytes).hexdigest()

    preview_lines = [ln.strip() for ln in text.splitlines() if ln.strip()][:5]
    summary = " ".join(preview_lines)[:420]

    record = DocumentRecord(
        user_id=user_id,
        filename=Path(filename).name,
        content_type=content_type or "application/octet-stream",
        sha256=digest,
        chunk_count=len(chunks),
        extracted_summary=summary,
        metadata_json={
            "char_count": len(text),
            "injection_flagged": injection_flagged,
            "injection_patterns": patterns,
        },
    )
    session.add(record)
    session.flush()

    for idx, ch in enumerate(chunks):
        session.add(
            DocumentChunk(
                document_id=record.id,
                user_id=user_id,
                chunk_index=idx,
                content=ch,
                keywords_json=_tokenize(ch),
            )
        )
    session.flush()
    return record


def search_user_documents(
    session: Session,
    *,
    user_id: str,
    query: str,
    document_id: str | None = None,
    limit: int = 4,
) -> List[Dict[str, Any]]:
    """Retrieves matching chunks strictly isolated to the authenticated user_id."""
    q_tokens = set(_tokenize(query))
    chunk_query = session.query(DocumentChunk).filter(DocumentChunk.user_id == user_id)
    if document_id:
        chunk_query = chunk_query.filter(DocumentChunk.document_id == document_id)
    chunks = chunk_query.all()
    if not chunks:
        return []

    doc_names = {
        d.id: d.filename
        for d in session.query(DocumentRecord).filter(DocumentRecord.user_id == user_id).all()
    }

    scored: List[tuple[int, DocumentChunk]] = []
    for ch in chunks:
        ch_tokens = set(ch.keywords_json or _tokenize(ch.content))
        overlap = len(q_tokens & ch_tokens)
        if overlap == 0 and query.lower() in ch.content.lower():
            overlap = 1
        scored.append((overlap, ch))

    scored.sort(key=lambda pair: (pair[0], -pair[1].chunk_index), reverse=True)
    top = [pair for pair in scored if pair[0] > 0][:limit] or scored[: min(2, len(scored))]

    return [
        {
            "document_id": ch.document_id,
            "filename": doc_names.get(ch.document_id, "document"),
            "chunk_index": ch.chunk_index,
            "score": score,
            "excerpt": ch.content,
        }
        for score, ch in top
    ]
