import time
from urllib.parse import urlencode

from django.conf import settings
from django.core import signing
from django.core.files.storage import default_storage
from django.urls import reverse


def build_signed_url(blob_path, expires_in=None, method="GET", user_id=None, download=False):
    if not blob_path:
        return ""
    if not getattr(settings, "MEDIA_SIGNED_URLS", True):
        return default_storage.url(blob_path)

    ttl = int(expires_in or getattr(settings, "MEDIA_SIGNED_URL_TTL", 300))
    ttl = max(ttl, 30)
    payload = {
        "path": blob_path,
        "uid": int(user_id or 0),
        "exp": int(time.time()) + ttl,
    }
    token = signing.dumps(payload, salt="media")
    query = {"token": token}
    if download:
        query["download"] = "1"
    url = reverse("library:protected-media", args=[blob_path])
    return f"{url}?{urlencode(query)}"
