"""Complete SQLAlchemy 2.0 ORM schema for DeskMate AI."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: _new_id("usr"))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), default="user", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class AgentProfile(Base):
    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    instruction_file: Mapped[str] = mapped_column(String(255), nullable=False)
    allowed_tools_json: Mapped[List[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(32), default="active")
    config_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: _new_id("conv"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(255), default="New Conversation")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    messages: Mapped[List["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: _new_id("msg"))
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)  # user | assistant | system
    content: Mapped[str] = mapped_column(Text, nullable=False)
    agent_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    trace_id: Mapped[Optional[str]] = mapped_column(String(64), index=True, nullable=True)
    metadata_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: _new_id("proj"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="active")
    due_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: _new_id("task"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    parent_task_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="pending")  # pending | in_progress | completed
    priority: Mapped[str] = mapped_column(String(32), default="Medium")  # Critical | High | Medium | Low
    category: Mapped[str] = mapped_column(String(64), default="General")
    tags_json: Mapped[List[str]] = mapped_column(JSON, default=list)
    dependencies_json: Mapped[List[str]] = mapped_column(JSON, default=list)
    due_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    recurrence: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    source: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class CalendarEvent(Base):
    __tablename__ = "calendar_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: _new_id("evt"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    external_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    timezone_name: Mapped[str] = mapped_column(String(64), default="UTC")
    recurrence: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    attendees_json: Mapped[List[str]] = mapped_column(JSON, default=list)
    agenda: Mapped[str] = mapped_column(Text, default="")
    location: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(32), default="confirmed")  # confirmed | cancelled | tentative
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class Contact(Base):
    __tablename__ = "contacts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: _new_id("cnt"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[Optional[str]] = mapped_column(String(255), index=True, nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    company: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    job_title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    category: Mapped[str] = mapped_column(String(64), default="Professional")
    notes: Mapped[str] = mapped_column(Text, default="")
    interaction_history_json: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list)
    follow_up_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class EmailMetadata(Base):
    __tablename__ = "email_metadata"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: _new_id("em"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    external_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    thread_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    sender: Mapped[str] = mapped_column(String(255), nullable=False)
    recipients_json: Mapped[List[str]] = mapped_column(JSON, default=list)
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    snippet: Mapped[str] = mapped_column(Text, default="")
    body_preview: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(64), default="General")
    priority: Mapped[str] = mapped_column(String(32), default="Medium")
    is_unread: Mapped[bool] = mapped_column(Boolean, default=True)
    is_suspicious: Mapped[bool] = mapped_column(Boolean, default=False)
    has_attachments: Mapped[bool] = mapped_column(Boolean, default=False)
    attachments_json: Mapped[List[str]] = mapped_column(JSON, default=list)
    deadline_detected: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    action_items_json: Mapped[List[str]] = mapped_column(JSON, default=list)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Workflow(Base):
    __tablename__ = "workflows"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: _new_id("wf"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    trigger_type: Mapped[str] = mapped_column(String(64), default="manual")
    schedule_cron: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    steps_json: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list)
    require_approval: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    max_retries: Mapped[int] = mapped_column(Integer, default=2)
    execution_limit: Mapped[int] = mapped_column(Integer, default=10)
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class WorkflowExecution(Base):
    __tablename__ = "workflow_executions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: _new_id("wfex"))
    workflow_id: Mapped[str] = mapped_column(ForeignKey("workflows.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="running")  # running | waiting_approval | completed | cancelled | failed
    trace_id: Mapped[str] = mapped_column(String(64), index=True)
    step_results_json: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class ToolRegistryEntry(Base):
    __tablename__ = "tool_registry"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    category: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(String(64), default="local")
    input_schema_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    output_schema_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    cost_estimate: Mapped[float] = mapped_column(Float, default=0.0)
    timeout_sec: Mapped[int] = mapped_column(Integer, default=15)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class ToolExecution(Base):
    __tablename__ = "tool_executions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: _new_id("tex"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    trace_id: Mapped[str] = mapped_column(String(64), index=True)
    agent_name: Mapped[str] = mapped_column(String(128), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    duration_ms: Mapped[float] = mapped_column(Float, default=0.0)
    cost_incurred: Mapped[float] = mapped_column(Float, default=0.0)
    approval_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    error_sanitized: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class PermissionPolicy(Base):
    __tablename__ = "permissions"
    __table_args__ = (UniqueConstraint("agent_name", "tool_name", name="uq_agent_tool_policy"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: _new_id("perm"))
    agent_name: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
    scope: Mapped[str] = mapped_column(String(64), default="read")
    effect: Mapped[str] = mapped_column(String(16), default="allow")


class ApprovalRequest(Base):
    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: _new_id("apr"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    trace_id: Mapped[str] = mapped_column(String(64), index=True)
    agent_name: Mapped[str] = mapped_column(String(128), nullable=False)
    action_type: Mapped[str] = mapped_column(String(128), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    payload_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="pending")  # pending | approved | rejected | expired
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class AuditRecord(Base):
    __tablename__ = "audit_records"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: _new_id("aud"))
    user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True)
    trace_id: Mapped[Optional[str]] = mapped_column(String(64), index=True, nullable=True)
    agent_name: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
    action: Mapped[str] = mapped_column(String(128), default="tool_call")
    params_redacted_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    outcome: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    approval_state: Mapped[str] = mapped_column(String(64), default="not_required")
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)


class UserPreference(Base):
    __tablename__ = "user_preferences"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: _new_id("pref"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    timezone_name: Mapped[str] = mapped_column(String(64), default="UTC")
    working_hours_start: Mapped[str] = mapped_column(String(16), default="09:00")
    working_hours_end: Mapped[str] = mapped_column(String(16), default="17:30")
    preferred_llm_provider: Mapped[str] = mapped_column(String(32), default="offline")
    daily_briefing_time: Mapped[str] = mapped_column(String(16), default="08:30")
    preferences_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)


class MemoryEntry(Base):
    __tablename__ = "memory_entries"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: _new_id("mem"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    category: Mapped[str] = mapped_column(String(64), default="preference")
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    approved: Mapped[bool] = mapped_column(Boolean, default=True)
    retention_days: Mapped[int] = mapped_column(Integer, default=90)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class IntegrationConnection(Base):
    __tablename__ = "integration_connections"
    __table_args__ = (UniqueConstraint("user_id", "provider", name="uq_user_provider"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: _new_id("intg"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="disconnected")
    scopes_json: Mapped[List[str]] = mapped_column(JSON, default=list)
    encrypted_tokens: Mapped[str] = mapped_column(Text, default="")
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_health_check_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class DocumentRecord(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: _new_id("doc"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    extracted_summary: Mapped[str] = mapped_column(Text, default="")
    metadata_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    chunks: Mapped[List["DocumentChunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: _new_id("chk"))
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    keywords_json: Mapped[List[str]] = mapped_column(JSON, default=list)

    document: Mapped["DocumentRecord"] = relationship(back_populates="chunks")
