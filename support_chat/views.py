import json

from django.conf import settings
from django.db import transaction
from django.http import Http404, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from web3d.queue import enqueue_task

from .models import SupportConversation, SupportMessage
from .services import (
    create_operator_reply,
    dispatch_owner_notification,
    get_or_create_conversation,
    parse_operator_command,
    serialize_message,
)


def _ensure_enabled():
    if not getattr(settings, "SUPPORT_CHAT_ENABLED", False):
        raise Http404


def _json_body(request):
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        payload = {}
    return payload if isinstance(payload, dict) else {}


def _error(message, *, status=400):
    return JsonResponse({"ok": False, "error": message}, status=status)


@require_GET
def messages_feed(request):
    _ensure_enabled()
    conversation_code = request.session.get("support_chat_conversation_code", "").strip()
    if not conversation_code:
        return JsonResponse({"ok": True, "conversation_code": "", "messages": []})

    conversation = SupportConversation.objects.filter(conversation_code=conversation_code).first()
    if conversation is None:
        request.session.pop("support_chat_conversation_code", None)
        return JsonResponse({"ok": True, "conversation_code": "", "messages": []})

    try:
        after_id = int(request.GET.get("after_id", "0") or "0")
    except ValueError:
        after_id = 0

    messages = conversation.messages.all()
    if after_id > 0:
        messages = messages.filter(id__gt=after_id)

    return JsonResponse(
        {
            "ok": True,
            "conversation_code": conversation.conversation_code,
            "status": conversation.status,
            "messages": [serialize_message(message) for message in messages],
        }
    )


@require_POST
def send_message(request):
    _ensure_enabled()
    payload = _json_body(request)
    body = str(payload.get("message") or "").strip()
    if not body:
        return _error("Message is required.")
    if len(body) > settings.SUPPORT_CHAT_MESSAGE_MAX_CHARS:
        return _error("Message is too long.")

    created_messages = []
    with transaction.atomic():
        conversation, _ = get_or_create_conversation(request, payload)
        now = timezone.now()
        customer_message = SupportMessage.objects.create(
            conversation=conversation,
            sender_type=SupportMessage.SenderType.CUSTOMER,
            source=SupportMessage.Source.WEB,
            body=body,
            metadata={
                "page_url": conversation.page_url,
                "page_title": conversation.page_title,
            },
        )
        created_messages.append(customer_message)

        conversation.last_customer_message_at = now
        conversation.status = SupportConversation.Status.OPEN

        auto_reply = (settings.SUPPORT_CHAT_AUTO_REPLY_MESSAGE or "").strip()
        update_fields = ["last_customer_message_at", "status", "updated_at"]
        if auto_reply and conversation.auto_reply_sent_at is None:
            system_message = SupportMessage.objects.create(
                conversation=conversation,
                sender_type=SupportMessage.SenderType.SYSTEM,
                source=SupportMessage.Source.SYSTEM,
                body=auto_reply,
            )
            created_messages.append(system_message)
            conversation.auto_reply_sent_at = now
            update_fields.append("auto_reply_sent_at")

        conversation.save(update_fields=update_fields)
        transaction.on_commit(
            lambda: enqueue_task(dispatch_owner_notification, conversation.id, customer_message.id)
        )

    return JsonResponse(
        {
            "ok": True,
            "conversation_code": conversation.conversation_code,
            "messages": [serialize_message(message) for message in created_messages],
        }
    )


@csrf_exempt
@require_POST
def operator_reply(request):
    _ensure_enabled()
    token = (settings.SUPPORT_CHAT_OPERATOR_TOKEN or "").strip()
    if not token:
        return _error("Operator token is not configured.", status=503)

    auth_header = request.headers.get("Authorization", "")
    if auth_header != f"Bearer {token}":
        return _error("Unauthorized.", status=403)

    payload = _json_body(request)
    conversation_code = str(payload.get("conversation_code") or "").strip().upper()
    body = str(payload.get("message") or "").strip()
    source = str(payload.get("source") or SupportMessage.Source.WHATSAPP).strip() or SupportMessage.Source.WHATSAPP

    if not conversation_code and not body:
        command = str(payload.get("command") or "").strip()
        conversation_code, body = parse_operator_command(command)

    if not conversation_code or not body:
        return _error("conversation_code and message are required.")

    conversation = SupportConversation.objects.filter(conversation_code=conversation_code).first()
    if conversation is None:
        return _error("Conversation not found.", status=404)

    message = create_operator_reply(conversation, body, source=source)

    return JsonResponse(
        {
            "ok": True,
            "conversation_code": conversation.conversation_code,
            "message": serialize_message(message),
        }
    )
