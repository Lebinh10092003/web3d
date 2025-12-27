from django.core.files.storage import default_storage


def build_signed_url(blob_path, expires_in=None, method="GET"):
    if not blob_path:
        return ""
    return default_storage.url(blob_path)
