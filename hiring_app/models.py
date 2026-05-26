from django.db import models
from django.contrib.auth.models import User


class GoogleOAuthToken(models.Model):
    """
    Stores per-user Google OAuth2 credentials.
    Each user who connects their Google account gets one row here.
    The token_json field holds the full credentials JSON (access token,
    refresh token, token_uri, client_id, client_secret, scopes).
    """
    user       = models.OneToOneField(User, on_delete=models.CASCADE, related_name='google_token')
    token_json = models.TextField(help_text="Google OAuth2 credentials as JSON string")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"GoogleOAuthToken({self.user.username})"
