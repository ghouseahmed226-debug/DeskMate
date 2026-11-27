"""Daily Executive Briefing service aggregating authorized workspace sources."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from db.models import CalendarEvent, Contact, EmailMetadata, Task


def generate_daily_briefing(
    session: Session,
    *,
    user_id: str,
    tz_name: str = "UTC",
) -> Dict[str, Any]:
    """Generates a grounded Daily Executive Briefing. Never fabricates missing events/data."""
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = timezone.utc

    now = datetime.now(tz)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)
    prep_window_end = today_start + timedelta(days=2)

    events = (
        session.query(CalendarEvent)
        .filter(
            CalendarEvent.user_id == user_id,
            CalendarEvent.status != "cancelled",
        )
        .order_by(CalendarEvent.start_at.asc())
        .all()
    )

    todays_events = []
    meetings_needing_prep = []
    for e in events:
        start_aware = e.start_at if e.start_at.tzinfo else e.start_at.replace(tzinfo=timezone.utc)
        start_local = start_aware.astimezone(tz)
        item = {
            "id": e.id,
            "title": e.title,
            "start": start_local.isoformat(),
            "end": (e.end_at if e.end_at.tzinfo else e.end_at.replace(tzinfo=timezone.utc)).astimezone(tz).isoformat(),
            "attendees": e.attendees_json or [],
            "link": f"/calendar?event={e.id}",
        }
        if today_start <= start_local < today_end:
            todays_events.append(item)
        if now <= start_local <= prep_window_end and len(e.attendees_json or []) > 0:
            meetings_needing_prep.append(item)

    emails = (
        session.query(EmailMetadata)
        .filter(EmailMetadata.user_id == user_id, EmailMetadata.is_unread.is_(True))
        .order_by(EmailMetadata.received_at.desc())
        .all()
    )
    important_emails = [
        {
            "id": em.id,
            "sender": em.sender,
            "subject": em.subject,
            "category": em.category,
            "priority": em.priority,
            "deadline_detected": em.deadline_detected,
            "link": f"/inbox?email={em.id}",
        }
        for em in emails
        if em.category in {"Urgent", "Action Required", "Meetings", "Finance"} or em.priority in {"Critical", "High"}
    ]

    tasks = (
        session.query(Task)
        .filter(Task.user_id == user_id, Task.done.is_(False))
        .all()
    )
    overdue_tasks: List[Dict[str, Any]] = []
    upcoming_deadlines: List[Dict[str, Any]] = []
    pending_tasks: List[Dict[str, Any]] = []

    for t in tasks:
        task_item = {
            "id": t.id,
            "title": t.title,
            "priority": t.priority,
            "category": t.category,
            "due_date": t.due_date.isoformat() if t.due_date else None,
            "link": f"/tasks?task={t.id}",
        }
        pending_tasks.append(task_item)
        if t.due_date:
            due_aware = t.due_date if t.due_date.tzinfo else t.due_date.replace(tzinfo=timezone.utc)
            if due_aware < now:
                overdue_tasks.append(task_item)
            elif due_aware <= today_end + timedelta(days=2):
                upcoming_deadlines.append(task_item)

    contacts = (
        session.query(Contact)
        .filter(Contact.user_id == user_id, Contact.follow_up_at.is_not(None))
        .all()
    )
    follow_ups = [
        {
            "id": c.id,
            "name": c.name,
            "company": c.company,
            "follow_up_at": c.follow_up_at.isoformat() if c.follow_up_at else None,
            "link": f"/contacts?contact={c.id}",
        }
        for c in contacts
    ]

    recommendations: List[str] = []
    if overdue_tasks:
        recommendations.append(
            f"Address {len(overdue_tasks)} overdue task(s) first, starting with '{overdue_tasks[0]['title']}'."
        )
    if important_emails:
        recommendations.append(
            f"Review {len(important_emails)} priority unread email(s), led by '{important_emails[0]['subject']}'."
        )
    if meetings_needing_prep:
        recommendations.append(
            f"Run Meeting Prep for '{meetings_needing_prep[0]['title']}' with {len(meetings_needing_prep[0]['attendees'])} attendee(s)."
        )
    if not recommendations:
        recommendations.append("No urgent blockers found in your connected records. Use focus time for proactive planning.")

    return {
        "generated_at": now.isoformat(),
        "timezone": str(tz),
        "todays_calendar": todays_events,
        "important_emails": important_emails,
        "upcoming_deadlines": upcoming_deadlines,
        "pending_tasks": pending_tasks,
        "overdue_tasks": overdue_tasks,
        "meetings_requiring_prep": meetings_needing_prep,
        "important_follow_ups": follow_ups,
        "priority_recommendations": recommendations,
    }
