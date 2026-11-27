"""SecurityComplianceAgent: audits permissions, anomalies, prompt-injection flags, and compliance."""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from agents.base import AgentTaskInput, AgentTaskOutput, BaseSpecialistAgent
from core.security import scan_prompt_injection
from services.audit_service import summarize_security_posture
from tools.registry import AGENT_ALLOWLISTS


class SecurityComplianceAgent(BaseSpecialistAgent):
    name = "SecurityComplianceAgent"
    category = "security"
    description = "Audits least-privilege permissions, anomaly alerts, prompt injections, and audit logs."
    instruction_filename = "security_compliance.md"

    def execute(self, task: AgentTaskInput, session: Optional[Session] = None) -> AgentTaskOutput:
        self.assert_no_loop(task)
        self.check_tool_permission(session, task, "read_audit_records", task.params)

        sample_text = task.params.get("text")
        if sample_text:
            flagged, hits = scan_prompt_injection(sample_text)
            self.log_tool_use(session, task, "scan_text_security", params={"flagged": flagged, "hits": hits})
            return AgentTaskOutput(
                agent_name=self.name,
                message=f"Security scan complete: suspicious={flagged}, matched_rules={hits}",
                data={"suspicious": flagged, "matched_rules": hits},
                tools_called=["scan_text_security"],
            )

        posture = (
            summarize_security_posture(session, task.user_id)
            if session is not None
            else {"total_audited_events": 0, "allowed_count": 0, "denied_count": 0, "flagged_suspicious_count": 0}
        )
        self.log_tool_use(session, task, "read_audit_records", params={"events": posture["total_audited_events"]})
        msg = (
            "### DeskMate Security & Compliance Summary\n"
            f"- **Audited Tool Events:** {posture['total_audited_events']} "
            f"(Allowed: {posture['allowed_count']}, Denied: {posture['denied_count']}, Flagged Suspicious: {posture['flagged_suspicious_count']})\n"
            f"- **Enforced Least-Privilege Profiles:** {len(AGENT_ALLOWLISTS)} scoped agent policies\n"
            "- **Defense-in-Depth:** Principal signature binding, PII-redacted logs, prompt-injection scanner, Fernet OAuth token encryption, confirmation gates."
        )
        return AgentTaskOutput(
            agent_name=self.name,
            message=msg,
            data={"posture": posture, "allowlist_count": len(AGENT_ALLOWLISTS)},
            tools_called=["read_audit_records", "get_permission_matrix"],
        )
