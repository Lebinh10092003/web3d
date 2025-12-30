from pathlib import Path
import os

from django.utils.translation import gettext_lazy as _


BASE_DIR = Path(__file__).resolve().parent.parent

try:
    from dotenv import load_dotenv, dotenv_values
except Exception:
    load_dotenv = None
    dotenv_values = None

if load_dotenv:
    env_path = BASE_DIR / ".env"
    env_local_path = BASE_DIR / ".env_local"
    debug_value = os.environ.get("DJANGO_DEBUG")
    if debug_value is None and dotenv_values and env_local_path.exists():
        debug_value = dotenv_values(env_local_path).get("DJANGO_DEBUG")
    if debug_value == "1" and env_local_path.exists():
        load_dotenv(env_local_path, override=True)
    else:
        load_dotenv(env_path, override=True)

DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "django-insecure-xv#im*-mx#_54(3^tf=_y683n$_9xj$5_xe4g#e0y0om0prg)h"
    else:
        raise RuntimeError("DJANGO_SECRET_KEY is required when DEBUG is False")

ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
ALLOWED_HOSTS = [host.strip() for host in ALLOWED_HOSTS if host.strip()]
SITE_NAME = os.environ.get("SITE_NAME", "V+ STEAM LAB Library")
SITE_URL = os.environ.get("SITE_URL", "")


INSTALLED_APPS = [
    "web3d.admin_config.Web3dAdminConfig",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_rq",
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
        "CONN_MAX_AGE": int(os.environ.get("DB_CONN_MAX_AGE", "60")),
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
MEDIA_SIGNED_URLS = os.environ.get("MEDIA_SIGNED_URLS", "1") == "1"
MEDIA_SIGNED_URL_TTL = int(os.environ.get("MEDIA_SIGNED_URL_TTL", "300"))
MEDIA_SIGNED_URL_HIDE_PATH = os.environ.get("MEDIA_SIGNED_URL_HIDE_PATH", "1") == "1"
MEDIA_SIGNED_URL_OG_TTL = int(os.environ.get("MEDIA_SIGNED_URL_OG_TTL", "86400"))
MEDIA_ACCEL_REDIRECT_PREFIX = os.environ.get("MEDIA_ACCEL_REDIRECT_PREFIX", "")
USE_SIGNED_DOWNLOADS = os.environ.get("USE_SIGNED_DOWNLOADS", "1") == "1"
X_FRAME_OPTIONS = os.environ.get("X_FRAME_OPTIONS", "SAMEORIGIN")

LEGO_THREE_BASE_URL = os.environ.get(
    "LEGO_THREE_BASE_URL", "https://cdn.jsdelivr.net/npm/three@0.160.0"
)

USE_BACKGROUND_JOBS = os.environ.get("USE_BACKGROUND_JOBS", "1") == "1"
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
RQ_DEFAULT_TIMEOUT = int(os.environ.get("RQ_DEFAULT_TIMEOUT", "600"))
RQ_QUEUES = {
    "default": {
        "URL": REDIS_URL,
        "DEFAULT_TIMEOUT": RQ_DEFAULT_TIMEOUT,
    }
}

ZALOPAY_APP_ID = os.environ.get("ZALOPAY_APP_ID", "")
ZALOPAY_KEY1 = os.environ.get("ZALOPAY_KEY1", "")
ZALOPAY_KEY2 = os.environ.get("ZALOPAY_KEY2", "")
ZALOPAY_ENDPOINT_CREATE = os.environ.get(
    "ZALOPAY_ENDPOINT_CREATE", "https://sb-openapi.zalopay.vn/v2/create"
)
ZALOPAY_CALLBACK_URL = os.environ.get("ZALOPAY_CALLBACK_URL", "")
ZALOPAY_RETURN_URL = os.environ.get("ZALOPAY_RETURN_URL", "")


AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "library:home"
LOGOUT_REDIRECT_URL = "library:home"


CONTRIBUTION_APPROVAL_POINTS = int(os.environ.get("CONTRIBUTION_APPROVAL_POINTS", "10"))
MAX_CONTRIBUTION_UPLOAD_MB = int(os.environ.get("MAX_CONTRIBUTION_UPLOAD_MB", "50"))
MAX_PREVIEW_UPLOAD_MB = int(os.environ.get("MAX_PREVIEW_UPLOAD_MB", "5"))
MAX_PDF_PREVIEW_MB = int(os.environ.get("MAX_PDF_PREVIEW_MB", "20"))
PREBUILD_LDRAW_ON_APPROVAL = os.environ.get("PREBUILD_LDRAW_ON_APPROVAL", "1") == "1"
RATE_LIMIT_LDRAW_PER_MIN = int(os.environ.get("RATE_LIMIT_LDRAW_PER_MIN", "30"))
RATE_LIMIT_PREVIEW_PER_MIN = int(os.environ.get("RATE_LIMIT_PREVIEW_PER_MIN", "60"))
RATE_LIMIT_DOWNLOAD_PER_MIN = int(os.environ.get("RATE_LIMIT_DOWNLOAD_PER_MIN", "20"))

SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = False
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"

if not DEBUG:
    SECURE_SSL_REDIRECT = os.environ.get("SECURE_SSL_REDIRECT", "1") == "1"
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "1") == "1"
    CSRF_COOKIE_SECURE = os.environ.get("CSRF_COOKIE_SECURE", "1") == "1"
    SECURE_HSTS_SECONDS = int(os.environ.get("SECURE_HSTS_SECONDS", "31536000"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = (
        os.environ.get("SECURE_HSTS_INCLUDE_SUBDOMAINS", "1") == "1"
    )
    SECURE_HSTS_PRELOAD = os.environ.get("SECURE_HSTS_PRELOAD", "0") == "1"
    if os.environ.get("SECURE_PROXY_SSL_HEADER", "1") == "1":
        SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

ADSENSE_CLIENT = os.environ.get("ADSENSE_CLIENT", "")
ADSENSE_SLOT_HOME = os.environ.get("ADSENSE_SLOT_HOME", "")
ADSENSE_SLOT_DETAIL = os.environ.get("ADSENSE_SLOT_DETAIL", "")
ADSENSE_SLOT_PAGE = os.environ.get("ADSENSE_SLOT_PAGE", "")


DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
