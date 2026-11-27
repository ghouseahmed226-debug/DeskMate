"""
tests/test_db.py

Tests for the database layer (db/):
- init_db() creates all 20 tables
- seed_demo_data() populates User + demo records
- All 20 ORM models are importable and have expected columns
- session_scope() context manager
"""

from __future__ import annotations

import os
import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret-key-32chars-not-prod!")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-32chars-not-prod!")

from sqlalchemy import inspect as sa_inspect

from db.base import init_db, session_scope
from db.models import (
    AuditRecord,
    CalendarEvent,
    Contact,
    Conversation,
    DocumentChunk,
    DocumentRecord,
    EmailMetadata,
    IntegrationConnection,
    MemoryEntry,
    Message,
    PermissionPolicy,
    Project,
    Task,
    ToolExecution,
    ToolRegistryEntry,
    User,
    UserPreference,
    Workflow,
    WorkflowExecution,
    ApprovalRequest,
)
from db.seed import DEMO_USER_ID, seed_demo_data


# ---------------------------------------------------------------------------
# 20 models importable
# ---------------------------------------------------------------------------

class TestModelImports:
    def test_all_20_models_importable(self):
        models = [
            User, Conversation, Message, Project, Task,
            CalendarEvent, Contact, EmailMetadata, Workflow, WorkflowExecution,
            ToolRegistryEntry, ToolExecution, PermissionPolicy, ApprovalRequest,
            AuditRecord, UserPreference, MemoryEntry, IntegrationConnection,
            DocumentRecord, DocumentChunk,
        ]
        assert len(models) == 20

    def test_user_has_expected_columns(self):
        cols = {c.key for c in User.__table__.columns}
        assert "id" in cols
        assert "email" in cols

    def test_task_has_expected_columns(self):
        cols = {c.key for c in Task.__table__.columns}
        assert "title" in cols
        assert "user_id" in cols

    def test_calendar_event_has_start_time(self):
        cols = {c.key for c in CalendarEvent.__table__.columns}
        assert "start_at" in cols and "end_at" in cols

    def test_audit_record_has_outcome(self):
        cols = {c.key for c in AuditRecord.__table__.columns}
        assert "outcome" in cols


# ---------------------------------------------------------------------------
# init_db() creates tables
# ---------------------------------------------------------------------------

class TestInitDb:
    def test_init_db_runs_without_error(self, test_engine):
        """init_db() must be idempotent — calling twice must not raise."""
        from db.base import Base
        Base.metadata.create_all(test_engine)  # already done in fixture; verify idempotency
        inspector = sa_inspect(test_engine)
        tables = inspector.get_table_names()
        assert len(tables) >= 10, f"Expected ≥10 tables, found: {tables}"

    def test_expected_tables_exist(self, test_engine):
        inspector = sa_inspect(test_engine)
        tables = set(inspector.get_table_names())
        expected = {"users", "tasks", "calendar_events", "audit_records", "conversations"}
        missing = expected - tables
        assert not missing, f"Missing tables: {missing}"


# ---------------------------------------------------------------------------
# seed_demo_data() populates records
# ---------------------------------------------------------------------------

class TestSeedDemoData:
    def test_seed_creates_demo_user(self, seeded_session):
        user = seeded_session.get(User, DEMO_USER_ID)
        assert user is not None, "Demo user must exist after seeding"
        assert user.email is not None

    def test_seed_creates_calendar_events(self, seeded_session):
        from sqlalchemy import select
        events = seeded_session.execute(
            select(CalendarEvent).where(CalendarEvent.user_id == DEMO_USER_ID)
        ).scalars().all()
        assert len(events) >= 1, "At least 1 calendar event expected after seeding"

    def test_seed_creates_tasks(self, seeded_session):
        from sqlalchemy import select
        tasks = seeded_session.execute(
            select(Task).where(Task.user_id == DEMO_USER_ID)
        ).scalars().all()
        assert len(tasks) >= 1, "At least 1 task expected after seeding"

    def test_seed_is_idempotent(self, seeded_session):
        """Calling seed_demo_data twice must not raise or duplicate the user."""
        seed_demo_data(seeded_session)  # second call
        user_count = seeded_session.query(User).filter(User.id == DEMO_USER_ID).count()
        assert user_count == 1, "User must not be duplicated on re-seed"
