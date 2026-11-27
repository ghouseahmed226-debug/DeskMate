"""
calendar_agent.py

CalendarSchedulingAgent (and backward-compatible CalendarAgent wrapper).
Supports viewing, creating, updating, rescheduling, cancelling, conflict detection,
available time slot finding, timezones, recurring events, and agendas.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from dateutil import parser as date_parser
from sqlalchemy.orm import Session

from agents.base import AgentTaskInput, AgentTaskOutput, BaseSpecialistAgent
from db.models import CalendarEvent, UserPreference
from mcp_server.personal_data_mcp_server import call_tool


def _ensure_aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _find_conflicts(events: List[CalendarEvent], start_at: datetime, end_at: datetime, exclude_id: Optional[str] = None) -> List[CalendarEvent]:
    s_new = _ensure_aware(start_at)
    e_new = _ensure_aware(end_at)
    conflicts = []
    for ev in events:
        if ev.status == "cancelled" or (exclude_id and ev.id == exclude_id):
            continue
        ev_s = _ensure_aware(ev.start_at)
        ev_e = _ensure_aware(ev.end_at)
        if ev_s < e_new and s_new < ev_e:
            conflicts.append(ev)
    return conflicts


class CalendarSchedulingAgent(BaseSpecialistAgent):
    name = "CalendarSchedulingAgent"
    category = "calendar"
    description = "Views, schedules, updates, cancels events, detects conflicts, and finds available slots."
    instruction_filename = "calendar_scheduling.md"

    def execute(self, task: AgentTaskInput, session: Optional[Session] = None) -> AgentTaskOutput:
        self.assert_no_loop(task)
        intent = task.intent
        params = task.params
        tz_name = params.get("timezone") or task.timezone_name or "UTC"

        if session is None:
            events = call_tool("CalendarAgent", "get_calendar_events", date=params.get("date"))
            if intent == "list_events":
                return AgentTaskOutput(
                    agent_name=self.name,
                    message=CalendarAgent._format_events(events),
                    data={"events": events},
                    tools_called=["get_calendar_events"],
                )
            return AgentTaskOutput(
                agent_name=self.name,
                status="error",
                message="Database session required for stateful calendar operations.",
            )

        events = (
            session.query(CalendarEvent)
            .filter(CalendarEvent.user_id == task.user_id, CalendarEvent.status != "cancelled")
            .order_by(CalendarEvent.start_at.asc())
            .all()
        )

        if intent in {"list_events", "daily_summary"}:
            self.check_tool_permission(session, task, "get_calendar_events", params)
            date_filter = params.get("date")
            filtered = events
            if date_filter:
                filtered = [e for e in events if _ensure_aware(e.start_at).date().isoformat() == date_filter]
            self.log_tool_use(session, task, "get_calendar_events", params={"date": date_filter, "count": len(filtered)})
            return self._format_db_events(filtered, tz_name)

        if intent == "find_available_slots":
            self.check_tool_permission(session, task, "find_free_slots", params)
            pref = session.query(UserPreference).filter_by(user_id=task.user_id).first()
            wh_start = pref.working_hours_start if pref else "09:00"
            wh_end = pref.working_hours_end if pref else "17:30"
            try:
                tz = ZoneInfo(tz_name)
            except Exception:
                tz = timezone.utc

            target_date_str = params.get("date")
            if target_date_str:
                base_date = datetime.strptime(target_date_str, "%Y-%m-%d").date()
            else:
                base_date = (datetime.now(tz) + timedelta(days=1)).date()

            sh, sm = map(int, wh_start.split(":"))
            eh, em = map(int, wh_end.split(":"))
            duration = int(params.get("duration_minutes", 60))
            cursor = datetime(base_date.year, base_date.month, base_date.day, sh, sm, tzinfo=tz)
            day_end = datetime(base_date.year, base_date.month, base_date.day, eh, em, tzinfo=tz)

            slots: List[Dict[str, str]] = []
            while cursor + timedelta(minutes=duration) <= day_end and len(slots) < 5:
                cand_end = cursor + timedelta(minutes=duration)
                if not _find_conflicts(events, cursor, cand_end):
                    slots.append({"start": cursor.isoformat(), "end": cand_end.isoformat(), "timezone": str(tz)})
                cursor += timedelta(minutes=30)

            self.log_tool_use(session, task, "find_free_slots", params={"date": base_date.isoformat(), "slots_found": len(slots)})
            if not slots:
                return AgentTaskOutput(
                    agent_name=self.name,
                    message=f"No {duration}-minute open slots found on {base_date.isoformat()} ({tz}).",
                    data={"slots": []},
                    tools_called=["find_free_slots"],
                )
            formatted = "\n".join(f"- {s['start']} to {s['end']} ({s['timezone']})" for s in slots)
            return AgentTaskOutput(
                agent_name=self.name,
                message=f"Available {duration}-minute slots on {base_date.isoformat()}:\n{formatted}",
                data={"slots": slots},
                tools_called=["find_free_slots"],
            )

        if intent == "create_event":
            self.check_tool_permission(session, task, "create_calendar_event", params)
            start_iso = params.get("start")
            end_iso = params.get("end")
            title = params.get("title")
            if not start_iso or not end_iso or not title:
                return AgentTaskOutput(
                    agent_name=self.name,
                    status="needs_clarification",
                    message="Need title, start time, and end time before creating an event.",
                    clarification_question="Please confirm the event title, date, start time, and timezone.",
                )

            start_at = _ensure_aware(date_parser.isoparse(start_iso))
            end_at = _ensure_aware(date_parser.isoparse(end_iso))
            conflicts = _find_conflicts(events, start_at, end_at)
            conflict_note = ""
            if conflicts:
                conflict_titles = ", ".join(c.title for c in conflicts)
                conflict_note = f" WARNING: Conflicts with existing event(s): {conflict_titles}."

            attendees = params.get("attendees", [])
            proposal = (
                f"Create event '{title}' on {start_at.date().isoformat()} "
                f"{start_at.strftime('%H:%M')}–{end_at.strftime('%H:%M')} ({tz_name}), "
                f"attendees={attendees or ['only you']}.{conflict_note}"
            )
            if not task.auto_confirm and not task.approval_id:
                apr = self.create_approval_gate(
                    session,
                    task,
                    action_type="create_calendar_event",
                    summary=proposal,
                    payload={
                        "title": title,
                        "start": start_iso,
                        "end": end_iso,
                        "timezone": tz_name,
                        "attendees": attendees,
                        "conflicts": [c.id for c in conflicts],
                    },
                )
                return AgentTaskOutput(
                    agent_name=self.name,
                    status="needs_approval",
                    message=f"Approval required before modifying your calendar:\n{proposal}",
                    approval_request=apr,
                )

            created = CalendarEvent(
                user_id=task.user_id,
                title=title,
                start_at=start_at,
                end_at=end_at,
                timezone_name=tz_name,
                attendees_json=attendees,
                agenda=params.get("agenda", ""),
                recurrence=params.get("recurrence"),
                status="confirmed",
            )
            session.add(created)
            session.flush()
            self.log_tool_use(
                session,
                task,
                "create_calendar_event",
                params={"event_id": created.id, "title": title},
                approval_state="approved" if task.approval_id else "auto_confirm",
            )
            return AgentTaskOutput(
                agent_name=self.name,
                message=f"Created calendar event '{created.title}' ({created.start_at.isoformat()} to {created.end_at.isoformat()}, {tz_name}).",
                data={"event": {"id": created.id, "title": created.title, "start": created.start_at.isoformat(), "end": created.end_at.isoformat()}},
                tools_called=["create_calendar_event"],
            )

        if intent in {"reschedule_event", "update_event"}:
            self.check_tool_permission(session, task, "update_calendar_event", params)
            target = self._locate_event(events, params.get("event_id"), params.get("query"))
            if target is None:
                return AgentTaskOutput(
                    agent_name=self.name,
                    status="needs_clarification",
                    message="I couldn't uniquely identify which calendar event to update.",
                    clarification_question="Which event ID or exact event title should I reschedule?",
                )
            new_start = _ensure_aware(date_parser.isoparse(params["start"])) if params.get("start") else target.start_at
            new_end = _ensure_aware(date_parser.isoparse(params["end"])) if params.get("end") else (new_start + (target.end_at - target.start_at))
            conflicts = _find_conflicts(events, new_start, new_end, exclude_id=target.id)
            conflict_note = f" WARNING: Overlaps with {', '.join(c.title for c in conflicts)}." if conflicts else ""

            proposal = (
                f"Update event '{target.title}' (id: {target.id}) to "
                f"{new_start.isoformat()} – {new_end.isoformat()} ({tz_name}), "
                f"attendees={target.attendees_json or ['only you']}.{conflict_note}"
            )
            if not task.auto_confirm and not task.approval_id:
                apr = self.create_approval_gate(
                    session,
                    task,
                    action_type="update_calendar_event",
                    summary=proposal,
                    payload={"event_id": target.id, "start": new_start.isoformat(), "end": new_end.isoformat(), "timezone": tz_name},
                )
                return AgentTaskOutput(
                    agent_name=self.name,
                    status="needs_approval",
                    message=f"Approval required before updating your calendar:\n{proposal}",
                    approval_request=apr,
                )

            target.start_at = new_start
            target.end_at = new_end
            target.timezone_name = tz_name
            if params.get("title"):
                target.title = params["title"]
            session.flush()
            self.log_tool_use(session, task, "update_calendar_event", params={"event_id": target.id}, approval_state="approved" if task.approval_id else "auto_confirm")
            return AgentTaskOutput(
                agent_name=self.name,
                message=f"Updated '{target.title}' (id: {target.id}) to {target.start_at.isoformat()} ({tz_name}).",
                data={"event": {"id": target.id, "title": target.title, "start": target.start_at.isoformat()}},
                tools_called=["update_calendar_event"],
            )

        if intent == "cancel_event":
            self.check_tool_permission(session, task, "cancel_calendar_event", params)
            target = self._locate_event(events, params.get("event_id"), params.get("query"))
            if target is None:
                return AgentTaskOutput(
                    agent_name=self.name,
                    status="needs_clarification",
                    message="Could not find the calendar event to cancel.",
                    clarification_question="Please provide the exact event title or ID to cancel.",
                )
            proposal = f"Cancel meeting '{target.title}' scheduled for {target.start_at.isoformat()} ({target.timezone_name})."
            if not task.auto_confirm and not task.approval_id:
                apr = self.create_approval_gate(
                    session,
                    task,
                    action_type="cancel_calendar_event",
                    summary=proposal,
                    payload={"event_id": target.id},
                )
                return AgentTaskOutput(
                    agent_name=self.name,
                    status="needs_approval",
                    message=f"Approval required before cancelling a meeting:\n{proposal}",
                    approval_request=apr,
                )
            target.status = "cancelled"
            session.flush()
            self.log_tool_use(session, task, "cancel_calendar_event", params={"event_id": target.id}, approval_state="approved" if task.approval_id else "auto_confirm")
            return AgentTaskOutput(
                agent_name=self.name,
                message=f"Cancelled meeting '{target.title}' (id: {target.id}).",
                data={"cancelled_event_id": target.id},
                tools_called=["cancel_calendar_event"],
            )

        return AgentTaskOutput(
            agent_name=self.name,
            status="error",
            message=f"Unsupported calendar intent '{intent}'.",
        )

    @staticmethod
    def _locate_event(events: List[CalendarEvent], event_id: Optional[str], query: Optional[str]) -> Optional[CalendarEvent]:
        if event_id:
            found = next((e for e in events if e.id == event_id), None)
            if found:
                return found
        if query:
            q = query.lower().strip()
            for e in events:
                if q in e.title.lower() or any(tok in e.title.lower() for tok in q.split() if len(tok) > 3):
                    return e
        return None

    def _format_db_events(self, events: List[CalendarEvent], tz_name: str) -> AgentTaskOutput:
        if not events:
            return AgentTaskOutput(
                agent_name=self.name,
                message="No scheduled events found for that period.",
                data={"events": []},
                tools_called=["get_calendar_events"],
            )
        lines = []
        serialized = []
        for e in events:
            lines.append(f"- {e.title} ({e.start_at.isoformat()} to {e.end_at.isoformat()}, {e.timezone_name})")
            serialized.append(
                {
                    "id": e.id,
                    "title": e.title,
                    "start": e.start_at.isoformat(),
                    "end": e.end_at.isoformat(),
                    "timezone": e.timezone_name,
                    "attendees": e.attendees_json or [],
                }
            )
        return AgentTaskOutput(
            agent_name=self.name,
            message="Here is your schedule:\n" + "\n".join(lines),
            data={"events": serialized},
            tools_called=["get_calendar_events"],
        )


# Backward-compatible legacy alias used by run_demo.py / existing callers
AGENT_NAME = "CalendarAgent"


class CalendarAgent:
    name = AGENT_NAME
    description = "Manages calendar events: viewing schedule, booking, rescheduling."

    def run(self, intent: str, params: dict, confirm_callback=None) -> str:
        if intent == "list_events":
            events = call_tool(AGENT_NAME, "get_calendar_events", date=params.get("date"))
            return self._format_events(events)

        if intent == "create_event":
            summary = f"I'll add '{params['title']}' on {params['start']} to {params['end']}."
            if confirm_callback and not confirm_callback(summary):
                return "Okay, I won't create that event."
            event = call_tool(
                AGENT_NAME,
                "create_calendar_event",
                title=params["title"],
                start=params["start"],
                end=params["end"],
                attendees=params.get("attendees", []),
            )
            return f"Done -- created '{event['title']}' (id: {event['id']})."

        if intent == "update_event":
            summary = f"I'll update the event '{params.get('event_id')}'."
            if confirm_callback and not confirm_callback(summary):
                return "Okay, I won't update that event."
            event = call_tool(
                AGENT_NAME,
                "update_calendar_event",
                event_id=params["event_id"],
                title=params.get("title"),
                start=params.get("start"),
                end=params.get("end"),
            )
            return f"Done -- updated event '{event['title']}' (id: {event['id']})."

        return f"CalendarAgent doesn't know how to handle intent '{intent}'."

    @staticmethod
    def _format_events(events: List[Dict[str, Any]]) -> str:
        if not events:
            return "No events found."
        lines = [f"- {e['title']} ({e['start']} to {e['end']})" for e in events]
        return "Here's what I found:\n" + "\n".join(lines)
