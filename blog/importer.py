import json

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import Post, PostBlock, PostRevision


def _parse_iso_datetime(value, *, field_name: str):
    text = str(value or "").strip()
    if not text:
        return timezone.now()
    candidate = text.replace("Z", "+00:00")
    try:
        parsed = timezone.datetime.fromisoformat(candidate)
    except Exception as exc:
        raise ValidationError(f"Invalid {field_name}: {text}") from exc
    if parsed.tzinfo is None:
        parsed = timezone.make_aware(parsed)
    return parsed


def _normalize_block_type(raw_value):
    aliases = {
        "BILINGUAL": PostBlock.BlockType.BILINGUAL_TEXT,
        "TEXT_I18N": PostBlock.BlockType.BILINGUAL_TEXT,
        "I18N_TEXT": PostBlock.BlockType.BILINGUAL_TEXT,
    }
    value = str(raw_value or PostBlock.BlockType.TEXT).strip().upper()
    value = aliases.get(value, value)
    valid = {choice for choice, _label in PostBlock.BlockType.choices}
    if value not in valid:
        raise ValidationError(f"Unsupported block type: {value}")
    return value


def _normalize_block_payload(payload, *, post_index: int, block_index: int):
    if not isinstance(payload, dict):
        raise ValidationError(f"Post #{post_index} block #{block_index} must be an object.")

    block_type = _normalize_block_type(payload.get("type"))
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    data = dict(data)

    text = str(payload.get("text") or "").strip()
    media_url = str(payload.get("media_url") or "").strip()
    caption = str(payload.get("caption") or "").strip()
    alt_text = str(payload.get("alt_text") or "").strip()
    align = str(payload.get("align") or "").strip()

    position_raw = payload.get("position")
    try:
        position = int(position_raw) if position_raw not in (None, "") else block_index
    except (TypeError, ValueError):
        position = block_index
    if position <= 0:
        position = block_index

    if block_type == PostBlock.BlockType.BILINGUAL_TEXT:
        i18n_data = data.get("i18n") if isinstance(data.get("i18n"), dict) else {}
        text_vi = str(
            payload.get("text_vi")
            or payload.get("vi")
            or i18n_data.get("vi")
            or data.get("vi")
            or ""
        ).strip()
        text_en = str(
            payload.get("text_en")
            or payload.get("en")
            or i18n_data.get("en")
            or data.get("en")
            or ""
        ).strip()
        if not text and text_vi:
            text = text_vi
        if not text and text_en:
            text = text_en
        if not text:
            raise ValidationError(
                f"Post #{post_index} block #{block_index}: bilingual block requires text_vi or text_en."
            )
        data["i18n"] = {"vi": text_vi, "en": text_en}

    if block_type == PostBlock.BlockType.GALLERY:
        raw_items = data.get("items")
        if not isinstance(raw_items, list):
            raw_items = data.get("gallery")
        if not isinstance(raw_items, list):
            raw_items = data.get("images")

        normalized_items = []
        if isinstance(raw_items, list):
            for raw_item in raw_items:
                if isinstance(raw_item, str):
                    url = raw_item.strip()
                    if url:
                        normalized_items.append({"url": url})
                    continue
                if not isinstance(raw_item, dict):
                    continue
                url = str(raw_item.get("url") or raw_item.get("src") or "").strip()
                if not url:
                    continue
                item_payload = {"url": url}
                caption_value = str(raw_item.get("caption") or "").strip()
                if caption_value:
                    item_payload["caption"] = caption_value
                normalized_items.append(item_payload)
        data["items"] = normalized_items

    return {
        "position": position,
        "type": block_type,
        "text": text,
        "media_url": media_url,
        "caption": caption,
        "alt_text": alt_text,
        "align": align,
        "data": data,
    }


def _normalize_post_payload(payload, *, index: int):
    if not isinstance(payload, dict):
        raise ValidationError(f"Post #{index} must be an object.")

    title = str(payload.get("title") or "").strip()
    if not title:
        raise ValidationError(f"Post #{index}: title is required.")

    status_value = str(payload.get("status") or Post.Status.DRAFT).strip().upper()
    valid_statuses = {choice for choice, _label in Post.Status.choices}
    if status_value not in valid_statuses:
        raise ValidationError(
            f"Post #{index}: invalid status '{status_value}'. Allowed: {', '.join(sorted(valid_statuses))}"
        )

    blocks_payload = payload.get("blocks") or []
    if not isinstance(blocks_payload, list):
        raise ValidationError(f"Post #{index}: blocks must be a list.")

    blocks = [
        _normalize_block_payload(item, post_index=index, block_index=block_index)
        for block_index, item in enumerate(blocks_payload, start=1)
    ]

    return {
        "title": title,
        "slug": str(payload.get("slug") or "").strip(),
        "summary": str(payload.get("summary") or "").strip(),
        "body": str(payload.get("body") or "").strip(),
        "hero_image_url": str(payload.get("hero_image_url") or "").strip(),
        "seo_title": str(payload.get("seo_title") or "").strip(),
        "seo_description": str(payload.get("seo_description") or "").strip(),
        "status": status_value,
        "published_at": _parse_iso_datetime(
            payload.get("published_at"), field_name=f"post #{index}.published_at"
        ),
        "author_username": str(payload.get("author_username") or "").strip(),
        "author_email": str(payload.get("author_email") or "").strip(),
        "blocks": blocks,
    }


def parse_bulk_posts(raw_data: str):
    text = str(raw_data or "").strip()
    if not text:
        raise ValidationError("Import data is empty.")

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"Invalid JSON: {exc.msg}") from exc

    if isinstance(payload, dict):
        posts_payload = payload.get("posts")
    elif isinstance(payload, list):
        posts_payload = payload
    else:
        raise ValidationError("Top-level JSON must be an object with 'posts' or a list.")

    if not isinstance(posts_payload, list):
        raise ValidationError("`posts` must be a list.")
    if not posts_payload:
        raise ValidationError("`posts` is empty.")

    return [
        _normalize_post_payload(item, index=index)
        for index, item in enumerate(posts_payload, start=1)
    ]


def _resolve_author(*, post_index: int, author_username: str, author_email: str, default_author=None):
    username = str(author_username or "").strip()
    email = str(author_email or "").strip()
    if not username and not email:
        return default_author

    User = get_user_model()
    if username:
        user = User.objects.filter(username=username).first()
    else:
        user = User.objects.filter(email=email).first()
    if not user:
        raise ValidationError(f"Post #{post_index}: author not found.")
    return user


def import_posts(*, posts, replace_existing: bool = False, default_author=None):
    created_posts = 0
    updated_posts = 0
    created_blocks = 0

    with transaction.atomic():
        for index, item in enumerate(posts, start=1):
            author = _resolve_author(
                post_index=index,
                author_username=item.get("author_username"),
                author_email=item.get("author_email"),
                default_author=default_author,
            )

            existing = None
            if replace_existing and item.get("slug"):
                existing = Post.objects.filter(slug=item["slug"]).first()

            if existing:
                post = existing
                post.title = item["title"]
                post.summary = item["summary"]
                post.body = item["body"]
                post.hero_image_url = item["hero_image_url"]
                post.seo_title = item["seo_title"]
                post.seo_description = item["seo_description"]
                post.status = item["status"]
                post.published_at = item["published_at"]
                post.author = author
                updated_posts += 1
            else:
                post = Post(
                    title=item["title"],
                    summary=item["summary"],
                    body=item["body"],
                    hero_image_url=item["hero_image_url"],
                    seo_title=item["seo_title"],
                    seo_description=item["seo_description"],
                    status=item["status"],
                    published_at=item["published_at"],
                    author=author,
                )
                created_posts += 1

            if item["slug"]:
                post.slug = item["slug"]

            try:
                post.save()
            except IntegrityError as exc:
                raise ValidationError(
                    f"Post #{index}: slug '{item['slug']}' already exists."
                ) from exc

            PostBlock.objects.filter(post=post).delete()
            block_objs = [PostBlock(post=post, **block_data) for block_data in item["blocks"]]
            if block_objs:
                PostBlock.objects.bulk_create(block_objs)
                created_blocks += len(block_objs)

            PostRevision.objects.create(
                post=post,
                created_by=author if author and getattr(author, "is_authenticated", False) else None,
                is_autosave=False,
                payload=post.snapshot(),
            )

    return created_posts, updated_posts, created_blocks
