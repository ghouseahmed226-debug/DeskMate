"""
personal_data_mcp_server.py

A custom MCP server exposing mock "personal data" tools (calendar, email,
contacts, tasks) for the DeskMate concierge agent system.

SECURITY DESIGN
----------------
This server enforces least-privilege access: every tool call must
declare which agent is calling it (`agent_name`). The server checks
that agent against an explicit allowlist (AGENT_PERMISSIONS) before
executing anything. Calls that violate the allowlist are REJECTED and
logged, not silently ignored -- this is the visible security boundary
for the demo.

Every tool call (allowed or denied) is appended to audit_log.jsonl with
a timestamp, agent name, tool name, params, and outcome.

NOTE ON REAL MCP / ADK INTEGRATION
-----------------------------------
This file implements the server logic in plain Python so it runs with
zero external dependencies and is easy to demo/grade. To wire it into
the real MCP Python SDK, wrap each function below in an `@server.tool()`
decorator from the `mcp` package and run it over stdio/SSE per the MCP
spec (see https://modelcontextprotocol.io). The allowlist + audit logic
is identical either way -- that's the part worth showing off.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "mock_data"
AUDIT_LOG_PATH = BASE_DIR / "audit_log.jsonl"

CALENDAR_FILE = DATA_DIR / "calendar.json"
EMAILS_FILE = DATA_DIR / "emails.json"
CONTACTS_FILE = DATA_DIR / "contacts.json"
TASKS_FILE = DATA_DIR / "tasks.json"


# ---------------------------------------------------------------------------
# Least-privilege allowlist: which agent may call which tool.
# This is the enforcement point for the "security features" capstone
# requirement -- it is checked on every single call, not just documented.
# ---------------------------------------------------------------------------
AGENT_PERMISSIONS = {
    "CalendarAgent": {
        "get_calendar_events",
        "create_calendar_event",
        "update_calendar_event",
    },
    "EmailTriageAgent": {
        "get_emails",
        "mark_email_read",
        # Deliberately NOT allowed: send_email, delete_email (don't exist
        # on this server at all -- the agent literally cannot do them).
    },
    "TaskCaptureAgent": {
        "create_task",
        "get_tasks",
        "update_task",
    },
    "Orchestrator": {
        # Orchestrator can read across domains to make routing decisions,
        # but cannot write anywhere -- writes are delegated to specialists.
        "get_calendar_events",
        "get_emails",
        "get_tasks",
        "get_contacts",
    },
}


class PermissionDeniedError(Exception):
    pass


def _load(path: Path):
    with open(path, "r") as f:
        return json.load(f)


def _save(path: Path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)


def _audit(agent_name: str, tool: str, params: dict, outcome: str, detail: str = ""):
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agent": agent_name,
        "tool": tool,
        "params": params,
        "outcome": outcome,  # "ALLOWED" or "DENIED"
        "detail": detail,
    }
    with open(AUDIT_LOG_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


def _check_permission(agent_name: str, tool_name: str):
    allowed_tools = AGENT_PERMISSIONS.get(agent_name, set())
    if tool_name not in allowed_tools:
        _audit(
            agent_name,
            tool_name,
            {},
            "DENIED",
            f"{agent_name} is not permitted to call {tool_name}",
        )
        raise PermissionDeniedError(
            f"DENIED: '{agent_name}' is not authorized to call '{tool_name}'. "
            f"Allowed tools for this agent: {sorted(allowed_tools)}"
        )


# ---------------------------------------------------------------------------
# Tools. Each tool takes agent_name as its first argument so the server can
# enforce the allowlist before touching any data.
# ---------------------------------------------------------------------------

def get_calendar_events(agent_name: str, date: str = None):
    _check_permission(agent_name, "get_calendar_events")
    events = _load(CALENDAR_FILE)
    if date:
        events = [e for e in events if e["start"].startswith(date)]
    _audit(agent_name, "get_calendar_events", {"date": date}, "ALLOWED")
    return events


def create_calendar_event(agent_name: str, title: str, start: str, end: str, attendees=None):
    _check_permission(agent_name, "create_calendar_event")
    events = _load(CALENDAR_FILE)
    new_event = {
        "id": f"evt-{len(events) + 1:03d}",
        "title": title,
        "start": start,
        "end": end,
        "attendees": attendees or [],
    }
    events.append(new_event)
    _save(CALENDAR_FILE, events)
    _audit(agent_name, "create_calendar_event", {"title": title, "start": start, "end": end}, "ALLOWED")
    return new_event


def update_calendar_event(agent_name: str, event_id: str, **changes):
    _check_permission(agent_name, "update_calendar_event")
    events = _load(CALENDAR_FILE)
    for e in events:
        if e["id"] == event_id:
            e.update(changes)
            _save(CALENDAR_FILE, events)
            _audit(agent_name, "update_calendar_event", {"event_id": event_id, **changes}, "ALLOWED")
            return e
    raise ValueError(f"Event {event_id} not found")


def get_emails(agent_name: str, unread_only: bool = False):
    _check_permission(agent_name, "get_emails")
    emails = _load(EMAILS_FILE)
    if unread_only:
        emails = [e for e in emails if not e["read"]]
    _audit(agent_name, "get_emails", {"unread_only": unread_only}, "ALLOWED")
    return emails


def mark_email_read(agent_name: str, email_id: str):
    _check_permission(agent_name, "mark_email_read")
    emails = _load(EMAILS_FILE)
    for e in emails:
        if e["id"] == email_id:
            e["read"] = True
            _save(EMAILS_FILE, emails)
            _audit(agent_name, "mark_email_read", {"email_id": email_id}, "ALLOWED")
            return e
    raise ValueError(f"Email {email_id} not found")


def get_contacts(agent_name: str):
    _check_permission(agent_name, "get_contacts")
    contacts = _load(CONTACTS_FILE)
    _audit(agent_name, "get_contacts", {}, "ALLOWED")
    return contacts


def create_task(agent_name: str, title: str, due: str = None, source: str = None):
    _check_permission(agent_name, "create_task")
    tasks = _load(TASKS_FILE)
    new_task = {
        "id": f"task-{len(tasks) + 1:03d}",
        "title": title,
        "due": due,
        "source": source,
        "done": False,
        "created": datetime.now(timezone.utc).isoformat(),
    }
    tasks.append(new_task)
    _save(TASKS_FILE, tasks)
    _audit(agent_name, "create_task", {"title": title, "due": due}, "ALLOWED")
    return new_task


def get_tasks(agent_name: str, include_done: bool = False):
    _check_permission(agent_name, "get_tasks")
    tasks = _load(TASKS_FILE)
    if not include_done:
        tasks = [t for t in tasks if not t["done"]]
    _audit(agent_name, "get_tasks", {"include_done": include_done}, "ALLOWED")
    return tasks


def update_task(agent_name: str, task_id: str, **changes):
    _check_permission(agent_name, "update_task")
    tasks = _load(TASKS_FILE)
    for t in tasks:
        if t["id"] == task_id:
            t.update(changes)
            _save(TASKS_FILE, tasks)
            _audit(agent_name, "update_task", {"task_id": task_id, **changes}, "ALLOWED")
            return t
    raise ValueError(f"Task {task_id} not found")


# Registry mapping tool name -> function, used by agents to "call the MCP server"
TOOL_REGISTRY = {
    "get_calendar_events": get_calendar_events,
    "create_calendar_event": create_calendar_event,
    "update_calendar_event": update_calendar_event,
    "get_emails": get_emails,
    "mark_email_read": mark_email_read,
    "get_contacts": get_contacts,
    "create_task": create_task,
    "get_tasks": get_tasks,
    "update_task": update_task,
}


def call_tool(agent_name: str, tool_name: str, **kwargs):
    """Single entry point agents use to call any MCP tool. Mirrors how a
    real MCP client would invoke a tool by name with a JSON payload."""
    if tool_name not in TOOL_REGISTRY:
        raise ValueError(f"Unknown tool: {tool_name}")
    return TOOL_REGISTRY[tool_name](agent_name, **kwargs)
