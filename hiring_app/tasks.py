"""
Background tasks — interview invites and outcome emails. Both used to run
synchronously inside the request, against gunicorn's 120s timeout, with no
guard against re-sending to a candidate who'd already been emailed if a
mid-batch crash forced a re-run.

Idempotency here is DB-level, not exception-based: each task re-queries for
candidates whose invite_sent_at/outcome_sent_at is still unset immediately
before running, so re-running the *same* task (a Celery retry, a redelivered
message after a worker crash, or just clicking the button again) only ever
processes whoever didn't get through last time. HiringAutomator.send_invites/
send_outcomes already wrap each individual candidate's send in its own
try/except (a single bounced address shouldn't fail the whole batch) — so a
Google API error for one candidate never propagates up to Celery as a task
failure; it's logged and the loop continues. That's why these tasks don't use
autoretry_for=(HttpError,): there's nothing at this level to catch.

What acks_late does matter for: if the *worker process* itself dies mid-task
(OOM, deploy restart, SIGKILL), the broker redelivers the message and the task
runs again — combined with the DB-level filtering above, that redelivery is
safe. This is the specific scenario ROADMAP.md's Phase 3 "Verify" section
calls out: kill the worker mid-run, restart it, confirm no one is emailed twice.
"""
import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from .services import HiringAutomator, get_user_google_creds

logger = logging.getLogger('hiring_app')


@shared_task(bind=True, acks_late=True, max_retries=3, default_retry_delay=30)
def send_invites_task(self, campaign_id, candidate_ids, organizer_name, interview_date):
    from .models import Campaign

    try:
        campaign = Campaign.objects.get(pk=campaign_id)
    except Campaign.DoesNotExist:
        logger.error(f"send_invites_task: campaign {campaign_id} no longer exists — dropping")
        return {'sent': 0, 'skipped': 0, 'failed': 0}

    # Re-filtered here, not just by the view that enqueued this: a retried or
    # redelivered task must only touch candidates still owed an invite.
    candidates = list(
        campaign.candidates.filter(pk__in=candidate_ids, invite_sent_at__isnull=True)
    )
    already_done = len(candidate_ids) - len(candidates)

    if not candidates:
        logger.info(f"send_invites_task: campaign={campaign_id} — nothing left to send")
        return {'sent': 0, 'skipped': already_done, 'failed': 0}

    creds = get_user_google_creds(campaign.owner)
    automator = HiringAutomator(creds=creds)

    try:
        results = automator.send_invites(campaign, candidates, organizer_name, interview_date)
    except ValueError:
        # Bad interview_date — the view validates this before enqueueing, so
        # this should be unreachable in practice, but don't silently retry a
        # request that will never succeed.
        raise
    except Exception as exc:
        logger.exception(f"send_invites_task failed outright for campaign={campaign_id}")
        raise self.retry(exc=exc)

    failed = sum(1 for r in results if r.startswith('Failed'))
    logger.info(
        f"send_invites_task: campaign={campaign_id} — {len(results) - failed} sent, "
        f"{failed} failed, {already_done} already done"
    )
    return {'sent': len(results) - failed, 'skipped': already_done, 'failed': failed}


@shared_task(bind=True, acks_late=True, max_retries=3, default_retry_delay=30)
def send_outcomes_task(self, campaign_id, hired_candidate_ids):
    from .models import Campaign

    try:
        campaign = Campaign.objects.get(pk=campaign_id)
    except Campaign.DoesNotExist:
        logger.error(f"send_outcomes_task: campaign {campaign_id} no longer exists — dropping")
        return {'sent': 0, 'skipped': 0, 'failed': 0}

    candidates = list(campaign.candidates.filter(outcome_sent_at__isnull=True))
    already_done = campaign.candidates.exclude(outcome_sent_at__isnull=True).count()

    if not candidates:
        logger.info(f"send_outcomes_task: campaign={campaign_id} — nothing left to send")
        campaign.status = 'completed'
        if campaign.closed_at is None:
            campaign.closed_at = timezone.now()
        campaign.save(update_fields=['status', 'closed_at', 'updated_at'])
        return {'sent': 0, 'skipped': already_done, 'failed': 0}

    creds = get_user_google_creds(campaign.owner)
    automator = HiringAutomator(creds=creds)
    hired_ids = set(hired_candidate_ids)

    try:
        results = automator.send_outcomes(campaign, candidates, hired_ids)
    except Exception as exc:
        logger.exception(f"send_outcomes_task failed outright for campaign={campaign_id}")
        raise self.retry(exc=exc)

    failed = sum(1 for r in results if r.startswith('FAILED'))
    # 'completed' regardless of individual failures: the recruiter's decision
    # was made and acted on, even if a handful of addresses bounced. Those
    # failures are visible in the count returned here, not hidden.
    campaign.status = 'completed'
    if campaign.closed_at is None:
        campaign.closed_at = timezone.now()
    campaign.save(update_fields=['status', 'closed_at', 'updated_at'])

    logger.info(
        f"send_outcomes_task: campaign={campaign_id} — {len(results) - failed} sent, "
        f"{failed} failed, {already_done} already done"
    )
    return {'sent': len(results) - failed, 'skipped': already_done, 'failed': failed}


@shared_task
def purge_expired_resumes():
    """Phase 4 retention: delete resume files and text_preview for candidates
    of a *closed* (status='completed') campaign once `closed_at +
    retention_days` has passed. Scheduled daily via app.conf.beat_schedule
    in my_hiring_project/celery.py — requires a running `celery ... beat`
    process, separate from the worker (see render.yaml).

    Iterates campaigns rather than expressing the whole thing as one queryset
    filter: retention_days varies per campaign, and Django's ORM has no clean
    way to compare `closed_at + F('retention_days') days` against now() at
    the DB level without a raw expression. Campaign volume here is small
    enough (one row per hiring campaign, not per candidate) that this is a
    non-issue in practice.

    Only ever clears the resume file + text_preview — never deletes the
    Candidate row itself (that stays until an explicit erasure request, see
    hiring_app/admin.py) and never touches campaigns that are still draft/
    active, since those have no closed_at yet to measure retention from.
    """
    from .models import Campaign

    purged_candidates = 0
    campaigns_swept = 0

    closed_campaigns = Campaign.objects.filter(status='completed', closed_at__isnull=False)
    for campaign in closed_campaigns.iterator():
        deadline = campaign.closed_at + timedelta(days=campaign.retention_days)
        if timezone.now() < deadline:
            continue

        campaigns_swept += 1
        candidates = campaign.candidates.exclude(resume='', text_preview='')
        for candidate in candidates.iterator():
            if candidate.resume:
                candidate.resume.delete(save=False)
            candidate.text_preview = ''
            candidate.save(update_fields=['resume', 'text_preview', 'updated_at'])
            purged_candidates += 1

    logger.info(
        f"purge_expired_resumes: {campaigns_swept} campaign(s) past retention, "
        f"{purged_candidates} candidate(s) purged"
    )
    return {'campaigns_swept': campaigns_swept, 'candidates_purged': purged_candidates}
