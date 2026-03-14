from django.contrib import admin

from .models import BlogAutomationRun


@admin.register(BlogAutomationRun)
class BlogAutomationRunAdmin(admin.ModelAdmin):
    list_display = (
        "request_id",
        "source_channel",
        "requested_by",
        "status",
        "created_post",
        "created_at",
    )
    list_filter = ("status", "source_channel", "created_at")
    search_fields = ("request_id", "requested_by", "command_text")
    readonly_fields = (
        "request_id",
        "source_channel",
        "requested_by",
        "command_text",
        "payload",
        "sources",
        "media_results",
        "status",
        "created_post",
        "error_detail",
        "created_at",
        "updated_at",
    )
