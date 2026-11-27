"""
chat.py

Interactive CLI chat loop for DeskMate AI v2.0.
Passes user input to DeskMateOrchestrator with auto_confirm=False so write
actions prompt for real y/n confirmation.

Usage:
    python chat.py
    python chat.py --auto-confirm   # skip confirmation prompts (useful for testing)
    python chat.py --user-id <uid>  # run as a specific demo user
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Bootstrap DB (idempotent) and seed demo data before importing agents
# ---------------------------------------------------------------------------
from db.base import init_db, session_scope
from db.seed import DEMO_USER_ID, seed_demo_data

init_db()
with session_scope() as _s:
    seed_demo_data(_s)

from agents.orchestrator import DeskMateOrchestrator  # noqa: E402

BANNER = r"""
  ╔══════════════════════════════════════════════╗
  ║      DeskMate AI — Interactive Chat v2.0     ║
  ║  One Assistant. Every Workflow. Intelligent. ║
  ╚══════════════════════════════════════════════╝

  Commands:
    exit / quit  — quit the session
    /help        — show available intents
    /agents      — list all 12 specialist agents
    /audit       — print recent audit log entries
"""

HELP_TEXT = """
  Supported intents (examples):
    📧  "Check my inbox"  |  "Summarise unread emails"
    📅  "What's on my calendar today?"  |  "Schedule a meeting on Friday at 2pm"
    ✅  "Add a task: review Q3 report"  |  "Mark task 3 as done"
    👤  "Look up contact Sarah Chen"
    🔍  "Research: latest AI agent frameworks"
    📄  "Summarise the uploaded document"
    📊  "Daily briefing"  |  "Executive summary"
    🤝  "Prep for the Project Review meeting"
    🔒  "Security audit"  |  "Show anomaly flags"
"""


def _divider(w: int = 60) -> str:
    return "─" * w


def _print_audit(n: int = 10) -> None:
    from mcp_server.personal_data_mcp_server import AUDIT_LOG_PATH
    import json
    if not AUDIT_LOG_PATH.exists():
        print("  (no audit entries yet)")
        return
    with open(AUDIT_LOG_PATH, encoding="utf-8") as fh:
        lines = fh.readlines()[-n:]
    for raw in lines:
        try:
            e = json.loads(raw)
        except Exception:
            continue
        flag = {"SUCCESS": "✅", "DENIED": "🔒", "ERROR": "❌", "FLAGGED_SUSPICIOUS": "⚠️"}.get(
            e.get("outcome", ""), "•"
        )
        print(f"  {flag} {e.get('timestamp','')[:19]}  {e.get('agent','?')} → {e.get('tool','?')}  [{e.get('outcome','?')}]")


def _print_agents(orchestrator: DeskMateOrchestrator) -> None:
    specs = orchestrator.list_agent_specs()
    print(f"\n  {'Name':<35} {'Category':<25} Description")
    print(f"  {_divider(35)} {_divider(25)} {_divider(40)}")
    for s in specs:
        name = s["name"][:34]
        cat = s.get("category", "")[:24]
        desc = s.get("description", "")[:60]
        print(f"  {name:<35} {cat:<25} {desc}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="DeskMate AI interactive chat")
    parser.add_argument("--auto-confirm", action="store_true", help="Skip y/n prompts for write actions")
    parser.add_argument("--user-id", default=DEMO_USER_ID, help="User ID for DB-persisted conversation")
    args = parser.parse_args()

    print(BANNER)
    if args.auto_confirm:
        print("  [mode: auto-confirm — write actions will not prompt]\n")
    else:
        print("  [mode: interactive — write actions will ask for confirmation]\n")

    orchestrator = DeskMateOrchestrator(auto_confirm=args.auto_confirm)
    conversation_id: str | None = None

    while True:
        try:
            user_input = input("  You ▶  ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n\n  Goodbye! 👋\n")
            break

        if not user_input:
            continue

        lower = user_input.lower()

        if lower in ("exit", "quit", ":q"):
            print("\n  Goodbye! 👋\n")
            break

        if lower == "/help":
            print(HELP_TEXT)
            continue

        if lower == "/agents":
            _print_agents(orchestrator)
            continue

        if lower == "/audit":
            _print_audit()
            continue

        # Normal orchestration path
        try:
            with session_scope() as session:
                result = orchestrator.process_turn(
                    user_input,
                    user_id=args.user_id,
                    session=session,
                    conversation_id=conversation_id,
                )
                conversation_id = result.conversation_id

            # Pretty output
            print(f"\n  DeskMate ▶  {result.response}")
            if result.agents_invoked:
                print(f"  [routed to: {', '.join(result.agents_invoked)}]")
            if result.needs_clarification and result.clarification_question:
                print(f"  [clarification needed: {result.clarification_question}]")
            print()

        except KeyboardInterrupt:
            print("\n\n  Goodbye! 👋\n")
            break
        except Exception as exc:
            # Graceful degradation — fall back to simple handle()
            try:
                resp = orchestrator.handle(user_input)
                print(f"\n  DeskMate ▶  {resp}\n")
            except Exception as inner:
                print(f"\n  [error: {inner}]\n")


if __name__ == "__main__":
    main()
