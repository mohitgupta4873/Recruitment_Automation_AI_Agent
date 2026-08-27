"""
One-shot import: campaigns/user_{id}/*.json  ->  Campaign/Candidate rows.

This is the Phase 1 migration path off the old file-based storage
(campaign_manager.py, deleted). Run it once per environment that still has a
campaigns/ directory, then verify the dashboard looks right before removing
the old files.

Safe to re-run: campaigns already imported (matched by owner + role + form_id)
are skipped rather than duplicated. Does NOT read the orphaned
RecruitmentCampaign/CampaignHistory tables some local dev databases may still
have lying around from an earlier, abandoned migration attempt — those were
never committed to git and were deliberately left untouched; see ROADMAP.md.

Usage:
    python manage.py import_legacy_campaigns            # imports for real
    python manage.py import_legacy_campaigns --dry-run   # report only
"""
import json
import os
import re

from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from hiring_app.models import Campaign, Candidate

STATUS_MAP = {'draft': 'draft', 'active': 'active', 'completed': 'completed'}
LEGACY_CV_DIR = 'cv_pdfs'  # under MEDIA_ROOT, holds old locally-downloaded resumes


class Command(BaseCommand):
    help = "Import campaigns/user_{id}/*.json into the Campaign/Candidate models."

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help="Report what would be imported without writing anything.",
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        campaigns_root = os.path.join(settings.BASE_DIR, 'campaigns')

        if not os.path.isdir(campaigns_root):
            self.stdout.write(self.style.WARNING(f"No campaigns/ directory at {campaigns_root} — nothing to do."))
            return

        stats = {'campaigns': 0, 'candidates': 0, 'skipped_empty': 0,
                  'skipped_existing': 0, 'users_missing': 0}

        for entry in sorted(os.listdir(campaigns_root)):
            m = re.fullmatch(r'user_(\d+)', entry)
            if not m:
                continue
            user_id = int(m.group(1))
            user_dir = os.path.join(campaigns_root, entry)

            user = User.objects.filter(pk=user_id).first()
            if not user:
                self.stdout.write(self.style.WARNING(f"  user_{user_id}: no such User — skipped"))
                stats['users_missing'] += 1
                continue

            index_path = os.path.join(user_dir, '_index.json')
            if not os.path.exists(index_path):
                continue
            try:
                index = json.load(open(index_path, encoding='utf-8'))
            except (json.JSONDecodeError, OSError) as e:
                self.stdout.write(self.style.ERROR(f"  user_{user_id}: could not read _index.json: {e}"))
                continue

            for meta in index:
                self._import_one(user, user_dir, meta, dry_run, stats)

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f"{'Would import' if dry_run else 'Imported'}: "
            f"{stats['campaigns']} campaign(s), {stats['candidates']} candidate(s). "
            f"Skipped: {stats['skipped_empty']} empty draft(s), "
            f"{stats['skipped_existing']} already-imported, "
            f"{stats['users_missing']} campaign(s) for missing users."
        ))
        if not dry_run and stats['campaigns']:
            self.stdout.write(
                "The original campaigns/ JSON files were left in place. "
                "Once you've checked the dashboard looks right, delete them yourself."
            )

    def _import_one(self, user, user_dir, meta, dry_run, stats):
        old_id = meta.get('id', '?')
        role = meta.get('role', 'New Campaign')
        status = STATUS_MAP.get(meta.get('status'), 'draft')
        form_url = meta.get('form_url', '')

        # Empty placeholder drafts (never had a JD, never launched) aren't
        # worth carrying into the new schema — they were exactly the
        # unbounded clutter problem the old ensure_active_campaign() caused.
        if status == 'draft' and role in ('New Campaign', '') and not form_url:
            stats['skipped_empty'] += 1
            return

        state = {}
        state_path = os.path.join(user_dir, f'campaign_{old_id}.json')
        if os.path.exists(state_path):
            try:
                state = json.load(open(state_path, encoding='utf-8'))
            except (json.JSONDecodeError, OSError) as e:
                self.stdout.write(self.style.ERROR(f"  user_{user.id}/{old_id}: unreadable state file: {e}"))

        form_id = state.get('form_id', '')

        existing = Campaign.objects.filter(owner=user, role=role, form_id=form_id).exists()
        if existing:
            stats['skipped_existing'] += 1
            return

        self.stdout.write(f"  user_{user.id}/{old_id}: {role!r} ({status}) — "
                           f"{len(state.get('candidates', []))} candidate(s)")
        stats['campaigns'] += 1
        if dry_run:
            stats['candidates'] += len(state.get('candidates', []))
            return

        campaign = Campaign.objects.create(
            owner=user,
            role=role,
            status=status,
            form_id=form_id,
            form_url=form_url or state.get('form_url', ''),
            sheet_id=state.get('sheet_id', ''),
            sheet_url=meta.get('sheet_url', '') or state.get('sheet_url', ''),
            drive_qid=state.get('drive_qid') or '',
            email_qid=state.get('email_qid') or '',
            linkedin_post_id=state.get('linkedin_post_id') or '',
        )
        created_at = parse_datetime(meta.get('created_at', '')) or timezone.now()
        if timezone.is_naive(created_at):
            created_at = timezone.make_aware(created_at, timezone.get_current_timezone())
        # auto_now_add would otherwise stamp "now" on every save(); .update()
        # bypasses that so the original date is preserved.
        Campaign.objects.filter(pk=campaign.pk).update(created_at=created_at)

        for cand in state.get('candidates', []):
            email = (cand.get('email') or '').strip()
            if not email:
                continue
            text_preview = cand.get('text_preview', '')
            score = cand.get('score', 0)
            download_status = (
                'downloaded' if score or (text_preview and 'could not' not in text_preview.lower())
                else 'download_failed'
            )
            candidate, _created = Candidate.objects.get_or_create(
                campaign=campaign, email=email,
                defaults={
                    'form_response_id': cand.get('id', ''),
                    'drive_link': cand.get('drive_link', '') or '',
                    'file_id': cand.get('file_id', '') or '',
                    'score': score,
                    'text_preview': text_preview,
                    'download_status': download_status,
                },
            )
            stats['candidates'] += 1

            file_id = cand.get('file_id')
            if file_id:
                local_pdf = os.path.join(settings.MEDIA_ROOT, LEGACY_CV_DIR, f'{file_id}.pdf')
                if os.path.exists(local_pdf) and not candidate.resume:
                    with open(local_pdf, 'rb') as fh:
                        candidate.resume.save(f'{file_id}.pdf', ContentFile(fh.read()), save=True)
