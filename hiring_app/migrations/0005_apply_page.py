"""
Phase 2: the public apply page replaces the Google Form as candidate intake.

Written by hand rather than via makemigrations because:
  - Campaign.public_token is unique with a callable default — Django's
    autodetector can't generate distinct values for existing rows and refuses
    to proceed non-interactively, so backfilling is done explicitly below.
  - Candidate.download_status -> resume_status is a real rename, not a
    drop+add: the legacy Google-Form-sourced rows' values ('downloaded',
    'no_link', ...) must survive it. RenameField preserves them; makemigrations'
    default non-interactive behavior would have silently dropped the column.
"""
import secrets

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import hiring_app.models


def backfill_public_tokens(apps, schema_editor):
    Campaign = apps.get_model('hiring_app', 'Campaign')
    for campaign in Campaign.objects.filter(public_token=''):
        # 32 hex chars fits the field's max_length=32 exactly. Not the same
        # generator as _generate_public_token (that's url-safe base64, ~22
        # chars) — doesn't need to be; both are unguessable, this only runs
        # once per pre-existing row.
        campaign.public_token = secrets.token_hex(16)
        campaign.save(update_fields=['public_token'])


def backfill_candidate_source(apps, schema_editor):
    """Historical candidates from import_legacy_campaigns arrived via the old
    Google Form, not the apply page — flag them as such so the two intake
    paths stay distinguishable now they share one table."""
    Candidate = apps.get_model('hiring_app', 'Candidate')
    Candidate.objects.exclude(form_response_id='').update(source='google_form')


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('hiring_app', '0004_candidate_resume'),
    ]

    operations = [
        # ── Campaign: public apply link + AI-derived scoring keywords ──
        migrations.AddField(
            model_name='campaign',
            name='public_token',
            field=models.CharField(default='', editable=False, max_length=32),
        ),
        migrations.RunPython(backfill_public_tokens, noop_reverse),
        migrations.AlterField(
            model_name='campaign',
            name='public_token',
            field=models.CharField(
                default=hiring_app.models._generate_public_token,
                editable=False, max_length=32, unique=True,
            ),
        ),
        migrations.AddField(
            model_name='campaign',
            name='scoring_keywords',
            field=models.JSONField(blank=True, default=list),
        ),

        # ── Candidate: fields the apply form collects ──
        migrations.AddField(
            model_name='candidate',
            name='source',
            field=models.CharField(
                choices=[('google_form', 'Google Form (legacy)'), ('apply_page', 'Apply Page')],
                default='apply_page', max_length=20,
            ),
        ),
        migrations.RunPython(backfill_candidate_source, noop_reverse),
        migrations.AddField(
            model_name='candidate',
            name='full_name',
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name='candidate',
            name='years_experience',
            field=models.CharField(
                blank=True, max_length=10,
                choices=[('0', '0 years'), ('1', '1 year'), ('2', '2 years'), ('3+', '3+ years')],
            ),
        ),
        migrations.AddField(
            model_name='candidate',
            name='why_fit',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='candidate',
            name='linkedin_url',
            field=models.URLField(blank=True),
        ),
        migrations.AddField(
            model_name='candidate',
            name='consent_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='candidate',
            name='matched_terms',
            field=models.JSONField(blank=True, default=list),
        ),

        # ── Candidate: generalise download_status -> resume_status ──
        migrations.RenameField(
            model_name='candidate', old_name='download_status', new_name='resume_status',
        ),
        migrations.AlterField(
            model_name='candidate',
            name='resume_status',
            field=models.CharField(
                choices=[
                    ('no_link', 'No Link (legacy)'),
                    ('unrecognised_link', 'Unrecognised Link (legacy)'),
                    ('downloaded', 'Downloaded (legacy)'),
                    ('download_failed', 'Download Failed (legacy)'),
                    ('parsed', 'Parsed'),
                    ('parse_failed', 'Parse Failed'),
                ],
                default='parsed', max_length=20,
            ),
        ),
    ]
