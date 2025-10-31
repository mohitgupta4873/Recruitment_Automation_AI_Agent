

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from dateutil import tz

try:
    # config.py is intentionally not checked in
    import recruito_agent.config as config
except ImportError:
    # fallback so the repo still imports without secrets
    import recruito_agent.config_example as config


SCOPES_CORE = [
    "https://www.googleapis.com/auth/forms.body",
    "https://www.googleapis.com/auth/forms.responses.readonly",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
]

SCOPE_GMAIL_SEND = "https://www.googleapis.com/auth/gmail.send"


def get_timezone():
    """Return default tzinfo used for interview scheduling."""
    return tz.gettz(getattr(config, "DEFAULT_TZ", "Asia/Kolkata"))


def gmail_service():
    """
    Build a Gmail API client that is allowed to send email on behalf of the
    recruiting org. Uses a stored refresh token. Actual secrets live in config.py
    (not committed).
    """
    creds = Credentials(
        token=None,
        refresh_token=config.GMAIL_REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=config.GMAIL_CLIENT_ID,
        client_secret=config.GMAIL_CLIENT_SECRET,
        scopes=[SCOPE_GMAIL_SEND],
    )
    creds.refresh(Request())
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def google_clients_from_runtime_credentials(creds):
    """
    Given a google.oauth2.credentials.Credentials object (e.g. from your local OAuth flow),
    construct service clients for Forms / Sheets / Drive.

    In local/dev you’d obtain `creds` via InstalledAppFlow and NOT commit token.json.
    """
    forms = build("forms", "v1", credentials=creds, cache_discovery=False)
    sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)
    drive = build("drive", "v3", credentials=creds, cache_discovery=False)
    return {"forms": forms, "sheets": sheets, "drive": drive}
