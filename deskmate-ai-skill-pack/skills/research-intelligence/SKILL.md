---
name: research-intelligence
description: >
  Web research, information retrieval, and knowledge synthesis.
  Use when the user wants to research a topic, find recent news about a
  subject, compare technologies, look up background information, or get
  a synthesised briefing on any topic. Uses DuckDuckGo for live web search
  when available; falls back to honest offline disclosure when not.
license: MIT
metadata:
  author: ghouseahmed226-debug
  version: "2.0.0"
  project: DeskMate AI
  category: research
allowed-tools: read_file list_directory
---

# Research Intelligence Skill

## Overview

Delegates to the **ResearchIntelligenceAgent**. Performs web searches,
synthesises results, and returns a structured summary with sources.
Never fabricates citations — if offline, explicitly states it cannot
retrieve live information.

## Key Capabilities

| Capability | Description |
|---|---|
| **Web Search** | DuckDuckGo search with result ranking |
| **Topic Briefing** | 3-5 bullet summary on any subject |
| **Technology Comparison** | Side-by-side comparison of tools/frameworks |
| **News Summary** | Latest headlines on a topic |
| **Source Attribution** | All claims linked to source URLs |
| **Offline Disclosure** | Explicit message when live search unavailable |

## Example Prompts

```
Research: Google ADK multi-agent framework
What are the latest developments in AI agents?
Compare Anthropic Claude vs Google Gemini for coding tasks
Find recent news about LLM security vulnerabilities
What is the Model Context Protocol?
```

## Honesty Guarantees

This agent is instructed never to fabricate facts or URLs.
If `requests` or network access is unavailable, it returns:
> "I'm currently running in offline mode and cannot fetch live web
> results. I can share what I know up to my training cutoff, but
> please verify with a live search."

## Related Skills

- `document-assistant` — research from uploaded local documents
- `business-intelligence` — business-specific research and analytics
- `daily-briefing` — integrates research into morning briefing
