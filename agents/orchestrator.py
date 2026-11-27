"""
orchestrator.py

DeskMateOrchestrator: Hierarchical multi-agent executive orchestrator.
Supports:
- 12 specialist agents + Daily Executive Briefing
- Provider-independent LLM routing + deterministic offline NLP fallback
- Optional Google ADK integration
- Multi-intent decomposition, relative dates, ambiguity clarification
- Conversation persistence, execution tracing, approval gates, anti-loop protection
- 100% backward compatibility via `Orchestrator = DeskMateOrchestrator` and `.handle(str)`
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from agents.adk_bridge import build_adk_agent_tree
from agents.base import AgentTaskInput, AgentTaskOutput, BaseSpecialistAgent, ExecutionStepTrace
from agents.business_intel_agent import BusinessIntelligenceAgent
from agents.calendar_agent import CalendarAgent, CalendarSchedulingAgent
from agents.communication_agent import CommunicationAgent
from agents.contacts_crm_agent import ContactCRM_Agent
from agents.document_agent import DocumentAssistantAgent
from agents.email_agent import EmailIntelligenceAgent, EmailTriageAgent
from agents.knowledge_agent import PersonalKnowledgeAgent
from agents.meeting_agent import MeetingAssistantAgent
from agents.research_agent import ResearchIntelligenceAgent
from agents.security_agent import SecurityComplianceAgent
from agents.task_agent import TaskCaptureAgent, TaskProjectManagementAgent
from agents.workflow_agent import WorkflowAutomationAgent
from db.models import Conversation, Message
from llm.adapter import ModelFactory
from nlp.parser import ParsedIntent, parse_clause_intent, split_multi_intent
from services.audit_service import record_audit_event
from services.briefing_service import generate_daily_briefing

AGENT_NAME = "DeskMateOrchestrator"


class OrchestratorTurnResult(BaseModel):
    trace_id: str
    conversation_id: Optional[str] = None
    response: str
    agents_invoked: List[str] = Field(default_factory=list)
    tools_called: List[str] = Field(default_factory=list)
    approvals_required: List[Dict[str, Any]] = Field(default_factory=list)
    needs_clarification: bool = False
    clarification_question: Optional[str] = None
    execution_trace: List[ExecutionStepTrace] = Field(default_factory=list)
    data: Dict[str, Any] = Field(default_factory=dict)


class DeskMateOrchestrator:
    """Main hierarchical orchestrator coordinating all 12 DeskMate specialists."""

    name = AGENT_NAME

    def __init__(
        self,
        auto_confirm: bool = False,
        confirm_callback: Optional[Callable[[str], bool]] = None,
    ) -> None:
        self.auto_confirm = auto_confirm
        self.confirm_callback = confirm_callback
        self.model = ModelFactory.create()
        self.specialists: Dict[str, BaseSpecialistAgent] = {
            "EmailIntelligenceAgent": EmailIntelligenceAgent(),
            "CalendarSchedulingAgent": CalendarSchedulingAgent(),
            "TaskProjectManagementAgent": TaskProjectManagementAgent(),
            "ContactCRM_Agent": ContactCRM_Agent(),
            "ResearchIntelligenceAgent": ResearchIntelligenceAgent(),
            "BusinessIntelligenceAgent": BusinessIntelligenceAgent(),
            "DocumentAssistantAgent": DocumentAssistantAgent(),
            "MeetingAssistantAgent": MeetingAssistantAgent(),
            "CommunicationAgent": CommunicationAgent(),
            "WorkflowAutomationAgent": WorkflowAutomationAgent(),
            "PersonalKnowledgeAgent": PersonalKnowledgeAgent(),
            "SecurityComplianceAgent": SecurityComplianceAgent(),
        }
        # Legacy single-script compatibility sub-agents
        self.calendar_agent = CalendarAgent()
        self.email_agent = EmailTriageAgent()
        self.task_agent = TaskCaptureAgent()
        self.adk_tree = build_adk_agent_tree(list(self.specialists.keys()))

    def _cli_confirm(self, summary: str) -> bool:
        if self.confirm_callback:
            return self.confirm_callback(summary)
        if self.auto_confirm:
            print(f"[auto-confirm] {summary} -> YES")
            return True
        answer = input(f"{summary} Proceed? [y/n]: ").strip().lower()
        return answer.startswith("y")

    def list_agent_specs(self) -> List[Dict[str, Any]]:
        specs = [
            {
                "name": self.name,
                "category": "orchestrator",
                "description": "Primary natural-language router, planner, approval gate, and synthesizer.",
                "allowed_tools": ["get_calendar_events", "get_emails", "get_tasks", "get_contacts", "discover_tools"],
            }
        ]
        for ag in self.specialists.values():
            specs.append(
                {
                    "name": ag.name,
                    "category": ag.category,
                    "description": ag.description,
                    "allowed_tools": ag.allowed_tools,
                    "instructions_preview": ag.load_instructions()[:260],
                }
            )
        return specs

    def process_turn(
        self,
        user_input: str,
        *,
        user_id: str,
        session: Optional[Session] = None,
        conversation_id: Optional[str] = None,
        timezone_name: str = "UTC",
        approval_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> OrchestratorTurnResult:
        """Executes a full natural-language turn with tracing, DB persistence, and safety gates."""
        trace_id = f"trc-{uuid.uuid4().hex[:12]}"
        clauses = split_multi_intent(user_input)
        trace: List[ExecutionStepTrace] = [
            ExecutionStepTrace(
                step="parse_request",
                agent_name=self.name,
                detail=f"Split request into {len(clauses)} clause(s) via {self.model.provider_name} adapter.",
            )
        ]

        # Ensure conversation tracking when DB session exists
        conv_id = conversation_id
        if session is not None:
            if not conv_id:
                conv = Conversation(user_id=user_id, title=user_input[:80])
                session.add(conv)
                session.flush()
                conv_id = conv.id
            session.add(
                Message(
                    conversation_id=conv_id,
                    role="user",
                    content=user_input,
                    trace_id=trace_id,
                )
            )
            session.flush()

        outputs: List[AgentTaskOutput] = []
        approvals_required: List[Dict[str, Any]] = []
        tools_called: List[str] = []
        agents_invoked: List[str] = []
        clarifications: List[str] = []
        aggregated_data: Dict[str, Any] = {}

        for clause in clauses:
            parsed: ParsedIntent = parse_clause_intent(
                clause,
                tz_name=timezone_name,
                allow_default_time_if_date_present=self.auto_confirm and session is None,
            )

            # Optional LLM enhancement when configured (never falls back to fabricating slots)
            if parsed.intent == "unknown" and self.model.provider_name != "offline":
                parsed = self._llm_reclassify(clause, parsed, timezone_name)

            trace.append(
                ExecutionStepTrace(
                    step="route_clause",
                    agent_name=parsed.agent,
                    detail=f"Clause '{clause}' -> intent='{parsed.intent}'",
                )
            )

            if parsed.needs_clarification and parsed.clarification_question:
                clarifications.append(parsed.clarification_question)
                outputs.append(
                    AgentTaskOutput(
                        agent_name=parsed.agent,
                        status="needs_clarification",
                        message=parsed.clarification_question,
                        clarification_question=parsed.clarification_question,
                    )
                )
                continue

            if parsed.agent == self.name and parsed.intent == "daily_briefing":
                if session is not None:
                    brief = generate_daily_briefing(session, user_id=user_id, tz_name=timezone_name)
                    record_audit_event(
                        session,
                        user_id=user_id,
                        trace_id=trace_id,
                        agent_name=self.name,
                        tool_name="daily_briefing",
                        params={"timezone": timezone_name},
                        outcome="ALLOWED",
                    )
                    agents_invoked.append(self.name)
                    aggregated_data["daily_briefing"] = brief
                    msg = self._format_briefing_markdown(brief)
                    outputs.append(AgentTaskOutput(agent_name=self.name, message=msg, data=brief))
                    trace.append(
                        ExecutionStepTrace(
                            step="execute_briefing",
                            agent_name=self.name,
                            detail="Compiled Daily Executive Briefing from authorized sources.",
                            tools_selected=["get_calendar_events", "get_emails", "get_tasks", "get_contacts"],
                        )
                    )
                    continue

            specialist = self.specialists.get(parsed.agent)
            if specialist is None:
                outputs.append(
                    AgentTaskOutput(
                        agent_name=self.name,
                        message=(
                            "I'm not sure which specialist handles that yet. I can help with email, calendar, tasks/projects, "
                            "contacts/CRM, research, business intelligence, uploaded documents, meeting prep, drafts, workflows, memory, or security audits."
                        ),
                    )
                )
                continue

            task_input = AgentTaskInput(
                user_id=user_id,
                trace_id=trace_id,
                intent=parsed.intent,
                params=parsed.params,
                raw_query=clause,
                timezone_name=timezone_name,
                depth=1,
                visited_agents=[self.name],
                approval_id=approval_id,
                auto_confirm=self.auto_confirm,
                idempotency_key=idempotency_key,
            )
            out = specialist.execute(task_input, session=session)
            outputs.append(out)
            agents_invoked.append(specialist.name)
            tools_called.extend(out.tools_called)
            if out.approval_request:
                approvals_required.append(out.approval_request)
            if out.data:
                aggregated_data[f"{specialist.name}:{parsed.intent}"] = out.data

            trace.append(
                ExecutionStepTrace(
                    step="specialist_result",
                    agent_name=specialist.name,
                    detail=f"status={out.status}",
                    status=out.status,
                    tools_selected=out.tools_called,
                )
            )

        final_text = "\n\n".join(o.message for o in outputs if o.message).strip()

        if session is not None and conv_id:
            session.add(
                Message(
                    conversation_id=conv_id,
                    role="assistant",
                    content=final_text,
                    agent_name=", ".join(dict.fromkeys(agents_invoked)) or self.name,
                    trace_id=trace_id,
                    metadata_json={
                        "tools_called": tools_called,
                        "approvals_required": approvals_required,
                        "trace": [t.model_dump() for t in trace],
                    },
                )
            )
            session.flush()

        return OrchestratorTurnResult(
            trace_id=trace_id,
            conversation_id=conv_id,
            response=final_text,
            agents_invoked=list(dict.fromkeys(agents_invoked)),
            tools_called=list(dict.fromkeys(tools_called)),
            approvals_required=approvals_required,
            needs_clarification=bool(clarifications),
            clarification_question=clarifications[0] if clarifications else None,
            execution_trace=trace,
            data=aggregated_data,
        )

    def handle(self, user_input: str) -> str:
        """Legacy synchronous CLI handle() used by run_demo.py and chat.py."""
        parsed = parse_clause_intent(user_input, allow_default_time_if_date_present=True)
        if parsed.needs_clarification and parsed.clarification_question:
            return parsed.clarification_question

        if parsed.agent == "MeetingAssistantAgent" and parsed.intent == "prepare_meeting":
            from skills.meeting_prep import prepare_meeting
            return prepare_meeting("Orchestrator", parsed.params.get("meeting_title", user_input))

        if parsed.agent == "CalendarSchedulingAgent":
            if parsed.intent == "create_event":
                start = parsed.params.get("start") or "2026-11-28T10:00:00"
                end = parsed.params.get("end") or "2026-11-28T11:00:00"
                return self.calendar_agent.run(
                    "create_event",
                    {"title": parsed.params.get("title", "New Event"), "start": start, "end": end},
                    confirm_callback=self._cli_confirm,
                )
            if parsed.intent in {"reschedule_event", "update_event"}:
                return self.calendar_agent.run(
                    "update_event",
                    {
                        "event_id": parsed.params.get("event_id") or "evt-001",
                        "title": parsed.params.get("title"),
                        "start": parsed.params.get("start"),
                        "end": parsed.params.get("end"),
                    },
                    confirm_callback=self._cli_confirm,
                )
            return self.calendar_agent.run("list_events", {"date": parsed.params.get("date")})

        if parsed.agent == "EmailIntelligenceAgent":
            if parsed.intent == "restricted_send_or_delete":
                return self.email_agent.run("send_email", {})
            return self.email_agent.run("triage_inbox", {"unread_only": True})

        if parsed.agent == "TaskProjectManagementAgent":
            if parsed.intent == "create_task":
                return self.task_agent.run(
                    "create_task",
                    {
                        "title": parsed.params.get("title", "New task"),
                        "source": "orchestrator",
                        "priority": parsed.params.get("priority", "Medium"),
                    },
                    confirm_callback=self._cli_confirm,
                )
            if parsed.intent in {"complete_task", "update_task"}:
                return self.task_agent.run(
                    "update_task",
                    {"task_id": parsed.params.get("task_id") or "task-001", "done": True},
                    confirm_callback=self._cli_confirm,
                )
            return self.task_agent.run("list_tasks", {})

        # For expanded specialists in CLI mode, run with an ephemeral DB session if possible
        try:
            from db.base import init_db, session_scope
            from db.seed import DEMO_USER_ID, seed_demo_data

            init_db()
            with session_scope() as session:
                seed_demo_data(session)
                res = self.process_turn(user_input, user_id=DEMO_USER_ID, session=session)
                return res.response
        except Exception:
            return (
                "I'm not sure which specialist handles that yet. Try asking about your calendar, "
                "inbox, tasks, contacts, briefing, documents, or security posture."
            )

    def _llm_reclassify(self, clause: str, fallback: ParsedIntent, tz_name: str) -> ParsedIntent:
        try:
            res = self.model.generate_json(
                system_prompt=(
                    "Classify the user request into one of the 12 DeskMate specialists: "
                    f"{list(self.specialists.keys())}. Return JSON with keys: agent, intent, params."
                ),
                user_prompt=f"Timezone={tz_name}. Request: {clause}",
            )
            if res.structured and res.structured.get("agent") in self.specialists:
                return ParsedIntent(
                    raw_clause=clause,
                    agent=res.structured["agent"],
                    intent=res.structured.get("intent", "default"),
                    params=res.structured.get("params") or {},
                    confidence=0.8,
                )
        except Exception:
            pass
        return fallback

    @staticmethod
    def _format_briefing_markdown(brief: Dict[str, Any]) -> str:
        lines = [f"### Daily Executive Briefing ({brief['timezone']})"]
        lines.append(f"- **Today's Calendar:** {len(brief['todays_calendar'])} event(s)")
        for ev in brief["todays_calendar"]:
            lines.append(f"  - {ev['title']} ({ev['start']})")
        lines.append(f"- **Priority Unread Emails:** {len(brief['important_emails'])}")
        for em in brief["important_emails"]:
            lines.append(f"  - [{em['category']}] {em['subject']} (from {em['sender']})")
        lines.append(f"- **Overdue Tasks:** {len(brief['overdue_tasks'])} | **Pending Tasks:** {len(brief['pending_tasks'])}")
        lines.append("- **Recommendations:**")
        for rec in brief["priority_recommendations"]:
            lines.append(f"  - {rec}")
        return "\n".join(lines)


# Backward-compatible class export
Orchestrator = DeskMateOrchestrator
