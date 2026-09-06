"""
Phase 0 (security hardening) + Phase 1 (Postgres-backed campaigns) +
Phase 2 (public apply page) verification.
"""
import json
import os
import shutil
import tempfile

from django.conf import settings
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
        dt = a.parse_interview_datetime('2026-09-01T14:30')
        self.assertFalse(timezone.is_naive(dt))
        self.assertEqual(dt.hour, 14)
        with self.assertRaises(ValueError):
            a.parse_interview_datetime('not-a-date')

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


class BackgroundTaskTests(TestCase):
    """Phase 3: invites/outcomes run as Celery tasks, not inline in the
    request. CELERY_TASK_ALWAYS_EAGER is forced on under the test runner
    (settings.py: `if TESTING`), so `.delay()` here runs synchronously in the
    same process — no broker or worker needed to test the task logic itself.
    """

    def setUp(self):
        self.user = User.objects.create_user(username='jack', password='Str0ng!Passphrase42')
        self.campaign = Campaign.objects.create(owner=self.user, role='Engineer', status='active')
        self.c1 = Candidate.objects.create(campaign=self.campaign, email='jack1@example.com', full_name='One')
        self.c2 = Candidate.objects.create(campaign=self.campaign, email='jack2@example.com', full_name='Two')

    # ── idempotency: the actual point of this phase ──────────
    def test_send_outcomes_task_does_not_double_send_on_retry(self):
        """The specific failure this phase exists to prevent: re-running the
        same task (a crash + redeliver, or just clicking twice) must not
        re-email anyone already reached."""
        from django.core import mail
        from hiring_app.tasks import send_outcomes_task

        first = send_outcomes_task.delay(str(self.campaign.pk), [self.c1.pk])
        self.assertEqual(first.get(), {'sent': 2, 'skipped': 0, 'failed': 0})
        self.assertEqual(len(mail.outbox), 2)

        second = send_outcomes_task.delay(str(self.campaign.pk), [self.c1.pk])
        self.assertEqual(second.get(), {'sent': 0, 'skipped': 2, 'failed': 0})
        self.assertEqual(len(mail.outbox), 2)  # unchanged — nothing re-sent

    def test_send_invites_task_does_not_double_send_on_retry(self):
        from django.core import mail
        from hiring_app.tasks import send_invites_task

        args = (str(self.campaign.pk), [self.c1.pk, self.c2.pk], 'Hiring Team', '2026-09-01T10:00')
        first = send_invites_task.delay(*args)
        self.assertEqual(first.get(), {'sent': 2, 'skipped': 0, 'failed': 0})
        self.assertEqual(len(mail.outbox), 2)

        second = send_invites_task.delay(*args)
        self.assertEqual(second.get(), {'sent': 0, 'skipped': 2, 'failed': 0})
        self.assertEqual(len(mail.outbox), 2)

    def test_send_outcomes_task_marks_campaign_completed(self):
        from hiring_app.tasks import send_outcomes_task
        send_outcomes_task.delay(str(self.campaign.pk), [self.c1.pk]).get()
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.status, 'completed')

    def test_send_outcomes_task_survives_a_deleted_campaign(self):
        """A redelivered task for a campaign that no longer exists must not
        raise — there's nothing sensible left to retry."""
        from hiring_app.tasks import send_outcomes_task
        fake_id = self.campaign.pk
        self.campaign.delete()
        result = send_outcomes_task.delay(str(fake_id), [self.c1.pk])
        self.assertEqual(result.get(), {'sent': 0, 'skipped': 0, 'failed': 0})

    # ── views enqueue and return, don't send inline ──────────
    def test_send_outcomes_view_enqueues_and_redirects_with_watch_param(self):
        self.client.force_login(self.user)
        resp = self.client.post(
            f'/campaign/{self.campaign.pk}/outcomes/',
            {'hired_candidates': [self.c1.email], 'confirm': 'SEND'},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn('?watch=outcomes', resp['Location'])

    def test_send_invites_view_rejects_bad_date_before_enqueueing(self):
        from django.core import mail
        self.client.force_login(self.user)
        resp = self.client.post(
            f'/campaign/{self.campaign.pk}/invites/',
            {'selected_candidates': [self.c1.email], 'interview_date': 'not-a-real-date'},
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)
        self.c1.refresh_from_db()
        self.assertIsNone(self.c1.invite_sent_at)

    # ── status endpoint ───────────────────────────────────────
    def test_campaign_status_reports_counts(self):
        from hiring_app.tasks import send_outcomes_task
        send_outcomes_task.delay(str(self.campaign.pk), [self.c1.pk]).get()

        self.client.force_login(self.user)
        resp = self.client.get(f'/campaign/{self.campaign.pk}/status/')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['total_candidates'], 2)
        self.assertEqual(data['outcomes_sent'], 2)
        self.assertEqual(data['status'], 'completed')

    def test_campaign_status_ownership_checked(self):
        other = User.objects.create_user(username='mallory', password='Str0ng!Passphrase42')
        self.client.force_login(other)
        resp = self.client.get(f'/campaign/{self.campaign.pk}/status/')
        self.assertEqual(resp.status_code, 404)


class LegalPagesTests(TestCase):
    """Phase 4: privacy policy + terms are public, linked from the footer,
    and the apply page's consent notice actually names a deletion contact."""

    def test_privacy_page_loads(self):
        resp = self.client.get('/privacy/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Privacy Policy')

    def test_terms_page_loads(self):
        resp = self.client.get('/terms/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Terms of Service')

    def test_footer_links_to_both_on_a_public_page(self):
        resp = self.client.get('/')
        self.assertContains(resp, '/privacy/')
        self.assertContains(resp, '/terms/')

    def test_apply_page_notice_names_retention_and_contact(self):
        user = User.objects.create_user(username='nora', password='Str0ng!Passphrase42')
        campaign = Campaign.objects.create(owner=user, role='Analyst', status='active')
        resp = self.client.get(f'/apply/{campaign.public_token}/')
        self.assertContains(resp, str(campaign.retention_days))
        self.assertContains(resp, settings.PRIVACY_CONTACT_EMAIL)


class AdminRegistrationTests(TestCase):
    """Phase 4: Campaign/Candidate need to be admin-manageable to service
    erasure requests; GoogleOAuthToken deliberately stays unregistered — it's
    encrypted OAuth credentials with no legitimate reason to browse in admin.
    """

    def test_campaign_and_candidate_are_registered(self):
        from django.contrib import admin
        self.assertIn(Campaign, admin.site._registry)
        self.assertIn(Candidate, admin.site._registry)

    def test_google_oauth_token_is_not_registered(self):
        from django.contrib import admin
        from hiring_app.models import GoogleOAuthToken
        self.assertNotIn(GoogleOAuthToken, admin.site._registry)


class ResumeRetentionTests(TestCase):
    """Phase 4: resume files must not outlive the Candidate/Campaign rows
    that reference them, and must be purged automatically once a closed
    campaign's retention window elapses.

    Writes real files via Candidate.resume, same reason as ApplyPageTests —
    MEDIA_ROOT is overridden to a temp dir for the duration of this class.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._media_root = tempfile.mkdtemp(prefix='hireai-test-retention-')
        cls._override = override_settings(MEDIA_ROOT=cls._media_root)
        cls._override.enable()

    @classmethod
    def tearDownClass(cls):
        cls._override.disable()
        shutil.rmtree(cls._media_root, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.user = User.objects.create_user(username='priya', password='Str0ng!Passphrase42')
        self.campaign = Campaign.objects.create(owner=self.user, role='Designer', status='active')

    def _candidate_with_resume(self, **overrides):
        from django.core.files.base import ContentFile
        defaults = dict(campaign=self.campaign, email='res@example.com', text_preview='some extracted text')
        defaults.update(overrides)
        candidate = Candidate.objects.create(**defaults)
        candidate.resume.save('resume.pdf', ContentFile(b'%PDF-1.1\nfake'), save=True)
        return candidate

    def test_deleting_candidate_removes_resume_file_from_disk(self):
        candidate = self._candidate_with_resume()
        path = candidate.resume.path
        self.assertTrue(os.path.exists(path))
        candidate.delete()
        self.assertFalse(os.path.exists(path))

    def test_deleting_campaign_cascades_and_removes_resume_files(self):
        candidate = self._candidate_with_resume()
        path = candidate.resume.path
        self.campaign.delete()
        self.assertFalse(os.path.exists(path))

    def test_purge_leaves_active_campaign_untouched(self):
        from hiring_app.tasks import purge_expired_resumes
        candidate = self._candidate_with_resume()
        # status stays 'active' / closed_at stays None from setUp.
        result = purge_expired_resumes()
        self.assertEqual(result, {'campaigns_swept': 0, 'candidates_purged': 0})
        candidate.refresh_from_db()
        self.assertTrue(candidate.resume)
        self.assertTrue(os.path.exists(candidate.resume.path))

    def test_purge_leaves_recently_closed_campaign_untouched(self):
        from django.utils import timezone
        from hiring_app.tasks import purge_expired_resumes
        candidate = self._candidate_with_resume()
        self.campaign.status = 'completed'
        self.campaign.closed_at = timezone.now()  # closed just now — well within retention_days
        self.campaign.save()

        result = purge_expired_resumes()
        self.assertEqual(result, {'campaigns_swept': 0, 'candidates_purged': 0})
        candidate.refresh_from_db()
        self.assertTrue(candidate.resume)

    def test_purge_clears_resume_and_text_preview_past_retention(self):
        from datetime import timedelta
        from django.utils import timezone
        from hiring_app.tasks import purge_expired_resumes

        candidate = self._candidate_with_resume()
        path = candidate.resume.path
        self.campaign.status = 'completed'
        self.campaign.retention_days = 30
        self.campaign.closed_at = timezone.now() - timedelta(days=31)
        self.campaign.save()

        result = purge_expired_resumes()
        self.assertEqual(result, {'campaigns_swept': 1, 'candidates_purged': 1})

        candidate.refresh_from_db()
        self.assertFalse(candidate.resume)
        self.assertEqual(candidate.text_preview, '')
        self.assertFalse(os.path.exists(path))
        # The candidate record itself survives — only the file/text are purged.
        self.assertTrue(Candidate.objects.filter(pk=candidate.pk).exists())

    def test_purge_is_a_noop_the_second_time(self):
        """Nothing left to clear on a re-run shouldn't error or re-count."""
        from datetime import timedelta
        from django.utils import timezone
        from hiring_app.tasks import purge_expired_resumes

        self._candidate_with_resume()
        self.campaign.status = 'completed'
        self.campaign.retention_days = 30
        self.campaign.closed_at = timezone.now() - timedelta(days=31)
        self.campaign.save()

        purge_expired_resumes()
        result = purge_expired_resumes()
        self.assertEqual(result, {'campaigns_swept': 1, 'candidates_purged': 0})


class AccountDeletionTests(TestCase):
    """Phase 4: a recruiter can permanently delete their own account, and
    only their own — cascading to their campaigns, candidates, resume files,
    and any connected Google grant."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._media_root = tempfile.mkdtemp(prefix='hireai-test-delete-')
        cls._override = override_settings(MEDIA_ROOT=cls._media_root)
        cls._override.enable()

    @classmethod
    def tearDownClass(cls):
        cls._override.disable()
        shutil.rmtree(cls._media_root, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.user = User.objects.create_user(username='quinn', password='Str0ng!Passphrase42')
        self.campaign = Campaign.objects.create(owner=self.user, role='PM', status='active')
        self.candidate = Candidate.objects.create(campaign=self.campaign, email='c@example.com')
        from django.core.files.base import ContentFile
        self.candidate.resume.save('r.pdf', ContentFile(b'%PDF-1.1\nfake'), save=True)
        self.resume_path = self.candidate.resume.path

    def test_confirm_page_requires_login(self):
        resp = self.client.get('/account/delete/')
        self.assertEqual(resp.status_code, 302)  # redirected to login

    def test_confirm_page_reports_counts(self):
        self.client.force_login(self.user)
        resp = self.client.get('/account/delete/')
        self.assertEqual(resp.context['campaign_count'], 1)
        self.assertEqual(resp.context['candidate_count'], 1)

    def test_wrong_confirmation_text_deletes_nothing(self):
        self.client.force_login(self.user)
        resp = self.client.post('/account/delete/confirm/', {'confirm': 'delete'}, follow=True)
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())
        self.assertTrue(Campaign.objects.filter(pk=self.campaign.pk).exists())

    def test_delete_requires_post(self):
        self.client.force_login(self.user)
        resp = self.client.get('/account/delete/confirm/')
        self.assertEqual(resp.status_code, 405)

    def test_confirmed_deletion_cascades_everything(self):
        self.client.force_login(self.user)
        user_id = self.user.pk
        resp = self.client.post('/account/delete/confirm/', {'confirm': 'DELETE'})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp['Location'], '/')

        self.assertFalse(User.objects.filter(pk=user_id).exists())
        self.assertFalse(Campaign.objects.filter(pk=self.campaign.pk).exists())
        self.assertFalse(Candidate.objects.filter(pk=self.candidate.pk).exists())
        self.assertFalse(os.path.exists(self.resume_path))

    def test_deletion_logs_the_user_out(self):
        self.client.force_login(self.user)
        self.client.post('/account/delete/confirm/', {'confirm': 'DELETE'})
        # A follow-up request to a login-required page should now bounce to login.
        resp = self.client.get('/dashboard/')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/login/', resp['Location'])

    def test_deletion_revokes_and_removes_google_token(self):
        from unittest.mock import patch
        from hiring_app.models import GoogleOAuthToken
        import json

        GoogleOAuthToken.objects.create(
            user=self.user, token_json=json.dumps({'refresh_token': 'rt-123'}),
        )
        self.client.force_login(self.user)
        with patch('hiring_app.views.requests.post') as mock_post:
            mock_post.return_value.status_code = 200
            self.client.post('/account/delete/confirm/', {'confirm': 'DELETE'})
            mock_post.assert_called_once()
        self.assertFalse(GoogleOAuthToken.objects.filter(user__pk=self.user.pk).exists())

    def test_deleting_one_account_does_not_touch_another_users_data(self):
        other = User.objects.create_user(username='rex', password='Str0ng!Passphrase42')
        other_campaign = Campaign.objects.create(owner=other, role='Other role', status='active')

        self.client.force_login(self.user)
        self.client.post('/account/delete/confirm/', {'confirm': 'DELETE'})

        self.assertTrue(User.objects.filter(pk=other.pk).exists())
        self.assertTrue(Campaign.objects.filter(pk=other_campaign.pk).exists())


class LinkedInCredsTests(TestCase):
    """get_user_linkedin_creds / HiringAutomator.has_linkedin — the same
    "optional, per-user, no shared fallback" shape as Google, minus the
    refresh-token dance LinkedIn's scopes don't grant."""

    def setUp(self):
        self.user = User.objects.create_user(username='sam', password='Str0ng!Passphrase42')

    def _make_token(self, expires_in_seconds):
        from django.utils import timezone
        from hiring_app.models import LinkedInOAuthToken
        LinkedInOAuthToken.objects.create(
            user=self.user,
            token_json=json.dumps({
                'access_token': 'tok-123',
                'member_urn': 'urn:li:person:abc',
                'expires_at': timezone.now().timestamp() + expires_in_seconds,
            }),
        )

    def test_no_token_returns_none(self):
        from hiring_app.services import get_user_linkedin_creds
        self.assertIsNone(get_user_linkedin_creds(self.user))

    def test_valid_token_returns_creds_dict(self):
        from hiring_app.services import get_user_linkedin_creds
        self._make_token(expires_in_seconds=3600)
        creds = get_user_linkedin_creds(self.user)
        self.assertEqual(creds['access_token'], 'tok-123')
        self.assertEqual(creds['member_urn'], 'urn:li:person:abc')

    def test_expired_token_returns_none(self):
        """No refresh token under these scopes — expired just means
        'reconnect', same as never having connected at all."""
        from hiring_app.services import get_user_linkedin_creds
        self._make_token(expires_in_seconds=-3600)
        self.assertIsNone(get_user_linkedin_creds(self.user))

    def test_token_json_is_encrypted_in_the_database(self):
        from django.db import connection
        self._make_token(expires_in_seconds=3600)
        with connection.cursor() as cur:
            cur.execute(
                "SELECT token_json FROM hiring_app_linkedinoauthtoken WHERE user_id = %s",
                [self.user.id],
            )
            raw = cur.fetchone()[0]
        self.assertNotIn('tok-123', raw)  # ciphertext, not plaintext

    def test_automator_has_linkedin_reflects_creds(self):
        from hiring_app.services import HiringAutomator
        self.assertFalse(HiringAutomator(linkedin_creds=None).has_linkedin)
        self.assertTrue(HiringAutomator(linkedin_creds={'access_token': 'x', 'member_urn': 'y'}).has_linkedin)


class LinkedInPostingTests(TestCase):
    """HiringAutomator.post_jd_to_linkedin / create_campaign's opt-in
    cross-post — best-effort like Sheets export, never blocks a launch."""

    def setUp(self):
        self.user = User.objects.create_user(username='tara', password='Str0ng!Passphrase42')
        self.campaign = Campaign.objects.create(owner=self.user, role='Recruiter', status='draft')
        self.creds = {'access_token': 'tok-abc', 'member_urn': 'urn:li:person:xyz'}

    def test_post_success_sets_linkedin_post_id(self):
        from unittest.mock import patch, MagicMock
        from hiring_app.services import HiringAutomator

        mock_resp = MagicMock(status_code=201, headers={'x-restli-id': 'urn:li:share:999'})
        mock_resp.raise_for_status.return_value = None
        with patch('hiring_app.services.requests.post', return_value=mock_resp) as mock_post:
            automator = HiringAutomator(linkedin_creds=self.creds)
            ok = automator.post_jd_to_linkedin(self.campaign, 'A great job description.', 'https://example.com/apply/x/')
            self.assertTrue(ok)
            mock_post.assert_called_once()
        self.assertEqual(self.campaign.linkedin_post_id, 'urn:li:share:999')

    def test_post_failure_never_raises_and_leaves_post_id_blank(self):
        from unittest.mock import patch
        import requests as requests_module
        from hiring_app.services import HiringAutomator

        with patch('hiring_app.services.requests.post', side_effect=requests_module.RequestException('boom')):
            automator = HiringAutomator(linkedin_creds=self.creds)
            ok = automator.post_jd_to_linkedin(self.campaign, 'JD text', 'https://example.com/apply/x/')
        self.assertFalse(ok)
        self.assertEqual(self.campaign.linkedin_post_id, '')

    def test_create_campaign_skips_posting_when_not_connected(self):
        """post_to_linkedin=True but has_linkedin is False (no creds) must be
        a silent no-op, not an AttributeError on self.linkedin_creds."""
        from unittest.mock import patch
        from hiring_app.services import HiringAutomator

        with patch('hiring_app.services.requests.post') as mock_post:
            automator = HiringAutomator(linkedin_creds=None)
            automator.create_campaign(self.campaign, 'JD text', post_to_linkedin=True, apply_url='https://x/')
            mock_post.assert_not_called()
        self.assertEqual(self.campaign.linkedin_post_id, '')
        self.assertEqual(self.campaign.status, 'active')  # still launched

    def test_create_campaign_does_not_post_when_checkbox_unset(self):
        from unittest.mock import patch
        from hiring_app.services import HiringAutomator

        with patch('hiring_app.services.requests.post') as mock_post:
            automator = HiringAutomator(linkedin_creds=self.creds)
            automator.create_campaign(self.campaign, 'JD text', post_to_linkedin=False, apply_url='https://x/')
            mock_post.assert_not_called()

    def test_create_campaign_posts_when_opted_in_and_connected(self):
        from unittest.mock import patch, MagicMock
        from hiring_app.services import HiringAutomator

        mock_resp = MagicMock(status_code=201, headers={'x-restli-id': 'urn:li:share:111'})
        mock_resp.raise_for_status.return_value = None
        with patch('hiring_app.services.requests.post', return_value=mock_resp):
            automator = HiringAutomator(linkedin_creds=self.creds)
            automator.create_campaign(self.campaign, 'JD text', post_to_linkedin=True, apply_url='https://x/')
        self.assertEqual(self.campaign.linkedin_post_id, 'urn:li:share:111')
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.linkedin_post_id, 'urn:li:share:111')  # create_campaign's save() persisted it


class LinkedInPostUrlTests(TestCase):
    def test_blank_when_never_posted(self):
        user = User.objects.create_user(username='uma', password='Str0ng!Passphrase42')
        campaign = Campaign.objects.create(owner=user, role='X')
        self.assertEqual(campaign.linkedin_post_url, '')

    def test_builds_encoded_feed_url_once_posted(self):
        user = User.objects.create_user(username='vic', password='Str0ng!Passphrase42')
        campaign = Campaign.objects.create(owner=user, role='X', linkedin_post_id='urn:li:share:555')
        self.assertEqual(
            campaign.linkedin_post_url,
            'https://www.linkedin.com/feed/update/urn%3Ali%3Ashare%3A555/',
        )


class LinkedInOAuthViewTests(TestCase):
    """The connect/callback/disconnect views — separate provider and flow
    from Google's, but the same shape: optional, per-user, no shared token."""

    def setUp(self):
        self.user = User.objects.create_user(username='walt', password='Str0ng!Passphrase42')

    def test_connect_requires_login(self):
        resp = self.client.get('/linkedin/connect/')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/login/', resp['Location'])

    def test_connect_without_client_id_shows_configuration_error(self):
        from django.test import override_settings
        self.client.force_login(self.user)
        with override_settings(LINKEDIN_CLIENT_ID=''):
            resp = self.client.get('/linkedin/connect/')
        self.assertEqual(resp.status_code, 200)  # renders the error template, doesn't redirect
        self.assertContains(resp, 'not configured')

    def test_connect_redirects_to_linkedin_with_state_in_session(self):
        from django.test import override_settings
        self.client.force_login(self.user)
        with override_settings(LINKEDIN_CLIENT_ID='client-123'):
            resp = self.client.get('/linkedin/connect/')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('linkedin.com/oauth/v2/authorization', resp['Location'])
        self.assertIn('client_id=client-123', resp['Location'])
        self.assertTrue(self.client.session.get('linkedin_oauth_state'))

    def test_callback_rejects_mismatched_state(self):
        self.client.force_login(self.user)
        session = self.client.session
        session['linkedin_oauth_state'] = 'expected-state'
        session.save()
        resp = self.client.get('/linkedin/oauth2callback/', {'code': 'abc', 'state': 'wrong-state'})
        self.assertContains(resp, 'invalid state')
        from hiring_app.models import LinkedInOAuthToken
        self.assertFalse(LinkedInOAuthToken.objects.filter(user=self.user).exists())

    def test_callback_shows_message_on_denied_consent(self):
        self.client.force_login(self.user)
        resp = self.client.get('/linkedin/oauth2callback/', {'error': 'user_cancelled_login'})
        self.assertContains(resp, 'cancelled')

    def test_callback_success_stores_token_and_member_urn(self):
        from unittest.mock import patch, MagicMock
        from hiring_app.models import LinkedInOAuthToken

        self.client.force_login(self.user)
        session = self.client.session
        session['linkedin_oauth_state'] = 'good-state'
        session.save()

        token_resp = MagicMock(status_code=200)
        token_resp.raise_for_status.return_value = None
        token_resp.json.return_value = {'access_token': 'tok-xyz', 'expires_in': 5183999}

        userinfo_resp = MagicMock(status_code=200)
        userinfo_resp.raise_for_status.return_value = None
        userinfo_resp.json.return_value = {'sub': 'member42'}

        with patch('hiring_app.views.requests.post', return_value=token_resp), \
             patch('hiring_app.views.requests.get', return_value=userinfo_resp):
            resp = self.client.get('/linkedin/oauth2callback/', {'code': 'auth-code', 'state': 'good-state'})

        self.assertEqual(resp.status_code, 302)
        token = LinkedInOAuthToken.objects.get(user=self.user)
        data = json.loads(token.token_json)
        self.assertEqual(data['access_token'], 'tok-xyz')
        self.assertEqual(data['member_urn'], 'urn:li:person:member42')

    def test_disconnect_requires_post(self):
        self.client.force_login(self.user)
        resp = self.client.get('/linkedin/disconnect/')
        self.assertEqual(resp.status_code, 405)

    def test_disconnect_removes_token(self):
        from hiring_app.models import LinkedInOAuthToken
        LinkedInOAuthToken.objects.create(user=self.user, token_json=json.dumps({
            'access_token': 'x', 'member_urn': 'y', 'expires_at': 9999999999,
        }))
        self.client.force_login(self.user)
        resp = self.client.post('/linkedin/disconnect/')
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(LinkedInOAuthToken.objects.filter(user=self.user).exists())


class LinkedInManualConnectTests(TestCase):
    """The manual paste-a-token alternative to the OAuth flow — for a single
    self-hosted operator with their own LinkedIn Developer app access, using
    a token generated by hand from LinkedIn's own portal rather than going
    through linkedin_connect's consent-screen redirect."""

    def setUp(self):
        self.user = User.objects.create_user(username='yusuf', password='Str0ng!Passphrase42')

    def test_requires_login(self):
        resp = self.client.post('/linkedin/connect-manual/', {'access_token': 'x', 'member_id': 'y'})
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/login/', resp['Location'])

    def test_requires_post(self):
        self.client.force_login(self.user)
        resp = self.client.get('/linkedin/connect-manual/')
        self.assertEqual(resp.status_code, 405)

    def test_missing_fields_rejected(self):
        from hiring_app.models import LinkedInOAuthToken
        self.client.force_login(self.user)
        resp = self.client.post('/linkedin/connect-manual/', {'access_token': '', 'member_id': 'abc123'}, follow=True)
        self.assertContains(resp, 'required')
        self.assertFalse(LinkedInOAuthToken.objects.filter(user=self.user).exists())

    def test_bare_member_id_gets_normalised_to_a_urn(self):
        from hiring_app.models import LinkedInOAuthToken
        self.client.force_login(self.user)
        self.client.post('/linkedin/connect-manual/', {'access_token': 'tok-1', 'member_id': 'abc123'})
        token = LinkedInOAuthToken.objects.get(user=self.user)
        data = json.loads(token.token_json)
        self.assertEqual(data['member_urn'], 'urn:li:person:abc123')
        self.assertEqual(data['access_token'], 'tok-1')

    def test_full_urn_is_not_double_prefixed(self):
        from hiring_app.models import LinkedInOAuthToken
        self.client.force_login(self.user)
        self.client.post('/linkedin/connect-manual/', {
            'access_token': 'tok-1', 'member_id': 'urn:li:person:already-a-urn',
        })
        token = LinkedInOAuthToken.objects.get(user=self.user)
        data = json.loads(token.token_json)
        self.assertEqual(data['member_urn'], 'urn:li:person:already-a-urn')

    def test_resaving_updates_rather_than_duplicates(self):
        from hiring_app.models import LinkedInOAuthToken
        self.client.force_login(self.user)
        self.client.post('/linkedin/connect-manual/', {'access_token': 'old-tok', 'member_id': 'abc'})
        self.client.post('/linkedin/connect-manual/', {'access_token': 'new-tok', 'member_id': 'abc'})
        self.assertEqual(LinkedInOAuthToken.objects.filter(user=self.user).count(), 1)
        data = json.loads(LinkedInOAuthToken.objects.get(user=self.user).token_json)
        self.assertEqual(data['access_token'], 'new-tok')

    def test_manually_saved_token_is_immediately_usable(self):
        """Round-trips through get_user_linkedin_creds — the same function
        the OAuth-connected path relies on — proving there's exactly one
        code path downstream regardless of how the token got there."""
        from hiring_app.services import get_user_linkedin_creds
        self.client.force_login(self.user)
        self.client.post('/linkedin/connect-manual/', {'access_token': 'tok-1', 'member_id': 'abc123'})
        creds = get_user_linkedin_creds(self.user)
        self.assertIsNotNone(creds)
        self.assertEqual(creds['access_token'], 'tok-1')
        self.assertEqual(creds['member_urn'], 'urn:li:person:abc123')


class CreateCampaignLinkedInIntegrationTests(TestCase):
    """The full view-level path: the checkbox on agent.html's launch form
    actually reaches HiringAutomator.create_campaign and behaves as promised
    in the flash message."""

    def setUp(self):
        self.user = User.objects.create_user(username='xena', password='Str0ng!Passphrase42')
        self.campaign = Campaign.objects.create(owner=self.user, role='Draft role', status='draft')

    def _launch(self, **extra):
        data = {'role': 'Engineer', 'jd_text': 'Job description text.'}
        data.update(extra)
        return self.client.post(f'/campaign/{self.campaign.pk}/create/', data, follow=True)

    def test_launch_without_linkedin_connection_ignores_checkbox(self):
        self.client.force_login(self.user)
        resp = self._launch(post_to_linkedin='on')
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.status, 'active')
        self.assertEqual(self.campaign.linkedin_post_id, '')
        self.assertNotContains(resp, 'LinkedIn')

    def test_launch_with_connection_and_checkbox_posts_and_confirms(self):
        from unittest.mock import patch, MagicMock
        from hiring_app.models import LinkedInOAuthToken
        from django.utils import timezone

        LinkedInOAuthToken.objects.create(user=self.user, token_json=json.dumps({
            'access_token': 'tok', 'member_urn': 'urn:li:person:1',
            'expires_at': timezone.now().timestamp() + 3600,
        }))
        self.client.force_login(self.user)

        mock_resp = MagicMock(status_code=201, headers={'x-restli-id': 'urn:li:share:42'})
        mock_resp.raise_for_status.return_value = None
        with patch('hiring_app.services.requests.post', return_value=mock_resp):
            resp = self._launch(post_to_linkedin='on')

        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.linkedin_post_id, 'urn:li:share:42')
        self.assertContains(resp, 'Also posted to your LinkedIn feed')

    def test_launch_with_connection_but_unchecked_box_does_not_post(self):
        from unittest.mock import patch
        from hiring_app.models import LinkedInOAuthToken
        from django.utils import timezone

        LinkedInOAuthToken.objects.create(user=self.user, token_json=json.dumps({
            'access_token': 'tok', 'member_urn': 'urn:li:person:1',
            'expires_at': timezone.now().timestamp() + 3600,
        }))
        self.client.force_login(self.user)

        with patch('hiring_app.services.requests.post') as mock_post:
            self._launch()  # no post_to_linkedin in the POST data at all
            mock_post.assert_not_called()
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.linkedin_post_id, '')

    def test_launch_warns_when_linkedin_post_fails(self):
        from unittest.mock import patch
        from hiring_app.models import LinkedInOAuthToken
        from django.utils import timezone
        import requests as requests_module

        LinkedInOAuthToken.objects.create(user=self.user, token_json=json.dumps({
            'access_token': 'tok', 'member_urn': 'urn:li:person:1',
            'expires_at': timezone.now().timestamp() + 3600,
        }))
        self.client.force_login(self.user)

        with patch('hiring_app.services.requests.post', side_effect=requests_module.RequestException('down')):
            resp = self._launch(post_to_linkedin='on')

        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.status, 'active')  # launch still succeeds
        self.assertEqual(self.campaign.linkedin_post_id, '')
        self.assertContains(resp, 'posting to LinkedIn failed')


class LinkedInAdminRegistrationTests(TestCase):
    def test_linkedin_oauth_token_is_not_registered(self):
        from django.contrib import admin
        from hiring_app.models import LinkedInOAuthToken
        self.assertNotIn(LinkedInOAuthToken, admin.site._registry)


class JdManualFallbackTests(TestCase):
    """A Gemini failure (quota, outage, bad key) must not strand the
    recruiter without a way to launch — the editor and Launch button have to
    appear either way, since the error message itself promises exactly that."""

    def setUp(self):
        self.user = User.objects.create_user(username='amber', password='Str0ng!Passphrase42')
        self.campaign = Campaign.objects.create(owner=self.user, role='New Campaign', status='draft')
        self.client.force_login(self.user)

    def test_failed_generation_still_shows_editable_jd_textarea(self):
        from unittest.mock import patch
        from hiring_app.services import JDGenerationFailed
        with patch('hiring_app.services.HiringAutomator.generate_jd', side_effect=JDGenerationFailed('quota')):
            resp = self.client.post(f'/campaign/{self.campaign.pk}/generate-jd/', {
                'role': 'Backend Engineer', 'experience': '2 years',
            })
        self.assertContains(resp, 'name="jd_text"')
        self.assertContains(resp, 'write your own below')
        self.assertContains(resp, 'Launch Campaign')

    def test_successful_generation_prefills_jd_textarea_without_the_hint(self):
        from unittest.mock import patch
        with patch('hiring_app.services.HiringAutomator.generate_jd', return_value='A drafted JD.'):
            resp = self.client.post(f'/campaign/{self.campaign.pk}/generate-jd/', {
                'role': 'Backend Engineer', 'experience': '2 years',
            })
        self.assertContains(resp, 'A drafted JD.')
        self.assertNotContains(resp, 'write your own below')

    def test_can_launch_with_a_manually_written_jd_after_a_failed_generation(self):
        """The actual end-to-end ask: Gemini down -> write it yourself -> the
        rest of the launch flow behaves exactly as it would with an AI draft."""
        from unittest.mock import patch
        from hiring_app.services import JDGenerationFailed
        with patch('hiring_app.services.HiringAutomator.generate_jd', side_effect=JDGenerationFailed('quota')):
            self.client.post(f'/campaign/{self.campaign.pk}/generate-jd/', {
                'role': 'Backend Engineer', 'experience': '2 years',
            })
        resp = self.client.post(f'/campaign/{self.campaign.pk}/create/', {
            'role': 'Backend Engineer', 'jd_text': 'Hand-written JD text.',
        }, follow=True)
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.status, 'active')
        self.assertEqual(self.campaign.jd_text, 'Hand-written JD text.')
        self.assertContains(resp, 'is live')

    def test_draft_campaign_reload_preserves_previously_saved_jd_text(self):
        """Refreshing the page (no fresh generate_jd POST) shouldn't lose a
        JD that's already been saved — e.g. from an earlier attempt."""
        self.campaign.jd_text = 'Previously saved JD.'
        self.campaign.role = 'Backend Engineer'
        self.campaign.save()
        resp = self.client.get(f'/campaign/{self.campaign.pk}/')
        self.assertContains(resp, 'Previously saved JD.')

    def test_active_campaign_does_not_show_relaunch_form_on_plain_reload(self):
        """Once launched, a plain page visit must not re-offer the launch
        form — create_campaign isn't idempotent about Sheet creation, so
        resubmitting it for an already-active campaign would create a
        duplicate tracking Sheet (see SheetCreationIdempotencyTests)."""
        self.campaign.jd_text = 'Live JD.'
        self.campaign.status = 'active'
        self.campaign.save()
        resp = self.client.get(f'/campaign/{self.campaign.pk}/')
        self.assertNotContains(resp, 'Launch Campaign')


class SheetCreationIdempotencyTests(TestCase):
    """create_campaign used to create a brand-new tracking Sheet on every
    call with no check for an existing one — re-launching (or, after the fix
    above, simply reloading a still-draft campaign's page and resubmitting)
    would silently orphan the previous Sheet."""

    def _connected_automator(self):
        from unittest.mock import MagicMock
        from hiring_app.services import HiringAutomator
        automator = HiringAutomator()
        automator.creds = object()   # has_google only checks creds/gmail are not None
        automator.gmail = MagicMock()
        automator.sheets = MagicMock()
        return automator

    def test_skips_sheet_creation_when_one_already_exists(self):
        user = User.objects.create_user(username='yara', password='Str0ng!Passphrase42')
        campaign = Campaign.objects.create(
            owner=user, role='Analyst', status='active',
            sheet_id='existing-sheet-id', sheet_url='https://existing/',
        )
        automator = self._connected_automator()
        automator.create_campaign(campaign, 'JD text')
        automator.sheets.spreadsheets.return_value.create.assert_not_called()
        self.assertEqual(campaign.sheet_id, 'existing-sheet-id')

    def test_creates_sheet_when_none_exists_yet(self):
        user = User.objects.create_user(username='zane', password='Str0ng!Passphrase42')
        campaign = Campaign.objects.create(owner=user, role='Analyst', status='draft')
        automator = self._connected_automator()
        automator.sheets.spreadsheets.return_value.create.return_value.execute.return_value = {
            'spreadsheetId': 'new-id', 'spreadsheetUrl': 'https://new/',
        }
        automator.create_campaign(campaign, 'JD text')
        automator.sheets.spreadsheets.return_value.create.assert_called_once()
        self.assertEqual(campaign.sheet_id, 'new-id')


class GoogleOptionalUiTests(TestCase):
    """Google/LinkedIn are meant to read as optional extras, not required
    setup — these check the actual UI surfaces the user pointed at: the
    navbar, the landing page's stale claims, the dashboard's Integrations
    panel, and the one real functional risk of skipping Google (no email
    provider configured in production)."""

    def setUp(self):
        self.user = User.objects.create_user(username='bo', password='Str0ng!Passphrase42')

    def test_landing_page_no_longer_claims_google_forms_or_drive(self):
        """The old copy advertised features removed back in Phase 1-2
        (Forms, Drive) as if they still existed. The new copy is allowed to
        *mention* "Google Form" to reassure readers one isn't needed — what
        it must never do again is claim these as active tech/features."""
        resp = self.client.get('/')
        content = resp.content.decode()
        self.assertNotIn('Auto Google Forms', content)
        self.assertNotIn('Google Forms API', content)
        self.assertNotIn('Google Drive', content)
        self.assertNotIn('Drive API', content)
        self.assertNotIn('downloads resumes from Drive', content)

    def test_navbar_has_no_persistent_connect_google_button(self):
        """The button used to sit next to the user's identity on every page
        (a dedicated CSS class, google-connect-btn) — it's now a neutral
        'Integrations' link to the dashboard instead. 'Connect Google' text
        legitimately still appears elsewhere, inside the dashboard's
        Integrations panel — this checks the navbar specifically, not the
        whole page."""
        self.client.force_login(self.user)
        resp = self.client.get('/dashboard/')
        self.assertNotContains(resp, 'google-connect-btn')
        self.assertContains(resp, 'href="/dashboard/#integrations"')

    def test_dashboard_shows_integrations_panel_with_connect_links_when_disconnected(self):
        self.client.force_login(self.user)
        resp = self.client.get('/dashboard/')
        self.assertContains(resp, 'id="integrations"')
        self.assertContains(resp, 'Connect Google')  # inside the panel now, not the navbar
        self.assertContains(resp, 'Connect LinkedIn')

    def test_dashboard_shows_connected_badges_and_disconnect_when_connected(self):
        from hiring_app.models import GoogleOAuthToken, LinkedInOAuthToken
        GoogleOAuthToken.objects.create(user=self.user, token_json=json.dumps({'refresh_token': 'x'}))
        LinkedInOAuthToken.objects.create(user=self.user, token_json=json.dumps({
            'access_token': 'x', 'member_urn': 'y', 'expires_at': 9999999999,
        }))
        self.client.force_login(self.user)
        resp = self.client.get('/dashboard/')
        self.assertContains(resp, 'Connected', count=2)

    def test_email_not_configured_warning_hidden_in_debug(self):
        self.client.force_login(self.user)
        resp = self.client.get('/dashboard/')  # test settings run with DEBUG=True
        self.assertNotContains(resp, 'No email provider is configured')

    def test_email_not_configured_warning_shown_in_production_without_smtp_host(self):
        self.client.force_login(self.user)
        with override_settings(DEBUG=False, EMAIL_HOST=''):
            resp = self.client.get('/dashboard/')
        self.assertContains(resp, 'No email provider is configured')

    def test_email_not_configured_warning_hidden_once_smtp_host_is_set(self):
        self.client.force_login(self.user)
        with override_settings(DEBUG=False, EMAIL_HOST='smtp.resend.com'):
            resp = self.client.get('/dashboard/')
        self.assertNotContains(resp, 'No email provider is configured')
