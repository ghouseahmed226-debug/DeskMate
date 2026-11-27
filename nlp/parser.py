"""Deterministic & LLM-assisted NLU parser for DeskMate AI.

Handles:
- Relative dates ("today", "tomorrow", "next Monday", "this Friday", "in 3 days")
- Times & durations ("at 2pm", "at 14:30", "for 45 minutes")
- Multi-intent splitting ("Check my inbox and remind me to submit the report")
- Structured entity extraction (emails, names, companies, priorities, categories)
- Ambiguity detection (returns clarification prompts rather than inventing facts)
"""

from __future__ import annotations

import re
from datetime import datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from dateutil import parser as date_parser
from pydantic import BaseModel, Field

_WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_TIME_RE = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", re.I)
_ISO_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_DURATION_RE = re.compile(r"\bfor\s+(\d+)\s*(min|mins|minute|minutes|hr|hrs|hour|hours)\b", re.I)
_ID_RE = re.compile(r"\b((?:evt|task|em|cnt|wf|doc|proj|demo-[a-z]+)-[a-z0-9-]+)\b", re.I)


class ParsedIntent(BaseModel):
    raw_clause: str
    agent: str
    intent: str
    params: Dict[str, Any] = Field(default_factory=dict)
    confidence: float = 0.85
    needs_clarification: bool = False
    clarification_question: Optional[str] = None
    requires_confirmation: bool = False


class ParsedDateResult(BaseModel):
    date_str: Optional[str] = None
    start_iso: Optional[str] = None
    end_iso: Optional[str] = None
    has_explicit_date: bool = False
    has_explicit_time: bool = False
    timezone_name: str = "UTC"


def _get_tz(tz_name: str) -> timezone | ZoneInfo:
    try:
        return ZoneInfo(tz_name)
    except Exception:
        return timezone.utc


def parse_natural_datetime(
    text: str,
    *,
    now: Optional[datetime] = None,
    tz_name: str = "UTC",
    default_duration_min: int = 60,
) -> ParsedDateResult:
    """Parses relative dates and explicit times without inventing unmentioned dates."""
    tz = _get_tz(tz_name)
    ref = now.astimezone(tz) if now else datetime.now(tz)
    lower = text.lower()

    target_date = None
    has_date = False

    iso_match = _ISO_DATE_RE.search(text)
    if iso_match:
        target_date = datetime.strptime(iso_match.group(1), "%Y-%m-%d").date()
        has_date = True
    elif re.search(r"\btoday\b|\btonight\b", lower):
        target_date = ref.date()
        has_date = True
    elif re.search(r"\btomorrow\b", lower):
        target_date = (ref + timedelta(days=1)).date()
        has_date = True
    elif re.search(r"\byesterday\b", lower):
        target_date = (ref - timedelta(days=1)).date()
        has_date = True
    elif m_in := re.search(r"\bin\s+(\d+)\s+days?\b", lower):
        target_date = (ref + timedelta(days=int(m_in.group(1)))).date()
        has_date = True
    else:
        for day_name, day_idx in _WEEKDAYS.items():
            m_wd = re.search(rf"\b(?:(next|this)\s+)?{day_name}\b", lower)
            if m_wd:
                qualifier = m_wd.group(1)
                days_ahead = (day_idx - ref.weekday()) % 7
                if qualifier == "next":
                    days_ahead = days_ahead + 7 if days_ahead != 0 else 7
                elif days_ahead == 0 and qualifier is None:
                    days_ahead = 7
                target_date = (ref + timedelta(days=days_ahead)).date()
                has_date = True
                break

    if not has_date:
        # Try explicit Month Day parsing (e.g. "July 3" or "Dec 12, 2026")
        m_month = re.search(
            r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
            r"aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+\d{1,2}(?:st|nd|rd|th)?(?:\s*,?\s*\d{4})?\b",
            lower,
        )
        if m_month:
            try:
                parsed = date_parser.parse(m_month.group(0), default=ref)
                target_date = parsed.date()
                has_date = True
            except Exception:
                pass

    # Extract explicit time
    has_time = False
    parsed_time: Optional[time] = None
    # Match "at 2pm", "at 14:30", or standalone "2:30pm" / "9am"
    m_time = re.search(
        r"(?:\bat\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?|\b(\d{1,2}):(\d{2})\s*(am|pm)?|\b(\d{1,2})\s*(am|pm))\b",
        lower,
    )
    if m_time:
        if m_time.group(1):
            hh, mm, mer = int(m_time.group(1)), int(m_time.group(2) or 0), m_time.group(3)
        elif m_time.group(4):
            hh, mm, mer = int(m_time.group(4)), int(m_time.group(5) or 0), m_time.group(6)
        else:
            hh, mm, mer = int(m_time.group(7)), 0, m_time.group(8)
        if mer == "pm" and hh < 12:
            hh += 12
        elif mer == "am" and hh == 12:
            hh = 0
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            parsed_time = time(hh, mm, 0)
            has_time = True

    duration_min = default_duration_min
    m_dur = _DURATION_RE.search(lower)
    if m_dur:
        val = int(m_dur.group(1))
        unit = m_dur.group(2)
        duration_min = val * 60 if unit.startswith(("hr", "hour")) else val

    if target_date and parsed_time:
        start_dt = datetime.combine(target_date, parsed_time, tzinfo=tz)
        end_dt = start_dt + timedelta(minutes=duration_min)
        return ParsedDateResult(
            date_str=target_date.isoformat(),
            start_iso=start_dt.isoformat(),
            end_iso=end_dt.isoformat(),
            has_explicit_date=True,
            has_explicit_time=True,
            timezone_name=tz_name,
        )

    return ParsedDateResult(
        date_str=target_date.isoformat() if target_date else None,
        has_explicit_date=has_date,
        has_explicit_time=has_time,
        timezone_name=tz_name,
    )


def split_multi_intent(user_input: str) -> List[str]:
    """Splits compound user requests on explicit separators ('then', ';', ' and <verb>')."""
    text = user_input.strip()
    if not text:
        return []
    # Split on ';' or ' and then ' or ' then ' or ' and <action_verb>'
    parts = re.split(
        r"\s*(?:;|\band\s+then\b|\bthen\b|\band\s+(?=(?:check|summarize|list|show|find|schedule|book|create|add|remind|draft|reply|send|prepare|mark|complete|update|cancel|delete|research|analyze|run)\b))\s*",
        text,
        flags=re.I,
    )
    cleaned = [p.strip(" ,.") for p in parts if p and p.strip(" ,.")]
    return cleaned or [text]


def extract_priority(text: str) -> str:
    lower = text.lower()
    if re.search(r"\b(critical|asap|urgent|emergency|p0)\b", lower):
        return "Critical"
    if re.search(r"\b(high\s*priority|important|p1|high)\b", lower):
        return "High"
    if re.search(r"\b(low\s*priority|whenever|someday|p3|low)\b", lower):
        return "Low"
    return "Medium"


def extract_person_or_company(text: str) -> Optional[str]:
    # Prefer capitalized proper nouns after 'with', 'about', 'for', 'contact', 'company'
    m = re.search(r"\b(?:with|about|for|contact|company|competitor|research)\s+([A-Z][a-zA-Z0-9&.\-]*(?:\s+[A-Z][a-zA-Z0-9&.\-]*)?)", text)
    if m:
        candidate = m.group(1).strip()
        if candidate.lower() not in {"Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday", "Today", "Tomorrow"}:
            return candidate
    m2 = re.search(r"\bwith\s+([a-zA-Z]+)\b", text, re.I)
    if m2:
        word = m2.group(1)
        if word.lower() not in _WEEKDAYS and word.lower() not in {"today", "tomorrow", "me", "us"}:
            return word
    return None


def _clean_title(raw: str, strip_patterns: Tuple[str, ...]) -> str:
    title = raw.strip().rstrip(".?!")
    for pat in strip_patterns:
        title = re.sub(pat, "", title, flags=re.I).strip()
    return re.sub(r"\s{2,}", " ", title).strip(" -:,.")


def parse_clause_intent(
    clause: str,
    *,
    tz_name: str = "UTC",
    allow_default_time_if_date_present: bool = False,
) -> ParsedIntent:
    """Classifies one natural-language clause into a specialist agent + intent + slots."""
    lower = clause.lower().strip()
    dt_info = parse_natural_datetime(clause, tz_name=tz_name)
    emails_found = _EMAIL_RE.findall(clause)
    id_match = _ID_RE.search(clause)
    extracted_id = id_match.group(1) if id_match else None
    person = extract_person_or_company(clause)

    # 1. Daily Executive Briefing
    if re.search(r"\b(daily\s+briefing|morning\s+briefing|brief\s+me|executive\s+briefing)\b", lower):
        return ParsedIntent(
            raw_clause=clause,
            agent="DeskMateOrchestrator",
            intent="daily_briefing",
            params={"timezone": tz_name},
        )

    # 2. Weekly Planning / Organize week
    if re.search(r"\b(organize\s+my\s+week|weekly\s+plan|weekly\s+summary|plan\s+my\s+week)\b", lower):
        return ParsedIntent(
            raw_clause=clause,
            agent="TaskProjectManagementAgent",
            intent="weekly_plan",
            params={"timezone": tz_name},
        )

    # 3. Security & Audit Inspection
    if re.search(r"\b(audit\s+log|security\s+status|security\s+report|anomal(?:y|ies)|permissions?)\b", lower):
        return ParsedIntent(
            raw_clause=clause,
            agent="SecurityComplianceAgent",
            intent="security_audit",
            params={},
        )

    # 4. Personal Knowledge / Memory
    if re.search(r"\b(remember\s+that|save\s+preference|my\s+memory|forget\s+|export\s+memory|working\s+preference)\b", lower):
        if re.search(r"\b(forget|delete|remove)\b", lower):
            return ParsedIntent(
                raw_clause=clause,
                agent="PersonalKnowledgeAgent",
                intent="delete_memory",
                params={"query": clause},
                requires_confirmation=True,
            )
        if re.search(r"\b(export)\b", lower):
            return ParsedIntent(raw_clause=clause, agent="PersonalKnowledgeAgent", intent="export_memory", params={})
        if re.search(r"\b(remember|save|prefer|preference)\b", lower):
            return ParsedIntent(
                raw_clause=clause,
                agent="PersonalKnowledgeAgent",
                intent="save_memory",
                params={"content": clause},
            )
        return ParsedIntent(raw_clause=clause, agent="PersonalKnowledgeAgent", intent="list_memory", params={})

    # 5. Workflows
    if re.search(r"\b(workflow|automate|automation)\b", lower):
        if re.search(r"\b(run|trigger|execute)\b", lower):
            return ParsedIntent(
                raw_clause=clause,
                agent="WorkflowAutomationAgent",
                intent="run_workflow",
                params={"query": clause},
                requires_confirmation=True,
            )
        return ParsedIntent(raw_clause=clause, agent="WorkflowAutomationAgent", intent="list_workflows", params={})

    # 6. Documents & Knowledge QA
    if re.search(r"\b(document|pdf|docx|csv|spreadsheet|uploaded\s+file|report\s+file)\b", lower):
        if re.search(r"\b(compare)\b", lower):
            return ParsedIntent(raw_clause=clause, agent="DocumentAssistantAgent", intent="compare_documents", params={"query": clause})
        if re.search(r"\b(summarize|summary)\b", lower):
            return ParsedIntent(raw_clause=clause, agent="DocumentAssistantAgent", intent="summarize_document", params={"query": clause})
        return ParsedIntent(raw_clause=clause, agent="DocumentAssistantAgent", intent="answer_question", params={"question": clause})

    # 7. Meeting Intelligence (Agenda / Prep / Notes / Follow-up)
    # Important: match "prepare for X meeting" / "meeting agenda", NOT "schedule a meeting to prep..."
    if re.search(r"\b(agenda|meeting\s+notes|transcript|follow-?up\s+action)\b", lower) or (
        re.search(r"\b(prepare|prep)\b", lower)
        and re.search(r"\b(meeting|review|standup|sync)\b", lower)
        and not re.search(r"\b(schedule|book|create|add|reschedule|move|cancel)\b", lower)
    ):
        if re.search(r"\b(agenda)\b", lower):
            return ParsedIntent(
                raw_clause=clause,
                agent="MeetingAssistantAgent",
                intent="generate_agenda",
                params={"meeting_title": _clean_title(clause, (r"^(?:prepare|create|write|generate)\s+(?:a\s+)?(?:meeting\s+)?agenda\s*(?:for)?",))},
            )
        if re.search(r"\b(follow-?up|transcript|notes|decisions|action\s+list)\b", lower):
            return ParsedIntent(
                raw_clause=clause,
                agent="MeetingAssistantAgent",
                intent="extract_followups",
                params={"notes": clause},
            )
        topic = _clean_title(
            clause,
            (
                r"^(?:help\s+me\s+)?(?:prepare|prep)\s+(?:for\s+)?(?:the\s+)?",
                r"\bmeeting\b$",
            ),
        )
        return ParsedIntent(
            raw_clause=clause,
            agent="MeetingAssistantAgent",
            intent="prepare_meeting",
            params={"meeting_title": topic or clause},
        )

    # 8. Business Intelligence vs Research Intelligence
    if re.search(r"\b(swot|competitor|business\s+report|lead\s+research|company\s+profile|market\s+trend|enrich)\b", lower):
        target = person or _clean_title(clause, (r"^(?:research|analyze|prepare\s+a\s+professional\s+business\s+report\s+(?:on|for)|swot\s+analysis\s+(?:on|for))\s*",))
        if not target:
            return ParsedIntent(
                raw_clause=clause,
                agent="BusinessIntelligenceAgent",
                intent="company_brief",
                needs_clarification=True,
                clarification_question="Which company, competitor, or market topic would you like me to analyze?",
            )
        return ParsedIntent(
            raw_clause=clause,
            agent="BusinessIntelligenceAgent",
            intent="swot_report" if "swot" in lower or "report" in lower else "competitor_analysis",
            params={"subject": target, "query": clause},
        )

    if re.search(r"\b(research|look\s+up\s+online|fact\s+check|verify|industry\s+analysis|market\s+research|find\s+important\s+information\s+about)\b", lower):
        target = person or _clean_title(clause, (r"^(?:research|find\s+important\s+information\s+about|verify)\s*",))
        if not target:
            return ParsedIntent(
                raw_clause=clause,
                agent="ResearchIntelligenceAgent",
                intent="web_research",
                needs_clarification=True,
                clarification_question="What topic, company, or claim should ResearchIntelligenceAgent investigate?",
            )
        return ParsedIntent(
            raw_clause=clause,
            agent="ResearchIntelligenceAgent",
            intent="web_research",
            params={"query": target},
        )

    # 9. Communication / Drafting vs Email Intelligence
    if re.search(r"\b(draft\s+(?:a\s+)?(?:reply|email|message|invite)|adjust\s+tone|rewrite\s+(?:in\s+)?(?:formal|informal)\s+tone)\b", lower):
        return ParsedIntent(
            raw_clause=clause,
            agent="CommunicationAgent",
            intent="draft_communication",
            params={
                "instruction": clause,
                "recipient_emails": emails_found,
                "tone": "formal" if "formal" in lower else ("friendly" if "friendly" in lower else "professional"),
            },
        )

    if re.search(r"\b(email|emails|inbox|mail|unread|newsletter|spam|phishing)\b", lower):
        if re.search(r"\b(send|delete|forward)\b", lower):
            return ParsedIntent(
                raw_clause=clause,
                agent="EmailIntelligenceAgent",
                intent="restricted_send_or_delete",
                params={"action": "send" if "send" in lower else ("delete" if "delete" in lower else "forward"), "instruction": clause},
                requires_confirmation=True,
            )
        if re.search(r"\b(reply|draft)\b", lower):
            return ParsedIntent(
                raw_clause=clause,
                agent="EmailIntelligenceAgent",
                intent="draft_reply",
                params={"email_id": extracted_id, "query": clause},
            )
        if re.search(r"\b(attention|urgent|priority|important|action)\b", lower):
            return ParsedIntent(
                raw_clause=clause,
                agent="EmailIntelligenceAgent",
                intent="find_urgent",
                params={"unread_only": "unread" in lower or True},
            )
        if re.search(r"\b(summarize|summary)\b", lower):
            return ParsedIntent(
                raw_clause=clause,
                agent="EmailIntelligenceAgent",
                intent="summarize_emails",
                params={"unread_only": "unread" in lower},
            )
        if re.search(r"\b(find|search|from)\b", lower) and not re.search(r"\b(check\s+my\s+inbox|triage)\b", lower):
            return ParsedIntent(
                raw_clause=clause,
                agent="EmailIntelligenceAgent",
                intent="search_emails",
                params={"query": clause},
            )
        return ParsedIntent(
            raw_clause=clause,
            agent="EmailIntelligenceAgent",
            intent="triage_inbox",
            params={"unread_only": True},
        )

    # 10. Contacts & Personal CRM
    if re.search(r"\b(contact|contacts|crm|phone\s+number|professional\s+details|email\s+address\s+of|who\s+is)\b", lower):
        if re.search(r"\b(add|create|new|save)\b", lower):
            if not person and not emails_found:
                return ParsedIntent(
                    raw_clause=clause,
                    agent="ContactCRM_Agent",
                    intent="create_contact",
                    needs_clarification=True,
                    clarification_question="Please provide the contact's full name (and optionally email, company, or phone) to create the record.",
                )
            return ParsedIntent(
                raw_clause=clause,
                agent="ContactCRM_Agent",
                intent="create_contact",
                params={"name": person or emails_found[0].split("@")[0], "email": emails_found[0] if emails_found else None},
                requires_confirmation=True,
            )
        return ParsedIntent(
            raw_clause=clause,
            agent="ContactCRM_Agent",
            intent="search_contacts",
            params={"query": person or _clean_title(clause, (r"^(?:find|search|show|get|who\s+is)\s*(?:a\s+)?(?:contact'?s?\s+)?(?:professional\s+details\s+(?:of|for)\s+)?",))},
        )

    # 11. Calendar & Scheduling (handles reschedule, cancel, slot finding, create, list)
    if re.search(r"\b(reschedule|calendar|schedule|event|meeting|meetings|appointment|slot|available\s+time|free\s+time|conflict|book\s+(?:a\s+)?call)\b", lower):
        if re.search(r"\b(suitable\s+time|available\s+time|free\s+slot|when\s+are\s+we\s+free|find\s+a?\s*time)\b", lower):
            return ParsedIntent(
                raw_clause=clause,
                agent="CalendarSchedulingAgent",
                intent="find_available_slots",
                params={
                    "date": dt_info.date_str,
                    "duration_minutes": 60,
                    "timezone": tz_name,
                },
            )

        if re.search(r"\b(summarize\s+(?:today'?s?\s+)?meetings|calendar\s+summary)\b", lower):
            return ParsedIntent(
                raw_clause=clause,
                agent="CalendarSchedulingAgent",
                intent="daily_summary",
                params={"date": dt_info.date_str, "timezone": tz_name},
            )

        if re.search(r"\b(cancel|delete\s+event|remove\s+meeting)\b", lower):
            target = extracted_id or _clean_title(clause, (r"^(?:cancel|delete|remove)\s+(?:the\s+)?", r"\b(meeting|event)\b$"))
            if not target:
                return ParsedIntent(
                    raw_clause=clause,
                    agent="CalendarSchedulingAgent",
                    intent="cancel_event",
                    needs_clarification=True,
                    clarification_question="Which event ID or meeting title would you like to cancel?",
                )
            return ParsedIntent(
                raw_clause=clause,
                agent="CalendarSchedulingAgent",
                intent="cancel_event",
                params={"event_id": extracted_id, "query": target},
                requires_confirmation=True,
            )

        if re.search(r"\b(reschedule|update|move|change)\b", lower):
            target = extracted_id or _clean_title(
                clause,
                (
                    r"^(?:reschedule|update|move|change)\s+(?:the\s+)?",
                    r"\bto\s+(?:today|tomorrow|next\s+\w+|monday|tuesday|wednesday|thursday|friday|saturday|sunday|\d+.*)\b.*$",
                ),
            )
            if not dt_info.has_explicit_date and not dt_info.has_explicit_time and not allow_default_time_if_date_present:
                return ParsedIntent(
                    raw_clause=clause,
                    agent="CalendarSchedulingAgent",
                    intent="reschedule_event",
                    params={"event_id": extracted_id, "query": target},
                    needs_clarification=True,
                    clarification_question=f"What new date and time would you like for '{target or 'this meeting'}' (including timezone)?",
                )
            return ParsedIntent(
                raw_clause=clause,
                agent="CalendarSchedulingAgent",
                intent="reschedule_event",
                params={
                    "event_id": extracted_id,
                    "query": target,
                    "start": dt_info.start_iso,
                    "end": dt_info.end_iso,
                    "date": dt_info.date_str,
                    "timezone": tz_name,
                },
                requires_confirmation=True,
            )

        if re.search(r"\b(add|create|book|schedule|set\s+up)\b", lower) and not re.search(r"\b(what'?s\s+on|show|view|list)\b", lower):
            title = _clean_title(
                clause,
                (
                    r"^(?:please\s+)?(?:add|create|book|schedule|set\s+up)\s+(?:a\s+)?(?:calendar\s+)?(?:meeting|event|appointment|call)?\s*(?:to|for|about|with)?\s*",
                    r"\b(?:on|at)\s+(?:today|tomorrow|next\s+\w+|monday|tuesday|wednesday|thursday|friday|saturday|sunday|\d{4}-\d{2}-\d{2}|\d{1,2}(?::\d{2})?\s*(?:am|pm)?).*$",
                ),
            )
            if not title and person:
                title = f"Meeting with {person}"

            if not dt_info.has_explicit_date:
                return ParsedIntent(
                    raw_clause=clause,
                    agent="CalendarSchedulingAgent",
                    intent="create_event",
                    params={"title": title, "attendees": emails_found},
                    needs_clarification=True,
                    clarification_question="What date and start time (and timezone) should I schedule this event for?",
                )
            if not dt_info.has_explicit_time and not allow_default_time_if_date_present:
                return ParsedIntent(
                    raw_clause=clause,
                    agent="CalendarSchedulingAgent",
                    intent="create_event",
                    params={"title": title, "date": dt_info.date_str, "attendees": emails_found},
                    needs_clarification=True,
                    clarification_question=f"What time on {dt_info.date_str} (and duration) should I propose for '{title or 'this meeting'}'?",
                )

            # Explicit fallback slot ONLY when caller opted in (e.g., scripted legacy demo)
            start_iso = dt_info.start_iso
            end_iso = dt_info.end_iso
            if not start_iso and dt_info.date_str and allow_default_time_if_date_present:
                start_iso = f"{dt_info.date_str}T10:00:00+00:00"
                end_iso = f"{dt_info.date_str}T11:00:00+00:00"

            return ParsedIntent(
                raw_clause=clause,
                agent="CalendarSchedulingAgent",
                intent="create_event",
                params={
                    "title": title or "Scheduled Meeting",
                    "start": start_iso,
                    "end": end_iso,
                    "timezone": tz_name,
                    "attendees": emails_found,
                    "attendee_names": [person] if person and not emails_found else [],
                },
                requires_confirmation=True,
            )

        return ParsedIntent(
            raw_clause=clause,
            agent="CalendarSchedulingAgent",
            intent="list_events",
            params={"date": dt_info.date_str, "timezone": tz_name},
        )

    # 12. Task & Project Management
    if re.search(r"\b(task|tasks|todo|to-do|remind|reminder|overdue|project|action\s+item)\b", lower):
        if re.search(r"\b(overdue|late|past\s+due)\b", lower):
            return ParsedIntent(raw_clause=clause, agent="TaskProjectManagementAgent", intent="overdue_tasks", params={})

        if re.search(r"\b(delete|remove)\b", lower):
            return ParsedIntent(
                raw_clause=clause,
                agent="TaskProjectManagementAgent",
                intent="delete_task",
                params={"task_id": extracted_id, "query": clause},
                requires_confirmation=True,
            )

        if re.search(r"\b(done|complete|finish|mark\s+.*\s*done)\b", lower):
            return ParsedIntent(
                raw_clause=clause,
                agent="TaskProjectManagementAgent",
                intent="complete_task",
                params={"task_id": extracted_id, "query": clause, "done": True},
                requires_confirmation=True,
            )

        if re.search(r"\b(add|create|new|remind)\b", lower):
            title = _clean_title(
                clause,
                (
                    r"^(?:please\s+)?(?:add|create|new)\s+(?:a\s+)?(?:task|to-?do|reminder)\s*(?:to|for|about)?\s*",
                    r"^(?:please\s+)?remind\s+me\s+(?:to\s+)?",
                    r"\bby\s+(?:today|tomorrow|next\s+\w+|monday|tuesday|wednesday|thursday|friday|\d{4}-\d{2}-\d{2}).*$",
                ),
            )
            if not title:
                return ParsedIntent(
                    raw_clause=clause,
                    agent="TaskProjectManagementAgent",
                    intent="create_task",
                    needs_clarification=True,
                    clarification_question="What is the task title or reminder you would like me to capture?",
                )
            return ParsedIntent(
                raw_clause=clause,
                agent="TaskProjectManagementAgent",
                intent="create_task",
                params={
                    "title": title,
                    "due_date": dt_info.start_iso or (f"{dt_info.date_str}T17:00:00+00:00" if dt_info.date_str else None),
                    "priority": extract_priority(clause),
                    "source": "orchestrator",
                },
                requires_confirmation=True,
            )

        return ParsedIntent(
            raw_clause=clause,
            agent="TaskProjectManagementAgent",
            intent="list_tasks",
            params={"include_done": "all" in lower or "completed" in lower},
        )

    return ParsedIntent(
        raw_clause=clause,
        agent="DeskMateOrchestrator",
        intent="unknown",
        params={},
        confidence=0.2,
    )
