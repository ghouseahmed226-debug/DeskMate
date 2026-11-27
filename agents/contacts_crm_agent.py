"""ContactCRM_Agent: personal CRM management, duplicate detection, and interaction history."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from agents.base import AgentTaskInput, AgentTaskOutput, BaseSpecialistAgent
from db.models import Contact


class ContactCRM_Agent(BaseSpecialistAgent):
    name = "ContactCRM_Agent"
    category = "crm"
    description = "Manages contacts, company associations, notes, interaction history, and duplicate checks."
    instruction_filename = "contacts_crm.md"

    def execute(self, task: AgentTaskInput, session: Optional[Session] = None) -> AgentTaskOutput:
        self.assert_no_loop(task)
        if session is None:
            return AgentTaskOutput(
                agent_name=self.name,
                status="error",
                message="Database session required for ContactCRM_Agent.",
            )

        contacts = session.query(Contact).filter(Contact.user_id == task.user_id).all()
        intent = task.intent
        params = task.params

        if intent == "create_contact":
            self.check_tool_permission(session, task, "create_contact", params)
            name = (params.get("name") or "").strip()
            email = (params.get("email") or "").strip() or None
            if not name:
                return AgentTaskOutput(
                    agent_name=self.name,
                    status="needs_clarification",
                    message="Contact name is required.",
                    clarification_question="What is the full name of the contact you want to add?",
                )

            dup = next(
                (
                    c for c in contacts
                    if (email and c.email and c.email.lower() == email.lower())
                    or c.name.lower() == name.lower()
                ),
                None,
            )
            if dup:
                return AgentTaskOutput(
                    agent_name=self.name,
                    status="completed",
                    message=f"Duplicate check: '{dup.name}' ({dup.email or 'no email'}) already exists (id: {dup.id}).",
                    data={"duplicate": True, "contact": self._serialize(dup)},
                    tools_called=["search_contacts"],
                )

            summary = f"Add contact '{name}'" + (f" <{email}>" if email else "")
            if not task.auto_confirm and not task.approval_id:
                apr = self.create_approval_gate(
                    session,
                    task,
                    action_type="create_contact",
                    summary=summary,
                    payload={"name": name, "email": email, "company": params.get("company")},
                )
                return AgentTaskOutput(
                    agent_name=self.name,
                    status="needs_approval",
                    message=f"Approval required:\n{summary}",
                    approval_request=apr,
                )

            created = Contact(
                user_id=task.user_id,
                name=name,
                email=email,
                phone=params.get("phone"),
                company=params.get("company"),
                job_title=params.get("job_title"),
                notes=params.get("notes", ""),
            )
            session.add(created)
            session.flush()
            self.log_tool_use(session, task, "create_contact", params={"contact_id": created.id})
            return AgentTaskOutput(
                agent_name=self.name,
                message=f"Created contact '{created.name}' (id: {created.id}).",
                data={"contact": self._serialize(created)},
                tools_called=["create_contact"],
            )

        # search_contacts / list
        self.check_tool_permission(session, task, "search_contacts", params)
        query = (params.get("query") or "").strip().lower()
        matches = [
            c for c in contacts
            if not query or query in f"{c.name} {c.email or ''} {c.company or ''} {c.job_title or ''}".lower()
        ]
        self.log_tool_use(session, task, "search_contacts", params={"query": query, "count": len(matches)})
        if not matches:
            return AgentTaskOutput(
                agent_name=self.name,
                message=f"No contacts matched '{params.get('query', '')}'. DeskMate never invents missing contact details.",
                data={"contacts": []},
                tools_called=["search_contacts"],
            )
        lines = [
            f"- {c.name} | {c.job_title or 'N/A'} @ {c.company or 'N/A'} | {c.email or 'no email'} | {c.phone or 'no phone'}"
            for c in matches
        ]
        return AgentTaskOutput(
            agent_name=self.name,
            message="Contacts found:\n" + "\n".join(lines),
            data={"contacts": [self._serialize(c) for c in matches]},
            tools_called=["search_contacts"],
        )

    @staticmethod
    def _serialize(c: Contact) -> Dict[str, Any]:
        return {
            "id": c.id,
            "name": c.name,
            "email": c.email,
            "phone": c.phone,
            "company": c.company,
            "job_title": c.job_title,
            "category": c.category,
            "notes": c.notes,
        }
