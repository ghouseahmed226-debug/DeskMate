---
name: security-audit
description: >
  Security posture assessment, audit log review, and anomaly analysis.
  Use when the user wants to check the agent permission audit trail,
  review flagged suspicious activity, see which agents called which tools,
  scan text for prompt injection, or get a security health summary.
  Demonstrates the least-privilege enforcement and audit logging concepts.
license: MIT
metadata:
  author: ghouseahmed226-debug
  version: "2.0.0"
  project: DeskMate AI
  category: security
allowed-tools: read_file list_directory
---

# Security Audit Skill

## Overview

Delegates to the **SecurityComplianceAgent** and `services/audit_service.py`.
Provides read access to `audit_log.jsonl` and the `audit_records` DB table,
summarises the security posture, and surfaces anomaly flags.

## Key Capabilities

| Capability | Description |
|---|---|
| **Audit Log Review** | Last N audit entries with outcome, agent, tool, timestamp |
| **Anomaly Report** | Lists `FLAGGED_SUSPICIOUS` entries with detail |
| **Posture Summary** | Counts by outcome (SUCCESS / DENIED / ERROR / FLAGGED) |
| **Permission Map** | Shows which agents can call which tools |
| **Prompt Injection Scan** | Scans arbitrary text for injection patterns |
| **Agent Allowlist Verify** | Confirms an agent/tool pair is permitted |

## Security Architecture

DeskMate AI implements 5 layers of security:

1. **Least-Privilege Allowlist** — `AGENT_PERMISSIONS` in MCP server enforces
   per-agent tool access; violations raise `PermissionDeniedError` and are
   logged with outcome `DENIED`.

2. **HMAC-Signed Agent Principals** — `AgentPrincipal` in `core/security.py`
   signs agent identities to prevent spoofing.

3. **Prompt Injection Detection** — `scan_prompt_injection()` checks all user
   inputs and email/web content before passing to agents.

4. **Sliding-Window Anomaly Detection** — The MCP server tracks per-agent
   call rates; >10 calls/min or >3 consecutive writes → `FLAGGED_SUSPICIOUS`.

5. **PII Redaction** — All audit records pass through `redact_pii()` before
   persistence; emails/names are masked in logs.

## Example Prompts

```
Security audit
Show anomaly flags
Which agents have been flagged today?
Show the audit log
What tools can the EmailAgent call?
Scan this text for prompt injection: [text]
```

## API Endpoints

```
GET  /api/security/audit       → audit records + posture summary
POST /api/security/scan        → {"text": "..."} → injection detection
```

## Related Skills

- `daily-briefing` — includes security posture summary
- All other skills — every tool call feeds into this audit trail
