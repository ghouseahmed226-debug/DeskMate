# DeskMate AI

> **One Assistant. Every Workflow. Intelligent Execution.**

A production-grade multi-agent personal AI operating system built for the
**Kaggle × Google "AI Agents: Intensive Vibe Coding"** competition.

---

## 🏆 Competition Concepts Demonstrated

| # | Concept | Implementation |
|---|---|---|
| **1** | **Multi-Agent System** | 1 Orchestrator + 12 Specialist Agents with hierarchical delegation |
| **2** | **MCP Server** | Custom JSON-RPC 2.0 MCP server with `@server.tool()` decorators + fallback |
| **3** | **Security** | Least-privilege allowlist + HMAC signing + prompt injection + anomaly detection + audit log |
| **4** | **Agent Skills** | `meeting_prep` skill composing 3 tools into 1 high-level capability |
| **5** | **Testing** | 50+ tests across security, MCP, NLU, orchestrator, agents, DB, and tools |

---

## 🏗 Architecture

```
                    ┌─────────────────────────────────────┐
                    │         DeskMateOrchestrator         │
                    │  NLU Parser · LLM Routing · Approval │
                    └──────────────┬──────────────────────┘
                                   │ delegates to
              ┌────────────────────┼────────────────────┐
              │                    │                    │
   ┌──────────▼─────────┐  ┌───────▼────────┐  ┌───────▼────────────┐
   │ EmailIntelligence  │  │CalendarSched.  │  │ TaskProjectMgmt    │
   │ Agent              │  │ Agent          │  │ Agent              │
   └──────────┬─────────┘  └───────┬────────┘  └───────┬────────────┘
              │                    │                    │
   ┌──────────▼────────────────────▼────────────────────▼────────────┐
   │              Personal Data MCP Server (JSON-RPC 2.0)             │
   │   get_calendar_events · create_calendar_event · update_calendar  │
   │   get_emails · get_contacts · create_task · get_tasks · update   │
   │                                                                   │
   │   ┌─ AGENT_PERMISSIONS allowlist (least privilege) ─────────┐    │
   │   │  Audit log (PII-redacted) · Anomaly detection           │    │
   │   └─────────────────────────────────────────────────────────┘    │
   └───────────────────────────────────────────────────────────────────┘
              │
   ┌──────────▼─────────────────┐
   │  mock_data/ JSON files     │  ← zero credentials required
   │  SQLite / PostgreSQL DB    │  ← 20 SQLAlchemy ORM models
   └────────────────────────────┘
```

**Additional 9 specialist agents:** ContactCRM · ResearchIntelligence ·
BusinessIntelligence · DocumentAssistant · MeetingAssistant · Communication ·
WorkflowAutomation · PersonalKnowledge · SecurityCompliance

---

## 🚀 Quick Start (Zero Credentials)

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run the full scripted demo (screen-record this!)
cd deskmate
python run_demo.py

# 3. Interactive chat
python chat.py

# 4. FastAPI backend
uvicorn backend.main:app --reload --port 8000
# → http://localhost:8000/api/docs

# 5. Run tests
python -m pytest tests/ -v
```

---

## 📁 Project Structure

```
deskmate/
├── agents/                    # 12 specialist agents + orchestrator
│   ├── orchestrator.py        # DeskMateOrchestrator — main router
│   ├── calendar_agent.py      # CalendarSchedulingAgent
│   ├── email_agent.py         # EmailIntelligenceAgent
│   ├── task_agent.py          # TaskProjectManagementAgent
│   ├── contacts_crm_agent.py  # ContactCRM_Agent
│   ├── research_agent.py      # ResearchIntelligenceAgent
│   ├── meeting_agent.py       # MeetingAssistantAgent
│   ├── document_agent.py      # DocumentAssistantAgent
│   ├── security_agent.py      # SecurityComplianceAgent
│   └── ...                    # + 4 more specialists
│
├── mcp_server/
│   └── personal_data_mcp_server.py  # MCP + allowlist + anomaly detection
│
├── backend/
│   └── main.py                # FastAPI REST API (19 endpoint groups)
│
├── core/
│   ├── config.py              # Pydantic settings
│   └── security.py            # JWT, Fernet, CSRF, PII redaction, rate limiter
│
├── db/
│   ├── models.py              # 20 SQLAlchemy ORM models
│   ├── base.py                # Engine, session, init_db()
│   └── seed.py                # Demo data seeding (idempotent)
│
├── nlp/
│   └── parser.py              # 12-intent NLU parser, relative dates, multi-intent
│
├── tools/
│   └── registry.py            # UnifiedToolRegistry — 25 categories, permission gates
│
├── skills/
│   └── meeting_prep.py        # Agent Skill: multi-tool composition
│
├── services/
│   ├── audit_service.py       # Audit log DB + JSONL writer
│   ├── briefing_service.py    # Daily executive briefing
│   └── document_service.py    # PDF/DOCX/CSV RAG ingestion
│
├── integrations/              # Gmail, Calendar, Drive, Slack, Notion adapters
├── mock_data/                 # calendar.json, emails.json, contacts.json, tasks.json
├── tests/                     # 50+ tests (security, MCP, NLU, DB, tools, agents)
├── deskmate-ai-skill-pack/    # AgenSi-compatible skill pack (9 skills)
│
├── run_demo.py                # Scripted demo (screen-record this)
├── chat.py                    # Interactive CLI chat loop
├── Dockerfile                 # Multi-stage production Docker build
├── docker-compose.yml         # App + PostgreSQL + Redis
└── .env.example               # All environment variables documented
```

---

## 🔐 Security Architecture

DeskMate AI implements **5 security layers**:

### 1. Least-Privilege Allowlist
Every agent has an explicit allowlist of permitted tools in `AGENT_PERMISSIONS`.
Violations raise `PermissionDeniedError` and are logged with outcome `DENIED`.

```python
# EmailTriageAgent trying to call create_task → BLOCKED
TOOL_REGISTRY["create_task"]("EmailTriageAgent", title="injected")
# → PermissionDeniedError: EmailTriageAgent is not permitted to use create_task
```

### 2. HMAC-Signed Agent Principals
`AgentPrincipal` in `core/security.py` signs agent identities with HMAC-SHA256
to prevent agent name spoofing between trust boundaries.

### 3. Prompt Injection Detection
`scan_prompt_injection()` checks all user inputs and external content (emails,
web pages) before passing to agent LLM context.

### 4. Sliding-Window Anomaly Detection
The MCP server tracks per-agent call rates in a 60-second sliding window:
- **>10 calls/minute** → `FLAGGED_SUSPICIOUS` in audit log
- **>3 consecutive write calls** → `FLAGGED_SUSPICIOUS` + warning

### 5. PII Redaction
All audit log entries pass through `redact_pii()` — emails, names, and phone
numbers are masked before persistence.

---

## 🤖 Agent Roster

| Agent | Category | Key Tools |
|---|---|---|
| DeskMateOrchestrator | orchestrator | routing, approval gates, briefing |
| EmailIntelligenceAgent | email | get_emails, get_contacts |
| CalendarSchedulingAgent | calendar | get/create/update_calendar_event |
| TaskProjectManagementAgent | tasks | create/get/update_task |
| ContactCRM_Agent | crm | get_contacts |
| ResearchIntelligenceAgent | research | web_search (DuckDuckGo) |
| BusinessIntelligenceAgent | analytics | get_tasks, get_calendar_events |
| DocumentAssistantAgent | documents | document_search |
| MeetingAssistantAgent | productivity | 3-tool skill composition |
| CommunicationAgent | communication | get_emails, get_contacts |
| WorkflowAutomationAgent | automation | get/create_task, calendar |
| PersonalKnowledgeAgent | knowledge | get_tasks, get_contacts |
| SecurityComplianceAgent | security | audit_log read |

---

## 🧪 Test Suite

```bash
cd deskmate
python -m pytest tests/ -v --tb=short
```

| Test File | Tests | Coverage |
|---|---|---|
| `test_security.py` | 4 | Core security primitives |
| `test_mcp_server.py` | 11 | MCP allowlist, JSON-RPC, call_tool |
| `test_nlu_parser.py` | 20+ | Intent routing, date parsing, multi-intent |
| `test_orchestrator.py` | 12 | Routing, process_turn, approval gate |
| `test_agents.py` | 15+ | All 12 specialists |
| `test_db.py` | 10 | 20 ORM models, seeding |
| `test_tools.py` | 10 | Registry, permissions, timeout |

---

## 🌐 REST API

```
GET  /api/health
POST /api/auth/register | login | logout
GET  /api/auth/me
POST /api/chat                    ← main orchestrator endpoint
GET  /api/conversations
GET  /api/calendar
POST /api/calendar/events
GET  /api/inbox
GET  /api/tasks
POST /api/tasks
PUT  /api/tasks/{id}
GET  /api/contacts
POST /api/documents/upload
POST /api/documents/{id}/ask
GET  /api/briefing
GET  /api/integrations
GET  /api/agents
GET  /api/security/audit
POST /api/security/scan
```

Full interactive docs: `http://localhost:8000/api/docs`

---

## 🐳 Docker

```bash
docker-compose up --build
# → API: http://localhost:8000
# → PostgreSQL: localhost:5432
```

---

## ⚙️ Environment Variables

Copy `.env.example` to `.env` and fill in values. All variables have
safe auto-generated defaults for local demo mode.

```bash
cp .env.example .env
python run_demo.py    # works with zero credentials
```

Key variables:
- `DATABASE_URL` — SQLite default for local dev; PostgreSQL for production
- `GEMINI_API_KEY` — optional; enables real LLM routing
- `GOOGLE_CLIENT_ID/SECRET` — optional; enables Gmail + Calendar OAuth
- `SECRET_KEY`, `JWT_SECRET_KEY`, `FERNET_KEY` — auto-generated if empty

---

## 📦 AgenSi Skill Pack

The `deskmate-ai-skill-pack/` directory contains 9 `SKILL.md` files
compatible with the Antigravity agent marketplace.

```bash
# Build the ZIP
Compress-Archive -Path deskmate-ai-skill-pack -DestinationPath dist/deskmate-ai-skill-pack.zip
```

---

## 🎬 Demo Video Script

See [`docs/demo_script.md`](docs/demo_script.md) for the word-for-word
2–3 minute Kaggle submission video script.

---

## 📄 License

MIT © 2026 @ghouseahmed226-debug
