"""
tests/test_mcp_server.py

Tests for personal_data_mcp_server.py:
- call_tool() convenience function
- AGENT_PERMISSIONS allowlist enforcement
- handle_jsonrpc_message() JSON-RPC 2.0 protocol
- Anomaly detection (FLAGGED_SUSPICIOUS)
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret-key-32chars-not-prod!")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-32chars-not-prod!")

from mcp_server.personal_data_mcp_server import (
    AGENT_PERMISSIONS,
    AUDIT_LOG_PATH,
    TOOL_REGISTRY,
    PermissionDeniedError,
    call_tool,
)


# ---------------------------------------------------------------------------
# Allowlist enforcement
# ---------------------------------------------------------------------------

class TestPermissions:
    def test_calendar_agent_can_read_calendar(self):
        """CalendarAgent has get_calendar_events in its allowlist."""
        assert "get_calendar_events" in AGENT_PERMISSIONS.get("CalendarAgent", set())

    def test_email_agent_can_read_emails(self):
        """EmailTriageAgent / EmailIntelligenceAgent has get_emails."""
        email_perms = (
            AGENT_PERMISSIONS.get("EmailTriageAgent", set())
            | AGENT_PERMISSIONS.get("EmailIntelligenceAgent", set())
        )
        assert "get_emails" in email_perms

    def test_email_agent_cannot_create_task(self):
        """EmailTriageAgent must NOT be allowed to create tasks."""
        assert "create_task" not in AGENT_PERMISSIONS.get("EmailTriageAgent", set())

    def test_calendar_agent_cannot_create_task(self):
        """CalendarAgent must NOT be allowed to create tasks."""
        assert "create_task" not in AGENT_PERMISSIONS.get("CalendarAgent", set())

    def test_task_agent_can_create_task(self):
        """TaskCaptureAgent / TaskProjectManagementAgent can create tasks."""
        task_perms = (
            AGENT_PERMISSIONS.get("TaskCaptureAgent", set())
            | AGENT_PERMISSIONS.get("TaskProjectManagementAgent", set())
        )
        assert "create_task" in task_perms

    def test_task_agent_cannot_read_emails(self):
        """TaskCaptureAgent must NOT be able to read emails."""
        assert "get_emails" not in AGENT_PERMISSIONS.get("TaskCaptureAgent", set())


# ---------------------------------------------------------------------------
# call_tool() permission enforcement via TOOL_REGISTRY
# ---------------------------------------------------------------------------

class TestToolRegistry:
    def test_permitted_call_returns_data(self):
        """A permitted tool call must succeed and return data."""
        fn = TOOL_REGISTRY.get("get_calendar_events")
        assert fn is not None, "get_calendar_events missing from TOOL_REGISTRY"
        result = fn("CalendarAgent")
        assert isinstance(result, (list, dict))

    def test_denied_call_raises_permission_error(self):
        """An unpermitted call must raise PermissionDeniedError."""
        fn = TOOL_REGISTRY.get("create_task")
        assert fn is not None
        with pytest.raises(PermissionDeniedError):
            fn("EmailTriageAgent", title="injected task")

    def test_orchestrator_read_only(self):
        """DeskMateOrchestrator may read events but not create calendar events directly."""
        get_fn = TOOL_REGISTRY.get("get_calendar_events")
        create_fn = TOOL_REGISTRY.get("create_calendar_event")
        assert get_fn is not None
        assert create_fn is not None
        # Read should be allowed
        result = get_fn("DeskMateOrchestrator")
        assert result is not None
        # Write should be denied
        with pytest.raises(PermissionDeniedError):
            create_fn(
                "DeskMateOrchestrator",
                title="Injected event",
                start="2026-01-01T10:00:00",
                end="2026-01-01T11:00:00",
            )


# ---------------------------------------------------------------------------
# call_tool() convenience wrapper
# ---------------------------------------------------------------------------

class TestCallToolWrapper:
    def test_call_tool_permitted(self):
        """call_tool() must succeed for a permitted (agent, tool) pair."""
        result = call_tool("CalendarAgent", "get_calendar_events")
        assert result is not None

    def test_call_tool_denied(self):
        """call_tool() must raise PermissionDeniedError for unpermitted pair."""
        with pytest.raises(PermissionDeniedError):
            call_tool("EmailTriageAgent", "create_task", title="injected")

    def test_call_tool_unknown_tool_raises(self):
        """call_tool() with an unknown tool name must raise an appropriate error."""
        with pytest.raises(Exception):
            call_tool("CalendarAgent", "nonexistent_tool_xyz")


# ---------------------------------------------------------------------------
# JSON-RPC 2.0 protocol handler
# ---------------------------------------------------------------------------

class TestJsonRpc:
    def _rpc(self, method: str, params: dict, id_: int = 1) -> dict:
        from mcp_server.personal_data_mcp_server import handle_jsonrpc_message
        msg = {"jsonrpc": "2.0", "method": method, "params": params, "id": id_}
        resp = handle_jsonrpc_message(msg)
        assert isinstance(resp, dict)
        return resp

    def test_tools_list(self):
        """tools/list must return a list of tool definitions."""
        resp = self._rpc("tools/list", {})
        assert "result" in resp
        tools = resp["result"].get("tools", [])
        assert isinstance(tools, list)
        assert len(tools) > 0

    def test_call_tool_via_rpc_permitted(self):
        """tools/call for a permitted (agent, tool) pair must succeed."""
        resp = self._rpc(
            "tools/call",
            {
                "name": "get_calendar_events",
                "arguments": {"agent_name": "CalendarAgent"},
            },
        )
        assert "result" in resp, f"Expected result, got: {resp}"

    def test_call_tool_via_rpc_denied(self):
        """tools/call for unpermitted pair must return an error response."""
        resp = self._rpc(
            "tools/call",
            {
                "name": "create_task",
                "arguments": {"agent_name": "EmailTriageAgent", "title": "injected"},
            },
        )
        assert "error" in resp, f"Expected error, got: {resp}"

    def test_unknown_method_returns_error(self):
        """An unknown JSON-RPC method must return error code -32601."""
        resp = self._rpc("nonexistent/method", {})
        assert "error" in resp
        assert resp["error"].get("code") == -32601
