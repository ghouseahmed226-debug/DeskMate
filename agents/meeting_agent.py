"""MeetingAssistantAgent: meeting preparation, agendas, transcript follow-ups, and decisions."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from agents.base import AgentTaskInput, AgentTaskOutput, BaseSpecialistAgent
from db.models import CalendarEvent, Contact, EmailMetadata
from skills.meeting_prep import prepare_meeting


class MeetingAssistantAgent(BaseSpecialistAgent):
    name = "MeetingAssistantAgent"
    category = "productivity"
    description = "Prepares meetings, builds agendas, summarizes notes, and proposes approval-gated follow-ups."
    instruction_filename = "meeting_assistant.md"

    def execute(self, task: AgentTaskInput, session: Optional[Session] = None) -> AgentTaskOutput:
        self.assert_no_loop(task)
        intent = task.intent
        params = task.params

        if session is None:
            title = params.get("meeting_title") or "meeting"
            summary = prepare_meeting("Orchestrator", title)
            return AgentTaskOutput(
                agent_name=self.name,
                message=summary,
                data={"meeting_title": title},
                tools_called=["get_calendar_events", "get_contacts"],
            )

        events = session.query(CalendarEvent).filter(CalendarEvent.user_id == task.user_id, CalendarEvent.status != "cancelled").all()
        contacts = session.query(Contact).filter(Contact.user_id == task.user_id).all()
        emails = session.query(EmailMetadata).filter(EmailMetadata.user_id == task.user_id).all()

        if intent == "generate_agenda":
            self.check_tool_permission(session, task, "get_calendar_events", params)
            topic = (params.get("meeting_title") or "Team Sync").strip()
            matched_event = self._match_event(events, topic)
            attendees = matched_event.attendees_json if matched_event else []
            agenda = (
                f"### Proposed Agenda: {matched_event.title if matched_event else topic}\n"
                f"1. **Check-in & Objectives (5 min)**\n"
                f"2. **Status & Key Metrics Review (15 min)**\n"
                f"3. **Open Risks & Decisions (15 min)**\n"
                f"4. **Action Items, Owners & Deadlines (10 min)**\n"
                f"- **Attendees:** {', '.join(attendees) if attendees else 'Pending confirmation'}"
            )
            self.log_tool_use(session, task, "get_calendar_events", params={"agenda_for": topic})
            return AgentTaskOutput(
                agent_name=self.name,
                message=agenda,
                data={"agenda": agenda, "event_id": matched_event.id if matched_event else None},
                tools_called=["get_calendar_events"],
            )

        if intent == "extract_followups":
            self.check_tool_permission(session, task, "create_task", params)
            notes = params.get("notes", "")
            items = [s.strip() for s in re.split(r"[.;\n]+", notes) if re.search(r"\b(will|need|action|follow|send|update|submit|decide)\b", s, re.I)]
            if not items:
                items = ["Circulate meeting notes and confirm next milestone owner"]
            self.log_tool_use(session, task, "draft_email", params={"extracted_items": len(items)})
            return AgentTaskOutput(
                agent_name=self.name,
                message=(
                    "Extracted follow-up action candidates (approval required before saving tasks or sending follow-up):\n"
                    + "\n".join(f"- {item}" for item in items[:6])
                ),
                data={"proposed_action_items": items[:6]},
                tools_called=["draft_email"],
            )

        # Default: prepare_meeting
        self.check_tool_permission(session, task, "get_calendar_events", params)
        self.check_tool_permission(session, task, "get_contacts", params)
        title = (params.get("meeting_title") or "").strip()
        meeting = self._match_event(events, title)
        if not meeting:
            self.log_tool_use(session, task, "get_calendar_events", params={"meeting_title": title, "found": False})
            return AgentTaskOutput(
                agent_name=self.name,
                message=f"Could not find a scheduled meeting matching '{title}'.",
                data={"found": False},
                tools_called=["get_calendar_events"],
            )

        attendee_lines: List[str] = []
        for email in meeting.attendees_json or []:
            c = next((ct for ct in contacts if ct.email and ct.email.lower() == email.lower()), None)
            if c:
                attendee_lines.append(f"- {c.name} ({c.email}) — {c.job_title or 'Contact'} @ {c.company or 'N/A'}")
            else:
                attendee_lines.append(f"- {email} (not in CRM)")

        related_emails = [
            f"- [{em.category}] {em.subject} (from {em.sender})"
            for em in emails
            if any(tok in f"{em.subject} {em.sender}".lower() for tok in meeting.title.lower().split() if len(tok) > 3)
        ][:3]

        self.log_tool_use(session, task, "get_contacts", params={"meeting_id": meeting.id})
        msg = (
            f"### Meeting Prep Summary: {meeting.title}\n"
            f"- **Time:** {meeting.start_at.isoformat()} to {meeting.end_at.isoformat()} ({meeting.timezone_name})\n"
            f"- **Attendees:**\n" + ("\n".join(attendee_lines) if attendee_lines else "None listed") + "\n"
            f"- **Related Emails:**\n" + ("\n".join(related_emails) if related_emails else "None matched")
        )
        return AgentTaskOutput(
            agent_name=self.name,
            message=msg,
            data={"event_id": meeting.id, "title": meeting.title, "attendees": meeting.attendees_json or []},
            tools_called=["get_calendar_events", "get_contacts", "get_emails"],
        )

    @staticmethod
    def _match_event(events: List[CalendarEvent], title_query: str) -> Optional[CalendarEvent]:
        if not events:
            return None
        q = title_query.lower().strip()
        if not q:
            return events[0]
        # Exact substring first, then token overlap
        for ev in events:
            if q in ev.title.lower():
                return ev
        tokens = [w for w in re.findall(r"[a-z0-9]+", q) if w not in {"the", "for", "meeting", "review"}]
        if tokens:
            for ev in events:
                if any(tok in ev.title.lower() for tok in tokens):
                    return ev
        return None
