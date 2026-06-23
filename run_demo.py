"""
run_demo.py

Scripted demo for DeskMate. Runs a fixed sequence of prompts through the
Orchestrator and prints the conversation, then prints the audit log so the
security boundary is visible. This is what you'd screen-record for the
Kaggle capstone submission.

Usage:
    python run_demo.py
"""

import json
import os
from pathlib import Path

from agents.orchestrator import Orchestrator
from mcp_server.personal_data_mcp_server import (
    AUDIT_LOG_PATH,
    TOOL_REGISTRY,
    AGENT_PERMISSIONS,
    PermissionDeniedError,
)

DEMO_PROMPTS = [
    "What's on my calendar?",
    "Add a task to follow up with Sarah about the project review",
    "Schedule a meeting to prep for the Friday review",
    "Check my inbox",
    "Send an email to my boss about the budget",  # should be refused
]


def print_header(text):
    print("\n" + "=" * 70)
    print(text)
    print("=" * 70)


def reset_audit_log():
    if AUDIT_LOG_PATH.exists():
        AUDIT_LOG_PATH.unlink()


def run_conversation():
    print_header("DESKMATE DEMO -- Conversation")
    orchestrator = Orchestrator(auto_confirm=True)
    for prompt in DEMO_PROMPTS:
        print(f"\n> User: {prompt}")
        response = orchestrator.handle(prompt)
        print(f"DeskMate: {response}")


def demonstrate_security_boundary():
    print_header("SECURITY DEMO -- Direct permission violation attempt")
    print(
        "Simulating EmailTriageAgent attempting to call create_task,\n"
        "a tool it is NOT permitted to use (least-privilege enforcement):\n"
    )
    try:
        TOOL_REGISTRY["create_task"]("EmailTriageAgent", title="Should not be allowed")
    except PermissionDeniedError as e:
        print(f"BLOCKED as expected: {e}")


def print_permissions_table():
    print_header("AGENT PERMISSIONS (least privilege)")
    for agent, tools in AGENT_PERMISSIONS.items():
        print(f"{agent}:")
        for t in sorted(tools):
            print(f"  - {t}")


def print_audit_log():
    print_header("AUDIT LOG (audit_log.jsonl)")
    if not AUDIT_LOG_PATH.exists():
        print("(no audit log entries yet)")
        return
    with open(AUDIT_LOG_PATH) as f:
        for line in f:
            entry = json.loads(line)
            print(f"[{entry['outcome']}] {entry['timestamp']} | {entry['agent']} -> {entry['tool']} {entry['params']}")


if __name__ == "__main__":
    reset_audit_log()
    print_permissions_table()
    run_conversation()
    demonstrate_security_boundary()
    print_audit_log()
