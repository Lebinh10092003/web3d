from django.contrib import admin

from .models import SupportConversation, SupportMessage


class SupportMessageInline(admin.TabularInline):
    model = SupportMessage
    extra = 0
    can_delete = False
    fields = ("sender_type", "source", "body", "created_at")
    readonly_fields = fields
    ordering = ("created_at",)


@admin.register(SupportConversation)
class SupportConversationAdmin(admin.ModelAdmin):
    list_display = (
        "conversation_code",
        "status",
        "visitor_name",
        "visitor_phone",
        "last_customer_message_at",
        "last_operator_message_at",
        "updated_at",
    )
    list_filter = ("status", "created_at", "last_customer_message_at", "last_operator_message_at")
    search_fields = ("conversation_code", "visitor_name", "visitor_phone", "page_url", "page_title")
    readonly_fields = ("conversation_code", "session_key", "created_at", "updated_at")
    inlines = [SupportMessageInline]


@admin.register(SupportMessage)
class SupportMessageAdmin(admin.ModelAdmin):
    list_display = ("conversation", "sender_type", "source", "created_at")
    list_filter = ("sender_type", "source", "created_at")
    search_fields = ("conversation__conversation_code", "body")
    readonly_fields = ("created_at",)
