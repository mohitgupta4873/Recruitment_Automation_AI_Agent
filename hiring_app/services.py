import base64
import io
import json
import re
import uuid
from datetime import datetime, timedelta
from dateutil import tz
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from django.core.files.base import ContentFile
from django.core.mail import EmailMessage, send_mail
from django.utils import timezone

# Google Libraries
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from pypdf import PdfReader
import google.generativeai as genai
from django.conf import settings

import logging
logger = logging.getLogger('hiring_app')

# As of Phase 2, Forms and Drive are gone entirely — applicants upload a PDF
# directly (see forms.py:ApplicationForm) instead of pasting a Drive link into
# a Google Form question. Sheets stays (optional export) and gmail.send stays
# (sending as the recruiter). Both are "sensitive" scopes; neither is
# "restricted" the way the old drive scope was, which is what let Phase 2
# happen without a paid CASA security assessment for OAuth verification.
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/gmail.send",
]

# Applicant-uploaded resumes are untrusted input. ApplicationForm.clean_resume
# rejects anything over this before it reaches the ORM; kept here too since
# _extract_text loads the whole file into memory regardless of who called it.
MAX_RESUME_BYTES = 5 * 1024 * 1024   # 5 MB

# Used to score a resume when a campaign has no AI-derived scoring_keywords —
# either generate_scoring_keywords failed (Gemini down, bad response) or the
# campaign predates it (imported by import_legacy_campaigns). Not tied to any
# particular role; better than scoring 0 across the board.
FALLBACK_KEYWORDS = ["python", "django", "api", "sql", "rest", "docker", "java", "node", "aws"]


def get_user_google_creds(user):
    """
    Load & auto-refresh Google OAuth credentials for a user from DB.
    Returns a Credentials object, or None if the user hasn't connected Google
    (or refresh failed) — HiringAutomator then runs in its no-Google mode.
    There is no fallback to a shared token.

    Moved here from views.py in Phase 3 so hiring_app/tasks.py can use it too,
    without importing views.py (which imports tasks.py to enqueue — that way
    lies a circular import).
    """
    from .models import GoogleOAuthToken  # local import: models.py doesn't import services.py, but keep this lazy to avoid any app-loading-order surprises

    try:
        token_record = GoogleOAuthToken.objects.get(user=user)
        creds = Credentials.from_authorized_user_info(
            json.loads(token_record.token_json), SCOPES
        )
        # Auto-refresh expired token
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(GoogleRequest())
                token_record.token_json = creds.to_json()
                token_record.save()
                logger.info(f"Refreshed Google token for user id={user.id}")
            except Exception as e:
                logger.error(f"Failed to refresh Google token for user id={user.id}: {e}")
                return None
        return creds
    except GoogleOAuthToken.DoesNotExist:
        return None
    except Exception as e:
        logger.error(f"Error loading Google creds for user id={user.id}: {e}")
        return None


class ResumeTooLarge(Exception):
    """Raised when a candidate's resume exceeds MAX_RESUME_BYTES."""


class JDGenerationFailed(Exception):
    """Raised when the Gemini call for JD generation fails."""


class HiringAutomator:
    """
    Wraps the (now optional) Google API calls — Sheets export, Gmail send —
    plus Gemini JD generation and resume scoring. As of Phase 1, persistence
    goes through the Campaign/Candidate models via the ORM. As of Phase 2,
    Google is optional throughout: every method that used to require it now
    has a non-Google fallback (Django's configured EMAIL_BACKEND for sending,
    silently skipping for the Sheets export). See CLAUDE.md for the fuller
    history — Forms and Drive integration were removed entirely this phase.

    Constructed per-request with the *current user's* Google credentials, or
    None. It's not a singleton and holds no cross-request state of its own.
    """

    def __init__(self, creds=None):
        self.creds = creds
        self.sheets = self.gmail = None

        if self.creds:
            try:
                self.sheets = build("sheets", "v4", credentials=self.creds, cache_discovery=False)
                self.gmail  = build("gmail",  "v1", credentials=self.creds, cache_discovery=False)
            except Exception as e:
                logger.error(f"Failed to build Google API clients: {e}")
                self.creds = None

    @property
    def has_google(self):
        return self.creds is not None and self.gmail is not None

    # --- JD GENERATION ---
    def generate_jd(self, role_title, experience):
        prompt = f"""Draft an inclusive, crisp Job Description for: {role_title}.
Required Experience: {experience}.
Include: About the role, Responsibilities, Must-haves, Nice-to-haves, What we offer, How to apply.
Aim ~350–450 words. Bullets welcome."""

        if not getattr(settings, 'GEMINI_API_KEY', ''):
            raise JDGenerationFailed("Gemini is not configured on this server.")
        try:
            model = genai.GenerativeModel("gemini-2.5-flash-lite")
            resp = model.generate_content(prompt)
            return resp.text
        except Exception as e:
            # Surface the failure so the view can tell the user, instead of
            # returning a placeholder that reads like a successful result.
            logger.error(f"Gemini JD generation failed for role={role_title!r}: {e}")
            raise JDGenerationFailed(str(e)) from e

    def generate_scoring_keywords(self, role_title, jd_text):
        """Ask Gemini for the short list of skills/keywords resumes should be
        scored against for this role. Never raises — keyword generation
        failing must not block launching a campaign — falls back to
        FALLBACK_KEYWORDS on any error or unparseable response.
        """
        if not getattr(settings, 'GEMINI_API_KEY', ''):
            return list(FALLBACK_KEYWORDS)
        prompt = f"""Based on this job description for "{role_title}", list 8-15 \
specific skills or keywords a strong resume should mention (tools, languages, \
frameworks, methodologies — not soft skills like "communication").

Job description:
{jd_text[:3000]}

Respond with ONLY a JSON array of lowercase strings, nothing else. Example:
["python", "django", "postgresql", "rest api", "docker"]"""
        try:
            model = genai.GenerativeModel("gemini-2.5-flash-lite")
            resp = model.generate_content(prompt)
            keywords = _parse_keyword_response(resp.text)
            if keywords:
                return keywords
            logger.warning(f"Gemini returned no usable keywords for role={role_title!r}; using fallback")
        except Exception as e:
            logger.warning(f"Scoring keyword generation failed for role={role_title!r}: {e}")
        return list(FALLBACK_KEYWORDS)

    # --- CAMPAIGN CREATION ---
    def create_campaign(self, campaign, jd_text):
        """Finalise `campaign`: store the JD, derive scoring keywords, go live.

        `campaign` is an already-saved Campaign row (owner/role already set,
        public_token already generated by the model default). Mutates and
        saves it in place. Google is entirely optional here — if connected, a
        tracking Sheet is created best-effort; if not, the campaign still
        launches and is fully usable through the apply page alone.
        """
        campaign.jd_text = jd_text
        campaign.scoring_keywords = self.generate_scoring_keywords(campaign.role, jd_text)
        campaign.status = 'active'

        if self.has_google:
            try:
                ss = self.sheets.spreadsheets().create(
                    body={"properties": {"title": f"Applications — {campaign.role}"}}
                ).execute()
                campaign.sheet_id = ss["spreadsheetId"]
                campaign.sheet_url = ss["spreadsheetUrl"]
                self._ensure_sheet_tab(campaign.sheet_id, "Applications",
                                        ["Applied At", "Full Name", "Email", "Experience", "AI Score", "Status"])
            except HttpError as e:
                # Sheet export is a nice-to-have, not a launch blocker.
                logger.warning(f"Could not create tracking sheet for campaign={campaign.pk}: {e}")

        campaign.save()
        return campaign

    # --- APPLICATIONS (replaces Phase 1's sync_responses — see CLAUDE.md) ---
    def process_application(self, campaign, cleaned_data):
        """Score `cleaned_data['resume']` (an UploadedFile) against
        `campaign.scoring_keywords` and create/update the Candidate row.

        update_or_create rather than create: a second submission from the same
        email updates the existing application instead of colliding with the
        (campaign, email) unique constraint — a candidate correcting a typo'd
        resume, say. Matches the precedent set by Phase 1's sync_responses.
        """
        uploaded = cleaned_data['resume']
        file_content = uploaded.read()

        text = self._extract_text(file_content)
        keywords = campaign.scoring_keywords or FALLBACK_KEYWORDS
        score, matched = self._score_resume(text, keywords)
        resume_status = 'parsed' if text else 'parse_failed'

        candidate, _created = campaign.candidates.update_or_create(
            email=cleaned_data['email'],
            defaults={
                'source': 'apply_page',
                'full_name': cleaned_data.get('full_name', ''),
                'years_experience': cleaned_data.get('years_experience', ''),
                'why_fit': cleaned_data.get('why_fit', ''),
                'linkedin_url': cleaned_data.get('linkedin_url', '') or '',
                'consent_at': timezone.now(),
                'score': score,
                'matched_terms': matched,
                'text_preview': (text[:200] or "No extractable text") if text else "Resume could not be read",
                'resume_status': resume_status,
            },
        )
        candidate.resume.save(f"{uuid.uuid4().hex}.pdf", ContentFile(file_content), save=True)

        if self.has_google and campaign.sheet_id:
            self._append_candidate_row(campaign.sheet_id, candidate)

        return candidate

    # --- INTERVIEW INVITES ---
    def send_invites(self, campaign, candidates, organizer_name, interview_date):
        """candidates: an iterable of Candidate rows belonging to `campaign`.
        Sends via Gmail if the recruiter has connected Google, otherwise via
        Django's configured EMAIL_BACKEND (see DEFAULT_FROM_EMAIL) — Google is
        optional for every step of this app as of Phase 2.
        """
        role = campaign.role
        results = []
        dt_start = self.parse_interview_datetime(interview_date)
        sender_email = self._sender_email()

        for i, candidate in enumerate(candidates):
            slot_time = dt_start + timedelta(minutes=i * 45)
            local_slot = timezone.localtime(slot_time)
            greeting = f"Hi {candidate.full_name}," if candidate.full_name else "Hi,"
            ics_content = self._make_ics(
                organizer_name, sender_email, candidate.full_name or "Candidate",
                candidate.email, role, slot_time,
            )
            subject = f"Interview Invitation: {role}"
            body = (
                f"{greeting}\n\nWe are impressed by your profile. Please find the interview "
                f"invite attached for {local_slot.strftime('%A %d %B %Y at %H:%M %Z')}."
            )
            try:
                self._send_email_with_ics(candidate.email, subject, body, ics_content, sender_email)
                candidate.invite_sent_at = timezone.now()
                candidate.save(update_fields=['invite_sent_at', 'updated_at'])
                results.append(f"Sent to {candidate.email}")
            except Exception as e:
                results.append(f"Failed {candidate.email}: {e}")
        return results

    # --- OUTCOMES ---
    def send_outcomes(self, campaign, candidates, hired_candidate_ids):
        """Send an offer to every candidate in `hired_candidate_ids` (a set of
        Candidate pks) and a rejection to everyone else in `candidates`.

        `candidates` — not `campaign.candidates.all()` — is the caller's job to
        supply (Phase 3: hiring_app.tasks.send_outcomes_task passes only
        candidates with outcome_sent_at unset, so a retried task doesn't
        re-email anyone the previous attempt already reached).
        """
        role = campaign.role
        results = []
        sender_email = self._sender_email()

        for candidate in candidates:
            greeting = f"Hi {candidate.full_name}," if candidate.full_name else "Hi,"
            if candidate.pk in hired_candidate_ids:
                subject = f"Offer: {role}"
                body = f"{greeting}\n\nCongratulations! We are thrilled to offer you the {role} position.\n\nWelcome aboard!"
                outcome_type = 'offer'
                log_status = 'OFFER_SENT'
            else:
                subject = f"Update on your application for {role}"
                body = f"{greeting}\n\nThank you for your application. We have decided to move forward with other candidates."
                outcome_type = 'rejected'
                log_status = 'REJECTED'

            try:
                self._send_plain_email(candidate.email, subject, body, sender_email)
                candidate.outcome_type = outcome_type
                candidate.outcome_sent_at = timezone.now()
                candidate.save(update_fields=['outcome_type', 'outcome_sent_at', 'updated_at'])
                results.append(f"{log_status}: {candidate.email}")
            except Exception as e:
                results.append(f"FAILED: {candidate.email} - {e}")

            if self.has_google and campaign.sheet_id:
                self._log_outcome_to_sheet(campaign.sheet_id, candidate.email, log_status)
        return results

    # --- HELPERS ---
    def parse_interview_datetime(self, value):
        """Parse the <input type="datetime-local"> value into an aware datetime.

        strptime produces a naive datetime, and .astimezone() on a naive value
        assumes the *server's* timezone. On a UTC container with TIME_ZONE set to
        Asia/Kolkata that silently shifted every invite by 5.5 hours.
        """
        if not value:
            raise ValueError("An interview date and time is required.")
        for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"):
            try:
                naive = datetime.strptime(value, fmt)
            except ValueError:
                continue
            return timezone.make_aware(naive, timezone.get_current_timezone())
        raise ValueError(f"Unrecognised interview date/time: {value!r}")

    def _sender_email(self):
        """The address candidate-facing email goes out from: the connected
        Google account's own address if there is one, else the app's own
        configured sender."""
        if self.has_google:
            try:
                profile = self.gmail.users().getProfile(userId='me').execute()
                addr = profile.get('emailAddress')
                if addr:
                    return addr
            except HttpError as e:
                logger.warning(f"Could not read Gmail profile, falling back to DEFAULT_FROM_EMAIL: {e}")
        return settings.DEFAULT_FROM_EMAIL

    def _send_plain_email(self, to_email, subject, body, sender_email):
        if self.has_google:
            msg = MIMEMultipart()
            msg["To"] = to_email
            msg["Subject"] = subject
            msg.attach(MIMEText(body, "plain", "utf-8"))
            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
            self.gmail.users().messages().send(userId="me", body={"raw": raw}).execute()
        else:
            send_mail(subject, body, sender_email, [to_email], fail_silently=False)

    def _send_email_with_ics(self, to_email, subject, body, ics_text, sender_email):
        if self.has_google:
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
        else:
            email = EmailMessage(subject, body, sender_email, [to_email])
            email.attach('invite.ics', ics_text, 'text/calendar; method=REQUEST')
            email.send(fail_silently=False)

    def _ensure_sheet_tab(self, sheet_id, tab_title, header_row):
        try:
            self.sheets.spreadsheets().batchUpdate(
                spreadsheetId=sheet_id,
                body={"requests": [{"addSheet": {"properties": {"title": tab_title}}}]},
            ).execute()
            self.sheets.spreadsheets().values().append(
                spreadsheetId=sheet_id, range=f"{tab_title}!A1",
                valueInputOption="RAW", body={"values": [header_row]},
            ).execute()
        except HttpError as e:
            if e.resp.status != 400:   # 400 == tab already exists
                logger.warning(f"Could not initialise {tab_title!r} tab on {sheet_id}: {e}")

    def _append_candidate_row(self, sheet_id, candidate):
        row = [[
            timezone.localtime(candidate.created_at).strftime("%Y-%m-%d %H:%M:%S"),
            candidate.full_name, candidate.email, candidate.years_experience,
            candidate.score, candidate.resume_status,
        ]]
        try:
            self.sheets.spreadsheets().values().append(
                spreadsheetId=sheet_id, range="Applications!A1",
                valueInputOption="RAW", body={"values": row},
            ).execute()
        except HttpError as e:
            # Best-effort: the application is already saved in the DB regardless.
            logger.warning(f"Could not append candidate row to sheet {sheet_id}: {e}")

    def _log_outcome_to_sheet(self, sheet_id, email, status):
        self._ensure_sheet_tab(sheet_id, "Outcomes", ["Time", "Email", "Status"])
        try:
            row = [[timezone.now().strftime("%Y-%m-%d %H:%M:%S"), email, status]]
            self.sheets.spreadsheets().values().append(
                spreadsheetId=sheet_id, range="Outcomes!A1",
                valueInputOption="RAW", body={"values": row},
            ).execute()
        except HttpError as e:
            # Logging the outcome is best-effort; the email has already been sent
            # and must not be re-sent just because the Sheet write failed.
            logger.error(f"Failed to log outcome to sheet {sheet_id}: {e}")

    def _extract_text(self, file_content):
        try:
            reader = PdfReader(io.BytesIO(file_content))
            return "\n".join((p.extract_text() or "") for p in reader.pages)
        except Exception as e:
            # pypdf raises a wide range of types on malformed input, and this
            # parses untrusted applicant-supplied PDFs.
            logger.warning(f"Could not extract text from resume: {e}")
            return ""

    def _score_resume(self, text, keywords):
        """Word-boundary match against `keywords`, normalised to 0-100.

        The old substring check (`"java" in text`) matched "javascript" and
        `"api" in text` matched "therapist" — both real false positives.
        `\\b` boundaries fix that; re.escape handles multi-word keywords like
        "machine learning" safely.
        """
        if not keywords:
            return 0, []
        lowered = text.lower()
        matched = [
            k for k in keywords
            if re.search(rf"\b{re.escape(k.lower())}\b", lowered)
        ]
        score = round(100 * len(matched) / len(keywords))
        return score, matched

    def _make_ics(self, org_name, sender_email, cand_name, cand_email, role, start_dt):
        uid = f"{uuid.uuid4().hex}@hiring-agent"
        end_dt = start_dt + timedelta(minutes=45)

        def fmt(d):
            if timezone.is_naive(d):
                d = timezone.make_aware(d, timezone.get_current_timezone())
            return d.astimezone(tz.UTC).strftime("%Y%m%dT%H%M%SZ")

        return f"""BEGIN:VCALENDAR
PRODID:-//HiringAgent//EN
VERSION:2.0
METHOD:REQUEST
BEGIN:VEVENT
UID:{uid}
DTSTAMP:{fmt(timezone.now())}
DTSTART:{fmt(start_dt)}
DTEND:{fmt(end_dt)}
SUMMARY:Interview: {role}
ORGANIZER;CN={org_name}:mailto:{sender_email}
ATTENDEE;ROLE=REQ-PARTICIPANT;RSVP=TRUE;CN={cand_name}:mailto:{cand_email}
DESCRIPTION:Interview for {role}
END:VEVENT
END:VCALENDAR"""


def _parse_keyword_response(raw_text):
    """Best-effort parse of Gemini's keyword-list response into a clean list
    of lowercase strings. Gemini sometimes wraps JSON in a ```json fence
    despite being asked not to — strip that before parsing."""
    text = raw_text.strip()
    if text.startswith('```'):
        text = re.sub(r'^```[a-zA-Z]*\n?', '', text)
        text = re.sub(r'```$', '', text).strip()
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    keywords = [str(k).strip().lower() for k in data if str(k).strip()]
    return keywords[:20]  # sanity cap — a runaway response shouldn't balloon scoring cost
