from unittest.mock import patch

from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .models import SupportConversation, SupportMessage
from .services import build_owner_notification


@override_settings(
    SUPPORT_CHAT_ENABLED=True,
    SUPPORT_CHAT_AUTO_REPLY_MESSAGE="Auto reply",
    SUPPORT_CHAT_OPERATOR_TOKEN="secret-token",
    USE_BACKGROUND_JOBS=False,
)
class SupportChatViewTests(TestCase):
    def setUp(self):
        self.client = Client()

    @patch("support_chat.views.dispatch_owner_notification", return_value=False)
    def test_send_message_creates_conversation_and_auto_reply(self, _dispatch):
        response = self.client.post(
            reverse("support_chat:send"),
            data='{"message":"Hello from customer","page_url":"https://example.com/test"}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(len(payload["messages"]), 2)
        conversation = SupportConversation.objects.get(conversation_code=payload["conversation_code"])
        self.assertEqual(conversation.messages.count(), 2)
        self.assertEqual(conversation.messages.first().sender_type, SupportMessage.SenderType.CUSTOMER)

    def test_operator_reply_accepts_command_format(self):
        conversation = SupportConversation.objects.create(conversation_code="W4821")
        response = self.client.post(
            reverse("support_chat:operator-reply"),
            data='{"command":"#W4821 Reply from operator"}',
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer secret-token",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["conversation_code"], conversation.conversation_code)
        self.assertEqual(conversation.messages.count(), 1)

    def test_build_owner_notification_includes_explicit_relay_instruction(self):
        conversation = SupportConversation.objects.create(
            conversation_code="W4821",
            visitor_name="Alice",
            visitor_phone="0123456789",
            page_title="Robot page",
            page_url="https://stemrobotics.io.vn/robots",
        )
        message = SupportMessage.objects.create(
            conversation=conversation,
            sender_type=SupportMessage.SenderType.CUSTOMER,
            source=SupportMessage.Source.WEB,
            body="Hello from customer",
        )

        notification = build_owner_notification(conversation, message)

        self.assertIn("Respond with ONLY the operator notification text below.", notification)
        self.assertIn("[W4821] New website chat", notification)
        self.assertIn("Visitor: Alice", notification)
        self.assertIn("#W4821 Your reply here", notification)
