from django.contrib import admin

from .models import ContributionSubmission


@admin.register(ContributionSubmission)
class ContributionSubmissionAdmin(admin.ModelAdmin):
    list_display = ("title", "user", "competition", "category", "status", "created_at")
    list_filter = ("status", "content_type", "competition", "category")
    search_fields = ("title", "description")
