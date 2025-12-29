from django.contrib import admin
from django.utils.html import format_html

from library.storage import build_signed_url

from .models import ContributionSubmission


@admin.register(ContributionSubmission)
class ContributionSubmissionAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "user",
        "competition",
        "category",
        "status",
        "download_cost_points",
        "award_points",
        "download_source",
        "created_at",
    )
    list_filter = ("status", "content_type", "competition", "category")
    search_fields = ("title", "description")
    exclude = ("price_vnd",)

    @admin.display(description="Source file")
    def download_source(self, obj):
        if not obj.file_path:
            return "-"
        url = build_signed_url(obj.file_path, download=True)
        if not url:
            return obj.file_path
        return format_html('<a href="{}" target="_blank" rel="noopener">Download</a>', url)
