Recruitment Automation AI Agent 🤖

A full-stack Django application that automates the end-to-end hiring lifecycle: draft a job description with Google Gemini, launch a campaign with its own public application page, let candidates apply directly with a resume upload, score them automatically against AI-derived keywords for the role, schedule interviews, and send offer/rejection outcomes — all from one dashboard. Google (Sheets export, Gmail send) is entirely optional; everything works without it.

📸 Dashboard Preview

<img width="2770" height="1062" alt="Screenshot 2025-11-29 155736" src="https://github.com/user-attachments/assets/97a176d7-70c4-4402-a3f0-7d50d2ecfa74" />

Figure 1: AI Job Description Generation and Campaign Launch

<img width="2745" height="1388" alt="Screenshot 2025-11-29 155742" src="https://github.com/user-attachments/assets/db1840c8-d9c9-4d91-a51e-3f5925f58a18" />

Figure 2: Candidate scoring and interview scheduling (screenshots predate the move to a self-hosted apply page — the core dashboard layout is unchanged)

🔄 The Full Automation Flow

1. Smart JD Drafting ✍️

Input: The recruiter enters a Role Title (e.g., "Backend Engineer") and Required Experience (e.g., "2 years").

AI Action: Google Gemini (Flash-Lite model) generates a structured, professional Job Description instantly.

Edit: The recruiter can tweak the JD before finalizing.

2. Campaign Launch 🚀

One-Click Deployment: Launching a campaign generates a public application link (`/apply/<token>/`) hosted by the app itself — no Google Form involved. If the recruiter has connected Google, a tracking Sheet is also created automatically (optional).

Scoring setup: Gemini reads the final JD and derives a short list of role-relevant skills/keywords, used to score every applicant automatically.

Result: A live link to share with candidates immediately.

3. Applications & AI Scoring 🧠

Direct upload: Candidates apply on the app's own page — name, experience, a short pitch, and a resume PDF (validated for type and size).

AI Analysis: The resume is parsed and scored against the role's derived keywords, with the matched skills shown alongside the score — not just a raw number.

Display: Candidates appear on the dashboard immediately as they apply, with their score, matched skills, and a link to their resume.

4. Automated Scheduling 📅

Selection: The recruiter selects promising candidates via checkboxes.

Action: The app sends personalized calendar invites (`.ics` files) for the specified interview time — via Gmail if Google is connected, or the app's own email sender otherwise.

5. Final Outcomes ⚖️

Decision: After interviews, the recruiter selects candidates to hire. This step requires typing a confirmation, since it emails every candidate and can't be undone.

Bulk Processing: Selected candidates receive an offer email; everyone else receives a polite rejection.

Logging: If a tracking Sheet exists, outcomes are logged to its "Outcomes" tab.

🛠️ Tech Stack

Backend: Django (Python)

Database: PostgreSQL in production (SQLite for local dev)

AI Model: Google Gemini (`gemini-2.5-flash-lite`) — JD drafting and scoring-keyword extraction

Auth: Django's own accounts (username/password, password reset via email) — Google is a separate, optional per-user connection

Optional Google integration: Sheets API (campaign export) and Gmail API (sending as the recruiter), via per-user OAuth 2.0 — encrypted at rest, never required to use the app

Rate limiting: `django-ratelimit`, backed by Redis in production

⚙️ Installation & Setup

1. Clone the repository

```bash
git clone https://github.com/mohitgupta4873/Recruitment_Automation_AI_Agent.git
cd Recruitment_Automation_AI_Agent
```

2. Set up a virtual environment

```bash
python -m venv .venv
# Windows
.\.venv\Scripts\activate
# Mac/Linux
source .venv/bin/activate
```

3. Install dependencies

```bash
pip install -r requirements.txt
```

4. Configure environment variables

```bash
cp .env.example .env
```

At minimum, set `SECRET_KEY` and `GEMINI_API_KEY` in `.env`. Everything else has a sane local-dev default — see the comments in `.env.example` for what's required outside of `DEBUG=True` (a `REDIS_URL` and a `FIELD_ENCRYPTION_KEY` are both mandatory in production).

5. Run migrations and start the server

```bash
python manage.py migrate
python manage.py runserver
```

Visit http://127.0.0.1:8000/, register an account, and start a campaign. Connecting Google is optional and can be done later from the dashboard ("Connect Google") — it unlocks Sheets export and sending email as your own Gmail address instead of the app's default sender.

Interview invites and outcome emails run as background tasks (Celery). With no `REDIS_URL` set, they run synchronously in-process instead — `runserver` alone is enough for normal local development. To actually exercise the background path, set `REDIS_URL` in `.env` and run a worker alongside the server:

```bash
celery -A my_hiring_project worker --loglevel=info
```

6. (Optional) Google OAuth for local development

If you want to test the Google integration locally: download OAuth 2.0 Client credentials from Google Cloud Console as `client_secrets.json` and place it in the repo root (this is read automatically when `GOOGLE_CLIENT_SECRETS` isn't set in `.env`). No separate token-generation script is needed — connecting happens through the app's own "Connect Google" button, per user.

🔒 Security

- Secrets (`SECRET_KEY`, API keys, `client_secrets.json`, `.env`, the local SQLite DB) are never committed — see `.gitignore`.
- Each user's Google OAuth token is encrypted at rest and scoped to that user only; there is no shared fallback credential.
- Passwords are validated against Django's standard strength rules; sessions/CSRF use Django's built-in protections throughout.
- Resume uploads are validated for file type (PDF magic bytes, not just the extension) and capped in size before being parsed.
- State-changing actions require POST and, for irreversible bulk actions (sending offers/rejections to an entire candidate pool), a typed confirmation.
- Rate limiting is enforced on login, registration, and the public application page.

🧪 Tests

```bash
python manage.py test
```

📍 Status

This app has been through several rounds of production-readiness hardening (moving campaign data into Postgres, replacing the Google Form with a self-hosted application page, narrowing Google OAuth scopes, moving interview invites and outcome emails to a background task queue). Not yet in place: a privacy policy, a data retention policy, and account/candidate deletion — all real requirements given the app handles resumes belonging to people who aren't its users.
