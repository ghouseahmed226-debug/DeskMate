"""Idempotent demo database seeding from read-only mock_data fixtures."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from dateutil import parser as date_parser
from sqlalchemy.orm import Session

from core.config import get_settings
from core.security import hash_password
from db.models import (
    CalendarEvent,
    Contact,
    EmailMetadata,
    MemoryEntry,
    Project,
    Task,
    User,
    UserPreference,
    Workflow,
)

DEMO_USER_ID = "usr-demo"
DEMO_USER_EMAIL = "alex.morgan@deskmate.local"


def _parse_dt(raw: Optional[str], fallback: Optional[datetime] = None) -> Optional[datetime]:
    if not raw:
        return fallback
    dt = date_parser.isoparse(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def seed_demo_data(session: Session, data_dir: Optional[Path] = None) -> User:
    """Seeds demo workspace records for usr-demo without altering mock_data/*.json."""
    settings = get_settings()
    src = data_dir or settings.data_dir

    user = session.get(User, DEMO_USER_ID)
    if user is None:
        user = User(
            id=DEMO_USER_ID,
            email=DEMO_USER_EMAIL,
            full_name="Alex Morgan",
            hashed_password=hash_password("DeskMateDemo!2026"),
            role="admin",
            is_active=True,
        )
        session.add(user)
        session.flush()

    if session.query(UserPreference).filter_by(user_id=DEMO_USER_ID).first() is None:
        session.add(
            UserPreference(
                user_id=DEMO_USER_ID,
                timezone_name="UTC",
                working_hours_start="09:00",
                working_hours_end="17:30",
                preferred_llm_provider=settings.llm_provider,
                daily_briefing_time="08:30",
                preferences_json={"briefing_style": "concise", "confirm_all_writes": True},
            )
        )

    if session.query(Project).filter_by(user_id=DEMO_USER_ID).count() == 0:
        p1 = Project(
            id="proj-001",
            user_id=DEMO_USER_ID,
            name="Q4 Launch",
            description="Cross-functional product launch deliverables and stakeholder reviews.",
            status="active",
            due_date=datetime.now(timezone.utc) + timedelta(days=14),
        )
        p2 = Project(
            id="proj-002",
            user_id=DEMO_USER_ID,
            name="Budget",
            description="Q3/Q4 department budget review and marketing sign-off.",
            status="active",
            due_date=datetime.now(timezone.utc) + timedelta(days=2),
        )
        session.add_all([p1, p2])
        session.flush()

    cal_file = src / "calendar.json"
    if session.query(CalendarEvent).filter_by(user_id=DEMO_USER_ID).count() == 0 and cal_file.exists():
        events = json.loads(cal_file.read_text(encoding="utf-8"))
        now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        for idx, e in enumerate(events):
            # Shift fixture events around current week so daily briefing is immediately useful,
            # while keeping titles/attendees accurate.
            start = _parse_dt(e.get("start"), now + timedelta(days=idx))
            end = _parse_dt(e.get("end"), start + timedelta(hours=1))
            if idx == 0:
                start = now.replace(hour=10)
                end = now.replace(hour=10, minute=30)
            elif idx == 1:
                start = (now + timedelta(days=1)).replace(hour=14)
                end = (now + timedelta(days=1)).replace(hour=15)
            session.add(
                CalendarEvent(
                    id=f"demo-{e['id']}",
                    user_id=DEMO_USER_ID,
                    title=e["title"],
                    start_at=start,
                    end_at=end,
                    timezone_name="UTC",
                    attendees_json=e.get("attendees", []),
                    agenda=f"Agenda for {e['title']}",
                    status="confirmed",
                )
            )

    contacts_file = src / "contacts.json"
    if session.query(Contact).filter_by(user_id=DEMO_USER_ID).count() == 0 and contacts_file.exists():
        contacts = json.loads(contacts_file.read_text(encoding="utf-8"))
        for c in contacts:
            session.add(
                Contact(
                    id=f"demo-{c['id']}",
                    user_id=DEMO_USER_ID,
                    name=c["name"],
                    email=c.get("email"),
                    phone=c.get("phone"),
                    company=c.get("company"),
                    job_title="Stakeholder" if c.get("company") == "Acme Corp" else "Partner",
                    category="Work" if c.get("company") == "Acme Corp" else "External",
                    notes=f"Seeded contact from {c.get('company', 'Directory')}",
                )
            )

    emails_file = src / "emails.json"
    if session.query(EmailMetadata).filter_by(user_id=DEMO_USER_ID).count() == 0 and emails_file.exists():
        emails = json.loads(emails_file.read_text(encoding="utf-8"))
        for em in emails:
            subj = em["subject"]
            body = em.get("body", "")
            category = "General"
            priority = "Medium"
            action_items = []
            if "budget" in subj.lower() or "sign-off" in body.lower():
                category = "Urgent"
                priority = "High"
                action_items = ["Review marketing spend line", "Reply with sign-off before Friday"]
            elif "project review" in subj.lower():
                category = "Meetings"
                priority = "High"
                action_items = ["Sync 15 minutes with Sarah before Friday review"]
            elif "invoice" in subj.lower():
                category = "Billing"
                priority = "Low"
            elif "trends" in subj.lower():
                category = "Newsletter"
                priority = "Low"

            session.add(
                EmailMetadata(
                    id=f"demo-{em['id']}",
                    user_id=DEMO_USER_ID,
                    sender=em["from"],
                    recipients_json=[DEMO_USER_EMAIL],
                    subject=subj,
                    snippet=body[:140],
                    body_preview=body,
                    category=category,
                    priority=priority,
                    is_unread=not bool(em.get("read", False)),
                    is_suspicious=False,
                    action_items_json=action_items,
                    received_at=_parse_dt(em.get("received"), datetime.now(timezone.utc)),
                )
            )

    tasks_file = src / "tasks.json"
    if session.query(Task).filter_by(user_id=DEMO_USER_ID).count() == 0 and tasks_file.exists():
        tasks = json.loads(tasks_file.read_text(encoding="utf-8"))
        for idx, t in enumerate(tasks):
            due = _parse_dt(t.get("due"))
            if idx == 1 and not t.get("done"):
                # Keep one realistically overdue task for executive briefing demo
                due = datetime.now(timezone.utc) - timedelta(days=1)
            session.add(
                Task(
                    id=f"demo-{t['id']}",
                    user_id=DEMO_USER_ID,
                    project_id="proj-001" if t.get("project") == "Q4 Launch" else "proj-002",
                    title=t["title"],
                    status="completed" if t.get("done") else "pending",
                    priority=t.get("priority", "Medium"),
                    category=t.get("category", "Work"),
                    tags_json=t.get("tags", []),
                    due_date=due,
                    source=t.get("source"),
                    done=bool(t.get("done", False)),
                )
            )

    if session.query(Workflow).filter_by(user_id=DEMO_USER_ID).count() == 0:
        session.add_all(
            [
                Workflow(
                    id="wf-daily-briefing",
                    user_id=DEMO_USER_ID,
                    name="Daily Executive Briefing",
                    description="Summarizes today's calendar, urgent unread emails, and overdue tasks.",
                    trigger_type="scheduled",
                    schedule_cron="0 8 * * 1-5",
                    require_approval=False,
                    steps_json=[
                        {"agent": "CalendarSchedulingAgent", "intent": "daily_summary"},
                        {"agent": "EmailIntelligenceAgent", "intent": "triage_inbox"},
                        {"agent": "TaskProjectManagementAgent", "intent": "overdue_tasks"},
                    ],
                ),
                Workflow(
                    id="wf-email-to-task",
                    user_id=DEMO_USER_ID,
                    name="Important Email to Action Plan",
                    description="Analyzes urgent emails, extracts deadlines, proposes tasks for approval, and drafts a reply.",
                    trigger_type="event",
                    require_approval=True,
                    steps_json=[
                        {"agent": "EmailIntelligenceAgent", "intent": "find_urgent"},
                        {"agent": "TaskProjectManagementAgent", "intent": "propose_from_emails"},
                        {"agent": "CommunicationAgent", "intent": "draft_reply"},
                    ],
                ),
            ]
        )

    if session.query(MemoryEntry).filter_by(user_id=DEMO_USER_ID).count() == 0:
        session.add(
            MemoryEntry(
                id="mem-001",
                user_id=DEMO_USER_ID,
                category="working_preference",
                key="meeting_buffer",
                content="Prefer 15-minute buffers between meetings and morning focus blocks before 10:00 UTC.",
                approved=True,
                retention_days=180,
            )
        )

    session.commit()
    return user
