"""
orchestrator.py

Orchestrator: the single entry point a user talks to. It classifies
intent from natural language, routes to the correct specialist sub-agent,
and enforces a confirm-before-write step for any action that mutates data.

This is the "multi-agent system" piece of the capstone: the Orchestrator
itself holds no write permissions (see AGENT_PERMISSIONS in the MCP
server) -- it can only read across domains to decide routing, then
delegates the actual write to the specialist responsible for that domain.

In a real Google ADK deployment, this class maps to a top-level ADK Agent
configured with the three specialists as `sub_agents`, and intent
classification would be handled by the LLM via ADK's automatic
delegation rather than the keyword router below. The keyword router here
keeps the demo deterministic and dependency-free; swapping it for an
ADK LLM-driven router is a drop-in change (see comment at bottom).
"""

import re

from agents.calendar_agent import CalendarAgent
from agents.email_agent import EmailTriageAgent
from agents.task_agent import TaskCaptureAgent

AGENT_NAME = "Orchestrator"


class Orchestrator:
    def __init__(self, auto_confirm=False):
        self.calendar_agent = CalendarAgent()
        self.email_agent = EmailTriageAgent()
        self.task_agent = TaskCaptureAgent()
        self.auto_confirm = auto_confirm  # if True, skip interactive confirmation (for scripted demo)

    def _confirm(self, summary: str) -> bool:
        if self.auto_confirm:
            print(f"[auto-confirm] {summary} -> YES")
            return True
        answer = input(f"{summary} Proceed? [y/n]: ").strip().lower()
        return answer.startswith("y")

    def handle(self, user_input: str) -> str:
        """Classify the request and delegate to the right specialist."""
        text = user_input.lower()

        # --- Calendar intents ---
        if re.search(r"\b(schedule|calendar|event|meeting|appointment)\b", text):
            if re.search(r"\b(add|create|book|schedule)\b", text):
                # naive slot extraction for demo purposes
                title = self._extract_title(user_input)
                return self.calendar_agent.run(
                    "create_event",
                    {
                        "title": title or "New Event",
                        "start": "2026-07-04T10:00:00",
                        "end": "2026-07-04T11:00:00",
                    },
                    confirm_callback=self._confirm,
                )
            return self.calendar_agent.run("list_events", {"date": None})

        # --- Email intents ---
        if re.search(r"\b(email|inbox|mail)\b", text):
            if re.search(r"\b(send|delete|reply)\b", text):
                return self.email_agent.run("send_email", {})
            return self.email_agent.run("triage_inbox", {"unread_only": True})

        # --- Task intents ---
        if re.search(r"\b(task|todo|to-do|remind)\b", text):
            if re.search(r"\b(add|create|new)\b", text):
                title = self._extract_title(user_input)
                return self.task_agent.run(
                    "create_task",
                    {"title": title or "New task", "source": "orchestrator"},
                    confirm_callback=self._confirm,
                )
            return self.task_agent.run("list_tasks", {})

        return (
            "I'm not sure which specialist handles that yet. Try asking about "
            "your calendar, your inbox, or your tasks."
        )

    @staticmethod
    def _extract_title(user_input: str) -> str:
        # Very naive extraction: text after "to" or after the verb.
        match = re.search(r"(?:to|for)\s+(.+)", user_input, re.IGNORECASE)
        if match:
            return match.group(1).strip().rstrip(".")
        return user_input.strip()


# ---------------------------------------------------------------------------
# Real-ADK swap note:
#
#   from google.adk.agents import Agent
#
#   orchestrator = Agent(
#       name="Orchestrator",
#       model="gemini-2.0-flash",
#       instruction="Route requests to the right specialist sub-agent...",
#       sub_agents=[calendar_agent_adk, email_agent_adk, task_agent_adk],
#   )
#
# ADK's LLM-driven delegation replaces the regex router in `handle()`
# above. The permission/audit boundary stays in the MCP server either way.
# ---------------------------------------------------------------------------
