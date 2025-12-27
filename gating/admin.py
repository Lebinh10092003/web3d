from django.contrib import admin

from .models import PointLedger, Unlock


@admin.register(PointLedger)
class PointLedgerAdmin(admin.ModelAdmin):
    list_display = ("user", "delta", "reason", "created_at")
    list_filter = ("reason",)
    search_fields = ("reason",)


@admin.register(Unlock)
class UnlockAdmin(admin.ModelAdmin):
    list_display = ("user", "content", "method", "cost_points", "created_at")
    list_filter = ("method",)
