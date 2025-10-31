"""
mailer.py
1. For each scheduled slot, generate .ics
2. Send calendar invite email via Gmail API
3. Log results (you can append these results back to the Sheet)
"""

import base64
import email.utils
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from recruito_agent.auth import gmail_service


def send_interview_invite(
    organizer_name: str,
    sender_email: str,
    role_prompt: str,
    slot,
    ics_text: str,
):
    """
    slot = {
      "candidate_name": ...,
      "candidate_email": ...,
      "start": datetime(...),
    }
    """
    to_addr = slot["candidate_email"]
    cand_name = slot["candidate_name"]

    subject = f"Interview: {role_prompt} — {cand_name}"
    body = f"""Hi {cand_name},

We’d like to invite you for an interview for {role_prompt}.
Please accept the attached calendar invite to confirm.

Thanks,
{organizer_name}
"""

    msg = MIMEMultipart("alternative")
    msg["From"] = email.utils.formataddr((organizer_name, sender_email))
    msg["To"] = to_addr
    msg["Subject"] = subject

    # Plain text body
    msg.attach(MIMEText(body, "plain", "utf-8"))

    # Calendar part
    ics_part = MIMEText(ics_text, "calendar", "utf-8")
    ics_part.add_header("Content-Class", "urn:content-classes:calendarmessage")
    ics_part.add_header("Content-Type", "text/calendar; method=REQUEST; charset=UTF-8")
    msg.attach(ics_part)

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")

    svc = gmail_service()
    resp = svc.users().messages().send(
        userId="me", body={"raw": raw}
    ).execute()

    return {
        "gmail_message_id": resp.get("id"),
        "gmail_thread_id": resp.get("threadId"),
        "to": to_addr,
    }
