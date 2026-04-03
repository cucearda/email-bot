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
    logger.warning("No valid Gmail token — launching OAuth flow")
    run_oauth_local_server(settings)
    return Credentials.from_authorized_user_file(settings.gmail_token_path, SCOPES)


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

    def get_message(self, message_id: str) -> dict[str, Any]:
        try:
            return (
                self._service.users()
                .messages()
                .get(userId=self._user_id, id=message_id, format="full")
                .execute()
            )
        except HttpError:
            logger.error("get_message failed for %s", message_id)
            raise
        except Exception:
            logger.error("get_message unexpected error for %s", message_id, exc_info=True)
            raise

    def _refresh_label_map(self) -> None:
        try:
            res = self._service.users().labels().list(userId=self._user_id).execute()
        except HttpError:
            logger.error("labels.list failed", exc_info=True)
            raise
        self._label_name_to_id = {lab["name"]: lab["id"] for lab in res.get("labels", [])}

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
                if label_name in self._label_name_to_id:
                    return self._label_name_to_id[label_name]
                logger.error("Label %r not found after 409 refresh", label_name)
                raise
            logger.error("labels.create failed for %r (status=%s)", label_name, e.resp.status)
            raise
        self._label_name_to_id[label_name] = created["id"]
        return created["id"]

    def add_labels(self, message_id: str, label_names: list[str]) -> None:
        ids = [self.ensure_label_id(n) for n in label_names]
        try:
            self._service.users().messages().modify(
                userId=self._user_id, id=message_id, body={"addLabelIds": ids}
            ).execute()
        except HttpError:
            logger.error("add_labels failed for %s labels=%s", message_id, label_names)
            raise

    def mark_read(self, message_id: str) -> None:
        try:
            self._service.users().messages().modify(
                userId=self._user_id, id=message_id, body={"removeLabelIds": ["UNREAD"]}
            ).execute()
        except HttpError:
            logger.error("mark_read failed for %s", message_id)
            raise

    def get_profile_email(self) -> str:
        try:
            prof = self._service.users().getProfile(userId=self._user_id).execute()
        except HttpError:
            logger.error("get_profile failed", exc_info=True)
            raise
        return prof["emailAddress"]

    def watch(self, project_id: str, topic_name: str) -> dict[str, Any]:
        """Register Gmail push notifications via Pub/Sub. Expires after ~7 days."""
        body = {
            "topicName": f"projects/{project_id}/topics/{topic_name}",
            "labelIds": ["INBOX"],
        }
        try:
            return (
                self._service.users()
                .watch(userId=self._user_id, body=body)
                .execute()
            )
        except HttpError:
            logger.error("watch failed for project=%s topic=%s", project_id, topic_name)
            raise

    def history_list(self, start_history_id: str) -> list[str]:
        """Return message IDs added to INBOX since start_history_id."""
        logger.debug("history_list called with startHistoryId=%s", start_history_id)
        message_ids: list[str] = []
        page_token = None
        while True:
            req = (
                self._service.users()
                .history()
                .list(
                    userId=self._user_id,
                    startHistoryId=start_history_id,
                    historyTypes=["messageAdded"],
                    labelId="INBOX",
                    pageToken=page_token,
                )
            )
            try:
                res = req.execute()
            except HttpError as e:
                if e.resp.status == 404:
                    logger.warning("historyId %s expired (404), returning empty", start_history_id)
                    return []
                logger.error("history.list failed (status=%s) for historyId=%s", e.resp.status, start_history_id)
                raise
            logger.debug("history_list raw response: historyId=%s, history_count=%d, keys=%s",
                         res.get("historyId"), len(res.get("history", [])), list(res.keys()))
            for record in res.get("history", []):
                logger.debug("history record: %s", record)
                for added in record.get("messagesAdded", []):
                    mid = added["message"]["id"]
                    labels = added["message"].get("labelIds", [])
                    logger.debug("messagesAdded: id=%s labels=%s", mid, labels)
                    if mid not in message_ids:
                        message_ids.append(mid)
            page_token = res.get("nextPageToken")
            if not page_token:
                break
        logger.debug("history_list result: %d message(s) -> %s", len(message_ids), message_ids)
        return message_ids

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
        send_body = {"raw": raw, "threadId": thread_id}
        try:
            sent = self._service.users().messages().send(userId=self._user_id, body=send_body).execute()
        except HttpError:
            logger.error("send_reply failed for thread=%s to=%s", thread_id, to_address)
            raise
        return sent["id"]


_cached_client: GmailClient | None = None


def get_gmail_client(settings: Settings | None = None) -> GmailClient:
    """Return a cached GmailClient, recreating on auth errors."""
    global _cached_client
    if _cached_client is None:
        from app.core.config import get_settings
        _cached_client = GmailClient(settings or get_settings())
    return _cached_client


def reset_gmail_client() -> None:
    """Clear cached client (e.g. after auth failure)."""
    global _cached_client
    _cached_client = None
