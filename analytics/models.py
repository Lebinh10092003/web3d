from django.conf import settings
from django.db import models

from library.models import ContentItem


class ContentView(models.Model):
    content = models.ForeignKey(ContentItem, related_name="views", on_delete=models.CASCADE)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, related_name="views", on_delete=models.SET_NULL
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"View {self.content_id}"


class ContentDownload(models.Model):
    content = models.ForeignKey(ContentItem, related_name="downloads", on_delete=models.CASCADE)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, related_name="downloads", on_delete=models.SET_NULL
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Download {self.content_id}"
