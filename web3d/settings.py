from pathlib import Path
import os

from django.utils.translation import gettext_lazy as _


BASE_DIR = Path(__file__).resolve().parent.parent

try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None

if load_dotenv:
    env_path = BASE_DIR / ".env"
    env_local_path = BASE_DIR / ".env_local"
    if env_local_path.exists():
        load_dotenv(env_local_path, override=True)
    elif env_path.exists():
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
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]
SITE_NAME = os.environ.get("SITE_NAME", "V+ STEAM LAB Library")
SITE_URL = os.environ.get("SITE_URL", "")
SUPPORT_CHAT_ENABLED = os.environ.get("SUPPORT_CHAT_ENABLED", "0") == "1"
SUPPORT_CHAT_TITLE = os.environ.get("SUPPORT_CHAT_TITLE", "Chat with us").strip() or "Chat with us"
SUPPORT_CHAT_SUBTITLE = (
    os.environ.get("SUPPORT_CHAT_SUBTITLE", "Leave a message and we will reply here.")
    .strip()
    or "Leave a message and we will reply here."
)
SUPPORT_CHAT_AUTO_REPLY_MESSAGE = (
    os.environ.get(
        "SUPPORT_CHAT_AUTO_REPLY_MESSAGE",
        "Thanks for your message. We will reply here soon. If urgent, please leave your phone number.",
    ).strip()
    or "Thanks for your message. We will reply here soon. If urgent, please leave your phone number."
)
SUPPORT_CHAT_POLL_INTERVAL_MS = int(os.environ.get("SUPPORT_CHAT_POLL_INTERVAL_MS", "5000"))
SUPPORT_CHAT_MESSAGE_MAX_CHARS = int(os.environ.get("SUPPORT_CHAT_MESSAGE_MAX_CHARS", "1200"))
SUPPORT_CHAT_OPERATOR_TOKEN = os.environ.get("SUPPORT_CHAT_OPERATOR_TOKEN", "").strip()
SUPPORT_CHAT_OPENCLAW_BASE_URL = os.environ.get("SUPPORT_CHAT_OPENCLAW_BASE_URL", "").strip().rstrip("/")
SUPPORT_CHAT_OPENCLAW_HOOK_PATH = (
    os.environ.get("SUPPORT_CHAT_OPENCLAW_HOOK_PATH", "/hooks/agent").strip()
    or "/hooks/agent"
)
SUPPORT_CHAT_OPENCLAW_HOOK_TOKEN = os.environ.get("SUPPORT_CHAT_OPENCLAW_HOOK_TOKEN", "").strip()
SUPPORT_CHAT_OPENCLAW_AGENT_ID = (
    os.environ.get("SUPPORT_CHAT_OPENCLAW_AGENT_ID", "support").strip() or "support"
)
SUPPORT_CHAT_OWNER_WHATSAPP = os.environ.get("SUPPORT_CHAT_OWNER_WHATSAPP", "").strip()
SUPPORT_CHAT_REQUEST_TIMEOUT = float(os.environ.get("SUPPORT_CHAT_REQUEST_TIMEOUT", "10"))
BLOG_AUTOMATION_ENABLED = os.environ.get("BLOG_AUTOMATION_ENABLED", "0") == "1"
BLOG_AUTOMATION_TOKEN = os.environ.get("BLOG_AUTOMATION_TOKEN", "").strip()
BLOG_AUTOMATION_DEFAULT_STATUS = (
    os.environ.get("BLOG_AUTOMATION_DEFAULT_STATUS", "PENDING_REVIEW").strip().upper()
    or "PENDING_REVIEW"
)
BLOG_AUTOMATION_DEFAULT_AUTHOR_USERNAME = (
    os.environ.get("BLOG_AUTOMATION_DEFAULT_AUTHOR_USERNAME", "").strip()
)
BLOG_AUTOMATION_REQUEST_TIMEOUT = float(os.environ.get("BLOG_AUTOMATION_REQUEST_TIMEOUT", "20"))
BLOG_AUTOMATION_MAX_VIDEO_MB = int(os.environ.get("BLOG_AUTOMATION_MAX_VIDEO_MB", "80"))
BLOG_AUTOMATION_MEDIA_FOLDER = (
    os.environ.get("BLOG_AUTOMATION_MEDIA_FOLDER", "blog/automation").strip()
    or "blog/automation"
)
BLOG_AUTOMATION_INCLUDE_SOURCES_BLOCK = (
    os.environ.get("BLOG_AUTOMATION_INCLUDE_SOURCES_BLOCK", "1") == "1"
)
BLOG_AUTOMATION_USER_AGENT = (
    os.environ.get(
        "BLOG_AUTOMATION_USER_AGENT",
        "web3d-blog-automation/1.0 (+https://localhost)",
    ).strip()
    or "web3d-blog-automation/1.0 (+https://localhost)"
)


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
    "blockly_quiz",
    "blog",
    "support_chat",
    "automation_bridge",
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
    "web3d.middleware.HtmxMessageMiddleware",
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
            "libraries": {
                "user_groups": "accounts.templatetags.user_groups",
            },
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

BLOCKLY_QUIZ_BLOCKLY_VERSION = (
    os.environ.get("BLOCKLY_QUIZ_BLOCKLY_VERSION", "10.4.3").strip() or "10.4.3"
)
BLOCKLY_QUIZ_BLOCKLY_OFFICIAL_CORE_URL = (
    f"https://unpkg.com/blockly@{BLOCKLY_QUIZ_BLOCKLY_VERSION}/blockly_compressed.js"
)
BLOCKLY_QUIZ_BLOCKLY_OFFICIAL_BLOCKS_URL = (
    f"https://unpkg.com/blockly@{BLOCKLY_QUIZ_BLOCKLY_VERSION}/blocks_compressed.js"
)
BLOCKLY_QUIZ_BLOCKLY_OFFICIAL_MSG_EN_URL = (
    f"https://unpkg.com/blockly@{BLOCKLY_QUIZ_BLOCKLY_VERSION}/msg/en.js"
)
BLOCKLY_QUIZ_BLOCKLY_OFFICIAL_DEFAULT_URLS = [
    BLOCKLY_QUIZ_BLOCKLY_OFFICIAL_CORE_URL,
    BLOCKLY_QUIZ_BLOCKLY_OFFICIAL_BLOCKS_URL,
    BLOCKLY_QUIZ_BLOCKLY_OFFICIAL_MSG_EN_URL,
]
BLOCKLY_QUIZ_BLOCKLY_LEGACY_MIN_URL = "https://unpkg.com/blockly/blockly.min.js"
BLOCKLY_QUIZ_BLOCKLY_JS_URL = (
    os.environ.get("BLOCKLY_QUIZ_BLOCKLY_JS_URL", BLOCKLY_QUIZ_BLOCKLY_OFFICIAL_CORE_URL)
    .strip()
    or BLOCKLY_QUIZ_BLOCKLY_OFFICIAL_CORE_URL
)
BLOCKLY_QUIZ_BLOCKLY_JS_URLS = [
    url.strip()
    for url in os.environ.get("BLOCKLY_QUIZ_BLOCKLY_JS_URLS", "").split(",")
    if url.strip()
]
if not BLOCKLY_QUIZ_BLOCKLY_JS_URLS:
    if BLOCKLY_QUIZ_BLOCKLY_JS_URL in {
        BLOCKLY_QUIZ_BLOCKLY_LEGACY_MIN_URL,
        BLOCKLY_QUIZ_BLOCKLY_OFFICIAL_CORE_URL,
    }:
        BLOCKLY_QUIZ_BLOCKLY_JS_URLS = BLOCKLY_QUIZ_BLOCKLY_OFFICIAL_DEFAULT_URLS
    else:
        BLOCKLY_QUIZ_BLOCKLY_JS_URLS = [BLOCKLY_QUIZ_BLOCKLY_JS_URL]
BLOCKLY_QUIZ_BLOCKLY_MEDIA_URL = (
    os.environ.get(
        "BLOCKLY_QUIZ_BLOCKLY_MEDIA_URL",
        f"https://unpkg.com/blockly@{BLOCKLY_QUIZ_BLOCKLY_VERSION}/media/",
    )
    .strip()
    or f"https://unpkg.com/blockly@{BLOCKLY_QUIZ_BLOCKLY_VERSION}/media/"
)
BLOCKLY_QUIZ_SCRATCHBLOCKS_JS_URL = (
    os.environ.get(
        "BLOCKLY_QUIZ_SCRATCHBLOCKS_JS_URL",
        "https://scratchblocks.github.io/js/scratchblocks-v3.6.1-min.js",
    )
    .strip()
    or "https://scratchblocks.github.io/js/scratchblocks-v3.6.1-min.js"
)
BLOCKLY_QUIZ_GSHEET_URL = os.environ.get("BLOCKLY_QUIZ_GSHEET_URL", "").strip()
BLOCKLY_QUIZ_GSHEET_TIMEOUT = int(os.environ.get("BLOCKLY_QUIZ_GSHEET_TIMEOUT", "10"))

YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
BLOG_POST_API_KEY = os.environ.get("BLOG_POST_API_KEY", "").strip()
BLOG_POST_API_KEYS = os.environ.get("BLOG_POST_API_KEYS", "").strip()
BLOG_API_MAX_BODY_BYTES = int(os.environ.get("BLOG_API_MAX_BODY_BYTES", "600000"))
BLOG_IMPORT_MAX_JSON_BYTES = int(os.environ.get("BLOG_IMPORT_MAX_JSON_BYTES", "800000"))
RATE_LIMIT_BLOG_API_POST_PER_MIN = int(os.environ.get("RATE_LIMIT_BLOG_API_POST_PER_MIN", "40"))
BLOG_IMAGE_MAX_UPLOAD_MB = int(os.environ.get("BLOG_IMAGE_MAX_UPLOAD_MB", "12"))
BLOG_IMAGE_MAX_WIDTH = int(os.environ.get("BLOG_IMAGE_MAX_WIDTH", "2200"))
BLOG_IMAGE_MAX_HEIGHT = int(os.environ.get("BLOG_IMAGE_MAX_HEIGHT", "2200"))
BLOG_IMAGE_THUMB_WIDTH = int(os.environ.get("BLOG_IMAGE_THUMB_WIDTH", "800"))
BLOG_IMAGE_THUMB_HEIGHT = int(os.environ.get("BLOG_IMAGE_THUMB_HEIGHT", "450"))
BLOG_IMAGE_OG_WIDTH = int(os.environ.get("BLOG_IMAGE_OG_WIDTH", "1200"))
BLOG_IMAGE_OG_HEIGHT = int(os.environ.get("BLOG_IMAGE_OG_HEIGHT", "630"))
BLOG_IMAGE_WEBP_QUALITY = float(os.environ.get("BLOG_IMAGE_WEBP_QUALITY", "84"))

USE_BACKGROUND_JOBS = os.environ.get("USE_BACKGROUND_JOBS", "1") == "1"
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
RQ_DEFAULT_TIMEOUT = int(os.environ.get("RQ_DEFAULT_TIMEOUT", "600"))
RQ_QUEUES = {
    "default": {
        "URL": REDIS_URL,
        "DEFAULT_TIMEOUT": RQ_DEFAULT_TIMEOUT,
    }
}

# Caching (optional): enable Redis cache by setting USE_REDIS_CACHE=1 or DJANGO_CACHE_URL.
USE_REDIS_CACHE = os.environ.get("USE_REDIS_CACHE", "0") == "1"
DJANGO_CACHE_URL = os.environ.get("DJANGO_CACHE_URL", "").strip()
if USE_REDIS_CACHE or DJANGO_CACHE_URL:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": DJANGO_CACHE_URL or REDIS_URL,
        }
    }

LIBRARY_GRID_CACHE_TTL = int(os.environ.get("LIBRARY_GRID_CACHE_TTL", "60"))
CONTENT_VIEW_LOG_TTL = int(os.environ.get("CONTENT_VIEW_LOG_TTL", "900"))
USE_FULLTEXT_SEARCH = os.environ.get("USE_FULLTEXT_SEARCH", "1") == "1"
POSTGRES_FTS_CONFIG = os.environ.get("POSTGRES_FTS_CONFIG", "simple")

ZALOPAY_APP_ID = os.environ.get("ZALOPAY_APP_ID", "")
ZALOPAY_KEY1 = os.environ.get("ZALOPAY_KEY1", "")
ZALOPAY_KEY2 = os.environ.get("ZALOPAY_KEY2", "")
ZALOPAY_ENDPOINT_CREATE = os.environ.get(
    "ZALOPAY_ENDPOINT_CREATE", "https://sb-openapi.zalopay.vn/v2/create"
)
ZALOPAY_CALLBACK_URL = os.environ.get("ZALOPAY_CALLBACK_URL", "")
ZALOPAY_RETURN_URL = os.environ.get("ZALOPAY_RETURN_URL", "")
ZALOPAY_TOPUP_CALLBACK_URL = os.environ.get("ZALOPAY_TOPUP_CALLBACK_URL", "")
ZALOPAY_TOPUP_RETURN_URL = os.environ.get("ZALOPAY_TOPUP_RETURN_URL", "")


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

SENTRY_DSN = os.environ.get("SENTRY_DSN", "").strip()
SENTRY_TRACES_SAMPLE_RATE = float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.0"))
if SENTRY_DSN:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.django import DjangoIntegration

        sentry_sdk.init(
            dsn=SENTRY_DSN,
            integrations=[DjangoIntegration()],
            traces_sample_rate=max(0.0, min(1.0, SENTRY_TRACES_SAMPLE_RATE)),
            send_default_pii=False,
        )
    except Exception:
        pass


DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
