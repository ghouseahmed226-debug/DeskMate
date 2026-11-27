"""Official Google Calendar API adapter with OAuth credentials and conflict awareness."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from googleapiclient.discovery import build
from sqlalchemy.orm import Session

from integrations.google_oauth import GoogleOAuthAdapter


class GoogleCalendarAdapter(GoogleOAuthAdapter):
    provider = "google_calendar"
    display_name = "Google Calendar"
    category = "calendar"
    required_scopes = ["https://www.googleapis.com/auth/calendar.events"]
    permission_explanation = (
        "Reads calendar events to check availability/conflicts and creates or updates events only on explicit confirmation."
    )

    def _service(self, session: Session, user_id: str):
        creds = self.get_credentials(session, user_id)
        return build("calendar", "v3", credentials=creds, cache_discovery=False)

    def list_events(
        self,
        session: Session,
        user_id: str,
        *,
        time_min_iso: Optional[str] = None,
        max_results: int = 25,
    ) -> List[Dict[str, Any]]:
        svc = self._service(session, user_id)
        params: Dict[str, Any] = {
            "calendarId": "primary",
            "maxResults": max_results,
            "singleEvents": True,
            "orderBy": "startTime",
        }
        if time_min_iso:
            params["timeMin"] = time_min_iso
        resp = svc.events().list(**params).execute()
        return [
            {
                "id": e.get("id"),
                "title": e.get("summary", "(Untitled)"),
                "start": e.get("start", {}).get("dateTime") or e.get("start", {}).get("date"),
                "end": e.get("end", {}).get("dateTime") or e.get("end", {}).get("date"),
                "attendees": [a.get("email") for a in e.get("attendees", []) if a.get("email")],
            }
            for e in resp.get("items", [])
        ]

    def create_event(
        self,
        session: Session,
        user_id: str,
        *,
        title: str,
        start_iso: str,
        end_iso: str,
        timezone_name: str = "UTC",
        attendees: Optional[List[str]] = None,
        description: str = "",
    ) -> Dict[str, Any]:
        svc = self._service(session, user_id)
        body = {
            "summary": title,
            "description": description,
            "start": {"dateTime": start_iso, "timeZone": timezone_name},
            "end": {"dateTime": end_iso, "timeZone": timezone_name},
            "attendees": [{"email": email} for email in (attendees or [])],
        }
        created = svc.events().insert(calendarId="primary", body=body).execute()
        return {
            "id": created.get("id"),
            "title": created.get("summary"),
            "htmlLink": created.get("htmlLink"),
            "status": "created_in_google_calendar",
        }
