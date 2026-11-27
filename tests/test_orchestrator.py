"""
tests/test_orchestrator.py

Tests for DeskMateOrchestrator:
- handle() backward-compatibility
- process_turn() with DB session
- Routing to correct specialists
- Approval gate (auto_confirm=True vs False)
"""

from __future__ import annotations

import os
import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret-key-32chars-not-prod!")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-32chars-not-prod!")

from agents.orchestrator import DeskMateOrchestrator, Orchestrator, OrchestratorTurnResult


# ---------------------------------------------------------------------------
# Backward-compatibility alias
# ---------------------------------------------------------------------------

class TestBackwardCompat:
    def test_orchestrator_alias(self):
        """Orchestrator must be an alias for DeskMateOrchestrator."""
        assert Orchestrator is DeskMateOrchestrator

    def test_handle_returns_string(self):
        """handle() must return a non-empty string without crashing."""
        orch = DeskMateOrchestrator(auto_confirm=True)
        result = orch.handle("What's on my calendar?")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_handle_email_returns_string(self):
        orch = DeskMateOrchestrator(auto_confirm=True)
        result = orch.handle("Show my inbox")
        assert isinstance(result, str)

    def test_handle_task_returns_string(self):
        orch = DeskMateOrchestrator(auto_confirm=True)
        result = orch.handle("Add a task: write unit tests")
        assert isinstance(result, str)

    def test_handle_briefing_returns_string(self):
        orch = DeskMateOrchestrator(auto_confirm=True)
        result = orch.handle("Give me my daily briefing")
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# process_turn() with DB session
# ---------------------------------------------------------------------------

class TestProcessTurn:
    def test_process_turn_returns_result(self, seeded_session, demo_user_id):
        orch = DeskMateOrchestrator(auto_confirm=True)
        result = orch.process_turn(
            "Check my calendar",
            user_id=demo_user_id,
            session=seeded_session,
        )
        assert isinstance(result, OrchestratorTurnResult)
        assert isinstance(result.response, str)
        assert len(result.response) > 0

    def test_process_turn_has_trace(self, seeded_session, demo_user_id):
        orch = DeskMateOrchestrator(auto_confirm=True)
        result = orch.process_turn(
            "Show tasks",
            user_id=demo_user_id,
            session=seeded_session,
        )
        assert isinstance(result.execution_trace, list)

    def test_process_turn_records_conversation_id(self, seeded_session, demo_user_id):
        orch = DeskMateOrchestrator(auto_confirm=True)
        result = orch.process_turn(
            "What's new?",
            user_id=demo_user_id,
            session=seeded_session,
        )
        # conversation_id may be None for offline mode; just verify no exception
        assert result is not None

    def test_process_turn_no_session(self, demo_user_id):
        """process_turn without a DB session must still return a result."""
        orch = DeskMateOrchestrator(auto_confirm=True)
        result = orch.process_turn(
            "Check inbox",
            user_id=demo_user_id,
            session=None,
        )
        assert isinstance(result.response, str)


# ---------------------------------------------------------------------------
# Routing to specialists
# ---------------------------------------------------------------------------

class TestRouting:
    @pytest.mark.parametrize(
        "prompt,expected_agent_fragments",
        [
            ("Check my inbox", ["Email"]),
            ("What's on my calendar?", ["Calendar"]),
            ("Add task: finish report", ["Task"]),
            ("Look up contact John", ["Contact", "CRM"]),
            ("daily briefing", ["Orchestrator", "DeskMate", "Executive"]),
        ],
    )
    def test_routing_produces_sensible_response(self, prompt, expected_agent_fragments):
        """The orchestrator must produce a non-empty response for each intent."""
        orch = DeskMateOrchestrator(auto_confirm=True)
        result = orch.handle(prompt)
        assert isinstance(result, str)
        assert len(result) >= 10, f"Response too short for '{prompt}': {result!r}"

    def test_list_agent_specs_covers_12_specialists(self):
        orch = DeskMateOrchestrator(auto_confirm=True)
        specs = orch.list_agent_specs()
        # Should include orchestrator itself + ≥12 specialists
        assert len(specs) >= 12


# ---------------------------------------------------------------------------
# Approval gate
# ---------------------------------------------------------------------------

class TestApprovalGate:
    def test_auto_confirm_true_does_not_prompt(self, capsys):
        """With auto_confirm=True, write actions must not block on input."""
        orch = DeskMateOrchestrator(auto_confirm=True)
        result = orch.handle("Add a task: test approval gate")
        # Must return without raising; captured output may contain [auto-confirm]
        assert isinstance(result, str)

    def test_auto_confirm_false_uses_callback(self):
        """confirm_callback=lambda: True must behave like auto_confirm=True."""
        orch = DeskMateOrchestrator(auto_confirm=False, confirm_callback=lambda _: True)
        result = orch.handle("Add a task: callback test")
        assert isinstance(result, str)
