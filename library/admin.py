from django.contrib import admin

from .models import Category, ContentFile, ContentItem, RecapHeroBanner, RecapVideo


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "parent", "is_active")
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}


@admin.register(ContentItem)
class ContentItemAdmin(admin.ModelAdmin):
    list_display = ("title", "content_type", "owner", "status", "is_public", "created_at")
    list_filter = ("content_type", "status", "is_public")
    search_fields = ("title", "description")
    filter_horizontal = ("categories",)


@admin.register(ContentFile)
class ContentFileAdmin(admin.ModelAdmin):
    list_display = ("content", "kind", "mime_type", "size_bytes", "created_at")
    list_filter = ("kind", "mime_type")
    search_fields = ("storage_path",)


@admin.register(RecapVideo)
class RecapVideoAdmin(admin.ModelAdmin):
    list_display = ("competition", "year", "title", "video_provider", "is_published", "updated_at")
    list_filter = ("competition", "year", "video_provider", "is_published")
    search_fields = ("competition", "title", "summary", "video_id")
    ordering = ("competition", "-year")


@admin.register(RecapHeroBanner)
class RecapHeroBannerAdmin(admin.ModelAdmin):
    list_display = ("title", "is_active", "updated_at")
    list_filter = ("is_active", "updated_at")
    search_fields = ("title", "body", "eyebrow")
