import json
import logging
import secrets
from urllib.parse import urlencode

import requests

from django.http import FileResponse, Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_POST, require_http_methods
from django_ratelimit.decorators import ratelimit

from google_auth_oauthlib.flow import Flow

from .services import (
    HiringAutomator, SCOPES, JDGenerationFailed,
    get_user_google_creds, get_user_linkedin_creds,
    LINKEDIN_SCOPES, LINKEDIN_AUTHORIZATION_URL, LINKEDIN_TOKEN_URL, LINKEDIN_USERINFO_URL,
)
from .models import GoogleOAuthToken, LinkedInOAuthToken, Campaign, Candidate
from .forms import ApplicationForm
from .tasks import send_invites_task, send_outcomes_task

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


def _automator_for(request):
    # get_user_google_creds moved to services.py in Phase 3 so hiring_app/tasks.py
    # can use it too, without importing views.py (which imports tasks.py to
    # enqueue — that way lies a circular import). get_user_linkedin_creds
    # follows the same pattern for the optional LinkedIn cross-post.
    return HiringAutomator(
        creds=get_user_google_creds(request.user),
        linkedin_creds=get_user_linkedin_creds(request.user),
    )


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
        # Unlike has_google, this checks the connection is actually still
        # usable (get_user_linkedin_creds returns None on an expired token,
        # not just a missing one) — LinkedIn tokens don't auto-refresh, so a
        # stale row shouldn't make the launch-time checkbox appear to work.
        'has_linkedin':  get_user_linkedin_creds(request.user) is not None,
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
            automator = HiringAutomator(creds=get_user_google_creds(campaign.owner))
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

    return render(request, 'hiring_app/apply.html', {
        'campaign': campaign,
        'form': form,
        'privacy_contact_email': settings.PRIVACY_CONTACT_EMAIL,
    })


# ─────────────────────────────────────────────────────────────
# PUBLIC — Legal pages
# ─────────────────────────────────────────────────────────────

def privacy_policy(request):
    return render(request, 'hiring_app/privacy.html', {
        'privacy_contact_email': settings.PRIVACY_CONTACT_EMAIL,
    })


def terms_of_service(request):
    return render(request, 'hiring_app/terms.html', {
        'privacy_contact_email': settings.PRIVACY_CONTACT_EMAIL,
    })


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
# LINKEDIN OAUTH — optional "post this JD to LinkedIn" feature
#
# Separate from Google's OAuth entirely: different provider, different
# scopes, connected/disconnected independently. A user can post to LinkedIn
# with no Google connection at all, or vice versa.
# ─────────────────────────────────────────────────────────────

def _linkedin_redirect_uri(request):
    return request.build_absolute_uri('/linkedin/oauth2callback/')


@login_required
def linkedin_connect(request):
    """Start the LinkedIn OAuth2 flow — redirects to LinkedIn's consent screen.

    Plain 3-legged OAuth (LinkedIn has no PKCE requirement for this flow,
    unlike Google) — a `state` value round-tripped through the session is
    enough CSRF protection, checked in linkedin_oauth_callback below.
    """
    if not settings.LINKEDIN_CLIENT_ID:
        logger.error("LinkedIn OAuth start attempted but LINKEDIN_CLIENT_ID is not set")
        return render(request, 'hiring_app/linkedin_connect.html', {
            'error': 'LinkedIn sign-in is not configured yet. Please contact the administrator.',
        })

    state = secrets.token_urlsafe(24)
    request.session['linkedin_oauth_state'] = state
    params = {
        'response_type': 'code',
        'client_id': settings.LINKEDIN_CLIENT_ID,
        'redirect_uri': _linkedin_redirect_uri(request),
        'state': state,
        'scope': LINKEDIN_SCOPES,
    }
    return redirect(f'{LINKEDIN_AUTHORIZATION_URL}?{urlencode(params)}')


@login_required
def linkedin_oauth_callback(request):
    """Handle LinkedIn's OAuth2 callback: exchange the code for an access
    token, resolve the connecting member's URN via the OIDC userinfo
    endpoint (needed as the `author` on every UGC post), and store both.
    """
    error = request.GET.get('error')
    if error:
        logger.info(f"LinkedIn OAuth denied for user id={request.user.id}: {error}")
        return render(request, 'hiring_app/linkedin_connect.html', {
            'error': 'LinkedIn sign-in was cancelled.',
        })

    expected_state = request.session.pop('linkedin_oauth_state', None)
    if not expected_state or expected_state != request.GET.get('state'):
        logger.warning(f"LinkedIn OAuth state mismatch for user id={request.user.id}")
        return render(request, 'hiring_app/linkedin_connect.html', {
            'error': 'LinkedIn sign-in failed (invalid state). Please try again.',
        })

    try:
        token_resp = requests.post(LINKEDIN_TOKEN_URL, data={
            'grant_type': 'authorization_code',
            'code': request.GET.get('code'),
            'redirect_uri': _linkedin_redirect_uri(request),
            'client_id': settings.LINKEDIN_CLIENT_ID,
            'client_secret': settings.LINKEDIN_CLIENT_SECRET,
        }, timeout=15)
        token_resp.raise_for_status()
        token_data = token_resp.json()
        access_token = token_data['access_token']
        # LinkedIn's own default under these scopes is ~60 days; fall back to
        # that if expires_in is ever absent from the response.
        expires_in = token_data.get('expires_in', 60 * 24 * 3600)

        userinfo_resp = requests.get(
            LINKEDIN_USERINFO_URL,
            headers={'Authorization': f'Bearer {access_token}'},
            timeout=15,
        )
        userinfo_resp.raise_for_status()
        member_id = userinfo_resp.json()['sub']

        LinkedInOAuthToken.objects.update_or_create(
            user=request.user,
            defaults={'token_json': json.dumps({
                'access_token': access_token,
                'expires_at': timezone.now().timestamp() + expires_in,
                'member_urn': f'urn:li:person:{member_id}',
            })},
        )
        logger.info(f"LinkedIn account connected for user: {request.user.username}")
        return redirect('agent')
    except Exception:
        # Do not render {e}: same reasoning as the Google callback — can leak
        # client IDs, token endpoints, and paths.
        logger.exception(f"LinkedIn OAuth callback failed for user id={request.user.id}")
        return render(request, 'hiring_app/linkedin_connect.html', {
            'error': 'LinkedIn sign-in failed. Please try connecting again.',
        })


@login_required
@require_POST
def linkedin_disconnect(request):
    """Remove the stored LinkedIn token.

    Unlike Google, LinkedIn doesn't offer a public token-revocation endpoint
    for member-facing apps — deleting this row stops the app from being able
    to post, but full revocation of the grant itself has to happen from the
    member's own LinkedIn settings (Settings & Privacy → Data privacy →
    Permitted services). Said so explicitly in the success message rather
    than implying a Google-style full revoke happened.
    """
    if LinkedInOAuthToken.objects.filter(user=request.user).delete()[0]:
        logger.info(f"LinkedIn account disconnected for user id={request.user.id}")
        messages.success(
            request,
            "Your LinkedIn account has been disconnected here. To fully revoke access, "
            "also remove HireAI from linkedin.com under Settings & Privacy → Permitted services.",
        )
    return redirect('agent')


@login_required
@require_POST
def linkedin_connect_manual(request):
    """Manual alternative to the OAuth flow above: paste an access token and
    member ID/URN directly, generated by hand from LinkedIn's own Developer
    Portal (app → Auth tab → OAuth 2.0 tools → Token Generator) instead of
    going through linkedin_connect's redirect-based consent screen.

    This is deliberately a second path, not a replacement — the OAuth flow
    above is what this app would use for real multi-tenant public users (see
    ROADMAP.md's original reasoning for removing the old paste-a-token UI
    entirely in Phase 2: "no real user has such a token to paste"). But for a
    single self-hosted operator who already has developer access to their
    own LinkedIn app, generating a token by hand from the Developer Portal
    sidesteps LinkedIn's own OAuth consent screen and any "Share on
    LinkedIn" product-approval gating on the OAuth client entirely — which is
    plausibly why this "just worked" for one person months ago via the old
    UI, before it was pulled for being unsafe to expose to arbitrary public
    signups. Reintroduced here as an opt-in, not the default path.

    LinkedIn's Token Generator doesn't hand back a parseable expiry the way
    the OAuth token endpoint does — assume the same ~60-day window the OAuth
    path defaults to; get_user_linkedin_creds treats an expired token as
    'not connected' either way, so the fix when it lapses is just pasting a
    fresh one here.
    """
    access_token = request.POST.get('access_token', '').strip()
    member_id = request.POST.get('member_id', '').strip()

    if not access_token or not member_id:
        messages.error(request, "Both the access token and member ID/URN are required.")
        return redirect('dashboard')

    member_urn = member_id if member_id.startswith('urn:li:') else f'urn:li:person:{member_id}'

    LinkedInOAuthToken.objects.update_or_create(
        user=request.user,
        defaults={'token_json': json.dumps({
            'access_token': access_token,
            'member_urn': member_urn,
            'expires_at': timezone.now().timestamp() + 60 * 24 * 3600,
        })},
    )
    logger.info(f"LinkedIn account connected manually for user id={request.user.id}")
    messages.success(request, "LinkedIn connected — the token will need re-pasting here in ~60 days.")
    return redirect('dashboard')


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
        'has_linkedin':     LinkedInOAuthToken.objects.filter(user=user).exists(),
        # Google is optional; a real email backend is not. In production
        # with no SMTP host configured, invites/outcomes "send" without
        # raising (the per-candidate try/except in services.py swallows the
        # failure) but never actually arrive — this is the one way skipping
        # Google could silently mean nothing gets delivered. DEBUG mode
        # always uses the console backend, so this only fires in production.
        'email_not_configured': not settings.DEBUG and not getattr(settings, 'EMAIL_HOST', ''),
    }
    return render(request, 'hiring_app/dashboard_overview.html', context)


# ─────────────────────────────────────────────────────────────
# PROTECTED — Account deletion (Phase 4)
# ─────────────────────────────────────────────────────────────

@login_required
def delete_account_confirm(request):
    """Shows exactly what deleting the account will remove, before the
    irreversible POST — same typed-confirmation pattern as send_outcomes."""
    user = request.user
    campaigns = Campaign.objects.filter(owner=user)
    return render(request, 'hiring_app/delete_account_confirm.html', {
        'campaign_count':  campaigns.count(),
        'candidate_count': Candidate.objects.filter(campaign__owner=user).count(),
        'has_google':      GoogleOAuthToken.objects.filter(user=user).exists(),
        'has_linkedin':    LinkedInOAuthToken.objects.filter(user=user).exists(),
    })


@login_required
@require_POST
def delete_account(request):
    """Permanently deletes the account and everything tied to it: revokes any
    connected Google grant, then deletes the User row, which CASCADEs to
    every Campaign the user owns, which CASCADEs to every Candidate in those
    campaigns — and the post_delete signal on Candidate (models.py) removes
    each one's resume file from disk as it goes. The User CASCADE also takes
    out any LinkedInOAuthToken row; there's no revoke call for it first (see
    linkedin_disconnect) since LinkedIn has no public revoke endpoint to hit.
    Nothing here targets another user's data; `request.user` is the only row
    this can ever touch.
    """
    if request.POST.get('confirm') != 'DELETE':
        messages.error(request, 'Type DELETE exactly to confirm account deletion.')
        return redirect('delete_account_confirm')

    user = request.user
    token_record = GoogleOAuthToken.objects.filter(user=user).first()
    if token_record:
        _revoke_google_token(token_record)

    logger.info(f"Account deletion requested for user id={user.id}")
    logout(request)
    user.delete()
    messages.success(request, 'Your account and all its data have been permanently deleted.')
    return redirect('landing')


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
        'jd_preview':     jd,
        'role_preview':   role,
        'exp_preview':    experience,
        # Set on every attempt, success or failure — agent.html gates the
        # JD-editor + launch form on this, not on `jd_preview` being
        # non-empty. It used to be gated on jd_preview alone, which meant
        # the "you can write one manually" message above was a lie: on a
        # JDGenerationFailed, jd is '' (falsy), so the editor never rendered
        # and there was no textarea to write into at all.
        'show_jd_editor': True,
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
    LinkedIn is the same shape: optional, and only attempted if the
    "post_to_linkedin" checkbox was submitted (agent.html only renders it at
    all when the recruiter has a working LinkedIn connection).
    """
    campaign = _get_owned_campaign(request, campaign_id)
    role = request.POST.get('role', '').strip()
    jd   = request.POST.get('jd_text', '')
    post_to_linkedin = request.POST.get('post_to_linkedin') == 'on'

    if not role:
        messages.error(request, "Enter a role title before launching a campaign.")
        return redirect('campaign_agent', campaign_id=campaign.pk)

    campaign.role = role
    automator = _automator_for(request)
    apply_url = request.build_absolute_uri(reverse('apply', args=[campaign.public_token]))

    try:
        automator.create_campaign(campaign, jd, post_to_linkedin=post_to_linkedin, apply_url=apply_url)
        logger.info(f"Campaign launched: campaign={campaign.pk} by user id={request.user.id}")
        success_msg = f"Campaign for “{role}” is live — share the apply link with candidates."
        # Gate on automator.has_linkedin, not just the submitted checkbox —
        # if there's no actual connection (checkbox submitted via a stale
        # page load, say), create_campaign silently skipped posting
        # entirely, and a "posting failed" warning would be a false alarm
        # about an attempt that never happened.
        if post_to_linkedin and automator.has_linkedin:
            # Best-effort like Sheets export, but unlike Sheets the recruiter
            # explicitly asked for this one this time (checked the box), so
            # tell them plainly if it didn't happen rather than staying quiet.
            if campaign.linkedin_post_id:
                success_msg += " Also posted to your LinkedIn feed."
            else:
                messages.warning(request, "Campaign launched, but posting to LinkedIn failed. You can share it manually.")
        messages.success(request, success_msg)
    except Exception:
        logger.exception(f"Campaign creation failed for user id={request.user.id}")
        messages.error(request, "Could not launch the campaign. Please try again.")

    return redirect('campaign_agent', campaign_id=campaign.pk)


@login_required
@require_POST
def send_invites(request, campaign_id):
    """Enqueue interview invites and return immediately.

    Phase 3: this used to send synchronously, in the request, with no way to
    survive a crash mid-batch without risking a double-send. Now it hands off
    to send_invites_task and the agent page polls campaign_status for
    progress — see agent.html.
    """
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

    # Validate the date up front — fail fast in the request, not silently
    # inside a background task the user has already navigated away from.
    try:
        HiringAutomator(creds=None).parse_interview_datetime(interview_date)
    except ValueError as e:
        messages.error(request, str(e))
        return redirect('campaign_agent', campaign_id=campaign.pk)

    send_invites_task.delay(campaign.pk, [c.pk for c in selected], "Hiring Team", interview_date)
    logger.info(f"Queued {len(selected)} invite(s) for campaign={campaign.pk}, user id={request.user.id}")
    messages.success(request, f"Sending {len(selected)} interview invite(s) in the background…")
    # ?watch=invites tells agent.html's JS to poll campaign_status and update
    # live rather than leaving the recruiter looking at a static "sending…"
    # message with no idea whether it's actually progressing.
    return redirect(reverse('campaign_agent', args=[campaign.pk]) + '?watch=invites')


@login_required
@require_POST
def send_outcomes(request, campaign_id):
    """Enqueue offers to the selected candidates and rejections to everyone
    else. This is irreversible, so it requires an explicit confirmation token
    from the interstitial rather than firing on a single click — the typed
    confirmation is the safeguard; enqueueing rather than sending inline
    (Phase 3) is about not double-sending on a crash mid-batch, a separate
    concern from this one.
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

    hired_ids = [c.pk for c in hired]
    send_outcomes_task.delay(campaign.pk, hired_ids)
    logger.info(
        f"Queued outcomes for {total} candidate(s), campaign={campaign.pk}, "
        f"user id={request.user.id}"
    )
    messages.success(request, f"Sending {total} outcome email(s) in the background…")
    return redirect(reverse('campaign_agent', args=[campaign.pk]) + '?watch=outcomes')


@login_required
def campaign_status(request, campaign_id):
    """Polled from agent.html while invites/outcomes are sending in the
    background. Reports DB state directly — how many candidates actually have
    invite_sent_at/outcome_sent_at set — rather than tracking Celery task IDs.
    The DB is the source of truth either way, and this sidesteps needing a
    result backend that outlives a single poll (or a model field to stash a
    task ID in) for something the row itself already answers.
    """
    campaign = _get_owned_campaign(request, campaign_id)
    total = campaign.candidates.count()
    invited = campaign.candidates.exclude(invite_sent_at__isnull=True).count()
    outcomes_sent = campaign.candidates.exclude(outcome_sent_at__isnull=True).count()
    return JsonResponse({
        'status': campaign.status,
        'total_candidates': total,
        'invites_sent': invited,
        'outcomes_sent': outcomes_sent,
    })


# ─────────────────────────────────────────────────────────────
# Health check (platform readiness probe)
# ─────────────────────────────────────────────────────────────

@require_http_methods(['GET', 'HEAD'])
def healthz(request):
    return JsonResponse({'status': 'ok'})
