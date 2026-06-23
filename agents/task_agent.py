"""
task_agent.py

TaskCaptureAgent: captures, lists, and updates personal to-dos. Scoped to
task tools only via the MCP server allowlist.
"""

from mcp_server.personal_data_mcp_server import call_tool

AGENT_NAME = "TaskCaptureAgent"


class TaskCaptureAgent:
    name = AGENT_NAME
    description = "Captures and tracks personal tasks/to-dos."

    def run(self, intent: str, params: dict, confirm_callback=None):
        if intent == "create_task":
            summary = f"I'll add a task: '{params['title']}'" + (
                f" due {params['due']}." if params.get("due") else "."
            )
            if confirm_callback and not confirm_callback(summary):
                return "Okay, I won't add that task."
            task = call_tool(
                AGENT_NAME,
                "create_task",
                title=params["title"],
                due=params.get("due"),
                source=params.get("source", "manual"),
            )
            return f"Added task '{task['title']}' (id: {task['id']})."

        elif intent == "list_tasks":
            tasks = call_tool(AGENT_NAME, "get_tasks", include_done=params.get("include_done", False))
            if not tasks:
                return "No open tasks. You're all caught up."
            lines = [f"- [{ 'x' if t['done'] else ' ' }] {t['title']}" for t in tasks]
            return "Your tasks:\n" + "\n".join(lines)

        elif intent == "complete_task":
            task = call_tool(AGENT_NAME, "update_task", task_id=params["task_id"], done=True)
            return f"Marked '{task['title']}' as done."

        else:
            return f"TaskCaptureAgent doesn't know how to handle intent '{intent}'."
