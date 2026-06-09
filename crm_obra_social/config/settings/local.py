from .base import *

DEBUG = True

ALLOWED_HOSTS = ['*']

try:
    import debug_toolbar  # noqa: F401
    INSTALLED_APPS += ['debug_toolbar']
    MIDDLEWARE = ['debug_toolbar.middleware.DebugToolbarMiddleware'] + MIDDLEWARE
    INTERNAL_IPS = ['127.0.0.1']
except ImportError:
    pass  # debug_toolbar is optional in local dev; install with: pip install django-debug-toolbar

EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
