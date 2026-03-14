from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from blog.models import Post, PostBlock

from .models import BlogAutomationRun


def _fake_ingest(url, *, kind="auto", request_obj=None):
    text = str(url or "").strip()
    suffix = text.rsplit("/", 1)[-1].replace(".", "-") or "asset"
    resolved_kind = kind
    if resolved_kind == "auto":
        resolved_kind = "video" if suffix.endswith(("mp4", "webm", "mov")) else "image"
    return {
        "original_url": text,
        "resolved_url": f"https://media.example/{suffix}",
        "kind": resolved_kind,
        "ingested": True,
    }


@override_settings(
    BLOG_AUTOMATION_ENABLED=True,
    BLOG_AUTOMATION_TOKEN="bridge-token",
    BLOG_AUTOMATION_DEFAULT_STATUS=Post.Status.PENDING_REVIEW,
    BLOG_AUTOMATION_DEFAULT_AUTHOR_USERNAME="editor",
    BLOG_AUTOMATION_INCLUDE_SOURCES_BLOCK=True,
    BLOG_AUTOMATION_REQUEST_TIMEOUT=5,
    BLOG_AUTOMATION_MAX_VIDEO_MB=50,
    BLOG_AUTOMATION_MEDIA_FOLDER="blog/test-automation",
    BLOG_AUTOMATION_USER_AGENT="test-agent",
)
class BlogAutomationBridgeTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.auth_headers = {"HTTP_AUTHORIZATION": "Bearer bridge-token"}
        get_user_model().objects.create_user(
            username="editor",
            email="editor@example.com",
            password="password123",
        )

    @patch("automation_bridge.services.ingest_remote_media", side_effect=_fake_ingest)
    def test_blog_publish_creates_review_post_with_sources_and_media(self, _ingest):
        response = self.client.post(
            reverse("automation_bridge:blog-publish"),
            data="""
            {
              "request_id": "req-001",
              "source_channel": "whatsapp",
              "requested_by": "+84999999999",
              "mode": "review",
              "title": "Robot STEM cho hoc sinh tieu hoc",
              "summary": "Tong quan nhanh ve robot STEM cho tre em.",
              "article": "Bai viet mo ta loi ich cua robot STEM cho hoc sinh tieu hoc.",
              "hero": "https://cdn.example.com/hero.jpg",
              "images": [
                "https://cdn.example.com/image-1.jpg",
                {"url": "https://cdn.example.com/image-2.jpg", "caption": "Lop hoc demo"}
              ],
              "video": "https://www.youtube.com/watch?v=demo123",
              "sources": [
                {"title": "Nguon A", "url": "https://official.example.com/a", "note": "Thong tin tong quan"}
              ]
            }
            """,
            content_type="application/json",
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertTrue(payload["ok"])

        run = BlogAutomationRun.objects.get(request_id="req-001")
        self.assertEqual(run.status, BlogAutomationRun.Status.CREATED)
        self.assertIsNotNone(run.created_post)
        self.assertEqual(run.created_post.status, Post.Status.PENDING_REVIEW)
        self.assertEqual(run.created_post.author.username, "editor")
        self.assertEqual(run.created_post.blocks.count(), 5)
        self.assertTrue(
            run.created_post.blocks.filter(type=PostBlock.BlockType.VIDEO).exists()
        )
        self.assertTrue(
            any(block.data.get("sources") for block in run.created_post.blocks.all())
        )
        self.assertEqual(len(payload["media"]), 4)
        self.assertEqual(payload["sources"][0]["title"], "Nguon A")

    @patch("automation_bridge.services.ingest_remote_media", side_effect=_fake_ingest)
    def test_blog_publish_is_idempotent_for_duplicate_request_id(self, _ingest):
        payload = """
        {
          "request_id": "req-dup",
          "mode": "review",
          "title": "Bai viet thu nghiem",
          "article_body": "Noi dung bai viet thu nghiem."
        }
        """
        first = self.client.post(
            reverse("automation_bridge:blog-publish"),
            data=payload,
            content_type="application/json",
            **self.auth_headers,
        )
        second = self.client.post(
            reverse("automation_bridge:blog-publish"),
            data=payload,
            content_type="application/json",
            **self.auth_headers,
        )

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertTrue(second.json()["duplicate"])
        self.assertEqual(Post.objects.count(), 1)

    @patch("automation_bridge.services.ingest_remote_media", side_effect=_fake_ingest)
    def test_blog_request_detail_and_publish_promote_post_status(self, _ingest):
        create_response = self.client.post(
            reverse("automation_bridge:blog-publish"),
            data="""
            {
              "request_id": "req-publish",
              "mode": "review",
              "title": "Bai viet can duyet",
              "article_body": "Noi dung cho bai viet can duyet."
            }
            """,
            content_type="application/json",
            **self.auth_headers,
        )
        self.assertEqual(create_response.status_code, 201)

        preview_response = self.client.get(
            reverse("automation_bridge:blog-request-detail", args=["req-publish"]),
            **self.auth_headers,
        )
        self.assertEqual(preview_response.status_code, 200)
        self.assertEqual(preview_response.json()["request"]["request_id"], "req-publish")

        publish_response = self.client.post(
            reverse("automation_bridge:blog-request-publish", args=["req-publish"]),
            data="{}",
            content_type="application/json",
            **self.auth_headers,
        )
        self.assertEqual(publish_response.status_code, 200)

        run = BlogAutomationRun.objects.get(request_id="req-publish")
        run.created_post.refresh_from_db()
        self.assertEqual(run.created_post.status, Post.Status.PUBLISHED)
        self.assertIn("publish_request", run.payload)

    def test_media_ingest_accepts_local_media_url_without_download(self):
        response = self.client.post(
            reverse("automation_bridge:media-ingest"),
            data='{"url":"/media/blog/uploads/example.webp","kind":"image"}',
            content_type="application/json",
            **self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        item = response.json()["items"][0]
        self.assertFalse(item["ingested"])
        self.assertEqual(item["resolved_url"], "http://testserver/media/blog/uploads/example.webp")
