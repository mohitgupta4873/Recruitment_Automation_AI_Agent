"""
outcomes.py
After interviews, mark candidates as "selected" or "rejected":
- Send acceptance or regret emails
- Append results to a sheet tab "Outcome"
"""

import base64
from datetime import datetime
from email.mime.text import MIMEText

from recruito_agent.auth import gmail_service


def _send_plain_email(sender_email: str, to_email: str, subject: str, body: str):
    msg = MIMEText(body, _charset="utf-8")
    msg["To"] = to_email
    msg["From"] = sender_email
    msg["Subject"] = subject
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
    svc = gmail_service()
    return svc.users().messages().send(userId="me", body={"raw": raw}).execute()


def build_acceptance_body(candidate_name: str, role_prompt: str, organizer_name: str) -> str:
    return f"""Hi {candidate_name},

Congratulations! We'd love to move forward with you for the {role_prompt} role.

Next steps:
• We'll share offer details and onboarding info.
• If you have any questions, just reply to this email.

Welcome aboard!
{organizer_name}
"""


def build_regret_body(candidate_name: str, role_prompt: str, organizer_name: str) -> str:
    return f"""Hi {candidate_name},

Thank you for interviewing for the {role_prompt} role. We truly appreciate the time you invested.

After careful consideration, we will not be moving ahead this time.
Please don't be discouraged — we'll keep your profile in mind for future roles.

Wishing you all the best,
{organizer_name}
"""


def log_outcomes_to_sheet(sheets_client, sheet_id: str, rows: list[list[str]]):
    """
    Append rows to the "Outcome" tab in the sheet.
    Each row: [timestamp, name, email, status, gmail_msg_id]
    """
    # make sure "Outcome" tab exists
    try:
        sheets_client.spreadsheets().batchUpdate(
            spreadsheetId=sheet_id,
            body={"requests":[{"addSheet":{"properties":{"title":"Outcome"}}}]}
        ).execute()
    except Exception:
        pass

    header = [["Timestamp","Name","Email","Outcome","Gmail Msg Id"]]
    sheets_client.spreadsheets().values().append(
        spreadsheetId=sheet_id,
        range="Outcome!A1",
        valueInputOption="RAW",
        body={"values": header + rows}
    ).execute()


def process_outcomes(
    sheets_client,
    sheet_id: str,
    role_prompt: str,
    organizer_name: str,
    sender_email: str,
    shortlisted: list[dict],
    selected_indexes: set[int],
):
    """
    shortlisted is like:
    [
      {"name": "...", "email": "...", "score": 7.0, "cv_link": "..."},
      ...
    ]

    selected_indexes is a set of 1-based indexes of selected candidates.
    Others will receive regret mail.
    """

    results_for_sheet = []
    timestamp = datetime.now().isoformat(timespec="seconds")

    for i, cand in enumerate(shortlisted, start=1):
        name = cand.get("name","Candidate")
        email = cand.get("email","").strip()

        if not email:
            results_for_sheet.append([timestamp, name, email, "skipped_invalid_email", ""])
            continue

        if i in selected_indexes:
            subject = f"Offer — {role_prompt}"
            body = build_acceptance_body(name, role_prompt, organizer_name)
            status_label = "sent_accept"
        else:
            subject = f"Thank you — {role_prompt}"
            body = build_regret_body(name, role_prompt, organizer_name)
            status_label = "sent_regret"

        try:
            resp = _send_plain_email(sender_email, email, subject, body)
            msg_id = resp.get("id", "")
            results_for_sheet.append([timestamp, name, email, status_label, msg_id])
        except Exception as e:
            results_for_sheet.append([timestamp, name, email, f"send_error:{e}", ""])

    log_outcomes_to_sheet(sheets_client, sheet_id, results_for_sheet)
