"""Django settings for the example development server.

Extends the test settings pattern with a persistent SQLite database,
static file serving, and DEBUG mode for local development.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = "example-dev-key-not-for-production"
SALT_KEY = "example-salt-key-not-for-production"
DEBUG = True
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.messages",
    "django.contrib.sessions",
    "django.contrib.staticfiles",
    "django_program.conference",
    "django_program.registration",
    "django_program.pretalx",
    "django_program.sponsors",
    "django_program.programs",
    "django_program.manage",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

ROOT_URLCONF = "urls"

import django_program  # noqa: E402

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [Path(django_program.__file__).resolve().parent / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "django_program.context_processors.program_features",
            ],
        },
    },
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True

STATIC_URL = "static/"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

FIELD_ENCRYPTION_KEY = os.environ.get("FIELD_ENCRYPTION_KEY", "YBkocJMq0EEDhDBHQk2eMdBPhQrUzV8adaSz4mbHcFQ=")

LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/manage/"

DJANGO_PROGRAM = {
    "pretalx": {
        "base_url": os.environ.get("PRETALX_BASE_URL", "https://pretalx.com"),
        "token": os.environ.get("PRETALX_TOKEN", ""),
    },
    "psf_sponsors": {
        "token": os.environ.get("PSF_SPONSOR_API_TOKEN", ""),
    },
}
