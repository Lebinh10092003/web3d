from django.contrib import admin

from .models import ContentDownload, ContentView


@admin.register(ContentView)
class ContentViewAdmin(admin.ModelAdmin):
    list_display = ("content", "user", "ip_address", "created_at")
    list_filter = ("created_at",)


@admin.register(ContentDownload)
class ContentDownloadAdmin(admin.ModelAdmin):
    list_display = ("content", "user", "ip_address", "created_at")
    list_filter = ("created_at",)
