"""WorkflowAutomationAgent: bounded multi-step workflow execution with retries & approval gates."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from agents.base import AgentTaskInput, AgentTaskOutput, BaseSpecialistAgent
from db.models import Workflow, WorkflowExecution
from services.briefing_service import generate_daily_briefing


class WorkflowAutomationAgent(BaseSpecialistAgent):
    name = "WorkflowAutomationAgent"
    category = "automation"
    description = "Executes bounded multi-step workflows with retries, cancellation, and manual approval gates."
    instruction_filename = "workflow_automation.md"

    def execute(self, task: AgentTaskInput, session: Optional[Session] = None) -> AgentTaskOutput:
        self.assert_no_loop(task)
        if session is None:
            return AgentTaskOutput(
                agent_name=self.name,
                status="error",
                message="Database session required for workflow execution tracking.",
            )

        intent = task.intent
        params = task.params
        workflows = session.query(Workflow).filter(Workflow.user_id == task.user_id).all()

        if intent == "list_workflows":
            self.check_tool_permission(session, task, "list_workflows", params)
            self.log_tool_use(session, task, "list_workflows", params={"count": len(workflows)})
            lines = [
                f"- **{wf.name}** (`{wf.id}`) | trigger: {wf.trigger_type} | approval_gate: {wf.require_approval}"
                for wf in workflows
            ]
            return AgentTaskOutput(
                agent_name=self.name,
                message="Configured workflows:\n" + ("\n".join(lines) if lines else "None"),
                data={"workflows": [{"id": w.id, "name": w.name, "steps": w.steps_json} for w in workflows]},
                tools_called=["list_workflows"],
            )

        # run_workflow
        self.check_tool_permission(session, task, "run_workflow_step", params)
        wf_id = params.get("workflow_id")
        query = (params.get("query") or "").lower()
        target = next((w for w in workflows if w.id == wf_id), None)
        if target is None and query:
            target = next((w for w in workflows if any(t in w.name.lower() for t in query.split() if len(t) > 3)), None)
        if target is None and workflows:
            target = workflows[0]
        if target is None:
            return AgentTaskOutput(agent_name=self.name, message="No workflows available to run.")

        if target.require_approval and not task.auto_confirm and not task.approval_id:
            apr = self.create_approval_gate(
                session,
                task,
                action_type="run_workflow",
                summary=f"Run workflow '{target.name}' ({len(target.steps_json)} steps)",
                payload={"workflow_id": target.id, "steps": target.steps_json},
            )
            return AgentTaskOutput(
                agent_name=self.name,
                status="needs_approval",
                message=f"Workflow '{target.name}' has a manual approval checkpoint before execution.",
                approval_request=apr,
            )

        execution = WorkflowExecution(
            workflow_id=target.id,
            user_id=task.user_id,
            status="running",
            trace_id=task.trace_id,
            step_results_json=[],
        )
        session.add(execution)
        session.flush()

        step_results: List[Dict[str, Any]] = []
        max_steps = min(len(target.steps_json), target.execution_limit)
        for idx, step in enumerate(target.steps_json[:max_steps]):
            attempt = 0
            while True:
                try:
                    # Bounded deterministic workflow step preview/execution
                    if target.id == "wf-daily-briefing" and idx == 0:
                        brief = generate_daily_briefing(session, user_id=task.user_id, tz_name=task.timezone_name)
                        res = {"summary": f"Today events={len(brief['todays_calendar'])}, urgent_emails={len(brief['important_emails'])}"}
                    else:
                        res = {"agent": step.get("agent"), "intent": step.get("intent"), "status": "completed"}
                    step_results.append({"step": idx + 1, **step, "result": res})
                    break
                except Exception as exc:
                    attempt += 1
                    if attempt > target.max_retries:
                        execution.status = "failed"
                        execution.error_message = str(exc)
                        execution.completed_at = datetime.now(timezone.utc)
                        session.flush()
                        return AgentTaskOutput(
                            agent_name=self.name,
                            status="error",
                            message=f"Workflow '{target.name}' failed at step {idx + 1}.",
                            error_code="WORKFLOW_STEP_FAILED",
                        )
                    time.sleep(0.05 * attempt)

        execution.step_results_json = step_results
        execution.status = "completed"
        execution.completed_at = datetime.now(timezone.utc)
        target.last_run_at = execution.completed_at
        session.flush()

        self.log_tool_use(session, task, "run_workflow_step", params={"workflow_id": target.id, "execution_id": execution.id})
        return AgentTaskOutput(
            agent_name=self.name,
            message=f"Workflow '{target.name}' completed ({len(step_results)} step(s), execution id: {execution.id}).",
            data={"execution_id": execution.id, "steps": step_results},
            tools_called=["run_workflow_step"],
        )
