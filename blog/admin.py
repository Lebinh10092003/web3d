import logging

from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.db import DataError, IntegrityError, transaction
from django.http import Http404
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .forms import BulkPostImportForm
from .importer import import_posts, parse_bulk_posts
from .models import BlogComment, Post, PostBlock, PostRevision


logger = logging.getLogger(__name__)


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
        ]
        return custom_urls + urls

    def import_posts_view(self, request):
        if not (self.has_add_permission(request) or self.has_change_permission(request)):
            raise Http404

        if request.method == "POST":
            form = BulkPostImportForm(request.POST)
            if form.is_valid():
                try:
                    posts = parse_bulk_posts(form.cleaned_data["data"])
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
