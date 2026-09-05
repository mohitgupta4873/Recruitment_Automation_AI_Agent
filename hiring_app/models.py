import secrets
import uuid

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import models
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.contrib.auth.models import User


def _fernet():
    return Fernet(settings.FIELD_ENCRYPTION_KEY)


class EncryptedTextField(models.TextField):
    """A TextField that is Fernet-encrypted at rest.

    Transparent to Python code — reads/writes plain strings — but the database
    column only ever holds ciphertext. There is no separate migration needed
    for the column itself (it's still a plain TEXT column); only the
    application-level encode/decode changes.

    NOTE: because Fernet ciphertext is non-deterministic (a fresh IV per
    encrypt call), this field cannot be used in `.filter()`/`.get()` lookups
    by value. Nothing in this codebase does that — token_json is always
    fetched by `user` and never searched — but don't add such a lookup later
    without switching to a different scheme.
    """

    def get_prep_value(self, value):
        if value is None or value == '':
            return value
        return _fernet().encrypt(value.encode('utf-8')).decode('ascii')

    def from_db_value(self, value, expression, connection):
        if value is None or value == '':
            return value
        try:
            return _fernet().decrypt(value.encode('ascii')).decode('utf-8')
        except InvalidToken as e:
            raise ValueError(
                'Could not decrypt an EncryptedTextField value. Either '
                'FIELD_ENCRYPTION_KEY has changed since this row was written, '
                'or the row predates encryption and needs the '
                '`encrypt_legacy_tokens` data migration re-run.'
            ) from e


class GoogleOAuthToken(models.Model):
    """
    Stores per-user Google OAuth2 credentials.
    Each user who connects their Google account gets one row here.
    The token_json field holds the full credentials JSON (access token,
    refresh token, token_uri, client_id, client_secret, scopes) — encrypted
    at rest, since a leaked DATABASE_URL or backup would otherwise hand out
    durable Google access (full Drive + send-as-Gmail) for every connected user.
    """
    user       = models.OneToOneField(User, on_delete=models.CASCADE, related_name='google_token')
    token_json = EncryptedTextField(help_text="Google OAuth2 credentials as JSON string, encrypted at rest")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"GoogleOAuthToken({self.user.username})"


def _generate_public_token():
    # 22 url-safe chars (~131 bits) — unguessable enough that "does this token
    # resolve to a campaign" is itself a meaningful authorization check; the
    # apply page has no other access control.
    return secrets.token_urlsafe(16)


class Campaign(models.Model):
    """
    One hiring campaign for one role. Replaces the old campaigns/user_{id}/*.json
    file-based storage — see the module docstring that used to live in
    campaign_manager.py (deleted) for the shape this superseded.

    A UUID primary key (rather than the old 12-char hex string) doubles as the
    URL segment identifying a campaign — see urls.py — and there is no more
    "active campaign" concept stored in the session; the URL is the source of
    truth for which campaign a request is about.
    """
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('completed', 'Completed'),
    ]

    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner      = models.ForeignKey(User, on_delete=models.CASCADE, related_name='campaigns')
    role       = models.CharField(max_length=200, default='New Campaign')
    experience = models.CharField(max_length=100, blank=True)
    jd_text    = models.TextField(blank=True)
    status     = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')

    # As of Phase 2, this — not a Google Form — is how candidates apply.
    # Unique+indexed since it's looked up directly from the public apply view.
    public_token = models.CharField(max_length=32, unique=True, default=_generate_public_token, editable=False)

    # Populated by HiringAutomator.generate_scoring_keywords at launch time, from
    # the *final* (possibly recruiter-edited) jd_text. Falls back to a fixed
    # generic list (see services.FALLBACK_KEYWORDS) if Gemini is unavailable or
    # this is blank, e.g. for campaigns launched before this field existed.
    scoring_keywords = models.JSONField(default=list, blank=True)

    # Google Sheets export — optional. A campaign is fully usable without Google
    # connected; this is populated only best-effort if it is. form_id/form_url/
    # drive_qid/email_qid are Phase-1-era Google Forms fields, kept for the
    # historical campaigns imported by import_legacy_campaigns; new campaigns
    # never populate them, since there's no Form any more.
    form_id          = models.CharField(max_length=255, blank=True)
    form_url         = models.URLField(blank=True)
    sheet_id         = models.CharField(max_length=255, blank=True)
    sheet_url        = models.URLField(blank=True)
    drive_qid        = models.CharField(max_length=255, blank=True)   # legacy Forms question ID
    email_qid        = models.CharField(max_length=255, blank=True)   # legacy Forms question ID
    linkedin_post_id = models.CharField(max_length=255, blank=True)   # legacy — see services.py history

    # Phase 4 (retention). closed_at is stamped once, the first time status
    # becomes 'completed' (see tasks.send_outcomes_task) — not on every save,
    # so it records when the campaign actually stopped accepting outcomes,
    # not when it was last touched. retention_days is how long candidate
    # resumes/text_preview survive after that before purge_expired_resumes
    # (hiring_app/tasks.py) clears them; configurable per campaign since a
    # recruiter may be bound to a longer/shorter policy than the default.
    retention_days = models.PositiveIntegerField(default=180)
    closed_at      = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.role} ({self.status})"

    @property
    def candidates_count(self):
        return self.candidates.count()

    @property
    def accepting_applications(self):
        return self.status == 'active'


def candidate_resume_path(instance, filename):
    # Namespaced per campaign, unlike the old global media/cv_pdfs/<file_id>.pdf
    # — that flat layout mixed every tenant's resumes in one directory.
    return f'resumes/{instance.campaign_id}/{instance.file_id or uuid.uuid4().hex}.pdf'


class Candidate(models.Model):
    """
    One applicant to one Campaign. Replaces the "candidates": [...] list that
    used to live inside each campaign's JSON state file.

    `form_response_id` is a Google Forms response ID on the historical
    candidates imported by import_legacy_campaigns; new candidates (from the
    Phase 2 apply page — SOURCE_APPLY_PAGE below) leave it blank and are
    identified by `(campaign, email)` instead, which is unique regardless of
    source.
    """
    SOURCE_GOOGLE_FORM = 'google_form'
    SOURCE_APPLY_PAGE = 'apply_page'
    SOURCE_CHOICES = [
        (SOURCE_GOOGLE_FORM, 'Google Form (legacy)'),
        (SOURCE_APPLY_PAGE, 'Apply Page'),
    ]

    # Renamed from download_status (Phase 1) now that resumes arrive by direct
    # upload, not a Drive download — 'no_link'/'unrecognised_link'/'downloaded'/
    # 'download_failed' are the values legacy Google-Form-sourced rows carry;
    # 'parsed'/'parse_failed' are what the apply page produces.
    RESUME_STATUS_CHOICES = [
        ('no_link', 'No Link (legacy)'),
        ('unrecognised_link', 'Unrecognised Link (legacy)'),
        ('downloaded', 'Downloaded (legacy)'),
        ('download_failed', 'Download Failed (legacy)'),
        ('parsed', 'Parsed'),
        ('parse_failed', 'Parse Failed'),
    ]
    OUTCOME_CHOICES = [
        ('', 'Pending'),
        ('offer', 'Offer Sent'),
        ('rejected', 'Rejected'),
    ]
    EXPERIENCE_CHOICES = [
        ('0', '0 years'),
        ('1', '1 year'),
        ('2', '2 years'),
        ('3+', '3+ years'),
    ]

    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name='candidates')
    source   = models.CharField(max_length=20, choices=SOURCE_CHOICES, default=SOURCE_APPLY_PAGE)

    full_name        = models.CharField(max_length=200, blank=True)
    email             = models.EmailField()
    years_experience  = models.CharField(max_length=10, choices=EXPERIENCE_CHOICES, blank=True)
    why_fit           = models.TextField(blank=True)
    linkedin_url      = models.URLField(blank=True)
    consent_at        = models.DateTimeField(null=True, blank=True)  # applicant accepted the privacy notice

    form_response_id = models.CharField(max_length=255, blank=True, db_index=True)  # legacy Google Form rows only
    drive_link        = models.URLField(blank=True)   # legacy Google Form rows only
    file_id           = models.CharField(max_length=255, blank=True)  # legacy Google Form rows only

    # Uses STORAGES['default'] (settings.py) — local disk today. Swapping to S3/R2
    # later is a storage-backend config change, not an application code change.
    resume           = models.FileField(upload_to=candidate_resume_path, blank=True)

    score            = models.IntegerField(default=0)   # normalised 0-100 for apply-page candidates;
                                                          # legacy rows keep their old 0-9 raw hit-count
    matched_terms    = models.JSONField(default=list, blank=True)
    text_preview     = models.TextField(blank=True)   # short excerpt shown in the UI
    resume_status    = models.CharField(max_length=20, choices=RESUME_STATUS_CHOICES, default='parsed')
    download_attempts = models.PositiveSmallIntegerField(default=0)  # legacy retry counter

    invite_sent_at  = models.DateTimeField(null=True, blank=True)
    outcome_type    = models.CharField(max_length=10, choices=OUTCOME_CHOICES, blank=True, default='')
    outcome_sent_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['campaign', 'email'],
                name='unique_candidate_email_per_campaign',
            ),
        ]

    def __str__(self):
        return f"{self.email} → {self.campaign.role}"


@receiver(post_delete, sender=Candidate)
def _delete_resume_file_on_candidate_delete(sender, instance, **kwargs):
    """Deleting a Candidate row didn't used to delete its resume file from
    disk (Django's FileField never does this on its own) — the file was
    orphaned under media/resumes/<campaign-id>/ forever. This fires whenever
    a Candidate is deleted: directly (admin erasure request), cascaded from
    a Campaign delete, or cascaded from a User delete (account deletion) —
    registering this receiver also stops Django's cascade-delete Collector
    from "fast-deleting" Candidate rows in bulk, since a fast-delete skips
    signals entirely; every Candidate is now deleted (and its file cleaned
    up) one row at a time regardless of which path triggered it.
    """
    if instance.resume:
        instance.resume.delete(save=False)
