"""Base classes and encrypted DB token helpers for external integrations."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from core.security import TokenEncryptor
from db.models import IntegrationConnection


class IntegrationError(Exception):
    """Base error for integration operations."""


class IntegrationNotConnectedError(IntegrationError):
    """Raised when an integration requires user OAuth authorization first."""


class IntegrationStatusInfo(BaseModel):
    provider: str
    display_name: str
    category: str
    configured_on_server: bool
    connected: bool
    status: str
    required_scopes: List[str] = Field(default_factory=list)
    permission_explanation: str
    missing_env_vars: List[str] = Field(default_factory=list)
    last_health_check_at: Optional[str] = None
    last_error: Optional[str] = None


class BaseIntegrationAdapter(ABC):
    provider: str = ""
    display_name: str = ""
    category: str = ""
    required_scopes: List[str] = []
    permission_explanation: str = ""

    @abstractmethod
    def missing_env_vars(self) -> List[str]:
        """Returns env var names required to initiate OAuth for this provider."""

    def is_configured(self) -> bool:
        return len(self.missing_env_vars()) == 0

    @abstractmethod
    def get_authorization_url(self, state: str) -> str:
        """Generates an OAuth consent URL."""

    @abstractmethod
    def health_check(self, session: Session, user_id: str) -> Dict[str, Any]:
        """Checks connection status without fabricating connectivity."""

    def get_connection(self, session: Session, user_id: str) -> Optional[IntegrationConnection]:
        return (
            session.query(IntegrationConnection)
            .filter_by(user_id=user_id, provider=self.provider)
            .first()
        )

    def save_encrypted_tokens(
        self,
        session: Session,
        user_id: str,
        token_payload: Dict[str, Any],
        scopes: Optional[List[str]] = None,
        expires_at: Optional[datetime] = None,
    ) -> IntegrationConnection:
        encryptor = TokenEncryptor()
        encrypted = encryptor.encrypt(json.dumps(token_payload))
        conn = self.get_connection(session, user_id)
        if conn is None:
            conn = IntegrationConnection(
                user_id=user_id,
                provider=self.provider,
            )
            session.add(conn)
        conn.status = "connected"
        conn.scopes_json = scopes or list(self.required_scopes)
        conn.encrypted_tokens = encrypted
        conn.expires_at = expires_at
        conn.last_error = None
        conn.last_health_check_at = datetime.now(timezone.utc)
        session.flush()
        return conn

    def load_decrypted_tokens(self, session: Session, user_id: str) -> Dict[str, Any]:
        conn = self.get_connection(session, user_id)
        if not conn or conn.status != "connected" or not conn.encrypted_tokens:
            raise IntegrationNotConnectedError(
                f"{self.display_name} is not connected for this user. Authorize OAuth first."
            )
        encryptor = TokenEncryptor()
        return json.loads(encryptor.decrypt(conn.encrypted_tokens))

    def disconnect(self, session: Session, user_id: str) -> bool:
        conn = self.get_connection(session, user_id)
        if conn is None:
            return False
        conn.status = "disconnected"
        conn.encrypted_tokens = ""
        conn.expires_at = None
        conn.last_health_check_at = datetime.now(timezone.utc)
        session.flush()
        return True

    def status_info(self, session: Session, user_id: str) -> IntegrationStatusInfo:
        conn = self.get_connection(session, user_id)
        missing = self.missing_env_vars()
        connected = bool(conn and conn.status == "connected" and conn.encrypted_tokens)
        status = "connected" if connected else ("ready_to_connect" if not missing else "credentials_required")
        return IntegrationStatusInfo(
            provider=self.provider,
            display_name=self.display_name,
            category=self.category,
            configured_on_server=len(missing) == 0,
            connected=connected,
            status=status,
            required_scopes=list(self.required_scopes),
            permission_explanation=self.permission_explanation,
            missing_env_vars=missing,
            last_health_check_at=conn.last_health_check_at.isoformat() if conn and conn.last_health_check_at else None,
            last_error=conn.last_error if conn else None,
        )
