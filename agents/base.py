"""Shared base schema, loop guard, instruction loader, and tracing for all DeskMate agents."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from core.security import AgentPrincipal, IdempotencyGuard
from db.models import ApprovalRequest
from services.audit_service import record_audit_event
from tools.registry import AGENT_ALLOWLISTS, PermissionDeniedError

INSTRUCTIONS_DIR = Path(__file__).resolve().parent / "instructions"
_GLOBAL_IDEMPOTENCY = IdempotencyGuard(ttl_seconds=600)


class ExecutionStepTrace(BaseModel):
    step: str
    agent_name: str
    detail: str
    status: str = "ok"
    tools_selected: List[str] = Field(default_factory=list)


class AgentTaskInput(BaseModel):
    user_id: str
    trace_id: str
    intent: str
    params: Dict[str, Any] = Field(default_factory=dict)
    raw_query: str = ""
    timezone_name: str = "UTC"
    depth: int = 0
    visited_agents: List[str] = Field(default_factory=list)
    approval_id: Optional[str] = None
    auto_confirm: bool = False
    idempotency_key: Optional[str] = None


class AgentTaskOutput(BaseModel):
    agent_name: str
    status: str = "completed"  # completed | needs_approval | needs_clarification | denied | error
    message: str
    data: Dict[str, Any] = Field(default_factory=dict)
    tools_called: List[str] = Field(default_factory=list)
    approval_request: Optional[Dict[str, Any]] = None
    clarification_question: Optional[str] = None
    error_code: Optional[str] = None


class BaseSpecialistAgent:
    """Common secure execution contract implemented by all 12 DeskMate specialists."""

    name: str = "BaseSpecialistAgent"
    category: str = "general"
    description: str = ""
    instruction_filename: str = "orchestrator.md"
    max_delegation_depth: int = 4

    def __init__(self) -> None:
        self.allowed_tools = sorted(AGENT_ALLOWLISTS.get(self.name, set()))

    def load_instructions(self) -> str:
        path = INSTRUCTIONS_DIR / self.instruction_filename
        if path.exists():
            return path.read_text(encoding="utf-8")
        return f"# {self.name}\n{self.description}\nAllowed tools: {', '.join(self.allowed_tools)}"

    def issue_principal(self, task: AgentTaskInput) -> AgentPrincipal:
        return AgentPrincipal.issue(self.name, task.user_id, task.trace_id, depth=task.depth)

    def assert_no_loop(self, task: AgentTaskInput) -> None:
        if task.depth >= self.max_delegation_depth:
            raise RuntimeError(
                f"Delegation depth limit ({self.max_delegation_depth}) exceeded at {self.name}."
            )
        if self.name in task.visited_agents:
            raise RuntimeError(
                f"Circular delegation loop detected involving {self.name}: {task.visited_agents}"
            )

    def check_tool_permission(
        self,
        session: Optional[Session],
        task: AgentTaskInput,
        tool_name: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> None:
        allowed = AGENT_ALLOWLISTS.get(self.name, set())
        if tool_name not in allowed:
            record_audit_event(
                session,
                user_id=task.user_id,
                trace_id=task.trace_id,
                agent_name=self.name,
                tool_name=tool_name,
                params=params or {},
                outcome="DENIED",
                detail=f"{self.name} is not authorized to invoke {tool_name}",
            )
            raise PermissionDeniedError(
                f"DENIED: '{self.name}' is not authorized to invoke '{tool_name}'. Allowed: {sorted(allowed)}"
            )

    def log_tool_use(
        self,
        session: Optional[Session],
        task: AgentTaskInput,
        tool_name: str,
        params: Optional[Dict[str, Any]] = None,
        *,
        outcome: str = "ALLOWED",
        approval_state: str = "not_required",
        detail: str = "",
    ) -> None:
        record_audit_event(
            session,
            user_id=task.user_id,
            trace_id=task.trace_id,
            agent_name=self.name,
            tool_name=tool_name,
            params=params or {},
            outcome=outcome,
            approval_state=approval_state,
            detail=detail,
        )

    def create_approval_gate(
        self,
        session: Optional[Session],
        task: AgentTaskInput,
        *,
        action_type: str,
        summary: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Creates a persistent pending ApprovalRequest for high-impact/mutating actions."""
        if task.idempotency_key:
            seen, cached = _GLOBAL_IDEMPOTENCY.get_or_none(task.idempotency_key)
            if seen:
                return cached

        req_data: Dict[str, Any] = {
            "id": f"apr-{task.trace_id[-8:]}-{action_type}",
            "agent_name": self.name,
            "action_type": action_type,
            "summary": summary,
            "payload": payload,
            "status": "pending",
        }
        if session is not None:
            apr = ApprovalRequest(
                user_id=task.user_id,
                trace_id=task.trace_id,
                agent_name=self.name,
                action_type=action_type,
                summary=summary,
                payload_json=payload,
                status="pending",
                idempotency_key=task.idempotency_key,
            )
            session.add(apr)
            session.flush()
            req_data["id"] = apr.id

        self.log_tool_use(
            session,
            task,
            action_type,
            params=payload,
            outcome="PENDING_APPROVAL",
            approval_state="pending",
            detail=summary,
        )
        if task.idempotency_key:
            _GLOBAL_IDEMPOTENCY.record(task.idempotency_key, req_data)
        return req_data

    def execute(self, task: AgentTaskInput, session: Optional[Session] = None) -> AgentTaskOutput:
        raise NotImplementedError
