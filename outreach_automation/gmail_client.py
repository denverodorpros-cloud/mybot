from __future__ import annotations

import base64
import mimetypes
from email.message import EmailMessage as MimeEmailMessage
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]


def _credentials(client_secret_file: Path, token_file: Path) -> Credentials:
    creds = None
    if token_file.exists():
        creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    elif not creds or not creds.valid:
        if not client_secret_file.exists():
            raise FileNotFoundError(f"Gmail client secret file not found: {client_secret_file}")
        flow = InstalledAppFlow.from_client_secrets_file(str(client_secret_file), SCOPES)
        creds = flow.run_local_server(port=0)

    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(creds.to_json(), encoding="utf-8")
    return creds


def send_email(
    *,
    sender: str,
    to: str,
    subject: str,
    body: str,
    html_body: str | None = None,
    inline_logo_file: Path | None = None,
    client_secret_file: Path,
    token_file: Path,
) -> str:
    creds = _credentials(client_secret_file, token_file)
    service = build("gmail", "v1", credentials=creds)

    message = MimeEmailMessage()
    message["To"] = to
    message["From"] = sender
    message["Subject"] = subject
    message.set_content(body)
    if html_body:
        message.add_alternative(html_body, subtype="html")
        if inline_logo_file and inline_logo_file.exists():
            mime_type, _ = mimetypes.guess_type(inline_logo_file)
            maintype, subtype = (mime_type or "image/png").split("/", 1)
            html_part = message.get_payload()[-1]
            html_part.add_related(
                inline_logo_file.read_bytes(),
                maintype=maintype,
                subtype=subtype,
                cid="<denver-odor-pros-logo>",
                filename=inline_logo_file.name,
            )

    encoded = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
    sent = service.users().messages().send(userId="me", body={"raw": encoded}).execute()
    return sent["id"]
