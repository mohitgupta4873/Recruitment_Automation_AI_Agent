from django.urls import path
from django.contrib.auth.views import LogoutView
from . import views

urlpatterns = [
    # Public
    path('', views.landing, name='landing'),
    path('login/', views.login_view, name='login'),
    path('register/', views.register_view, name='register'),
    path('logout/', LogoutView.as_view(), name='logout'),

    # Google OAuth
    path('google/connect/', views.google_connect, name='google_connect'),
    path('google/oauth2callback/', views.google_oauth_callback, name='google_oauth_callback'),
    path('google/disconnect/', views.google_disconnect, name='google_disconnect'),

    # Dashboard & Multi-Campaign
    path('dashboard/', views.dashboard_overview, name='dashboard'),
    path('campaign/new/', views.new_campaign, name='new_campaign'),
    path('campaign/switch/<str:campaign_id>/', views.switch_campaign, name='switch_campaign'),

    # Active Campaign Workspace (Agent)
    path('agent/', views.agent, name='agent'),
    path('generate-jd/', views.generate_jd, name='generate_jd'),
    path('create-campaign/', views.create_campaign, name='create_campaign'),
    path('sync-responses/', views.sync_responses, name='sync_responses'),
    path('send-invites/', views.send_invites, name='send_invites'),
    path('send-outcomes/', views.send_outcomes, name='send_outcomes'),
]