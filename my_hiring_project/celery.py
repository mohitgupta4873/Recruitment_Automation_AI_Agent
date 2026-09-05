"""
Celery app for background work — interview invites and outcome emails, as of
Phase 3. Both used to run synchronously inside the request, against gunicorn's
120s timeout, with no way to survive a crash mid-batch without risking a
double-send. See hiring_app/tasks.py for the tasks themselves.

Broker/backend reuse REDIS_URL — the same Redis instance django-ratelimit's
cache already requires outside DEBUG (see settings.py). No new required env
var for this phase.
"""
import os

from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'my_hiring_project.settings')

app = Celery('my_hiring_project')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()
