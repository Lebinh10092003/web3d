import mimetypes

from django.conf import settings
from django.core.files.storage import default_storage
from django.db import models
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from library.models import Category, ContentFile, ContentItem


class ContributionSubmission(models.Model):
    class Competition(models.TextChoices):
        WRO = "WRO", "WRO"
        FLL = "FLL", "FLL"
        ENJOY_AI = "ENJOY_AI", "Enjoy AI"
        VEX_IQ = "VEX_IQ", "VEX IQ"
        VEX_V5 = "VEX_V5", "VEX V5"
        OTHER = "OTHER", _("Other competition")

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="submissions", on_delete=models.CASCADE
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    content_type = models.CharField(max_length=20)
    category = models.ForeignKey(
        Category,
        null=True,
        blank=True,
        related_name="submissions",
        on_delete=models.SET_NULL,
    )
    competition = models.CharField(
        max_length=20,
        choices=Competition.choices,
        blank=True,
    )
    file_path = models.CharField(max_length=500)
    preview_path = models.CharField(max_length=500, blank=True)
    points_awarded = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        related_name="reviewed_submissions",
        on_delete=models.SET_NULL,
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Submission {self.id} ({self.status})"

    def _resolve_content_type(self):
        ext = (self.content_type or "").lower()
        if ext == "pdf":
            return ContentItem.ContentType.PDF
        return ContentItem.ContentType.LEGO_3D

    def _get_or_create_competition_category(self):
        if not self.competition:
            return None
        name = self.get_competition_display() or self.competition
        category = Category.objects.filter(name__iexact=name).first()
        if category:
            if not category.is_active:
                category.is_active = True
                category.save(update_fields=["is_active"])
            return category

        base_slug = slugify(name)[:140] or "competition"
        slug = base_slug
        counter = 2
        while Category.objects.filter(slug=slug).exists():
            suffix = f"-{counter}"
            slug = f"{base_slug[:140 - len(suffix)]}{suffix}"
            counter += 1
        return Category.objects.create(name=name, slug=slug)

    def _attach_preview(self, content):
        if not self.preview_path:
            return
        if ContentFile.objects.filter(storage_path=self.preview_path).exists():
            return
        if not default_storage.exists(self.preview_path):
            return

        mime_type, _ = mimetypes.guess_type(self.preview_path)
        if not mime_type:
            mime_type = "application/octet-stream"
        try:
            size_bytes = default_storage.size(self.preview_path)
        except Exception:
            size_bytes = 0

        ContentFile.objects.create(
            content=content,
            kind=ContentFile.FileKind.PREVIEW,
            storage_path=self.preview_path,
            mime_type=mime_type,
            size_bytes=size_bytes,
            checksum="",
        )

    def _publish_if_approved(self):
        if self.status != self.Status.APPROVED:
            return
        if not self.file_path:
            return
        existing_source = (
            ContentFile.objects.filter(
                storage_path=self.file_path,
                kind=ContentFile.FileKind.SOURCE,
            )
            .select_related("content")
            .first()
        )
        if existing_source:
            content = existing_source.content
            if self.category:
                content.categories.add(self.category)
            competition_category = self._get_or_create_competition_category()
            if competition_category:
                content.categories.add(competition_category)
            self._attach_preview(content)
            return
        if not default_storage.exists(self.file_path):
            return

        content = ContentItem.objects.create(
            owner=self.user,
            title=self.title,
            description=self.description,
            content_type=self._resolve_content_type(),
            status=ContentItem.Status.PUBLISHED,
            is_public=True,
        )
        if self.category:
            content.categories.add(self.category)
        competition_category = self._get_or_create_competition_category()
        if competition_category:
            content.categories.add(competition_category)

        mime_type, _ = mimetypes.guess_type(self.file_path)
        if not mime_type:
            mime_type = "application/octet-stream"
        try:
            size_bytes = default_storage.size(self.file_path)
        except Exception:
            size_bytes = 0

        ContentFile.objects.create(
            content=content,
            kind=ContentFile.FileKind.SOURCE,
            storage_path=self.file_path,
            mime_type=mime_type,
            size_bytes=size_bytes,
            checksum="",
        )
        self._attach_preview(content)

    def save(self, *args, **kwargs):
        old_status = None
        old_awarded = False
        if self.pk:
            previous = type(self).objects.filter(pk=self.pk).values(
                "status", "points_awarded"
            ).first()
            if previous:
                old_status = previous["status"]
                old_awarded = previous["points_awarded"]

        should_award = (
            self.status == self.Status.APPROVED
            and old_status != self.Status.APPROVED
            and not self.points_awarded
            and not old_awarded
        )

        super().save(*args, **kwargs)

        if should_award:
            from gating.models import PointLedger

            points = int(getattr(settings, "CONTRIBUTION_APPROVAL_POINTS", 10))
            if points:
                PointLedger.record(self.user, points, f"Contribution approved #{self.id}")
            type(self).objects.filter(pk=self.pk).update(points_awarded=True)
            self.points_awarded = True

        self._publish_if_approved()
