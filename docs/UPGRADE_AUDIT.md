# DeskMate Repository Upgrade Audit (`docs/UPGRADE_AUDIT.md`)

**Audit Date:** 2026-11-27
**Audited Commit / State:** Local workspace on branch `main` (base commit `3eaa871` + partial uncommitted refactor across 10 files and 4 untracked directories/files).
**Target Product:** DeskMate AI — Multi-Agent Personal AI Operating System & AgenSi-Ready Skill Pack.

---

## 1. Repository Inventory & Existing Functionality

At audit time, the repository (`deskmate/`) contains 23 project files:
- `agents/orchestrator.py`, `agents/calendar_agent.py`, `agents/email_agent.py`, `agents/task_agent.py`
- `mcp_server/personal_data_mcp_server.py`
- `skills/meeting_prep.py`
- `mock_data/{calendar,contacts,emails,tasks}.json`
- `api/index.py`, `vercel.json`
- `run_demo.py`, `chat.py`
- `tests/test_security.py`
- `docs/architecture.mmd`, `docs/demo_script.md`, `README.md`, `requirements.txt`, `.gitignore`, `audit_log.jsonl`

**Working baseline functionality:**
- `run_demo.py` executes end-to-end with zero external dependencies using in-memory/regex orchestration, per-agent allowlist checks (`AGENT_PERMISSIONS`), confirm-before-write callbacks, a basic `meeting_prep` helper, and sliding-window call-rate anomaly logging (`FLAGGED_SUSPICIOUS`).
- `EmailTriageAgent` has no write tools for sending or deleting email.

---

## 2. Detailed Findings Across Required Audit Dimensions

### 2.1 Incomplete Functionality
1. **Only 3 specialist agents exist:** Calendar, Email, and Task agents exist; 9 planned specialists (Contacts/CRM, Research, Business Intelligence, Document/Knowledge, Meeting Intelligence, Communication, Workflow Automation, Personal Knowledge/Memory, Security/Compliance) are absent.
2. **Broken ADK wrapper (`agents/orchestrator.py`, `agents/*_agent.py`):** The `USE_ADK=true` branch subclasses `google.adk.agents.Agent` and overrides `.run(intent, params, confirm_callback)` while calling `self.agent.run(user_input)` on the orchestrator, which does not match Google ADK's `Runner`/`FunctionTool` invocation contract and omits confirmation callbacks. Neither `google-adk` nor `mcp` is installed in the current environment (`ModuleNotFoundError`).
3. **Broken MCP SDK integration (`mcp_server/personal_data_mcp_server.py`):** Decorates functions with `@server.tool()` on `mcp.server.Server`, whereas the official low-level `mcp.server.Server` uses `@server.list_tools()` / `@server.call_tool()` (only `FastMCP` defines `@mcp.tool()`). Tool schemas are not exported via MCP discovery.
4. **Incomplete CRUD & Calendar/Email/Task features:** Missing event deletion/cancellation, conflict detection, slot finding, timezones, recurring events, priority levels (`Critical..Low`), overdue tracking, subtasks/dependencies, email categorization/prioritization/drafting, CRM notes, and document ingestion.
5. **No Web Dashboard / Frontend:** Only CLI scripts (`run_demo.py`, `chat.py`) and a read-only Vercel demo endpoint exist.
6. **No AgenSi Skill Pack:** `skills/meeting_prep.py` is a Python helper coupled to the local `mcp_server`, not an AgenSi-compatible `SKILL.md` marketplace ZIP pack.

### 2.2 Security Vulnerabilities (CRITICAL)
1. **Unauthenticated Agent Identity Spoofing:** Every tool accepts `agent_name: str` as an untrusted caller-supplied argument (`call_tool("CalendarAgent", ...)`). Any compromised agent or caller can claim to be `"CalendarAgent"` or `"Orchestrator"` and bypass `AGENT_PERMISSIONS`.
2. **No User Authentication / Authorization:** There are no users, passwords, JWTs, API keys, CSRF checks, or multi-tenant isolation boundaries.
3. **Raw PII in Audit Logs (`audit_log.jsonl`):** `_audit()` logs raw `params` (task titles, email IDs, meeting subjects) in plaintext without PII redaction or secret scrubbing.
4. **No Prompt-Injection Protection:** Email subjects/bodies and future external web/document content are formatted and handled without untrusted-data framing or injection detection.
5. **Exposed Internal Output on Vercel (`api/index.py`):** Anonymous `GET` requests run the entire demo including security logs and print raw exception strings (`print(f"Error: {e}")`) directly in HTTP responses.
6. **Missing OAuth Token Security:** No OAuth 2.0 flow, no encrypted token storage, no token refresh/revocation, and no secrets-hygiene enforcement.

### 2.3 Hardcoded Values
1. **Hardcoded Dates & IDs (`agents/orchestrator.py`):** Event creation hardcodes `"start": "2026-07-04T10:00:00"` and `"end": "2026-07-04T11:00:00"`. Updates hardcode `"event_id": "evt-001"` and `"task_id": "task-001"`.
2. **Hardcoded Models & Providers:** Both `orchestrator.py` and the sub-agents hardcode `"gemini-2.0-flash"` directly with deprecated `google.generativeai` instead of a provider-independent model adapter.
3. **Schema Mismatch in Skill (`skills/meeting_prep.py`):** Looks up `contact.get('role')`, whereas `mock_data/contacts.json` stores `company` and `phone` (never `role`).

### 2.4 Incorrect Routing & Naive Natural-Language Extraction
1. **Regex Collisions (`agents/orchestrator.py`):**
   - `"Schedule a meeting to prep for the Friday review"` triggers the `meeting_prep` skill instead of creating/scheduling a meeting because `\b(prepare|prep)\b` + `\b(meeting|review)\b` runs before calendar creation.
   - `"Reschedule the Friday review"` falls through to `"I'm not sure which specialist handles that yet"` because `\b(schedule|...)\b` has a leading word boundary that fails to match `reschedule`.
2. **Naive `_extract_title`:** Regex `(?:to|for|about|prep)\s+(.+)` fails cleanly on queries like `"Prepare for the Project Review meeting"` (extracts `"the Project Review meeting"`, failing exact substring match against `"Project Review with Sarah"`).
3. **Missing NLU Features:** No relative date parsing (`tomorrow`, `next Monday`), no multi-intent handling, no ambiguity detection/clarification questions, no conversational memory, and no duplicate-action/idempotency check.

### 2.5 Missing Integrations & Dependencies
1. **No Real Connectors:** Gmail, Google Calendar, Google Contacts, Google Drive, Slack, Notion, GitHub, and Microsoft Outlook/Calendar integrations are absent.
2. **Empty `requirements.txt`:** All packages in `requirements.txt` are commented out, making reproducible installs impossible. Even `pytest` and `PyYAML` are unlisted despite already being needed/used by tests.
3. **No Unified Tool Registry:** Tools are stored in a flat 9-item dictionary without categories, capability discovery, JSON schemas, timeouts, retries, or cost tracking.

### 2.6 Data Persistence & Concurrency Limitations
1. **Unsafe JSON File Mutation:** `_load()` and `_save()` perform unlocked full-file reads and non-atomic overwrites, risking corruption under concurrent access.
2. **Test/Demo Pollution of Source Fixtures:** `mock_data/tasks.json` and `mock_data/calendar.json` are directly mutated by `run_demo.py`, leaving `"Spam task 0..3"` and duplicate entries committed in the working tree.
3. **No Relational Database / Migrations:** Missing PostgreSQL/SQLite SQLAlchemy ORM models, Alembic migrations, transactions, backups, and user separation.

### 2.7 Error Handling & Reliability Problems
1. `EmailTriageAgent` originally crashed with `KeyError: 'sender'` on `mock_data/emails.json` (which uses `"from"`), requiring an emergency patch.
2. No timeouts, retries with exponential backoff, structured error codes, or execution traces across multi-step operations.
3. Anomaly detection (`call_history`) stores state in an unbounded global dict keyed only by `agent_name`, leaks across test runs/users, and fires duplicate warnings for every call after threshold.

### 2.8 Scalability & Deployment Problems
1. **Stateful Serverless Conflict (`api/index.py` & `vercel.json`):** `api/index.py` relies on ephemeral `/tmp/mock_data` copied on every `GET` request. That architecture cannot persist PostgreSQL state, background workflows, OAuth tokens, or uploaded documents cleanly in serverless functions.
2. **No Containerization / Health Checks:** No `Dockerfile`, `docker-compose.yml`, `.env.example`, or `/api/health` readiness endpoint.

### 2.9 Lack of Automated Tests & Tooling Config
1. Running `python -m pytest` inside `deskmate/` fails during collection (`ModuleNotFoundError: No module named 'mcp_server'`) because no `pyproject.toml` / `pytest.ini` configures `pythonpath`.
2. `tests/test_security.py` only covers 4 minimal unit tests and mutates the repository-level `audit_log.jsonl`. There are zero tests for agents, orchestrator routing, NLU, tools, database, workflows, integrations, API endpoints, or skill packs.

---

## 3. Remediation Plan

1. **Foundation (`core/`, `db/`, `alembic/`, `llm/`, `nlp/`):** Implement config, encryption, PII redaction, JWT + CSRF auth, prompt-injection defense, principal-bound permissions, 20 SQLAlchemy models + Alembic migrations (PostgreSQL + local SQLite), provider-independent LLM adapter with full offline NLP fallback.
2. **Tooling & MCP (`tools/`, `mcp_server/`):** Build the 25-category capability-based `UnifiedToolRegistry` and a proper MCP server with stdio/JSON-RPC support, schema validation, timeouts, and cost transparency.
3. **12 Specialist Agents + `DeskMateOrchestrator` (`agents/`, `services/`):** Implement all 12 specialists with instruction files, Pydantic I/O schemas, anti-loop guards, execution tracing, Daily Executive Briefing, and optional Google ADK bridge.
4. **Integrations, FastAPI Backend & Next.js Dashboard (`integrations/`, `backend/`, `frontend/`):** Implement OAuth adapters, document ingestion/RAG, workflow engine, FastAPI REST API, and a 17-screen Deep Electric Navy + Cyan Next.js SaaS dashboard.
5. **AgenSi Skill Pack & QA (`deskmate-ai-skill-pack/`, `tests/`, `docs/`):** Create 9 standalone `SKILL.md` skills + `shared/` docs, package & validate `dist/deskmate-ai-skill-pack.zip`, write complete documentation, run full `pytest` & frontend build, and deploy/push cleanly.
