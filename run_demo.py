"""
run_demo.py

Fully-updated scripted demo for DeskMate AI v2.0.
Runs a fixed sequence of prompts through DeskMateOrchestrator, shows routing,
the security boundary denial, anomaly detection, and audit trail.
Designed to be screen-recorded for the Kaggle capstone submission.

Usage:
    python run_demo.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Bootstrap DB (idempotent) and seed demo data before importing agents
# ---------------------------------------------------------------------------
from db.base import init_db, session_scope
from db.seed import DEMO_USER_ID, seed_demo_data

init_db()
with session_scope() as _s:
    seed_demo_data(_s)

# ---------------------------------------------------------------------------
# Orchestrator and MCP server imports
# ---------------------------------------------------------------------------
from agents.orchestrator import DeskMateOrchestrator, Orchestrator  # noqa: E402
from mcp_server.personal_data_mcp_server import (  # noqa: E402
    AGENT_PERMISSIONS,
    AUDIT_LOG_PATH,
    TOOL_REGISTRY,
    PermissionDeniedError,
)

# ---------------------------------------------------------------------------
# Demo configuration
# ---------------------------------------------------------------------------
DEMO_PROMPTS = [
    # 1. Daily briefing – cross-agent read
    "Give me my daily briefing",
    # 2. Calendar read
    "What's on my calendar this week?",
    # 3. Email triage – read/summarise
    "Check my inbox and summarise unread messages",
    # 4. Task creation – triggers approval gate (auto-confirmed in demo)
    "Add a task to follow up with Sarah about the Q3 budget review",
    # 5. Meeting prep skill – multi-tool composition
    "Prepare for the Project Review meeting",
    # 6. Update a task (CRUD)
    "Mark the follow-up with Sarah task as done",
    # 7. Reschedule a calendar event (CRUD)
    "Reschedule the team sync to Thursday at 10 AM",
    # 8. Security boundary – email agent cannot send email (write blocked)
    "Send an email to my boss about the budget",  # will be blocked / explained
]

SECURITY_BOUNDARY_PROMPTS = [
    # EmailTriageAgent trying to call create_task (not in its allowlist)
    ("EmailTriageAgent", "create_task", {"title": "Injected task – should be blocked"}),
    # CalendarAgent trying to delete email – absolutely not allowed
    ("CalendarAgent", "get_emails", {}),  # this IS allowed – control
    ("CalendarAgent", "create_task", {"title": "Calendar writing tasks – blocked"}),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _divider(char: str = "=", width: int = 72) -> None:
    print(char * width)


def print_header(text: str, char: str = "=") -> None:
    print()
    _divider(char)
    print(f"  {text}")
    _divider(char)


def reset_audit_log() -> None:
    if AUDIT_LOG_PATH.exists():
        AUDIT_LOG_PATH.unlink()
    print(f"[reset] Audit log cleared: {AUDIT_LOG_PATH}")


def print_permissions_table() -> None:
    print_header("AGENT PERMISSIONS  (least-privilege allowlist)")
    for agent, tools in sorted(AGENT_PERMISSIONS.items()):
        label = f"  {agent}"
        print(f"{label}")
        for t in sorted(tools):
            print(f"      ✓  {t}")


def run_conversation() -> None:
    print_header("DESKMATE AI — Conversation Demo")
    orchestrator = DeskMateOrchestrator(auto_confirm=True)
    for prompt in DEMO_PROMPTS:
        print(f"\n{'─'*72}")
        print(f"  User ▶  {prompt}")
        print(f"{'─'*72}")
        try:
            response = orchestrator.handle(prompt)
        except Exception as exc:
            response = f"[orchestrator error: {exc}]"
        print(f"  DeskMate ▶  {response}")
        time.sleep(0.3)  # pacing for demo readability


def demonstrate_security_boundary() -> None:
    print_header("SECURITY DEMO — Direct Permission Violation Attempts", char="!")
    print(
        "  Simulating agents attempting to call tools outside their allowlist.\n"
        "  The MCP server's AGENT_PERMISSIONS check must block these.\n"
    )
    for agent_name, tool_name, params in SECURITY_BOUNDARY_PROMPTS:
        in_allowlist = tool_name in AGENT_PERMISSIONS.get(agent_name, set())
        print(f"  Agent: {agent_name}  →  tool: {tool_name}")
        print(f"  Allowed: {'YES' if in_allowlist else 'NO (expect BLOCKED)'}")
        try:
            fn = TOOL_REGISTRY.get(tool_name)
            if fn is None:
                print("  Result: [tool not in TOOL_REGISTRY – skipping]\n")
                continue
            result = fn(agent_name, **params)
            if in_allowlist:
                print(f"  Result: ✅ Permitted – {str(result)[:80]}\n")
            else:
                print(f"  Result: ⚠️  Unexpected success (check allowlist) – {str(result)[:80]}\n")
        except PermissionDeniedError as exc:
            print(f"  Result: 🔒 BLOCKED as expected → {exc}\n")
        except Exception as exc:
            print(f"  Result: [unexpected error: {exc}]\n")


def demonstrate_anomaly_detection() -> None:
    print_header("SECURITY DEMO — Anomaly Detection (Rate Limiting)", char="!")
    print("  Simulating a burst of 12 rapid calendar reads by CalendarAgent …")
    for i in range(12):
        try:
            fn = TOOL_REGISTRY.get("get_calendar_events")
            if fn:
                fn("CalendarAgent")
        except PermissionDeniedError:
            pass
        except Exception:
            pass

    print("\n  Simulating 4 consecutive create_task writes by TaskCaptureAgent …")
    for i in range(4):
        try:
            fn = TOOL_REGISTRY.get("create_task")
            if fn:
                fn("TaskCaptureAgent", title=f"Anomaly-test task {i + 1}")
        except PermissionDeniedError:
            pass
        except Exception:
            pass
    print("\n  → Check audit log for FLAGGED_SUSPICIOUS entries.")


def print_audit_log() -> None:
    print_header("AUDIT LOG  (audit_log.jsonl)")
    if not AUDIT_LOG_PATH.exists():
        print("  (no audit log entries yet)")
        return
    with open(AUDIT_LOG_PATH, encoding="utf-8") as fh:
        lines = fh.readlines()
    if not lines:
        print("  (audit log is empty)")
        return
    print(f"  Total entries: {len(lines)}\n")
    for raw in lines:
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError:
            print(f"  [malformed] {raw.strip()}")
            continue
        outcome = entry.get("outcome", "?")
        ts = entry.get("timestamp", "")[:19]
        agent = entry.get("agent", "?")
        tool = entry.get("tool", "?")
        params = entry.get("params", {})
        detail = entry.get("detail", "")

        flag = {
            "SUCCESS": "✅",
            "DENIED": "🔒",
            "ERROR": "❌",
            "FLAGGED_SUSPICIOUS": "⚠️",
        }.get(outcome, "•")

        print(f"  {flag} [{outcome:20s}] {ts}  {agent} → {tool}  {json.dumps(params)[:60]}")
        if detail:
            print(f"       Detail: {detail}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    reset_audit_log()
    print_permissions_table()
    run_conversation()
    demonstrate_security_boundary()
    demonstrate_anomaly_detection()
    print_audit_log()
    print()
    _divider()
    print("  Demo complete. See audit_log.jsonl for the full security trail.")
    _divider()
