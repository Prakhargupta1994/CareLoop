"""Deliver a follow-up message.

Chosen with CARELOOP_MAILER:
  mock    (default) -> print the email to the console. No network, no auth.
  gmail             -> send via the Gmail API.

Local -> Firestore taught the pattern: keep the real integration one env
flip away, but default to something that always works so the demo never
depends on a live service. Gmail is the fiddliest of the integrations
because sending from a personal account needs OAuth consent (there is no
service-account shortcut like Firestore had), so it stays opt-in and the
mock is the default. The Gmail path is written below but requires a
credentials.json / token.json you generate once (see CARELOOP_MASTER.md).
"""

from __future__ import annotations

import os

CARELOOP_MAILER = os.getenv("CARELOOP_MAILER", "mock").lower()

BAR = "-" * 60


def send(to: str, subject: str, body: str) -> dict:
    """Deliver a message via the configured mailer."""
    if CARELOOP_MAILER == "smtp":
        return _smtp_send(to, subject, body)
    if CARELOOP_MAILER == "gmail":
        return _gmail_send(to, subject, body)
    return _mock_send(to, subject, body)


def _mock_send(to: str, subject: str, body: str) -> dict:
    print(BAR)
    print(f"[MOCK EMAIL]  to: {to}")
    print(f"Subject: {subject}")
    print(BAR)
    print(body)
    print(BAR)
    return {"status": "mock-sent", "to": to, "subject": subject}


# --- Real Gmail (opt-in). Needs one-time OAuth setup. --------------------
def _gmail_send(to: str, subject: str, body: str) -> dict:
    import base64
    from email.mime.text import MIMEText

    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "CARELOOP_MAILER=gmail needs the Google API client. Install:\n"
            "  pip install google-api-python-client google-auth-oauthlib\n"
            "Or unset CARELOOP_MAILER to use the mock mailer."
        ) from exc

    token_path = os.getenv("CARELOOP_GMAIL_TOKEN", "token.json")
    if not os.path.exists(token_path):
        raise RuntimeError(
            f"Gmail token not found at {token_path}. Run the one-time OAuth "
            f"consent to create it (see CARELOOP_MASTER.md), or use the mock "
            f"mailer. Sending from a personal Gmail requires user consent -- "
            f"there is no service-account shortcut."
        )

    creds = Credentials.from_authorized_user_file(
        token_path, ["https://www.googleapis.com/auth/gmail.send"]
    )
    service = build("gmail", "v1", credentials=creds)

    mime = MIMEText(body)
    mime["to"] = to
    mime["subject"] = subject
    raw = base64.urlsafe_b64encode(mime.as_bytes()).decode()

    sent = service.users().messages().send(userId="me", body={"raw": raw}).execute()
    return {"status": "sent", "to": to, "subject": subject, "id": sent.get("id")}


# --- Real email via SMTP (simplest real path: a Gmail App Password). -----
def _smtp_send(to: str, subject: str, body: str) -> dict:
    """Send a real email using SMTP. For Gmail, generate an App Password
    (Google Account -> Security -> App passwords; needs 2-step verification)
    and set EMAIL_USER and EMAIL_PASS in careloop/.env. No OAuth needed."""
    import smtplib
    from email.mime.text import MIMEText

    user = os.getenv("EMAIL_USER", "")
    password = os.getenv("EMAIL_PASS", "")
    host = os.getenv("EMAIL_SMTP_HOST", "smtp.gmail.com")
    port = int(os.getenv("EMAIL_SMTP_PORT", "465"))
    if not user or not password:
        raise RuntimeError(
            "CARELOOP_MAILER=smtp needs EMAIL_USER and EMAIL_PASS in your .env "
            "(for Gmail, an App Password). Or unset CARELOOP_MAILER to use the mock."
        )

    mime = MIMEText(body)
    mime["Subject"] = subject
    mime["From"] = user
    mime["To"] = to
    with smtplib.SMTP_SSL(host, port) as server:
        server.login(user, password)
        server.send_message(mime)
    return {"status": "sent (real email via SMTP)", "to": to, "subject": subject}
