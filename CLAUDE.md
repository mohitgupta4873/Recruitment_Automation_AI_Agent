# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Django app that automates an end-to-end hiring workflow: generate a JD with Gemini → launch a campaign with its own public apply page (optionally with a Google Sheet for tracking, and optionally cross-posted to the recruiter's own LinkedIn feed) → candidates apply directly with a resume upload, which is scored against AI-derived keywords for the role → send Google Calendar interview invites → send offer/rejection emails and log outcomes. Google (Sheets export, Gmail send) and LinkedIn (cross-post) are both optional throughout — every step also works through Django's own email backend when Google isn't connected, and campaigns launch fine with no LinkedIn connection at all. Invites and outcomes run as background Celery tasks, not inline in the request. Candidate resumes are auto-purged N days after a campaign closes, and a recruiter can permanently delete their own account (and everything owned by it) from their dashboard.

There is effectively one Django app, `hiring_app`, inside the project `my_hiring_project`. Almost all business logic lives in `hiring_app/services.py` (Google/Gemini calls) and `hiring_app/models.py` (persistence). `hiring_app/views.py` is a thin controller layer over both.

## Commands

```bash
# Activate the venv first (Windows). NOTE: the live venv is .venv, not venv/ —
# the venv/ directory in the repo root is stale and missing dependencies.
.\.venv\Scripts\activate

# Install deps (all versions are pinned exactly)
pip install -r requirements.txt

# Run the dev server
python manage.py runserver

# Run a real Celery worker (optional — only needed to test the actual async
# path; with no REDIS_URL set locally, .delay() runs eagerly in-process, so
# `runserver` alone is enough for normal development)
celery -A my_hiring_project worker --loglevel=info

# Run Celery beat (optional — only needed to test the daily retention purge
# actually firing on schedule; see hiring_app/tasks.py:purge_expired_resumes
# and my_hiring_project/celery.py's beat_schedule)
celery -A my_hiring_project beat --loglevel=info

# DB migrations
python manage.py makemigrations
python manage.py migrate

# Run tests — hiring_app/tests.py covers Phase 0 security hardening (method
# guards, password policy, recipient validation), Phase 1 (ownership,
# encryption), Phase 2 (apply-page validation, scoring), Phase 3
# (background-task idempotency), Phase 4 (resume-file cleanup on delete,
# retention purge, account deletion, legal pages), and the LinkedIn
# cross-post feature (OAuth flow, opt-in posting, best-effort failure
# handling). File storage under test is redirected to a temp dir wherever a
# test writes a real Candidate.resume file (ApplyPageTests,
# ResumeRetentionTests, AccountDeletionTests) — don't remove those
# overrides, or running the suite writes real files under media/resumes/.
# Celery tasks run eagerly under the test runner (settings.py: `if
# TESTING`) — no broker needed.
python manage.py test

# Django's own checks. The --deploy variant is the pre-launch gate and must
# come back clean with production env vars set.
python manage.py check
DEBUG=False REDIS_URL=... ALLOWED_HOSTS=... python manage.py check --deploy
```

There is no separate lint/format/build tooling configured (no eslint/black/flake8 config in the repo).

**Required env vars** (see `.env.example`): `SECRET_KEY` has no default and the app
refuses to boot without it. `REDIS_URL` is mandatory whenever `DEBUG=False` —
settings raises `ImproperlyConfigured` otherwise, because django-ratelimit needs a
shared cache with atomic increment or login/register are effectively unthrottled.
`FIELD_ENCRYPTION_KEY` is the same pattern, guarding `GoogleOAuthToken.token_json`
(see Architecture below) — required outside `DEBUG`, derived deterministically from
`SECRET_KEY` in dev so it survives restarts without another env var to remember.

**Not enforced by a boot-time check, but just as required in practice: `EMAIL_HOST`
et al.** Google (Sheets/Gmail) is an optional, per-user, individually-connected
extra — invites and outcome emails are delivered through Django's own configured
`EMAIL_BACKEND` regardless of whether any recruiter ever connects Google (see
"LinkedIn cross-post"/"Google OAuth" below and `.env.example`'s Email section).
With `DEBUG=False` and no real SMTP provider configured, that backend has nothing
to actually deliver through — invites/outcomes "send" without error (Django's SMTP
backend just fails per-recipient, already swallowed by the per-candidate
try/except in `services.py`) but never arrive. Use a transactional provider
(Resend/SendGrid/SES), not Gmail SMTP, for real production volume — Gmail SMTP's
~500/day cap and cloud-IP deliverability issues make it a stopgap, not the
long-term answer, though it's a perfectly fine one when you don't yet own a
domain to verify with a transactional provider (see below).

`EMAIL_HOST` is read regardless of `DEBUG` (not just outside it, as it used to
be) specifically so local dev can opt into real sends without flipping
`DEBUG=False` — which would also demand `REDIS_URL`/`FIELD_ENCRYPTION_KEY` and
break plain-HTTP `runserver` access via `SECURE_SSL_REDIRECT`. With `DEBUG=True`
and `EMAIL_HOST` unset (the common case), the console backend is still the
default — nobody gets switched to real delivery by accident; setting `EMAIL_HOST`
locally is a deliberate, explicit opt-in.

One-time step after cloning a repo that still has a `campaigns/` directory from
before Phase 1: `python manage.py import_legacy_campaigns` migrates it into the
database (see Architecture). Safe to re-run; already-imported campaigns are skipped.

### Deployment (Render/Railway-style)

- `build.sh` runs `pip install`, `collectstatic`, then `migrate` — this is the production build step, not something to run ad hoc in dev.
- `Procfile` runs gunicorn against `my_hiring_project.wsgi`. It does **not** run the Celery worker — that's a separate process (`celery -A my_hiring_project worker`), which `Procfile` alone (single-service) has no way to express.
- `render.yaml` (added Phase 3, extended Phase 4) declares the web service, a worker service, a beat service (`hireai-beat` — fires the daily retention purge, see Architecture below), plus managed Postgres and a Key Value (Redis) instance, as an optional Render Blueprint. It's additive — `build.sh`/`Procfile` are untouched and keep working exactly as they do now whether or not this Blueprint is ever adopted. **Not deployed or verified against a real Render account** — written from documentation; review every value before adopting it.
- Static files are served by WhiteNoise via the `STORAGES['staticfiles']` setting. The manifest backend is used outside DEBUG and outside the test runner (`USE_MANIFEST_STATIC` overrides), so after touching anything in `hiring_app/static/`, `collectstatic` needs to run before it will show up in a production-like run.

## Architecture

### State lives in Postgres, not on the filesystem (as of Phase 1)

Before Phase 1, campaign/candidate data lived in `campaigns/user_{id}/*.json` on
disk — which meant it was wiped on every deploy to Render/Railway (ephemeral
filesystem) and not shared between gunicorn workers. That layer
(`hiring_app/campaign_manager.py`, `HiringAutomator.load_state`/`save_state`,
`CampaignStateCorrupted`) is **deleted**. Everything now goes through the ORM:

1. **`hiring_app/models.py`**:
   - `GoogleOAuthToken` — one row per user, OAuth credentials. `token_json` is an
     `EncryptedTextField` (Fernet, key from `FIELD_ENCRYPTION_KEY`) — a leaked
     `DATABASE_URL` or backup no longer hands out live Google access. Transparent
     to Python code; only the raw column is ciphertext. Don't add a `.filter()`
     lookup on this field — Fernet ciphertext isn't deterministic, so equality
     lookups can't work, and nothing needs one today.
   - `Campaign` — one hiring campaign. UUID primary key, which is also the
     `campaign_id` URL segment (see Views below). `status` is `draft` / `active`
     / `completed`. `public_token` (unique, unguessable — `secrets.token_urlsafe`)
     is the *other* identifier, used only in the public `/apply/<public_token>/`
     URL — it doesn't reveal the campaign's internal UUID. `scoring_keywords`
     is the AI-derived keyword list resumes are scored against (Phase 2; see
     `HiringAutomator.generate_scoring_keywords`). `form_id`/`form_url`/
     `drive_qid`/`email_qid` are Phase-1-era Google Forms fields kept only for
     campaigns `import_legacy_campaigns` pulled in — new campaigns never
     populate them, there's no Form any more.
   - `Candidate` — one applicant to one `Campaign`, unique on `(campaign, email)`
     — a second application from the same address updates the existing row
     rather than creating a duplicate. `source` distinguishes Phase-2 apply-page
     candidates from Phase-1-imported Google-Form ones; `resume_status` (renamed
     from `download_status` in the Phase 2 migration — see below) generalizes
     the same way. `resume` is a `FileField` on `STORAGES['default']` (local
     disk today) — swapping to S3/R2 later is a storage-backend config change,
     not an application code change. There is still no view serving a resume to
     anyone but the campaign owner — see `views.view_resume` — and nothing
     deletes the file when a `Candidate` row is deleted; that's flagged for the
     retention-policy work in ROADMAP.md Phase 4, not handled today.

2. **Ownership is a database constraint, not a filesystem path convention.**
   Every view resolves a campaign via
   `get_object_or_404(Campaign, pk=campaign_id, owner=request.user)`
   (`views.py:_get_owned_campaign`) — a campaign belonging to another user 404s,
   it's never reachable. There is **no more session-based "active campaign"**:
   the URL (`/campaign/<uuid:campaign_id>/...`) is the only source of truth for
   which campaign a request is about, so two browser tabs on two different
   campaigns just work, which the old `request.session['active_campaign_id']`
   scheme could not do.

3. **`/agent/` is a convenience redirect, not a real page.** It resolves to the
   user's most recent non-draft campaign (falling back to their most recent
   draft, then creating one) and forwards to `/campaign/<id>/`. Nav links and
   the post-Google-connect redirect use it so they don't need to know which
   campaign is "current." Unlike the old `ensure_active_campaign`, it reuses an
   existing draft instead of minting a fresh "New Campaign" on every hit with
   no non-draft campaign — that's what let empty drafts accumulate before.

If you inherit a checkout that still has an old `campaigns/` directory, run
`python manage.py import_legacy_campaigns` once (see Commands above) before
relying on the dashboard being complete.

### `HiringAutomator` (`hiring_app/services.py`)

As of Phase 2, this wraps only Sheets and Gmail — **Forms and Drive integration is
gone entirely**, along with the restricted `drive` scope that required them. See
"Candidate intake" below for what replaced it. `SCOPES` is now just
`spreadsheets` + `gmail.send`, both *sensitive*, neither *restricted* — that's
what makes public OAuth verification possible without a paid CASA assessment.

Constructed per-request with the *current user's* Google credentials, or `None`
— `HiringAutomator(creds=...)`. Every method takes a `Campaign` (and, where
relevant, `Candidate` rows) and persists straight to the DB via the ORM.
**Google is optional everywhere**, not just absent-tolerant: `has_google` gates
whether Sheets export happens (silently skipped if not connected — never raises),
and `_sender_email`/`_send_plain_email`/`_send_email_with_ics` all fall back to
Django's configured `EMAIL_BACKEND` (`DEFAULT_FROM_EMAIL`) when there's no Gmail
connection, so invites and outcomes still go out. There is no more
`GoogleNotConnected` exception — nothing hard-requires Google any more, so
nothing needs to signal its absence as an error.

Key methods, roughly in workflow order:
- `generate_jd(role, experience)` — Gemini, JD text.
- `generate_scoring_keywords(role, jd_text)` — a second Gemini call, asked to
  return a strict JSON array of 8–15 role-relevant keywords from the *final*
  JD text. Parsed defensively (`_parse_keyword_response` strips a stray
  markdown fence, tolerates non-JSON) and **never raises** — falls back to
  `FALLBACK_KEYWORDS` (the old hardcoded 9-keyword list) on any failure, so a
  Gemini outage never blocks launching a campaign.
- `create_campaign(campaign, jd_text, post_to_linkedin=False, apply_url=None)` —
  stores the JD, calls the above, sets `status='active'`. If `has_google`,
  best-effort creates a tracking Sheet; if not, the campaign is still fully
  live through the apply page alone. `post_to_linkedin` is a separate,
  explicit per-launch opt-in — see "LinkedIn cross-post" below — silently
  ignored if `has_linkedin` is False rather than erroring.
- `process_application(campaign, cleaned_data)` — the apply-page equivalent of
  the old `sync_responses`: extracts text from the uploaded PDF in memory,
  scores it against `campaign.scoring_keywords` (or `FALLBACK_KEYWORDS`), and
  `update_or_create`s the `Candidate` row keyed on email — a second
  application from the same address updates in place. Appends a row to the
  Sheet if one exists and Google is connected.
- `send_invites(campaign, candidates, ...)` — `.ics` invites, stamps
  `Candidate.invite_sent_at`.
- `send_outcomes(campaign, hired_candidate_ids)` — offer/rejection emails,
  stamps `Candidate.outcome_type`/`outcome_sent_at`, logs to the Sheet's
  "Outcomes" tab if there is one.

`_score_resume(text, keywords)` matches on `\bkeyword\b` (word boundaries, case
insensitive), not substring containment — the old check matched `"java"` inside
`"javascript"` and `"api"` inside `"therapist"`. Score is normalised to 0–100
(`matched / total`, rounded); `Candidate.matched_terms` records which keywords
hit, shown in the UI instead of (or alongside) the raw text preview. Note:
`Candidate` rows imported by `import_legacy_campaigns` still carry their old
0–9 raw hit-count in `score` — there was no attempt to renormalise historical
data onto the new 0–100 scale, so old rows will display as a low percentage.

### Candidate intake: the public apply page (Phase 2)

`views.apply` at `/apply/<public_token>/` is unauthenticated and takes the
place of the Google Form entirely. `Campaign.public_token` alone is the access
control — unguessable, and doesn't leak the campaign's UUID. Gated on
`campaign.accepting_applications` (i.e. `status == 'active'`); draft/completed
campaigns render `apply_closed.html` instead of the form. Rate-limited
`10/h` per IP on POST.

`hiring_app/forms.py:ApplicationForm` validates the upload before anything
else touches it: extension, a hard `MAX_RESUME_BYTES` (5 MB) size cap, and a
PDF magic-byte check (`%PDF-`) — extension alone is trivially spoofed by
renaming any file. `process_application` (above) does the actual scoring and
persistence.

Resumes are served back to the recruiter (never to anyone else) through
`views.view_resume`, ownership-checked the same way every campaign view is —
without it, resumes uploaded through the apply page would be write-only:
saved, scored, and permanently unreachable through the UI.

### LinkedIn cross-post (optional, per-launch opt-in)

A recruiter can optionally connect LinkedIn and, at the moment they launch a
campaign, check a box to also post that campaign's JD to their own LinkedIn
feed. This existed once as a "paste a raw UGC access token into a form field"
feature, was removed for exactly that reason (no real user has such a token
to paste, and persisting one that way is a worse security posture than not
having the feature at all), and has been reinstated here as proper per-user
OAuth — the same shape as Google's connection, not the old shortcut.

- **`LinkedInOAuthToken`** (`models.py`) — one row per user, `token_json`
  encrypted the same way as `GoogleOAuthToken` (holds `access_token`,
  `expires_at`, `member_urn`). No refresh token: the scopes this app
  requests (`openid profile w_member_social`) don't grant one, so
  `services.get_user_linkedin_creds` treats an expired token as "not
  connected" rather than erroring — the fix is reconnecting via
  `linkedin_connect`, not a silent refresh.
- **`views.linkedin_connect`/`linkedin_oauth_callback`/`linkedin_disconnect`**
  — a separate OAuth flow from Google's, built on plain `requests` calls
  (no SDK dependency added for one provider). Uses a `state` value
  round-tripped through the session for CSRF protection; no PKCE, since
  LinkedIn's flow doesn't require it the way Google's does. `linkedin_connect`
  fails soft (renders `linkedin_connect.html` with an error) if
  `LINKEDIN_CLIENT_ID`/`LINKEDIN_CLIENT_SECRET` aren't set — the feature is
  entirely absent, not broken, when unconfigured. Unlike Google, there is no
  public revoke endpoint to call on disconnect; `linkedin_disconnect` says so
  in its own success message rather than implying a full revoke happened.
- **`HiringAutomator.post_jd_to_linkedin(campaign, jd_text, apply_url)`** —
  posts via the UGC Posts API, best-effort exactly like the Sheets export:
  never raises, and a failure never blocks or un-launches a campaign. Sets
  `Campaign.linkedin_post_id` on success (not saved directly — `create_campaign`'s
  own `save()` covers it, matching how `sheet_id`/`sheet_url` are handled).
  `Campaign.linkedin_post_url` (a model property) builds a shareable feed
  link from that ID for the UI.
- **The checkbox itself is opt-in per launch, not implied by having a
  connection** — connecting once shouldn't mean every future campaign gets
  posted without asking again. `agent.html`'s launch form only renders the
  checkbox when `has_linkedin` is true (a currently-valid connection); when
  it's not, a "Connect LinkedIn" link is shown instead. `views.create_campaign`
  gates its post-launch messaging on `automator.has_linkedin`, not just
  whether the checkbox was submitted — otherwise a stale form resubmission
  with the box checked but no real connection would misreport "posting to
  LinkedIn failed" for an attempt that was never actually made.
- **Not re-verified**: whether `w_member_social` (the "Share on LinkedIn"
  product) is still self-serve-approved for a new LinkedIn Developer app, or
  requires additional review, was not re-checked against LinkedIn's current
  developer portal policy when this was written — verify that before relying
  on this in production. `LINKEDIN_CLIENT_ID`/`LINKEDIN_CLIENT_SECRET` blank
  disables the feature entirely rather than erroring either way.
- **`views.linkedin_connect_manual`** (added after the above) — a second,
  manual path into the exact same `LinkedInOAuthToken` row: paste an access
  token + member ID/URN generated by hand from the LinkedIn Developer
  Portal's own Token Generator tool (app → Auth → OAuth 2.0 tools), instead
  of going through `linkedin_connect`'s redirect-based consent screen. This
  sidesteps LinkedIn's own OAuth review/approval gating on the client
  entirely, since generating a token for yourself via the portal is a
  developer action, not a public consent flow — plausibly why this "just
  worked" for a single self-hosted operator via the old paste-a-token UI
  before it was pulled in Phase 2. Reinstated deliberately as a *second*
  path alongside the OAuth flow, not a replacement — the OAuth flow is what
  this app would need for real multi-tenant public signups (Phase 5); this
  manual one is scoped to "I already have developer access to my own
  LinkedIn app." Normalizes a bare member ID into `urn:li:person:<id>` if
  it isn't already a full `urn:li:...` string; assumes the same ~60-day
  expiry the OAuth path defaults to, since the Token Generator doesn't hand
  back a parseable one. Feeds `get_user_linkedin_creds`/`post_jd_to_linkedin`
  identically either way — one downstream code path regardless of how the
  token got there.

### Google OAuth (strictly per-user, and optional)

Each user authorizes their own Google account (Sheets/Gmail scopes are defined once in `SCOPES` in `services.py` — narrowed in Phase 2, see above). Credential resolution in `views.py`:

- `services.get_user_google_creds(user)` (moved out of `views.py` in Phase 3 so `hiring_app/tasks.py` can call it without importing `views.py`, which imports `tasks.py` to enqueue) loads the per-user `GoogleOAuthToken` DB row, auto-refreshing and re-saving if expired.
- If no DB row exists it returns `None`, and `HiringAutomator` runs in its no-Google mode — Sheets export silently skipped, email sent through Django's backend instead of Gmail (see `HiringAutomator` above). **There is deliberately no fallback to a token file on disk.** The old `token.json` fallback meant any user who had not connected Google silently operated as the deployer — full Drive access and send-as-Gmail on someone else's account. `token.json` and `generate_token.py` have been deleted; do not reintroduce them.
- `google_disconnect` revokes the grant at Google (`oauth2.googleapis.com/revoke`) before deleting the row, so the app also disappears from the user's Google permissions page.

`_build_oauth_flow` reads client secrets either from the `GOOGLE_CLIENT_SECRETS` env var (JSON string, used in production) or from `client_secrets.json` on disk (local dev) — same dual-source pattern as the token. The OAuth flow explicitly threads a PKCE `code_verifier` through the session between `google_connect` and `google_oauth_callback`, because `google-auth-oauthlib` generates a fresh one per `Flow` instance and the callback builds a separate `Flow` object than the one that started the flow (see the docstring on `_build_oauth_flow`) — don't remove that session round-trip when touching the OAuth views.

### Settings (`my_hiring_project/settings.py`)

Uses `django-environ`, reading `.env` in dev and real env vars in production (Render). `DEBUG` defaults to **`False`**; local dev opts in via `.env`. Database defaults to local SQLite, switching to `DATABASE_URL` (Postgres) automatically when that env var is present.

Logging goes to **stdout only** in production — the container filesystem is ephemeral, so rotating files were wiped every deploy and invisible to log aggregation, and creating `logs/` at import time crashes on a read-only filesystem. The rotating file handlers still exist under `DEBUG`. The `hiring_app` logger is the one used throughout `views.py`/`services.py`; **never log candidate emails or resume text through it** — that is applicant PII.

A `if not DEBUG:` block sets `SECURE_PROXY_SSL_HEADER`, `SECURE_SSL_REDIRECT` and HSTS. The proxy header is load-bearing, not cosmetic: without it `request.is_secure()` is `False` behind Render's TLS terminator, so `views.py` builds an `http://` OAuth `redirect_uri` that Google rejects, and `SECURE_SSL_REDIRECT` would infinite-loop.

### Background tasks (`hiring_app/tasks.py`, `my_hiring_project/celery.py`)

Interview invites and outcome emails run as Celery tasks (`send_invites_task`,
`send_outcomes_task`) rather than inline in the request — both used to run
synchronously against gunicorn's 120s timeout, with no guard against
re-sending to a candidate who'd already been emailed if a mid-batch crash
forced a re-run.

Idempotency is **DB-level, not exception-based**: each task re-queries for
candidates whose `invite_sent_at`/`outcome_sent_at` is still unset immediately
before running, so re-running the *same* task (a retry, a redelivered message
after a worker crash, or clicking the button twice) only ever processes
whoever didn't get through last time. `HiringAutomator.send_invites`/
`send_outcomes` already wrap each individual candidate's send in its own
try/except (Phase 0 — one bounced address shouldn't fail the whole batch), so
a single Google API error never propagates up to Celery as a task failure;
that's why the tasks don't use `autoretry_for=(HttpError,)` — there's nothing
at that level to catch. What `acks_late=True` is actually for: if the
*worker process* dies mid-task (OOM, deploy restart, SIGKILL), the broker
redelivers the message and the task runs again — combined with the DB-level
filtering, that redelivery is safe.

Broker/backend reuse `REDIS_URL` — no new required env var; production
already needs it for the rate-limit cache (Phase 0). Locally, with no
`REDIS_URL` set, `CELERY_TASK_ALWAYS_EAGER` is on and `.delay()` runs
synchronously in-process — `manage.py runserver` alone is enough to develop
against; a real worker is only needed to exercise the actual async path (or
under the test runner, where eager mode is forced regardless of `REDIS_URL`
via `TESTING`, so tests never need a real broker).

Views (`send_invites`, `send_outcomes`) enqueue and redirect immediately,
appending `?watch=invites` or `?watch=outcomes` to the URL. `agent.html`'s JS
notices that param and polls `GET /campaign/<id>/status/`
(`views.campaign_status`) every few seconds, updating a progress banner until
the counts catch up. That status endpoint reports **DB state directly** — how
many candidates actually have the timestamp set — rather than tracking Celery
task IDs; the DB is the source of truth either way, and this avoids needing a
result backend that outlives a single poll or a model field to stash a task
ID in.

Not yet verified against a real broker: the specific "kill a live worker
process mid-batch and confirm the redelivered task doesn't double-send" test
described in ROADMAP.md Phase 3 needs a running Redis + separate worker
process, which wasn't available in the environment this was built in (no
Docker daemon running). What *is* verified (`hiring_app/tests.py:
BackgroundTaskTests`) is that re-invoking a task for work already completed
is a no-op — the actual idempotency guarantee this phase depends on. Do that
worker-kill test for real before relying on it under production load.

### PII, retention, and account deletion (Phase 4)

The app processes resumes belonging to candidates who are not its users, so this phase
is about giving that data a lifecycle rather than letting it accumulate forever.

- **Legal pages.** `/privacy/` and `/terms/` (`views.privacy_policy`/`terms_of_service`,
  `templates/hiring_app/privacy.html`/`terms.html`) are public, linked from `base.html`'s
  footer and from the apply page. Both are explicitly marked as drafts pending real legal
  review in their own text — accurate about what the app does today, but not a substitute
  for a lawyer, especially before hiring in the EU (AI Act) or NYC (Local Law 144); see
  the "Automated scoring" section of the privacy page. A hosted privacy policy is also a
  hard requirement for the Google OAuth verification in Phase 5.
- **Cookie notice** lives inside the privacy policy rather than as a separate consent
  banner — the app sets exactly two cookies (session, CSRF), both strictly necessary, and
  strictly-necessary cookies don't require consent under GDPR/ePrivacy. Adding a banner
  for cookies that don't need one would be theater, not compliance.
- **Consent** on `/apply/` was already collected as of Phase 2 (`Candidate.consent_at`,
  stamped in `HiringAutomator.process_application`) — this phase only improved the
  *notice* text above the checkbox to actually name who's processing the data (the
  campaign owner, with HireAI as their processor), the retention window
  (`campaign.retention_days`), and a deletion contact (`settings.PRIVACY_CONTACT_EMAIL`),
  linking through to the privacy policy for the rest.
- **Retention.** `Campaign.retention_days` (default 180) and `Campaign.closed_at` (stamped
  once, the first time `tasks.send_outcomes_task` sets `status='completed'` — not on every
  save) drive `tasks.purge_expired_resumes`: a daily Celery Beat task that, for every
  completed campaign past `closed_at + retention_days`, clears each candidate's resume
  file and `text_preview` — never the `Candidate` row itself. Beat schedule lives in
  `my_hiring_project/celery.py` (`app.conf.beat_schedule`); it needs its own
  `celery -A my_hiring_project beat` process, separate from the worker (see `render.yaml`'s
  `hireai-beat` service) — a worker alone never fires scheduled tasks.
- **Resume files no longer outlive their row.** Deleting a `Candidate` never used to touch
  its file in storage — `FileField` doesn't do that on its own — so it was orphaned under
  `media/resumes/<campaign-id>/` forever. A `post_delete` signal on `Candidate`
  (`hiring_app/models.py`) now deletes the file whenever the row goes, whatever the
  path: a direct admin delete, a cascaded `Campaign.delete()`, or a cascaded account
  deletion (below). Registering that signal also stops Django's cascade-delete
  `Collector` from "fast-deleting" `Candidate` rows in bulk (fast-delete skips signals
  entirely), so every cascade now goes through one row at a time — the correctness this
  buys is worth that cost at this app's scale.
- **Account deletion.** `views.delete_account_confirm` (GET, shows exact counts) and
  `views.delete_account` (POST, typed `DELETE` confirmation — same pattern as
  `send_outcomes`) let a recruiter permanently remove their own account:
  `_revoke_google_token` (Phase 0) revokes any connected Google grant, then
  `request.user.delete()` cascades through every owned `Campaign` → `Candidate` →
  resume file (via the signal above) and the user's `GoogleOAuthToken` row. `logout()`
  runs before the delete so the session is invalidated even though the `User` row it
  pointed at no longer exists a moment later.
- **Candidate erasure requests** (someone who applied asks to be forgotten, without
  deleting the recruiter's whole account) are serviced through Django admin:
  `hiring_app/admin.py` registers `Campaign` and `Candidate` with `search_fields`
  including `email`, specifically so a candidate can be found and deleted (triggering the
  same file-cleanup signal) without a bespoke UI for what should be a rare request.
  `GoogleOAuthToken` is deliberately **not** registered — it's encrypted OAuth credentials
  with no legitimate reason to browse from admin.

### Error reporting to the user

Views report outcomes through `django.contrib.messages`, rendered by the block in `base.html`. Do not go back to the old pattern of `except Exception: logger.error(...); redirect('agent')` — that made a failed campaign launch look identical to a successful one. All state-changing views are `@require_POST`; `send_invites`/`send_outcomes` validate submitted addresses against the campaign's own candidate list via `_validate_recipients` before anything reaches the Gmail API, and `send_outcomes` requires a typed confirmation because it emails every candidate irreversibly.
