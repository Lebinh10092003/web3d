from django.contrib import admin, messages
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .models import Post, PostBlock, PostRevision


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
