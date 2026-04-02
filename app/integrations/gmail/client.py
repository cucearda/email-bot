from __future__ import annotations

import base64
import logging
from email.message import EmailMessage
from email.utils import parsedate_to_datetime
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.core.config import Settings

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


def load_credentials(settings: Settings) -> Credentials:
    creds: Credentials | None = None
    if settings.gmail_token_path:
        try:
            creds = Credentials.from_authorized_user_file(settings.gmail_token_path, SCOPES)
        except OSError:
            creds = None
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(settings.gmail_token_path, "w", encoding="utf-8") as token:
            token.write(creds.to_json())
        return creds
    raise RuntimeError(
        f"No valid Gmail token at {settings.gmail_token_path}. Run: python -m app.cli gmail-auth"
    )


def run_oauth_local_server(settings: Settings) -> None:
    flow = InstalledAppFlow.from_client_secrets_file(settings.gmail_credentials_path, SCOPES)
    creds = flow.run_local_server(port=0)
    with open(settings.gmail_token_path, "w", encoding="utf-8") as token:
        token.write(creds.to_json())


def _header(headers: list[dict[str, str]], name: str) -> str | None:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value")
    return None


def _decode_body_data(data_b64: str) -> str:
    raw = base64.urlsafe_b64decode(data_b64 + "===")
    try:
        return raw.decode("utf-8", errors="replace")
    except Exception:
        return raw.decode("latin-1", errors="replace")


def extract_plain_text_from_payload(payload: dict[str, Any]) -> str:
    mime = payload.get("mimeType", "")
    body = payload.get("body", {})
    data = body.get("data")
    if data and mime.startswith("text/plain"):
        return _decode_body_data(data)
    parts = payload.get("parts") or []
    for p in parts:
        nested = extract_plain_text_from_payload(p)
        if nested.strip():
            return nested
    if data and "text" in mime:
        return _decode_body_data(data)
    return ""


def parse_message_resource(msg: dict[str, Any]) -> dict[str, Any]:
    payload = msg.get("payload") or {}
    headers = payload.get("headers") or []
    internal_ms = int(msg.get("internalDate", 0))
    received = None
    if internal_ms:
        from datetime import datetime, timezone

        received = datetime.fromtimestamp(internal_ms / 1000.0, tz=timezone.utc)
    date_hdr = _header(headers, "Date")
    if received is None and date_hdr:
        try:
            received = parsedate_to_datetime(date_hdr)
            if received.tzinfo is None:
                from datetime import timezone as tz

                received = received.replace(tzinfo=tz.utc)
        except (TypeError, ValueError):
            pass
    return {
        "gmail_message_id": msg["id"],
        "thread_id": msg["threadId"],
        "snippet": msg.get("snippet") or "",
        "from_address": _header(headers, "From") or "",
        "subject": _header(headers, "Subject") or "",
        "rfc_message_id": _header(headers, "Message-ID") or _header(headers, "Message-Id") or "",
        "body_text": extract_plain_text_from_payload(payload) or (msg.get("snippet") or ""),
        "received_at": received,
    }


class GmailClient:
    def __init__(self, settings: Settings):
        self._settings = settings
        creds = load_credentials(settings)
        self._service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        self._user_id = "me"
        self._label_name_to_id: dict[str, str] = {}

    def list_unread_message_ids(self, max_results: int = 50) -> list[str]:
        out: list[str] = []
        page_token = None
        while len(out) < max_results:
            req = (
                self._service.users()
                .messages()
                .list(
                    userId=self._user_id,
                    q="is:unread in:inbox",
                    maxResults=min(50, max_results - len(out)),
                    pageToken=page_token,
                )
            )
            res = req.execute()
            for m in res.get("messages") or []:
                out.append(m["id"])
            page_token = res.get("nextPageToken")
            if not page_token:
                break
        return out[:max_results]

    def get_message(self, message_id: str) -> dict[str, Any]:
        return (
            self._service.users()
            .messages()
            .get(userId=self._user_id, id=message_id, format="full")
            .execute()
        )

    def _refresh_label_map(self) -> None:
        res = self._service.users().labels().list(userId=self._user_id).execute()
        self._label_name_to_id = {l["name"]: l["id"] for l in res.get("labels", [])}

    def ensure_label_id(self, label_name: str) -> str:
        if not self._label_name_to_id:
            self._refresh_label_map()
        if label_name in self._label_name_to_id:
            return self._label_name_to_id[label_name]
        body = {
            "name": label_name,
            "labelListVisibility": "labelShow",
            "messageListVisibility": "show",
        }
        try:
            created = self._service.users().labels().create(userId=self._user_id, body=body).execute()
        except HttpError as e:
            if e.resp.status == 409:
                self._refresh_label_map()
                return self._label_name_to_id[label_name]
            raise
        self._label_name_to_id[label_name] = created["id"]
        return created["id"]

    def add_labels(self, message_id: str, label_names: list[str]) -> None:
        ids = [self.ensure_label_id(n) for n in label_names]
        self._service.users().messages().modify(
            userId=self._user_id, id=message_id, body={"addLabelIds": ids}
        ).execute()

    def mark_read(self, message_id: str) -> None:
        """Remove UNREAD so cron does not keep picking up the same message."""
        self._service.users().messages().modify(
            userId=self._user_id, id=message_id, body={"removeLabelIds": ["UNREAD"]}
        ).execute()

    def get_profile_email(self) -> str:
        prof = self._service.users().getProfile(userId=self._user_id).execute()
        return prof["emailAddress"]

    def send_reply_in_thread(
        self,
        *,
        thread_id: str,
        to_address: str,
        subject: str,
        plain_body: str,
        in_reply_to: str,
        references: str,
    ) -> str:
        profile_from = self.get_profile_email()
        msg = EmailMessage()
        msg["Subject"] = subject if subject.lower().startswith("re:") else f"Re: {subject}"
        msg["To"] = to_address
        msg["From"] = profile_from
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
        if references:
            msg["References"] = references
        msg.set_content(plain_body, subtype="plain", charset="utf-8")
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        body = {"raw": raw, "threadId": thread_id}
        sent = self._service.users().messages().send(userId=self._user_id, body=body).execute()
        return sent["id"]
