"""Fetches relevant emails from Gmail for the current week."""

import base64
import json
import os
from datetime import datetime, timedelta, timezone
from email import message_from_bytes

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build


JST = timezone(timedelta(hours=9))
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def get_gmail_service():
    token_json = os.environ.get("GMAIL_TOKEN_JSON", "")
    if not token_json:
        raise ValueError("GMAIL_TOKEN_JSON environment variable is not set")

    token_data = json.loads(token_json)
    creds = Credentials(
        token=token_data.get("token"),
        refresh_token=token_data.get("refresh_token"),
        token_uri=token_data.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=token_data.get("client_id"),
        client_secret=token_data.get("client_secret"),
        scopes=token_data.get("scopes", SCOPES),
    )

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())

    return build("gmail", "v1", credentials=creds)


def get_week_query() -> str:
    now = datetime.now(JST)
    monday = now - timedelta(days=now.weekday())
    after = monday.strftime("%Y/%m/%d")
    return f"after:{after} -category:promotions -category:social -category:updates"


def decode_body(payload: dict) -> str:
    """Recursively decode email body from Gmail API payload."""
    mime_type = payload.get("mimeType", "")
    body = payload.get("body", {})
    data = body.get("data", "")

    if data and mime_type in ("text/plain", "text/html"):
        try:
            decoded = base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
            if mime_type == "text/html":
                # Strip HTML tags crudely for summary
                import re
                decoded = re.sub(r"<[^>]+>", " ", decoded)
                decoded = re.sub(r"\s+", " ", decoded).strip()
            return decoded[:2000]
        except Exception:
            return ""

    parts = payload.get("parts", [])
    for part in parts:
        result = decode_body(part)
        if result:
            return result

    return ""


def get_header(headers: list[dict], name: str) -> str:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def fetch_week_emails(project_names: list[str] | None = None, max_results: int = 30) -> list[dict]:
    """Fetch relevant emails from this week."""
    try:
        service = get_gmail_service()
    except Exception as e:
        print(f"Gmail auth error: {e}")
        return []

    query = get_week_query()

    # If project names provided, add them as OR search
    if project_names:
        names_query = " OR ".join(f'"{name}"' for name in project_names[:10] if name)
        if names_query:
            query = f"({names_query}) {query}"

    try:
        result = service.users().messages().list(
            userId="me",
            q=query,
            maxResults=max_results
        ).execute()
    except Exception as e:
        print(f"Gmail search error: {e}")
        return []

    messages = result.get("messages", [])
    emails = []

    for msg in messages:
        try:
            full = service.users().messages().get(
                userId="me",
                id=msg["id"],
                format="full"
            ).execute()

            payload = full.get("payload", {})
            headers = payload.get("headers", [])

            subject = get_header(headers, "Subject")
            sender = get_header(headers, "From")
            date = get_header(headers, "Date")
            body = decode_body(payload)

            emails.append({
                "subject": subject,
                "from": sender,
                "date": date,
                "body_preview": body[:800] if body else "",
                "thread_id": full.get("threadId", ""),
            })
        except Exception:
            continue

    return emails
