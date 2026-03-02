import logging
import json
import re
from collections import Counter, OrderedDict

from django.contrib import admin, messages
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import DataError, IntegrityError, transaction
from django.http import Http404
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .forms import BulkPostImportForm
from .importer import _load_json_payload, import_posts, parse_bulk_posts
from .media import save_blog_image_variants
from .models import BlogApiAuditLog, BlogComment, Post, PostBlock, PostRevision


logger = logging.getLogger(__name__)

UPLOAD_SLOT_PATTERNS = (
    re.compile(r"^\s*\[\[\s*UPLOAD:([A-Za-z0-9_-]{1,64})\s*\]\]\s*$"),
    re.compile(r"^\s*\{\{\s*UPLOAD:([A-Za-z0-9_-]{1,64})\s*\}\}\s*$"),
)


def _extract_upload_slot(value):
    text = str(value or "").strip()
    if not text:
        return ""
    for pattern in UPLOAD_SLOT_PATTERNS:
        match = pattern.match(text)
        if match:
            return str(match.group(1) or "").strip()
    return ""


def _parse_posts_payload(raw_data: str):
    payload = _load_json_payload(raw_data)

    if isinstance(payload, dict):
        posts_payload = payload.get("posts")
    elif isinstance(payload, list):
        posts_payload = payload
    else:
        raise ValidationError(_("Top-level JSON must be an object with 'posts' or a list."))

    if not isinstance(posts_payload, list):
        raise ValidationError(_("`posts` must be a list."))
    return payload, posts_payload


def _collect_upload_slot_locations(posts_payload):
    slots = OrderedDict()

    def to_text(value, *, max_length=140):
        text = str(value or "").strip()
        if len(text) <= max_length:
            return text
        return f"{text[: max_length - 3]}..."

    def add_slot(slot_name: str, location: str, *, caption: str = ""):
        slots.setdefault(slot_name, [])
        slots[slot_name].append(
            {
                "location": location,
                "caption": to_text(caption),
            }
        )

    for post_index, post in enumerate(posts_payload, start=1):
        if not isinstance(post, dict):
            continue

        hero_slot = _extract_upload_slot(post.get("hero_image_url"))
        if hero_slot:
            hero_caption = (
                post.get("hero_image_caption")
                or post.get("hero_caption")
                or post.get("title")
                or ""
            )
            add_slot(
                hero_slot,
                f"Post #{post_index} hero_image_url",
                caption=hero_caption,
            )

        blocks = post.get("blocks")
        if not isinstance(blocks, list):
            continue

        for block_index, block in enumerate(blocks, start=1):
            if not isinstance(block, dict):
                continue

            media_slot = _extract_upload_slot(block.get("media_url"))
            if media_slot:
                block_caption = block.get("caption") or block.get("alt_text") or ""
                add_slot(
                    media_slot,
                    f"Post #{post_index} block #{block_index} media_url",
                    caption=block_caption,
                )

            data = block.get("data")
            if not isinstance(data, dict):
                continue
            items = data.get("items")
            if not isinstance(items, list):
                continue
            for item_index, item in enumerate(items, start=1):
                if not isinstance(item, dict):
                    continue
                item_slot = _extract_upload_slot(item.get("url"))
                if item_slot:
                    add_slot(
                        item_slot,
                        f"Post #{post_index} block #{block_index} gallery item #{item_index} url",
                        caption=item.get("caption") or "",
                    )

    return slots


def _validate_import_payload_size(raw_data: str):
    max_bytes = int(getattr(settings, "BLOG_IMPORT_MAX_JSON_BYTES", 800_000) or 800_000)
    raw_text = str(raw_data or "")
    payload_bytes = len(raw_text.encode("utf-8"))
    if max_bytes > 0 and payload_bytes > max_bytes:
        raise ValidationError(
            _("Import JSON is too large (%(size)d bytes). Max allowed is %(max)d bytes.")
            % {"size": payload_bytes, "max": max_bytes}
        )
    return payload_bytes


def _summarize_import_preview(parsed_posts, posts_payload, slots):
    previews = []
    totals = Counter()
    warnings_total = 0

    for index, post_data in enumerate(parsed_posts, start=1):
        source_post = posts_payload[index - 1] if index - 1 < len(posts_payload) else {}
        post_warnings = []

        blocks = list(post_data.get("blocks") or [])
        block_counter = Counter(block.get("type") for block in blocks if isinstance(block, dict))
        totals.update(block_counter)

        missing_vi = 0
        missing_en = 0
        for block in blocks:
            if (block or {}).get("type") != PostBlock.BlockType.BILINGUAL_TEXT:
                continue
            i18n_data = ((block or {}).get("data") or {}).get("i18n") or {}
            text_vi = str(i18n_data.get("vi") or "").strip()
            text_en = str(i18n_data.get("en") or "").strip()
            if not text_vi:
                missing_vi += 1
            if not text_en:
                missing_en += 1
        if missing_vi:
            post_warnings.append(
                _("Missing Vietnamese translation in %(count)d bilingual block(s).")
                % {"count": missing_vi}
            )
        if missing_en:
            post_warnings.append(
                _("Missing English translation in %(count)d bilingual block(s).")
                % {"count": missing_en}
            )

        hero_slot = _extract_upload_slot((source_post or {}).get("hero_image_url"))
        if hero_slot:
            hero_caption = str(
                (source_post or {}).get("hero_image_caption")
                or (source_post or {}).get("hero_caption")
                or ""
            ).strip()
            if not hero_caption:
                post_warnings.append(
                    _("Hero placeholder %(slot)s has no hero_image_caption.")
                    % {"slot": f"[[UPLOAD:{hero_slot}]]"}
                )

        warnings_total += len(post_warnings)
        previews.append(
            {
                "index": index,
                "title": post_data.get("title"),
                "slug": post_data.get("slug"),
                "status": post_data.get("status"),
                "block_count": len(blocks),
                "block_counter": sorted(block_counter.items()),
                "warnings": post_warnings,
            }
        )

    return {
        "items": previews,
        "totals": {
            "post_count": len(previews),
            "block_count": sum(item["block_count"] for item in previews),
            "warning_count": warnings_total,
            "slot_count": len(slots),
            "block_type_counter": sorted(totals.items()),
        },
    }


def _save_uploaded_slot_file(file_obj, *, request=None):
    content_type = str(getattr(file_obj, "content_type", "") or "").lower()
    if content_type and not content_type.startswith("image/"):
        raise ValidationError(_("Only image files are allowed for image placeholders."))

    variants = save_blog_image_variants(
        file_obj,
        request=request,
        folder_prefix="blog/import_uploads",
    )
    return variants["url"]


def _replace_upload_slots_in_payload(posts_payload, *, url_by_slot):
    for post in posts_payload:
        if not isinstance(post, dict):
            continue

        hero_slot = _extract_upload_slot(post.get("hero_image_url"))
        if hero_slot and hero_slot in url_by_slot:
            post["hero_image_url"] = url_by_slot[hero_slot]

        blocks = post.get("blocks")
        if not isinstance(blocks, list):
            continue

        for block in blocks:
            if not isinstance(block, dict):
                continue

            media_slot = _extract_upload_slot(block.get("media_url"))
            if media_slot and media_slot in url_by_slot:
                block["media_url"] = url_by_slot[media_slot]

            data = block.get("data")
            if not isinstance(data, dict):
                continue
            items = data.get("items")
            if not isinstance(items, list):
                continue

            for item in items:
                if not isinstance(item, dict):
                    continue
                item_slot = _extract_upload_slot(item.get("url"))
                if item_slot and item_slot in url_by_slot:
                    item["url"] = url_by_slot[item_slot]


def _apply_upload_placeholders(raw_data: str, files, *, request=None):
    payload, posts_payload = _parse_posts_payload(raw_data)
    slots = _collect_upload_slot_locations(posts_payload)
    if not slots:
        return json.dumps(payload, ensure_ascii=False)

    missing_slots = []
    url_by_slot = {}
    for slot in slots.keys():
        input_name = f"upload_slot_{slot}"
        uploaded = files.get(input_name)
        if not uploaded:
            missing_slots.append(slot)
            continue
        url_by_slot[slot] = _save_uploaded_slot_file(uploaded, request=request)

    if missing_slots:
        raise ValidationError(
            _("Missing uploaded image for slot(s): %(slots)s")
            % {"slots": ", ".join(sorted(missing_slots))}
        )

    _replace_upload_slots_in_payload(posts_payload, url_by_slot=url_by_slot)
    return json.dumps(payload, ensure_ascii=False)


class PostBlockInline(admin.StackedInline):
    model = PostBlock
    extra = 1
    ordering = ("position",)
    fields = (
        "position",
        "type",
        "text",
        "media_url",
        "caption",
        "alt_text",
        "align",
        "data",
    )
    formfield_overrides = {
        PostBlock._meta.get_field("data").__class__: {"widget": admin.widgets.AdminTextareaWidget}
    }


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = ("title", "status", "published_at", "author", "is_live")
    list_filter = ("status", "published_at", "author")
    search_fields = ("title", "summary", "body")
    prepopulated_fields = {"slug": ("title",)}
    ordering = ("-published_at",)
    date_hierarchy = "published_at"
    autocomplete_fields = ("author",)
    inlines = [PostBlockInline]
    actions = ["publish_now"]
    readonly_fields = ("is_live",)
    change_list_template = "admin/blog/post/change_list.html"

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "import-posts/",
                self.admin_site.admin_view(self.import_posts_view),
                name="blog_post_import_posts",
            ),
            path(
                "import-posts/scan-upload-slots/",
                self.admin_site.admin_view(self.import_posts_scan_slots_view),
                name="blog_post_import_scan_slots",
            ),
            path(
                "import-posts/preview/",
                self.admin_site.admin_view(self.import_posts_preview_view),
                name="blog_post_import_preview",
            ),
        ]
        return custom_urls + urls

    def import_posts_view(self, request):
        if not (self.has_add_permission(request) or self.has_change_permission(request)):
            raise Http404

        if request.method == "POST":
            form = BulkPostImportForm(request.POST, request.FILES)
            if form.is_valid():
                try:
                    _validate_import_payload_size(form.cleaned_data["data"])
                    prepared_data = _apply_upload_placeholders(
                        form.cleaned_data["data"],
                        request.FILES,
                        request=request,
                    )
                    posts = parse_bulk_posts(prepared_data)
                    created_posts, updated_posts, created_blocks = import_posts(
                        posts=posts,
                        replace_existing=form.cleaned_data.get("replace_existing", False),
                        default_author=request.user if request.user.is_authenticated else None,
                    )
                except ValidationError as exc:
                    form.add_error("data", "; ".join(exc.messages) if exc.messages else str(exc))
                except (DataError, IntegrityError) as exc:
                    logger.exception("Blog import failed due to database error.")
                    form.add_error("data", _("Database error while importing posts: %(error)s") % {"error": str(exc)})
                except Exception:
                    logger.exception("Unexpected blog import error.")
                    form.add_error(
                        "data",
                        _("Unexpected import error. Please verify block fields (especially VIDEO media_url) and try again."),
                    )
                else:
                    self.message_user(
                        request,
                        _(
                            "Imported %(created_posts)d post(s), updated %(updated_posts)d post(s), created %(created_blocks)d block(s)."
                        )
                        % {
                            "created_posts": created_posts,
                            "updated_posts": updated_posts,
                            "created_blocks": created_blocks,
                        },
                        level=messages.SUCCESS,
                    )
                    return redirect(reverse("admin:blog_post_changelist"))
        else:
            form = BulkPostImportForm()

        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": _("Import blog posts"),
            "form": form,
        }
        return TemplateResponse(request, "admin/blog/post/import_posts.html", context)

    def import_posts_scan_slots_view(self, request):
        if not (self.has_add_permission(request) or self.has_change_permission(request)):
            raise Http404
        if request.method != "POST":
            raise Http404

        data_value = str(request.POST.get("data") or "")
        slot_items = []
        errors = []
        try:
            _validate_import_payload_size(data_value)
            _payload, posts_payload = _parse_posts_payload(data_value)
            slots = _collect_upload_slot_locations(posts_payload)
            slot_items = [
                {
                    "slot": slot_name,
                    "input_name": f"upload_slot_{slot_name}",
                    "input_id": f"id_upload_slot_{slot_name}",
                    "locations": locations,
                }
                for slot_name, locations in slots.items()
            ]
        except ValidationError as exc:
            errors = list(exc.messages or [str(exc)])

        context = {
            **self.admin_site.each_context(request),
            "slot_items": slot_items,
            "errors": errors,
        }
        return TemplateResponse(request, "admin/blog/post/_import_upload_slots.html", context)

    def import_posts_preview_view(self, request):
        if not (self.has_add_permission(request) or self.has_change_permission(request)):
            raise Http404
        if request.method != "POST":
            raise Http404

        data_value = str(request.POST.get("data") or "")
        errors = []
        preview = None

        try:
            payload_bytes = _validate_import_payload_size(data_value)
            _payload, posts_payload = _parse_posts_payload(data_value)
            parsed_posts = parse_bulk_posts(data_value)
            slots = _collect_upload_slot_locations(posts_payload)
            preview = _summarize_import_preview(parsed_posts, posts_payload, slots)
            preview["payload_bytes"] = payload_bytes
        except ValidationError as exc:
            errors = list(exc.messages or [str(exc)])
        except Exception as exc:  # pragma: no cover - defensive fallback
            logger.exception("Unexpected error while previewing blog import JSON.")
            errors = [str(exc)]

        context = {
            **self.admin_site.each_context(request),
            "preview": preview,
            "errors": errors,
        }
        return TemplateResponse(request, "admin/blog/post/_import_preview.html", context)

    def publish_now(self, request, queryset):
        updated = queryset.update(status=Post.Status.PUBLISHED, published_at=timezone.now())
        self.message_user(
            request, _("%(count)d post(s) marked as published.") % {"count": updated}, messages.SUCCESS
        )

    publish_now.short_description = _("Publish now")

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        post = form.instance
        # Create revision snapshot after blocks are saved
        PostRevision.objects.create(
            post=post,
            created_by=request.user if request.user.is_authenticated else None,
            is_autosave=False,
            payload=post.snapshot(),
        )


@admin.register(PostRevision)
class PostRevisionAdmin(admin.ModelAdmin):
    list_display = ("post", "created_at", "created_by", "is_autosave")
    list_filter = ("is_autosave", "created_at", "created_by")
    search_fields = ("post__title",)
    actions = ["restore_revision"]

    def restore_revision(self, request, queryset):
        restored = 0
        with transaction.atomic():
            for rev in queryset:
                rev.post.apply_snapshot(rev.payload)
                restored += 1
        self.message_user(
            request,
            _("%(count)d revision(s) restored.") % {"count": restored},
            messages.SUCCESS,
        )

    restore_revision.short_description = _("Restore selected revisions")


@admin.register(BlogComment)
class BlogCommentAdmin(admin.ModelAdmin):
    list_display = ("id", "post", "user", "is_deleted", "created_at")
    list_filter = ("is_deleted", "created_at")
    search_fields = ("body", "user__username", "user__email", "post__title")
    autocomplete_fields = ("post", "user", "parent")
    list_select_related = ("post", "user")
    ordering = ("-created_at",)


@admin.register(BlogApiAuditLog)
class BlogApiAuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "route", "status_code", "key_id", "request_id", "ip_address")
    list_filter = ("route", "status_code", "created_at", "key_id")
    search_fields = ("request_id", "key_id", "ip_address", "user_agent")
    readonly_fields = (
        "created_at",
        "route",
        "status_code",
        "key_id",
        "request_id",
        "ip_address",
        "user_agent",
        "detail",
    )
    ordering = ("-created_at",)

    def has_add_permission(self, request):
        return False
