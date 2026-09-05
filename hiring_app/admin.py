from django.contrib import admin

from .models import Campaign, Candidate

# GoogleOAuthToken is deliberately NOT registered here. It holds encrypted
# OAuth credentials (see models.EncryptedTextField) and there is no legitimate
# admin-UI use case for browsing it — anyone who needs to service a support
# request for a stuck Google connection should have the user re-run
# google_disconnect / google_connect, not have staff poke at the row.


@admin.register(Campaign)
class CampaignAdmin(admin.ModelAdmin):
    """Primarily here to service Phase 4 data requests — deletion (account
    closure, GDPR-style erasure) and retention lookups — not day-to-day
    campaign management, which happens through the app's own dashboard.
    """
    list_display = ('role', 'owner', 'status', 'candidates_count', 'retention_days', 'closed_at', 'created_at')
    list_filter = ('status',)
    search_fields = ('role', 'owner__username', 'owner__email', 'public_token')
    readonly_fields = ('id', 'public_token', 'created_at', 'updated_at')
    autocomplete_fields = ('owner',)


@admin.register(Candidate)
class CandidateAdmin(admin.ModelAdmin):
    """search_fields on email is the main reason this is registered: it's
    how a candidate erasure request ("delete my resume from campaign X") gets
    serviced today — find the row by email, delete it. Deleting a Candidate
    here also deletes its resume file from disk, via the post_delete signal
    in models.py.
    """
    list_display = ('email', 'full_name', 'campaign', 'source', 'score', 'resume_status', 'outcome_type', 'created_at')
    list_filter = ('source', 'resume_status', 'outcome_type')
    search_fields = ('email', 'full_name', 'campaign__role')
    readonly_fields = ('created_at', 'updated_at')
    autocomplete_fields = ('campaign',)
