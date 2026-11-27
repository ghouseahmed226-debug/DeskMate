---
name: document-assistant
description: >
  Document ingestion, analysis, and question-answering.
  Use when the user wants to upload a document (PDF, DOCX, CSV, XLSX,
  TXT, Markdown), ask questions about its contents, get a summary,
  extract key data points, or search across all uploaded documents.
  Uses keyword-overlap RAG for retrieval without requiring a vector DB.
license: MIT
metadata:
  author: ghouseahmed226-debug
  version: "2.0.0"
  project: DeskMate AI
  category: documents
allowed-tools: read_file list_directory
---

# Document Assistant Skill

## Overview

Delegates to the **DocumentAssistantAgent** backed by `services/document_service.py`.
Supports PDF, DOCX, CSV, XLSX, TXT, and Markdown. Documents are chunked,
indexed per user, and searched with a lightweight keyword-overlap retriever
(no external vector DB required).

## Key Capabilities

| Capability | Description |
|---|---|
| **Ingest** | Parse and chunk any supported document format |
| **Summarise** | Produce a 3-5 sentence overview of a document |
| **Q&A** | Answer questions grounded in the document's content |
| **Extract Data** | Pull tables, lists, or named entities |
| **Search All Docs** | Cross-document keyword search |
| **Privacy** | Documents are stored per user_id — no cross-user leakage |

## Supported Formats

- PDF (`pypdf`)
- DOCX (`python-docx`)
- CSV / XLSX (`pandas` / `openpyxl`)
- TXT / Markdown (plain text)

## Example Prompts

```
Summarise the uploaded Q3 report
What does the contract say about termination clauses?
Extract all action items from the meeting notes
Search my documents for "budget allocation"
What are the key numbers in the financial model?
```

## API Endpoint

```
POST /api/documents/upload          (multipart file upload)
POST /api/documents/{id}/ask        {"question": "..."}
GET  /api/documents                 (list all user documents)
```

## Related Skills

- `research-intelligence` — web research to complement document analysis
- `task-project-management` — create tasks from document action items
- `email-intelligence` — combine email context with document findings
