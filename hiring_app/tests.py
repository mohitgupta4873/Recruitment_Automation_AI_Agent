"""
Phase 0 (security hardening) + Phase 1 (Postgres-backed campaigns) +
Phase 2 (public apply page) verification.
"""
import shutil
import tempfile

from django.test import TestCase, override_settings
from django.contrib.auth.models import User

from hiring_app.models import Campaign, Candidate


def _build_valid_pdf_with_text(text):
    """A minimal but structurally real single-page PDF containing `text` as
    actual extractable content — real xref table with correct byte offsets,
    unlike ApplyPageTests.MIN_PDF. Built by hand (no reportlab dependency)
    so the resume-parsing test doesn't rely on files outside the repo.
    """
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 4 0 R >> >> "
        b"/MediaBox [0 0 300 300] /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    stream = f"BT /F1 12 Tf 10 250 Td ({text}) Tj ET".encode()
    objects.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]  # object 0 is the free-list head, never written
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"

    xref_offset = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        out += f"{off:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF"
    ).encode()
    return bytes(out)


class SecurityHardeningTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='alice', email='alice@example.com', password='Str0ng!Passphrase42'
        )
        self.campaign = Campaign.objects.create(owner=self.user, role='Backend Engineer')

    # ── method guards ────────────────────────────────────────
    def test_new_campaign_rejects_get(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get('/campaign/new/').status_code, 405)

    def test_google_disconnect_rejects_get(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get('/google/disconnect/').status_code, 405)

    def test_mutating_views_require_login(self):
        for url in ['/agent/', '/dashboard/', f'/campaign/{self.campaign.pk}/create/']:
            resp = self.client.get(url)
            self.assertIn(resp.status_code, (302, 405), url)
            if resp.status_code == 302:
                self.assertIn('/login/', resp['Location'], url)

    # ── password policy ──────────────────────────────────────
    def test_weak_password_rejected(self):
        """AUTH_PASSWORD_VALIDATORS were being skipped by hand-rolled checks."""
        resp = self.client.post('/register/', {
            'username': 'bob', 'email': 'bob@example.com',
            'password1': 'password123', 'password2': 'password123',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(User.objects.filter(username='bob').exists())

    def test_numeric_password_rejected(self):
        resp = self.client.post('/register/', {
            'username': 'carol', 'email': 'carol@example.com',
            'password1': '99887766', 'password2': '99887766',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(User.objects.filter(username='carol').exists())

    def test_strong_password_accepted(self):
        resp = self.client.post('/register/', {
            'username': 'dave', 'email': 'dave@example.com',
            'password1': 'Str0ng!Passphrase42', 'password2': 'Str0ng!Passphrase42',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(User.objects.filter(username='dave').exists())

    def test_duplicate_email_rejected(self):
        resp = self.client.post('/register/', {
            'username': 'eve', 'email': 'ALICE@example.com',
            'password1': 'Str0ng!Passphrase42', 'password2': 'Str0ng!Passphrase42',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(User.objects.filter(username='eve').exists())

    # ── password reset ───────────────────────────────────────
    def test_password_reset_flow_sends_email(self):
        from django.core import mail
        resp = self.client.post('/password-reset/', {'email': 'alice@example.com'})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('/password-reset/', mail.outbox[0].body)

    # ── health check ─────────────────────────────────────────
    def test_healthz(self):
        resp = self.client.get('/healthz/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['status'], 'ok')


class NoSharedTokenFallbackTests(TestCase):
    """A user without their own Google creds must not borrow the server's.

    As of Phase 2, Google is optional throughout — HiringAutomator no longer
    raises when disconnected, it falls back to Django's email backend. There is
    still deliberately no fallback to a *shared* token: has_google reflects
    only the creds this instance was built with.
    """

    def test_automator_without_creds_has_no_google(self):
        from hiring_app.services import HiringAutomator
        a = HiringAutomator(creds=None)
        self.assertFalse(a.has_google)
        # Sheet creation is best-effort and silently skipped, not blocking:
        self.assertIsNone(a.sheets)
        self.assertIsNone(a.gmail)

    def test_constructor_rejects_state_path_kwarg(self):
        """state_path/token_path were the pre-Phase-1 JSON-file plumbing."""
        from hiring_app.services import HiringAutomator
        with self.assertRaises(TypeError):
            HiringAutomator(token_path='token.json', state_path='x.json')

    def test_interview_datetime_is_timezone_aware(self):
        from django.utils import timezone
        from hiring_app.services import HiringAutomator
        a = HiringAutomator(creds=None)
        dt = a._parse_interview_datetime('2026-09-01T14:30')
        self.assertFalse(timezone.is_naive(dt))
        self.assertEqual(dt.hour, 14)
        with self.assertRaises(ValueError):
            a._parse_interview_datetime('not-a-date')

    def test_scopes_no_longer_include_forms_or_drive(self):
        """The restricted `drive` scope (and the now-unused Forms scopes) are
        what made public launch require a paid CASA assessment — the whole
        point of Phase 2 was removing them."""
        from hiring_app.services import SCOPES
        joined = ' '.join(SCOPES)
        self.assertNotIn('drive', joined)
        self.assertNotIn('forms', joined)
        self.assertIn('spreadsheets', joined)
        self.assertIn('gmail.send', joined)


class TokenEncryptionTests(TestCase):
    """GoogleOAuthToken.token_json must be ciphertext at rest, not plaintext."""

    def test_token_json_is_encrypted_in_the_database(self):
        from django.db import connection
        from hiring_app.models import GoogleOAuthToken
        import json

        user = User.objects.create_user(username='frank', password='Str0ng!Passphrase42')
        payload = json.dumps({'refresh_token': 'super-secret-value'})
        GoogleOAuthToken.objects.create(user=user, token_json=payload)

        with connection.cursor() as cur:
            cur.execute(
                "SELECT token_json FROM hiring_app_googleoauthtoken WHERE user_id = %s",
                [user.id],
            )
            raw = cur.fetchone()[0]

        self.assertNotIn('super-secret-value', raw)  # ciphertext, not plaintext
        self.assertEqual(GoogleOAuthToken.objects.get(user=user).token_json, payload)  # round-trips


class CampaignOwnershipTests(TestCase):
    """Ownership is a database constraint now, not a filesystem path."""

    def setUp(self):
        self.alice = User.objects.create_user(username='alice2', password='Str0ng!Passphrase42')
        self.bob = User.objects.create_user(username='bob2', password='Str0ng!Passphrase42')
        self.campaign = Campaign.objects.create(owner=self.alice, role='Data Scientist', status='active')

    def test_owner_can_view_their_campaign(self):
        self.client.force_login(self.alice)
        resp = self.client.get(f'/campaign/{self.campaign.pk}/')
        self.assertEqual(resp.status_code, 200)

    def test_other_user_gets_404_not_data(self):
        self.client.force_login(self.bob)
        resp = self.client.get(f'/campaign/{self.campaign.pk}/')
        self.assertEqual(resp.status_code, 404)

    def test_other_user_cannot_create_someone_elses_campaign(self):
        self.client.force_login(self.bob)
        resp = self.client.post(f'/campaign/{self.campaign.pk}/create/', {'role': 'Hijacked', 'jd_text': 'x'})
        self.assertEqual(resp.status_code, 404)

    def test_other_user_cannot_fetch_someone_elses_resume(self):
        candidate = Candidate.objects.create(campaign=self.campaign, email='c@example.com')
        self.client.force_login(self.bob)
        resp = self.client.get(f'/campaign/{self.campaign.pk}/candidates/{candidate.pk}/resume/')
        self.assertEqual(resp.status_code, 404)

    def test_dashboard_only_lists_own_campaigns(self):
        Campaign.objects.create(owner=self.bob, role='Bob Only Role')
        self.client.force_login(self.alice)
        resp = self.client.get('/dashboard/')
        self.assertContains(resp, 'Data Scientist')
        self.assertNotContains(resp, 'Bob Only Role')


class RecipientValidationTests(TestCase):
    """The POSTed address list used to go straight to the Gmail API."""

    def setUp(self):
        self.user = User.objects.create_user(username='gina', password='Str0ng!Passphrase42')
        self.campaign = Campaign.objects.create(owner=self.user, role='PM', form_id='F1')
        Candidate.objects.create(campaign=self.campaign, email='real@example.com')
        Candidate.objects.create(campaign=self.campaign, email='Also.Real@Example.com')

    def test_validate_recipients_filters_foreign_addresses(self):
        from hiring_app.views import _validate_recipients
        valid, rejected = _validate_recipients(
            self.campaign,
            ['real@example.com', 'also.real@example.com', 'attacker@evil.com'],
        )
        self.assertEqual(
            sorted(c.email for c in valid),
            ['Also.Real@Example.com', 'real@example.com'],
        )
        self.assertEqual(rejected, ['attacker@evil.com'])

    def test_send_invites_rejects_foreign_address_end_to_end(self):
        self.client.force_login(self.user)
        resp = self.client.post(
            f'/campaign/{self.campaign.pk}/invites/',
            {'selected_candidates': ['attacker@evil.com'], 'interview_date': '2026-09-01T10:00'},
            follow=True,
        )
        self.assertContains(resp, 'do not belong to this campaign'.split()[0])  # cheap smoke check
        self.assertIsNone(Candidate.objects.get(email='real@example.com').invite_sent_at)


class OutcomeConfirmationTests(TestCase):
    """Bulk offer/rejection email is irreversible and requires typed confirmation."""

    def setUp(self):
        self.user = User.objects.create_user(username='hank', password='Str0ng!Passphrase42')
        self.campaign = Campaign.objects.create(owner=self.user, role='Analyst', form_id='F1')
        self.hired = Candidate.objects.create(campaign=self.campaign, email='hire.me@example.com')
        Candidate.objects.create(campaign=self.campaign, email='reject.me@example.com')

    def test_first_post_shows_interstitial_without_sending(self):
        self.client.force_login(self.user)
        resp = self.client.post(
            f'/campaign/{self.campaign.pk}/outcomes/',
            {'hired_candidates': ['hire.me@example.com']},
        )
        self.assertContains(resp, 'Confirm outcome emails')
        self.hired.refresh_from_db()
        self.assertIsNone(self.hired.outcome_sent_at)  # nothing sent yet

    def test_no_google_connected_still_sends_via_django_email_backend(self):
        """As of Phase 2, Google is optional — outcome emails go out through
        Django's configured EMAIL_BACKEND (DEFAULT_FROM_EMAIL) when the
        recruiter hasn't connected Google, rather than being blocked."""
        from django.core import mail
        self.client.force_login(self.user)
        resp = self.client.post(
            f'/campaign/{self.campaign.pk}/outcomes/',
            {'hired_candidates': ['hire.me@example.com'], 'confirm': 'SEND'},
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.hired.refresh_from_db()
        self.assertIsNotNone(self.hired.outcome_sent_at)
        self.assertEqual(self.hired.outcome_type, 'offer')
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.status, 'completed')
        self.assertEqual(len(mail.outbox), 2)  # one offer, one rejection


class ApplyPageTests(TestCase):
    """The Phase 2 public apply page — replaces the Google Form as intake.

    Every successful submission here writes a real file via Candidate.resume
    (Django's test runner sandboxes the database but not file storage), so
    MEDIA_ROOT is overridden to a temp dir for the duration of this class —
    without it, running the suite leaves real files behind under
    media/resumes/<uuid-that-no-longer-exists-once-the-test-db-rolls-back>/.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._media_root = tempfile.mkdtemp(prefix='hireai-test-media-')
        cls._override = override_settings(MEDIA_ROOT=cls._media_root)
        cls._override.enable()

    @classmethod
    def tearDownClass(cls):
        cls._override.disable()
        shutil.rmtree(cls._media_root, ignore_errors=True)
        super().tearDownClass()

    # Passes ApplicationForm.clean_resume's magic-byte check, but has no xref
    # table so pypdf can't actually parse it — exercises the "upload succeeds,
    # text extraction fails gracefully" path (resume_status='parse_failed'),
    # not full end-to-end text extraction + scoring. That path was verified
    # manually against a real resume PDF during development (correct score
    # and matched_terms) rather than with a hand-built minimal PDF here.
    MIN_PDF = (
        b"%PDF-1.1\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 3 3]>>endobj\n"
        b"trailer<</Root 1 0 R>>"
    )

    def setUp(self):
        self.user = User.objects.create_user(username='ivy', password='Str0ng!Passphrase42')
        self.campaign = Campaign.objects.create(
            owner=self.user, role='Backend Engineer', status='active',
            scoring_keywords=['python', 'django', 'sql', 'docker'],
        )

    def _upload(self, content=None, name='resume.pdf', ctype='application/pdf'):
        from django.core.files.uploadedfile import SimpleUploadedFile
        return SimpleUploadedFile(name, content or self.MIN_PDF, content_type=ctype)

    def _post(self, **overrides):
        data = {
            'full_name': 'Test Applicant', 'email': 'applicant@example.com',
            'years_experience': '2', 'why_fit': 'Relevant experience.',
            'linkedin_url': '', 'consent': 'on',
        }
        data.update(overrides)
        resume = data.pop('resume', None) or self._upload()
        return self.client.post(f'/apply/{self.campaign.public_token}/', {**data, 'resume': resume})

    def test_valid_application_creates_candidate(self):
        resp = self._post()
        self.assertContains(resp, 'Application received')
        candidate = Candidate.objects.get(campaign=self.campaign, email='applicant@example.com')
        self.assertEqual(candidate.full_name, 'Test Applicant')
        self.assertEqual(candidate.source, Candidate.SOURCE_APPLY_PAGE)
        self.assertTrue(candidate.resume.name)
        self.assertIsNotNone(candidate.consent_at)

    def test_real_resume_is_parsed_and_scored(self):
        """End-to-end with a genuinely pypdf-parseable PDF (real xref table,
        real text-showing content stream) — MIN_PDF above deliberately isn't
        one, so this is what covers the real _extract_text -> _score_resume
        integration, not just the scoring math (see ScoringTests) or the
        upload/validation plumbing (the other tests in this class)."""
        content = _build_valid_pdf_with_text("python django docker experience")

        self.campaign.scoring_keywords = ['python', 'django', 'docker', 'kubernetes']
        self.campaign.save(update_fields=['scoring_keywords'])

        resp = self._post(resume=self._upload(content=content))
        self.assertContains(resp, 'Application received')
        candidate = Candidate.objects.get(campaign=self.campaign, email='applicant@example.com')
        self.assertEqual(candidate.resume_status, 'parsed')
        self.assertEqual(sorted(candidate.matched_terms), ['django', 'docker', 'python'])
        self.assertEqual(candidate.score, 75)  # 3/4 keywords

    def test_oversized_resume_rejected(self):
        from hiring_app.services import MAX_RESUME_BYTES
        big = b"%PDF-1.1\n" + b"0" * (MAX_RESUME_BYTES + 1)
        resp = self._post(resume=self._upload(content=big))
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Candidate.objects.filter(email='applicant@example.com').exists())

    def test_non_pdf_rejected(self):
        resp = self._post(resume=self._upload(content=b'just some text', name='resume.pdf'))
        self.assertFalse(Candidate.objects.filter(email='applicant@example.com').exists())

    def test_spoofed_extension_rejected(self):
        """.pdf extension but wrong magic bytes — extension alone is trivially
        spoofed by renaming any file."""
        resp = self._post(resume=self._upload(content=b'MZ\x90\x00 not a pdf', name='resume.pdf'))
        self.assertFalse(Candidate.objects.filter(email='applicant@example.com').exists())

    def test_missing_consent_rejected(self):
        resp = self._post(consent='')
        self.assertFalse(Candidate.objects.filter(email='applicant@example.com').exists())

    def test_second_application_updates_rather_than_duplicates(self):
        self._post(why_fit='First attempt')
        self._post(why_fit='Corrected version')
        self.assertEqual(Candidate.objects.filter(campaign=self.campaign).count(), 1)
        self.assertEqual(
            Candidate.objects.get(campaign=self.campaign).why_fit, 'Corrected version',
        )

    def test_draft_campaign_rejects_applications(self):
        self.campaign.status = 'draft'
        self.campaign.save()
        resp = self._post()
        self.assertContains(resp, 'Not open yet')
        self.assertFalse(Candidate.objects.filter(email='applicant@example.com').exists())

    def test_completed_campaign_rejects_applications(self):
        self.campaign.status = 'completed'
        self.campaign.save()
        resp = self._post()
        self.assertContains(resp, 'closed')
        self.assertFalse(Candidate.objects.filter(email='applicant@example.com').exists())

    def test_unknown_token_404s(self):
        resp = self.client.get('/apply/does-not-exist-at-all/')
        self.assertEqual(resp.status_code, 404)


class ScoringTests(TestCase):
    """Word-boundary matching — the old substring check matched "java" inside
    "javascript" and "api" inside "therapist"."""

    def setUp(self):
        from hiring_app.services import HiringAutomator
        self.automator = HiringAutomator(creds=None)

    def test_substring_false_positives_fixed(self):
        score, matched = self.automator._score_resume(
            "Experienced JavaScript and therapist background.",
            ["java", "api"],
        )
        self.assertEqual(matched, [])
        self.assertEqual(score, 0)

    def test_real_matches_still_score(self):
        score, matched = self.automator._score_resume(
            "5 years of Python and Django, deployed with Docker.",
            ["python", "django", "docker", "aws"],
        )
        self.assertEqual(sorted(matched), ['django', 'docker', 'python'])
        self.assertEqual(score, 75)  # 3/4 keywords, normalised to 0-100

    def test_empty_keywords_scores_zero_not_error(self):
        score, matched = self.automator._score_resume("anything", [])
        self.assertEqual((score, matched), (0, []))
