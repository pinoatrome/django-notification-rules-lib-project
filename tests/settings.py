"""The smallest Django configuration the tests need: the auth models (users, groups, permissions), the admin, in an
in-memory database, with Django REST framework when it's installed (the tox env `nodrf` runs without). This is the
library's own test setup, not a recommendation for an app."""

import importlib.util

SECRET_KEY = "tests-only"
DRF = importlib.util.find_spec("rest_framework") is not None
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    *(["rest_framework"] if DRF else []),
    "django_notification_rules",
    "tests",  # its events and recipients modules hold the tests' event types and resolvers (discovered as an app's)
]
MIDDLEWARE = [
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]
ROOT_URLCONF = "tests.urls"
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
LANGUAGE_CODE = "en"
LANGUAGES = [("en", "English"), ("it", "Italiano")]
STATIC_URL = "/static/"
# A test that wants the cache turns it on (tests/test_cache.py): with it, a rule changed inside a test's transaction
# would be read from the cache, which is dropped only on commit.
NOTIFICATION_RULES = {
    "CACHE": None,
    "CHANNELS": {
        "inbox": {"BACKEND": "django_notification_rules.channels.inbox.InboxChannel"},
        "memory": {"BACKEND": "django_notification_rules.channels.memory.MemoryChannel"},
        "console": {"BACKEND": "django_notification_rules.channels.console.ConsoleChannel"},
    },
}
