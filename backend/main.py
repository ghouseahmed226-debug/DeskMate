"""
backend/main.py

DeskMate AI — FastAPI REST Backend v2.0
Provides a complete REST API surface for the frontend, exposing all 12 specialist
agents, authentication, calendar, email, tasks, contacts, documents, integrations,
memory, workflows, briefing, and security audit.

Run with:
    uvicorn backend.main:app --reload --port 8000
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import (
    Depends,
    FastAPI,
    File,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

# ---------------------------------------------------------------------------
# DeskMate core imports
# ---------------------------------------------------------------------------
from core.config import get_settings
from core.security import JWTManager, redact_pii, scan_prompt_injection, SlidingWindowRateLimiter
from db.base import init_db, session_scope, get_db
from db.models import (
    AuditRecord, CalendarEvent, Contact, Conversation, DocumentRecord,
    Message, MemoryEntry, Task, User, Workflow,
)
from db.seed import DEMO_USER_ID, seed_demo_data
from agents.orchestrator import DeskMateOrchestrator, OrchestratorTurnResult
from mcp_server.personal_data_mcp_server import (
    AGENT_PERMISSIONS, AUDIT_LOG_PATH, call_tool,
)
from services.briefing_service import generate_daily_briefing
from services.document_service import ingest_document, search_user_documents
from services.audit_service import record_audit_event, summarize_security_posture

# ---------------------------------------------------------------------------
# App bootstrap
# ---------------------------------------------------------------------------
settings = get_settings()
init_db()
with session_scope() as _s:
    seed_demo_data(_s)

app = FastAPI(
    title="DeskMate AI API",
    description="Multi-agent personal AI assistant backend — Kaggle capstone v2.0",
    version="2.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_rate_limiter = SlidingWindowRateLimiter(max_calls=60, window_sec=60)
_jwt = JWTManager(settings.jwt_secret_key)
_orchestrators: Dict[str, DeskMateOrchestrator] = {}  # per-user orchestrator cache


# ---------------------------------------------------------------------------
# Shared Pydantic schemas
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "2.0.0"
    timestamp: str


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    display_name: Optional[str] = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: Optional[str] = None
    auto_confirm: bool = False


class ChatResponse(BaseModel):
    response: str
    conversation_id: Optional[str] = None
    agents_invoked: List[str] = []
    tools_called: List[str] = []
    needs_clarification: bool = False
    clarification_question: Optional[str] = None
    trace_id: str


class CalendarEventCreate(BaseModel):
    title: str
    start: str  # ISO 8601
    end: str
    description: Optional[str] = None
    location: Optional[str] = None
    attendees: List[str] = []


class TaskCreate(BaseModel):
    title: str
    description: Optional[str] = None
    due_date: Optional[str] = None
    priority: Optional[str] = "normal"
    tags: List[str] = []


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    due_date: Optional[str] = None
    priority: Optional[str] = None


class ContactCreate(BaseModel):
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    company: Optional[str] = None


class MemoryCreate(BaseModel):
    content: str
    tags: List[str] = []


class WorkflowRun(BaseModel):
    parameters: Dict[str, Any] = {}


class DocumentAskRequest(BaseModel):
    question: str


# ---------------------------------------------------------------------------
# Dependency: current user (JWT)
# ---------------------------------------------------------------------------

def _get_token(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    # For demo: allow query param ?token=
    return request.query_params.get("token", "")


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = _get_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        payload = _jwt.verify(token)
        user_id = payload.get("sub")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def get_demo_user(db: Session = Depends(get_db)) -> User:
    """Convenience dependency for demo mode — returns seeded demo user."""
    user = db.get(User, DEMO_USER_ID)
    if not user:
        raise HTTPException(status_code=503, detail="Demo user not seeded")
    return user


def _get_orchestrator(user_id: str) -> DeskMateOrchestrator:
    if user_id not in _orchestrators:
        _orchestrators[user_id] = DeskMateOrchestrator(auto_confirm=True)
    return _orchestrators[user_id]


# ---------------------------------------------------------------------------
# Error handler
# ---------------------------------------------------------------------------

@app.exception_handler(Exception)
async def global_error_handler(request: Request, exc: Exception):
    safe_msg = redact_pii(str(exc))
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "detail": safe_msg[:200]},
    )


# ---------------------------------------------------------------------------
# 1. Health
# ---------------------------------------------------------------------------

@app.get("/api/health", response_model=HealthResponse, tags=["System"])
async def health():
    return HealthResponse(timestamp=datetime.now(timezone.utc).isoformat())


# ---------------------------------------------------------------------------
# 2. Auth
# ---------------------------------------------------------------------------

@app.post("/api/auth/register", response_model=TokenResponse, status_code=201, tags=["Auth"])
async def register(body: RegisterRequest, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == body.email).first()
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")
    user = User(
        id=f"usr-{uuid.uuid4().hex[:12]}",
        email=body.email,
        display_name=body.display_name or body.email.split("@")[0],
    )
    # In production: hash password properly; for demo store hashed
    import hashlib
    user.password_hash = hashlib.sha256(body.password.encode()).hexdigest()
    db.add(user)
    db.commit()
    db.refresh(user)
    token = _jwt.create({"sub": user.id, "email": user.email})
    return TokenResponse(access_token=token, user_id=user.id)


@app.post("/api/auth/login", response_model=TokenResponse, tags=["Auth"])
async def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email).first()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    import hashlib
    pw_hash = hashlib.sha256(body.password.encode()).hexdigest()
    if getattr(user, "password_hash", None) != pw_hash:
        # Demo mode: allow login with any password if demo user
        if user.id != DEMO_USER_ID:
            raise HTTPException(status_code=401, detail="Invalid credentials")
    token = _jwt.create({"sub": user.id, "email": user.email})
    return TokenResponse(access_token=token, user_id=user.id)


@app.post("/api/auth/logout", tags=["Auth"])
async def logout():
    # Stateless JWT — client discards token
    return {"message": "Logged out"}


@app.get("/api/auth/me", tags=["Auth"])
async def me(user: User = Depends(get_current_user)):
    return {
        "id": user.id,
        "email": user.email,
        "display_name": getattr(user, "display_name", None),
        "created_at": str(getattr(user, "created_at", "")),
    }


# ---------------------------------------------------------------------------
# 3. Chat (Orchestrator)
# ---------------------------------------------------------------------------

@app.post("/api/chat", response_model=ChatResponse, tags=["Chat"])
async def chat(body: ChatRequest, request: Request, db: Session = Depends(get_db)):
    # Rate limiting
    client_ip = request.client.host if request.client else "unknown"
    if not _rate_limiter.is_allowed(client_ip):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    # Prompt injection scan
    threats = scan_prompt_injection(body.message)
    if threats:
        raise HTTPException(status_code=400, detail=f"Potential prompt injection detected: {threats}")

    # Use demo user for demo mode; in production use get_current_user
    token = _get_token(request)
    if token:
        try:
            payload = _jwt.verify(token)
            user_id = payload.get("sub", DEMO_USER_ID)
        except Exception:
            user_id = DEMO_USER_ID
    else:
        user_id = DEMO_USER_ID

    orch = _get_orchestrator(user_id)
    try:
        result: OrchestratorTurnResult = orch.process_turn(
            body.message,
            user_id=user_id,
            session=db,
            conversation_id=body.conversation_id,
        )
        return ChatResponse(
            response=result.response,
            conversation_id=result.conversation_id,
            agents_invoked=result.agents_invoked,
            tools_called=result.tools_called,
            needs_clarification=result.needs_clarification,
            clarification_question=result.clarification_question,
            trace_id=result.trace_id,
        )
    except Exception as exc:
        # Graceful fallback
        fallback = orch.handle(body.message)
        return ChatResponse(response=fallback, trace_id=f"trc-{uuid.uuid4().hex[:8]}")


# ---------------------------------------------------------------------------
# 4. Conversations
# ---------------------------------------------------------------------------

@app.get("/api/conversations", tags=["Conversations"])
async def list_conversations(request: Request, db: Session = Depends(get_db)):
    user_id = _resolve_user_id(request)
    convs = db.query(Conversation).filter(Conversation.user_id == user_id).order_by(
        Conversation.created_at.desc()
    ).limit(50).all()
    return [{"id": c.id, "title": c.title, "created_at": str(c.created_at)} for c in convs]


@app.get("/api/conversations/{conv_id}", tags=["Conversations"])
async def get_conversation(conv_id: str, request: Request, db: Session = Depends(get_db)):
    user_id = _resolve_user_id(request)
    conv = db.get(Conversation, conv_id)
    if not conv or conv.user_id != user_id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    messages = db.query(Message).filter(Message.conversation_id == conv_id).order_by(
        Message.created_at
    ).all()
    return {
        "id": conv.id,
        "title": conv.title,
        "messages": [{"role": m.role, "content": m.content, "created_at": str(m.created_at)} for m in messages],
    }


# ---------------------------------------------------------------------------
# 5. Calendar
# ---------------------------------------------------------------------------

@app.get("/api/calendar", tags=["Calendar"])
async def get_calendar(request: Request, db: Session = Depends(get_db)):
    user_id = _resolve_user_id(request)
    events = db.query(CalendarEvent).filter(CalendarEvent.user_id == user_id).limit(100).all()
    return [_serialize_event(e) for e in events]


@app.post("/api/calendar/events", status_code=201, tags=["Calendar"])
async def create_calendar_event(
    body: CalendarEventCreate, request: Request, db: Session = Depends(get_db)
):
    user_id = _resolve_user_id(request)
    result = call_tool(
        "CalendarSchedulingAgent", "create_calendar_event",
        title=body.title, start=body.start, end=body.end,
        description=body.description or "", attendees=body.attendees,
    )
    return {"message": "Event created", "event": result}


@app.put("/api/calendar/events/{event_id}", tags=["Calendar"])
async def update_calendar_event(
    event_id: str, body: CalendarEventCreate, request: Request, db: Session = Depends(get_db)
):
    user_id = _resolve_user_id(request)
    result = call_tool(
        "CalendarSchedulingAgent", "update_calendar_event",
        event_id=event_id, **body.dict(exclude_none=True),
    )
    return {"message": "Event updated", "event": result}


@app.delete("/api/calendar/events/{event_id}", tags=["Calendar"])
async def delete_calendar_event(event_id: str, request: Request, db: Session = Depends(get_db)):
    # Calendar deletion requires explicit approval — not implemented in mock
    raise HTTPException(status_code=501, detail="Calendar event deletion requires OAuth integration")


# ---------------------------------------------------------------------------
# 6. Email / Inbox
# ---------------------------------------------------------------------------

@app.get("/api/inbox", tags=["Email"])
async def get_inbox(request: Request, db: Session = Depends(get_db)):
    result = call_tool("EmailIntelligenceAgent", "get_emails")
    return {"emails": result, "count": len(result) if isinstance(result, list) else 0}


@app.post("/api/inbox/draft", status_code=201, tags=["Email"])
async def create_draft(request: Request, body: Dict[str, Any], db: Session = Depends(get_db)):
    # Create a draft (never sends without explicit approval)
    to = body.get("to", "")
    subject = body.get("subject", "")
    content = body.get("content", "")
    if not to or not subject:
        raise HTTPException(status_code=400, detail="to and subject are required")
    return {"message": "Draft saved (not sent)", "draft": {"to": to, "subject": subject, "content": content}}


# ---------------------------------------------------------------------------
# 7. Tasks
# ---------------------------------------------------------------------------

@app.get("/api/tasks", tags=["Tasks"])
async def get_tasks(request: Request, db: Session = Depends(get_db)):
    result = call_tool("TaskProjectManagementAgent", "get_tasks")
    return {"tasks": result}


@app.post("/api/tasks", status_code=201, tags=["Tasks"])
async def create_task(body: TaskCreate, request: Request, db: Session = Depends(get_db)):
    result = call_tool(
        "TaskProjectManagementAgent", "create_task",
        title=body.title, description=body.description or "",
        due_date=body.due_date or "", priority=body.priority or "normal",
    )
    return {"message": "Task created", "task": result}


@app.put("/api/tasks/{task_id}", tags=["Tasks"])
async def update_task(task_id: str, body: TaskUpdate, request: Request, db: Session = Depends(get_db)):
    result = call_tool(
        "TaskProjectManagementAgent", "update_task",
        task_id=task_id, **{k: v for k, v in body.dict().items() if v is not None},
    )
    return {"message": "Task updated", "task": result}


@app.delete("/api/tasks/{task_id}", tags=["Tasks"])
async def delete_task(task_id: str, request: Request, db: Session = Depends(get_db)):
    raise HTTPException(status_code=501, detail="Task deletion not yet implemented")


# ---------------------------------------------------------------------------
# 8. Contacts
# ---------------------------------------------------------------------------

@app.get("/api/contacts", tags=["Contacts"])
async def get_contacts(request: Request):
    result = call_tool("ContactCRM_Agent", "get_contacts")
    return {"contacts": result}


@app.post("/api/contacts", status_code=201, tags=["Contacts"])
async def create_contact(body: ContactCreate, request: Request):
    return {
        "message": "Contact saved (mock)",
        "contact": {"name": body.name, "email": body.email, "company": body.company},
    }


# ---------------------------------------------------------------------------
# 9. Documents
# ---------------------------------------------------------------------------

@app.get("/api/documents", tags=["Documents"])
async def list_documents(request: Request, db: Session = Depends(get_db)):
    user_id = _resolve_user_id(request)
    docs = db.query(DocumentRecord).filter(DocumentRecord.user_id == user_id).limit(50).all()
    return [{"id": d.id, "filename": d.filename, "mime_type": d.mime_type, "created_at": str(d.created_at)} for d in docs]


@app.post("/api/documents/upload", status_code=201, tags=["Documents"])
async def upload_document(
    file: UploadFile = File(...),
    request: Request = None,
    db: Session = Depends(get_db),
):
    user_id = _resolve_user_id(request) if request else DEMO_USER_ID
    content = await file.read()
    try:
        doc_id = ingest_document(
            db=db,
            user_id=user_id,
            filename=file.filename or "upload",
            content_bytes=content,
            mime_type=file.content_type or "application/octet-stream",
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Document processing failed: {exc}")
    return {"message": "Document ingested", "document_id": doc_id}


@app.post("/api/documents/{doc_id}/ask", tags=["Documents"])
async def ask_document(doc_id: str, body: DocumentAskRequest, request: Request, db: Session = Depends(get_db)):
    user_id = _resolve_user_id(request)
    results = search_user_documents(db=db, user_id=user_id, query=body.question, top_k=5)
    if not results:
        return {"answer": "No relevant content found in your documents.", "chunks": []}
    answer = "\n\n".join(r.get("text", "") for r in results[:3])
    return {"answer": answer, "chunks": results}


# ---------------------------------------------------------------------------
# 10. Daily Briefing
# ---------------------------------------------------------------------------

@app.get("/api/briefing", tags=["Briefing"])
async def daily_briefing(request: Request, db: Session = Depends(get_db)):
    user_id = _resolve_user_id(request)
    briefing = generate_daily_briefing(db=db, user_id=user_id)
    return {"briefing": briefing}


# ---------------------------------------------------------------------------
# 11. Integrations
# ---------------------------------------------------------------------------

@app.get("/api/integrations", tags=["Integrations"])
async def list_integrations(request: Request, db: Session = Depends(get_db)):
    try:
        from integrations.connectors import list_integration_statuses
        user_id = _resolve_user_id(request)
        statuses = list_integration_statuses(db, user_id)
        return {"integrations": statuses}
    except Exception as exc:
        return {"integrations": [], "note": str(exc)}


@app.get("/api/integrations/{provider}/connect", tags=["Integrations"])
async def connect_integration(provider: str, request: Request, db: Session = Depends(get_db)):
    try:
        from integrations.google_oauth import GoogleOAuthAdapter
        adapter = GoogleOAuthAdapter()
        url = adapter.get_auth_url(state=provider)
        return {"auth_url": url, "provider": provider}
    except Exception as exc:
        return {"error": str(exc), "note": "Configure OAuth credentials in .env to enable real integrations"}


@app.get("/api/integrations/{provider}/callback", tags=["Integrations"])
async def oauth_callback(provider: str, code: str, request: Request, db: Session = Depends(get_db)):
    return {"message": f"OAuth callback received for {provider}", "code": code[:8] + "..."}


@app.delete("/api/integrations/{provider}", tags=["Integrations"])
async def disconnect_integration(provider: str, request: Request, db: Session = Depends(get_db)):
    return {"message": f"Integration {provider} disconnected"}


# ---------------------------------------------------------------------------
# 12. Workflows
# ---------------------------------------------------------------------------

@app.get("/api/workflows", tags=["Workflows"])
async def list_workflows(request: Request, db: Session = Depends(get_db)):
    user_id = _resolve_user_id(request)
    wfs = db.query(Workflow).filter(Workflow.user_id == user_id).limit(20).all()
    return [{"id": w.id, "name": w.name, "status": getattr(w, "status", "active")} for w in wfs]


@app.post("/api/workflows/{workflow_id}/run", tags=["Workflows"])
async def run_workflow_endpoint(workflow_id: str, body: WorkflowRun, request: Request, db: Session = Depends(get_db)):
    user_id = _resolve_user_id(request)
    orch = _get_orchestrator(user_id)
    result = orch.handle(f"Run workflow {workflow_id} with parameters: {body.parameters}")
    return {"message": "Workflow triggered", "result": result}


# ---------------------------------------------------------------------------
# 13. Memory
# ---------------------------------------------------------------------------

@app.get("/api/memory", tags=["Memory"])
async def list_memory(request: Request, db: Session = Depends(get_db)):
    user_id = _resolve_user_id(request)
    entries = db.query(MemoryEntry).filter(MemoryEntry.user_id == user_id).order_by(
        MemoryEntry.created_at.desc()
    ).limit(50).all()
    return [{"id": e.id, "content": e.content, "tags": getattr(e, "tags", [])} for e in entries]


@app.post("/api/memory", status_code=201, tags=["Memory"])
async def create_memory(body: MemoryCreate, request: Request, db: Session = Depends(get_db)):
    user_id = _resolve_user_id(request)
    entry = MemoryEntry(
        id=f"mem-{uuid.uuid4().hex[:12]}",
        user_id=user_id,
        content=body.content,
    )
    db.add(entry)
    db.commit()
    return {"id": entry.id, "content": entry.content}


@app.delete("/api/memory/{mem_id}", tags=["Memory"])
async def delete_memory(mem_id: str, request: Request, db: Session = Depends(get_db)):
    user_id = _resolve_user_id(request)
    entry = db.get(MemoryEntry, mem_id)
    if not entry or entry.user_id != user_id:
        raise HTTPException(status_code=404, detail="Memory entry not found")
    db.delete(entry)
    db.commit()
    return {"message": "Deleted"}


# ---------------------------------------------------------------------------
# 14. Security
# ---------------------------------------------------------------------------

@app.get("/api/security/audit", tags=["Security"])
async def security_audit(request: Request, db: Session = Depends(get_db), limit: int = 50):
    user_id = _resolve_user_id(request)
    records = db.query(AuditRecord).filter(AuditRecord.user_id == user_id).order_by(
        AuditRecord.timestamp.desc()
    ).limit(limit).all()
    posture = summarize_security_posture(db, user_id)
    return {
        "posture": posture,
        "records": [
            {
                "id": r.id,
                "agent_name": r.agent_name,
                "tool_name": r.tool_name,
                "outcome": r.outcome,
                "timestamp": str(r.timestamp),
            }
            for r in records
        ],
    }


@app.post("/api/security/scan", tags=["Security"])
async def security_scan(request: Request):
    body = await request.json()
    text = body.get("text", "")
    threats = scan_prompt_injection(text)
    return {"threats_detected": bool(threats), "threats": threats}


# ---------------------------------------------------------------------------
# Agents roster
# ---------------------------------------------------------------------------

@app.get("/api/agents", tags=["Agents"])
async def list_agents():
    orch = DeskMateOrchestrator(auto_confirm=True)
    return {"agents": orch.list_agent_specs()}


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _resolve_user_id(request: Request) -> str:
    """Extract user_id from JWT or fall back to demo user."""
    token = _get_token(request)
    if token:
        try:
            payload = _jwt.verify(token)
            return payload.get("sub", DEMO_USER_ID)
        except Exception:
            pass
    return DEMO_USER_ID


def _serialize_event(e: CalendarEvent) -> dict:
    return {
        "id": e.id,
        "title": e.title,
        "start": str(getattr(e, "start_time", getattr(e, "start", ""))),
        "end": str(getattr(e, "end_time", getattr(e, "end", ""))),
        "description": getattr(e, "description", ""),
        "location": getattr(e, "location", ""),
    }
