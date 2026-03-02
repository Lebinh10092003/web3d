from django.shortcuts import get_object_or_404, redirect, render
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth import get_user_model
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.http import HttpResponse, HttpResponseRedirect, HttpResponseBadRequest, JsonResponse
from django.urls import reverse
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
import logging
import json
import secrets
import uuid

from .media import resolve_blog_og_image_url, save_blog_image_variants
from .models import BlogApiAuditLog, BlogComment, Post, PostBlock, PostRevision
from .forms import BlogCommentForm, PostQuickForm


logger = logging.getLogger(__name__)

def _seo_title(post):
    return post.seo_title or post.title


def _seo_description(post):
    if post.seo_description:
        return post.seo_description
    if post.summary:
        return post.summary
    return (post.body or "")[:155]


def _get_client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        ip = forwarded.split(",")[0].strip()
        return ip or None
    ip = request.META.get("REMOTE_ADDR")
    return ip if ip else None


def _rate_limit(request, key, limit, window):
    if not limit or limit <= 0:
        return True
    if request.user.is_authenticated:
        identity = f"user:{request.user.id}"
    else:
        identity = _get_client_ip(request) or "anon"
    cache_key = f"rl:{key}:{identity}"
    try:
        count = cache.incr(cache_key)
    except ValueError:
        cache.set(cache_key, 1, timeout=window)
        count = 1
    return count <= limit


def _rate_limit_response(window):
    response = HttpResponse("Too Many Requests", status=429, content_type="text/plain")
    response["Retry-After"] = str(window)
    return response


def _get_visible_post_or_404(request, slug):
    qs = Post.objects
    if not request.user.is_staff and not request.user.is_superuser:
        qs = qs.live()
    return get_object_or_404(qs, slug=slug)


def _get_related_posts(request, post, limit=6):
    qs = Post.objects
    if not request.user.is_staff and not request.user.is_superuser:
        qs = qs.live()
    return list(
        qs.exclude(pk=post.pk).order_by("-published_at", "-created_at")[:limit]
    )


def _get_comments(post):
    return list(
        BlogComment.objects.filter(post=post, parent__isnull=True)
        .select_related("user")
        .prefetch_related("replies__user")
    )


def _render_comment_list(request, post, comments, edit_form=None, editing_comment_id=None):
    context = {
        "post": post,
        "comments": comments,
        "edit_form": edit_form,
        "editing_comment_id": editing_comment_id,
    }
    if request.headers.get("HX-Request") == "true":
        return render(request, "blog/_comment_list.html", context)
    return redirect("blog:detail", slug=post.slug)


def _can_manage_comment(user, comment):
    return user.is_authenticated and (user.is_staff or comment.user_id == user.id)


def _parse_iso_datetime(value):
    text = str(value or "").strip()
    if not text:
        return None
    candidate = text.replace("Z", "+00:00")
    try:
        parsed = timezone.datetime.fromisoformat(candidate)
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = timezone.make_aware(parsed)
    return parsed


def _normalize_api_block_type(raw_value):
    aliases = {
        "BILINGUAL": PostBlock.BlockType.BILINGUAL_TEXT,
        "TEXT_I18N": PostBlock.BlockType.BILINGUAL_TEXT,
        "I18N_TEXT": PostBlock.BlockType.BILINGUAL_TEXT,
    }
    value = str(raw_value or PostBlock.BlockType.TEXT).strip().upper()
    value = aliases.get(value, value)
    valid = {choice for choice, _label in PostBlock.BlockType.choices}
    if value not in valid:
        return PostBlock.BlockType.TEXT
    return value


def _normalize_api_block_payload(item, *, index):
    if not isinstance(item, dict):
        raise ValueError(f"Block #{index}: expected an object.")

    position_raw = item.get("position")
    try:
        position = int(position_raw) if position_raw not in (None, "") else index
    except (TypeError, ValueError):
        position = index
    if position <= 0:
        position = index

    block_type = _normalize_api_block_type(item.get("type"))
    text = str(item.get("text") or "").strip()
    media_url = str(item.get("media_url") or "").strip()
    caption = str(item.get("caption") or "").strip()
    alt_text = str(item.get("alt_text") or "").strip()
    align = str(item.get("align") or "").strip()

    data = item.get("data") if isinstance(item.get("data"), dict) else {}
    data = dict(data)

    if block_type == PostBlock.BlockType.BILINGUAL_TEXT:
        i18n_data = data.get("i18n") if isinstance(data.get("i18n"), dict) else {}
        text_vi = str(
            item.get("text_vi")
            or item.get("vi")
            or i18n_data.get("vi")
            or data.get("vi")
            or ""
        ).strip()
        text_en = str(
            item.get("text_en")
            or item.get("en")
            or i18n_data.get("en")
            or data.get("en")
            or ""
        ).strip()
        if not text and text_vi:
            text = text_vi
        if not text and text_en:
            text = text_en
        if not text:
            raise ValueError(
                f"Block #{index}: bilingual block requires text_vi or text_en."
            )
        data["i18n"] = {
            "vi": text_vi,
            "en": text_en,
        }

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
                caption_value = str(raw_item.get("caption") or "").strip()
                item_payload = {"url": url}
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


def _resolve_api_author(payload):
    author_username = str(payload.get("author_username") or "").strip()
    author_email = str(payload.get("author_email") or "").strip()
    if not author_username and not author_email:
        return None, ""

    User = get_user_model()
    if author_username:
        user = User.objects.filter(username=author_username).first()
    else:
        user = User.objects.filter(email=author_email).first()
    if not user:
        return None, "author_not_found"
    return user, ""


def _parse_api_keys():
    keys = []
    raw_multi = str(getattr(settings, "BLOG_POST_API_KEYS", "") or "").strip()
    if raw_multi:
        for idx, chunk in enumerate(raw_multi.split(","), start=1):
            token = str(chunk or "").strip()
            if not token:
                continue
            if ":" in token:
                key_id, key_value = token.split(":", 1)
                key_id = key_id.strip() or f"key{idx}"
                key_value = key_value.strip()
            else:
                key_id = f"key{idx}"
                key_value = token
            if key_value:
                keys.append((key_id, key_value))

    legacy_key = str(getattr(settings, "BLOG_POST_API_KEY", "") or "").strip()
    if legacy_key and all(existing != legacy_key for _kid, existing in keys):
        keys.insert(0, ("default", legacy_key))
    return keys


def _authenticate_api_key(request):
    configured = _parse_api_keys()
    if not configured:
        return "", "blog_api_key_not_configured", 503

    provided = str(request.headers.get("X-API-Key") or "").strip()
    if not provided:
        return "", "unauthorized", 401

    hinted_key_id = str(request.headers.get("X-API-Key-Id") or "").strip()
    for key_id, expected in configured:
        if hinted_key_id and hinted_key_id != key_id:
            continue
        if secrets.compare_digest(provided, expected):
            return key_id, "", 0

    return "", "unauthorized", 401


def _client_ip_for_api(request):
    forwarded = str(request.META.get("HTTP_X_FORWARDED_FOR") or "").strip()
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return str(request.META.get("REMOTE_ADDR") or "").strip() or None


def _safe_json_size_limit():
    try:
        limit = int(getattr(settings, "BLOG_API_MAX_BODY_BYTES", 600_000) or 600_000)
    except (TypeError, ValueError):
        return 600_000
    return max(1, limit)


def _write_api_audit_log(*, request, status_code, key_id="", request_id="", detail=None):
    payload = detail if isinstance(detail, dict) else {}
    try:
        BlogApiAuditLog.objects.create(
            route="blog.api_post_create",
            status_code=int(status_code),
            key_id=str(key_id or "")[:80],
            request_id=str(request_id or "")[:80],
            ip_address=_client_ip_for_api(request),
            user_agent=str(request.META.get("HTTP_USER_AGENT") or "")[:255],
            detail=payload,
        )
    except Exception:
        logger.exception("Failed to write blog API audit log.")


def _api_json_response(*, request, status, payload, key_id="", request_id="", detail=None):
    response = JsonResponse(payload, status=status)
    if request_id:
        response["X-Request-Id"] = request_id
    _write_api_audit_log(
        request=request,
        status_code=status,
        key_id=key_id,
        request_id=request_id,
        detail=detail,
    )
    return response


@csrf_exempt
@require_POST
def api_post_create(request):
    request_id = str(request.headers.get("X-Request-Id") or uuid.uuid4().hex).strip()[:80]
    key_id, auth_error, auth_status = _authenticate_api_key(request)
    if auth_error:
        return _api_json_response(
            request=request,
            status=auth_status,
            payload={"error": auth_error},
            request_id=request_id,
            detail={"reason": auth_error},
        )

    api_limit = int(getattr(settings, "RATE_LIMIT_BLOG_API_POST_PER_MIN", 40) or 40)
    if not _rate_limit(request, f"blog:api-post:{key_id or 'anon'}", api_limit, 60):
        return _api_json_response(
            request=request,
            status=429,
            payload={"error": "too_many_requests", "retry_after": 60},
            key_id=key_id,
            request_id=request_id,
            detail={"reason": "rate_limited"},
        )

    max_body_bytes = _safe_json_size_limit()
    if len(request.body or b"") > max_body_bytes:
        return _api_json_response(
            request=request,
            status=413,
            payload={"error": "payload_too_large", "max_bytes": max_body_bytes},
            key_id=key_id,
            request_id=request_id,
            detail={"reason": "payload_too_large", "max_bytes": max_body_bytes},
        )

    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except (TypeError, ValueError, UnicodeDecodeError):
        return _api_json_response(
            request=request,
            status=400,
            payload={"error": "invalid_json"},
            key_id=key_id,
            request_id=request_id,
            detail={"reason": "invalid_json"},
        )
    if not isinstance(payload, dict):
        return _api_json_response(
            request=request,
            status=400,
            payload={"error": "invalid_json"},
            key_id=key_id,
            request_id=request_id,
            detail={"reason": "invalid_json_type"},
        )

    title = str(payload.get("title") or "").strip()
    if not title:
        return _api_json_response(
            request=request,
            status=400,
            payload={"error": "title_required"},
            key_id=key_id,
            request_id=request_id,
            detail={"reason": "title_required"},
        )

    status_value = str(payload.get("status") or Post.Status.DRAFT).strip().upper()
    valid_statuses = {choice for choice, _label in Post.Status.choices}
    if status_value not in valid_statuses:
        return _api_json_response(
            request=request,
            status=400,
            payload={
                "error": "invalid_status",
                "allowed_statuses": sorted(valid_statuses),
            },
            key_id=key_id,
            request_id=request_id,
            detail={"reason": "invalid_status"},
        )

    published_raw = payload.get("published_at")
    published_at = _parse_iso_datetime(published_raw) if published_raw else timezone.now()
    if published_raw and not published_at:
        return _api_json_response(
            request=request,
            status=400,
            payload={"error": "invalid_published_at"},
            key_id=key_id,
            request_id=request_id,
            detail={"reason": "invalid_published_at"},
        )

    blocks_payload = payload.get("blocks") or []
    if not isinstance(blocks_payload, list):
        return _api_json_response(
            request=request,
            status=400,
            payload={"error": "blocks_must_be_list"},
            key_id=key_id,
            request_id=request_id,
            detail={"reason": "blocks_must_be_list"},
        )

    normalized_blocks = []
    for idx, item in enumerate(blocks_payload, start=1):
        try:
            normalized = _normalize_api_block_payload(item, index=idx)
        except ValueError as error:
            return _api_json_response(
                request=request,
                status=400,
                payload={"error": "invalid_block", "detail": str(error)},
                key_id=key_id,
                request_id=request_id,
                detail={"reason": "invalid_block", "block_index": idx},
            )
        normalized_blocks.append(normalized)

    author, author_error = _resolve_api_author(payload)
    if author_error:
        return _api_json_response(
            request=request,
            status=400,
            payload={"error": author_error},
            key_id=key_id,
            request_id=request_id,
            detail={"reason": author_error},
        )

    summary = str(payload.get("summary") or "").strip()
    hero_image_url = str(payload.get("hero_image_url") or "").strip()
    seo_title = str(payload.get("seo_title") or "").strip()
    seo_description = str(payload.get("seo_description") or "").strip()
    slug = str(payload.get("slug") or "").strip()

    try:
        with transaction.atomic():
            post = Post(
                title=title,
                summary=summary,
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
    except IntegrityError:
        return _api_json_response(
            request=request,
            status=409,
            payload={"error": "conflict", "detail": "Slug already exists or data integrity issue."},
            key_id=key_id,
            request_id=request_id,
            detail={"reason": "conflict"},
        )

    detail_path = reverse("blog:detail", args=[post.slug])
    return _api_json_response(
        request=request,
        status=201,
        payload={
            "id": str(post.id),
            "slug": post.slug,
            "url": detail_path,
            "status": post.status,
            "published_at": post.published_at.isoformat() if post.published_at else None,
            "block_count": len(normalized_blocks),
            "request_id": request_id,
        },
        key_id=key_id,
        request_id=request_id,
        detail={"reason": "created", "post_id": str(post.id), "slug": post.slug},
    )


def post_list(request):
    # autopublish scheduled posts when due
    Post.objects.scheduled().filter(published_at__lte=timezone.now()).update(status=Post.Status.PUBLISHED)

    posts = Post.objects.live().select_related("author").order_by("-published_at", "-created_at")
    paginator = Paginator(posts, 9)
    page_obj = paginator.get_page(request.GET.get("page") or 1)
    page_range = paginator.get_elided_page_range(
        number=page_obj.number, on_each_side=1, on_ends=1
    )
    context = {
        "page_obj": page_obj,
        "page_range": page_range,
        "page_title": _("Blog / News"),
        "seo_title": _("STEAM & Robotics Blog - V+ STEAM LAB Library"),
        "seo_description": _("News, competition insights, robot tutorials, and new STEAM resources from V+ STEAM LAB Library."),
    }
    return render(request, "blog/list.html", context)


def post_detail(request, slug):
    post = _get_visible_post_or_404(request, slug)
    blocks = post.blocks.order_by("position", "created_at")
    related_posts = _get_related_posts(request, post)
    comments = _get_comments(post)
    canonical_url = request.build_absolute_uri(request.path)
    og_image_url = resolve_blog_og_image_url(post.hero_image_url, request=request)
    seo_description = _seo_description(post)
    article_json_ld = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": post.title,
        "description": seo_description,
        "mainEntityOfPage": canonical_url,
        "datePublished": post.published_at.isoformat() if post.published_at else "",
        "dateModified": post.updated_at.isoformat() if post.updated_at else "",
        "author": {
            "@type": "Person",
            "name": post.author.get_full_name() if post.author and post.author.get_full_name() else (
                post.author.username if post.author else "V+ STEAM LAB"
            ),
        },
        "publisher": {
            "@type": "Organization",
            "name": getattr(settings, "SITE_NAME", "V+ STEAM LAB Library"),
        },
        "inLanguage": request.LANGUAGE_CODE or "vi",
    }
    if og_image_url:
        article_json_ld["image"] = [og_image_url]

    context = {
        "post": post,
        "blocks": blocks,
        "related_posts_sidebar": related_posts[:4],
        "related_posts_bottom": related_posts[:4],
        "comments": comments,
        "edit_form": None,
        "editing_comment_id": None,
        "seo_title": _seo_title(post),
        "seo_description": seo_description,
        "canonical_url": canonical_url,
        "alternate_hreflang_urls": {
            "vi": canonical_url,
            "en": canonical_url,
            "x-default": canonical_url,
        },
        "og_image_url": og_image_url,
        "article_json_ld": json.dumps(article_json_ld, ensure_ascii=False),
    }
    return render(request, "blog/detail.html", context)


@require_POST
@login_required
def add_comment(request, slug):
    limit = int(getattr(settings, "RATE_LIMIT_BLOG_COMMENT_PER_MIN", 12) or 12)
    if not _rate_limit(request, "blog:comment", limit, 60):
        return _rate_limit_response(60)
    post = _get_visible_post_or_404(request, slug)
    form = BlogCommentForm(request.POST)
    if form.is_valid():
        parent = None
        parent_id = form.cleaned_data.get("parent_id")
        if parent_id:
            parent = BlogComment.objects.filter(id=parent_id, post=post).first()
        BlogComment.objects.create(
            post=post,
            user=request.user,
            body=form.cleaned_data["body"],
            parent=parent,
        )
    else:
        messages.error(request, _("Comment could not be saved."))

    comments = _get_comments(post)
    return _render_comment_list(request, post, comments)


@login_required
def edit_comment(request, slug, comment_id):
    post = _get_visible_post_or_404(request, slug)
    comment = get_object_or_404(BlogComment, pk=comment_id, post=post)
    if not _can_manage_comment(request.user, comment) or comment.is_deleted:
        return HttpResponse(status=403)

    if request.method == "POST":
        form = BlogCommentForm(request.POST)
        if form.is_valid():
            comment.body = form.cleaned_data["body"]
            comment.save(update_fields=["body", "updated_at"])
        else:
            messages.error(request, _("Comment could not be updated."))
            comments = _get_comments(post)
            return _render_comment_list(
                request, post, comments, edit_form=form, editing_comment_id=comment.id
            )
        comments = _get_comments(post)
        return _render_comment_list(request, post, comments)

    if request.GET.get("cancel") == "1":
        comments = _get_comments(post)
        return _render_comment_list(request, post, comments)

    form = BlogCommentForm(initial={"body": comment.body})
    comments = _get_comments(post)
    return _render_comment_list(
        request, post, comments, edit_form=form, editing_comment_id=comment.id
    )


@require_POST
@login_required
def delete_comment(request, slug, comment_id):
    post = _get_visible_post_or_404(request, slug)
    comment = get_object_or_404(BlogComment, pk=comment_id, post=post)
    if not _can_manage_comment(request.user, comment) or comment.is_deleted:
        return HttpResponse(status=403)

    comment.is_deleted = True
    comment.save(update_fields=["is_deleted", "updated_at"])
    comments = _get_comments(post)
    return _render_comment_list(request, post, comments)


@login_required
@user_passes_test(lambda u: u.is_staff or u.is_superuser)
def post_quick_create(request):
    if request.method == "POST":
        form = PostQuickForm(request.POST)
        if form.is_valid():
            post = form.save(commit=False)
            post.author = request.user
            post.save()
            messages.success(request, _("Post created. You can add detailed content blocks."))
            return HttpResponseRedirect(reverse("blog:editor-edit", args=[post.pk]))
    else:
        form = PostQuickForm(initial={"status": Post.Status.DRAFT, "published_at": timezone.now()})
    return render(
        request,
        "blog/create.html",
        {
            "form": form,
            "seo_title": _("Create blog post - V+ STEAM LAB Library"),
            "seo_description": _("Compose blog posts, schedule publishing, and add content blocks."),
        },
    )


def _staff_required(user):
    return user.is_staff or user.is_superuser


@login_required
@user_passes_test(_staff_required)
def post_editor_new(request):
    return post_editor_edit(request, post_id=None)


@login_required
@user_passes_test(_staff_required)
def post_editor_edit(request, post_id=None):
    post = None
    if post_id:
        post = get_object_or_404(Post, pk=post_id)

    if request.method == "POST":
        title = request.POST.get("title", "").strip()
        if not title:
            return HttpResponseBadRequest(_("Title is required"))
        summary = request.POST.get("summary", "").strip()
        hero_image_url = request.POST.get("hero_image_url", "").strip()
        status = request.POST.get("status") or Post.Status.DRAFT
        published_at_raw = request.POST.get("published_at")
        try:
            published_at = timezone.datetime.fromisoformat(published_at_raw) if published_at_raw else timezone.now()
            if not published_at.tzinfo:
                published_at = timezone.make_aware(published_at)
        except Exception:
            published_at = timezone.now()

        blocks_json = request.POST.get("blocks_json") or "[]"
        try:
            blocks_payload = json.loads(blocks_json)
        except Exception:
            blocks_payload = []

        if post is None:
            post = Post(author=request.user)
        post.title = title
        post.summary = summary
        post.hero_image_url = hero_image_url
        post.status = status
        post.published_at = published_at
        post.save()

        # replace blocks
        PostBlock.objects.filter(post=post).delete()
        block_objs = []
        for idx, item in enumerate(blocks_payload, start=1):
            if not isinstance(item, dict):
                continue
            block_objs.append(
                PostBlock(
                    post=post,
                    position=item.get("position") or idx,
                    type=item.get("type") or PostBlock.BlockType.TEXT,
                    text=item.get("text", ""),
                    media_url=item.get("media_url", ""),
                    caption=item.get("caption", ""),
                    alt_text=item.get("alt_text", ""),
                    align=item.get("align", ""),
                    data=item.get("data") or {},
                )
            )
        if block_objs:
            PostBlock.objects.bulk_create(block_objs)

        PostRevision.objects.create(
            post=post,
            created_by=request.user,
            is_autosave=False,
            payload=post.snapshot(),
        )

        messages.success(request, _("Post saved. You can continue editing."))
        return HttpResponseRedirect(reverse("blog:editor-edit", args=[post.id]))

    initial_blocks = []
    if post:
        initial_blocks = [b.to_dict() for b in post.blocks.order_by("position", "created_at")]

    context = {
        "post": post,
        "initial_blocks_json": json.dumps(initial_blocks),
        "status_choices": Post.Status.choices,
        "selected_status": post.status if post else Post.Status.DRAFT,
        "seo_title": _("Edit blog post") if post else _("Create blog post"),
        "seo_description": _("Compose blog posts with content blocks, images, videos, and galleries."),
    }
    return render(request, "blog/editor.html", context)


@login_required
@user_passes_test(_staff_required)
def upload_media(request):
    if request.method != "POST" or "file" not in request.FILES:
        return JsonResponse({"error": "No file"}, status=400)
    file = request.FILES["file"]
    content_type = str(getattr(file, "content_type", "") or "").lower()
    if content_type and not content_type.startswith("image/"):
        return JsonResponse({"error": "invalid_file_type"}, status=400)
    try:
        variants = save_blog_image_variants(file, request=request, folder_prefix="blog/uploads")
    except ValidationError as exc:
        detail = "; ".join(exc.messages) if getattr(exc, "messages", None) else str(exc)
        return JsonResponse({"error": "invalid_image", "detail": detail}, status=400)
    return JsonResponse(
        {
            "url": variants.get("url", ""),
            "thumb_url": variants.get("thumb_url", ""),
            "og_url": variants.get("og_url", ""),
        }
    )
