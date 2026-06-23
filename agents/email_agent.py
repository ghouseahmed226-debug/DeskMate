"""
email_agent.py

EmailTriageAgent: reads and summarizes/categorizes email. It can mark mail
as read, but it CANNOT send or delete anything -- those tools don't even
exist on the MCP server, so this restriction is structural, not just a
prompt instruction.
"""

from mcp_server.personal_data_mcp_server import call_tool

AGENT_NAME = "EmailTriageAgent"

CATEGORY_KEYWORDS = {
    "Action Needed": ["review", "sign-off", "need your", "approve", "asap"],
    "Newsletter": ["newsletter", "digest", "trends"],
    "Billing": ["invoice", "billing", "payment"],
    "Scheduling": ["sync", "meet", "schedule", "calendar"],
}


class EmailTriageAgent:
    name = AGENT_NAME
    description = "Reads and categorizes email; flags items that need action. Read-only -- cannot send or delete mail."

    def run(self, intent: str, params: dict, confirm_callback=None):
        if intent == "triage_inbox":
            emails = call_tool(AGENT_NAME, "get_emails", unread_only=params.get("unread_only", True))
            if not emails:
                return "Inbox is clear -- nothing unread."
            lines = []
            for e in emails:
                category = self._categorize(e)
                lines.append(f"- [{category}] {e['subject']} (from {e['from']})")
            return "Here's your triaged inbox:\n" + "\n".join(lines)

        elif intent == "mark_read":
            call_tool(AGENT_NAME, "mark_email_read", email_id=params["email_id"])
            return f"Marked {params['email_id']} as read."

        elif intent in ("send_email", "delete_email"):
            # Demonstration of the security boundary: this agent will refuse
            # even if asked, and the MCP server has no such tool to fall
            # back on anyway.
            return (
                "I'm not able to send or delete email -- EmailTriageAgent is "
                "read-only by design. You'd need to do that yourself."
            )

        else:
            return f"EmailTriageAgent doesn't know how to handle intent '{intent}'."

    @staticmethod
    def _categorize(email: dict) -> str:
        text = (email["subject"] + " " + email["body"]).lower()
        for category, keywords in CATEGORY_KEYWORDS.items():
            if any(kw in text for kw in keywords):
                return category
        return "General"
