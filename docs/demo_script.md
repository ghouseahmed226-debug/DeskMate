# DeskMate — Demo Script (2–3 min video)

Use this as the voiceover/screen-recording script. Run `python run_demo.py`
and narrate over the output, or run `python chat.py` to trigger each step manually for a live feel.

## 0. One-line pitch (10s)
"DeskMate is a personal concierge agent system: one orchestrator,
three specialist sub-agents, a composed skill, and a security layer that makes sure no
agent can touch data it doesn't need while automatically detecting anomalies."

## 1. Show the architecture (20s)
- Show the `docs/architecture.mmd` diagram.
- Point out: Orchestrator -> 3 specialists -> MCP server -> mock data.
- Point out `AGENT_PERMISSIONS` in `mcp_server/personal_data_mcp_server.py` — say out loud: "Each agent only gets the
  tools it actually needs. This is enforced in code."

## 2. Cross-agent routing & Agent Skills (40s)
Run these prompts through `run_demo.py` (or interactively) and narrate:
- "What's on my calendar?" -> CalendarAgent answers
- "Prepare for the Project Review meeting" -> *Orchestrator invokes the `meeting_prep` skill, pulling calendar and contact info to generate a summary.*
- "Add a task to follow up with Sarah about the project review" -> TaskCaptureAgent answers, after a confirm step
- "Mark task done" -> TaskCaptureAgent updates the task (CRUD update)

Narrate: "Notice the Orchestrator doesn't touch the raw data. It routes
to the specialist, or triggers a Composed Skill which securely batches MCP tool calls."

## 3. Security boundary in action (40s)
- Run the "Send an email to my boss about the budget" prompt -> EmailTriageAgent
  refuses; explain it's read-only by design.
- Run `demonstrate_security_boundary()` -> show
  EmailTriageAgent being blocked when attempting to call `create_task`.
- Narrate: "This is enforced at the MCP tool-access layer. The agent literally
  cannot call that function."

## 4. Anomaly Detection & Audit Log (20s)
- Run the anomaly detection script in `run_demo.py`.
- Open `audit_log.jsonl`.
- Narrate: "Every tool call is logged. If an agent suddenly bursts 10 reads a minute or 4 consecutive writes, our sliding-window Anomaly Detection flags it as `FLAGGED_SUSPICIOUS` in the audit log. You can always answer 'which agent touched what, and when.'"

## 5. Close (10s)
"Five concepts demonstrated: a multi-agent system built around an
orchestrator and ADK specialists, Agent Skills, a custom MCP server, least-privilege security with an audit trail, and real-time anomaly detection. Thanks for watching."
