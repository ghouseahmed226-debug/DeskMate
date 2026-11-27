"""Unified capability-based Tool Registry supporting 25 tool categories,
JSON Schema validation, least-privilege permissions, principal verification,
timeout protection, cost transparency, and audit logging.
"""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Set

import jsonschema
from pydantic import BaseModel, Field

from core.config import get_settings
from core.security import AgentPrincipal, redact_pii, sanitize_error

# All 25 ecosystem tool categories defined in the DeskMate specification
TOOL_CATEGORIES: List[str] = [
    "email",
    "calendar",
    "contacts",
    "tasks",
    "productivity",
    "web_search",
    "research",
    "business_intelligence",
    "crm",
    "documents",
    "databases",
    "spreadsheets",
    "communication",
    "automation",
    "ai_models",
    "image_generation",
    "video_generation",
    "audio_voice",
    "translation",
    "analytics",
    "cloud_services",
    "developer_tools",
    "project_management",
    "knowledge_management",
    "notifications",
]


class PermissionDeniedError(Exception):
    """Raised when an agent attempts to execute an unauthorized tool."""


class ToolValidationError(Exception):
    """Raised when tool input fails JSON Schema validation."""


class ToolExecutionError(Exception):
    """Raised when tool execution fails or times out."""


class ApprovalRequiredError(Exception):
    """Raised when a sensitive mutating tool is called without approval."""


class ToolMetadata(BaseModel):
    name: str
    category: str
    description: str
    capabilities: List[str] = Field(default_factory=list)
    provider: str = "local"
    input_schema: Dict[str, Any] = Field(default_factory=lambda: {"type": "object", "properties": {}})
    output_schema: Dict[str, Any] = Field(default_factory=lambda: {"type": "object", "properties": {}})
    requires_approval: bool = False
    is_write: bool = False
    cost_estimate_usd: float = 0.0
    timeout_sec: int = 15
    enabled: bool = True
    requires_connection: Optional[str] = None


# Centralized Least-Privilege Allowlist across DeskMateOrchestrator + 12 Specialist Agents
# Plus backward-compatible legacy aliases (Orchestrator, CalendarAgent, EmailTriageAgent, TaskCaptureAgent)
AGENT_ALLOWLISTS: Dict[str, Set[str]] = {
    # Legacy names preserved for backward compatibility
    "Orchestrator": {"get_calendar_events", "get_emails", "get_tasks", "get_contacts"},
    "CalendarAgent": {"get_calendar_events", "create_calendar_event", "update_calendar_event"},
    "EmailTriageAgent": {"get_emails", "mark_email_read"},
    "TaskCaptureAgent": {"create_task", "get_tasks", "update_task"},
    # Upgraded 12-specialist & Orchestrator allowlists
    "DeskMateOrchestrator": {
        "get_calendar_events",
        "get_emails",
        "get_tasks",
        "get_contacts",
        "discover_tools",
    },
    "EmailIntelligenceAgent": {
        "get_emails",
        "search_emails",
        "triage_emails",
        "mark_email_read",
        "draft_email",
        "send_email_approved",
    },
    "CalendarSchedulingAgent": {
        "get_calendar_events",
        "find_free_slots",
        "create_calendar_event",
        "update_calendar_event",
        "cancel_calendar_event",
    },
    "TaskProjectManagementAgent": {
        "get_tasks",
        "create_task",
        "update_task",
        "delete_task",
        "get_projects",
        "create_project",
    },
    "ContactCRM_Agent": {
        "get_contacts",
        "search_contacts",
        "create_contact",
        "update_contact",
    },
    "ResearchIntelligenceAgent": {
        "web_search",
        "fetch_web_page",
    },
    "BusinessIntelligenceAgent": {
        "web_search",
        "fetch_web_page",
        "search_contacts",
        "analyze_company_data",
    },
    "DocumentAssistantAgent": {
        "list_documents",
        "query_document_chunks",
        "summarize_document_chunks",
    },
    "MeetingAssistantAgent": {
        "get_calendar_events",
        "get_contacts",
        "get_emails",
        "create_calendar_event",
        "create_task",
        "draft_email",
    },
    "CommunicationAgent": {
        "draft_email",
        "send_email_approved",
        "post_slack_message_approved",
    },
    "WorkflowAutomationAgent": {
        "list_workflows",
        "run_workflow_step",
        "get_calendar_events",
        "get_emails",
        "get_tasks",
        "create_task",
        "draft_email",
    },
    "PersonalKnowledgeAgent": {
        "list_memory",
        "save_memory",
        "delete_memory",
        "export_memory",
    },
    "SecurityComplianceAgent": {
        "read_audit_records",
        "get_permission_matrix",
        "scan_text_security",
    },
}


class UnifiedToolRegistry:
    """Extensible registry with discovery, schema validation, permission gates, and telemetry."""

    def __init__(self) -> None:
        self._tools: Dict[str, ToolMetadata] = {}
        self._handlers: Dict[str, Callable[..., Any]] = {}
        self._audit_hooks: List[Callable[[Dict[str, Any]], None]] = []
        self._executor = ThreadPoolExecutor(max_workers=8)
        self._seed_catalog_adapters()

    def _seed_catalog_adapters(self) -> None:
        """Registers capability descriptors across the 25 supported ecosystem categories.
        External cloud tools are disabled unless an integration adapter activates them.
        """
        optional_catalog = [
            ToolMetadata(
                name="post_slack_message_approved",
                category="communication",
                description="Post a message to a Slack channel after explicit user approval.",
                capabilities=["slack_post", "team_messaging"],
                provider="slack_oauth",
                requires_approval=True,
                is_write=True,
                enabled=False,
                requires_connection="slack",
            ),
            ToolMetadata(
                name="notion_query_database",
                category="knowledge_management",
                description="Query Notion pages or databases via connected Notion OAuth integration.",
                capabilities=["notion_search", "knowledge_lookup"],
                provider="notion_oauth",
                enabled=False,
                requires_connection="notion",
            ),
            ToolMetadata(
                name="github_list_issues",
                category="developer_tools",
                description="List GitHub repository issues via connected GitHub integration.",
                capabilities=["github_issues", "repo_tracking"],
                provider="github_oauth",
                enabled=False,
                requires_connection="github",
            ),
            ToolMetadata(
                name="spreadsheet_export_csv",
                category="spreadsheets",
                description="Export structured tabular reports to CSV.",
                capabilities=["csv_export", "tabular_report"],
                provider="local",
                enabled=True,
            ),
            ToolMetadata(
                name="translate_text",
                category="translation",
                description="Translate business communications via configured LLM adapter.",
                capabilities=["translation", "multilingual"],
                provider="llm_adapter",
                cost_estimate_usd=0.001,
                enabled=True,
            ),
            ToolMetadata(
                name="analytics_productivity_summary",
                category="analytics",
                description="Compute task completion, overdue ratios, and calendar load metrics.",
                capabilities=["productivity_analytics", "metrics"],
                provider="local",
                enabled=True,
            ),
            ToolMetadata(
                name="image_generation_concept",
                category="image_generation",
                description="Optional external image generation provider adapter (requires external API key).",
                capabilities=["image_create"],
                provider="external_ai",
                cost_estimate_usd=0.04,
                enabled=False,
                requires_connection="openai",
            ),
            ToolMetadata(
                name="video_generation_brief",
                category="video_generation",
                description="Optional external video generation provider adapter (unconfigured).",
                capabilities=["video_create"],
                provider="external_ai",
                cost_estimate_usd=0.25,
                enabled=False,
                requires_connection="external_video",
            ),
            ToolMetadata(
                name="audio_transcription_adapter",
                category="audio_voice",
                description="Optional audio meeting transcription adapter (unconfigured).",
                capabilities=["audio_transcribe"],
                provider="external_ai",
                cost_estimate_usd=0.01,
                enabled=False,
                requires_connection="openai",
            ),
            ToolMetadata(
                name="cloud_storage_drive_list",
                category="cloud_services",
                description="List authorized files from Google Drive.",
                capabilities=["drive_list", "cloud_files"],
                provider="google_oauth",
                enabled=False,
                requires_connection="google_drive",
            ),
            ToolMetadata(
                name="database_sql_readonly_inspect",
                category="databases",
                description="Inspect authorized workspace record counts from DeskMate SQLAlchemy DB.",
                capabilities=["db_metrics", "sql_inspect"],
                provider="sqlalchemy",
                enabled=True,
            ),
            ToolMetadata(
                name="send_notification_alert",
                category="notifications",
                description="Send an in-app notification or reminder to the authenticated user.",
                capabilities=["notify", "reminder"],
                provider="local",
                enabled=True,
            ),
        ]
        for meta in optional_catalog:
            self._tools[meta.name] = meta

    def register(self, metadata: ToolMetadata, handler: Callable[..., Any]) -> None:
        if metadata.category not in TOOL_CATEGORIES:
            raise ValueError(f"Unsupported tool category: {metadata.category}")
        self._tools[metadata.name] = metadata
        self._handlers[metadata.name] = handler

    def add_audit_hook(self, hook: Callable[[Dict[str, Any]], None]) -> None:
        self._audit_hooks.append(hook)

    def _emit_audit(self, event: Dict[str, Any]) -> None:
        for hook in self._audit_hooks:
            try:
                hook(event)
            except Exception:
                pass

    def discover(
        self,
        *,
        category: Optional[str] = None,
        capability: Optional[str] = None,
        query: Optional[str] = None,
        agent_name: Optional[str] = None,
        include_disabled: bool = True,
    ) -> List[ToolMetadata]:
        allowed = AGENT_ALLOWLISTS.get(agent_name) if agent_name else None
        results: List[ToolMetadata] = []
        for meta in self._tools.values():
            if not include_disabled and not meta.enabled:
                continue
            if category and meta.category != category:
                continue
            if capability and capability not in meta.capabilities:
                continue
            if allowed is not None and meta.name not in allowed:
                continue
            if query:
                q = query.lower()
                hay = f"{meta.name} {meta.category} {meta.description} {' '.join(meta.capabilities)}".lower()
                if q not in hay:
                    continue
            results.append(meta)
        return sorted(results, key=lambda m: (m.category, m.name))

    def get_metadata(self, tool_name: str) -> Optional[ToolMetadata]:
        return self._tools.get(tool_name)

    def check_permission(
        self,
        agent_name: str,
        tool_name: str,
        *,
        principal: Optional[AgentPrincipal] = None,
        require_principal: bool = False,
        trace_id: str = "",
        user_id: Optional[str] = None,
    ) -> None:
        if principal is not None:
            if not principal.verify() or principal.agent_name != agent_name:
                self._emit_audit(
                    {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "user_id": user_id,
                        "trace_id": trace_id,
                        "agent": agent_name,
                        "tool": tool_name,
                        "outcome": "DENIED",
                        "detail": "Invalid or spoofed AgentPrincipal signature",
                    }
                )
                raise PermissionDeniedError("DENIED: Invalid AgentPrincipal authentication token.")
        elif require_principal:
            raise PermissionDeniedError("DENIED: Missing required signed AgentPrincipal token.")

        allowed_tools = AGENT_ALLOWLISTS.get(agent_name, set())
        if tool_name not in allowed_tools:
            self._emit_audit(
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "user_id": user_id,
                    "trace_id": trace_id,
                    "agent": agent_name,
                    "tool": tool_name,
                    "outcome": "DENIED",
                    "detail": f"{agent_name} is not authorized to call {tool_name}",
                }
            )
            raise PermissionDeniedError(
                f"DENIED: '{agent_name}' is not authorized to call '{tool_name}'. "
                f"Allowed tools: {sorted(allowed_tools)}"
            )

    def execute(
        self,
        agent_name: str,
        tool_name: str,
        params: Optional[Dict[str, Any]] = None,
        *,
        principal: Optional[AgentPrincipal] = None,
        require_principal: bool = False,
        approval_id: Optional[str] = None,
        user_id: Optional[str] = None,
        trace_id: str = "",
    ) -> Any:
        args = params or {}
        self.check_permission(
            agent_name,
            tool_name,
            principal=principal,
            require_principal=require_principal,
            trace_id=trace_id,
            user_id=user_id,
        )

        meta = self._tools.get(tool_name)
        handler = self._handlers.get(tool_name)
        if not meta or not handler:
            if meta and not meta.enabled:
                raise ToolExecutionError(
                    f"Tool '{tool_name}' requires connecting '{meta.requires_connection}' integration first."
                )
            raise ValueError(f"Unknown or unbound tool: {tool_name}")

        if not meta.enabled:
            raise ToolExecutionError(
                f"Tool '{tool_name}' is currently disabled (missing configuration: {meta.requires_connection})."
            )

        try:
            jsonschema.validate(instance=args, schema=meta.input_schema)
        except jsonschema.ValidationError as exc:
            raise ToolValidationError(f"Invalid parameters for '{tool_name}': {exc.message}") from exc

        if meta.requires_approval and not approval_id:
            raise ApprovalRequiredError(
                f"Tool '{tool_name}' requires explicit user approval before execution."
            )

        started = time.perf_counter()
        future = self._executor.submit(handler, **args)
        try:
            result = future.result(timeout=meta.timeout_sec)
        except FuturesTimeoutError as exc:
            future.cancel()
            raise ToolExecutionError(f"Tool '{tool_name}' timed out after {meta.timeout_sec}s.") from exc
        except Exception as exc:
            self._emit_audit(
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "user_id": user_id,
                    "trace_id": trace_id,
                    "agent": agent_name,
                    "tool": tool_name,
                    "params": redact_pii(args),
                    "outcome": "ERROR",
                    "approval_state": "approved" if approval_id else "not_required",
                    "detail": sanitize_error(exc),
                }
            )
            raise

        duration_ms = round((time.perf_counter() - started) * 1000.0, 2)
        self._emit_audit(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "user_id": user_id,
                "trace_id": trace_id,
                "agent": agent_name,
                "tool": tool_name,
                "params": redact_pii(args),
                "outcome": "ALLOWED",
                "approval_state": "approved" if approval_id else "not_required",
                "duration_ms": duration_ms,
                "cost_usd": meta.cost_estimate_usd,
                "detail": "",
            }
        )
        return result


_GLOBAL_REGISTRY: Optional[UnifiedToolRegistry] = None


def get_tool_registry() -> UnifiedToolRegistry:
    global _GLOBAL_REGISTRY
    if _GLOBAL_REGISTRY is None:
        _GLOBAL_REGISTRY = UnifiedToolRegistry()
    return _GLOBAL_REGISTRY
