"""Modular integration registry covering all supported external providers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List
from urllib.parse import urlencode

from sqlalchemy.orm import Session

from core.config import get_settings
from integrations.base import BaseIntegrationAdapter, IntegrationError, IntegrationStatusInfo
from integrations.gmail_adapter import GmailAdapter
from integrations.google_calendar_adapter import GoogleCalendarAdapter
from integrations.google_oauth import GoogleOAuthAdapter


class GoogleContactsAdapter(GoogleOAuthAdapter):
    provider = "google_contacts"
    display_name = "Google Contacts"
    category = "contacts"
    required_scopes = ["https://www.googleapis.com/auth/contacts.readonly"]
    permission_explanation = "Read-only access to contacts directory for CRM enrichment and meeting prep."


class GoogleDriveAdapter(GoogleOAuthAdapter):
    provider = "google_drive"
    display_name = "Google Drive"
    category = "documents"
    required_scopes = ["https://www.googleapis.com/auth/drive.readonly"]
    permission_explanation = "Read-only access to authorized Drive files for document summarization and Q&A."


class GenericOAuthConnector(BaseIntegrationAdapter):
    """Modular OAuth adapter for Slack, Notion, GitHub, and Microsoft Graph."""

    def __init__(
        self,
        *,
        provider: str,
        display_name: str,
        category: str,
        auth_base_url: str,
        client_id_attr: str,
        client_secret_attr: str,
        client_id_env: str,
        client_secret_env: str,
        scopes: List[str],
        permission_explanation: str,
    ) -> None:
        self.provider = provider
        self.display_name = display_name
        self.category = category
        self.auth_base_url = auth_base_url
        self.client_id_attr = client_id_attr
        self.client_secret_attr = client_secret_attr
        self.client_id_env = client_id_env
        self.client_secret_env = client_secret_env
        self.required_scopes = scopes
        self.permission_explanation = permission_explanation

    def missing_env_vars(self) -> List[str]:
        s = get_settings()
        missing = []
        if not getattr(s, self.client_id_attr, ""):
            missing.append(self.client_id_env)
        if not getattr(s, self.client_secret_attr, ""):
            missing.append(self.client_secret_env)
        return missing

    def get_authorization_url(self, state: str) -> str:
        missing = self.missing_env_vars()
        if missing:
            raise IntegrationError(
                f"Cannot initiate {self.display_name} OAuth; missing env vars: {', '.join(missing)}"
            )
        s = get_settings()
        client_id = getattr(s, self.client_id_attr)
        params = {
            "client_id": client_id,
            "scope": " ".join(self.required_scopes),
            "state": state,
            "response_type": "code",
        }
        return f"{self.auth_base_url}?{urlencode(params)}"

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
        conn.last_health_check_at = datetime.now(timezone.utc)
        session.flush()
        return {
            "provider": self.provider,
            "healthy": True,
            "status": "connected",
            "configured": self.is_configured(),
            "detail": "Encrypted token stored for user.",
        }


def get_all_integrations() -> Dict[str, BaseIntegrationAdapter]:
    adapters: List[BaseIntegrationAdapter] = [
        GmailAdapter(),
        GoogleCalendarAdapter(),
        GoogleContactsAdapter(),
        GoogleDriveAdapter(),
        GenericOAuthConnector(
            provider="slack",
            display_name="Slack",
            category="communication",
            auth_base_url="https://slack.com/oauth/v2/authorize",
            client_id_attr="slack_client_id",
            client_secret_attr="slack_client_secret",
            client_id_env="SLACK_CLIENT_ID",
            client_secret_env="SLACK_CLIENT_SECRET",
            scopes=["channels:history", "channels:read", "chat:write"],
            permission_explanation="Reads public channel history and posts approved messages.",
        ),
        GenericOAuthConnector(
            provider="notion",
            display_name="Notion",
            category="knowledge_management",
            auth_base_url="https://api.notion.com/v1/oauth/authorize",
            client_id_attr="notion_client_id",
            client_secret_attr="notion_client_secret",
            client_id_env="NOTION_CLIENT_ID",
            client_secret_env="NOTION_CLIENT_SECRET",
            scopes=["read_content", "update_content"],
            permission_explanation="Reads authorized Notion databases/pages and appends approved notes.",
        ),
        GenericOAuthConnector(
            provider="github",
            display_name="GitHub",
            category="developer_tools",
            auth_base_url="https://github.com/login/oauth/authorize",
            client_id_attr="github_client_id",
            client_secret_attr="github_client_secret",
            client_id_env="GITHUB_CLIENT_ID",
            client_secret_env="GITHUB_CLIENT_SECRET",
            scopes=["repo", "read:user"],
            permission_explanation="Reads repository issues/PRs and creates approved issue updates.",
        ),
        GenericOAuthConnector(
            provider="microsoft_outlook",
            display_name="Microsoft Outlook",
            category="email",
            auth_base_url="https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
            client_id_attr="microsoft_client_id",
            client_secret_attr="microsoft_client_secret",
            client_id_env="MICROSOFT_CLIENT_ID",
            client_secret_env="MICROSOFT_CLIENT_SECRET",
            scopes=["Mail.Read", "Mail.ReadWrite", "offline_access"],
            permission_explanation="Reads Outlook mail and creates drafts; requires approval to send.",
        ),
        GenericOAuthConnector(
            provider="microsoft_calendar",
            display_name="Microsoft Calendar",
            category="calendar",
            auth_base_url="https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
            client_id_attr="microsoft_client_id",
            client_secret_attr="microsoft_client_secret",
            client_id_env="MICROSOFT_CLIENT_ID",
            client_secret_env="MICROSOFT_CLIENT_SECRET",
            scopes=["Calendars.ReadWrite", "offline_access"],
            permission_explanation="Reads Outlook Calendar availability and schedules approved events.",
        ),
    ]
    return {a.provider: a for a in adapters}


def list_integration_statuses(session: Session, user_id: str) -> List[IntegrationStatusInfo]:
    return [adapter.status_info(session, user_id) for adapter in get_all_integrations().values()]
