"""
form_and_sheet.py
Creates:
1. Google Sheet to collect applicants
2. Google Form to capture candidate info
3. Adds questions like name/email/drive link to resume
"""

from rich import print as rprint

def create_sheet(sheets_client, title: str) -> dict:
    ss = sheets_client.spreadsheets().create(
        body={"properties": {"title": title}},
        fields="spreadsheetId,spreadsheetUrl"
    ).execute()
    return {
        "spreadsheet_id": ss["spreadsheetId"],
        "spreadsheet_url": ss.get("spreadsheetUrl")
    }


def create_form(forms_client, role_prompt: str) -> str:
    fm = forms_client.forms().create(
        body={"info": {"title": f"Application — {role_prompt}"}}
    ).execute()
    return fm["formId"]


def batch_update_form(forms_client, form_id: str, role_prompt: str, jd_text: str):
    """
    - Injects JD into the Form description
    - Adds questions (Name, Email, YOE, Motivation, Resume link, LinkedIn)
    """
    desc = jd_text if len(jd_text) <= 4000 else (jd_text[:3996] + " …")

    def create_text_q(title, paragraph, required, index, description=None):
        item = {
            "title": title,
            "questionItem": {
                "question": {
                    "required": required,
                    "textQuestion": {"paragraph": paragraph}
                }
            }
        }
        if description:
            item["description"] = description

        return {
            "createItem": {
                "item": item,
                "location": {"index": index}
            }
        }

    requests = [
        {
            "updateFormInfo": {
                "info": {"description": desc},
                "updateMask": "description"
            }
        },
        create_text_q("Full name", False, True, 0, None),
        create_text_q("Email", False, True, 1, None),
        {
            "createItem": {
                "item": {
                    "title": "Years of experience",
                    "questionItem": {
                        "question": {
                            "required": True,
                            "choiceQuestion": {
                                "type": "RADIO",
                                "options": [{"value":"0"}, {"value":"1"}, {"value":"2"}],
                                "shuffle": False
                            }
                        }
                    }
                },
                "location": {"index": 2}
            }
        },
        create_text_q(
            f"Why are you a fit for {role_prompt}?",
            True, True, 3, None
        ),
        create_text_q(
            "Resume Google Drive link (PDF)",
            False, True, 4,
            "Paste a Google Drive link to your PDF resume. "
            "Ensure 'Anyone with the link' can view."
        ),
        create_text_q("LinkedIn URL", False, False, 5, None),
    ]

    forms_client.forms().batchUpdate(
        formId=form_id,
        body={"requests": requests}
    ).execute()


def fetch_form_metadata(forms_client, form_id: str) -> dict:
    return forms_client.forms().get(formId=form_id).execute()


def find_question_id_case_insensitive(form_metadata: dict, wanted_title: str) -> str | None:
    want = wanted_title.strip().lower()
    for item in form_metadata.get("items", []):
        if (item.get("title") or "").strip().lower() == want:
            q = (item.get("questionItem") or {}).get("question") or {}
            qid = q.get("questionId")
            if qid:
                return qid
    return None


def setup_application_pipeline(clients: dict, role_prompt: str, jd_text: str) -> dict:
    """
    High-level orchestration:
    - Create Sheets
    - Create Form
    - Inject JD, add questions to the Form
    - Grab responder URL + specific question IDs (like Resume link)
    """
    sheets_client = clients["sheets"]
    forms_client = clients["forms"]

    sheet_info = create_sheet(sheets_client, f"Applications — {role_prompt}")
    sheet_id = sheet_info["spreadsheet_id"]

    form_id = create_form(forms_client, role_prompt)
    batch_update_form(forms_client, form_id, role_prompt, jd_text)

    meta = fetch_form_metadata(forms_client, form_id)
    form_url = meta.get("responderUri", f"https://docs.google.com/forms/d/{form_id}/viewform")

    drive_link_qid = find_question_id_case_insensitive(meta, "Resume Google Drive link (PDF)")
    email_qid      = find_question_id_case_insensitive(meta, "Email")

    rprint(f"[bold green]Sheet:[/bold green] {sheet_info['spreadsheet_url']}")
    rprint(f"[bold green]Form:[/bold green]  {form_url}")

    return {
        "sheet_id": sheet_id,
        "sheet_url": sheet_info["spreadsheet_url"],
        "form_id": form_id,
        "form_url": form_url,
        "drive_link_qid": drive_link_qid,
        "email_qid": email_qid,
    }
