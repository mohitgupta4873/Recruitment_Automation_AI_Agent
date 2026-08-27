import json
import logging

import requests

from django.http import FileResponse, Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.http import JsonResponse
from django.views.decorators.http import require_POST, require_http_methods
from django_ratelimit.decorators import ratelimit

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest
from google_auth_oauthlib.flow import Flow

from .services import HiringAutomator, SCOPES, JDGenerationFailed
from .models import GoogleOAuthToken, Campaign, Candidate
from .forms import ApplicationForm

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
    a separate Flow object than the one that started the flow, the token
    exchange would be missing it (Google error: "Missing code verifier").
    """
    import os
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
    Returns a Credentials object, or None if the user hasn't connected Google
    (or refresh failed) — HiringAutomator then raises GoogleNotConnected on
    any Google-backed operation. There is no fallback to a shared token.
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


def _automator_for(request):
    return HiringAutomator(creds=_get_user_google_creds(request.user))


def _get_owned_campaign(request, campaign_id):
    """Ownership is a database constraint, not a filesystem path convention:
    a campaign_id belonging to another user 404s here rather than ever being
    reachable."""
    return get_object_or_404(Campaign, pk=campaign_id, owner=request.user)


def _agent_context(request, campaign, extra=None):
    """Build the full context dict for agent.html."""
    ctx = {
        'campaign':      campaign,
        'campaign_id':   campaign.pk,
        'apply_url':     request.build_absolute_uri(reverse('apply', args=[campaign.public_token])),
        'candidates':    campaign.candidates.all(),
        'history':       Campaign.objects.filter(owner=request.user).exclude(pk=campaign.pk),
        'current_role':  campaign.role,
        'has_google':    GoogleOAuthToken.objects.filter(user=request.user).exists(),
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
    """Registration.

    Uses UserCreationForm so Django's configured AUTH_PASSWORD_VALIDATORS
    actually run. The previous hand-rolled checks only enforced a length of 8,
    which meant 'password123' and '12345678' were both accepted.
    """
    if request.user.is_authenticated:
        return redirect('dashboard')

    error = None
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        email = request.POST.get('email', '').strip()

        try:
            validate_email(email)
            email_ok = True
        except ValidationError:
            email_ok = False

        if not email_ok:
            error = "Enter a valid email address."
        elif User.objects.filter(email__iexact=email).exists():
            error = "Email already registered."
        elif form.is_valid():
            user = form.save(commit=False)
            user.email = email
            user.save()
            login(request, user)
            logger.info(f"New user registered: id={user.id}")
            return redirect('dashboard')
        else:
            error = ' '.join(
                msg for msgs in form.errors.values() for msg in msgs
            )

    return render(request, 'hiring_app/register.html', {'error': error})


# ─────────────────────────────────────────────────────────────
# PUBLIC — Apply Page
#
# This is what replaced the Google Form as of Phase 2: an applicant needs no
# account, and the recruiter needs no Google connection, for an application to
# go through. `public_token` alone is the access control — it's unguessable
# (see models._generate_public_token) and doesn't reveal the campaign's
# internal UUID.
# ─────────────────────────────────────────────────────────────

@ratelimit(key='ip', rate='10/h', method='POST', block=True)
def apply(request, public_token):
    campaign = get_object_or_404(Campaign, public_token=public_token)

    if not campaign.accepting_applications:
        return render(request, 'hiring_app/apply_closed.html', {'campaign': campaign})

    if request.method == 'POST':
        form = ApplicationForm(request.POST, request.FILES)
        if form.is_valid():
            automator = HiringAutomator(creds=_get_user_google_creds(campaign.owner))
            try:
                automator.process_application(campaign, form.cleaned_data)
                logger.info(f"New application to campaign={campaign.pk}")
                return render(request, 'hiring_app/apply_success.html', {'campaign': campaign})
            except Exception:
                logger.exception(f"Application processing failed for campaign={campaign.pk}")
                messages.error(
                    request,
                    "Something went wrong processing your application. Please try again.",
                )
    else:
        form = ApplicationForm()

    return render(request, 'hiring_app/apply.html', {'campaign': campaign, 'form': form})


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
    except Exception:
        # Do not render {e}: it can leak client IDs, token endpoints, and paths.
        logger.exception("Google OAuth start failed")
        return render(request, 'hiring_app/google_connect.html', {
            'error': 'Could not start Google sign-in. Please try again.',
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
    except Exception:
        logger.exception(f"Google OAuth callback failed for user id={request.user.id}")
        return render(request, 'hiring_app/google_connect.html', {
            'error': 'Google sign-in failed. Please try connecting again.',
            'has_google': False,
        })


@login_required
@require_POST
def google_disconnect(request):
    """Remove the stored Google token and revoke the grant with Google."""
    token_record = GoogleOAuthToken.objects.filter(user=request.user).first()
    if token_record:
        _revoke_google_token(token_record)
        token_record.delete()
        logger.info(f"Google account disconnected for user id={request.user.id}")
        messages.success(request, "Your Google account has been disconnected.")
    return redirect('dashboard')


def _revoke_google_token(token_record):
    """Best-effort revoke at Google's end.

    Deleting our row alone leaves the grant live on the user's Google account,
    so the app would still appear under myaccount.google.com/permissions.
    """
    try:
        data = json.loads(token_record.token_json)
        token = data.get('refresh_token') or data.get('token')
        if not token:
            return
        resp = requests.post(
            'https://oauth2.googleapis.com/revoke',
            params={'token': token},
            headers={'content-type': 'application/x-www-form-urlencoded'},
            timeout=10,
        )
        if resp.status_code != 200:
            logger.warning(f"Google token revoke returned HTTP {resp.status_code}")
    except (json.JSONDecodeError, requests.RequestException) as e:
        logger.warning(f"Could not revoke Google token: {e}")


# ─────────────────────────────────────────────────────────────
# PROTECTED — Dashboard Overview
# ─────────────────────────────────────────────────────────────

@login_required
def dashboard_overview(request):
    user = request.user
    campaigns = Campaign.objects.filter(owner=user)

    total_candidates = sum(c.candidates_count for c in campaigns)
    active_campaigns = campaigns.filter(status='active').count()

    context = {
        'campaigns':        campaigns,
        'total_campaigns':  campaigns.exclude(status='draft').count(),
        'active_campaigns': active_campaigns,
        'total_candidates': total_candidates,
        'has_google':       GoogleOAuthToken.objects.filter(user=user).exists(),
    }
    return render(request, 'hiring_app/dashboard_overview.html', context)


# ─────────────────────────────────────────────────────────────
# PROTECTED — Campaign Management
# ─────────────────────────────────────────────────────────────

@login_required
@require_POST
def new_campaign(request):
    campaign = Campaign.objects.create(owner=request.user)
    return redirect('campaign_agent', campaign_id=campaign.pk)


@login_required
def agent(request):
    """Convenience redirect: resolves to a specific campaign's workspace.

    Prefers the most recently created non-draft campaign, then the most
    recent draft, and only creates a new one if the user has none at all —
    unlike the old session-based version, this no longer manufactures a fresh
    "New Campaign" draft every time it can't find a non-draft one, which is
    what let empty drafts accumulate without bound.
    """
    campaigns = Campaign.objects.filter(owner=request.user)
    campaign = campaigns.exclude(status='draft').first() or campaigns.first()
    if not campaign:
        campaign = Campaign.objects.create(owner=request.user)
    return redirect('campaign_agent', campaign_id=campaign.pk)


@login_required
def campaign_agent(request, campaign_id):
    campaign = _get_owned_campaign(request, campaign_id)
    return render(request, 'hiring_app/agent.html', _agent_context(request, campaign))


@login_required
def view_resume(request, campaign_id, candidate_id):
    """Serve a candidate's resume PDF.

    Resumes are stored on STORAGES['default'] (local disk today, see
    models.candidate_resume_path) with no public URL — this is the only way
    to reach one, and it's ownership-checked the same way every campaign view
    is. Without this, resumes uploaded through the Phase 2 apply page would be
    write-only: saved, scored, and then unreachable through the UI forever.
    """
    campaign = _get_owned_campaign(request, campaign_id)
    candidate = get_object_or_404(Candidate, pk=candidate_id, campaign=campaign)
    if not candidate.resume:
        raise Http404("No resume on file for this candidate.")
    filename = f"{candidate.full_name or candidate.email}.pdf".replace('/', '-')
    return FileResponse(candidate.resume.open('rb'), filename=filename, content_type='application/pdf')


# ─────────────────────────────────────────────────────────────
# PROTECTED — Agent Actions
# ─────────────────────────────────────────────────────────────

def _validate_recipients(campaign, submitted):
    """Match submitted email strings to this campaign's own Candidate rows.

    Without this the POSTed list went straight to the Gmail API, so any
    authenticated user could send mail to arbitrary addresses from the
    connected Google account — an authenticated spam relay.
    """
    allowed = {c.email.strip().lower(): c for c in campaign.candidates.all()}
    valid, rejected = [], []
    for raw in submitted:
        addr = (raw or '').strip()
        candidate = allowed.get(addr.lower())
        if candidate:
            valid.append(candidate)
        else:
            rejected.append(addr)
    return valid, rejected


@login_required
@require_POST
@ratelimit(key='user', rate='10/h', method='POST', block=True)
def generate_jd(request, campaign_id):
    campaign = _get_owned_campaign(request, campaign_id)
    role       = request.POST.get('role', '').strip()
    experience = request.POST.get('experience', '').strip()

    if not role:
        messages.error(request, "Enter a role title before generating a JD.")
        return redirect('campaign_agent', campaign_id=campaign.pk)

    automator = _automator_for(request)
    try:
        jd = automator.generate_jd(role, experience)
    except JDGenerationFailed:
        messages.error(
            request,
            "The AI could not draft a job description right now. "
            "You can write one manually and continue.",
        )
        jd = ''

    campaign.role = role
    campaign.experience = experience
    campaign.save(update_fields=['role', 'experience', 'updated_at'])

    ctx = _agent_context(request, campaign, {
        'jd_preview':   jd,
        'role_preview': role,
        'exp_preview':  experience,
    })
    return render(request, 'hiring_app/agent.html', ctx)


@login_required
@require_POST
@ratelimit(key='user', rate='10/h', method='POST', block=True)
def create_campaign(request, campaign_id):
    """Launch the campaign: store the JD, derive scoring keywords, go live.

    Google is optional — HiringAutomator.create_campaign only touches Sheets,
    best-effort, if the recruiter has connected an account. There's no more
    Forms/Drive step, so there's nothing here that hard-requires Google.
    """
    campaign = _get_owned_campaign(request, campaign_id)
    role = request.POST.get('role', '').strip()
    jd   = request.POST.get('jd_text', '')

    if not role:
        messages.error(request, "Enter a role title before launching a campaign.")
        return redirect('campaign_agent', campaign_id=campaign.pk)

    campaign.role = role
    automator = _automator_for(request)

    try:
        automator.create_campaign(campaign, jd)
        logger.info(f"Campaign launched: campaign={campaign.pk} by user id={request.user.id}")
        messages.success(request, f"Campaign for “{role}” is live — share the apply link with candidates.")
    except Exception:
        logger.exception(f"Campaign creation failed for user id={request.user.id}")
        messages.error(request, "Could not launch the campaign. Please try again.")

    return redirect('campaign_agent', campaign_id=campaign.pk)


@login_required
@require_POST
def send_invites(request, campaign_id):
    campaign = _get_owned_campaign(request, campaign_id)
    submitted      = request.POST.getlist('selected_candidates')
    interview_date = request.POST.get('interview_date')

    if not submitted:
        messages.error(request, "Select at least one candidate to invite.")
        return redirect('campaign_agent', campaign_id=campaign.pk)

    selected, rejected = _validate_recipients(campaign, submitted)
    if rejected:
        logger.warning(
            f"Rejected {len(rejected)} invite recipient(s) not in campaign, "
            f"user id={request.user.id}"
        )
    if not selected:
        messages.error(request, "None of the selected candidates belong to this campaign.")
        return redirect('campaign_agent', campaign_id=campaign.pk)

    automator = _automator_for(request)
    try:
        results = automator.send_invites(campaign, selected, "Hiring Team", interview_date)
        failures = [r for r in results if r.startswith('Failed')]
        logger.info(
            f"Invites: {len(results) - len(failures)} sent, {len(failures)} failed, "
            f"user id={request.user.id}"
        )
        if failures:
            messages.warning(
                request,
                f"Sent {len(results) - len(failures)} invite(s); {len(failures)} could not be delivered.",
            )
        else:
            messages.success(request, f"Sent {len(results)} interview invite(s).")
    except ValueError as e:
        messages.error(request, str(e))
    except Exception:
        logger.exception(f"Send invites failed for user id={request.user.id}")
        messages.error(request, "Could not send the invites. Please try again.")

    return redirect('campaign_agent', campaign_id=campaign.pk)


@login_required
@require_POST
def send_outcomes(request, campaign_id):
    """Send offers to the selected candidates and rejections to everyone else.

    This is irreversible, so it requires an explicit confirmation token from the
    interstitial rather than firing on a single click.
    """
    campaign = _get_owned_campaign(request, campaign_id)
    submitted = request.POST.getlist('hired_candidates')
    hired, rejected = _validate_recipients(campaign, submitted)

    if rejected:
        logger.warning(
            f"Rejected {len(rejected)} outcome recipient(s) not in campaign, "
            f"user id={request.user.id}"
        )
        messages.error(request, "Some selected candidates do not belong to this campaign.")
        return redirect('campaign_agent', campaign_id=campaign.pk)

    total = campaign.candidates.count()
    if not total:
        messages.error(request, "There are no candidates to send outcomes to.")
        return redirect('campaign_agent', campaign_id=campaign.pk)

    if request.POST.get('confirm') != 'SEND':
        return render(request, 'hiring_app/confirm_outcomes.html', {
            'campaign_id':  campaign.pk,
            'hired_emails': [c.email for c in hired],
            'offer_count':  len(hired),
            'reject_count': total - len(hired),
            'total_count':  total,
        })

    automator = _automator_for(request)
    try:
        hired_ids = {c.pk for c in hired}
        results = automator.send_outcomes(campaign, hired_ids)
        campaign.status = 'completed'
        campaign.save(update_fields=['status', 'updated_at'])
        failures = [r for r in results if r.startswith('FAILED')]
        logger.info(
            f"Outcomes: {len(results) - len(failures)} sent, {len(failures)} failed, "
            f"campaign={campaign.pk}, user id={request.user.id}"
        )
        if failures:
            messages.warning(
                request,
                f"Sent {len(results) - len(failures)} outcome email(s); {len(failures)} failed.",
            )
        else:
            messages.success(request, f"Sent {len(results)} outcome email(s).")
    except Exception:
        logger.exception(f"Send outcomes failed for user id={request.user.id}")
        messages.error(request, "Could not send the outcome emails. Please try again.")

    return redirect('campaign_agent', campaign_id=campaign.pk)


# ─────────────────────────────────────────────────────────────
# Health check (platform readiness probe)
# ─────────────────────────────────────────────────────────────

@require_http_methods(['GET', 'HEAD'])
def healthz(request):
    return JsonResponse({'status': 'ok'})
