"""
tests/test_tools.py

Tests for the UnifiedToolRegistry (tools/registry.py):
- Permission checks (check_permission)
- Tool discovery (discover)
- execute() with timeout / cost tracking
- AGENT_ALLOWLISTS covers all 12 specialists
"""

from __future__ import annotations

import os
import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret-key-32chars-not-prod!")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-32chars-not-prod!")

from tools.registry import (
    AGENT_ALLOWLISTS,
    PermissionDeniedError,
    ToolMetadata,
    UnifiedToolRegistry,
    get_tool_registry,
)


# ---------------------------------------------------------------------------
# AGENT_ALLOWLISTS coverage
# ---------------------------------------------------------------------------

class TestAgentAllowlists:
    EXPECTED_AGENTS = [
        "DeskMateOrchestrator",
        "CalendarSchedulingAgent",
        "EmailIntelligenceAgent",
        "TaskProjectManagementAgent",
        "ContactCRM_Agent",
        "ResearchIntelligenceAgent",
        "BusinessIntelligenceAgent",
        "DocumentAssistantAgent",
        "MeetingAssistantAgent",
        "CommunicationAgent",
        "WorkflowAutomationAgent",
        "PersonalKnowledgeAgent",
        "SecurityComplianceAgent",
        # Legacy aliases
        "CalendarAgent",
        "EmailTriageAgent",
        "TaskCaptureAgent",
    ]

    def test_all_expected_agents_in_allowlist(self):
        for agent in self.EXPECTED_AGENTS:
            assert agent in AGENT_ALLOWLISTS, f"Missing allowlist for: {agent}"

    def test_no_agent_has_empty_allowlist(self):
        for agent, tools in AGENT_ALLOWLISTS.items():
            assert len(tools) > 0, f"Agent {agent} has empty allowlist"

    def test_email_agent_read_only(self):
        """EmailIntelligenceAgent must not have any write-action tools."""
        write_tools = {"create_calendar_event", "create_task", "update_task", "update_calendar_event"}
        email_tools = AGENT_ALLOWLISTS.get("EmailIntelligenceAgent", set())
        overlap = write_tools & email_tools
        assert not overlap, f"EmailIntelligenceAgent must not have write tools: {overlap}"

    def test_calendar_agent_no_task_tools(self):
        calendar_tools = AGENT_ALLOWLISTS.get("CalendarAgent", set())
        assert "create_task" not in calendar_tools


# ---------------------------------------------------------------------------
# UnifiedToolRegistry
# ---------------------------------------------------------------------------

class TestUnifiedToolRegistry:
    @pytest.fixture
    def registry(self) -> UnifiedToolRegistry:
        return get_tool_registry()

    def test_registry_has_tools(self, registry: UnifiedToolRegistry):
        tools = registry.discover()
        assert len(tools) > 0

    def test_discover_returns_tool_metadata(self, registry: UnifiedToolRegistry):
        tools = registry.discover()
        for t in tools:
            assert isinstance(t, ToolMetadata)

    def test_check_permission_permitted(self, registry: UnifiedToolRegistry):
        """check_permission must not raise for a permitted (agent, tool) pair."""
        # CalendarAgent → get_calendar_events is always permitted
        try:
            registry.check_permission("CalendarAgent", "get_calendar_events")
        except PermissionDeniedError:
            pytest.fail("check_permission raised for a permitted tool call")

    def test_check_permission_denied(self, registry: UnifiedToolRegistry):
        """check_permission must raise PermissionDeniedError for unpermitted pair."""
        with pytest.raises(PermissionDeniedError):
            registry.check_permission("EmailTriageAgent", "create_task")

    def test_execute_permitted_tool(self):
        """execute() must return a result for a permitted, registered tool."""
        reg = UnifiedToolRegistry()
        reg.register(
            ToolMetadata(
                name="get_calendar_events",
                category="calendar",
                description="List calendar events",
                is_write=False,
            ),
            lambda **kwargs: [{"id": "evt-1", "title": "Sync"}],
        )
        result = reg.execute("CalendarAgent", "get_calendar_events", {})
        assert isinstance(result, list) and len(result) == 1

    def test_execute_denied_tool_raises(self, registry: UnifiedToolRegistry):
        """execute() must raise PermissionDeniedError for unpermitted tool."""
        with pytest.raises(PermissionDeniedError):
            registry.execute("EmailTriageAgent", "create_task", {"title": "injected"})

    def test_discover_by_category(self, registry: UnifiedToolRegistry):
        """discover() must support filtering by category."""
        calendar_tools = registry.discover(category="calendar")
        assert all(t.category == "calendar" for t in calendar_tools)

    def test_tool_has_timeout(self, registry: UnifiedToolRegistry):
        """Every tool must have a timeout_sec > 0."""
        for t in registry.discover():
            assert t.timeout_sec > 0, f"Tool {t.name} has invalid timeout"
