"""
personal_data_mcp_server.py

Model Context Protocol (MCP) server & local adapter for DeskMate AI.
Preserves full backward compatibility for existing tests and run_demo.py while
upgrading:
- Thread-safe atomic JSON file writes (temporary file + os.replace + Lock)
- PII-redacted audit logging (audit_log.jsonl + DB AuditRecord hook)
- Expanded least-privilege AGENT_PERMISSIONS across all 12 specialist agents
- Sliding-window anomaly detection (FLAGGED_SUSPICIOUS)
- Proper MCP SDK @server.list_tools() / @server.call_tool() handlers plus
  built-in JSON-RPC 2.0 stdio transport fallback when the `mcp` SDK is absent.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.security import redact_pii
from tools.registry import (
    AGENT_ALLOWLISTS,
    PermissionDeniedError,
    ToolMetadata,
    get_tool_registry,
)

try:
    import mcp.server.stdio
    import mcp.types as mcp_types
    from mcp.server import Server

    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False
    Server = None  # type: ignore
    mcp_types = None  # type: ignore

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "mock_data"
AUDIT_LOG_PATH = BASE_DIR / "audit_log.jsonl"

CALENDAR_FILE = DATA_DIR / "calendar.json"
EMAILS_FILE = DATA_DIR / "emails.json"
CONTACTS_FILE = DATA_DIR / "contacts.json"
TASKS_FILE = DATA_DIR / "tasks.json"

# --- Anomaly Detection Configuration ---
ANOMALY_TIME_WINDOW_SEC = int(os.environ.get("ANOMALY_TIME_WINDOW_SEC", "60"))
ANOMALY_MAX_CALLS_PER_MIN = int(os.environ.get("ANOMALY_MAX_CALLS_PER_MIN", "10"))
ANOMALY_MAX_CONSECUTIVE_WRITES = int(os.environ.get("ANOMALY_MAX_CONSECUTIVE_WRITES", "3"))

call_history: Dict[str, deque] = {}
_FILE_LOCK = threading.RLock()
_HISTORY_LOCK = threading.Lock()

# Canonical permissions dictionary shared with tests & run_demo.py
AGENT_PERMISSIONS = AGENT_ALLOWLISTS


def _load(path: Path) -> Any:
    with _FILE_LOCK:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)


def _save(path: Path, data: Any) -> None:
    """Thread-safe atomic JSON write preventing partial/corrupted files."""
    with _FILE_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=path.stem, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as tmp_file:
                json.dump(data, tmp_file, indent=2, default=str)
                tmp_file.flush()
                os.fsync(tmp_file.fileno())
            os.replace(tmp_name, path)
        finally:
            if os.path.exists(tmp_name):
                try:
                    os.remove(tmp_name)
                except OSError:
                    pass


def _audit(
    agent_name: str,
    tool: str,
    params: dict,
    outcome: str,
    detail: str = "",
    *,
    user_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    approval_state: str = "not_required",
) -> Dict[str, Any]:
    """Appends a PII-redacted JSONL audit record."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "user_id": user_id,
        "trace_id": trace_id,
        "agent": agent_name,
        "tool": tool,
        "params": redact_pii(params or {}),
        "outcome": outcome,
        "approval_state": approval_state,
        "detail": redact_pii(detail) if detail else "",
    }
    with _FILE_LOCK:
        AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(AUDIT_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    return entry


def _check_anomaly(agent_name: str, tool_name: str) -> Optional[str]:
    now = time.time()
    is_write = tool_name.startswith(("create_", "update_", "mark_", "delete_", "cancel_", "send_"))

    with _HISTORY_LOCK:
        if agent_name not in call_history:
            call_history[agent_name] = deque()
        history = call_history[agent_name]

        while history and now - history[0][0] > ANOMALY_TIME_WINDOW_SEC:
            history.popleft()

        history.append((now, is_write))

        if len(history) > ANOMALY_MAX_CALLS_PER_MIN:
            detail = f"Exceeded {ANOMALY_MAX_CALLS_PER_MIN} calls per {ANOMALY_TIME_WINDOW_SEC}s"
            _audit(agent_name, tool_name, {}, "FLAGGED_SUSPICIOUS", detail)
            print(f"\n[WARNING] {agent_name} FLAGGED_SUSPICIOUS: exceeded call threshold.")
            return detail

        consecutive_writes = 0
        for _, write_flag in reversed(history):
            if write_flag:
                consecutive_writes += 1
            else:
                break

        if consecutive_writes > ANOMALY_MAX_CONSECUTIVE_WRITES:
            detail = f"Exceeded {ANOMALY_MAX_CONSECUTIVE_WRITES} consecutive write calls"
            _audit(agent_name, tool_name, {}, "FLAGGED_SUSPICIOUS", detail)
            print(f"\n[WARNING] {agent_name} FLAGGED_SUSPICIOUS: > {ANOMALY_MAX_CONSECUTIVE_WRITES} consecutive write calls.")
            return detail
    return None


def _check_permission(agent_name: str, tool_name: str) -> None:
    _check_anomaly(agent_name, tool_name)
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


def get_calendar_events(agent_name: str, date: Optional[str] = None) -> list:
    _check_permission(agent_name, "get_calendar_events")
    events = _load(CALENDAR_FILE)
    if date:
        events = [e for e in events if str(e.get("start", "")).startswith(date)]
    _audit(agent_name, "get_calendar_events", {"date": date}, "ALLOWED")
    return events


def create_calendar_event(
    agent_name: str,
    title: str,
    start: str,
    end: str,
    attendees: Optional[list] = None,
) -> dict:
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


def update_calendar_event(
    agent_name: str,
    event_id: str,
    title: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> dict:
    _check_permission(agent_name, "update_calendar_event")
    events = _load(CALENDAR_FILE)
    changes: Dict[str, Any] = {}
    if title is not None:
        changes["title"] = title
    if start is not None:
        changes["start"] = start
    if end is not None:
        changes["end"] = end

    for e in events:
        if e["id"] == event_id:
            e.update(changes)
            _save(CALENDAR_FILE, events)
            _audit(agent_name, "update_calendar_event", {"event_id": event_id, **changes}, "ALLOWED")
            return e
    raise ValueError(f"Event {event_id} not found")


def get_emails(agent_name: str, unread_only: bool = False) -> list:
    _check_permission(agent_name, "get_emails")
    emails = _load(EMAILS_FILE)
    if unread_only:
        emails = [e for e in emails if not e.get("read", False)]
    _audit(agent_name, "get_emails", {"unread_only": unread_only}, "ALLOWED")
    return emails


def mark_email_read(agent_name: str, email_id: str) -> dict:
    _check_permission(agent_name, "mark_email_read")
    emails = _load(EMAILS_FILE)
    for e in emails:
        if e["id"] == email_id:
            e["read"] = True
            _save(EMAILS_FILE, emails)
            _audit(agent_name, "mark_email_read", {"email_id": email_id}, "ALLOWED")
            return e
    raise ValueError(f"Email {email_id} not found")


def get_contacts(agent_name: str) -> list:
    _check_permission(agent_name, "get_contacts")
    contacts = _load(CONTACTS_FILE)
    _audit(agent_name, "get_contacts", {}, "ALLOWED")
    return contacts


def create_task(
    agent_name: str,
    title: str,
    due: Optional[str] = None,
    source: Optional[str] = None,
    priority: str = "Medium",
) -> dict:
    _check_permission(agent_name, "create_task")
    tasks = _load(TASKS_FILE)
    new_task = {
        "id": f"task-{len(tasks) + 1:03d}",
        "title": title,
        "due": due,
        "priority": priority,
        "source": source,
        "done": False,
        "created": datetime.now(timezone.utc).isoformat(),
    }
    tasks.append(new_task)
    _save(TASKS_FILE, tasks)
    _audit(agent_name, "create_task", {"title": title, "due": due, "priority": priority}, "ALLOWED")
    return new_task


def get_tasks(agent_name: str, include_done: bool = False) -> list:
    _check_permission(agent_name, "get_tasks")
    tasks = _load(TASKS_FILE)
    if not include_done:
        tasks = [t for t in tasks if not t.get("done", False)]
    _audit(agent_name, "get_tasks", {"include_done": include_done}, "ALLOWED")
    return tasks


def update_task(
    agent_name: str,
    task_id: str,
    done: Optional[bool] = None,
    title: Optional[str] = None,
) -> dict:
    _check_permission(agent_name, "update_task")
    tasks = _load(TASKS_FILE)
    changes: Dict[str, Any] = {}
    if done is not None:
        changes["done"] = done
    if title is not None:
        changes["title"] = title

    for t in tasks:
        if t["id"] == task_id:
            t.update(changes)
            _save(TASKS_FILE, tasks)
            _audit(agent_name, "update_task", {"task_id": task_id, **changes}, "ALLOWED")
            return t
    raise ValueError(f"Task {task_id} not found")


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

MCP_TOOL_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "get_calendar_events": {
        "description": "Retrieve calendar events, optionally filtered by ISO date prefix.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_name": {"type": "string"},
                "date": {"type": ["string", "null"]},
            },
            "required": ["agent_name"],
        },
    },
    "create_calendar_event": {
        "description": "Create a calendar event.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_name": {"type": "string"},
                "title": {"type": "string"},
                "start": {"type": "string"},
                "end": {"type": "string"},
                "attendees": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["agent_name", "title", "start", "end"],
        },
    },
    "update_calendar_event": {
        "description": "Update an existing calendar event by ID.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_name": {"type": "string"},
                "event_id": {"type": "string"},
                "title": {"type": ["string", "null"]},
                "start": {"type": ["string", "null"]},
                "end": {"type": ["string", "null"]},
            },
            "required": ["agent_name", "event_id"],
        },
    },
    "get_emails": {
        "description": "Read emails from the inbox.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_name": {"type": "string"},
                "unread_only": {"type": "boolean", "default": False},
            },
            "required": ["agent_name"],
        },
    },
    "mark_email_read": {
        "description": "Mark an email as read by ID.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_name": {"type": "string"},
                "email_id": {"type": "string"},
            },
            "required": ["agent_name", "email_id"],
        },
    },
    "get_contacts": {
        "description": "List contact directory entries.",
        "inputSchema": {
            "type": "object",
            "properties": {"agent_name": {"type": "string"}},
            "required": ["agent_name"],
        },
    },
    "create_task": {
        "description": "Create a to-do task.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_name": {"type": "string"},
                "title": {"type": "string"},
                "due": {"type": ["string", "null"]},
                "source": {"type": ["string", "null"]},
                "priority": {"type": "string"},
            },
            "required": ["agent_name", "title"],
        },
    },
    "get_tasks": {
        "description": "List pending or all tasks.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_name": {"type": "string"},
                "include_done": {"type": "boolean", "default": False},
            },
            "required": ["agent_name"],
        },
    },
    "update_task": {
        "description": "Update task completion status or title.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_name": {"type": "string"},
                "task_id": {"type": "string"},
                "done": {"type": ["boolean", "null"]},
                "title": {"type": ["string", "null"]},
            },
            "required": ["agent_name", "task_id"],
        },
    },
}


def call_tool(agent_name: str, tool_name: str, **kwargs):
    if tool_name not in TOOL_REGISTRY:
        raise ValueError(f"Unknown tool: {tool_name}")
    return TOOL_REGISTRY[tool_name](agent_name, **kwargs)


def handle_jsonrpc_message(raw_message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Built-in JSON-RPC 2.0 MCP handler usable over stdio even without external MCP SDK."""
    req_id = raw_message.get("id")
    method = raw_message.get("method")
    params = raw_message.get("params") or {}

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "personal-data-mcp", "version": "2.0.0"},
                "capabilities": {"tools": {}},
            },
        }
    if method == "tools/list":
        tools = [
            {
                "name": name,
                "description": spec["description"],
                "inputSchema": spec["inputSchema"],
            }
            for name, spec in MCP_TOOL_SCHEMAS.items()
        ]
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": tools}}

    if method == "tools/call":
        name = params.get("name", "")
        arguments = dict(params.get("arguments") or {})
        agent_name = arguments.pop("agent_name", "")
        if not agent_name:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32602, "message": "Missing required argument: agent_name"},
            }
        try:
            res = call_tool(agent_name, name, **arguments)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"content": [{"type": "text", "text": json.dumps(res, default=str)}]},
            }
        except PermissionDeniedError as exc:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32001, "message": str(exc)},
            }
        except Exception as exc:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32000, "message": str(exc)},
            }

    if req_id is None:
        return None
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def _create_official_mcp_server():
    server = Server("personal-data-mcp")

    @server.list_tools()
    async def list_tools():
        return [
            mcp_types.Tool(
                name=name,
                description=spec["description"],
                inputSchema=spec["inputSchema"],
            )
            for name, spec in MCP_TOOL_SCHEMAS.items()
        ]

    @server.call_tool()
    async def mcp_call_tool(name: str, arguments: dict):
        args = dict(arguments or {})
        agent_name = args.pop("agent_name", "")
        result = call_tool(agent_name, name, **args)
        return [mcp_types.TextContent(type="text", text=json.dumps(result, default=str))]

    return server


server = _create_official_mcp_server() if MCP_AVAILABLE else None


async def run_mcp_server():
    if MCP_AVAILABLE and server is not None:
        async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )
        return

    # Fallback stdio JSON-RPC 2.0 loop
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()
            continue
        resp = handle_jsonrpc_message(msg)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    asyncio.run(run_mcp_server())
