from django.urls import path, reverse_lazy
from django.contrib.auth import views as auth_views
from django.contrib.auth.views import LogoutView
from . import views

# Password reset/change wired explicitly rather than via
# include('django.contrib.auth.urls'): that module also registers 'login' and
# 'logout', and since reverse() resolves to the LAST pattern registered for a
# name, it would silently hijack {% url 'login' %} to a template we don't ship.
_password_urls = [
    path(
        'password-reset/',
        auth_views.PasswordResetView.as_view(
            template_name='hiring_app/password_reset_form.html',
            email_template_name='hiring_app/password_reset_email.txt',
            subject_template_name='hiring_app/password_reset_subject.txt',
            success_url=reverse_lazy('password_reset_done'),
        ),
        name='password_reset',
    ),
    path(
        'password-reset/sent/',
        auth_views.PasswordResetDoneView.as_view(
            template_name='hiring_app/password_reset_done.html',
        ),
        name='password_reset_done',
    ),
    path(
        'password-reset/<uidb64>/<token>/',
        auth_views.PasswordResetConfirmView.as_view(
            template_name='hiring_app/password_reset_confirm.html',
            success_url=reverse_lazy('password_reset_complete'),
        ),
        name='password_reset_confirm',
    ),
    path(
        'password-reset/done/',
        auth_views.PasswordResetCompleteView.as_view(
            template_name='hiring_app/password_reset_complete.html',
        ),
        name='password_reset_complete',
    ),
]

urlpatterns = _password_urls + [
    # Ops
    path('healthz/', views.healthz, name='healthz'),

    # Public
    path('', views.landing, name='landing'),
    path('login/', views.login_view, name='login'),
    path('register/', views.register_view, name='register'),
    path('logout/', LogoutView.as_view(), name='logout'),

    # Phase 4 — legal pages, linked from the footer and the apply page.
    path('privacy/', views.privacy_policy, name='privacy'),
    path('terms/', views.terms_of_service, name='terms'),

    # The public candidate-facing application form — replaces the Google Form
    # as of Phase 2. No login, no campaign_id: public_token alone identifies
    # the campaign (see Campaign.public_token).
    path('apply/<str:public_token>/', views.apply, name='apply'),

    # Google OAuth
    path('google/connect/', views.google_connect, name='google_connect'),
    path('google/oauth2callback/', views.google_oauth_callback, name='google_oauth_callback'),
    path('google/disconnect/', views.google_disconnect, name='google_disconnect'),

    # LinkedIn OAuth — separate provider/flow, optional "post JD to LinkedIn"
    # checkbox at campaign launch. Independent of the Google connection above.
    path('linkedin/connect/', views.linkedin_connect, name='linkedin_connect'),
    path('linkedin/oauth2callback/', views.linkedin_oauth_callback, name='linkedin_oauth_callback'),
    path('linkedin/disconnect/', views.linkedin_disconnect, name='linkedin_disconnect'),
    # Manual alternative to the OAuth flow above — paste a token generated
    # by hand from LinkedIn's Developer Portal instead of going through
    # linkedin_connect's redirect. See views.linkedin_connect_manual.
    path('linkedin/connect-manual/', views.linkedin_connect_manual, name='linkedin_connect_manual'),

    # Dashboard & Multi-Campaign
    path('dashboard/', views.dashboard_overview, name='dashboard'),
    path('campaign/new/', views.new_campaign, name='new_campaign'),

    # Phase 4 — account deletion. GET shows what will be removed and asks for
    # a typed confirmation; POST (a separate URL, like send_outcomes) is the
    # actual irreversible action.
    path('account/delete/', views.delete_account_confirm, name='delete_account_confirm'),
    path('account/delete/confirm/', views.delete_account, name='delete_account'),

    # 'agent/' is a convenience redirect (no campaign_id) that resolves to a
    # specific campaign and forwards there — kept so nav links and the
    # post-Google-connect redirect don't need to know which campaign is "current".
    path('agent/', views.agent, name='agent'),

    # Campaign Workspace — ownership is enforced per-request in views.py
    # (get_object_or_404(Campaign, pk=campaign_id, owner=request.user)), not by
    # anything in the URL itself. There is no more session-based "active
    # campaign": the URL is the only source of truth for which campaign a
    # request is about, so two tabs on two different campaigns just work.
    path('campaign/<uuid:campaign_id>/', views.campaign_agent, name='campaign_agent'),
    path('campaign/<uuid:campaign_id>/candidates/<int:candidate_id>/resume/', views.view_resume, name='view_resume'),
    path('campaign/<uuid:campaign_id>/generate-jd/', views.generate_jd, name='generate_jd'),
    path('campaign/<uuid:campaign_id>/create/', views.create_campaign, name='create_campaign'),
    path('campaign/<uuid:campaign_id>/invites/', views.send_invites, name='send_invites'),
    path('campaign/<uuid:campaign_id>/outcomes/', views.send_outcomes, name='send_outcomes'),
    # Polled by agent.html while an invites/outcomes task is running in the
    # background — see views.campaign_status.
    path('campaign/<uuid:campaign_id>/status/', views.campaign_status, name='campaign_status'),
]