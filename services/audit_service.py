"""Centralized PII-redacted database & JSONL audit persistence and compliance reporting."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from core.config import get_settings
from core.security import redact_pii
from db.models import AuditRecord


def record_audit_event(
    session: Optional[Session],
    *,
    user_id: Optional[str],
    trace_id: Optional[str],
    agent_name: str,
    tool_name: str,
    action: str = "tool_call",
    params: Optional[Dict[str, Any]] = None,
    outcome: str = "ALLOWED",
    approval_state: str = "not_required",
    detail: str = "",
) -> Dict[str, Any]:
    """Writes a sanitized, PII-redacted audit entry to DB (when session provided) and JSONL."""
    safe_params = redact_pii(params or {})
    safe_detail = redact_pii(detail) if detail else ""
    now = datetime.now(timezone.utc)

    payload = {
        "timestamp": now.isoformat(),
        "user_id": user_id,
        "trace_id": trace_id,
        "agent": agent_name,
        "tool": tool_name,
        "action": action,
        "params": safe_params,
        "outcome": outcome,
        "approval_state": approval_state,
        "detail": safe_detail,
    }

    if session is not None:
        session.add(
            AuditRecord(
                user_id=user_id,
                trace_id=trace_id,
                agent_name=agent_name,
                tool_name=tool_name,
                action=action,
                params_redacted_json=safe_params if isinstance(safe_params, dict) else {"value": safe_params},
                outcome=outcome,
                approval_state=approval_state,
                detail=str(safe_detail),
                created_at=now,
            )
        )
        session.flush()

    log_path = get_settings().audit_log_path
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, default=str) + "\n")
    except OSError:
        pass

    return payload


def check_db_anomaly(
    session: Optional[Session],
    *,
    user_id: Optional[str],
    agent_name: str,
    tool_name: str,
) -> Optional[str]:
    """Detects high-rate bursts or consecutive writes across persisted audit logs."""
    settings = get_settings()
    if session is None:
        return None

    cutoff = datetime.now(timezone.utc) - timedelta(seconds=settings.anomaly_time_window_sec)
    recent = (
        session.query(AuditRecord)
        .filter(
            AuditRecord.agent_name == agent_name,
            AuditRecord.created_at >= cutoff,
            AuditRecord.outcome.in_(["ALLOWED", "DENIED"]),
        )
        .order_by(AuditRecord.created_at.desc())
        .limit(settings.anomaly_max_calls_per_min + 2)
        .all()
    )

    if len(recent) >= settings.anomaly_max_calls_per_min:
        detail = f"Exceeded {settings.anomaly_max_calls_per_min} calls within {settings.anomaly_time_window_sec}s"
        record_audit_event(
            session,
            user_id=user_id,
            trace_id=None,
            agent_name=agent_name,
            tool_name=tool_name,
            action="anomaly_check",
            outcome="FLAGGED_SUSPICIOUS",
            detail=detail,
        )
        return detail

    consecutive_writes = 0
    for rec in recent:
        if rec.tool_name.startswith(("create_", "update_", "delete_", "cancel_", "send_", "mark_")):
            consecutive_writes += 1
        else:
            break

    if consecutive_writes >= settings.anomaly_max_consecutive_writes:
        detail = f"Exceeded {settings.anomaly_max_consecutive_writes} consecutive write operations"
        record_audit_event(
            session,
            user_id=user_id,
            trace_id=None,
            agent_name=agent_name,
            tool_name=tool_name,
            action="anomaly_check",
            outcome="FLAGGED_SUSPICIOUS",
            detail=detail,
        )
        return detail

    return None


def summarize_security_posture(session: Session, user_id: str) -> Dict[str, Any]:
    records = (
        session.query(AuditRecord)
        .filter((AuditRecord.user_id == user_id) | (AuditRecord.user_id.is_(None)))
        .order_by(AuditRecord.created_at.desc())
        .limit(200)
        .all()
    )
    allowed = sum(1 for r in records if r.outcome == "ALLOWED")
    denied = sum(1 for r in records if r.outcome == "DENIED")
    flagged = sum(1 for r in records if r.outcome == "FLAGGED_SUSPICIOUS")
    return {
        "total_audited_events": len(records),
        "allowed_count": allowed,
        "denied_count": denied,
        "flagged_suspicious_count": flagged,
        "recent_flags": [
            {
                "id": r.id,
                "agent": r.agent_name,
                "tool": r.tool_name,
                "detail": r.detail,
                "timestamp": r.created_at.isoformat() if r.created_at else None,
            }
            for r in records
            if r.outcome in {"FLAGGED_SUSPICIOUS", "DENIED"}
        ][:10],
    }
