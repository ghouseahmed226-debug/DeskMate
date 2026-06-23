"""
calendar_agent.py

CalendarAgent: handles all scheduling-related requests. Built in the style
of a Google ADK agent -- swap `SimpleAgent` for `google.adk.Agent` and the
`run()` method for an ADK-style `handle()` callback to run this on real ADK.

PERMISSIONS: this agent is restricted (via the MCP server's allowlist) to
calendar tools only. It cannot read emails or contacts.
"""

from mcp_server.personal_data_mcp_server import call_tool

AGENT_NAME = "CalendarAgent"


class CalendarAgent:
    name = AGENT_NAME
    description = "Manages calendar events: viewing schedule, booking, rescheduling."

    def run(self, intent: str, params: dict, confirm_callback=None):
        if intent == "list_events":
            events = call_tool(AGENT_NAME, "get_calendar_events", date=params.get("date"))
            return self._format_events(events)

        elif intent == "create_event":
            summary = (
                f"I'll add '{params['title']}' on {params['start']} "
                f"to {params['end']}."
            )
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

        else:
            return f"CalendarAgent doesn't know how to handle intent '{intent}'."

    @staticmethod
    def _format_events(events):
        if not events:
            return "No events found."
        lines = [f"- {e['title']} ({e['start']} to {e['end']})" for e in events]
        return "Here's what I found:\n" + "\n".join(lines)
