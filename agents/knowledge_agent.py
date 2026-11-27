"""PersonalKnowledgeAgent: user-controlled opt-in memory with credential blocking & export."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from agents.base import AgentTaskInput, AgentTaskOutput, BaseSpecialistAgent
from db.models import MemoryEntry

_SECRET_MEMORY_RE = re.compile(
    r"(?:password|passwd|api[_\s-]?key|access[_\s-]?token|refresh[_\s-]?token|secret[_\s-]?key|sk-[A-Za-z0-9]{12,}|AIza[0-9A-Za-z\-_]{16,})",
    re.I,
)


class PersonalKnowledgeAgent(BaseSpecialistAgent):
    name = "PersonalKnowledgeAgent"
    category = "knowledge_management"
    description = "Manages opt-in user preferences, working habits, and project memory isolated per user."
    instruction_filename = "personal_knowledge.md"

    def execute(self, task: AgentTaskInput, session: Optional[Session] = None) -> AgentTaskOutput:
        self.assert_no_loop(task)
        if session is None:
            return AgentTaskOutput(
                agent_name=self.name,
                status="error",
                message="Database session required for isolated user memory.",
            )

        intent = task.intent
        params = task.params

        if intent == "save_memory":
            self.check_tool_permission(session, task, "save_memory", params)
            content = (params.get("content") or "").strip()
            if _SECRET_MEMORY_RE.search(content):
                self.log_tool_use(
                    session,
                    task,
                    "save_memory",
                    params={},
                    outcome="DENIED",
                    detail="Rejected storing sensitive password/token/API key in conversational memory",
                )
                return AgentTaskOutput(
                    agent_name=self.name,
                    status="denied",
                    message="Blocked: DeskMate never stores passwords, API keys, or OAuth tokens in conversational memory.",
                    error_code="SENSITIVE_CREDENTIAL_REJECTED",
                )
            key = params.get("key") or "user_note"
            retention_days = int(params.get("retention_days", 90))
            entry = MemoryEntry(
                user_id=task.user_id,
                category=params.get("category", "preference"),
                key=key,
                content=content,
                approved=True,
                retention_days=retention_days,
                expires_at=datetime.now(timezone.utc) + timedelta(days=retention_days),
            )
            session.add(entry)
            session.flush()
            self.log_tool_use(session, task, "save_memory", params={"memory_id": entry.id, "key": key})
            return AgentTaskOutput(
                agent_name=self.name,
                message=f"Saved opt-in memory entry (id: {entry.id}, retention: {retention_days} days).",
                data={"memory_id": entry.id},
                tools_called=["save_memory"],
            )

        if intent == "delete_memory":
            self.check_tool_permission(session, task, "delete_memory", params)
            entries = session.query(MemoryEntry).filter(MemoryEntry.user_id == task.user_id).all()
            mem_id = params.get("memory_id")
            target = next((e for e in entries if e.id == mem_id), None)
            if target is None and entries:
                q = (params.get("query") or "").lower()
                target = next((e for e in entries if any(w in e.content.lower() for w in q.split() if len(w) > 3)), None)
            if target is None:
                return AgentTaskOutput(agent_name=self.name, message="No matching memory entry found to delete.")
            session.delete(target)
            session.flush()
            self.log_tool_use(session, task, "delete_memory", params={"memory_id": target.id})
            return AgentTaskOutput(agent_name=self.name, message=f"Deleted memory entry {target.id}.", tools_called=["delete_memory"])

        entries = session.query(MemoryEntry).filter(MemoryEntry.user_id == task.user_id).all()
        if intent == "export_memory":
            self.check_tool_permission(session, task, "export_memory", params)
            data = [{"id": e.id, "category": e.category, "key": e.key, "content": e.content} for e in entries]
            self.log_tool_use(session, task, "export_memory", params={"count": len(data)})
            return AgentTaskOutput(
                agent_name=self.name,
                message=f"Exported {len(data)} memory item(s) belonging exclusively to your user profile.",
                data={"memories": data},
                tools_called=["export_memory"],
            )

        self.check_tool_permission(session, task, "list_memory", params)
        self.log_tool_use(session, task, "list_memory", params={"count": len(entries)})
        if not entries:
            return AgentTaskOutput(agent_name=self.name, message="No saved personal memory entries.", data={"memories": []})
        lines = [f"- [{e.category}] {e.key}: {e.content} (id: {e.id})" for e in entries]
        return AgentTaskOutput(
            agent_name=self.name,
            message="Your stored memory entries:\n" + "\n".join(lines),
            data={"memories": [{"id": e.id, "key": e.key, "content": e.content} for e in entries]},
            tools_called=["list_memory"],
        )
