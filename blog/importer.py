import json
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import DataError, IntegrityError, transaction
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


_IFRAME_SRC_PATTERN = re.compile(r"""src\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
_MARKDOWN_LINK_PATTERN = re.compile(r"""^\s*\[[^\]]*\]\((?P<url>.+)\)\s*$""", re.DOTALL)
_TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "igshid",
    "mc_cid",
    "mc_eid",
    "ref",
    "source",
    "utm_campaign",
    "utm_content",
    "utm_id",
    "utm_medium",
    "utm_name",
    "utm_source",
    "utm_term",
}


def _validation_error_text(exc: ValidationError):
    if hasattr(exc, "message_dict") and exc.message_dict:
        parts = []
        for field, messages in exc.message_dict.items():
            for message in messages:
                parts.append(f"{field}: {message}")
        if parts:
            return "; ".join(parts)
    if exc.messages:
        return "; ".join(str(message) for message in exc.messages)
    return str(exc)


def _extract_iframe_src(value):
    text = str(value or "").strip()
    if not text:
        return ""
    if "<iframe" not in text.lower():
        return text
    match = _IFRAME_SRC_PATTERN.search(text)
    if not match:
        return ""
    return match.group(1).strip()


def _unwrap_markdown_url(value):
    text = str(value or "").strip()
    if not text:
        return ""

    markdown_match = _MARKDOWN_LINK_PATTERN.match(text)
    if markdown_match:
        candidate = str(markdown_match.group("url") or "").strip()
        if candidate:
            text = candidate

    if text.startswith("<") and text.endswith(">"):
        inner = text[1:-1].strip()
        if inner:
            text = inner

    if text.startswith("`") and text.endswith("`"):
        inner = text[1:-1].strip()
        if inner:
            text = inner

    return text


def _strip_tracking_params(url_text):
    text = str(url_text or "").strip()
    if not text:
        return ""
    try:
        parsed = urlsplit(text)
    except Exception:
        return text
    if parsed.scheme not in {"http", "https"}:
        return text
    if not parsed.query:
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", parsed.fragment))

    kept_params = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if str(key or "").lower() not in _TRACKING_QUERY_KEYS
    ]
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            urlencode(kept_params, doseq=True),
            parsed.fragment,
        )
    )


def _normalize_url(value):
    text = _unwrap_markdown_url(value)
    if not text:
        return ""
    return _strip_tracking_params(text).strip()


def _validate_post_char_limit(value: str, *, field_name: str, max_length: int, post_index: int):
    if max_length and len(value) > max_length:
        raise ValidationError(f"Post #{post_index}: {field_name} exceeds {max_length} characters.")
    return value


def _validate_char_limit(value: str, *, field_name: str, max_length: int, post_index: int, block_index: int):
    if max_length and len(value) > max_length:
        raise ValidationError(
            f"Post #{post_index} block #{block_index}: {field_name} exceeds {max_length} characters."
        )
    return value


def _normalize_block_payload(payload, *, post_index: int, block_index: int):
    if not isinstance(payload, dict):
        raise ValidationError(f"Post #{post_index} block #{block_index} must be an object.")

    block_type = _normalize_block_type(payload.get("type"))
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    data = dict(data)

    text = str(payload.get("text") or "").strip()
    media_url = _normalize_url(payload.get("media_url"))
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
                    url = _normalize_url(raw_item)
                    if url:
                        normalized_items.append({"url": url})
                    continue
                if not isinstance(raw_item, dict):
                    continue
                url = _normalize_url(raw_item.get("url") or raw_item.get("src"))
                if not url:
                    continue
                item_payload = {"url": url}
                caption_value = str(raw_item.get("caption") or "").strip()
                if caption_value:
                    item_payload["caption"] = caption_value
                normalized_items.append(item_payload)
        data["items"] = normalized_items

    if block_type == PostBlock.BlockType.VIDEO:
        media_url = _normalize_url(
            _extract_iframe_src(
                payload.get("media_url")
                or payload.get("video_url")
                or payload.get("embed_url")
                or payload.get("url")
                or payload.get("src")
                or data.get("media_url")
                or data.get("video_url")
                or data.get("embed_url")
                or data.get("url")
                or data.get("src")
            )
        )
        if not media_url:
            raise ValidationError(
                f"Post #{post_index} block #{block_index}: video block requires media_url (or video_url/url/src)."
            )

    media_url = _validate_char_limit(
        media_url,
        field_name="media_url",
        max_length=PostBlock._meta.get_field("media_url").max_length,
        post_index=post_index,
        block_index=block_index,
    )
    caption = _validate_char_limit(
        caption,
        field_name="caption",
        max_length=PostBlock._meta.get_field("caption").max_length,
        post_index=post_index,
        block_index=block_index,
    )
    alt_text = _validate_char_limit(
        alt_text,
        field_name="alt_text",
        max_length=PostBlock._meta.get_field("alt_text").max_length,
        post_index=post_index,
        block_index=block_index,
    )
    align = _validate_char_limit(
        align,
        field_name="align",
        max_length=PostBlock._meta.get_field("align").max_length,
        post_index=post_index,
        block_index=block_index,
    )

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

    hero_image_url = _normalize_url(payload.get("hero_image_url"))
    hero_image_url = _validate_post_char_limit(
        hero_image_url,
        field_name="hero_image_url",
        max_length=Post._meta.get_field("hero_image_url").max_length,
        post_index=index,
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
        "hero_image_url": hero_image_url,
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
    text = str(raw_data or "")
    if not text.strip():
        raise ValidationError("Import data is empty.")

    text = _sanitize_json_text(text).strip()

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        detail = exc.msg
        if "Invalid control character" in exc.msg:
            detail = "Invalid control character in JSON string (use \\\\n for line breaks, avoid raw tabs/newlines)."
        raise ValidationError(f"Invalid JSON: {detail}") from exc

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


def _sanitize_json_text(raw_text):
    text = str(raw_text or "")
    if text.startswith("\ufeff"):
        text = text.lstrip("\ufeff")

    out = []
    in_string = False
    escaping = False

    for ch in text:
        if not in_string:
            out.append(ch)
            if ch == '"':
                in_string = True
            continue

        if escaping:
            out.append(ch)
            escaping = False
            continue

        if ch == "\\":
            out.append(ch)
            escaping = True
            continue

        if ch == '"':
            out.append(ch)
            in_string = False
            continue

        if ch == "\r":
            out.append("\\n")
            continue

        if ch == "\n":
            out.append("\\n")
            continue

        if ch == "\t":
            out.append("\\t")
            continue

        if ord(ch) < 0x20:
            out.append(f"\\u{ord(ch):04x}")
            continue

        out.append(ch)

    return "".join(out)


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
                post.full_clean()
                post.save()
            except ValidationError as exc:
                raise ValidationError(f"Post #{index}: {_validation_error_text(exc)}") from exc
            except IntegrityError as exc:
                raise ValidationError(
                    f"Post #{index}: slug '{item['slug']}' already exists."
                ) from exc
            except DataError as exc:
                raise ValidationError(f"Post #{index}: data is too long or invalid.") from exc

            PostBlock.objects.filter(post=post).delete()
            block_objs = []
            for block_index, block_data in enumerate(item["blocks"], start=1):
                block_obj = PostBlock(post=post, **block_data)
                try:
                    block_obj.full_clean(validate_unique=False)
                except ValidationError as exc:
                    raise ValidationError(
                        f"Post #{index} block #{block_index}: {_validation_error_text(exc)}"
                    ) from exc
                block_objs.append(block_obj)
            if block_objs:
                try:
                    PostBlock.objects.bulk_create(block_objs)
                except (IntegrityError, DataError) as exc:
                    raise ValidationError(
                        f"Post #{index}: unable to save blocks because one or more values are invalid."
                    ) from exc
                created_blocks += len(block_objs)

            PostRevision.objects.create(
                post=post,
                created_by=author if author and getattr(author, "is_authenticated", False) else None,
                is_autosave=False,
                payload=post.snapshot(),
            )

    return created_posts, updated_posts, created_blocks
