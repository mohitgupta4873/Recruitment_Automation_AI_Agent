from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('generate-jd/', views.generate_jd, name='generate_jd'),
    path('create-campaign/', views.create_campaign, name='create_campaign'),
    path('sync/', views.sync_responses, name='sync_responses'),
    path('invite/', views.send_invites, name='send_invites'),
    path('outcomes/', views.send_outcomes, name='send_outcomes'),
]