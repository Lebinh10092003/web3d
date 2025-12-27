from django.contrib import admin

from .models import Comment, Favorite, Rating


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ("content", "user", "created_at", "is_deleted")
    list_filter = ("is_deleted",)
    search_fields = ("body",)


@admin.register(Rating)
class RatingAdmin(admin.ModelAdmin):
    list_display = ("content", "user", "score", "created_at")
    list_filter = ("score",)


@admin.register(Favorite)
class FavoriteAdmin(admin.ModelAdmin):
    list_display = ("content", "user", "created_at")
