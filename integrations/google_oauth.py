"""Google OAuth 2.0 flow, token encryption, refresh, and revocation."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import requests
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from sqlalchemy.orm import Session

from core.config import get_settings
from integrations.base import BaseIntegrationAdapter, IntegrationError, IntegrationNotConnectedError


class GoogleOAuthAdapter(BaseIntegrationAdapter):
    """Shared least-privilege Google OAuth adapter supporting refresh & revocation."""

    provider = "google"
    display_name = "Google Workspace OAuth"
    category = "oauth"
    required_scopes = [
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.compose",
        "https://www.googleapis.com/auth/calendar.events",
        "https://www.googleapis.com/auth/contacts.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
    ]
    permission_explanation = (
        "Uses least-privilege scopes: read-only email & contacts, draft creation (no silent send), "
        "calendar event management, and read-only Drive access."
    )

    def missing_env_vars(self) -> List[str]:
        s = get_settings()
        missing = []
        if not s.google_client_id:
            missing.append("GOOGLE_CLIENT_ID")
        if not s.google_client_secret:
            missing.append("GOOGLE_CLIENT_SECRET")
        return missing

    def get_authorization_url(self, state: str, scopes: Optional[List[str]] = None) -> str:
        missing = self.missing_env_vars()
        if missing:
            raise IntegrationError(
                f"Cannot generate Google OAuth URL; missing server environment variables: {', '.join(missing)}"
            )
        s = get_settings()
        params = {
            "client_id": s.google_client_id,
            "redirect_uri": s.google_redirect_uri,
            "response_type": "code",
            "scope": " ".join(scopes or self.required_scopes),
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
        return f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"

    def exchange_code(self, session: Session, user_id: str, code: str) -> Dict[str, Any]:
        missing = self.missing_env_vars()
        if missing:
            raise IntegrationError(f"Missing Google OAuth credentials: {', '.join(missing)}")
        s = get_settings()
        resp = requests.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": s.google_client_id,
                "client_secret": s.google_client_secret,
                "redirect_uri": s.google_redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=15,
        )
        if resp.status_code != 200:
            raise IntegrationError(f"Google OAuth token exchange failed (HTTP {resp.status_code}).")
        token_data = resp.json()
        self.save_encrypted_tokens(session, user_id, token_data, scopes=token_data.get("scope", "").split())
        return {"status": "connected", "provider": self.provider}

    def get_credentials(self, session: Session, user_id: str) -> Credentials:
        tokens = self.load_decrypted_tokens(session, user_id)
        s = get_settings()
        creds = Credentials(
            token=tokens.get("access_token"),
            refresh_token=tokens.get("refresh_token"),
            token_uri="https://oauth2.googleapis.com/token",
            client_id=s.google_client_id or None,
            client_secret=s.google_client_secret or None,
            scopes=self.required_scopes,
        )
        if creds.expired and creds.refresh_token:
            creds.refresh(GoogleAuthRequest())
            tokens["access_token"] = creds.token
            self.save_encrypted_tokens(session, user_id, tokens)
        return creds

    def revoke_and_disconnect(self, session: Session, user_id: str) -> bool:
        try:
            tokens = self.load_decrypted_tokens(session, user_id)
            token = tokens.get("refresh_token") or tokens.get("access_token")
            if token:
                try:
                    requests.post(
                        "https://oauth2.googleapis.com/revoke",
                        params={"token": token},
                        headers={"content-type": "application/x-www-form-urlencoded"},
                        timeout=10,
                    )
                except Exception:
                    pass
        except IntegrationNotConnectedError:
            pass
        return self.disconnect(session, user_id)

    def health_check(self, session: Session, user_id: str) -> Dict[str, Any]:
        conn = self.get_connection(session, user_id)
        if not conn or conn.status != "connected":
            return {
                "provider": self.provider,
                "healthy": False,
                "status": "disconnected",
                "configured": self.is_configured(),
                "detail": "Not connected. OAuth authorization required.",
            }
        try:
            creds = self.get_credentials(session, user_id)
            conn.last_health_check_at = datetime.now(timezone.utc)
            session.flush()
            return {
                "provider": self.provider,
                "healthy": bool(creds.token),
                "status": "connected",
                "configured": self.is_configured(),
                "detail": "Encrypted OAuth credentials present.",
            }
        except Exception as exc:
            conn.last_error = type(exc).__name__
            session.flush()
            return {"provider": self.provider, "healthy": False, "status": "error", "detail": str(exc)}
