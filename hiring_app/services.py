import os
import json
import base64
import re
import uuid
import io
import email.utils
import requests
from datetime import datetime, timedelta
from dateutil import tz
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# Google Libraries
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from pypdf import PdfReader
import google.generativeai as genai
from django.conf import settings

SCOPES = [
    "https://www.googleapis.com/auth/forms.body",
    "https://www.googleapis.com/auth/forms.responses.readonly",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/gmail.send",
]

class HiringAutomator:
    def __init__(self, token_path='token.json', state_path='campaign_state.json'):
        self.state_path = state_path
        self.creds = None
        
        if os.path.exists(token_path):
            self.creds = Credentials.from_authorized_user_file(token_path, SCOPES)
        else:
            print(f"⚠️ Warning: {token_path} not found.")

        if self.creds:
            self.forms = build("forms", "v1", credentials=self.creds, cache_discovery=False)
            self.sheets = build("sheets", "v4", credentials=self.creds, cache_discovery=False)
            self.drive = build("drive", "v3", credentials=self.creds, cache_discovery=False)
            self.gmail = build("gmail", "v1", credentials=self.creds, cache_discovery=False)
        
        if hasattr(settings, 'GEMINI_API_KEY') and settings.GEMINI_API_KEY:
            genai.configure(api_key=settings.GEMINI_API_KEY)

    def load_state(self):
        if os.path.exists(self.state_path):
            try: return json.load(open(self.state_path))
            except: return {}
        return {}

    def save_state(self, new_data):
        state = self.load_state()
        state.update(new_data)
        with open(self.state_path, "w") as f:
            json.dump(state, f, indent=2)
        return state

    # --- STEP 1: JD GENERATION (Uses Experience + Lite Model) ---
    def generate_jd(self, role_title, experience):
        prompt = f"""Draft an inclusive, crisp Job Description for: {role_title}.
Required Experience: {experience}.
Include: About the role, Responsibilities, Must-haves, Nice-to-haves, What we offer, How to apply.
Aim ~350–450 words. Bullets welcome."""
        
        try:
            model = genai.GenerativeModel("gemini-2.5-flash-lite") 
            resp = model.generate_content(prompt)
            return resp.text
        except Exception as e:
            return f"# {role_title}\n\n(AI Failed. Write manually.\nExp: {experience})"

    # --- NEW: LINKEDIN POSTING ---
    def post_to_linkedin(self, access_token, author_urn, role, jd_text, form_url):
        if not access_token or not author_urn: return None
        headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json", "X-Restli-Protocol-Version": "2.0.0"}
        post_text = f"🚀 We're hiring: {role}\n\nApply here: {form_url}\n\n{jd_text[:1000]}..."
        payload = {
            "author": author_urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {"com.linkedin.ugc.ShareContent": {"shareCommentary": {"text": post_text}, "shareMediaCategory": "NONE"}},
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"}
        }
        try:
            resp = requests.post("https://api.linkedin.com/v2/ugcPosts", headers=headers, json=payload)
            if resp.status_code in (200, 201): return resp.json().get("id")
        except: pass
        return None

    # --- STEP 2: CAMPAIGN CREATION (Clears old candidates) ---
    def create_campaign(self, role_title, jd_text, linkedin_token=None, linkedin_urn=None):
        # 1. Create Sheet & Form
        ss = self.sheets.spreadsheets().create(body={"properties": {"title": f"Applications — {role_title}"}}).execute()
        sheet_id = ss["spreadsheetId"]
        sheet_url = ss["spreadsheetUrl"]

        fm = self.forms.forms().create(body={"info": {"title": f"Application — {role_title}"}}).execute()
        form_id = fm["formId"]

        # Questions
        desc = jd_text[:3990] + "..." if len(jd_text) > 4000 else jd_text
        requests = [
            {"updateFormInfo": {"info": {"description": desc}, "updateMask": "description"}},
            self._q_text("Full name", 0),
            self._q_text("Email", 1),
            self._q_radio("Years of experience", ["0", "1", "2", "3+"], 2),
            self._q_text(f"Why are you a fit for {role_title}?", 3, paragraph=True),
            self._q_text("Resume Google Drive link (PDF)", 4, desc="Paste a generic shareable link"),
            self._q_text("LinkedIn URL", 5, required=False),
        ]
        self.forms.forms().batchUpdate(formId=form_id, body={"requests": requests}).execute()
        
        meta = self.forms.forms().get(formId=form_id).execute()
        form_url = meta.get("responderUri")
        drive_qid = self._get_qid(meta, "Resume Google Drive link (PDF)")
        email_qid = self._get_qid(meta, "Email")

        # LinkedIn
        linkedin_post_id = None
        if linkedin_token and linkedin_urn:
            linkedin_post_id = self.post_to_linkedin(linkedin_token, linkedin_urn, role_title, jd_text, form_url)

        # SAVE STATE - IMPORTANT: Reset candidates list to [] so new campaign is clean
        self.save_state({
            "role": role_title, "form_id": form_id, "form_url": form_url,
            "sheet_id": sheet_id, "sheet_url": sheet_url,
            "drive_qid": drive_qid, "email_qid": email_qid,
            "linkedin_post_id": linkedin_post_id,
            "processed_ids": [],
            "candidates": [] # <--- THIS LINE ENSURES ONLY NEW CANDIDATES SHOW
        })
        return form_url, sheet_url

    # --- STEP 3: SYNC & PARSE ---
    def sync_responses(self):
        state = self.load_state()
        if 'form_id' not in state: return {"error": "No active campaign"}
        
        sheet_id = state.get('sheet_id')
        processed_ids = set(state.get('processed_ids', []))

        responses = self.forms.forms().responses().list(formId=state['form_id']).execute().get('responses', [])
        
        # Load existing for this campaign, default to empty list
        processed_candidates = state.get('candidates', []) 
        new_rows = []
        
        download_dir = os.path.join(settings.MEDIA_ROOT, 'cv_pdfs')
        os.makedirs(download_dir, exist_ok=True)

        for resp in responses:
            resp_id = resp['responseId']
            if resp_id in processed_ids: continue 

            email = self._get_answer(resp, state.get('email_qid')) or resp.get('respondentEmail')
            drive_link = self._get_answer(resp, state.get('drive_qid'))
            create_time = resp.get('createTime')
            
            score = 0
            text_preview = "No PDF"
            status = "No Link"

            if drive_link:
                file_id = self._extract_file_id(drive_link)
                if file_id:
                    status = "Downloaded"
                    local_path = os.path.join(download_dir, f"{file_id}.pdf")
                    if not os.path.exists(local_path):
                        self._download_file(file_id, local_path)
                    
                    text = self._extract_text(local_path)
                    score = self._score_text(text)
                    text_preview = text[:200]
                    
                    processed_candidates.append({
                        "id": resp_id, "email": email, "file_id": file_id,
                        "score": score, "text_preview": text_preview, "drive_link": drive_link
                    })
            
            new_rows.append([resp_id, create_time, email, score, status, drive_link or ""])
            processed_ids.add(resp_id)

        if new_rows:
            try:
                self.sheets.spreadsheets().batchUpdate(spreadsheetId=sheet_id, body={
                    "requests": [{"addSheet": {"properties": {"title": "Responses"}}}]
                }).execute()
                header = [["Response ID", "Time", "Email", "AI Score", "Status", "Resume Link"]]
                self.sheets.spreadsheets().values().append(
                    spreadsheetId=sheet_id, range="Responses!A1", valueInputOption="RAW", body={"values": header}
                ).execute()
            except: pass 

            self.sheets.spreadsheets().values().append(
                spreadsheetId=sheet_id, range="Responses!A1", valueInputOption="RAW", body={"values": new_rows}
            ).execute()

        state['processed_ids'] = list(processed_ids)
        state['candidates'] = processed_candidates
        self.save_state(state)
        return processed_candidates

    # --- STEP 4 & 5 (Invites & Outcomes) ---
    def send_invites(self, candidate_emails, organizer_name, interview_date):
        state = self.load_state()
        role = state.get('role', 'Role')
        results = []
        try: dt_start = datetime.strptime(interview_date, "%Y-%m-%dT%H:%M")
        except ValueError: dt_start = datetime.strptime(interview_date, "%Y-%m-%dT%H:%M:%S")

        sender_email = "recruiter@example.com"
        try:
            profile = self.gmail.users().getProfile(userId='me').execute()
            sender_email = profile.get('emailAddress', sender_email)
        except: pass

        for i, email_addr in enumerate(candidate_emails):
            slot_time = dt_start + timedelta(minutes=i*45)
            ics_content = self._make_ics(organizer_name, sender_email, "Candidate", email_addr, role, slot_time)
            subject = f"Interview Invitation: {role}"
            body = f"Hi,\n\nWe are impressed by your profile. Please find the interview invite attached for {slot_time}."
            try:
                self._send_email_with_ics(email_addr, subject, body, ics_content)
                results.append(f"Sent to {email_addr}")
            except Exception as e:
                results.append(f"Failed {email_addr}: {e}")
        return results

    def send_outcomes(self, hired_emails):
        state = self.load_state()
        role = state.get('role', 'Role')
        all_candidates = state.get('candidates', [])
        results = []
        
        sender_email = "recruiter@example.com"
        try:
            profile = self.gmail.users().getProfile(userId='me').execute()
            sender_email = profile.get('emailAddress', sender_email)
        except: pass

        for cand in all_candidates:
            email_addr = cand.get('email')
            if not email_addr: continue
            
            if email_addr in hired_emails:
                subject = f"Offer: {role}"
                body = f"Hi,\n\nCongratulations! We are thrilled to offer you the {role} position.\n\nWelcome aboard!"
                status = "OFFER_SENT"
            else:
                subject = f"Update on your application for {role}"
                body = f"Hi,\n\nThank you for your application. We have decided to move forward with other candidates."
                status = "REJECTED"

            try:
                self._send_plain_email(email_addr, subject, body)
                results.append(f"{status}: {email_addr}")
            except Exception as e:
                results.append(f"FAILED: {email_addr} - {e}")
            
            self._log_outcome_to_sheet(state.get('sheet_id'), email_addr, status)
        return results

    # --- HELPERS ---
    def _send_plain_email(self, to_email, subject, body):
        msg = MIMEMultipart()
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain", "utf-8"))
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
        self.gmail.users().messages().send(userId="me", body={"raw": raw}).execute()

    def _log_outcome_to_sheet(self, sheet_id, email, status):
        try:
            try: self.sheets.spreadsheets().batchUpdate(spreadsheetId=sheet_id, body={"requests": [{"addSheet": {"properties": {"title": "Outcomes"}}}]}).execute()
            except: pass
            row = [[datetime.now().strftime("%Y-%m-%d %H:%M:%S"), email, status]]
            self.sheets.spreadsheets().values().append(spreadsheetId=sheet_id, range="Outcomes!A1", valueInputOption="RAW", body={"values": row}).execute()
        except: pass

    def _q_text(self, title, idx, paragraph=False, required=True, desc=None):
        item = {"title": title, "questionItem": {"question": {"required": required, "textQuestion": {"paragraph": paragraph}}}}
        if desc: item["description"] = desc
        return {"createItem": {"item": item, "location": {"index": idx}}}

    def _q_radio(self, title, options, idx):
        opts = [{"value": o} for o in options]
        item = {"title": title, "questionItem": {"question": {"required": True, "choiceQuestion": {"type": "RADIO", "options": opts}}}}
        return {"createItem": {"item": item, "location": {"index": idx}}}

    def _get_qid(self, meta, title):
        for item in meta.get("items", []):
            if item.get("title") == title: return item["questionItem"]["question"]["questionId"]
        return None

    def _get_answer(self, resp, qid):
        if not qid: return None
        a = resp.get('answers', {}).get(qid, {}).get('textAnswers', {}).get('answers', [])
        return a[0]['value'] if a else None

    def _extract_file_id(self, url):
        m = re.search(r"/file/d/([a-zA-Z0-9_-]+)", url)
        if m: return m.group(1)
        try:
            from urllib.parse import urlparse, parse_qs
            qs = parse_qs(urlparse(url).query)
            if "id" in qs: return qs["id"][0]
        except: pass
        return None 

    def _download_file(self, file_id, path):
        try:
            req = self.drive.files().get_media(fileId=file_id)
            with io.FileIO(path, "wb") as fh:
                downloader = MediaIoBaseDownload(fh, req)
                done = False
                while not done: status, done = downloader.next_chunk()
        except: pass

    def _extract_text(self, path):
        try: return "\n".join([p.extract_text() for p in PdfReader(path).pages])
        except: return ""

    def _score_text(self, text):
        keywords = ["python", "django", "api", "sql", "rest", "docker", "java", "node", "aws"]
        return sum(1 for k in keywords if k in text.lower())

    def _make_ics(self, org_name, sender_email, cand_name, cand_email, role, start_dt):
        uid = f"{uuid.uuid4().hex}@hiring-agent"
        end_dt = start_dt + timedelta(minutes=45)
        fmt = lambda d: d.astimezone(tz.UTC).strftime("%Y%m%dT%H%M%SZ")
        return f"""BEGIN:VCALENDAR
PRODID:-//HiringAgent//EN
VERSION:2.0
METHOD:REQUEST
BEGIN:VEVENT
UID:{uid}
DTSTAMP:{fmt(datetime.now())}
DTSTART:{fmt(start_dt)}
DTEND:{fmt(end_dt)}
SUMMARY:Interview: {role}
ORGANIZER;CN={org_name}:mailto:{sender_email}
ATTENDEE;ROLE=REQ-PARTICIPANT;RSVP=TRUE:mailto:{cand_email}
DESCRIPTION:Interview for {role}
END:VEVENT
END:VCALENDAR"""

    def _send_email_with_ics(self, to_email, subject, body, ics_text):
        msg = MIMEMultipart("mixed") 
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain", "utf-8"))
        ics_part = MIMEText(ics_text, "calendar", "utf-8")
        ics_part.add_header("Content-Class", "urn:content-classes:calendarmessage")
        ics_part.add_header("Content-Type", "text/calendar; method=REQUEST")
        msg.attach(ics_part)
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
        self.gmail.users().messages().send(userId="me", body={"raw": raw}).execute()