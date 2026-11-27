# DeskMate AI — Skill Pack

## Overview

This skill pack provides **9 specialist agent skills** for the DeskMate AI
multi-agent personal assistant system. Each skill corresponds to one of the
12 DeskMate specialist agents and can be installed in any Antigravity-compatible
agent environment.

## Skills Included

| Skill | Category | Description |
|---|---|---|
| `email-intelligence` | Email | Inbox triage, summarisation, action extraction |
| `calendar-scheduling` | Calendar | View, create, update calendar events |
| `task-project-management` | Tasks | Create, track, prioritise tasks |
| `contacts-crm` | CRM | Contact lookup and relationship management |
| `meeting-assistant` | Productivity | Multi-tool meeting prep (Agent Skill demo) |
| `research-intelligence` | Research | Web research with source attribution |
| `document-assistant` | Documents | PDF/DOCX/CSV ingestion and Q&A |
| `daily-briefing` | Productivity | Personalised morning executive briefing |
| `security-audit` | Security | Audit log review and anomaly analysis |

## Installation

1. Install from the DeskMate AI plugin page
2. Or unzip and place in your `~/.gemini/config/skills/` directory
3. Each skill activates the corresponding DeskMate AI backend agent

## Quick Start

```bash
# Start the DeskMate AI backend
cd deskmate
uvicorn backend.main:app --reload --port 8000

# Or run the scripted demo
python run_demo.py

# Interactive chat
python chat.py
```

## Project Links

- GitHub: https://github.com/ghouseahmed226-debug/DeskMate
- Kaggle Competition: AI Agents Intensive Vibe Coding
- Author: @ghouseahmed226-debug
- License: MIT
