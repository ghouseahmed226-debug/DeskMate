# DeskMate — Demo Script (2–3 min video)

Use this as the voiceover/screen-recording script. Run `python run_demo.py`
and narrate over the output, or trigger each step manually for a live feel.

## 0. One-line pitch (10s)
"DeskMate is a personal concierge agent system: one orchestrator,
three specialist sub-agents, and a security layer that makes sure no
agent can touch data it doesn't need."

## 1. Show the architecture (20s)
- Open `agents/orchestrator.py` and `mcp_server/personal_data_mcp_server.py`
  side by side.
- Point out: Orchestrator -> 3 specialists -> MCP server -> mock data.
- Point out `AGENT_PERMISSIONS` — say out loud: "Each agent only gets the
  tools it actually needs. This is enforced in code, not just prompted."

## 2. Cross-agent routing (40s)
Run these prompts through `run_demo.py` (or interactively) and narrate:
- "What's on my calendar?" -> CalendarAgent answers
- "Add a task to follow up with Sarah about the project review" -> TaskCaptureAgent
  answers, after a confirm step
- "Check my inbox" -> EmailTriageAgent triages and categorizes

Narrate: "Notice the Orchestrator never touches the data itself — it routes
to the specialist responsible for that domain, and that specialist is the
only one with write access there."

## 3. Security boundary in action (40s)
- Run the "Send an email to my boss about the budget" prompt -> EmailTriageAgent
  refuses; explain it's read-only by design, not just by accident.
- Run `demonstrate_security_boundary()` from `run_demo.py` -> show
  EmailTriageAgent being blocked by the MCP server when it tries to call
  `create_task`, a tool outside its allowlist.
- Narrate: "This isn't a refusal baked into a prompt that could be talked
  around — it's enforced at the tool-access layer. The agent literally
  cannot call that function."

## 4. Audit log (20s)
- Open `audit_log.jsonl` (or run `print_audit_log()`).
- Narrate: "Every tool call — allowed or denied — is logged with a
  timestamp, the calling agent, and the parameters. This is what makes
  the system auditable: you can always answer 'which agent touched what,
  and when.'"

## 5. Close (10s)
"Three concepts demonstrated: a multi-agent system built around an
orchestrator and specialists, a custom MCP server as the single
integration point for personal data, and least-privilege security with
a full audit trail. Thanks for watching."

---

## Bonus prompts to show range (optional, if time allows)
- "List my tasks"
- "What's on my calendar on July 3rd?"
- "Mark the dentist event done" (shows a graceful "doesn't understand" or
  extend update_calendar_event handling if you add it)
