import json

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse


class BlogAdminImportTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.admin_user = user_model.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="adminpass123",
        )
        self.client.force_login(self.admin_user)

    def test_scan_slots_includes_location_and_caption(self):
        payload = {
            "posts": [
                {
                    "title": "Slot test",
                    "hero_image_url": "[[UPLOAD:HERO]]",
                    "hero_image_caption": "Hero caption",
                    "blocks": [
                        {
                            "type": "IMAGE",
                            "media_url": "[[UPLOAD:IMG_MAIN]]",
                            "caption": "Main image caption",
                        },
                        {
                            "type": "GALLERY",
                            "data": {
                                "items": [
                                    {"url": "[[UPLOAD:GAL_A]]", "caption": "Gallery A"},
                                ]
                            },
                        },
                    ],
                }
            ]
        }

        response = self.client.post(
            reverse("admin:blog_post_import_scan_slots"),
            {"data": json.dumps(payload, ensure_ascii=False)},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Post #1 hero_image_url")
        self.assertContains(response, "Hero caption")
        self.assertContains(response, "Main image caption")
        self.assertContains(response, "Gallery A")

    def test_preview_shows_bilingual_missing_translation_warning(self):
        payload = {
            "posts": [
                {
                    "title": "Preview warning test",
                    "status": "DRAFT",
                    "blocks": [
                        {
                            "type": "BILINGUAL_TEXT",
                            "text_vi": "Noi dung tieng Viet co dau",
                            "text_en": "",
                        }
                    ],
                }
            ]
        }
        response = self.client.post(
            reverse("admin:blog_post_import_preview"),
            {"data": json.dumps(payload, ensure_ascii=False)},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Missing English translation")

    @override_settings(BLOG_IMPORT_MAX_JSON_BYTES=50)
    def test_preview_rejects_oversized_payload(self):
        oversized = {"posts": [{"title": "A" * 200, "blocks": []}]}
        response = self.client.post(
            reverse("admin:blog_post_import_preview"),
            {"data": json.dumps(oversized)},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Import JSON is too large")
