Recruitment Automation AI Agent 🤖

A full-stack application that automates the end-to-end hiring lifecycle. This agent leverages Google Gemini AI for intelligence and the Google Workspace Ecosystem (Drive, Forms, Sheets, Gmail, Calendar) for backend operations, creating a seamless experience for recruiters.

📸 Dashboard Preview

<img width="2770" height="1062" alt="Screenshot 2025-11-29 155736" src="https://github.com/user-attachments/assets/97a176d7-70c4-4402-a3f0-7d50d2ecfa74" />


Figure 1: AI Job Description Generation and Campaign Launch

<img width="2745" height="1388" alt="Screenshot 2025-11-29 155742" src="https://github.com/user-attachments/assets/db1840c8-d9c9-4d91-a51e-3f5925f58a18" />

Figure 2: Candidate Scoring, Syncing, and Interview Scheduling

🔄 The Full Automation Flow

This application replaces manual hiring tasks with a streamlined 5-step workflow:

1. Smart JD Drafting ✍️

Input: The recruiter enters a Role Title (e.g., "Backend Engineer") and Required Experience (e.g., "2 years").

AI Action: Google Gemini (Flash-Lite model) generates a structured, professional Job Description instantly.

Edit: The recruiter can tweak the JD before finalizing.

2. Campaign Launch 🚀

One-Click Deployment: The app automatically interacts with Google APIs to:

Create a dedicated Google Sheet for tracking.

Create a Google Form pre-filled with the JD and resume upload fields.

(Optional) Post the opening directly to LinkedIn with the form link.

Result: You get a live link to share with candidates immediately.

3. Sync & AI Scoring 🧠

Data Aggregation: When candidates apply, the app pulls responses from Google Forms.

Resume Parsing: It automatically downloads PDF resumes from Google Drive.

AI Analysis: The system reads the PDF text and scores the candidate based on keyword matching and relevance to the role.

Display: Candidates appear in the dashboard with their email, AI score, and a resume preview.

4. Automated Scheduling 📅

Selection: The recruiter selects promising candidates via checkboxes.

Action: The app sends personalized Google Calendar invites (ICS files) via Gmail to the selected candidates for the specified interview time.

5. Final Outcomes ⚖️

Decision: After interviews, the recruiter selects candidates to HIRE.

Bulk Processing:

Selected: Receive an automated "Offer/Next Steps" email.

Unselected: Receive a polite "Rejection" email.

Logging: All decisions are permanently logged in a specific "Outcomes" tab in the Google Sheet.

🛠️ Tech Stack

Backend: Django (Python)

AI Model: Google Gemini 1.5 Flash Lite

Database: Google Sheets (acting as the persistent data layer)

File Storage: Google Drive (for Resumes)

Authentication: OAuth 2.0 (Google Cloud Platform)

APIs Used:

Gmail API

Google Calendar API

Google Drive API

Google Sheets API

Google Forms API

LinkedIn API

⚙️ Installation & Setup

1. Clone the Repository

git clone [https://github.com/mohitgupta4873/Recruitment_Automation_AI_Agent.git](https://github.com/mohitgupta4873/Recruitment_Automation_AI_Agent.git)
cd Recruitment_Automation_AI_Agent


2. Set up Virtual Environment

python -m venv venv
# Windows
.\venv\Scripts\activate
# Mac/Linux
source venv/bin/activate


3. Install Dependencies

pip install -r requirements.txt


4. Environment Variables

Create a .env file in the root directory and add your Google Gemini API Key:

GEMINI_API_KEY=your_api_key_here


5. Google OAuth Setup

Download your OAuth 2.0 Client Credentials (client_secrets.json) from Google Cloud Console.

Place the file in the root directory.

Run the token generator script to authenticate locally:

python generate_token.py


Follow the browser prompt to allow access. This creates a token.json file.

6. Run the Server

python manage.py runserver


Visit http://127.0.0.1:8000/ to start hiring!

🔒 Security Note

This project uses a .gitignore file to ensure sensitive credentials (token.json, client_secrets.json, .env) and candidate data (cv_pdfs/) are never uploaded to GitHub.
