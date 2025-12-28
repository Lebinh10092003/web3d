from pathlib import Path
import os

from django.utils.translation import gettext_lazy as _


BASE_DIR = Path(__file__).resolve().parent.parent

try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None

if load_dotenv:
    load_dotenv(BASE_DIR / ".env", override=True)

DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "django-insecure-xv#im*-mx#_54(3^tf=_y683n$_9xj$5_xe4g#e0y0om0prg)h"
    else:
        raise RuntimeError("DJANGO_SECRET_KEY is required when DEBUG is False")

ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
ALLOWED_HOSTS = [host.strip() for host in ALLOWED_HOSTS if host.strip()]
SITE_NAME = os.environ.get("SITE_NAME", "Vsteam Lab")
SITE_URL = os.environ.get("SITE_URL", "")


INSTALLED_APPS = [
    "web3d.admin_config.Web3dAdminConfig",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts",
    "library",
    "interactions",
    "gating",
    "contributions",
    "analytics",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "web3d.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "web3d.context_processors.adsense",
                "web3d.context_processors.site_meta",
            ],
        },
    },
]

WSGI_APPLICATION = "web3d.wsgi.application"


DB_PASSWORD = os.environ.get("DB_PASSWORD")
if not DB_PASSWORD:
    if DEBUG:
        DB_PASSWORD = "abc"
    else:
        raise RuntimeError("DB_PASSWORD is required when DEBUG is False")

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("DB_NAME", "web3d"),
        "USER": os.environ.get("DB_USER", "postgres"),
        "PASSWORD": DB_PASSWORD,
        "HOST": os.environ.get("DB_HOST", "localhost"),
        "PORT": os.environ.get("DB_PORT", "5432"),
    }
}


AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 9},
    },
]


LANGUAGE_CODE = os.environ.get("DJANGO_LANGUAGE_CODE", "vi")
LANGUAGES = [
    ("en", _("English")),
    ("vi", _("Vietnamese")),
]
LOCALE_PATHS = [BASE_DIR / "locale"]
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True


STATIC_URL = "/static/"
STATICFILES_DIRS = [
    BASE_DIR / "static",
]
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = os.environ.get("MEDIA_URL", "/media/")
MEDIA_ROOT = BASE_DIR / "media"
X_FRAME_OPTIONS = os.environ.get("X_FRAME_OPTIONS", "SAMEORIGIN")


AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "library:home"
LOGOUT_REDIRECT_URL = "library:home"


CONTRIBUTION_APPROVAL_POINTS = int(os.environ.get("CONTRIBUTION_APPROVAL_POINTS", "10"))
MAX_CONTRIBUTION_UPLOAD_MB = int(os.environ.get("MAX_CONTRIBUTION_UPLOAD_MB", "50"))
MAX_PREVIEW_UPLOAD_MB = int(os.environ.get("MAX_PREVIEW_UPLOAD_MB", "5"))
MAX_PDF_PREVIEW_MB = int(os.environ.get("MAX_PDF_PREVIEW_MB", "20"))

ADSENSE_CLIENT = os.environ.get("ADSENSE_CLIENT", "")
ADSENSE_SLOT_HOME = os.environ.get("ADSENSE_SLOT_HOME", "")
ADSENSE_SLOT_DETAIL = os.environ.get("ADSENSE_SLOT_DETAIL", "")
ADSENSE_SLOT_PAGE = os.environ.get("ADSENSE_SLOT_PAGE", "")


DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
