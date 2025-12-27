from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from library.models import ContentItem


class Comment(models.Model):
    content = models.ForeignKey(ContentItem, related_name="comments", on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="comments", on_delete=models.CASCADE)
    parent = models.ForeignKey(
        "self", null=True, blank=True, related_name="replies", on_delete=models.CASCADE
    )
    body = models.TextField()
    is_deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"Comment {self.id} on {self.content_id}"


class Rating(models.Model):
    content = models.ForeignKey(ContentItem, related_name="ratings", on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="ratings", on_delete=models.CASCADE)
    score = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("content", "user")

    def __str__(self):
        return f"{self.score} for {self.content_id}"


class Favorite(models.Model):
    content = models.ForeignKey(ContentItem, related_name="favorites", on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="favorites", on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("content", "user")

    def __str__(self):
        return f"Favorite {self.content_id}"
