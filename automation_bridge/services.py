import io
import mimetypes
import os
import posixpath
import uuid
from urllib import error, parse, request

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone

from blog.media import save_blog_image_variants
from blog.models import Post, PostBlock, PostRevision
from blog.views import _normalize_api_block_payload, _parse_iso_datetime, _resolve_api_author


def _abs_url(url, *, request_obj=None):
    if request_obj and isinstance(url, str) and url.startswith("/"):
        return request_obj.build_absolute_uri(url)
    return url


def _clip_text(value, max_length):
    text = str(value or "").strip()
    if len(text) <= max_length:
        return text
    return text[:max_length]


def _normalized_netloc(value):
    return (parse.urlsplit(str(value or "")).netloc or "").lower().strip()


def _is_embed_video_url(url):
    host = (parse.urlsplit(str(url or "")).netloc or "").lower()
    return any(
        domain in host
        for domain in (
            "youtube.com",
            "youtu.be",
            "vimeo.com",
            "player.vimeo.com",
        )
    )


def _guess_extension(url, content_type):
    parsed = parse.urlsplit(str(url or ""))
    ext = os.path.splitext(parsed.path or "")[1].lower()
    if ext:
        return ext
    mime = str(content_type or "").split(";", 1)[0].strip().lower()
    guessed = mimetypes.guess_extension(mime)
    return guessed or ""


def _coerce_media_list(value):
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        item = value.strip()
        return [item] if item else []
    if isinstance(value, dict):
        return [value]
    return []


def _iter_top_level_images(data):
    image_values = []
    for key in ("images", "gallery", "gallery_images", "gallery_items"):
        image_values.extend(_coerce_media_list(data.get(key)))
    normalized = []
    for item in image_values:
        if isinstance(item, str):
            url = item.strip()
            if url:
                normalized.append({"url": url, "caption": ""})
            continue
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or item.get("media_url") or item.get("src") or "").strip()
        if not url:
            continue
        normalized.append(
            {
                "url": url,
                "caption": str(item.get("caption") or "").strip(),
                "alt_text": str(item.get("alt_text") or "").strip(),
            }
        )
    return normalized


def _extract_first_text_block(blocks):
    for block in blocks:
        if not isinstance(block, dict):
            continue
        if str(block.get("type") or "").strip().upper() not in {
            PostBlock.BlockType.TEXT,
            PostBlock.BlockType.BILINGUAL_TEXT,
            "",
        }:
            continue
        text = str(block.get("text") or "").strip()
        if text:
            return text
    return ""


def _is_local_media_url(url, *, request_obj=None):
    text = str(url or "").strip()
    if not text:
        return False

    media_url = str(getattr(settings, "MEDIA_URL", "/media/") or "/media/").strip() or "/media/"
    if not media_url.startswith("/"):
        media_url = f"/{media_url}"

    parsed = parse.urlsplit(text)
    if not parsed.scheme and not parsed.netloc:
        return text.startswith(media_url)

    site_hosts = set()
    site_url = str(getattr(settings, "SITE_URL", "") or "").strip()
    if site_url:
        site_hosts.add(_normalized_netloc(site_url))
    if request_obj:
        site_hosts.add(str(request_obj.get_host() or "").lower().strip())

    return parsed.path.startswith(media_url) and _normalized_netloc(text) in {
        host for host in site_hosts if host
    }


def _passthrough_media_result(url, *, kind="auto", request_obj=None):
    resolved_url = _abs_url(url, request_obj=request_obj)
    effective_kind = str(kind or "auto").strip().lower() or "auto"
    if effective_kind == "auto":
        ext = os.path.splitext(parse.urlsplit(str(resolved_url or "")).path or "")[1].lower()
        if ext in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}:
            effective_kind = "image"
        elif ext in {".mp4", ".webm", ".mov", ".m4v"}:
            effective_kind = "video"
    return {
        "original_url": str(url or "").strip(),
        "resolved_url": resolved_url,
        "kind": effective_kind,
        "ingested": False,
    }


def _download_remote_bytes(url, *, max_bytes, timeout):
    http_request = request.Request(
        str(url).strip(),
        headers={"User-Agent": settings.BLOG_AUTOMATION_USER_AGENT},
    )
    with request.urlopen(http_request, timeout=timeout) as response:
        content_type = str(response.headers.get("Content-Type") or "").strip().lower()
        content_length = str(response.headers.get("Content-Length") or "").strip()
        if content_length:
            try:
                announced = int(content_length)
            except ValueError:
                announced = 0
            if announced > max_bytes:
                raise ValidationError(f"Remote file is too large (max {max_bytes} bytes).")

        chunks = []
        total = 0
        while True:
            chunk = response.read(64 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise ValidationError(f"Remote file is too large (max {max_bytes} bytes).")
            chunks.append(chunk)
        if total <= 0:
            raise ValidationError("Remote file is empty.")
        return b"".join(chunks), content_type


def _save_video_bytes(raw_bytes, *, source_url, request_obj=None):
    max_video_bytes = max(1, int(settings.BLOG_AUTOMATION_MAX_VIDEO_MB)) * 1024 * 1024
    if len(raw_bytes) > max_video_bytes:
        raise ValidationError("Video is too large for blog automation.")

    guessed_ext = _guess_extension(source_url, "") or ".mp4"
    folder = settings.BLOG_AUTOMATION_MEDIA_FOLDER.strip("/")
    stamp = timezone.now().strftime("%Y/%m")
    file_name = f"{uuid.uuid4().hex}{guessed_ext}"
    storage_path = posixpath.join(folder, "videos", stamp, file_name)
    stored_path = default_storage.save(storage_path, ContentFile(raw_bytes))
    return {
        "url": _abs_url(default_storage.url(stored_path), request_obj=request_obj),
        "path": stored_path,
    }


def ingest_remote_media(url, *, kind="auto", request_obj=None):
    media_url = str(url or "").strip()
    if not media_url:
        return {"original_url": "", "resolved_url": "", "kind": kind, "ingested": False}

    if _is_local_media_url(media_url, request_obj=request_obj):
        return _passthrough_media_result(media_url, kind=kind, request_obj=request_obj)

    if kind == "video" and _is_embed_video_url(media_url):
        return {
            "original_url": media_url,
            "resolved_url": media_url,
            "kind": "video",
            "ingested": False,
        }

    image_limit = max(1, int(settings.BLOG_IMAGE_MAX_UPLOAD_MB)) * 1024 * 1024
    video_limit = max(1, int(settings.BLOG_AUTOMATION_MAX_VIDEO_MB)) * 1024 * 1024
    max_bytes = video_limit if kind == "video" else max(image_limit, video_limit)
    raw_bytes, content_type = _download_remote_bytes(
        media_url,
        max_bytes=max_bytes,
        timeout=settings.BLOG_AUTOMATION_REQUEST_TIMEOUT,
    )
    mime = str(content_type or "").split(";", 1)[0].strip().lower()
    ext = _guess_extension(media_url, mime)

    effective_kind = kind
    if effective_kind == "auto":
        if mime.startswith("image/") or ext in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
            effective_kind = "image"
        elif mime.startswith("video/") or ext in {".mp4", ".webm", ".mov", ".m4v"}:
            effective_kind = "video"
        elif _is_embed_video_url(media_url):
            effective_kind = "video"
        else:
            raise ValidationError(f"Unsupported remote media type for URL: {media_url}")

    if effective_kind == "image":
        file_obj = io.BytesIO(raw_bytes)
        variants = save_blog_image_variants(
            file_obj,
            request=request_obj,
            folder_prefix=posixpath.join(settings.BLOG_AUTOMATION_MEDIA_FOLDER.strip("/"), "images"),
        )
        return {
            "original_url": media_url,
            "resolved_url": variants["url"],
            "kind": "image",
            "ingested": True,
            "variants": variants,
        }

    if effective_kind == "video":
        stored = _save_video_bytes(raw_bytes, source_url=media_url, request_obj=request_obj)
        return {
            "original_url": media_url,
            "resolved_url": stored["url"],
            "kind": "video",
            "ingested": True,
            "path": stored["path"],
        }

    raise ValidationError(f"Unsupported media kind: {effective_kind}")


def ingest_media_items(items, *, request_obj=None):
    results = []
    for item in items:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or item.get("media_url") or "").strip()
        kind = str(item.get("kind") or "auto").strip().lower() or "auto"
        if not url:
            continue
        results.append(ingest_remote_media(url, kind=kind, request_obj=request_obj))
    return results


def _normalize_sources(payload):
    raw_sources = payload.get("sources") or payload.get("research_sources") or []
    normalized = []
    if not isinstance(raw_sources, list):
        return normalized
    for item in raw_sources:
        if isinstance(item, str):
            url = item.strip()
            if url:
                normalized.append({"title": url, "url": url, "note": ""})
            continue
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        title = str(item.get("title") or url or "Source").strip()
        note = str(item.get("note") or item.get("summary") or "").strip()
        if not url:
            continue
        normalized.append({"title": title, "url": url, "note": note})
    return normalized


def _sources_block(sources):
    lines = ["Sources:"]
    for source in sources:
        title = str(source.get("title") or source.get("url") or "Source").strip()
        url = str(source.get("url") or "").strip()
        note = str(source.get("note") or "").strip()
        if note:
            lines.append(f"- {title}: {url} ({note})")
        else:
            lines.append(f"- {title}: {url}")
    return {
        "type": PostBlock.BlockType.TEXT,
        "text": "\n".join(lines),
        "data": {"sources": sources},
    }


def _resolve_status(payload):
    explicit = str(payload.get("status") or "").strip().upper()
    if explicit:
        return explicit

    mode = str(payload.get("mode") or payload.get("publish_mode") or "").strip().lower()
    mapping = {
        "draft": Post.Status.DRAFT,
        "review": Post.Status.PENDING_REVIEW,
        "publish": Post.Status.PUBLISHED,
        "schedule": Post.Status.SCHEDULED,
    }
    return mapping.get(mode, settings.BLOG_AUTOMATION_DEFAULT_STATUS)


def prepare_blog_payload(payload, *, request_obj=None):
    data = dict(payload or {})
    title = _clip_text(data.get("title") or data.get("headline"), 220)
    if not title:
        raise ValidationError("title is required for blog automation.")

    article_body = str(
        data.get("article_body")
        or data.get("article")
        or data.get("body")
        or data.get("content")
        or ""
    ).strip()
    incoming_blocks = data.get("blocks")
    has_block_list = isinstance(incoming_blocks, list)
    if not article_body and not has_block_list:
        raise ValidationError("Provide article_body/content or blocks.")

    blocks = incoming_blocks or []
    if not isinstance(blocks, list):
        blocks = []
    if not article_body:
        article_body = _extract_first_text_block(blocks)

    summary = _clip_text(data.get("summary") or article_body[:320], 320)
    if not article_body and not isinstance(data.get("blocks"), list):
        raise ValidationError("Provide article_body/content or blocks.")

    hero_image_url = str(
        data.get("hero_image_url") or data.get("hero_url") or data.get("hero") or ""
    ).strip()
    hero_payload = data.get("hero_image") if isinstance(data.get("hero_image"), dict) else {}
    if not hero_image_url:
        hero_image_url = str(hero_payload.get("url") or "").strip()

    top_level_images = _iter_top_level_images(data)
    if not hero_image_url and top_level_images:
        hero_image_url = str(top_level_images[0].get("url") or "").strip()
        top_level_images = top_level_images[1:]

    top_level_video = str(
        data.get("video_url") or data.get("video") or data.get("embed_url") or ""
    ).strip()
    top_level_video_caption = _clip_text(data.get("video_caption") or data.get("video_title"), 300)

    media_results = []
    if hero_image_url:
        hero_result = ingest_remote_media(hero_image_url, kind="image", request_obj=request_obj)
        media_results.append({"target": "hero_image_url", **hero_result})
        hero_image_url = hero_result["resolved_url"]

    if not blocks and article_body:
        blocks = [{"type": PostBlock.BlockType.TEXT, "text": article_body}]
        for image_item in top_level_images:
            blocks.append(
                {
                    "type": PostBlock.BlockType.IMAGE,
                    "media_url": image_item["url"],
                    "caption": image_item.get("caption") or "",
                    "alt_text": image_item.get("alt_text") or "",
                }
            )
        if top_level_video:
            blocks.append(
                {
                    "type": PostBlock.BlockType.VIDEO,
                    "media_url": top_level_video,
                    "caption": top_level_video_caption,
                }
            )

    processed_blocks = []
    for item in blocks:
        if not isinstance(item, dict):
            continue
        block = dict(item)
        block_type = str(block.get("type") or PostBlock.BlockType.TEXT).strip().upper()
        block["type"] = block_type

        if block_type == PostBlock.BlockType.IMAGE:
            media_url = str(block.get("media_url") or block.get("url") or "").strip()
            if media_url:
                result = ingest_remote_media(media_url, kind="image", request_obj=request_obj)
                media_results.append({"target": "block.media_url", **result})
                block["media_url"] = result["resolved_url"]

        elif block_type == PostBlock.BlockType.GALLERY:
            data_payload = block.get("data") if isinstance(block.get("data"), dict) else {}
            gallery_items = data_payload.get("items") if isinstance(data_payload.get("items"), list) else []
            if not gallery_items and isinstance(data_payload.get("gallery"), list):
                gallery_items = data_payload.get("gallery")
            if not gallery_items and isinstance(data_payload.get("images"), list):
                gallery_items = data_payload.get("images")
            resolved_items = []
            for gallery_item in gallery_items:
                if isinstance(gallery_item, str):
                    gallery_item = {"url": gallery_item}
                if not isinstance(gallery_item, dict):
                    continue
                gallery_url = str(gallery_item.get("url") or gallery_item.get("src") or "").strip()
                if not gallery_url:
                    continue
                result = ingest_remote_media(gallery_url, kind="image", request_obj=request_obj)
                media_results.append({"target": "gallery.item", **result})
                resolved_items.append(
                    {
                        "url": result["resolved_url"],
                        "caption": str(gallery_item.get("caption") or "").strip(),
                    }
                )
            data_payload["items"] = resolved_items
            block["data"] = data_payload

        elif block_type == PostBlock.BlockType.VIDEO:
            media_url = str(
                block.get("media_url")
                or block.get("video_url")
                or block.get("url")
                or block.get("embed_url")
                or ""
            ).strip()
            if media_url:
                if _is_embed_video_url(media_url):
                    result = {
                        "original_url": media_url,
                        "resolved_url": media_url,
                        "kind": "video",
                        "ingested": False,
                    }
                else:
                    result = ingest_remote_media(media_url, kind="video", request_obj=request_obj)
                media_results.append({"target": "video.media_url", **result})
                block["media_url"] = result["resolved_url"]

        processed_blocks.append(block)

    sources = _normalize_sources(data)
    if sources and settings.BLOG_AUTOMATION_INCLUDE_SOURCES_BLOCK:
        processed_blocks.append(_sources_block(sources))

    for idx, block in enumerate(processed_blocks, start=1):
        block["position"] = idx

    status_value = _resolve_status(data)
    publish_at = str(data.get("published_at") or data.get("publish_at") or "").strip()
    if status_value == Post.Status.SCHEDULED and not publish_at:
        raise ValidationError("published_at is required when mode/status is schedule.")

    author_username = str(
        data.get("author_username") or settings.BLOG_AUTOMATION_DEFAULT_AUTHOR_USERNAME or ""
    ).strip()
    seo_title = _clip_text(data.get("seo_title") or title, 240)
    seo_description = _clip_text(data.get("seo_description") or summary, 320)

    prepared = {
        "title": title,
        "summary": summary,
        "body": article_body,
        "hero_image_url": hero_image_url,
        "seo_title": seo_title,
        "seo_description": seo_description,
        "status": status_value,
        "published_at": publish_at,
        "slug": str(data.get("slug") or "").strip(),
        "author_username": author_username,
        "blocks": processed_blocks,
    }
    return prepared, media_results, sources


def create_post_from_payload(payload):
    title = str(payload.get("title") or "").strip()
    if not title:
        raise ValidationError("title_required")

    status_value = str(payload.get("status") or Post.Status.DRAFT).strip().upper()
    valid_statuses = {choice for choice, _label in Post.Status.choices}
    if status_value not in valid_statuses:
        raise ValidationError("invalid_status")

    published_raw = payload.get("published_at")
    published_at = _parse_iso_datetime(published_raw) if published_raw else timezone.now()
    if published_raw and not published_at:
        raise ValidationError("invalid_published_at")

    blocks_payload = payload.get("blocks") or []
    if not isinstance(blocks_payload, list):
        raise ValidationError("blocks_must_be_list")

    normalized_blocks = []
    for idx, item in enumerate(blocks_payload, start=1):
        normalized_blocks.append(_normalize_api_block_payload(item, index=idx))

    author, author_error = _resolve_api_author(payload)
    if author_error:
        raise ValidationError(author_error)

    summary = str(payload.get("summary") or "").strip()
    hero_image_url = str(payload.get("hero_image_url") or "").strip()
    seo_title = str(payload.get("seo_title") or "").strip()
    seo_description = str(payload.get("seo_description") or "").strip()
    slug = str(payload.get("slug") or "").strip()
    body = str(payload.get("body") or "").strip()

    try:
        with transaction.atomic():
            post = Post(
                title=title,
                summary=summary,
                body=body,
                hero_image_url=hero_image_url,
                seo_title=seo_title,
                seo_description=seo_description,
                status=status_value,
                published_at=published_at,
                author=author,
            )
            if slug:
                post.slug = slug
            post.save()

            if normalized_blocks:
                PostBlock.objects.bulk_create(
                    [PostBlock(post=post, **block_data) for block_data in normalized_blocks]
                )

            PostRevision.objects.create(
                post=post,
                created_by=author,
                is_autosave=False,
                payload=post.snapshot(),
            )
            return post, normalized_blocks
    except IntegrityError as exc:
        raise ValidationError("conflict") from exc


def build_post_response(post, *, block_count, request_obj=None):
    detail_path = reverse("blog:detail", args=[post.slug])
    url = _abs_url(detail_path, request_obj=request_obj)
    return {
        "id": str(post.id),
        "slug": post.slug,
        "url": url,
        "status": post.status,
        "published_at": post.published_at.isoformat() if post.published_at else None,
        "block_count": int(block_count),
    }
