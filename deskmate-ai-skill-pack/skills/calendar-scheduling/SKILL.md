---
name: calendar-scheduling
description: >
  Calendar management, event creation, and scheduling assistant.
  Use when the user wants to view upcoming events, schedule a meeting,
  create a calendar entry, reschedule an existing event, check availability,
  or get a weekly overview. Supports relative dates ("tomorrow", "next Monday")
  and attendee-aware scheduling.
license: MIT
metadata:
  author: ghouseahmed226-debug
  version: "2.0.0"
  project: DeskMate AI
  category: calendar
allowed-tools: read_file list_directory
---

# Calendar Scheduling Skill

## Overview

This skill delegates to the **CalendarSchedulingAgent**. It reads from and
writes to the calendar data store (mock JSON or Google Calendar via OAuth).
Relative date parsing ("next Friday at 3pm") is handled by `nlp/parser.py`.

## Key Capabilities

| Capability | Description |
|---|---|
| **View Events** | Lists calendar events for a date range |
| **Create Event** | Schedules a new event (requires confirmation) |
| **Update/Reschedule** | Moves or modifies an existing event (requires confirmation) |
| **Weekly Overview** | Produces a formatted week view |
| **Availability Check** | Checks whether a time slot is free |
| **Meeting Prep** | Combined with meeting-assistant skill for prep summaries |

## Security Constraints

- `create_calendar_event` and `update_calendar_event` are **write actions**
  — the orchestrator presents an approval summary before execution.
- CalendarAgent allowlist: `get_calendar_events`, `create_calendar_event`,
  `update_calendar_event`, `get_contacts`. Never includes email or task writes.
- All writes are logged to `audit_log.jsonl`.

## Example Prompts

```
What's on my calendar this week?
Schedule a team sync on Thursday at 2pm
Reschedule the Friday review to Monday at 10am
Book a 1-on-1 with Alice tomorrow at 11am
Am I free next Tuesday afternoon?
```

## Relative Date Support

The NLU parser (`nlp/parser.py`) resolves:
- `today`, `tomorrow`, `yesterday`
- `next Monday`, `next Friday`
- `in 3 days`, `in 2 weeks`
- `Thursday at 3pm`, `Friday morning`
- Explicit ISO dates: `2026-12-25`

## Related Skills

- `meeting-assistant` — full meeting prep from calendar + contacts
- `email-intelligence` — context from email threads for scheduling
- `contacts-crm` — attendee lookup by name
