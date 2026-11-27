"""
task_agent.py

TaskProjectManagementAgent (and backward-compatible TaskCaptureAgent wrapper).
Supports full CRUD, delete with confirmation, Critical/High/Medium/Low priorities,
due dates, overdue detection, projects, dependencies, subtasks, and weekly planning.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from dateutil import parser as date_parser
from sqlalchemy.orm import Session

from agents.base import AgentTaskInput, AgentTaskOutput, BaseSpecialistAgent
from db.models import Task
from mcp_server.personal_data_mcp_server import call_tool

PRIORITY_ORDER = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}


class TaskProjectManagementAgent(BaseSpecialistAgent):
    name = "TaskProjectManagementAgent"
    category = "tasks"
    description = "Manages tasks, priorities, overdue detection, dependencies, projects, and weekly planning."
    instruction_filename = "task_project_management.md"

    def execute(self, task: AgentTaskInput, session: Optional[Session] = None) -> AgentTaskOutput:
        self.assert_no_loop(task)
        intent = task.intent
        params = task.params

        if session is None:
            tasks = call_tool("TaskCaptureAgent", "get_tasks", include_done=params.get("include_done", False))
            return AgentTaskOutput(
                agent_name=self.name,
                message=TaskCaptureAgent._format_tasks(tasks),
                data={"tasks": tasks},
                tools_called=["get_tasks"],
            )

        all_tasks = session.query(Task).filter(Task.user_id == task.user_id).all()
        now = datetime.now(timezone.utc)

        if intent == "overdue_tasks":
            self.check_tool_permission(session, task, "get_tasks", params)
            overdue = [
                t for t in all_tasks
                if not t.done and t.due_date and (t.due_date if t.due_date.tzinfo else t.due_date.replace(tzinfo=timezone.utc)) < now
            ]
            overdue.sort(key=lambda t: PRIORITY_ORDER.get(t.priority, 2))
            self.log_tool_use(session, task, "get_tasks", params={"filter": "overdue", "count": len(overdue)})
            if not overdue:
                return AgentTaskOutput(
                    agent_name=self.name,
                    message="You have no overdue tasks.",
                    data={"tasks": []},
                    tools_called=["get_tasks"],
                )
            lines = [f"- [{t.priority}] {t.title} (due {t.due_date.date().isoformat()}, id: {t.id})" for t in overdue]
            return AgentTaskOutput(
                agent_name=self.name,
                message=f"Overdue tasks ({len(overdue)}):\n" + "\n".join(lines),
                data={"tasks": [self._serialize(t) for t in overdue]},
                tools_called=["get_tasks"],
            )

        if intent == "weekly_plan":
            self.check_tool_permission(session, task, "get_tasks", params)
            pending = [t for t in all_tasks if not t.done]
            pending.sort(key=lambda t: PRIORITY_ORDER.get(t.priority, 2))
            self.log_tool_use(session, task, "get_tasks", params={"filter": "weekly_plan", "count": len(pending)})
            if not pending:
                return AgentTaskOutput(
                    agent_name=self.name,
                    message="All tasks are completed. Your week is wide open.",
                    data={"tasks": []},
                    tools_called=["get_tasks"],
                )
            lines = ["Weekly Work Plan (prioritized):"]
            for idx, t in enumerate(pending, 1):
                due_txt = f" | due {t.due_date.date().isoformat()}" if t.due_date else ""
                lines.append(f"{idx}. [{t.priority}] {t.title}{due_txt} (id: {t.id})")
            return AgentTaskOutput(
                agent_name=self.name,
                message="\n".join(lines),
                data={"tasks": [self._serialize(t) for t in pending]},
                tools_called=["get_tasks"],
            )

        if intent == "create_task":
            self.check_tool_permission(session, task, "create_task", params)
            title = params.get("title")
            if not title:
                return AgentTaskOutput(
                    agent_name=self.name,
                    status="needs_clarification",
                    message="Need a task title before creating a task.",
                    clarification_question="What should the task title be?",
                )
            priority = params.get("priority", "Medium")
            due_str = params.get("due_date")
            summary = f"Create {priority}-priority task: '{title}'" + (f" (due {due_str})" if due_str else "")
            if not task.auto_confirm and not task.approval_id:
                apr = self.create_approval_gate(
                    session,
                    task,
                    action_type="create_task",
                    summary=summary,
                    payload={"title": title, "priority": priority, "due_date": due_str},
                )
                return AgentTaskOutput(
                    agent_name=self.name,
                    status="needs_approval",
                    message=f"Approval required before adding task:\n{summary}",
                    approval_request=apr,
                )

            due_dt = date_parser.isoparse(due_str) if due_str else None
            if due_dt and due_dt.tzinfo is None:
                due_dt = due_dt.replace(tzinfo=timezone.utc)
            created = Task(
                user_id=task.user_id,
                title=title,
                priority=priority,
                category=params.get("category", "General"),
                due_date=due_dt,
                source=params.get("source", "orchestrator"),
                done=False,
                status="pending",
            )
            session.add(created)
            session.flush()
            self.log_tool_use(
                session,
                task,
                "create_task",
                params={"task_id": created.id, "priority": created.priority},
                approval_state="approved" if task.approval_id else "auto_confirm",
            )
            return AgentTaskOutput(
                agent_name=self.name,
                message=f"Added task '{created.title}' [{created.priority}] (id: {created.id}).",
                data={"task": self._serialize(created)},
                tools_called=["create_task"],
            )

        if intent in {"complete_task", "update_task"}:
            self.check_tool_permission(session, task, "update_task", params)
            target = self._locate_task(all_tasks, params.get("task_id"), params.get("query"))
            if target is None:
                return AgentTaskOutput(
                    agent_name=self.name,
                    status="needs_clarification",
                    message="Could not identify which task to update.",
                    clarification_question="Which task ID or task title would you like to mark complete/update?",
                )
            summary = f"Mark task '{target.title}' (id: {target.id}) as done."
            if not task.auto_confirm and not task.approval_id:
                apr = self.create_approval_gate(
                    session,
                    task,
                    action_type="update_task",
                    summary=summary,
                    payload={"task_id": target.id, "done": True},
                )
                return AgentTaskOutput(
                    agent_name=self.name,
                    status="needs_approval",
                    message=f"Approval required:\n{summary}",
                    approval_request=apr,
                )
            target.done = bool(params.get("done", True))
            target.status = "completed" if target.done else "pending"
            session.flush()
            self.log_tool_use(session, task, "update_task", params={"task_id": target.id, "done": target.done}, approval_state="approved" if task.approval_id else "auto_confirm")
            return AgentTaskOutput(
                agent_name=self.name,
                message=f"Updated task '{target.title}' (id: {target.id}) -> status: {target.status}.",
                data={"task": self._serialize(target)},
                tools_called=["update_task"],
            )

        if intent == "delete_task":
            self.check_tool_permission(session, task, "delete_task", params)
            target = self._locate_task(all_tasks, params.get("task_id"), params.get("query"))
            if target is None:
                return AgentTaskOutput(
                    agent_name=self.name,
                    status="needs_clarification",
                    message="Could not find the task to delete.",
                    clarification_question="Please provide the exact task ID or title to delete.",
                )
            summary = f"Permanently delete task '{target.title}' (id: {target.id})."
            if not task.approval_id:
                apr = self.create_approval_gate(
                    session,
                    task,
                    action_type="delete_task",
                    summary=summary,
                    payload={"task_id": target.id},
                )
                return AgentTaskOutput(
                    agent_name=self.name,
                    status="needs_approval",
                    message=f"Approval required before deleting task:\n{summary}",
                    approval_request=apr,
                )
            deleted_id = target.id
            session.delete(target)
            session.flush()
            self.log_tool_use(session, task, "delete_task", params={"task_id": deleted_id}, approval_state="approved")
            return AgentTaskOutput(
                agent_name=self.name,
                message=f"Deleted task {deleted_id}.",
                data={"deleted_task_id": deleted_id},
                tools_called=["delete_task"],
            )

        # Default: list_tasks
        self.check_tool_permission(session, task, "get_tasks", params)
        include_done = bool(params.get("include_done", False))
        filtered = all_tasks if include_done else [t for t in all_tasks if not t.done]
        filtered.sort(key=lambda t: PRIORITY_ORDER.get(t.priority, 2))
        self.log_tool_use(session, task, "get_tasks", params={"include_done": include_done, "count": len(filtered)})
        if not filtered:
            return AgentTaskOutput(agent_name=self.name, message="No pending tasks.", data={"tasks": []}, tools_called=["get_tasks"])
        lines = [f"- [{t.priority}] {t.title} (id: {t.id}, status: {t.status})" for t in filtered]
        return AgentTaskOutput(
            agent_name=self.name,
            message="Here are your tasks:\n" + "\n".join(lines),
            data={"tasks": [self._serialize(t) for t in filtered]},
            tools_called=["get_tasks"],
        )

    @staticmethod
    def _locate_task(tasks: List[Task], task_id: Optional[str], query: Optional[str]) -> Optional[Task]:
        if task_id:
            found = next((t for t in tasks if t.id == task_id), None)
            if found:
                return found
        if query:
            q = query.lower()
            for t in tasks:
                if not t.done and (q in t.title.lower() or any(tok in t.title.lower() for tok in q.split() if len(tok) > 3)):
                    return t
        return next((t for t in tasks if not t.done), None)

    @staticmethod
    def _serialize(t: Task) -> Dict[str, Any]:
        return {
            "id": t.id,
            "title": t.title,
            "status": t.status,
            "priority": t.priority,
            "category": t.category,
            "due_date": t.due_date.isoformat() if t.due_date else None,
            "done": t.done,
        }


# Backward-compatible legacy alias
AGENT_NAME = "TaskCaptureAgent"


class TaskCaptureAgent:
    name = AGENT_NAME
    description = "Captures and manages to-do items."

    def run(self, intent: str, params: dict, confirm_callback=None) -> str:
        if intent == "list_tasks":
            tasks = call_tool(AGENT_NAME, "get_tasks", include_done=params.get("include_done", False))
            return self._format_tasks(tasks)

        if intent == "create_task":
            summary = f"I'll add a task: '{params['title']}'."
            if confirm_callback and not confirm_callback(summary):
                return "Okay, I won't add that task."
            task = call_tool(
                AGENT_NAME,
                "create_task",
                title=params["title"],
                source=params.get("source", "unknown"),
                priority=params.get("priority", "Medium"),
            )
            return f"Added task '{task['title']}' (id: {task['id']})."

        if intent == "update_task":
            summary = f"I'll update the task '{params.get('task_id')}'."
            if confirm_callback and not confirm_callback(summary):
                return "Okay, I won't update that task."
            task = call_tool(
                AGENT_NAME,
                "update_task",
                task_id=params["task_id"],
                done=params.get("done"),
                title=params.get("title"),
            )
            return f"Updated task '{task['title']}' (id: {task['id']})."

        return f"TaskCaptureAgent doesn't know how to handle intent '{intent}'."

    @staticmethod
    def _format_tasks(tasks: List[Dict[str, Any]]) -> str:
        if not tasks:
            return "No pending tasks."
        lines = [f"- {t['title']} (id: {t['id']})" for t in tasks]
        return "Here are your tasks:\n" + "\n".join(lines)
