"""CommunicationAgent: professional drafting, tone adjustment, and approval-gated messaging."""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from agents.base import AgentTaskInput, AgentTaskOutput, BaseSpecialistAgent
from llm.adapter import ModelFactory


class CommunicationAgent(BaseSpecialistAgent):
    name = "CommunicationAgent"
    category = "communication"
    description = "Drafts emails, executive summaries, invites, and messages with explicit approval before send."
    instruction_filename = "communication.md"

    def execute(self, task: AgentTaskInput, session: Optional[Session] = None) -> AgentTaskOutput:
        self.assert_no_loop(task)
        self.check_tool_permission(session, task, "draft_email", task.params)

        instruction = (task.params.get("instruction") or task.raw_query or "").strip()
        tone = task.params.get("tone", "professional")
        recipients = task.params.get("recipient_emails", [])

        adapter = ModelFactory.create()
        if adapter.provider_name != "offline":
            try:
                res = adapter.generate_text(
                    system_prompt=(
                        f"Draft a concise, {tone} business communication. Never invent facts or claims. "
                        "Mark placeholders in [brackets] if details are missing."
                    ),
                    user_prompt=instruction,
                )
                draft_text = res.text.strip()
            except Exception:
                draft_text = self._deterministic_draft(instruction, tone, recipients)
        else:
            draft_text = self._deterministic_draft(instruction, tone, recipients)

        self.log_tool_use(session, task, "draft_email", params={"tone": tone, "recipients_count": len(recipients)})
        return AgentTaskOutput(
            agent_name=self.name,
            message=(
                f"Prepared **{tone}** communication draft (not sent — requires explicit approval and connected email/Slack integration):\n\n"
                f"```text\n{draft_text}\n```"
            ),
            data={"draft": draft_text, "tone": tone, "recipients": recipients, "sent": False},
            tools_called=["draft_email"],
        )

    @staticmethod
    def _deterministic_draft(instruction: str, tone: str, recipients: list) -> str:
        to_line = ", ".join(recipients) if recipients else "[Recipient]"
        greeting = "Dear [Name]," if tone == "formal" else ("Hi [Name]," if tone == "friendly" else "Hello [Name],")
        closing = "Sincerely," if tone == "formal" else "Best regards,"
        return (
            f"To: {to_line}\n"
            f"Subject: [Subject — regarding your request]\n\n"
            f"{greeting}\n\n"
            f"I am writing to follow up regarding: {instruction}.\n"
            "Please let me know your feedback or preferred timing.\n\n"
            f"{closing}\n[Your Name]"
        )
