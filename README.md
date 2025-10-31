# Recruito Agent ()

This project is an **AI-augmented recruiting assistant**.  
It automates a full lightweight hiring funnel for an early-career engineering role.

## What it does

### 1. Job Description generator
- Generates an inclusive JD for a given role (0–2 YOE, backend engineer style).
- Can optionally call an LLM (e.g. Gemini / GPT) to draft or refine.
- Saved as markdown.

### 2. Auto-sourcing funnel (Google Workspace automation)
- Creates a Google Sheet to track applicants.
- Creates a Google Form with:
  - Name
  - Email
  - YOE
  - Motivation / “Why are you a fit?”
  - Resume (Google Drive link to PDF)
  - LinkedIn URL
- Injects the JD into the form description so candidates see the role context.
- Captures the form responder URL.

### 3. Resume ingestion + shortlist
- Reads form responses via the Google Forms API.
- For each applicant:
  - Extracts their resume file ID from a shared Drive link.
  - Downloads their PDF from Google Drive.
  - Extracts text from the PDF.
  - Tries to infer contact email if missing.
  - Scores them using simple keyword heuristics
    (e.g. `python`, `rest`, `docker`, `aws`, etc.).
- Logs all applications to a `Raw` tab in the Sheet.
- Writes the top N candidates into a `Shortlist` tab with name/email/score.

### 4. Interview scheduling + calendar invites
- Takes the shortlist and auto-allocates interview slots (e.g. 45 min + 15 min gap).
- Builds `.ics` calendar invites with a unique Google Meet link per candidate.
- Sends each candidate an email + ICS attachment using the Gmail API.
- Writes an `Invited` tab (ID, email, slot time, status).

### 5. Post-interview outcomes
- After interviews, you choose who is selected.
- Automatically:
  - Sends acceptance emails to selected candidates.
  - Sends polite regret emails to others.
  - Logs the outcome (+ Gmail message IDs) into an `Outcome` tab.

## Key modules

- `jd_generator.py`  
  Generate / refine the JD.

- `form_and_sheet.py`  
  Stand up a Google Form + Google Sheet with the JD and all questions.

- `ingest_and_rank.py`  
  Pull responses, download resumes, parse PDFs, extract skills, rank, and write to Sheets.

- `scheduler.py`  
  Build interview slots and construct `.ics` calendar invites.

- `mailer.py`  
  Send those invites to candidates via Gmail API.

- `outcomes.py`  
  Send acceptance / regret emails and log outcomes.

- `auth.py`  
  Central place to build authenticated Google clients.  
  In real usage, OAuth refresh tokens and API keys live in `config.py`
  (which is **not** committed). The repo only includes `config_example.py`.

## Security notes

- This repo intentionally does **not** contain:
  - OAuth tokens
  - Refresh tokens
  - Gmail client secrets
  - API keys
  - Candidate PII / resumes

- `config_example.py` documents what secrets are expected.
  You create `config.py` locally with real credentials and never commit it.

## Why this matters

This project shows:
- Automated high-volume candidate intake (Forms)
- Structured candidate evaluation (resume parsing & scoring)
- Automated scheduling (calendar invites via ICS)
- Automated communication (Gmail API for invites, accepts, regrets)
- Sheet-based audit trail for every stage

In a real setting this reduces manual recruiter work:
- No copy/paste CVs
- No back-and-forth scheduling emails
- Instant shortlists for hiring managers
- Clean, consistent candidate communication
