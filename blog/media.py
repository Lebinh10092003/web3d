import io
import os
import uuid
from urllib.parse import urlsplit

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.utils import timezone

try:
    from PIL import Image, ImageOps, UnidentifiedImageError
except Exception:  # pragma: no cover - Pillow is optional at runtime
    Image = None
    ImageOps = None
    UnidentifiedImageError = Exception


def _abs_url(url, *, request=None):
    if request and isinstance(url, str) and url.startswith("/"):
        return request.build_absolute_uri(url)
    return url


def _setting_int(name, default):
    value = getattr(settings, name, default)
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number


def _setting_float(name, default):
    value = getattr(settings, name, default)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number


def _load_upload_bytes(file_obj, *, max_bytes):
    raw = file_obj.read()
    try:
        file_obj.seek(0)
    except Exception:
        pass

    if max_bytes > 0 and len(raw) > max_bytes:
        raise ValidationError(f"Uploaded image is too large (max {max_bytes} bytes).")
    if not raw:
        raise ValidationError("Uploaded image is empty.")
    return raw


def _to_webp_bytes(image, *, quality):
    output = io.BytesIO()
    image.save(output, format="WEBP", quality=quality, method=6)
    return output.getvalue()


def _resize_fit(image, *, max_width, max_height):
    if max_width <= 0 and max_height <= 0:
        return image.copy()

    width = max(1, int(max_width or image.width))
    height = max(1, int(max_height or image.height))
    resized = image.copy()
    resized.thumbnail((width, height), Image.Resampling.LANCZOS)
    return resized


def _cover_crop(image, *, width, height):
    return ImageOps.fit(
        image,
        (max(1, int(width)), max(1, int(height))),
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.5),
    )


def _to_rgb(image):
    if image.mode in {"RGB", "RGBA"}:
        if image.mode == "RGBA":
            return image.convert("RGB")
        return image
    return image.convert("RGB")


def save_blog_image_variants(file_obj, *, request=None, folder_prefix="blog/images"):
    if Image is None or ImageOps is None:
        raise ValidationError("Image processing is unavailable on server.")

    max_upload_mb = _setting_int("BLOG_IMAGE_MAX_UPLOAD_MB", 12)
    max_upload_bytes = max(1, max_upload_mb) * 1024 * 1024
    max_width = _setting_int("BLOG_IMAGE_MAX_WIDTH", 2200)
    max_height = _setting_int("BLOG_IMAGE_MAX_HEIGHT", 2200)
    thumb_width = _setting_int("BLOG_IMAGE_THUMB_WIDTH", 800)
    thumb_height = _setting_int("BLOG_IMAGE_THUMB_HEIGHT", 450)
    og_width = _setting_int("BLOG_IMAGE_OG_WIDTH", 1200)
    og_height = _setting_int("BLOG_IMAGE_OG_HEIGHT", 630)
    webp_quality = int(_setting_float("BLOG_IMAGE_WEBP_QUALITY", 84.0))
    webp_quality = min(100, max(60, webp_quality))

    raw = _load_upload_bytes(file_obj, max_bytes=max_upload_bytes)
    try:
        src = Image.open(io.BytesIO(raw))
        src.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise ValidationError("Uploaded file is not a valid image.") from exc

    src = ImageOps.exif_transpose(src)
    src = _to_rgb(src)
    main_img = _resize_fit(src, max_width=max_width, max_height=max_height)
    thumb_img = _resize_fit(main_img, max_width=thumb_width, max_height=thumb_height)
    og_img = _cover_crop(main_img, width=og_width, height=og_height)

    main_bytes = _to_webp_bytes(main_img, quality=webp_quality)
    thumb_bytes = _to_webp_bytes(thumb_img, quality=webp_quality)
    og_bytes = _to_webp_bytes(og_img, quality=webp_quality)

    stamp = timezone.now().strftime("%Y/%m")
    base_name = uuid.uuid4().hex
    root = f"{folder_prefix.strip('/')}/{stamp}/{base_name}"
    main_path = f"{root}.webp"
    thumb_path = f"{root}__thumb.webp"
    og_path = f"{root}__og.webp"

    stored_main = default_storage.save(main_path, ContentFile(main_bytes))
    stored_thumb = default_storage.save(thumb_path, ContentFile(thumb_bytes))
    stored_og = default_storage.save(og_path, ContentFile(og_bytes))

    main_url = _abs_url(default_storage.url(stored_main), request=request)
    thumb_url = _abs_url(default_storage.url(stored_thumb), request=request)
    og_url = _abs_url(default_storage.url(stored_og), request=request)

    return {
        "url": main_url,
        "thumb_url": thumb_url,
        "og_url": og_url,
        "paths": {
            "main": stored_main,
            "thumb": stored_thumb,
            "og": stored_og,
        },
    }


def _relative_storage_path_from_url(url):
    text = str(url or "").strip()
    if not text:
        return ""

    parsed = urlsplit(text)
    path = parsed.path if parsed.scheme or parsed.netloc else text
    path = str(path or "").strip()
    if not path:
        return ""

    media_url = str(getattr(settings, "MEDIA_URL", "") or "")
    base_url = str(getattr(default_storage, "base_url", "") or media_url)
    if base_url and path.startswith(base_url):
        rel = path[len(base_url) :]
        return rel.lstrip("/")

    if media_url and path.startswith(media_url):
        rel = path[len(media_url) :]
        return rel.lstrip("/")

    return path.lstrip("/")


def resolve_blog_og_image_url(image_url, *, request=None):
    text = str(image_url or "").strip()
    if not text:
        return ""

    rel = _relative_storage_path_from_url(text)
    if rel:
        stem, _ext = os.path.splitext(rel)
        og_rel = f"{stem}__og.webp"
        try:
            if default_storage.exists(og_rel):
                return _abs_url(default_storage.url(og_rel), request=request)
        except Exception:
            pass

    return text
