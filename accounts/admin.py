from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    fieldsets = BaseUserAdmin.fieldsets + (
        (
            "Profile",
            {
                "fields": (
                    "display_name",
                    "role",
                    "bio",
                    "avatar_path",
                    "points_balance",
                )
            },
        ),
    )
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        (
            "Profile",
            {"fields": ("display_name", "role")},
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
