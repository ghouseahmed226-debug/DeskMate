"""skills/meeting_prep.py

Agent Skill: Meeting Prep
Composes calendar retrieval and contact lookup to prepare a meeting brief.
"""

from __future__ import annotations

import re
from mcp_server.personal_data_mcp_server import _audit, call_tool


def prepare_meeting(agent_name: str, meeting_title: str) -> str:
    """Composes calendar retrieval and contact lookup to prepare a summary."""
    _audit(agent_name, "meeting_prep_skill", {"meeting_title": meeting_title}, "ALLOWED", "Skill invoked")

    events = call_tool(agent_name, "get_calendar_events")
    q = meeting_title.lower().strip()
    meeting = None

    for event in events:
        if q and q in event["title"].lower():
            meeting = event
            break

    if meeting is None and q:
        tokens = [w for w in re.findall(r"[a-z0-9]+", q) if w not in {"the", "for", "meeting", "about", "with"}]
        for event in events:
            if tokens and any(tok in event["title"].lower() for tok in tokens):
                meeting = event
                break

    if not meeting:
        return f"Could not find a meeting matching '{meeting_title}' on the calendar."

    contacts = call_tool(agent_name, "get_contacts")
    attendee_info = []
    for email in meeting.get("attendees", []):
        contact_match = next((c for c in contacts if c.get("email") == email), None)
        if contact_match:
            company = contact_match.get("company") or contact_match.get("role") or "No company specified"
            attendee_info.append(f"- {contact_match['name']} ({contact_match['email']}) - {company}")
        else:
            attendee_info.append(f"- {email} (Contact info not found)")

    return (
        f"Meeting Prep Summary: {meeting['title']}\n"
        f"Time: {meeting['start']} to {meeting['end']}\n"
        f"Attendees:\n" + ("\n".join(attendee_info) if attendee_info else "None")
    )
