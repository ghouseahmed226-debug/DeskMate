---
name: meeting-assistant
description: >
  Intelligent meeting preparation and follow-up assistant.
  Use when the user wants to prepare for an upcoming meeting, generate
  an agenda, pull attendee profiles, review related calendar events,
  summarise prior discussion context from emails, or produce action-item
  summaries after a meeting. This is the "Agent Skill" demonstration
  showcasing multi-tool composition.
license: MIT
metadata:
  author: ghouseahmed226-debug
  version: "2.0.0"
  project: DeskMate AI
  category: productivity
allowed-tools: read_file list_directory
---

# Meeting Assistant Skill

## Overview

Delegates to the **MeetingAssistantAgent** and invokes the `meeting_prep`
Agent Skill (`skills/meeting_prep.py`). This is the primary demonstration
of **multi-tool composition** — a single high-level capability composed
from multiple lower-level tools.

## Composition Flow

```
User: "Prep for the Project Review meeting"
  │
  ├─► get_calendar_events("Project Review")   [CalendarAgent tools]
  ├─► get_contacts(attendee names)            [ContactCRM tools]
  ├─► get_emails(related threads)             [EmailAgent tools — read-only]
  └─► Compose: title + attendees + context → Prep Summary
```

All tool calls are logged separately to `audit_log.jsonl`, each with the
`MeetingAssistantAgent` agent name.

## Key Capabilities

| Capability | Description |
|---|---|
| **Meeting Prep** | Pulls calendar event + attendees + email context |
| **Agenda Builder** | Generates a structured agenda from context |
| **Attendee Profiles** | Enriches attendee list with contact data |
| **Action Item Tracker** | Records decisions and next steps post-meeting |
| **Follow-up Drafts** | Drafts follow-up emails for review (not sent) |

## Example Prompts

```
Prepare for the Project Review meeting
Give me a briefing before the Friday team sync
What do I need to know before meeting with Sarah Chen?
Summarise the last team meeting notes
Draft a follow-up for today's stand-up
```

## Related Skills

- `calendar-scheduling` — provides the meeting event data
- `contacts-crm` — provides attendee profiles
- `email-intelligence` — provides related email context
- `task-project-management` — captures action items as tasks
