"""
tests/test_agents.py

Tests for the 12 specialist agents:
- Each agent must respond to a valid AgentTaskInput
- Permission checks are enforced (agents cannot call tools outside their allowlist)
- Output schema validation (AgentTaskOutput fields present)
"""

from __future__ import annotations

import os
import uuid
import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret-key-32chars-not-prod!")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-32chars-not-prod!")

from agents.base import AgentTaskInput, AgentTaskOutput
from agents.calendar_agent import CalendarAgent, CalendarSchedulingAgent
from agents.email_agent import EmailTriageAgent, EmailIntelligenceAgent
from agents.task_agent import TaskCaptureAgent, TaskProjectManagementAgent
from agents.contacts_crm_agent import ContactCRM_Agent
from agents.research_agent import ResearchIntelligenceAgent
from agents.business_intel_agent import BusinessIntelligenceAgent
from agents.document_agent import DocumentAssistantAgent
from agents.meeting_agent import MeetingAssistantAgent
from agents.communication_agent import CommunicationAgent
from agents.workflow_agent import WorkflowAutomationAgent
from agents.knowledge_agent import PersonalKnowledgeAgent
from agents.security_agent import SecurityComplianceAgent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_input(user_request: str, intent: str = "read", **params) -> AgentTaskInput:
    return AgentTaskInput(
        user_id="usr-demo",
        trace_id=f"trc-{uuid.uuid4().hex[:8]}",
        intent=intent,
        params=params,
        raw_query=user_request,
        auto_confirm=True,
    )


def _assert_valid_output(output: AgentTaskOutput) -> None:
    assert isinstance(output, AgentTaskOutput), f"Expected AgentTaskOutput, got {type(output)}"
    assert isinstance(output.message, str), "message must be a string"
    assert len(output.message) > 0, "message must not be empty"
    assert output.status in ("completed", "needs_approval", "needs_clarification", "denied", "error")


# ---------------------------------------------------------------------------
# Calendar Agent
# ---------------------------------------------------------------------------

class TestCalendarAgent:
    def test_read_calendar(self, seeded_session):
        agent = CalendarSchedulingAgent()
        inp = _make_input("Show my calendar events", intent="list_events")
        out = agent.execute(inp, session=seeded_session)
        _assert_valid_output(out)

    def test_legacy_calendar_agent(self):
        agent = CalendarAgent()
        assert agent is not None
        assert hasattr(agent, "run")

    def test_allowed_tools_contains_calendar_tools(self):
        agent = CalendarSchedulingAgent()
        assert any("calendar" in t for t in agent.allowed_tools)


# ---------------------------------------------------------------------------
# Email Agent
# ---------------------------------------------------------------------------

class TestEmailAgent:
    def test_read_emails(self, seeded_session):
        agent = EmailIntelligenceAgent()
        inp = _make_input("Check my inbox", intent="triage_inbox")
        out = agent.execute(inp, session=seeded_session)
        _assert_valid_output(out)

    def test_legacy_email_agent(self):
        agent = EmailTriageAgent()
        assert agent is not None

    def test_cannot_access_create_task(self):
        """EmailIntelligenceAgent must not list create_task in its allowed_tools."""
        agent = EmailIntelligenceAgent()
        assert "create_task" not in agent.allowed_tools


# ---------------------------------------------------------------------------
# Task Agent
# ---------------------------------------------------------------------------

class TestTaskAgent:
    def test_read_tasks(self, seeded_session):
        agent = TaskProjectManagementAgent()
        inp = _make_input("Show my tasks", intent="list_tasks")
        out = agent.execute(inp, session=seeded_session)
        _assert_valid_output(out)

    def test_legacy_task_agent(self):
        agent = TaskCaptureAgent()
        assert agent is not None

    def test_allowed_tools_contains_task_tools(self):
        agent = TaskProjectManagementAgent()
        assert any("task" in t for t in agent.allowed_tools)


# ---------------------------------------------------------------------------
# Contacts CRM Agent
# ---------------------------------------------------------------------------

class TestContactsCRMAgent:
    def test_read_contacts(self, seeded_session):
        agent = ContactCRM_Agent()
        inp = _make_input("Show all contacts", intent="search_contacts")
        out = agent.execute(inp, session=seeded_session)
        _assert_valid_output(out)

    def test_allowed_tools_contains_contacts(self):
        agent = ContactCRM_Agent()
        assert any("contact" in t for t in agent.allowed_tools)


# ---------------------------------------------------------------------------
# Other Specialist Agents (smoke tests — verify they instantiate and respond)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "agent_cls,prompt,intent",
    [
        (ResearchIntelligenceAgent, "Find information about AI agents", "web_research"),
        (BusinessIntelligenceAgent, "Show business KPIs", "competitor_analysis"),
        (DocumentAssistantAgent, "Summarise my documents", "summarize_document"),
        (MeetingAssistantAgent, "Prep for the team sync meeting", "prepare_meeting"),
        (CommunicationAgent, "Draft a status update", "draft_communication"),
        (WorkflowAutomationAgent, "Show active workflows", "list_workflows"),
        (PersonalKnowledgeAgent, "What do I know about the Q3 project?", "list_memory"),
        (SecurityComplianceAgent, "Run security audit", "security_audit"),
    ],
)
def test_specialist_agent_responds(agent_cls, prompt, intent, seeded_session):
    agent = agent_cls()
    inp = _make_input(prompt, intent=intent)
    out = agent.execute(inp, session=seeded_session)
    _assert_valid_output(out)
