"""
Celery app for background work — interview invites and outcome emails (Phase
3), plus the daily resume-retention purge (Phase 4). Interview invites/
outcomes used to run synchronously inside the request, against gunicorn's
120s timeout, with no way to survive a crash mid-batch without risking a
double-send. See hiring_app/tasks.py for the tasks themselves.

Broker/backend reuse REDIS_URL — the same Redis instance django-ratelimit's
cache already requires outside DEBUG (see settings.py). No new required env
var for this phase.
"""
import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'my_hiring_project.settings')

app = Celery('my_hiring_project')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

# purge_expired_resumes (Phase 4) needs a `celery -A my_hiring_project beat`
# process running alongside the worker — beat is what actually fires
# schedule entries; a worker with no beat process never runs this on its own.
# Not deployed anywhere yet (see render.yaml) — add a `beat` service before
# relying on retention purging actually happening in production.
app.conf.beat_schedule = {
    'purge-expired-resumes-daily': {
        'task': 'hiring_app.tasks.purge_expired_resumes',
        'schedule': crontab(hour=3, minute=0),
    },
}
