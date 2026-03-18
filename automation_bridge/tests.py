import json
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

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

    def _create_blog_request(self, *, request_id, requested_by, title):
        response = self.client.post(
            reverse("automation_bridge:blog-publish"),
            data=json.dumps(
                {
                    "request_id": request_id,
                    "source_channel": "whatsapp",
                    "requested_by": requested_by,
                    "mode": "review",
                    "title": title,
                    "article_body": f"Noi dung cho {title}.",
                }
            ),
            content_type="application/json",
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, 201)
        return response.json()

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

    def test_blog_request_latest_detail_filters_by_whatsapp_sender(self):
        self._create_blog_request(
            request_id="req-owner-1",
            requested_by="+84911111111",
            title="Bai viet dau tien",
        )
        self._create_blog_request(
            request_id="req-other-1",
            requested_by="+84922222222",
            title="Bai viet nguoi khac",
        )
        self._create_blog_request(
            request_id="req-owner-2",
            requested_by="+84911111111",
            title="Bai viet moi nhat cua owner",
        )

        response = self.client.get(
            reverse("automation_bridge:blog-request-latest")
            + "?source_channel=whatsapp&requested_by=%2B84911111111",
            **self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        request_payload = response.json()["request"]
        self.assertEqual(request_payload["request_id"], "req-owner-2")
        self.assertEqual(request_payload["requested_by"], "+84911111111")
        self.assertEqual(request_payload["post"]["title"], "Bai viet moi nhat cua owner")

    def test_blog_request_latest_publish_promotes_latest_post_for_sender(self):
        self._create_blog_request(
            request_id="req-owner-old",
            requested_by="+84933333333",
            title="Bai viet cu",
        )
        self._create_blog_request(
            request_id="req-owner-new",
            requested_by="+84933333333",
            title="Bai viet moi nhat",
        )
        self._create_blog_request(
            request_id="req-other-new",
            requested_by="+84944444444",
            title="Bai viet chat khac",
        )

        response = self.client.post(
            reverse("automation_bridge:blog-request-latest-publish"),
            data=json.dumps(
                {
                    "source_channel": "whatsapp",
                    "requested_by": "+84933333333",
                }
            ),
            content_type="application/json",
            **self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["request_id"], "req-owner-new")

        latest_owner_run = BlogAutomationRun.objects.get(request_id="req-owner-new")
        latest_owner_run.created_post.refresh_from_db()
        self.assertEqual(latest_owner_run.created_post.status, Post.Status.PUBLISHED)

        other_run = BlogAutomationRun.objects.get(request_id="req-other-new")
        other_run.created_post.refresh_from_db()
        self.assertEqual(other_run.created_post.status, Post.Status.PENDING_REVIEW)

    def test_blog_request_latest_publish_returns_existing_published_post(self):
        self._create_blog_request(
            request_id="req-published",
            requested_by="+84955555555",
            title="Bai viet da dang",
        )

        first_publish = self.client.post(
            reverse("automation_bridge:blog-request-publish", args=["req-published"]),
            data="{}",
            content_type="application/json",
            **self.auth_headers,
        )
        self.assertEqual(first_publish.status_code, 200)

        response = self.client.post(
            reverse("automation_bridge:blog-request-latest-publish"),
            data=json.dumps(
                {
                    "source_channel": "whatsapp",
                    "requested_by": "+84955555555",
                }
            ),
            content_type="application/json",
            **self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["already_published"])
        self.assertEqual(payload["request_id"], "req-published")
        self.assertEqual(payload["post"]["status"], Post.Status.PUBLISHED)

    def test_blog_request_latest_publish_supports_future_publish_at(self):
        self._create_blog_request(
            request_id="req-schedule-latest",
            requested_by="+84966666666",
            title="Bai viet hen gio",
        )

        publish_at = (timezone.now() + timedelta(days=1)).isoformat()
        response = self.client.post(
            reverse("automation_bridge:blog-request-latest-publish"),
            data=json.dumps(
                {
                    "source_channel": "whatsapp",
                    "requested_by": "+84966666666",
                    "publish_at": publish_at,
                }
            ),
            content_type="application/json",
            **self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["request_id"], "req-schedule-latest")
        self.assertEqual(payload["post"]["status"], Post.Status.SCHEDULED)

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
