"""
Django settings for my_hiring_project.
Production-ready: reads all secrets from environment variables.
"""

from pathlib import Path
import os
import sys
import environ
import dj_database_url
from django.core.exceptions import ImproperlyConfigured
from django.contrib.messages import constants as message_constants

# ── Base dir ──────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent

# ── django-environ ────────────────────────────────────────────
env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, ['127.0.0.1', 'localhost']),
)
# Read .env file if it exists (local dev)
environ.Env.read_env(BASE_DIR / '.env')

# ── Core ──────────────────────────────────────────────────────
# No default: a missing SECRET_KEY must fail at boot rather than silently
# signing sessions/CSRF tokens with a key that is public in the repo history.
SECRET_KEY = env('SECRET_KEY')
DEBUG = env.bool('DEBUG', default=False)
TESTING = 'test' in sys.argv
ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=['127.0.0.1', 'localhost'])

if DEBUG:
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

CSRF_TRUSTED_ORIGINS = env.list(
    'CSRF_TRUSTED_ORIGINS',
    default=['http://127.0.0.1:8000', 'http://localhost:8000'],
)

# ── Field-level encryption (GoogleOAuthToken.token_json) ────────
# The refresh token + client secret stored there grant durable Google access;
# encrypting the column limits the blast radius of a leaked DATABASE_URL or
# backup. Required in production, same pattern as SECRET_KEY/REDIS_URL: fail
# at boot rather than silently running with plaintext or a key nobody wrote
# down. In dev, derive a deterministic (not secret — SECRET_KEY is already in
# .env) key so tokens survive a restart without needing another env var.
FIELD_ENCRYPTION_KEY = env('FIELD_ENCRYPTION_KEY', default='')
if not FIELD_ENCRYPTION_KEY:
    if DEBUG:
        import hashlib, base64
        FIELD_ENCRYPTION_KEY = base64.urlsafe_b64encode(
            hashlib.sha256(f'dev-only:{SECRET_KEY}'.encode()).digest()
        ).decode()
    else:
        raise ImproperlyConfigured(
            'FIELD_ENCRYPTION_KEY must be set when DEBUG=False: it encrypts '
            'stored Google OAuth tokens. Generate one with: '
            'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
        )

# ── Messages ──────────────────────────────────────────────────
# Map ERROR to the existing .alert-danger class in style.css rather than
# inventing an .alert-error rule.
MESSAGE_TAGS = {message_constants.ERROR: 'danger'}

# ── Auth redirects ────────────────────────────────────────────
LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/dashboard/'
LOGOUT_REDIRECT_URL = '/'

# ── Session ───────────────────────────────────────────────────
SESSION_COOKIE_AGE = 86400          # 24 hours
SESSION_COOKIE_SECURE = not DEBUG   # HTTPS only in production
CSRF_COOKIE_SECURE = not DEBUG

# ── Security hardening ────────────────────────────────────────
# SecurityMiddleware is installed but is close to a no-op without these.
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'
X_FRAME_OPTIONS = 'DENY'
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'

# Cap request bodies. Resume uploads are validated separately in forms.py.
DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024   # 5 MB
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024

if not DEBUG:
    # Render/Railway terminate TLS at a proxy. Without this, request.is_secure()
    # is False, so views.py builds an http:// OAuth redirect_uri that Google
    # rejects — and SECURE_SSL_REDIRECT below would infinite-loop.
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_SSL_REDIRECT = True
    SECURE_HSTS_SECONDS = 31536000          # 1 year
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

# ── Installed apps ───────────────────────────────────────────
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django_ratelimit',
    'hiring_app',
]

# ── Middleware ────────────────────────────────────────────────
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',   # serve static files
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'my_hiring_project.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'my_hiring_project.wsgi.application'

# ── Database ──────────────────────────────────────────────────
# Uses DATABASE_URL env var in production (Railway injects this).
# Falls back to SQLite in development.
DATABASES = {
    'default': dj_database_url.config(
        default=f'sqlite:///{BASE_DIR}/db.sqlite3',
        conn_max_age=600,
        ssl_require=not DEBUG and bool(env('DATABASE_URL', default='')),
    )
}

# ── Cache ─────────────────────────────────────────────────────
# django-ratelimit needs a shared cache with atomic increment — in practice
# Redis or Memcached. With the default per-process LocMemCache and gunicorn
# --workers 2, a "10/m" limit is really 20/m and resets on every recycle.
REDIS_URL = env('REDIS_URL', default='')

if REDIS_URL:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.redis.RedisCache',
            'LOCATION': REDIS_URL,
        }
    }
    # W001 only says Redis isn't on django-ratelimit's officially-tested list.
    # E003 (the check that matters — atomic increment) passes, because Django's
    # RedisCache.incr() maps to Redis INCRBY.
    SILENCED_SYSTEM_CHECKS = ['django_ratelimit.W001']
elif DEBUG:
    # Local dev only. The ratelimit checks below are silenced *because* this
    # branch is dev-only — production takes the branch above or refuses to boot.
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'hiring-app-dev',
        }
    }
    SILENCED_SYSTEM_CHECKS = ['django_ratelimit.E003', 'django_ratelimit.W001']
else:
    raise ImproperlyConfigured(
        'REDIS_URL must be set when DEBUG=False: rate limiting is unenforceable '
        'without a shared cache, and login/register would be effectively open.'
    )

# ── Celery (background tasks — Phase 3) ─────────────────────────
# Interview invites and outcome emails run here instead of inline in the
# request: both used to run synchronously against gunicorn's 120s timeout,
# with no way to survive a crash mid-batch without risking a double-send.
#
# Reuses REDIS_URL rather than adding a new required env var — same instance
# django-ratelimit's cache already needs outside DEBUG. In local dev with no
# REDIS_URL (and not under the test runner), tasks run eagerly in-process —
# .delay() behaves like a normal function call, no worker required — so
# `manage.py runserver` alone is still enough to develop against. Tests always
# run eagerly regardless of REDIS_URL, so they never need a real broker.
CELERY_TASK_SERIALIZER = 'json'
CELERY_ACCEPT_CONTENT = ['json']
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 20 * 60         # hard kill
CELERY_TASK_SOFT_TIME_LIMIT = 15 * 60    # raises SoftTimeLimitExceeded first

if REDIS_URL:
    CELERY_BROKER_URL = REDIS_URL
    CELERY_RESULT_BACKEND = REDIS_URL
    CELERY_TASK_ALWAYS_EAGER = False
else:
    CELERY_TASK_ALWAYS_EAGER = True
    CELERY_TASK_EAGER_PROPAGATES = True

if TESTING:
    CELERY_TASK_ALWAYS_EAGER = True
    CELERY_TASK_EAGER_PROPAGATES = True

# ── Password validation ───────────────────────────────────────
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# ── Internationalisation ──────────────────────────────────────
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Kolkata'
USE_I18N = True
USE_TZ = True

# ── Static files (WhiteNoise) ─────────────────────────────────
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
# No STATICFILES_DIRS entry for hiring_app/static: AppDirectoriesFinder already
# collects it, and listing it twice made collectstatic warn about every file.

# Django 5.x spelling; STATICFILES_STORAGE is removed in Django 6.0.
#
# The manifest backend requires collectstatic to have run. The test runner forces
# DEBUG=False, so keying this off DEBUG alone would make `manage.py test` fail on
# a clean checkout with "Missing staticfiles manifest entry".
_manifest_static = env.bool('USE_MANIFEST_STATIC', default=not (DEBUG or TESTING))

STORAGES = {
    'default': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
    },
    'staticfiles': {
        'BACKEND': (
            'whitenoise.storage.CompressedManifestStaticFilesStorage'
            if _manifest_static
            else 'django.contrib.staticfiles.storage.StaticFilesStorage'
        ),
    },
}

# ── Media files ───────────────────────────────────────────────
MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

# ── API Keys ──────────────────────────────────────────────────
GEMINI_API_KEY = env('GEMINI_API_KEY', default='')
GOOGLE_CLIENT_SECRETS = env('GOOGLE_CLIENT_SECRETS', default='')  # JSON string in prod
ADMIN_EMAIL = env('ADMIN_EMAIL', default='')  # for error emails

# ── Admins (get 500 error emails) ─────────────────────────────
if ADMIN_EMAIL:
    ADMINS = [('Admin', ADMIN_EMAIL)]

# ── Email ─────────────────────────────────────────────────────
# Used for password reset as well as 500-error notifications, so this is no
# longer optional: without it a locked-out user has no recovery path.
DEFAULT_FROM_EMAIL = env('DEFAULT_FROM_EMAIL', default='HireAI <no-reply@hireai.app>')

if not DEBUG:
    EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
    EMAIL_HOST = env('EMAIL_HOST', default='')
    EMAIL_PORT = env.int('EMAIL_PORT', default=587)
    EMAIL_USE_TLS = True
    EMAIL_HOST_USER = env('EMAIL_HOST_USER', default='')
    EMAIL_HOST_PASSWORD = env('EMAIL_HOST_PASSWORD', default='')
    SERVER_EMAIL = env('SERVER_EMAIL', default=DEFAULT_FROM_EMAIL)
else:
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# ── Logging ───────────────────────────────────────────────────
# Production logs to stdout only: the container filesystem is ephemeral, so
# rotating files are wiped every deploy and invisible to log aggregation.
# Creating LOGS_DIR at import time also crashes on a read-only filesystem.
_LOG_HANDLERS = ['console']

if DEBUG:
    LOGS_DIR = BASE_DIR / 'logs'
    LOGS_DIR.mkdir(exist_ok=True)
    _LOG_HANDLERS = ['console', 'file', 'error_file']

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '[{levelname}] {asctime} {module} — {message}',
            'style': '{',
        },
        'simple': {
            'format': '[{levelname}] {asctime} {name} — {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
        },
        **({
            'file': {
                'class': 'logging.handlers.RotatingFileHandler',
                'filename': LOGS_DIR / 'app.log',
                'maxBytes': 5 * 1024 * 1024,  # 5 MB
                'backupCount': 3,
                'formatter': 'verbose',
            },
            'error_file': {
                'class': 'logging.handlers.RotatingFileHandler',
                'filename': LOGS_DIR / 'errors.log',
                'maxBytes': 5 * 1024 * 1024,
                'backupCount': 3,
                'level': 'ERROR',
                'formatter': 'verbose',
            },
        } if DEBUG else {}),
    },
    'loggers': {
        'django': {
            'handlers': _LOG_HANDLERS,
            'level': 'INFO',
            'propagate': True,
        },
        'django.request': {
            'handlers': _LOG_HANDLERS,
            'level': 'ERROR',
            'propagate': False,
        },
        'hiring_app': {
            'handlers': _LOG_HANDLERS,
            'level': 'DEBUG' if DEBUG else 'INFO',
            'propagate': False,
        },
    },
}

# ── Misc ──────────────────────────────────────────────────────
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
# NOTE: django_ratelimit.E003/W001 are no longer silenced — E003 is the check
# that warns when no shared cache is configured, and it was correct. See CACHES.

