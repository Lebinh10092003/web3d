import json
import logging
import re
from urllib import error, request

from django.conf import settings
from django.utils.crypto import get_random_string

from .models import SupportConversation, SupportMessage


logger = logging.getLogger(__name__)

OPERATOR_COMMAND_RE = re.compile(r"^#(?P<code>W[0-9A-Z]{4,})\s+(?P<body>.+)$", re.S)


def _clip(value, max_length):
    text = str(value or "").strip()
    if len(text) <= max_length:
        return text
    return text[:max_length]


def generate_conversation_code():
    for _ in range(24):
        code = f"W{get_random_string(6, allowed_chars='23456789')}"
        if not SupportConversation.objects.filter(conversation_code=code).exists():
            return code
    raise RuntimeError("Unable to generate a unique support chat code.")


def serialize_message(message):
    return {
        "id": message.id,
        "sender_type": message.sender_type,
        "source": message.source,
        "body": message.body,
        "created_at": message.created_at.isoformat(),
    }


def parse_operator_command(command):
    text = str(command or "").strip()
    match = OPERATOR_COMMAND_RE.match(text)
    if not match:
        return "", ""
    return match.group("code").upper(), match.group("body").strip()


def get_or_create_conversation(request, payload):
    conversation_code = str(request.session.get("support_chat_conversation_code") or "").strip()
    conversation = None
    if conversation_code:
        conversation = SupportConversation.objects.filter(conversation_code=conversation_code).first()

    if request.session.session_key is None:
        request.session.save()
    session_key = request.session.session_key or ""

    created = False
    if conversation is None:
        conversation = SupportConversation.objects.create(
            conversation_code=generate_conversation_code(),
            session_key=session_key,
        )
        request.session["support_chat_conversation_code"] = conversation.conversation_code
        request.session.modified = True
        created = True

    fields = []
    if session_key and conversation.session_key != session_key:
        conversation.session_key = session_key
        fields.append("session_key")

    field_limits = {
        "visitor_name": 120,
        "visitor_phone": 40,
        "page_url": 500,
        "page_title": 200,
    }
    for field_name, max_length in field_limits.items():
        value = _clip(payload.get(field_name), max_length)
        if value and getattr(conversation, field_name) != value:
            setattr(conversation, field_name, value)
            fields.append(field_name)

    if fields:
        fields.append("updated_at")
        conversation.save(update_fields=fields)

    return conversation, created


def build_owner_notification(conversation, message):
    operator_lines = [f"[{conversation.conversation_code}] New website chat"]
    if conversation.visitor_name:
        operator_lines.append(f"Visitor: {conversation.visitor_name}")
    if conversation.visitor_phone:
        operator_lines.append(f"Phone: {conversation.visitor_phone}")
    if conversation.page_title:
        operator_lines.append(f"Page title: {conversation.page_title}")
    if conversation.page_url:
        operator_lines.append(f"Page URL: {conversation.page_url}")
    operator_lines.extend(
        [
            f"Message: {message.body}",
            "",
            "Reply format:",
            f"#{conversation.conversation_code} Your reply here",
        ]
    )
    operator_notification = "\n".join(operator_lines)
    # OpenClaw /hooks/agent delivers the agent's response, not the raw hook payload.
    # Make the relay instruction explicit so the operator receives the exact website chat notice.
    return "\n".join(
        [
            "Task: relay this website chat notification to the WhatsApp operator immediately.",
            "Respond with ONLY the operator notification text below.",
            "Do not add commentary, greetings, markdown fences, or extra explanations.",
            "",
            operator_notification,
        ]
    )


def dispatch_owner_notification(conversation_id, message_id):
    base_url = (settings.SUPPORT_CHAT_OPENCLAW_BASE_URL or "").strip().rstrip("/")
    hook_token = (settings.SUPPORT_CHAT_OPENCLAW_HOOK_TOKEN or "").strip()
    owner_whatsapp = (settings.SUPPORT_CHAT_OWNER_WHATSAPP or "").strip()
    if not base_url or not hook_token or not owner_whatsapp:
        logger.info("Support chat notification skipped because OpenClaw settings are incomplete.")
        return False

    conversation = SupportConversation.objects.filter(pk=conversation_id).first()
    message = SupportMessage.objects.filter(pk=message_id).first()
    if conversation is None or message is None:
        logger.warning(
            "Support chat notification skipped because conversation=%s or message=%s was not found.",
            conversation_id,
            message_id,
        )
        return False

    hook_path = (settings.SUPPORT_CHAT_OPENCLAW_HOOK_PATH or "/hooks/agent").strip()
    if not hook_path.startswith("/"):
        hook_path = f"/{hook_path}"
    endpoint = f"{base_url}{hook_path}"
    payload = {
        "agentId": settings.SUPPORT_CHAT_OPENCLAW_AGENT_ID,
        "message": build_owner_notification(conversation, message),
        "deliver": True,
        "channel": "whatsapp",
        "to": owner_whatsapp,
        "wakeMode": "now",
    }
    data = json.dumps(payload).encode("utf-8")
    http_request = request.Request(
        endpoint,
        data=data,
        headers={
            "Authorization": f"Bearer {hook_token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with request.urlopen(http_request, timeout=settings.SUPPORT_CHAT_REQUEST_TIMEOUT) as response:
            response.read()
            return 200 <= response.status < 300
    except error.HTTPError as exc:
        logger.warning("OpenClaw notification failed with status %s.", exc.code)
    except error.URLError:
        logger.exception("OpenClaw notification failed due to a network error.")
    except Exception:
        logger.exception("OpenClaw notification failed unexpectedly.")
    return False
