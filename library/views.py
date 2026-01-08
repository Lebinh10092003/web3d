import logging
import mimetypes
import os
import re
import time
import hashlib
from pathlib import Path, PurePosixPath
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.staticfiles import finders
from django.core import signing
from django.core.paginator import Paginator
from django.core.files.storage import default_storage
from django.core.cache import cache
from django.db import IntegrityError, transaction, connection
from django.db.models import Avg, Count, Q
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from analytics.models import ContentDownload, ContentView
from gating.models import PointLedger, Unlock
from interactions.models import Comment, Favorite, Rating

from .lego_ldraw import (
    UnsupportedLegoModel,
    find_cached_ldraw_model_path,
    get_cached_ldraw_model_path,
)
from .models import Category, ContentFile, ContentItem, LibrarySideBanner
from .tasks import enqueue_ldraw_prebuild

try:
    import fitz
except Exception:
    fitz = None


STARS = [5, 4, 3, 2, 1]
logger = logging.getLogger(__name__)


def _cache_ttl(seconds, *, max_seconds=None):
    try:
        ttl = int(seconds or 0)
    except (TypeError, ValueError):
        ttl = 0
    if ttl <= 0:
        return 0
    if max_seconds is not None:
        ttl = min(ttl, max(0, int(max_seconds)))
    return max(ttl, 0)


def _library_grid_cache_ttl():
    ttl = _cache_ttl(getattr(settings, "LIBRARY_GRID_CACHE_TTL", 60))
    if not ttl:
        return 0
    if getattr(settings, "MEDIA_SIGNED_URLS", True):
        media_ttl = _cache_ttl(getattr(settings, "MEDIA_SIGNED_URL_TTL", 300))
        if media_ttl:
            ttl = min(ttl, max(10, media_ttl - 5))
    return ttl


def _build_library_grid_cache_key(request):
    lang = getattr(request, "LANGUAGE_CODE", "") or ""
    if request.user.is_authenticated:
        user_key = f"u:{request.user.id}"
    else:
        user_key = "anon"
    query = request.GET.get("q", "").strip()
    sort = request.GET.get("sort", "").strip().lower()
    if not sort:
        sort = "relevance" if query else "newest"
    params = {
        "lang": lang,
        "user": user_key,
        "q": query,
        "category": request.GET.get("category", "").strip(),
        "content_type": request.GET.get("content_type", "").strip().lower(),
        "sort": sort,
        "page": request.GET.get("page") or 1,
    }
    raw = "|".join(f"{key}={params[key]}" for key in sorted(params))
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
    return f"library:grid:v2:{digest}"


def _build_meta_description(content):
    description = (content.description or "").strip()
    if not description:
        description = _("%(title)s - %(type)s resource from V+ STEAM LAB Library.") % {
            "title": content.title,
            "type": content.get_content_type_display(),
        }
    if len(description) > 155:
        description = description[:152].rstrip() + "..."
    return description


def _get_client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        ip = forwarded.split(",")[0].strip()
        return ip or None
    ip = request.META.get("REMOTE_ADDR")
    return ip if ip else None


def _should_log_content_view(request, content_id):
    ttl = _cache_ttl(getattr(settings, "CONTENT_VIEW_LOG_TTL", 900))
    if ttl <= 0:
        return True

    if request.user.is_authenticated:
        identity = f"user:{request.user.id}"
    else:
        ip = _get_client_ip(request) or "anon"
        ua = request.META.get("HTTP_USER_AGENT", "")[:200]
        ua_hash = hashlib.sha256(ua.encode("utf-8")).hexdigest()[:12] if ua else "na"
        identity = f"ip:{ip}:ua:{ua_hash}"

    cache_key = f"content:view:{content_id}:{identity}"
    if cache.get(cache_key):
        return False
    cache.set(cache_key, 1, timeout=ttl)
    return True


def _safe_signed_url(content_file, expires_in=None):
    if not content_file:
        return ""
    try:
        return content_file.get_signed_url(expires_in=expires_in)
    except Exception:
        return ""



def _rate_limit(request, key, limit, window):
    if not limit or limit <= 0:
        return True
    identity = ""
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
    if count > limit:
        return False
    return True


def _rate_limit_response(window):
    response = HttpResponse("Too Many Requests", status=429, content_type="text/plain")
    response["Retry-After"] = str(window)
    return response


def rate_limit(limit, window, key_prefix):
    def decorator(view):
        def wrapped(request, *args, **kwargs):
            if not _rate_limit(request, key_prefix, limit, window):
                return _rate_limit_response(window)
            return view(request, *args, **kwargs)

        wrapped.__name__ = getattr(view, "__name__", "wrapped")
        wrapped.__doc__ = getattr(view, "__doc__", None)
        return wrapped

    return decorator


def _extract_extension(path):
    if not path:
        return ""
    _, ext = os.path.splitext(path)
    return ext[1:].lower() if ext else ""


def _build_preview_image_url(content_id, page=None):
    url = reverse("library:content-preview", args=[content_id])
    if page:
        return f"{url}?page={page}"
    return url


def _render_pdf_page(pdf_bytes, page_index=0, target_width=1200):
    if not fitz:
        return None
    doc = None
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        if doc.page_count < 1:
            return None
        if page_index < 0 or page_index >= doc.page_count:
            return None
        page = doc.load_page(page_index)
        page_width = page.rect.width or 1
        scale = target_width / page_width
        scale = max(0.5, min(scale, 2.0))
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        return pix.tobytes("png")
    except Exception:
        return None
    finally:
        if doc:
            doc.close()


def _pick_pdf_file(preview_file, source_file):
    for candidate in (preview_file, source_file):
        if _extract_extension(getattr(candidate, "storage_path", "")) == "pdf":
            return candidate
    return None


def _get_pdf_page_count(file_path):
    if not fitz or not file_path:
        return 0
    max_mb = int(getattr(settings, "MAX_PDF_PREVIEW_MB", 20))
    try:
        size_bytes = default_storage.size(file_path)
    except Exception:
        size_bytes = None
    if size_bytes and size_bytes > max_mb * 1024 * 1024:
        return 0

    doc = None
    try:
        with default_storage.open(file_path, "rb") as pdf_file_handle:
            pdf_bytes = pdf_file_handle.read()
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        return doc.page_count or 0
    except Exception:
        return 0
    finally:
        if doc:
            doc.close()


def _collect_file_types():
    file_types = set()
    paths = ContentFile.objects.filter(
        kind=ContentFile.FileKind.SOURCE,
        content__is_public=True,
        content__status=ContentItem.Status.PUBLISHED,
    ).values_list("storage_path", flat=True)
    for path in paths:
        ext = _extract_extension(path)
        if ext:
            file_types.add(ext)
    return sorted(file_types)


def _annotate_preview(items):
    for item in items:
        preview_file = next(
            (f for f in item.files.all() if f.kind == ContentFile.FileKind.PREVIEW), None
        )
        source_file = next(
            (f for f in item.files.all() if f.kind == ContentFile.FileKind.SOURCE), None
        )
        preview_ext = _extract_extension(getattr(preview_file, "storage_path", ""))
        source_ext = _extract_extension(getattr(source_file, "storage_path", ""))
        preview_url = _safe_signed_url(preview_file)
        if preview_ext == "pdf" or (not preview_url and source_ext == "pdf"):
            preview_url = _build_preview_image_url(item.id, page=1) if fitz else ""
        item.preview_url = preview_url
        item.file_type = source_ext
        item.file_type_label = source_ext.upper() if source_ext else item.get_content_type_display()


def home(request):
    is_htmx = request.headers.get("HX-Request") == "true"
    grid_cache_ttl = _library_grid_cache_ttl()
    grid_cache_key = _build_library_grid_cache_key(request) if grid_cache_ttl else ""
    if grid_cache_key:
        cached_html = cache.get(grid_cache_key)
        if cached_html:
            if is_htmx:
                return HttpResponse(cached_html)
            query = request.GET.get("q", "").strip()
            category_slug = request.GET.get("category", "").strip()
            content_type = request.GET.get("content_type", "").strip().lower()
            sort = request.GET.get("sort", "").strip().lower()
            if not sort:
                sort = "relevance" if query else "newest"

            categories = Category.objects.filter(is_active=True)
            left_banners = LibrarySideBanner.objects.filter(
                is_active=True, position=LibrarySideBanner.Position.LEFT
            ).order_by("sort_order", "id")
            right_banners = LibrarySideBanner.objects.filter(
                is_active=True, position=LibrarySideBanner.Position.RIGHT
            ).order_by("sort_order", "id")
            file_types = [
                {"value": ext, "label": ext.upper()} for ext in _collect_file_types()
            ]

            context = {
                "categories": categories,
                "query": query,
                "category_slug": category_slug,
                "content_type": content_type,
                "sort": sort,
                "file_types": file_types,
                "canonical_url": request.build_absolute_uri(request.path),
                "left_banners": left_banners,
                "right_banners": right_banners,
                "content_grid_html": cached_html,
            }
            return render(request, "library/home.html", context)
        content_grid_html = ""
    else:
        content_grid_html = ""

    items = (
        ContentItem.objects.filter(is_public=True, status=ContentItem.Status.PUBLISHED)
        .select_related("owner")
        .prefetch_related("categories", "files")
    )

    query = request.GET.get("q", "").strip()
    search_ranked = False
    if query and connection.vendor == "postgresql" and getattr(settings, "USE_FULLTEXT_SEARCH", True):
        try:
            from django.contrib.postgres.search import (
                SearchQuery,
                SearchRank,
                SearchVector,
            )
        except Exception:
            search_ranked = False
        else:
            search_config = getattr(settings, "POSTGRES_FTS_CONFIG", "simple") or "simple"
            vector = SearchVector("title", weight="A", config=search_config) + SearchVector(
                "description", weight="B", config=search_config
            )
            search_query = SearchQuery(query, search_type="websearch", config=search_config)
            items = items.annotate(search_rank=SearchRank(vector, search_query)).filter(
                search_rank__gt=0
            )
            search_ranked = True
    if query and not search_ranked:
        items = items.filter(Q(title__icontains=query) | Q(description__icontains=query))

    category_slug = request.GET.get("category", "").strip()
    if category_slug:
        items = items.filter(categories__slug=category_slug)

    content_type = request.GET.get("content_type", "").strip().lower()
    if content_type:
        items = items.filter(
            files__kind=ContentFile.FileKind.SOURCE,
            files__storage_path__iendswith=f".{content_type}",
        ).distinct()

    items = items.annotate(
        rating_avg=Avg("ratings__score"),
        favorites_count=Count("favorites", distinct=True),
    )

    sort = request.GET.get("sort", "").strip().lower()
    if not sort:
        sort = "relevance" if query and search_ranked else "newest"

    if sort == "relevance" and query and search_ranked:
        items = items.order_by("-search_rank", "-created_at")
    elif sort == "oldest":
        items = items.order_by("created_at")
    elif sort == "rating":
        items = items.order_by("-rating_avg", "-created_at")
    elif sort == "favorites":
        items = items.order_by("-favorites_count", "-created_at")
    elif sort == "title":
        items = items.order_by("title")
    else:
        sort = "newest"
        items = items.order_by("-created_at")

    paginator = Paginator(items, 8)
    page_obj = paginator.get_page(request.GET.get("page") or 1)
    _annotate_preview(page_obj)
    user = request.user
    is_privileged = bool(
        user.is_authenticated and (user.is_staff or user.is_superuser)
    )
    unlocked_ids = set()
    if user.is_authenticated and not is_privileged:
        unlocked_ids = set(
            Unlock.objects.filter(content__in=page_obj.object_list, user=user).values_list(
                "content_id", flat=True
            )
        )
    for item in page_obj:
        is_unlocked = item.download_cost_points == 0
        if user.is_authenticated:
            if is_privileged or item.owner_id == user.id or item.id in unlocked_ids:
                is_unlocked = True
        item.lock_preview = item.download_cost_points > 0 and not is_unlocked

    categories = Category.objects.filter(is_active=True)
    left_banners = LibrarySideBanner.objects.filter(
        is_active=True, position=LibrarySideBanner.Position.LEFT
    ).order_by("sort_order", "id")
    right_banners = LibrarySideBanner.objects.filter(
        is_active=True, position=LibrarySideBanner.Position.RIGHT
    ).order_by("sort_order", "id")

    params = {}
    if query:
        params["q"] = query
    if category_slug:
        params["category"] = category_slug
    if content_type:
        params["content_type"] = content_type
    if sort:
        params["sort"] = sort
    filter_query = urlencode(params)
    page_range = paginator.get_elided_page_range(number=page_obj.number, on_each_side=1, on_ends=1)
    file_types = [{"value": ext, "label": ext.upper()} for ext in _collect_file_types()]

    context = {
        "page_obj": page_obj,
        "categories": categories,
        "query": query,
        "category_slug": category_slug,
        "content_type": content_type,
        "sort": sort,
        "file_types": file_types,
        "filter_query": filter_query,
        "page_range": page_range,
        "canonical_url": request.build_absolute_uri(request.path),
        "left_banners": left_banners,
        "right_banners": right_banners,
    }

    if not content_grid_html:
        content_grid_html = render_to_string(
            "library/_content_grid.html", context=context, request=request
        )
        if grid_cache_key and content_grid_html:
            cache.set(grid_cache_key, content_grid_html, grid_cache_ttl)

    if is_htmx:
        return HttpResponse(content_grid_html)

    context["content_grid_html"] = content_grid_html
    return render(request, "library/home.html", context)


def content_detail(request, slug):
    content = ContentItem.objects.filter(
        slug=slug, is_public=True, status=ContentItem.Status.PUBLISHED
    ).first()
    if not content and str(slug).isdigit():
        content = get_object_or_404(
            ContentItem, pk=int(slug), is_public=True, status=ContentItem.Status.PUBLISHED
        )
        if not content.slug:
            content.save(update_fields=["slug"])
        if content.slug and content.slug != slug:
            return redirect("library:content-detail", slug=content.slug, permanent=True)
    if not content:
        raise Http404
    preview_file = content.files.filter(kind=ContentFile.FileKind.PREVIEW).first()
    source_file = content.files.filter(kind=ContentFile.FileKind.SOURCE).first()
    preview_url = _safe_signed_url(preview_file)
    source_ext = _extract_extension(getattr(source_file, "storage_path", ""))
    preview_ext = _extract_extension(getattr(preview_file, "storage_path", ""))
    file_type_label = source_ext.upper() if source_ext else (
        preview_ext.upper() if preview_ext else content.get_content_type_display()
    )
    is_pdf = (preview_ext or source_ext) == "pdf"
    lego_model_url = ""
    if source_ext in {"io", "lxf", "ldr", "mpd"}:
        lego_model_url = reverse("library:content-lego-model", args=[content.id])
    preview_pages = []
    if is_pdf and fitz:
        pdf_file = _pick_pdf_file(preview_file, source_file)
        page_count = _get_pdf_page_count(getattr(pdf_file, "storage_path", ""))
        if page_count:
            page_numbers = range(1, page_count + 1, 10)
            preview_pages = [
                _build_preview_image_url(content.id, page=page_num)
                for page_num in page_numbers
            ]
            preview_url = preview_pages[0] if preview_pages else ""

    og_ttl = int(getattr(settings, "MEDIA_SIGNED_URL_OG_TTL", 86400))
    og_image_url = ""
    if preview_file:
        og_image_url = _safe_signed_url(preview_file, expires_in=og_ttl)
    if not og_image_url and preview_pages:
        og_image_url = preview_pages[0]
    if not og_image_url:
        og_image_url = preview_url

    if request.method == "GET" and _should_log_content_view(request, content.id):
        ContentView.objects.create(
            content=content,
            user=request.user if request.user.is_authenticated else None,
            ip_address=_get_client_ip(request),
            user_agent=request.META.get("HTTP_USER_AGENT", "")[:255],
        )

    rating_stats = content.ratings.aggregate(avg=Avg("score"), count=Count("id"))
    favorites_count = content.favorites.count()

    user_rating = None
    is_favorited = False
    is_unlocked = content.download_cost_points == 0
    if request.user.is_authenticated:
        user_rating = Rating.objects.filter(content=content, user=request.user).first()
        is_favorited = Favorite.objects.filter(content=content, user=request.user).exists()
        is_unlocked = is_unlocked or Unlock.objects.filter(
            content=content, user=request.user
        ).exists()
        if content.owner_id == request.user.id:
            is_unlocked = True
        if request.user.is_staff or request.user.is_superuser:
            is_unlocked = True

    can_view_lego_model = bool(lego_model_url) and is_unlocked

    comments = list(
        Comment.objects.filter(content=content, parent__isnull=True)
        .select_related("user")
        .prefetch_related("replies__user")
    )
    download_banner = (
        LibrarySideBanner.objects.filter(
            is_active=True, position=LibrarySideBanner.Position.DOWNLOAD
        )
        .order_by("sort_order", "id")
        .first()
    )

    context = {
        "content": content,
        "preview_url": preview_url,
        "preview_pages": preview_pages,
        "file_type_label": file_type_label,
        "is_pdf": is_pdf,
        "lego_model_url": lego_model_url,
        "source_file": source_file,
        "meta_description": _build_meta_description(content),
        "og_image_url": og_image_url,
        "rating_avg": rating_stats["avg"],
        "rating_count": rating_stats["count"],
        "favorites_count": favorites_count,
        "user_rating": user_rating,
        "is_favorited": is_favorited,
        "is_unlocked": is_unlocked,
        "lock_preview": (
            content.content_type == ContentItem.ContentType.LEGO_3D
            and content.download_cost_points > 100
            and not is_unlocked
        ),
        "can_view_lego_model": can_view_lego_model,
        "is_htmx": False,
        "action_message": None,
        "action_level": "",
        "comments": comments,
        "edit_form": None,
        "editing_comment_id": None,
        "stars": STARS,
        "canonical_url": request.build_absolute_uri(request.path),
        "download_banner": download_banner,
    }
    return render(request, "library/detail.html", context)


@require_GET
@rate_limit(
    limit=int(getattr(settings, "RATE_LIMIT_PREVIEW_PER_MIN", 60) or 60),
    window=60,
    key_prefix="preview",
)
def content_preview_image(request, pk):
    content = get_object_or_404(
        ContentItem, pk=pk, is_public=True, status=ContentItem.Status.PUBLISHED
    )
    preview_file = content.files.filter(kind=ContentFile.FileKind.PREVIEW).first()
    source_file = content.files.filter(kind=ContentFile.FileKind.SOURCE).first()
    pdf_file = _pick_pdf_file(preview_file, source_file)
    if not pdf_file or not fitz:
        raise Http404

    file_path = getattr(pdf_file, "storage_path", "")
    if not file_path:
        raise Http404

    max_mb = int(getattr(settings, "MAX_PDF_PREVIEW_MB", 20))
    try:
        size_bytes = default_storage.size(file_path)
    except Exception:
        size_bytes = None
    if size_bytes and size_bytes > max_mb * 1024 * 1024:
        raise Http404

    try:
        with default_storage.open(file_path, "rb") as pdf_file_handle:
            pdf_bytes = pdf_file_handle.read()
    except Exception:
        raise Http404

    page_number_raw = request.GET.get("page", "")
    try:
        page_number = int(page_number_raw) if page_number_raw else 1
    except ValueError:
        page_number = 1
    if page_number < 1:
        page_number = 1

    preview_bytes = _render_pdf_page(pdf_bytes, page_index=page_number - 1)
    if not preview_bytes:
        raise Http404

    response = HttpResponse(preview_bytes, content_type="image/png")
    response["Cache-Control"] = "public, max-age=3600"
    return response


@require_GET
def ldraw_index(request):
    return HttpResponse("LDraw assets", content_type="text/plain; charset=utf-8")


@require_GET
def protected_media(request, blob_path=None):
    token = request.GET.get("token", "")
    if not token:
        return HttpResponse("Missing token.", status=403, content_type="text/plain")
    try:
        payload = signing.loads(token, salt="media")
    except signing.BadSignature:
        return HttpResponse("Invalid token.", status=403, content_type="text/plain")
    path = payload.get("path")
    if not path:
        return HttpResponse("Invalid token.", status=403, content_type="text/plain")
    if blob_path and path != blob_path:
        return HttpResponse("Invalid token.", status=403, content_type="text/plain")
    exp = payload.get("exp")
    if exp and int(exp) < int(time.time()):
        return HttpResponse("Expired token.", status=403, content_type="text/plain")
    uid = int(payload.get("uid") or 0)
    if uid:
        if not request.user.is_authenticated or request.user.id != uid:
            return HttpResponse("Invalid user.", status=403, content_type="text/plain")

    resolved_path = blob_path or path
    try:
        file_handle = default_storage.open(resolved_path, "rb")
    except Exception:
        raise Http404

    filename = os.path.basename(resolved_path)
    guessed, _ = mimetypes.guess_type(filename)
    content_type = guessed or "application/octet-stream"
    response = FileResponse(file_handle, content_type=content_type)
    if request.GET.get("download") == "1":
        response["Content-Disposition"] = f'attachment; filename="{filename}"'

    accel_prefix = getattr(settings, "MEDIA_ACCEL_REDIRECT_PREFIX", "")
    if accel_prefix:
        response = HttpResponse(content_type=content_type)
        response["X-Accel-Redirect"] = (
            f"{accel_prefix.rstrip('/')}/{resolved_path.lstrip('/')}"
        )
        if request.GET.get("download") == "1":
            response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response["Cache-Control"] = "private, max-age=60"
    return response


def _get_ldraw_root():
    ldconfig_path = finders.find("ldraw/LDConfig.ldr")
    if not ldconfig_path:
        raise Http404
    return Path(ldconfig_path).resolve().parent


def _clean_ldraw_path(relative_path):
    cleaned = (relative_path or "").replace("\\", "/").lstrip("/")
    if not cleaned:
        return ""
    path = PurePosixPath(cleaned)
    if path.is_absolute() or ".." in path.parts:
        return ""
    return path.as_posix()


def _ldraw_candidates(clean_path):
    candidates = []

    def push(value):
        if not value:
            return
        if value not in candidates:
            candidates.append(value)

    def collapse_known_prefixes(value):
        collapsed = value
        for prefix in ("p", "parts", "models"):
            token = f"{prefix}/{prefix}/"
            while token in collapsed:
                collapsed = collapsed.replace(token, f"{prefix}/")
        return collapsed

    push(clean_path)
    push(collapse_known_prefixes(clean_path))

    if not clean_path:
        return candidates

    path = PurePosixPath(clean_path)
    parts = list(path.parts)

    if parts and parts[0] == "models":
        remainder = PurePosixPath(*parts[1:]).as_posix()
        push(remainder)
        push(collapse_known_prefixes(remainder))

    if parts and parts[0] == "parts":
        remainder = PurePosixPath(*parts[1:]).as_posix()
        push(remainder)
        push(collapse_known_prefixes(remainder))
        # Some loaders request primitives under "parts/" even though they live in "p/".
        push(f"p/{remainder}")
        push(collapse_known_prefixes(f"p/{remainder}"))
        if parts[1:]:
            first_segment = parts[1]
            if first_segment.isdigit():
                push(f"p/{remainder}")
            if first_segment == "p":
                push(PurePosixPath("p", *parts[2:]).as_posix())
            if first_segment == "models":
                push(PurePosixPath(*parts[2:]).as_posix())

    if len(parts) == 1:
        push(f"parts/{clean_path}")
        push(f"p/{clean_path}")
        push(f"models/{clean_path}")

    if parts and parts[0] not in {"parts", "p", "models"} and parts[0].isdigit():
        push(f"p/{clean_path}")

    expanded = []
    for candidate in candidates:
        expanded.append(candidate)
        if candidate.lower().endswith("-bl.dat"):
            expanded.append(candidate[:-7] + ".dat")
        rewritten = _rewrite_ldraw_suffix(candidate)
        if rewritten and rewritten != candidate:
            expanded.append(rewritten)
        rewritten = _rewrite_bricklink_part_id(candidate)
        if rewritten and rewritten != candidate:
            expanded.append(rewritten)
        if candidate.lower().endswith(".dat") and "/parts/" not in f"/{candidate}":
            expanded.append(f"parts/{candidate}")
    out = []
    for candidate in expanded:
        if candidate and candidate not in out:
            out.append(candidate)
    return out


def _rewrite_bricklink_part_id(candidate):
    if not candidate or not candidate.lower().endswith(".dat"):
        return ""
    path = PurePosixPath(candidate)
    name = path.name
    rewritten = re.sub(r"^(\d+)pb", r"\1p", name, flags=re.IGNORECASE)
    if rewritten == name:
        return ""
    return path.with_name(rewritten).as_posix()


def _rewrite_ldraw_suffix(candidate):
    if not candidate or not candidate.lower().endswith(".dat"):
        return ""
    path = PurePosixPath(candidate)
    name = path.name
    match = re.fullmatch(r"(\d+)[a-z]\.dat", name, flags=re.IGNORECASE)
    if not match:
        return ""
    return path.with_name(f"{match.group(1)}.dat").as_posix()


def _is_numeric_part_dat(clean_path):
    name = PurePosixPath(clean_path).name
    return bool(re.fullmatch(r"\d+\.dat", name, flags=re.IGNORECASE))


def _build_placeholder_part_dat(clean_path):
    name = PurePosixPath(clean_path).name
    safe_name = re.sub(r"[^A-Za-z0-9_.-]", "_", name)
    lines = [
        f"0 Placeholder part for missing file: {safe_name}",
        f"0 Name: {safe_name}",
        "0 Author: web3d",
        "0 !LDRAW_ORG Unofficial_Part",
        "0 BFC NOCLIP",
        "4 16 -10 0 -10 10 0 -10 10 0 10 -10 0 10",
        "4 16 -10 20 -10 -10 20 10 10 20 10 10 20 -10",
        "4 16 -10 0 -10 -10 20 -10 10 20 -10 10 0 -10",
        "4 16 10 0 -10 10 20 -10 10 20 10 10 0 10",
        "4 16 10 0 10 10 20 10 -10 20 10 -10 0 10",
        "4 16 -10 0 10 -10 20 10 -10 20 -10 -10 0 -10",
        "2 24 -10 0 -10 10 0 -10",
        "2 24 10 0 -10 10 0 10",
        "2 24 10 0 10 -10 0 10",
        "2 24 -10 0 10 -10 0 -10",
        "2 24 -10 20 -10 10 20 -10",
        "2 24 10 20 -10 10 20 10",
        "2 24 10 20 10 -10 20 10",
        "2 24 -10 20 10 -10 20 -10",
        "2 24 -10 0 -10 -10 20 -10",
        "2 24 10 0 -10 10 20 -10",
        "2 24 10 0 10 10 20 10",
        "2 24 -10 0 10 -10 20 10",
        "0",
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")

@require_GET
def ldraw_asset(request, relative_path):
    clean_path = _clean_ldraw_path(relative_path)
    if not clean_path:
        raise Http404

    root = _get_ldraw_root()
    resolved = None
    for candidate in _ldraw_candidates(clean_path):
        candidate_path = (root / candidate).resolve()
        try:
            candidate_path.relative_to(root)
        except ValueError:
            continue
        if candidate_path.is_file():
            resolved = candidate_path
            break

    if not resolved:
        if _is_numeric_part_dat(clean_path):
            response = HttpResponse(
                _build_placeholder_part_dat(clean_path),
                content_type="text/plain; charset=utf-8",
            )
            response["Cache-Control"] = "public, max-age=300"
            response["X-LDraw-Placeholder"] = "1"
            return response
        raise Http404

    ext = resolved.suffix.lower()
    if ext in {".dat", ".ldr", ".mpd", ".txt", ".ldr"}:
        content_type = "text/plain; charset=utf-8"
    else:
        guessed, _ = mimetypes.guess_type(str(resolved))
        content_type = guessed or "application/octet-stream"

    try:
        file_handle = resolved.open("rb")
    except OSError:
        raise Http404

    response = FileResponse(file_handle, content_type=content_type)
    response["Cache-Control"] = "public, max-age=3600"
    return response


@require_http_methods(["GET", "HEAD"])
@rate_limit(
    limit=int(getattr(settings, "RATE_LIMIT_LDRAW_PER_MIN", 30) or 30),
    window=60,
    key_prefix="ldraw",
)
def content_lego_model(request, pk):
    content = get_object_or_404(
        ContentItem, pk=pk, is_public=True, status=ContentItem.Status.PUBLISHED
    )
    source_file = content.files.filter(kind=ContentFile.FileKind.SOURCE).first()
    if not source_file:
        raise Http404

    source_path = source_file.storage_path
    if not source_path:
        raise Http404

    is_unlocked = content.download_cost_points == 0
    if request.user.is_authenticated:
        is_unlocked = is_unlocked or Unlock.objects.filter(
            content=content, user=request.user
        ).exists()
        if content.owner_id == request.user.id:
            is_unlocked = True
        if request.user.is_staff or request.user.is_superuser:
            is_unlocked = True
    if not is_unlocked:
        return HttpResponse("Unlock required.", status=403, content_type="text/plain")

    cache_path = find_cached_ldraw_model_path(
        content_id=content.id, source_path=source_path
    )
    if not cache_path and getattr(settings, "USE_BACKGROUND_JOBS", True):
        enqueue_ldraw_prebuild(content.id, source_path)
        return HttpResponse(
            "LDraw model is being prepared. Please retry shortly.",
            status=202,
            content_type="text/plain; charset=utf-8",
        )

    if not cache_path:
        try:
            cache_path = get_cached_ldraw_model_path(
                content_id=content.id, source_path=source_path
            )
        except UnsupportedLegoModel as exc:
            if settings.DEBUG:
                return HttpResponse(
                    f"LDraw conversion failed: {exc}",
                    status=400,
                    content_type="text/plain; charset=utf-8",
                )
            logger.warning("LDraw conversion failed for content %s: %s", content.id, exc)
            raise Http404
        except Exception:
            logger.exception("Unexpected LDraw conversion error for content %s", content.id)
            if settings.DEBUG:
                return HttpResponse(
                    "Unexpected LDraw conversion error. Check server logs.",
                    status=500,
                    content_type="text/plain; charset=utf-8",
                )
            raise Http404

    try:
        file_handle = default_storage.open(cache_path, "rb")
    except Exception:
        if settings.DEBUG:
            return HttpResponse(
                f"LDraw model not found: {cache_path}",
                status=404,
                content_type="text/plain; charset=utf-8",
            )
        logger.warning("LDraw model missing for content %s: %s", content.id, cache_path)
        raise Http404

    response = FileResponse(file_handle, content_type="text/plain; charset=utf-8")
    response["Cache-Control"] = "public, max-age=3600"
    filename = PurePosixPath(cache_path).name
    if filename.startswith("model-") and filename.lower().endswith(".ldr"):
        variant = filename[len("model-") : -len(".ldr")]
        response["X-LDraw-Variant"] = variant
        if variant.startswith("lxf-cli"):
            response["X-LXF-Converter"] = "cli"
        elif variant.startswith("lxf-py"):
            response["X-LXF-Converter"] = "python"
    return response


@require_POST
@login_required
@rate_limit(
    limit=int(getattr(settings, "RATE_LIMIT_DOWNLOAD_PER_MIN", 20) or 20),
    window=60,
    key_prefix="download",
)
def content_download(request, pk):
    content = get_object_or_404(
        ContentItem, pk=pk, is_public=True, status=ContentItem.Status.PUBLISHED
    )
    is_htmx = request.headers.get("HX-Request") == "true"
    is_owner = content.owner_id == request.user.id
    is_privileged = request.user.is_staff or request.user.is_superuser
    if not content.files.exists():
        message_text = _("No files available for this content yet.")
        if is_htmx:
            return render(
                request,
                "library/_download_action.html",
                {
                    "content": content,
                    "is_unlocked": False,
                    "action_message": message_text,
                    "action_level": "error",
                },
            )
        messages.error(request, message_text)
        return redirect("library:content-detail", slug=content.slug)

    base_context = {
        "content": content,
    }

    did_unlock = False
    user = request.user
    unlock = None
    is_unlocked = False

    if is_owner or is_privileged:
        is_unlocked = True
        if is_htmx:
            if is_owner:
                action_message = _("You own this content. Download is ready.")
            else:
                action_message = _("Access granted. Download is ready.")
            return render(
                request,
                "library/_download_action.html",
                {
                    **base_context,
                    "is_unlocked": True,
                    "action_message": action_message,
                    "action_level": "success",
                },
            )
    else:
        with transaction.atomic():
            user_model = get_user_model()
            user = user_model.objects.select_for_update().get(pk=request.user.pk)
            unlock = Unlock.objects.filter(content=content, user=user).first()
            if not unlock:
                cost = content.download_cost_points
                if cost > 0 and user.points_balance < cost:
                    message_text = _("Not enough points to unlock this download.")
                    if is_htmx:
                        return render(
                            request,
                            "library/_download_action.html",
                            {
                                **base_context,
                                "is_unlocked": False,
                                "action_message": message_text,
                                "action_level": "error",
                            },
                        )
                    messages.error(request, message_text)
                    return redirect("library:content-detail", slug=content.slug)

                if cost > 0:
                    try:
                        unlock, created = Unlock.objects.get_or_create(
                            content=content,
                            user=user,
                            defaults={
                                "method": Unlock.Method.POINTS,
                                "cost_points": cost,
                            },
                        )
                    except IntegrityError:
                        unlock = Unlock.objects.filter(content=content, user=user).first()
                        created = False

                    if created:
                        PointLedger.record(user, -cost, f"Unlock {content.title}")
                    did_unlock = True
        is_unlocked = content.download_cost_points == 0 or bool(unlock)

    if did_unlock:
        if request.LANGUAGE_CODE == "vi":
            action_message = (
                'Mở khóa thành công. Nhấn "Tải ngay" để bắt đầu tải.'
            )
        else:
            action_message = 'Unlocked successfully. Click "Download now" to start downloading.'
        if is_htmx:
            return render(
                request,
                "library/_download_action.html",
                {
                    **base_context,
                    "is_unlocked": True,
                    "action_message": action_message,
                    "action_level": "success",
                },
            )
        messages.success(request, action_message)
        return redirect("library:content-detail", slug=content.slug)

    if is_htmx:
        if content.download_cost_points == 0 or unlock:
            if request.LANGUAGE_CODE == "vi":
                action_message = (
                    'Nội dung đã được mở khóa. Nhấn "Tải ngay" để bắt đầu tải.'
                )
            else:
                action_message = 'Content already unlocked. Click "Download now" to start downloading.'
            return render(
                request,
                "library/_download_action.html",
                {
                    **base_context,
                    "is_unlocked": True,
                    "action_message": action_message,
                    "action_level": "success",
                },
            )
        if request.LANGUAGE_CODE == "vi":
            action_message = "Không đủ điểm để mở khóa nội dung này."
        else:
            action_message = "Not enough points to unlock this download."
        return render(
            request,
            "library/_download_action.html",
            {
                **base_context,
                "is_unlocked": False,
                "action_message": action_message,
                "action_level": "error",
            },
        )

    source_file = content.files.filter(kind=ContentFile.FileKind.SOURCE).first()
    if not source_file:
        messages.error(request, _("Source file not available yet."))
        return redirect("library:content-detail", slug=content.slug)

    file_path = source_file.storage_path
    if not file_path:
        messages.error(request, _("Download service is not configured yet."))
        return redirect("library:content-detail", slug=content.slug)

    if getattr(settings, "USE_SIGNED_DOWNLOADS", True):
        signed_url = source_file.get_signed_url(
            expires_in=getattr(settings, "MEDIA_SIGNED_URL_TTL", 300),
            user_id=request.user.id,
            download=True,
        )
        return redirect(signed_url)

    try:
        file_handle = default_storage.open(file_path, "rb")
    except Exception:
        messages.error(request, _("Download service is not configured yet."))
        return redirect("library:content-detail", slug=content.slug)

    ContentDownload.objects.create(
        content=content,
        user=user or request.user,
        ip_address=_get_client_ip(request),
        user_agent=request.META.get("HTTP_USER_AGENT", "")[:255],
    )

    filename = os.path.basename(file_path) or f"download-{content.id}"
    mime_type, _encoding = mimetypes.guess_type(filename)
    return FileResponse(
        file_handle,
        as_attachment=True,
        filename=filename,
        content_type=mime_type or "application/octet-stream",
    )
