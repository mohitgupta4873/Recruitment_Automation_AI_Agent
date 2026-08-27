import logging

from django.apps import AppConfig
from django.conf import settings

logger = logging.getLogger('hiring_app')


class HiringAppConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'hiring_app'

    def ready(self):
        """Configure Gemini once per process.

        This used to run inside HiringAutomator.__init__, i.e. on every single
        request, mutating process-global state each time.
        """
        api_key = getattr(settings, 'GEMINI_API_KEY', '')
        if not api_key:
            logger.warning("GEMINI_API_KEY is not set — JD generation will be unavailable.")
            return
        import google.generativeai as genai
        genai.configure(api_key=api_key)
