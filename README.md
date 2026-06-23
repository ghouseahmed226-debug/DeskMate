# DeskMate — A Concierge Multi-Agent System

**Track:** Concierge Agents
**Capstone:** AI Agents: Intensive Vibe Coding Capstone Project (Kaggle x Google)

DeskMate is a personal admin agent that manages your calendar, inbox, and
to-do list by routing requests through an orchestrator to scoped specialist
sub-agents — none of which has more data access than it strictly needs.

## The three concepts demonstrated

1. **Multi-agent system (Agent Development Kit style)**
   An `Orchestrator` agent classifies each request and delegates to one of
   three specialists: `CalendarAgent`, `EmailTriageAgent`, `TaskCaptureAgent`.
   See `agents/orchestrator.py` for the routing logic and a note on how to
   swap the keyword router for ADK's LLM-driven delegation.

2. **MCP server**
   All access to "personal data" (calendar, email, contacts, tasks) goes
   through a single custom MCP-style server,
   `mcp_server/personal_data_mcp_server.py`. No agent talks to the mock
   data files directly — every read/write is a tool call through this
   server, which is what makes the security layer below possible.

3. **Security features**
   - **Least-privilege allowlists:** `AGENT_PERMISSIONS` in the MCP server
     defines exactly which tools each agent may call. Calls outside that
     allowlist are rejected with a `PermissionDeniedError`, not just
     discouraged by a prompt.
   - **Structural restriction:** `EmailTriageAgent` is read-only by
     design — there is no `send_email` or `delete_email` tool on the
     server at all, so the restriction can't be prompt-injected around.
   - **Confirm-before-write:** any action that mutates data (creating a
     calendar event or task) is echoed back to the user for confirmation
     before it executes.
   - **Full audit trail:** every tool call, allowed or denied, is appended
     to `audit_log.jsonl` with a timestamp, the calling agent, the tool,
     and the parameters.

## Project structure

```
deskmate/
├── agents/
│   ├── orchestrator.py      # routes requests to specialists
│   ├── calendar_agent.py    # CalendarAgent
│   ├── email_agent.py       # EmailTriageAgent (read-only)
│   └── task_agent.py        # TaskCaptureAgent
├── mcp_server/
│   └── personal_data_mcp_server.py   # MCP-style server + permission allowlist + audit log
├── mock_data/
│   ├── calendar.json
│   ├── emails.json
│   ├── contacts.json
│   └── tasks.json
├── docs/
│   └── demo_script.md       # script for the submission video
├── run_demo.py               # scripted end-to-end demo, run this first
├── requirements.txt
└── audit_log.jsonl           # generated at runtime
```

## Running it

No external dependencies required:

```bash
cd deskmate
python3 run_demo.py
```

This will:
1. Print each agent's permission allowlist
2. Run a scripted conversation through the Orchestrator
3. Trigger a deliberate permission violation to show the security
   boundary working
4. Print the resulting audit log

## Design notes / what to highlight to judges

- **Why a custom MCP server instead of direct function calls?** Centralizing
  all data access behind one server means the security policy
  (`AGENT_PERMISSIONS`) lives in exactly one place and applies uniformly,
  regardless of which agent or future agent calls in. Adding a new agent
  later means adding one line to a dict, not auditing every tool
  implementation.
- **Why deny rather than just not expose tools?** Both — `EmailTriageAgent`
  shows the "structural" version (the dangerous tool doesn't exist), and
  the live demo also shows the "explicit allowlist" version (a tool exists
  on the server, but a specific agent is blocked from it), since real
  systems often need both layers.
- **Where this would go next:** swap the regex-based intent router in
  `Orchestrator.handle()` for real Google ADK LLM-driven delegation, wrap
  each MCP tool in the official `mcp` Python SDK's `@server.tool()`
  decorator and serve it over stdio/SSE, and replace the JSON mock data
  with real Google Calendar / Gmail API calls behind OAuth — the
  permission and audit layers would not need to change.

## Track fit: Concierge Agents

DeskMate is a personal assistant that simplifies planning, organization,
and task management while explicitly keeping user data secure through
least-privilege access and a full audit trail — directly addressing the
track's brief.
