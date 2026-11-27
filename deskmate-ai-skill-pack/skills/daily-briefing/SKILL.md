---
name: daily-briefing
description: >
  Personalised daily executive briefing combining calendar, tasks, and inbox.
  Use when the user asks for their morning briefing, daily summary, executive
  overview, or "what's on today". Pulls data from calendar events, overdue
  tasks, and email inbox — never fabricates or invents data not in the user's
  actual records.
license: MIT
metadata:
  author: ghouseahmed226-debug
  version: "2.0.0"
  project: DeskMate AI
  category: productivity
allowed-tools: read_file list_directory
---

# Daily Executive Briefing Skill

## Overview

Delegates to the **DeskMateOrchestrator**'s `daily_briefing` intent,
which calls `services/briefing_service.py` → `generate_daily_briefing()`.
The briefing synthesises real data from the user's calendar, task list,
and inbox into a formatted morning summary.

## Briefing Structure

```
📅  TODAY'S SCHEDULE
   • 09:00 — Team Standup (Conference Room B)
   • 14:00 — Project Review (Zoom)

✅  OPEN TASKS (3)
   • [HIGH] Review Q3 budget report — DUE TODAY
   • [NORMAL] Follow up with Sarah Chen
   • [LOW] Update project documentation

📧  INBOX HIGHLIGHTS
   • 2 unread messages
   • 1 requires response (from: ceo@example.com — Budget Approval)

⚠️  SECURITY POSTURE
   • 0 anomalies detected in the last 24 hours
```

## Key Guarantees

- **No fabrication** — only data from authorised DB sources is included.
- **User isolation** — queries always filter by `user_id`.
- **Graceful degradation** — if a data source is unavailable, that
  section is omitted with an explanatory note.

## Example Prompts

```
Daily briefing
Give me my morning summary
What's on today?
Executive overview
What do I need to know to start my day?
```

## API Endpoint

```
GET /api/briefing     → {"briefing": "..."}
```

## Related Skills

- `calendar-scheduling` — detailed calendar view
- `task-project-management` — full task list
- `email-intelligence` — full inbox summary
