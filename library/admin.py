from django.contrib import admin

from .models import (
    Category,
    ContentFile,
    ContentItem,
    Course,
    CourseLesson,
    LibrarySideBanner,
    RecapHeroBanner,
    RecapVideo,
)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "parent", "is_active")
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}


@admin.register(ContentItem)
class ContentItemAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "slug",
        "content_type",
        "owner",
        "download_cost_points",
        "status",
        "is_public",
        "created_at",
    )
    list_filter = ("content_type", "status", "is_public")
    search_fields = ("title", "slug", "description")
    filter_horizontal = ("categories",)
    prepopulated_fields = {"slug": ("title",)}
    exclude = ("price_vnd",)


@admin.register(ContentFile)
class ContentFileAdmin(admin.ModelAdmin):
    list_display = ("content", "kind", "mime_type", "size_bytes", "created_at")
    list_filter = ("kind", "mime_type")
    search_fields = ("storage_path",)


class CourseLessonInline(admin.TabularInline):
    model = CourseLesson
    extra = 0
    fields = ("title", "video_id", "sort_order")


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ("title", "slug", "is_published", "sort_order", "updated_at")
    list_filter = ("is_published",)
    search_fields = ("title", "slug", "description", "playlist_id", "featured_video_id")
    prepopulated_fields = {"slug": ("title",)}
    inlines = (CourseLessonInline,)


@admin.register(CourseLesson)
class CourseLessonAdmin(admin.ModelAdmin):
    list_display = ("title", "course", "sort_order")
    list_filter = ("course",)
    search_fields = ("title", "video_id")


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


@admin.register(LibrarySideBanner)
class LibrarySideBannerAdmin(admin.ModelAdmin):
    list_display = ("title", "position", "is_active", "sort_order", "updated_at")
    list_filter = ("position", "is_active")
    search_fields = ("title", "link_url")
