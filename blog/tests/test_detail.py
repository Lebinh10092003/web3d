from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from blog.models import Post


@override_settings(ALLOWED_HOSTS=["localhost", "testserver"])
class BlogDetailViewTests(TestCase):
    def test_detail_page_renders_hreflang_without_template_error(self):
        user = get_user_model().objects.create_user(
            username="detail_author",
            email="detail@example.com",
            password="password123",
        )
        post = Post.objects.create(
            title="Enjoy AI 2026",
            summary="Summary",
            body="Body",
            status=Post.Status.PUBLISHED,
            published_at=timezone.now(),
            author=user,
        )

        response = Client(HTTP_HOST="localhost").get(f"/blog/{post.slug}/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'hreflang="x-default"')
