"""BusinessIntelligenceAgent: SWOT, competitor briefs, and authorized workspace CRM enrichment."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from agents.base import AgentTaskInput, AgentTaskOutput, BaseSpecialistAgent
from db.models import Contact, DocumentRecord


class BusinessIntelligenceAgent(BaseSpecialistAgent):
    name = "BusinessIntelligenceAgent"
    category = "business_intelligence"
    description = "Company profiles, competitor analysis, SWOT frameworks, and privacy-compliant BI reports."
    instruction_filename = "business_intelligence.md"

    def execute(self, task: AgentTaskInput, session: Optional[Session] = None) -> AgentTaskOutput:
        self.assert_no_loop(task)
        subject = (task.params.get("subject") or task.params.get("query") or "").strip()
        if not subject:
            return AgentTaskOutput(
                agent_name=self.name,
                status="needs_clarification",
                message="Need a company or competitor name.",
                clarification_question="Which company or market competitor should I build a business report on?",
            )

        self.check_tool_permission(session, task, "analyze_company_data", task.params)

        crm_hits: List[Dict[str, Any]] = []
        doc_hits: List[str] = []
        if session is not None:
            contacts = session.query(Contact).filter(Contact.user_id == task.user_id).all()
            crm_hits = [
                {"name": c.name, "company": c.company, "title": c.job_title}
                for c in contacts
                if c.company and subject.lower() in c.company.lower()
            ]
            docs = session.query(DocumentRecord).filter(DocumentRecord.user_id == task.user_id).all()
            doc_hits = [
                d.filename
                for d in docs
                if subject.lower() in f"{d.filename} {d.extracted_summary}".lower()
            ]

        self.log_tool_use(
            session,
            task,
            "analyze_company_data",
            params={"subject": subject, "crm_matches": len(crm_hits), "doc_matches": len(doc_hits)},
        )

        crm_section = (
            "\n".join(f"- {h['name']} ({h['title']} @ {h['company']})" for h in crm_hits)
            if crm_hits
            else "No matching records in your authorized CRM."
        )
        doc_section = ", ".join(doc_hits) if doc_hits else "None"

        report = (
            f"### Business Intelligence Brief: {subject}\n"
            f"**1. Verified Internal Context (Authorized CRM & Docs):**\n"
            f"- CRM Contacts: {crm_section}\n"
            f"- Related Uploaded Docs: {doc_section}\n\n"
            f"**2. Structured SWOT Framework (Template for Verified Verification):**\n"
            f"- *Strengths / Weaknesses / Opportunities / Threats:* Connect live web search or upload market filings to populate verified figures rather than guessing revenue or headcount.\n\n"
            f"**3. Compliance Guardrail:** Follow applicable GDPR/CCPA and anti-spam rules before outbound lead outreach."
        )
        return AgentTaskOutput(
            agent_name=self.name,
            message=report,
            data={"subject": subject, "crm_matches": crm_hits, "doc_matches": doc_hits},
            tools_called=["analyze_company_data"],
        )
