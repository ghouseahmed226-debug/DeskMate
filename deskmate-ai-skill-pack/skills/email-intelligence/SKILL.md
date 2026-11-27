---
name: email-intelligence
description: >
  Intelligent email triage, summarisation, and inbox management.
  Use when the user wants to check unread messages, summarise email threads,
  categorise emails by priority, identify action items from inbox, search
  email history, or draft response templates. Does NOT send emails — sending
  always requires explicit user confirmation via a connected Gmail integration.
license: MIT
metadata:
  author: ghouseahmed226-debug
  version: "2.0.0"
  project: DeskMate AI
  category: email
allowed-tools: read_file list_directory
---

# Email Intelligence Skill

## Overview

This skill delegates to the **EmailIntelligenceAgent**, one of DeskMate AI's
12 specialist agents. It reads and analyses the user's inbox from either the
mock JSON data store or a connected Gmail account (via OAuth), then produces
summaries, priority labels, and action-item extracts.

## Key Capabilities

| Capability | Description |
|---|---|
| **Inbox Summary** | Lists unread messages with sender, subject, and urgency label |
| **Thread Summary** | Summarises a full email thread into key points and decisions |
| **Priority Triage** | Labels messages as `urgent`, `important`, `normal`, or `fyi` |
| **Action Extraction** | Identifies to-dos mentioned in email body text |
| **Search** | Finds messages by keyword, sender, or date range |
| **Draft Template** | Produces a reply draft (never sent without explicit approval) |

## Security Constraints

- **Read-only by design** — this agent is in the `EmailIntelligenceAgent`
  allowlist for `get_emails` and `get_contacts` only.
- Writing (send, delete, label) requires a separate `CommunicationAgent`
  call with an explicit `approval_id`.
- All email content is wrapped in `wrap_untrusted_data()` before analysis
  to prevent prompt-injection from malicious email bodies.

## Example Prompts

```
Check my inbox
Summarise unread emails
Which emails need a response today?
Search for emails from Sarah Chen
What action items are in my inbox?
```

## Implementation Notes

The agent calls `mcp_server.call_tool("EmailIntelligenceAgent", "get_emails")`
which enforces the AGENT_PERMISSIONS allowlist in `personal_data_mcp_server.py`.
Every call is logged to `audit_log.jsonl` with agent name, tool, params
(PII-redacted), timestamp, and outcome.

## Related Skills

- `calendar-scheduling` — for scheduling follow-ups from email threads
- `task-project-management` — for creating tasks from email action items
- `meeting-assistant` — for meeting prep from email context
