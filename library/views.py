import mimetypes
import os
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.core.files.storage import default_storage
from django.db import transaction
from django.db.models import Avg, Count, Q
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_POST

from analytics.models import ContentDownload, ContentView
from gating.models import PointLedger, Unlock
from interactions.models import Comment, Favorite, Rating

from .models import Category, ContentFile, ContentItem

try:
    import fitz
except Exception:
    fitz = None


STARS = [5, 4, 3, 2, 1]


def _build_meta_description(content):
    description = (content.description or "").strip()
    if not description:
        description = _("%(title)s - %(type)s resource from Vsteam Lab.") % {
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


def _safe_signed_url(content_file):
    if not content_file:
        return ""
    try:
        return content_file.get_signed_url()
    except Exception:
        return ""


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
    items = (
        ContentItem.objects.filter(is_public=True, status=ContentItem.Status.PUBLISHED)
        .select_related("owner")
        .prefetch_related("categories", "files")
    )

    query = request.GET.get("q", "").strip()
    if query:
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

    paginator = Paginator(items, 8)
    page_obj = paginator.get_page(request.GET.get("page") or 1)
    _annotate_preview(page_obj)

    categories = Category.objects.filter(is_active=True)

    params = {}
    if query:
        params["q"] = query
    if category_slug:
        params["category"] = category_slug
    if content_type:
        params["content_type"] = content_type
    filter_query = urlencode(params)
    page_range = paginator.get_elided_page_range(number=page_obj.number, on_each_side=1, on_ends=1)
    file_types = [{"value": ext, "label": ext.upper()} for ext in _collect_file_types()]

    context = {
        "page_obj": page_obj,
        "categories": categories,
        "query": query,
        "category_slug": category_slug,
        "content_type": content_type,
        "file_types": file_types,
        "filter_query": filter_query,
        "page_range": page_range,
        "canonical_url": request.build_absolute_uri(request.path),
    }

    if request.headers.get("HX-Request") == "true":
        return render(request, "library/_content_grid.html", context)
    return render(request, "library/home.html", context)


def content_detail(request, pk):
    content = get_object_or_404(
        ContentItem, pk=pk, is_public=True, status=ContentItem.Status.PUBLISHED
    )

    preview_file = content.files.filter(kind=ContentFile.FileKind.PREVIEW).first()
    source_file = content.files.filter(kind=ContentFile.FileKind.SOURCE).first()

    preview_url = _safe_signed_url(preview_file)
    source_ext = _extract_extension(getattr(source_file, "storage_path", ""))
    preview_ext = _extract_extension(getattr(preview_file, "storage_path", ""))
    file_type_label = source_ext.upper() if source_ext else (
        preview_ext.upper() if preview_ext else content.get_content_type_display()
    )
    is_pdf = (preview_ext or source_ext) == "pdf"
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

    if request.method == "GET":
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

    comments = list(
        Comment.objects.filter(content=content, parent__isnull=True)
        .select_related("user")
        .prefetch_related("replies__user")
    )

    context = {
        "content": content,
        "preview_url": preview_url,
        "preview_pages": preview_pages,
        "file_type_label": file_type_label,
        "is_pdf": is_pdf,
        "source_file": source_file,
        "meta_description": _build_meta_description(content),
        "rating_avg": rating_stats["avg"],
        "rating_count": rating_stats["count"],
        "favorites_count": favorites_count,
        "user_rating": user_rating,
        "is_favorited": is_favorited,
        "is_unlocked": is_unlocked,
        "comments": comments,
        "edit_form": None,
        "editing_comment_id": None,
        "stars": STARS,
        "canonical_url": request.build_absolute_uri(request.path),
    }
    return render(request, "library/detail.html", context)


@require_GET
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


@require_POST
@login_required
def content_download(request, pk):
    content = get_object_or_404(
        ContentItem, pk=pk, is_public=True, status=ContentItem.Status.PUBLISHED
    )
    if not content.files.exists():
        messages.error(request, _("No files available for this content yet."))
        return redirect("library:content-detail", pk=pk)

    with transaction.atomic():
        user = type(request.user).objects.select_for_update().get(pk=request.user.pk)
        unlock = Unlock.objects.filter(content=content, user=user).first()
        if not unlock:
            cost = content.download_cost_points
            if cost > 0 and user.points_balance < cost:
                messages.error(request, _("Not enough points to unlock this download."))
                return redirect("library:content-detail", pk=pk)

            if cost > 0:
                PointLedger.record(user, -cost, f"Unlock {content.title}")

            unlock = Unlock.objects.create(
                content=content,
                user=user,
                method=Unlock.Method.POINTS,
                cost_points=cost,
            )

    source_file = content.files.filter(kind=ContentFile.FileKind.SOURCE).first()
    if not source_file:
        messages.error(request, _("Source file not available yet."))
        return redirect("library:content-detail", pk=pk)

    file_path = source_file.storage_path
    if not file_path:
        messages.error(request, _("Download service is not configured yet."))
        return redirect("library:content-detail", pk=pk)

    try:
        file_handle = default_storage.open(file_path, "rb")
    except Exception:
        messages.error(request, _("Download service is not configured yet."))
        return redirect("library:content-detail", pk=pk)

    ContentDownload.objects.create(
        content=content,
        user=request.user,
        ip_address=_get_client_ip(request),
        user_agent=request.META.get("HTTP_USER_AGENT", "")[:255],
    )

    filename = os.path.basename(file_path) or f"download-{content.id}"
    mime_type, _ = mimetypes.guess_type(filename)
    return FileResponse(
        file_handle,
        as_attachment=True,
        filename=filename,
        content_type=mime_type or "application/octet-stream",
    )
