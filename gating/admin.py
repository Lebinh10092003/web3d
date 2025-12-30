from django.contrib import admin

from .models import PaymentTransaction, PointLedger, PointPackage, PointTopupTransaction, Unlock


@admin.register(PointLedger)
class PointLedgerAdmin(admin.ModelAdmin):
    list_display = ("user", "delta", "reason", "created_at")
    list_filter = ("reason",)
    search_fields = ("reason",)


@admin.register(Unlock)
class UnlockAdmin(admin.ModelAdmin):
    list_display = ("user", "content", "method", "cost_points", "created_at")
    list_filter = ("method",)


@admin.register(PaymentTransaction)
class PaymentTransactionAdmin(admin.ModelAdmin):
    list_display = ("app_trans_id", "user", "content", "amount", "status", "created_at")
    list_filter = ("status", "provider", "currency")
    search_fields = ("app_trans_id", "zp_trans_id", "user__username")


@admin.register(PointPackage)
class PointPackageAdmin(admin.ModelAdmin):
    list_display = ("name", "points", "price_vnd", "is_active", "sort_order")
    list_filter = ("is_active",)
    search_fields = ("name",)


@admin.register(PointTopupTransaction)
class PointTopupTransactionAdmin(admin.ModelAdmin):
    list_display = ("app_trans_id", "user", "points", "amount", "status", "created_at")
    list_filter = ("status", "provider", "currency")
    search_fields = ("app_trans_id", "zp_trans_id", "user__username")
