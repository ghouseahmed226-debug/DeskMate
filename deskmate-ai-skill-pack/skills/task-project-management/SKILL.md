---
name: task-project-management
description: >
  Task creation, tracking, prioritisation, and project management.
  Use when the user wants to create a to-do item, view open tasks,
  mark a task as complete, update task priority or due date, organise
  tasks by project or tag, or get a summary of overdue items.
license: MIT
metadata:
  author: ghouseahmed226-debug
  version: "2.0.0"
  project: DeskMate AI
  category: tasks
allowed-tools: read_file list_directory
---

# Task & Project Management Skill

## Overview

This skill delegates to the **TaskProjectManagementAgent**. It performs full
CRUD on tasks stored in the mock JSON data store or a connected project
management integration (Notion, Linear, etc.).

## Key Capabilities

| Capability | Description |
|---|---|
| **Create Task** | Adds a new to-do with title, description, priority, due date |
| **Read Tasks** | Lists open, completed, or overdue tasks |
| **Update Task** | Changes status, priority, due date, or title |
| **Mark Done** | Sets `status: completed` on a task |
| **Prioritise** | Labels tasks as `high`, `normal`, or `low` priority |
| **Filter by Tag** | Shows tasks matching a tag or project name |
| **Overdue Summary** | Identifies tasks past their due date |

## Security Constraints

- `create_task` and `update_task` are **write actions** requiring approval.
- TaskCaptureAgent allowlist: `create_task`, `get_tasks`, `update_task`.
  It may NOT read emails or calendar events.
- Anomaly detection: >3 consecutive `create_task` calls are flagged
  as `FLAGGED_SUSPICIOUS` in the audit log.

## Example Prompts

```
Add a task: review Q3 budget report by Friday
Show all my open tasks
Mark the follow-up with Sarah task as done
What tasks are overdue?
Change the priority of task 3 to high
Show tasks tagged with "project-alpha"
```

## Related Skills

- `email-intelligence` — extract action items from emails into tasks
- `calendar-scheduling` — set calendar reminders for task deadlines
- `daily-briefing` — overdue task summary in the morning briefing
