"""
email_agent.py

EmailIntelligenceAgent (and backward-compatible EmailTriageAgent wrapper).
Supports 10 categories, priority scoring, phishing/prompt-injection flagging,
deadline & action extraction, thread summarization, search, draft replies,
and strict read/draft safety (never sends without explicit approval & connected Gmail).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from agents.base import AgentTaskInput, AgentTaskOutput, BaseSpecialistAgent
from core.security import scan_prompt_injection, wrap_untrusted_data
from db.models import EmailMetadata
from integrations.gmail_adapter import GmailAdapter
from mcp_server.personal_data_mcp_server import call_tool

EMAIL_CATEGORIES = [
    "Urgent",
    "Action Required",
    "Work",
    "Personal",
    "Finance",
    "Billing",
    "Meetings",
    "Newsletter",
    "Promotions",
    "General",
]


def classify_email_metadata(subject: str, sender: str, body: str) -> Dict[str, Any]:
    """Deterministic email classifier extracting category, priority, phishing flags, deadlines, actions."""
    text = f"{subject} {body}".lower()
    sender_lower = sender.lower()
    flagged_inj, inj_patterns = scan_prompt_injection(f"{subject}\n{body}")
    suspicious_phish = bool(
        re.search(r"\b(wire\s+transfer|verify\s+your\s+account\s+immediately|urgent\s+password\s+reset|gift\s+card)\b", text)
    )
    is_suspicious = flagged_inj or suspicious_phish

    category = "General"
    priority = "Medium"
    if is_suspicious:
        category = "Urgent"
        priority = "Critical"
    elif re.search(r"\b(urgent|asap|sign-off|deadline|immediately|eod)\b", text):
        category = "Urgent"
        priority = "High"
    elif re.search(r"\b(can you|please\s+review|need\s+your|action\s+required|follow\s+up)\b", text):
        category = "Action Required"
        priority = "High"
    elif re.search(r"\b(invoice|payment|receipt|billing)\b", text):
        category = "Billing"
        priority = "Low"
    elif re.search(r"\b(budget|quarter|q[1-4]|forecast|expense)\b", text):
        category = "Finance"
        priority = "High"
    elif re.search(r"\b(meeting|sync|calendar|agenda|invite|review)\b", text):
        category = "Meetings"
        priority = "Medium"
    elif "newsletter" in sender_lower or re.search(r"\b(unsubscribe|digest|trends\s+to\s+watch)\b", text):
        category = "Newsletter"
        priority = "Low"
    elif re.search(r"\b(sale|discount|offer|promo|deal)\b", text):
        category = "Promotions"
        priority = "Low"
    elif any(d in sender_lower for d in ("example.com", "acme", "team")):
        category = "Work"

    deadline = None
    m_dl = re.search(r"\b(?:before|by)\s+([A-Za-z]+day|\d{4}-\d{2}-\d{2}|tomorrow|today|end\s+of\s+\w+)\b", body, re.I)
    if m_dl:
        deadline = m_dl.group(1)

    actions: List[str] = []
    for sentence in re.split(r"[.!?]+", body):
        s_clean = sentence.strip()
        if s_clean and re.search(r"\b(review|need|can you|please|sync|submit|sign-off|pay|check)\b", s_clean, re.I):
            actions.append(s_clean)

    return {
        "category": category,
        "priority": priority,
        "is_suspicious": is_suspicious,
        "suspicious_reasons": inj_patterns + (["phishing_heuristics"] if suspicious_phish else []),
        "deadline_detected": deadline,
        "action_items": actions[:5],
    }


class EmailIntelligenceAgent(BaseSpecialistAgent):
    name = "EmailIntelligenceAgent"
    category = "email"
    description = "Inbox reading, prioritization, spam/phishing detection, triage, and approval-gated draft replies."
    instruction_filename = "email_intelligence.md"

    def execute(self, task: AgentTaskInput, session: Optional[Session] = None) -> AgentTaskOutput:
        self.assert_no_loop(task)
        intent = task.intent
        params = task.params

        if intent == "restricted_send_or_delete":
            action = params.get("action", "send")
            self.log_tool_use(
                session,
                task,
                f"email_{action}_attempt",
                params={"action": action},
                outcome="DENIED",
                approval_state="blocked_policy",
                detail="Direct send/delete/forward requires draft + explicit approval + connected OAuth.",
            )
            return AgentTaskOutput(
                agent_name=self.name,
                status="denied",
                message=(
                    f"Blocked direct '{action}' action: DeskMate never automatically sends, forwards, or deletes emails. "
                    "Ask me to draft the reply first, then approve sending via your connected Gmail/Outlook integration."
                ),
                error_code="APPROVAL_REQUIRED_FOR_SEND",
            )

        if session is None:
            # Stateless fallback (used when called without DB session)
            emails = call_tool("EmailTriageAgent", "get_emails", unread_only=params.get("unread_only", True))
            return self._stateless_response(intent, emails, params)

        emails_q = session.query(EmailMetadata).filter(EmailMetadata.user_id == task.user_id)
        if params.get("unread_only") and intent in {"triage_inbox", "find_urgent"}:
            emails_q = emails_q.filter(EmailMetadata.is_unread.is_(True))
        emails = emails_q.order_by(EmailMetadata.received_at.desc()).all()

        if intent == "search_emails":
            self.check_tool_permission(session, task, "search_emails", params)
            query = (params.get("query") or "").lower()
            terms = [w for w in re.findall(r"[a-z0-9]{3,}", query) if w not in {"find", "search", "emails", "email", "from", "about"}]
            matched = [
                em for em in emails
                if not terms or any(t in f"{em.sender} {em.subject} {em.body_preview}".lower() for t in terms)
            ]
            self.log_tool_use(session, task, "search_emails", params={"hits": len(matched)})
            return self._format_email_list(matched, header=f"Found {len(matched)} matching email(s):")

        if intent == "find_urgent":
            self.check_tool_permission(session, task, "triage_emails", params)
            urgent = [
                em for em in emails
                if em.category in {"Urgent", "Action Required", "Finance", "Meetings"} or em.priority in {"Critical", "High"} or em.is_suspicious
            ]
            self.log_tool_use(session, task, "triage_emails", params={"urgent_count": len(urgent)})
            return self._format_email_list(urgent, header=f"Priority emails requiring attention ({len(urgent)}):")

        if intent == "draft_reply":
            self.check_tool_permission(session, task, "draft_email", params)
            target = None
            email_id = params.get("email_id")
            if email_id:
                target = next((e for e in emails if e.id == email_id), None)
            if target is None:
                q_lower = (params.get("query") or "").lower()
                target = next(
                    (e for e in emails if e.sender.split("@")[0].lower() in q_lower or any(w in e.subject.lower() for w in q_lower.split() if len(w) > 3)),
                    emails[0] if emails else None,
                )
            if target is None:
                return AgentTaskOutput(
                    agent_name=self.name,
                    status="needs_clarification",
                    message="I couldn't find an email to reply to.",
                    clarification_question="Which email sender or subject should I draft a reply for?",
                )
            draft_body = (
                f"Hi {target.sender.split('@')[0].title()},\n\n"
                f"Thanks for your note regarding \"{target.subject}\". "
                "I have reviewed the items and will follow up with final details shortly.\n\nBest regards,"
            )
            gmail = GmailAdapter()
            gmail_status = gmail.status_info(session, task.user_id)
            draft_info = {
                "email_id": target.id,
                "to": target.sender,
                "subject": f"Re: {target.subject}",
                "body": draft_body,
                "gmail_connected": gmail_status.connected,
                "delivery_status": "local_draft_only" if not gmail_status.connected else "ready_for_gmail_draft",
            }
            self.log_tool_use(session, task, "draft_email", params={"to": target.sender, "subject": draft_info["subject"]})
            return AgentTaskOutput(
                agent_name=self.name,
                status="completed",
                message=(
                    f"Draft reply prepared for **{target.sender}** (Subject: `{draft_info['subject']}`):\n\n"
                    f"```text\n{draft_body}\n```\n"
                    "Not sent — Gmail requires explicit approval and an authorized OAuth connection to send."
                ),
                data={"draft": draft_info},
                tools_called=["draft_email"],
            )

        # Default: triage_inbox / summarize_emails
        self.check_tool_permission(session, task, "get_emails", params)
        enriched = []
        for em in emails:
            analysis = classify_email_metadata(em.subject, em.sender, em.body_preview)
            em.category = analysis["category"]
            em.priority = analysis["priority"]
            em.is_suspicious = analysis["is_suspicious"]
            em.deadline_detected = analysis["deadline_detected"]
            em.action_items_json = analysis["action_items"]
            enriched.append(em)
        session.flush()
        self.log_tool_use(session, task, "get_emails", params={"count": len(enriched)})
        return self._format_email_list(enriched, header=f"Triaged {len(enriched)} email(s):")

    def _format_email_list(self, emails: List[EmailMetadata], header: str) -> AgentTaskOutput:
        if not emails:
            return AgentTaskOutput(
                agent_name=self.name,
                status="completed",
                message="Your inbox has no matching emails.",
                data={"emails": []},
                tools_called=["get_emails"],
            )
        lines = [header]
        serialized = []
        for em in emails:
            flag = " [SUSPICIOUS]" if em.is_suspicious else ""
            dl = f" | Deadline: {em.deadline_detected}" if em.deadline_detected else ""
            lines.append(
                f"- [{em.category} | {em.priority}{flag}] {em.subject} (from {em.sender}){dl}"
            )
            serialized.append(
                {
                    "id": em.id,
                    "sender": em.sender,
                    "subject": em.subject,
                    "category": em.category,
                    "priority": em.priority,
                    "unread": em.is_unread,
                    "suspicious": em.is_suspicious,
                    "deadline": em.deadline_detected,
                    "action_items": em.action_items_json or [],
                    "safe_preview": wrap_untrusted_data(f"email:{em.id}", em.body_preview[:240]),
                }
            )
        return AgentTaskOutput(
            agent_name=self.name,
            status="completed",
            message="\n".join(lines),
            data={"emails": serialized},
            tools_called=["get_emails"],
        )

    def _stateless_response(self, intent: str, emails: List[Dict[str, Any]], params: Dict[str, Any]) -> AgentTaskOutput:
        if not emails:
            return AgentTaskOutput(agent_name=self.name, message="Your inbox is clear!", data={"emails": []})
        lines = []
        for e in emails:
            info = classify_email_metadata(e["subject"], e.get("from", "Unknown"), e.get("body", ""))
            lines.append(f"- [{info['category']} | {info['priority']}] {e['subject']} (from {e.get('from', 'Unknown')})")
        return AgentTaskOutput(
            agent_name=self.name,
            message="Here's your triaged inbox:\n" + "\n".join(lines),
            data={"emails": emails},
            tools_called=["get_emails"],
        )


# Backward-compatible legacy alias used by run_demo.py / existing callers
AGENT_NAME = "EmailTriageAgent"


class EmailTriageAgent:
    name = AGENT_NAME
    description = "Triages inbox. Can read and summarize emails, but cannot send or delete."

    def __init__(self) -> None:
        self._specialist = EmailIntelligenceAgent()

    def run(self, intent: str, params: dict, confirm_callback=None) -> str:
        if intent in {"send_email", "restricted_send_or_delete"}:
            return (
                "I'm not able to send or delete email -- EmailTriageAgent is read-only by design. "
                "You'd need to approve sending via an authorized integration."
            )
        if intent == "triage_inbox":
            emails = call_tool(AGENT_NAME, "get_emails", unread_only=params.get("unread_only", True))
            return self._format_emails(emails)
        return f"EmailTriageAgent doesn't know how to handle intent '{intent}'."

    @staticmethod
    def _format_emails(emails: List[Dict[str, Any]]) -> str:
        if not emails:
            return "Your inbox is clear!"
        lines = []
        for e in emails:
            info = classify_email_metadata(e["subject"], e.get("from", "Unknown"), e.get("body", ""))
            lines.append(f"- [{info['category']}] {e['subject']} (from {e.get('from', 'Unknown')})")
        return "Here's your triaged inbox:\n" + "\n".join(lines)
