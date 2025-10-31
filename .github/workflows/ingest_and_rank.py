"""
ingest_and_rank.py
1. Pulls Google Form responses
2. Downloads each candidate's resume PDF from Drive
3. Extracts text
4. Builds a shortlist ranked by keyword relevance

This is the "intake + screening" brain.
"""

import os
import re
from rich import print as rprint
from googleapiclient.http import MediaIoBaseDownload

from recruito_agent.utils import (
    valid_email,
    extract_any_email_from_text,
    extract_drive_file_id,
    pdf_to_text,
)


KEYWORDS = [
    "python","java","node","go","rest","http","api","graphql",
    "postgres","mysql","mongodb","redis",
    "docker","kubernetes","aws","gcp","azure",
    "unit test","pytest","junit","integration test"
]


def list_form_responses(forms_client, form_id: str, page_size: int = 200):
    """Fetch all responses from the Google Form."""
    out, token = [], None
    while True:
        resp = forms_client.forms().responses().list(
            formId=form_id,
            pageSize=page_size,
            pageToken=token
        ).execute()
        out.extend(resp.get("responses", []))
        token = resp.get("nextPageToken")
        if not token:
            break
    return out


def get_text_answer(response: dict, question_id: str) -> str | None:
    answers = response.get("answers", {}) or {}
    entry = answers.get(question_id)
    if not entry:
        return None
    vals = (entry.get("textAnswers", {}).get("answers", []) or [])
    return vals[0].get("value") if vals else None


def download_drive_file(drive_client, file_id: str, local_path: str):
    """Download a Drive file by ID -> local_path."""
    req = drive_client.files().get_media(fileId=file_id)
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    with open(local_path, "wb") as fh:
        downloader = MediaIoBaseDownload(fh, req)
        done = False
        while not done:
            status, done = downloader.next_chunk()
    return local_path


def sync_and_score(
    clients: dict,
    form_id: str,
    sheet_id: str,
    drive_link_qid: str,
    email_qid: str | None,
    download_dir="cv_pdfs",
    shortlist_top_n=5,
):
    """
    - Reads raw responses
    - For each response, grab candidate email + drive link
    - Download resume PDF locally
    - Extract text, infer skill keywords
    - Compute simple score = keyword hits
    - Append raw log to the Sheet ("Raw")
    - Return shortlist
    """

    forms_client = clients["forms"]
    sheets_client = clients["sheets"]
    drive_client = clients["drive"]
    os.makedirs(download_dir, exist_ok=True)

    # ensure "Raw" tab exists
    try:
        sheets_client.spreadsheets().batchUpdate(
            spreadsheetId=sheet_id,
            body={"requests": [{"addSheet": {"properties": {"title": "Raw"}}}]}
        ).execute()
    except Exception:
        pass

    responses = list_form_responses(forms_client, form_id)
    rows_for_sheet = [["responseId","timestamp","email","fileId","fileViewLink","status"]]

    candidates = []

    for resp in responses:
        rid = resp.get("responseId")
        ts  = resp.get("createTime", "")

        email_val = ""
        if email_qid:
            email_val = valid_email(get_text_answer(resp, email_qid))
        if not email_val:
            # fallback to respondentEmail if form is set to collect email
            email_val = valid_email(resp.get("respondentEmail", ""))

        resume_link_val = get_text_answer(resp, drive_link_qid)
        fid = extract_drive_file_id(resume_link_val)

        file_meta = {}
        local_resume_path = ""
        status = "missing_resume"

        if fid:
            try:
                file_meta = drive_client.files().get(
                    fileId=fid,
                    fields="id,name,mimeType,webViewLink"
                ).execute()

                file_name = file_meta.get("name", f"{fid}.pdf")
                if not file_name.lower().endswith(".pdf"):
                    file_name += ".pdf"

                safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", file_name)
                local_resume_path = os.path.join(download_dir, f"{fid}_{safe_name}")

                download_drive_file(drive_client, fid, local_resume_path)
                status = "downloaded"
            except Exception as e:
                status = f"download_error:{e}"

        # parse PDF and infer skills
        cv_text = pdf_to_text(local_resume_path, max_pages=15) if status == "downloaded" else ""
        inferred_email = valid_email(email_val) or valid_email(extract_any_email_from_text(cv_text))

        # simple keyword score
        blob = (cv_text or "").lower()
        score = sum(1 for kw in KEYWORDS if kw in blob)

        candidates.append({
            "name": file_meta.get("name", "Candidate"),
            "email": inferred_email,
            "score": float(score),
            "cv_link": file_meta.get("webViewLink", ""),
        })

        rows_for_sheet.append([
            rid,
            ts,
            inferred_email,
            fid or "",
            file_meta.get("webViewLink", ""),
            status,
        ])

    # write Raw log
    sheets_client.spreadsheets().values().append(
        spreadsheetId=sheet_id,
        range="Raw!A1",
        valueInputOption="RAW",
        body={"values": rows_for_sheet}
    ).execute()

    # shortlist top N by score
    candidates.sort(key=lambda x: x["score"], reverse=True)
    shortlist = candidates[:shortlist_top_n]

    # write Shortlist tab
    try:
        sheets_client.spreadsheets().batchUpdate(
            spreadsheetId=sheet_id,
            body={"requests":[{"addSheet":{"properties":{"title":"Shortlist"}}}]}
        ).execute()
    except Exception:
        pass

    shortlist_rows = [["Name","Email","Score","CV link"]]
    for c in shortlist:
        shortlist_rows.append([c["name"], c["email"], c["score"], c["cv_link"]])

    sheets_client.spreadsheets().values().update(
        spreadsheetId=sheet_id,
        range="Shortlist!A1",
        valueInputOption="RAW",
        body={"values": shortlist_rows}
    ).execute()

    rprint("[bold blue]Shortlist created and written to 'Shortlist' tab.[/bold blue]")
    return shortlist
