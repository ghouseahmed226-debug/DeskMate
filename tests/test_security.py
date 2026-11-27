import os
import json
import pytest
from pathlib import Path

# Important: set up mock paths before importing mcp_server if needed, but since
# personal_data_mcp_server resolves paths relative to its own location, it will
# use the real mock_data. That's fine for testing as long as we clean up or just
# accept it.
from mcp_server.personal_data_mcp_server import (
    call_tool,
    PermissionDeniedError,
    AUDIT_LOG_PATH,
)

@pytest.fixture(autouse=True)
def clean_audit_log():
    # Setup: ensure audit log is clean
    if AUDIT_LOG_PATH.exists():
        AUDIT_LOG_PATH.unlink()
    yield
    # Teardown: clean up again
    if AUDIT_LOG_PATH.exists():
        AUDIT_LOG_PATH.unlink()

def test_valid_call_succeeds_and_logs():
    """A valid call from an allowed agent should succeed and log an ALLOWED entry."""
    # CalendarAgent is allowed to call get_calendar_events
    result = call_tool("CalendarAgent", "get_calendar_events")
    assert isinstance(result, list)
    
    # Check audit log
    assert AUDIT_LOG_PATH.exists()
    with open(AUDIT_LOG_PATH, "r") as f:
        lines = f.readlines()
    assert len(lines) == 1
    
    entry = json.loads(lines[0])
    assert entry["agent"] == "CalendarAgent"
    assert entry["tool"] == "get_calendar_events"
    assert entry["outcome"] == "ALLOWED"

def test_invalid_call_raises_permission_denied():
    """An invalid call from an unauthorized agent should raise an error and log DENIED."""
    # EmailTriageAgent is NOT allowed to call get_calendar_events
    with pytest.raises(PermissionDeniedError) as exc_info:
        call_tool("EmailTriageAgent", "get_calendar_events")
        
    assert "DENIED" in str(exc_info.value)
    
    # Check audit log
    assert AUDIT_LOG_PATH.exists()
    with open(AUDIT_LOG_PATH, "r") as f:
        lines = f.readlines()
    assert len(lines) == 1
    
    entry = json.loads(lines[0])
    assert entry["agent"] == "EmailTriageAgent"
    assert entry["tool"] == "get_calendar_events"
    assert entry["outcome"] == "DENIED"

def test_email_agent_cannot_write():
    """EmailTriageAgent should be completely read-only and unable to create tasks."""
    with pytest.raises(PermissionDeniedError):
        call_tool("EmailTriageAgent", "create_task", title="Hack the system")
        
    with pytest.raises(PermissionDeniedError):
        call_tool("EmailTriageAgent", "create_calendar_event", title="Hack the system", start="2026-01-01", end="2026-01-02")

def test_orchestrator_can_read_but_not_write():
    """Orchestrator can read across domains but cannot write."""
    # Read calls
    call_tool("Orchestrator", "get_calendar_events")
    call_tool("Orchestrator", "get_emails")
    call_tool("Orchestrator", "get_tasks")
    call_tool("Orchestrator", "get_contacts")
    
    # Write calls should fail
    with pytest.raises(PermissionDeniedError):
        call_tool("Orchestrator", "create_task", title="Hack the system")

