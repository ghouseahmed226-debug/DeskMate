"""Official Gmail API adapter using least-privilege Google OAuth credentials."""

from __future__ import annotations

import base64
from email.message import EmailMessage
from typing import Any, Dict, List, Optional

from googleapiclient.discovery import build
from sqlalchemy.orm import Session

from core.security import SecurityError
from integrations.google_oauth import GoogleOAuthAdapter


class GmailAdapter(GoogleOAuthAdapter):
    provider = "gmail"
    display_name = "Gmail"
    category = "email"
    required_scopes = [
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.compose",
    ]
    permission_explanation = (
        "Reads inbox metadata/threads and creates drafts. Sending email requires explicit gmail.send scope and user approval."
    )

    def _service(self, session: Session, user_id: str):
        creds = self.get_credentials(session, user_id)
        return build("gmail", "v1", credentials=creds, cache_discovery=False)

    def list_messages(self, session: Session, user_id: str, max_results: int = 20, query: str = "") -> List[Dict[str, Any]]:
        svc = self._service(session, user_id)
        resp = svc.users().messages().list(userId="me", maxResults=max_results, q=query).execute()
        items = resp.get("messages", [])
        results: List[Dict[str, Any]] = []
        for item in items:
            msg = svc.users().messages().get(userId="me", id=item["id"], format="metadata").execute()
            headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
            results.append(
                {
                    "id": msg["id"],
                    "thread_id": msg.get("threadId"),
                    "sender": headers.get("from", ""),
                    "subject": headers.get("subject", "(No Subject)"),
                    "snippet": msg.get("snippet", ""),
                    "unread": "UNREAD" in msg.get("labelIds", []),
                }
            )
        return results

    def create_draft(self, session: Session, user_id: str, *, to: str, subject: str, body: str) -> Dict[str, Any]:
        svc = self._service(session, user_id)
        message = EmailMessage()
        message.set_content(body)
        message["To"] = to
        message["Subject"] = subject
        encoded = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
        draft = svc.users().drafts().create(userId="me", body={"message": {"raw": encoded}}).execute()
        return {"draft_id": draft.get("id"), "status": "draft_created", "to": to, "subject": subject}

    def send_email_approved(
        self,
        session: Session,
        user_id: str,
        *,
        to: str,
        subject: str,
        body: str,
        approval_id: Optional[str],
    ) -> Dict[str, Any]:
        if not approval_id:
            raise SecurityError("Explicit user approval_id is required before sending any email via Gmail.")
        svc = self._service(session, user_id)
        message = EmailMessage()
        message.set_content(body)
        message["To"] = to
        message["Subject"] = subject
        encoded = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
        sent = svc.users().messages().send(userId="me", body={"raw": encoded}).execute()
        return {"message_id": sent.get("id"), "status": "sent_confirmed_by_gmail", "to": to}
