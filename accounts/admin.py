from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User
from .groups import sync_user_role_from_groups


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    fieldsets = BaseUserAdmin.fieldsets + (
        (
            "Profile",
            {
                "fields": (
                    "display_name",
                    "bio",
                    "avatar_path",
                    "website_url",
                    "facebook_url",
                    "github_url",
                    "points_balance",
                )
            },
        ),
    )
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        (
            "Profile",
            {"fields": ("display_name",)},
        ),
    )
    list_display = (
        "username",
        "email",
        "display_name",
        "role",
        "is_staff",
        "is_active",
    )
    list_filter = ("role", "is_staff", "is_active")
    search_fields = ("username", "email", "display_name")

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        sync_user_role_from_groups(form.instance, add_missing_group_from_role=False)
