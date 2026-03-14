from django.contrib import admin, messages
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from .models import SupportConversation, SupportMessage
from .services import create_operator_reply


class SupportMessageInline(admin.TabularInline):
    model = SupportMessage
    extra = 0
    can_delete = False
    fields = ("sender_type", "source", "body", "created_at")
    readonly_fields = fields
    ordering = ("created_at",)


@admin.register(SupportConversation)
class SupportConversationAdmin(admin.ModelAdmin):
    change_form_template = "admin/support_chat/supportconversation/change_form.html"
    list_display = (
        "conversation_code",
        "reply_state",
        "status",
        "visitor_name",
        "visitor_phone",
        "latest_message_preview",
        "last_customer_message_at",
        "last_operator_message_at",
        "open_conversation_link",
        "updated_at",
    )
    list_filter = ("status", "created_at", "last_customer_message_at", "last_operator_message_at")
    search_fields = ("conversation_code", "visitor_name", "visitor_phone", "page_url", "page_title")
    readonly_fields = ("conversation_code", "session_key", "created_at", "updated_at")
    inlines = [SupportMessageInline]

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("messages")

    @admin.display(description=_("Reply state"))
    def reply_state(self, obj):
        if obj.last_customer_message_at and (
            not obj.last_operator_message_at or obj.last_customer_message_at > obj.last_operator_message_at
        ):
            return format_html('<strong style="color:#b42318;">{}</strong>', _("Awaiting staff reply"))
        return format_html('<span style="color:#027a48;">{}</span>', _("Replied"))

    @admin.display(description=_("Latest message"))
    def latest_message_preview(self, obj):
        message = obj.messages.order_by("-id").first()
        if not message:
            return "-"
        label = dict(SupportMessage.SenderType.choices).get(message.sender_type, message.sender_type)
        text = str(message.body or "").strip().replace("\n", " ")
        if len(text) > 80:
            text = f"{text[:77]}..."
        return f"{label}: {text}"

    @admin.display(description=_("Open"))
    def open_conversation_link(self, obj):
        url = reverse("admin:support_chat_supportconversation_change", args=[obj.pk])
        return format_html('<a class="button" href="{}">{}</a>', url, _("Reply"))

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "<path:object_id>/manual-reply/",
                self.admin_site.admin_view(self.manual_reply_view),
                name="support_chat_supportconversation_manual_reply",
            ),
        ]
        return custom_urls + urls

    def change_view(self, request, object_id, form_url="", extra_context=None):
        conversation = self.get_object(request, object_id)
        extra = extra_context or {}
        if conversation is not None:
            extra["conversation_messages"] = conversation.messages.order_by("id")
            extra["manual_reply_url"] = reverse(
                "admin:support_chat_supportconversation_manual_reply",
                args=[conversation.pk],
            )
        return super().change_view(request, object_id, form_url=form_url, extra_context=extra)

    def manual_reply_view(self, request, object_id):
        conversation = get_object_or_404(SupportConversation, pk=object_id)
        if not self.has_change_permission(request, obj=conversation):
            return TemplateResponse(request, "admin/403.html", status=403)

        reply_text = str(request.POST.get("reply_text") or "").strip()
        if not reply_text:
            self.message_user(request, _("Reply message is required."), level=messages.ERROR)
            return HttpResponseRedirect(
                reverse("admin:support_chat_supportconversation_change", args=[conversation.pk])
            )

        create_operator_reply(conversation, reply_text, source=SupportMessage.Source.API)
        self.message_user(request, _("Manual reply saved to the conversation."))
        return HttpResponseRedirect(
            reverse("admin:support_chat_supportconversation_change", args=[conversation.pk])
        )


@admin.register(SupportMessage)
class SupportMessageAdmin(admin.ModelAdmin):
    list_display = ("conversation", "sender_type", "source", "created_at")
    list_filter = ("sender_type", "source", "created_at")
    search_fields = ("conversation__conversation_code", "body")
    readonly_fields = ("created_at",)
