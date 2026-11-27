"""DocumentAssistantAgent: per-user RAG retrieval, summarization, and document comparison."""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from agents.base import AgentTaskInput, AgentTaskOutput, BaseSpecialistAgent
from core.security import wrap_untrusted_data
from db.models import DocumentRecord
from services.document_service import search_user_documents


class DocumentAssistantAgent(BaseSpecialistAgent):
    name = "DocumentAssistantAgent"
    category = "documents"
    description = "Answers questions over uploaded PDF, DOCX, CSV, XLSX, TXT, and Markdown files."
    instruction_filename = "document_assistant.md"

    def execute(self, task: AgentTaskInput, session: Optional[Session] = None) -> AgentTaskOutput:
        self.assert_no_loop(task)
        if session is None:
            return AgentTaskOutput(
                agent_name=self.name,
                status="error",
                message="Database session required to access isolated user documents.",
            )

        docs = (
            session.query(DocumentRecord)
            .filter(DocumentRecord.user_id == task.user_id)
            .order_by(DocumentRecord.created_at.desc())
            .all()
        )
        if not docs:
            return AgentTaskOutput(
                agent_name=self.name,
                status="completed",
                message="You have no uploaded documents yet. Upload a PDF, DOCX, CSV, XLSX, TXT, or Markdown file in the Documents tab first.",
                data={"documents": []},
            )

        intent = task.intent
        params = task.params

        if intent == "summarize_document":
            self.check_tool_permission(session, task, "summarize_document_chunks", params)
            doc_id = params.get("document_id")
            target = next((d for d in docs if d.id == doc_id), docs[0])
            self.log_tool_use(session, task, "summarize_document_chunks", params={"document_id": target.id})
            return AgentTaskOutput(
                agent_name=self.name,
                message=(
                    f"### Summary of `{target.filename}` ({target.chunk_count} chunks)\n"
                    f"{wrap_untrusted_data(f'doc:{target.id}', target.extracted_summary)}"
                ),
                data={"document_id": target.id, "filename": target.filename, "summary": target.extracted_summary},
                tools_called=["summarize_document_chunks"],
            )

        if intent == "compare_documents":
            self.check_tool_permission(session, task, "list_documents", params)
            if len(docs) < 2:
                return AgentTaskOutput(
                    agent_name=self.name,
                    message="Upload at least two documents to run a side-by-side comparison.",
                    data={"document_count": len(docs)},
                )
            d1, d2 = docs[0], docs[1]
            self.log_tool_use(session, task, "list_documents", params={"compared": [d1.id, d2.id]})
            msg = (
                f"### Document Comparison\n"
                f"- **{d1.filename}** ({d1.chunk_count} chunks): {d1.extracted_summary[:180]}\n"
                f"- **{d2.filename}** ({d2.chunk_count} chunks): {d2.extracted_summary[:180]}"
            )
            return AgentTaskOutput(
                agent_name=self.name,
                message=msg,
                data={"compared": [d1.id, d2.id]},
                tools_called=["list_documents"],
            )

        # Default: RAG question answering
        self.check_tool_permission(session, task, "query_document_chunks", params)
        question = (params.get("question") or task.raw_query or "").strip()
        excerpts = search_user_documents(
            session,
            user_id=task.user_id,
            query=question,
            document_id=params.get("document_id"),
            limit=3,
        )
        self.log_tool_use(session, task, "query_document_chunks", params={"hits": len(excerpts)})
        if not excerpts:
            return AgentTaskOutput(
                agent_name=self.name,
                message="No matching sections were found in your uploaded documents.",
                data={"excerpts": []},
                tools_called=["query_document_chunks"],
            )
        formatted = "\n\n".join(
            f"**Source `{ex['filename']}` (chunk #{ex['chunk_index']}):**\n{wrap_untrusted_data(ex['filename'], ex['excerpt'][:350])}"
            for ex in excerpts
        )
        return AgentTaskOutput(
            agent_name=self.name,
            message=f"Here is what I found in your documents:\n\n{formatted}",
            data={"excerpts": excerpts},
            tools_called=["query_document_chunks"],
        )
