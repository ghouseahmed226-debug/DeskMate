"""Initial DeskMate AI multi-agent database schema.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-11-27
"""

from alembic import op
import sqlalchemy as sa


revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "agents",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False, unique=True),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("instruction_file", sa.String(255), nullable=False),
        sa.Column("allowed_tools_json", sa.JSON()),
        sa.Column("status", sa.String(32)),
        sa.Column("config_json", sa.JSON()),
    )
    op.create_table(
        "conversations",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("title", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "messages",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("conversation_id", sa.String(64), sa.ForeignKey("conversations.id", ondelete="CASCADE")),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("agent_name", sa.String(128)),
        sa.Column("trace_id", sa.String(64)),
        sa.Column("metadata_json", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "projects",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("status", sa.String(32)),
        sa.Column("due_date", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "tasks",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("project_id", sa.String(64), sa.ForeignKey("projects.id", ondelete="SET NULL")),
        sa.Column("parent_task_id", sa.String(64), sa.ForeignKey("tasks.id", ondelete="SET NULL")),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("status", sa.String(32)),
        sa.Column("priority", sa.String(32)),
        sa.Column("category", sa.String(64)),
        sa.Column("tags_json", sa.JSON()),
        sa.Column("dependencies_json", sa.JSON()),
        sa.Column("due_date", sa.DateTime(timezone=True)),
        sa.Column("recurrence", sa.String(64)),
        sa.Column("source", sa.String(128)),
        sa.Column("done", sa.Boolean()),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "calendar_events",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("external_id", sa.String(255)),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("timezone_name", sa.String(64)),
        sa.Column("recurrence", sa.String(128)),
        sa.Column("attendees_json", sa.JSON()),
        sa.Column("agenda", sa.Text()),
        sa.Column("location", sa.String(255)),
        sa.Column("status", sa.String(32)),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "contacts",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255)),
        sa.Column("phone", sa.String(64)),
        sa.Column("company", sa.String(255)),
        sa.Column("job_title", sa.String(255)),
        sa.Column("category", sa.String(64)),
        sa.Column("notes", sa.Text()),
        sa.Column("interaction_history_json", sa.JSON()),
        sa.Column("follow_up_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "email_metadata",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("external_id", sa.String(255)),
        sa.Column("thread_id", sa.String(255)),
        sa.Column("sender", sa.String(255), nullable=False),
        sa.Column("recipients_json", sa.JSON()),
        sa.Column("subject", sa.String(500), nullable=False),
        sa.Column("snippet", sa.Text()),
        sa.Column("body_preview", sa.Text()),
        sa.Column("category", sa.String(64)),
        sa.Column("priority", sa.String(32)),
        sa.Column("is_unread", sa.Boolean()),
        sa.Column("is_suspicious", sa.Boolean()),
        sa.Column("has_attachments", sa.Boolean()),
        sa.Column("attachments_json", sa.JSON()),
        sa.Column("deadline_detected", sa.String(128)),
        sa.Column("action_items_json", sa.JSON()),
        sa.Column("received_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "workflows",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("trigger_type", sa.String(64)),
        sa.Column("schedule_cron", sa.String(64)),
        sa.Column("steps_json", sa.JSON()),
        sa.Column("require_approval", sa.Boolean()),
        sa.Column("is_active", sa.Boolean()),
        sa.Column("max_retries", sa.Integer()),
        sa.Column("execution_limit", sa.Integer()),
        sa.Column("last_run_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "workflow_executions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("workflow_id", sa.String(64), sa.ForeignKey("workflows.id", ondelete="CASCADE")),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("status", sa.String(32)),
        sa.Column("trace_id", sa.String(64)),
        sa.Column("step_results_json", sa.JSON()),
        sa.Column("error_message", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "tool_registry",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False, unique=True),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("provider", sa.String(64)),
        sa.Column("input_schema_json", sa.JSON()),
        sa.Column("output_schema_json", sa.JSON()),
        sa.Column("requires_approval", sa.Boolean()),
        sa.Column("cost_estimate", sa.Float()),
        sa.Column("timeout_sec", sa.Integer()),
        sa.Column("enabled", sa.Boolean()),
    )
    op.create_table(
        "tool_executions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("trace_id", sa.String(64)),
        sa.Column("agent_name", sa.String(128), nullable=False),
        sa.Column("tool_name", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("duration_ms", sa.Float()),
        sa.Column("cost_incurred", sa.Float()),
        sa.Column("approval_id", sa.String(64)),
        sa.Column("error_sanitized", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "permissions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("agent_name", sa.String(128), nullable=False),
        sa.Column("tool_name", sa.String(128), nullable=False),
        sa.Column("scope", sa.String(64)),
        sa.Column("effect", sa.String(16)),
        sa.UniqueConstraint("agent_name", "tool_name", name="uq_agent_tool_policy"),
    )
    op.create_table(
        "approvals",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("trace_id", sa.String(64)),
        sa.Column("agent_name", sa.String(128), nullable=False),
        sa.Column("action_type", sa.String(128), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("payload_json", sa.JSON()),
        sa.Column("status", sa.String(32)),
        sa.Column("idempotency_key", sa.String(128)),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "audit_records",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("trace_id", sa.String(64)),
        sa.Column("agent_name", sa.String(128), nullable=False),
        sa.Column("tool_name", sa.String(128), nullable=False),
        sa.Column("action", sa.String(128)),
        sa.Column("params_redacted_json", sa.JSON()),
        sa.Column("outcome", sa.String(64), nullable=False),
        sa.Column("approval_state", sa.String(64)),
        sa.Column("detail", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "user_preferences",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id", ondelete="CASCADE"), unique=True),
        sa.Column("timezone_name", sa.String(64)),
        sa.Column("working_hours_start", sa.String(16)),
        sa.Column("working_hours_end", sa.String(16)),
        sa.Column("preferred_llm_provider", sa.String(32)),
        sa.Column("daily_briefing_time", sa.String(16)),
        sa.Column("preferences_json", sa.JSON()),
    )
    op.create_table(
        "memory_entries",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("category", sa.String(64)),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("approved", sa.Boolean()),
        sa.Column("retention_days", sa.Integer()),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "integration_connections",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32)),
        sa.Column("scopes_json", sa.JSON()),
        sa.Column("encrypted_tokens", sa.Text()),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("last_health_check_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("user_id", "provider", name="uq_user_provider"),
    )
    op.create_table(
        "documents",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(128), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("chunk_count", sa.Integer()),
        sa.Column("extracted_summary", sa.Text()),
        sa.Column("metadata_json", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "document_chunks",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("document_id", sa.String(64), sa.ForeignKey("documents.id", ondelete="CASCADE")),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("keywords_json", sa.JSON()),
    )


def downgrade() -> None:
    for table in [
        "document_chunks",
        "documents",
        "integration_connections",
        "memory_entries",
        "user_preferences",
        "audit_records",
        "approvals",
        "permissions",
        "tool_executions",
        "tool_registry",
        "workflow_executions",
        "workflows",
        "email_metadata",
        "contacts",
        "calendar_events",
        "tasks",
        "projects",
        "messages",
        "conversations",
        "agents",
        "users",
    ]:
        op.drop_table(table)
