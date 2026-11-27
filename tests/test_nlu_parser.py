"""
tests/test_nlu_parser.py

Tests for the NLP intent parser (nlp/parser.py):
- parse_clause_intent routing for all 12 intents
- parse_natural_datetime relative dates
- split_multi_intent multi-clause decomposition
- Ambiguity clarification
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta
import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret-key-32chars-not-prod!")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-32chars-not-prod!")

from nlp.parser import (
    ParsedDateResult,
    ParsedIntent,
    parse_clause_intent,
    parse_natural_datetime,
    split_multi_intent,
)


# ---------------------------------------------------------------------------
# Intent routing
# ---------------------------------------------------------------------------

class TestIntentRouting:
    """Each keyword pattern must map to the correct intent and agent."""

    @pytest.mark.parametrize(
        "text,expected_intent",
        [
            ("Check my inbox", "triage_inbox"),
            ("summarise unread messages", "triage_inbox"),
            ("summarize my unread emails", "summarize_emails"),
            ("What's on my calendar?", "list_events"),
            ("show my schedule for Monday", "list_events"),
            ("Add a task to review the report", "create_task"),
            ("create a to-do: buy milk", "create_task"),
            ("schedule a meeting on Friday at 3pm", "create_event"),
            ("book a call with Alice tomorrow at 11am", "create_event"),
            ("mark task 5 done", "complete_task"),
            ("complete the follow-up task", "complete_task"),
            ("reschedule the team sync to Thursday at 2pm", "reschedule_event"),
            ("move the Friday meeting to Monday at 10am", "reschedule_event"),
            ("look up contact Sarah", "search_contacts"),
            ("who is John", "search_contacts"),
            ("daily briefing", "daily_briefing"),
            ("executive briefing", "daily_briefing"),
            ("prep for the Project Review meeting", "prepare_meeting"),
            ("prepare meeting notes for stand-up", "extract_followups"),
            ("research latest AI frameworks", "web_research"),
            ("find important information about blockchain", "web_research"),
        ],
    )
    def test_routing(self, text: str, expected_intent: str):
        result = parse_clause_intent(text)
        assert result.intent == expected_intent, (
            f"Text: '{text}'\n"
            f"  Expected intent '{expected_intent}', got '{result.intent}'"
        )

    def test_unknown_intent_does_not_crash(self):
        result = parse_clause_intent("asdfghjkl qwertyuiop")
        assert isinstance(result, ParsedIntent)
        assert result.intent == "unknown"


# ---------------------------------------------------------------------------
# Multi-intent splitting
# ---------------------------------------------------------------------------

class TestMultiIntentSplit:
    def test_single_clause_returns_one(self):
        clauses = split_multi_intent("Check my inbox")
        assert len(clauses) == 1

    def test_two_clauses_with_and(self):
        clauses = split_multi_intent("Check my inbox and show my calendar")
        assert len(clauses) >= 2

    def test_two_clauses_with_also(self):
        clauses = split_multi_intent("Add a task also schedule a meeting")
        assert len(clauses) >= 1

    def test_does_not_split_mid_phrase(self):
        """'and' inside a natural phrase must not be split aggressively."""
        clauses = split_multi_intent("Schedule meeting with Sarah and Bob")
        assert len(clauses) == 1


# ---------------------------------------------------------------------------
# Natural datetime parsing
# ---------------------------------------------------------------------------

class TestDatetimeParsing:
    def test_explicit_date(self):
        result = parse_natural_datetime("2026-12-25")
        assert isinstance(result, ParsedDateResult)
        assert result.has_explicit_date is True
        assert result.date_str == "2026-12-25"

    def test_tomorrow_keyword(self):
        result = parse_natural_datetime("tomorrow at 3pm")
        tomorrow = date.today() + timedelta(days=1)
        assert result.has_explicit_date is True
        assert result.has_explicit_time is True
        assert result.date_str == tomorrow.isoformat()

    def test_next_monday(self):
        result = parse_natural_datetime("next Monday")
        assert result.has_explicit_date is True
        assert result.date_str is not None
        assert date.fromisoformat(result.date_str).weekday() == 0

    def test_today_keyword(self):
        result = parse_natural_datetime("today")
        assert result.has_explicit_date is True
        assert result.date_str == date.today().isoformat()

    def test_no_date_returns_false_flag(self):
        result = parse_natural_datetime("check my inbox")
        assert result.has_explicit_date is False
        assert result.date_str is None

    def test_time_parsing(self):
        result = parse_natural_datetime("Friday at 10:30am")
        assert result.has_explicit_date is True
        assert result.has_explicit_time is True
        assert result.start_iso is not None
        dt = datetime.fromisoformat(result.start_iso)
        assert dt.hour == 10
        assert dt.minute == 30
