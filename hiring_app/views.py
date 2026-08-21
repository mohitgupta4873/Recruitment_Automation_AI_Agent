import os
import json
import logging

from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.conf import settings
from django.http import HttpResponseServerError
from django_ratelimit.decorators import ratelimit

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest
from google_auth_oauthlib.flow import Flow

from .services import HiringAutomator, SCOPES
from .models import GoogleOAuthToken
from .campaign_manager import (
    load_index, get_campaign_meta, upsert_campaign_meta,
    sync_index_from_state, campaign_state_path,
    get_active_campaign_id, set_active_campaign_id,
    create_new_campaign, ensure_active_campaign,
)

logger = logging.getLogger('hiring_app')


# ─────────────────────────────────────────────────────────────
# Google OAuth helpers
# ─────────────────────────────────────────────────────────────

def _build_oauth_flow(request, state=None, code_verifier=None):
    """Build a google_auth_oauthlib Flow from env var or file.

    code_verifier must be passed in on the callback leg (retrieved from the
    session) so it matches the PKCE code_challenge sent on the initial
    authorization request — google-auth-oauthlib auto-generates a fresh
    code_verifier per Flow instance otherwise, and since the callback builds
    a separate Flow object from the one that started the flow, the token
    exchange would be missing it (Google error: "Missing code verifier").
    """
    redirect_uri = request.build_absolute_uri('/google/oauth2callback/')
    client_secrets_json = getattr(settings, 'GOOGLE_CLIENT_SECRETS', '')

    if client_secrets_json:
        # Production: secrets stored as JSON env var
        client_config = json.loads(client_secrets_json)
        flow = Flow.from_client_config(client_config, scopes=SCOPES, state=state, code_verifier=code_verifier)
    else:
        # Development: use client_secrets.json file
        secrets_file = os.path.join(settings.BASE_DIR, 'client_secrets.json')
        flow = Flow.from_client_secrets_file(secrets_file, scopes=SCOPES, state=state, code_verifier=code_verifier)

    flow.redirect_uri = redirect_uri
    return flow


def _get_user_google_creds(user):
    """
    Load & auto-refresh Google OAuth credentials for a user from DB.
    Returns Credentials object or None (falls back to token.json in HiringAutomator).
    """
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
                logger.info(f"Refreshed Google token for user {user.username}")
            except Exception as e:
                logger.error(f"Failed to refresh Google token for {user.username}: {e}")
                return None
        return creds
    except GoogleOAuthToken.DoesNotExist:
        return None  # HiringAutomator will fall back to token.json
    except Exception as e:
        logger.error(f"Error loading Google creds for {user.username}: {e}")
        return None


def _get_automator_for_active(request):
    """Build HiringAutomator for the active campaign, injecting per-user Google creds."""
    campaign_id, state_path = ensure_active_campaign(request)
    token_path = os.path.join(settings.BASE_DIR, 'token.json')
    creds = _get_user_google_creds(request.user)
    automator = HiringAutomator(token_path=token_path, state_path=state_path, creds=creds)
    return automator, campaign_id


def _agent_context(request, campaign_id, state, extra=None):
    """Build the full context dict for agent.html."""
    all_campaigns = load_index(request.user.id)
    ctx = {
        'state':              state,
        'candidates':         state.get('candidates', []),
        'campaign_id':        campaign_id,
        'campaign_meta':      get_campaign_meta(request.user.id, campaign_id),
        'history':            [c for c in all_campaigns if c['id'] != campaign_id],
        'current_role':       state.get('role', ''),
        'has_google':         GoogleOAuthToken.objects.filter(user=request.user).exists(),
    }
    if extra:
        ctx.update(extra)
    return ctx


# ─────────────────────────────────────────────────────────────
# PUBLIC — Landing, Login, Register
# ─────────────────────────────────────────────────────────────

def landing(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    return render(request, 'hiring_app/landing.html')


@ratelimit(key='ip', rate='10/m', method='POST', block=True)
def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    error = None
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            login(request, form.get_user())
            logger.info(f"User logged in: {form.get_user().username}")
            return redirect('dashboard')
        error = "Invalid username or password. Please try again."
    return render(request, 'hiring_app/login.html', {'error': error})


@ratelimit(key='ip', rate='5/m', method='POST', block=True)
def register_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    error = None
    if request.method == 'POST':
        username  = request.POST.get('username', '').strip()
        email     = request.POST.get('email', '').strip()
        password1 = request.POST.get('password1', '')
        password2 = request.POST.get('password2', '')

        if not username or not email or not password1:
            error = "All fields are required."
        elif password1 != password2:
            error = "Passwords do not match."
        elif len(password1) < 8:
            error = "Password must be at least 8 characters."
        elif User.objects.filter(username=username).exists():
            error = "Username already taken."
        elif User.objects.filter(email=email).exists():
            error = "Email already registered."
        else:
            user = User.objects.create_user(username=username, email=email, password=password1)
            login(request, user)
            logger.info(f"New user registered: {username}")
            return redirect('dashboard')

    return render(request, 'hiring_app/register.html', {'error': error})


# ─────────────────────────────────────────────────────────────
# GOOGLE OAUTH — Connect & Callback (Option A)
# ─────────────────────────────────────────────────────────────

@login_required
def google_connect(request):
    """Start the Google OAuth2 flow — redirects user to Google consent screen."""
    try:
        flow = _build_oauth_flow(request)
        authorization_url, state = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            prompt='consent',   # Always ask for consent to get refresh_token
        )
        request.session['google_oauth_state'] = state
        request.session['google_oauth_code_verifier'] = flow.code_verifier
        return redirect(authorization_url)
    except FileNotFoundError:
        logger.error("client_secrets.json not found and GOOGLE_CLIENT_SECRETS env var not set")
        return render(request, 'hiring_app/google_connect.html', {
            'error': 'Google OAuth is not configured yet. Please contact the administrator.',
            'has_google': False,
        })
    except Exception as e:
        logger.error(f"Google OAuth start failed: {e}")
        return render(request, 'hiring_app/google_connect.html', {
            'error': f'Could not start Google sign-in: {e}',
            'has_google': False,
        })


@login_required
def google_oauth_callback(request):
    """Handle Google OAuth2 callback — save token to DB."""
    state = request.session.get('google_oauth_state')
    code_verifier = request.session.get('google_oauth_code_verifier')
    try:
        flow = _build_oauth_flow(request, state=state, code_verifier=code_verifier)
        flow.fetch_token(authorization_response=request.build_absolute_uri(request.get_full_path()))
        creds = flow.credentials

        GoogleOAuthToken.objects.update_or_create(
            user=request.user,
            defaults={'token_json': creds.to_json()},
        )
        request.session.pop('google_oauth_state', None)
        request.session.pop('google_oauth_code_verifier', None)
        logger.info(f"Google account connected for user: {request.user.username}")
        return redirect('agent')
    except Exception as e:
        logger.error(f"Google OAuth callback failed for {request.user.username}: {e}")
        return render(request, 'hiring_app/google_connect.html', {
            'error': f'Google sign-in failed: {e}. Please try again.',
            'has_google': False,
        })


@login_required
def google_disconnect(request):
    """Remove stored Google token for the user."""
    if request.method == 'POST':
        GoogleOAuthToken.objects.filter(user=request.user).delete()
        logger.info(f"Google account disconnected for user: {request.user.username}")
    return redirect('dashboard')


# ─────────────────────────────────────────────────────────────
# PROTECTED — Dashboard Overview
# ─────────────────────────────────────────────────────────────

@login_required
def dashboard_overview(request):
    user = request.user
    index = load_index(user.id)

    total_candidates = sum(c.get('candidates_count', 0) for c in index)
    active_campaigns = len([c for c in index if c.get('status') == 'active'])

    context = {
        'campaigns':        index,
        'total_campaigns':  len([c for c in index if c.get('status') != 'draft']),
        'active_campaigns': active_campaigns,
        'total_candidates': total_candidates,
        'has_google':       GoogleOAuthToken.objects.filter(user=user).exists(),
    }
    return render(request, 'hiring_app/dashboard_overview.html', context)


# ─────────────────────────────────────────────────────────────
# PROTECTED — Campaign Management
# ─────────────────────────────────────────────────────────────

@login_required
def new_campaign(request):
    create_new_campaign(request)
    return redirect('agent')


@login_required
def switch_campaign(request, campaign_id):
    if get_campaign_meta(request.user.id, campaign_id):
        set_active_campaign_id(request, campaign_id)
    return redirect('agent')


# ─────────────────────────────────────────────────────────────
# PROTECTED — Agent Page
# ─────────────────────────────────────────────────────────────

@login_required
def agent(request):
    campaign_id, state_path = ensure_active_campaign(request)
    token_path = os.path.join(settings.BASE_DIR, 'token.json')
    creds = _get_user_google_creds(request.user)
    automator = HiringAutomator(token_path=token_path, state_path=state_path, creds=creds)

    try:
        state = automator.load_state()
    except Exception as e:
        logger.error(f"Failed to load campaign state for user {request.user.username}: {e}")
        state = {}

    return render(request, 'hiring_app/agent.html', _agent_context(request, campaign_id, state))


# ─────────────────────────────────────────────────────────────
# PROTECTED — Agent Actions
# ─────────────────────────────────────────────────────────────

@login_required
def generate_jd(request):
    if request.method != 'POST':
        return redirect('agent')

    role       = request.POST.get('role', '').strip()
    experience = request.POST.get('experience', '').strip()

    automator, campaign_id = _get_automator_for_active(request)

    try:
        jd = automator.generate_jd(role, experience)
    except Exception as e:
        logger.error(f"JD generation failed: {e}")
        jd = f"# {role}\n\n(AI generation failed. Please write the JD manually.)"

    upsert_campaign_meta(request.user.id, campaign_id, role=role, status='draft')

    state = automator.load_state()
    ctx = _agent_context(request, campaign_id, state, {
        'jd_preview':   jd,
        'role_preview': role,
        'exp_preview':  experience,
        'current_role': role,
    })
    return render(request, 'hiring_app/agent.html', ctx)


@login_required
def create_campaign(request):
    if request.method != 'POST':
        return redirect('agent')

    role           = request.POST.get('role', '').strip()
    jd             = request.POST.get('jd_text', '')
    linkedin_token = request.POST.get('linkedin_token', '').strip() or None
    linkedin_urn   = request.POST.get('linkedin_urn', '').strip() or None

    automator, campaign_id = _get_automator_for_active(request)

    try:
        form_url, sheet_url = automator.create_campaign(role, jd, linkedin_token, linkedin_urn)
        upsert_campaign_meta(
            request.user.id, campaign_id,
            role=role, status='active',
            form_url=form_url, sheet_url=sheet_url, candidates_count=0,
        )
        logger.info(f"Campaign launched: {role} by {request.user.username}")
    except Exception as e:
        logger.error(f"Campaign creation failed for {request.user.username}: {e}")

    return redirect('agent')


@login_required
def sync_responses(request):
    automator, campaign_id = _get_automator_for_active(request)
    try:
        automator.sync_responses()
        sync_index_from_state(request.user.id, campaign_id)
        logger.info(f"Sync completed for campaign {campaign_id}")
    except Exception as e:
        logger.error(f"Sync failed for {request.user.username}: {e}")
    return redirect('agent')


@login_required
def send_invites(request):
    if request.method != 'POST':
        return redirect('agent')

    selected_emails = request.POST.getlist('selected_candidates')
    interview_date  = request.POST.get('interview_date')

    if not selected_emails:
        return redirect('agent')

    automator, _ = _get_automator_for_active(request)
    try:
        results = automator.send_invites(selected_emails, "Hiring Team", interview_date)
        logger.info(f"Invites sent to {selected_emails} by {request.user.username}")
        for r in results:
            logger.info(r)
    except Exception as e:
        logger.error(f"Send invites failed: {e}")

    return redirect('agent')


@login_required
def send_outcomes(request):
    if request.method != 'POST':
        return redirect('agent')

    hired_emails = request.POST.getlist('hired_candidates')
    automator, campaign_id = _get_automator_for_active(request)

    try:
        results = automator.send_outcomes(hired_emails)
        upsert_campaign_meta(request.user.id, campaign_id, status='completed')
        sync_index_from_state(request.user.id, campaign_id)
        logger.info(f"Outcomes sent by {request.user.username}: hired={hired_emails}")
        for r in results:
            logger.info(r)
    except Exception as e:
        logger.error(f"Send outcomes failed: {e}")

    return redirect('agent')