import json

from django.test import TestCase, override_settings
from django.urls import reverse

from blog.models import BlogApiAuditLog, Post


@override_settings(
    BLOG_POST_API_KEY="",
    BLOG_POST_API_KEYS="bot_a:key_a_secret,bot_b:key_b_secret",
    BLOG_API_MAX_BODY_BYTES=200000,
)
class BlogApiSecurityTests(TestCase):
    def _post(self, payload, *, key="", key_id=""):
        headers = {}
        if key:
            headers["HTTP_X_API_KEY"] = key
        if key_id:
            headers["HTTP_X_API_KEY_ID"] = key_id
        return self.client.post(
            reverse("blog:api-create"),
            data=json.dumps(payload, ensure_ascii=False),
            content_type="application/json",
            **headers,
        )

    def test_api_accepts_rotated_key_and_writes_audit_log(self):
        payload = {
            "title": "API created post",
            "status": "DRAFT",
            "blocks": [
                {"type": "TEXT", "text": "hello"},
            ],
        }
        response = self._post(payload, key="key_b_secret", key_id="bot_b")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Post.objects.count(), 1)
        self.assertEqual(BlogApiAuditLog.objects.count(), 1)
        audit = BlogApiAuditLog.objects.first()
        self.assertEqual(audit.key_id, "bot_b")
        self.assertEqual(audit.status_code, 201)

    def test_api_rejects_wrong_key_id_hint(self):
        payload = {"title": "Unauthorized", "blocks": []}
        response = self._post(payload, key="key_b_secret", key_id="bot_a")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(BlogApiAuditLog.objects.count(), 1)
        audit = BlogApiAuditLog.objects.first()
        self.assertEqual(audit.status_code, 401)

    @override_settings(BLOG_API_MAX_BODY_BYTES=80)
    def test_api_rejects_oversized_payload(self):
        payload = {"title": "Too big", "blocks": [{"type": "TEXT", "text": "x" * 300}]}
        response = self._post(payload, key="key_a_secret", key_id="bot_a")
        self.assertEqual(response.status_code, 413)
        self.assertEqual(BlogApiAuditLog.objects.count(), 1)
        audit = BlogApiAuditLog.objects.first()
        self.assertEqual(audit.status_code, 413)
