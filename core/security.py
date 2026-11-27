"""Defense-in-depth security primitives for DeskMate AI.

Covers:
- Fernet token encryption at rest
- Bcrypt password hashing
- JWT bearer authentication & token revocation
- CSRF token generation and verification
- AgentPrincipal signed delegation tokens (prevents agent_name spoofing)
- PII & secret redaction for audit logs
- Prompt-injection scanning & untrusted-data framing
- Path traversal containment
- Sliding-window rate limiting & idempotency tracking
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import bcrypt
import jwt
from cryptography.fernet import Fernet, InvalidToken

from core.config import get_settings

# Secrets & PII patterns scrubbed before writing audit logs or diagnostic errors
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE_RE = re.compile(r"\b(?:\+?\d{1,3}[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}\b")
_SECRET_RE = re.compile(
    r"(?:AIza[0-9A-Za-z\-_]{20,}|sk-[A-Za-z0-9\-_]{16,}|ghp_[A-Za-z0-9]{20,}|xox[baprs]-[A-Za-z0-9\-]{10,}|Bearer\s+[A-Za-z0-9\-._~+/]+=*)"
)

_SENSITIVE_KEYS = {
    "password",
    "hashed_password",
    "secret",
    "token",
    "access_token",
    "refresh_token",
    "api_key",
    "authorization",
    "cookie",
    "ssn",
    "credit_card",
}

_PROMPT_INJECTION_PATTERNS = [
    (re.compile(r"ignore\s+(?:all\s+)?(?:previous|prior|above)\s+instructions", re.I), "override_instructions"),
    (re.compile(r"disregard\s+(?:system|security|safety)\s+(?:rules|prompt|policy)", re.I), "disregard_policy"),
    (re.compile(r"reveal\s+(?:system\s+prompt|api\s*key|secret|token|password)", re.I), "secret_exfiltration"),
    (re.compile(r"(?:execute|run|call)\s+(?:shell|bash|powershell|cmd|send_email|delete_)", re.I), "forced_tool_execution"),
    (re.compile(r"<\s*/?\s*(?:system|assistant|tool_call)\s*>", re.I), "role_delimiter_spoofing"),
    (re.compile(r"you\s+are\s+now\s+(?:in\s+)?(?:developer|admin|unrestricted|jailbreak)\s+mode", re.I), "jailbreak_mode"),
]


class SecurityError(Exception):
    """Raised when a security control rejects an operation."""


class TokenEncryptor:
    """Encrypts and decrypts OAuth credentials at rest using Fernet (AES-128-CBC + HMAC)."""

    def __init__(self, key: Optional[str] = None) -> None:
        settings = get_settings()
        raw_key = (key or settings.encryption_key).encode("ascii")
        self._fernet = Fernet(raw_key)

    def encrypt(self, plaintext: str) -> str:
        if not plaintext:
            return ""
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")

    def decrypt(self, ciphertext: str) -> str:
        if not ciphertext:
            return ""
        try:
            return self._fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8")
        except InvalidToken as exc:
            raise SecurityError("Failed to decrypt stored credential token.") from exc


def hash_password(password: str) -> str:
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


class JWTManager:
    """Issues and validates signed JWT access tokens with in-memory revocation list."""

    _revoked_jti: set[str] = set()
    _lock = threading.Lock()

    @classmethod
    def create_access_token(
        cls,
        *,
        user_id: str,
        email: str,
        role: str = "user",
        expires_minutes: Optional[int] = None,
    ) -> str:
        settings = get_settings()
        now = datetime.now(timezone.utc)
        ttl = expires_minutes or settings.jwt_expire_minutes
        payload = {
            "sub": user_id,
            "email": email,
            "role": role,
            "jti": str(uuid.uuid4()),
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=ttl)).timestamp()),
        }
        return jwt.encode(payload, settings.secret_key, algorithm="HS256")

    @classmethod
    def decode_token(cls, token: str) -> Dict[str, Any]:
        settings = get_settings()
        try:
            payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
        except jwt.ExpiredSignatureError as exc:
            raise SecurityError("Session token has expired.") from exc
        except jwt.InvalidTokenError as exc:
            raise SecurityError("Invalid authentication token.") from exc

        jti = payload.get("jti")
        with cls._lock:
            if jti and jti in cls._revoked_jti:
                raise SecurityError("Authentication token has been revoked.")
        return payload

    @classmethod
    def revoke_token(cls, token: str) -> None:
        try:
            payload = cls.decode_token(token)
            jti = payload.get("jti")
            if jti:
                with cls._lock:
                    cls._revoked_jti.add(jti)
        except SecurityError:
            pass


class CSRFManager:
    """Stateless HMAC CSRF protection bound to a user/session identifier."""

    @staticmethod
    def generate(subject: str) -> str:
        settings = get_settings()
        nonce = secrets.token_urlsafe(16)
        msg = f"{subject}:{nonce}".encode("utf-8")
        sig = hmac.new(settings.secret_key.encode("utf-8"), msg, hashlib.sha256).hexdigest()
        return f"{nonce}.{sig}"

    @staticmethod
    def verify(subject: str, token: Optional[str]) -> bool:
        if not token or "." not in token:
            return False
        settings = get_settings()
        nonce, sig = token.split(".", 1)
        msg = f"{subject}:{nonce}".encode("utf-8")
        expected = hmac.new(settings.secret_key.encode("utf-8"), msg, hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, expected)


@dataclass(frozen=True)
class AgentPrincipal:
    """Verified identity token binding a delegated specialist to a user and trace."""

    agent_name: str
    user_id: str
    trace_id: str
    depth: int
    signature: str

    @classmethod
    def issue(cls, agent_name: str, user_id: str, trace_id: str, depth: int = 0) -> "AgentPrincipal":
        settings = get_settings()
        msg = f"{agent_name}|{user_id}|{trace_id}|{depth}".encode("utf-8")
        sig = hmac.new(settings.secret_key.encode("utf-8"), msg, hashlib.sha256).hexdigest()
        return cls(
            agent_name=agent_name,
            user_id=user_id,
            trace_id=trace_id,
            depth=depth,
            signature=sig,
        )

    def verify(self) -> bool:
        settings = get_settings()
        msg = f"{self.agent_name}|{self.user_id}|{self.trace_id}|{self.depth}".encode("utf-8")
        expected = hmac.new(settings.secret_key.encode("utf-8"), msg, hashlib.sha256).hexdigest()
        return hmac.compare_digest(self.signature, expected)


def _mask_email(match: re.Match[str]) -> str:
    email = match.group(0)
    local, domain = email.split("@", 1)
    prefix = local[0] if local else "*"
    return f"{prefix}***@{domain}"


def redact_string(text: str, max_len: int = 180) -> str:
    """Redacts emails, phones, and token-like secrets from loggable text."""
    cleaned = _SECRET_RE.sub("[REDACTED_SECRET]", text)
    cleaned = _EMAIL_RE.sub(_mask_email, cleaned)
    cleaned = _PHONE_RE.sub("[REDACTED_PHONE]", cleaned)
    if len(cleaned) > max_len:
        return cleaned[:max_len] + "...[truncated]"
    return cleaned


def redact_pii(data: Any) -> Any:
    """Recursively scrubs PII and secrets from dicts/lists before audit persistence."""
    if isinstance(data, dict):
        sanitized: Dict[str, Any] = {}
        for k, v in data.items():
            key_lower = str(k).lower()
            if any(sens in key_lower for sens in _SENSITIVE_KEYS):
                sanitized[k] = "[REDACTED]"
            elif key_lower in {"body", "content", "raw_text", "transcript"} and isinstance(v, str):
                sanitized[k] = f"[REDACTED_CONTENT len={len(v)}]"
            else:
                sanitized[k] = redact_pii(v)
        return sanitized
    if isinstance(data, list):
        return [redact_pii(item) for item in data[:25]]
    if isinstance(data, str):
        return redact_string(data)
    return data


def scan_prompt_injection(text: str) -> Tuple[bool, List[str]]:
    """Detects common prompt-injection attempts inside untrusted external text."""
    if not text:
        return False, []
    hits = [label for pattern, label in _PROMPT_INJECTION_PATTERNS if pattern.search(text)]
    return bool(hits), hits


def wrap_untrusted_data(source: str, text: str) -> str:
    """Frames external emails, docs, or web outputs strictly as untrusted data."""
    flagged, patterns = scan_prompt_injection(text)
    warning = f" [SECURITY_NOTICE: potential prompt-injection markers={','.join(patterns)}]" if flagged else ""
    safe_body = text.replace("</untrusted_data>", "[/untrusted_data]")
    return f"<untrusted_data source=\"{source}\"{warning}>\n{safe_body}\n</untrusted_data>"


def sanitize_error(exc: Exception, env: Optional[str] = None) -> str:
    """Returns safe, non-leaking error text for API clients."""
    current_env = env or get_settings().app_env
    if isinstance(exc, SecurityError):
        return str(exc)
    raw = redact_string(str(exc), max_len=240)
    if current_env == "production":
        return f"Request could not be completed ({type(exc).__name__})."
    return raw


def safe_resolve_path(base_dir: Path, relative_target: str) -> Path:
    """Prevents path traversal outside an approved base directory."""
    resolved_base = base_dir.resolve()
    candidate = (resolved_base / relative_target).resolve()
    try:
        candidate.relative_to(resolved_base)
    except ValueError as exc:
        raise SecurityError(f"Path '{relative_target}' escapes allowed workspace directory.") from exc
    return candidate


class SlidingWindowRateLimiter:
    """Thread-safe in-memory sliding-window rate limiter keyed by subject."""

    def __init__(self, max_requests: int = 60, window_seconds: int = 60) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: Dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> Tuple[bool, int]:
        now = time.time()
        with self._lock:
            q = self._hits.setdefault(key, deque())
            cutoff = now - self.window_seconds
            while q and q[0] < cutoff:
                q.popleft()
            if len(q) >= self.max_requests:
                return False, 0
            q.append(now)
            return True, self.max_requests - len(q)

    def reset(self, key: Optional[str] = None) -> None:
        with self._lock:
            if key is None:
                self._hits.clear()
            else:
                self._hits.pop(key, None)


class IdempotencyGuard:
    """Prevents duplicate execution of mutating operations within a TTL window."""

    def __init__(self, ttl_seconds: int = 300) -> None:
        self.ttl_seconds = ttl_seconds
        self._seen: Dict[str, Tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get_or_none(self, key: Optional[str]) -> Tuple[bool, Any]:
        if not key:
            return False, None
        now = time.time()
        with self._lock:
            entry = self._seen.get(key)
            if not entry:
                return False, None
            ts, value = entry
            if now - ts > self.ttl_seconds:
                self._seen.pop(key, None)
                return False, None
            return True, value

    def record(self, key: Optional[str], value: Any) -> None:
        if not key:
            return
        with self._lock:
            self._seen[key] = (time.time(), value)
