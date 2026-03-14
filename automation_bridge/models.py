from django.db import models


class BlogAutomationRun(models.Model):
    class Status(models.TextChoices):
        RECEIVED = "RECEIVED", "Received"
        CREATED = "CREATED", "Created"
        FAILED = "FAILED", "Failed"

    request_id = models.CharField(max_length=80, unique=True)
    source_channel = models.CharField(max_length=40, blank=True)
    requested_by = models.CharField(max_length=120, blank=True)
    command_text = models.TextField(blank=True)
    payload = models.JSONField(default=dict, blank=True)
    sources = models.JSONField(default=list, blank=True)
    media_results = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.RECEIVED)
    created_post = models.ForeignKey(
        "blog.Post",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="automation_runs",
    )
    error_detail = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return self.request_id
