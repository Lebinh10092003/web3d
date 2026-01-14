from django.conf import settings
from django.contrib import admin, messages
from django.db import transaction

from .models import (
    Category,
    ContentFile,
    ContentItem,
    Course,
    CourseFavorite,
    CourseLesson,
    CourseLessonProgress,
    LibrarySideBanner,
    RecapHeroBanner,
    RecapVideo,
)
from .youtube import fetch_playlist_items


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
    filter_horizontal = ("categories", "allowed_groups")
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
    actions = ("import_lessons_from_youtube",)
    change_form_template = "admin/library/course/change_form.html"

    @admin.action(description="Import lessons from YouTube playlist")
    def import_lessons_from_youtube(self, request, queryset):
        for course in queryset:
            self._import_lessons(request, course)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        should_import = "_import_lessons" in request.POST
        if not should_import:
            if not change and (obj.playlist_id or "").strip():
                should_import = True
            elif "playlist_id" in getattr(form, "changed_data", []):
                should_import = True
        if should_import:
            self._import_lessons(request, obj)

    def _import_lessons(self, request, course):
        api_key = getattr(settings, "YOUTUBE_API_KEY", "")
        if not api_key:
            messages.error(request, "Set YOUTUBE_API_KEY to import playlist items.")
            return
        playlist_id = (course.playlist_id or "").strip()
        if not playlist_id:
            messages.warning(request, f"{course.title}: playlist_id is empty.")
            return
        items = fetch_playlist_items(playlist_id, api_key)
        if not items:
            messages.warning(request, f"{course.title}: no items fetched.")
            return
        existing = {
            lesson.video_id: lesson
            for lesson in course.lessons.exclude(video_id="").all()
        }
        with transaction.atomic():
            for idx, item in enumerate(items, start=1):
                video_id = item.get("video_id") or ""
                title = item.get("title") or video_id
                if not video_id:
                    continue
                if video_id in existing:
                    lesson = existing[video_id]
                    lesson.title = title
                    lesson.sort_order = idx
                    lesson.save(update_fields=["title", "sort_order"])
                else:
                    CourseLesson.objects.create(
                        course=course,
                        title=title,
                        video_id=video_id,
                        sort_order=idx,
                    )
        messages.success(request, f"{course.title}: imported {len(items)} lessons.")


@admin.register(CourseLesson)
class CourseLessonAdmin(admin.ModelAdmin):
    list_display = ("title", "course", "sort_order")
    list_filter = ("course",)
    search_fields = ("title", "video_id")


@admin.register(CourseFavorite)
class CourseFavoriteAdmin(admin.ModelAdmin):
    list_display = ("course", "user", "created_at")
    list_filter = ("course", "user")
    search_fields = ("course__title", "user__username")


@admin.register(CourseLessonProgress)
class CourseLessonProgressAdmin(admin.ModelAdmin):
    list_display = ("lesson", "user", "is_completed", "last_watched_at", "updated_at")
    list_filter = ("is_completed", "lesson__course")
    search_fields = ("lesson__title", "user__username")


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
