import mimetypes
import os
import shutil

from django.conf import settings
from django.core.files.storage import default_storage
from django.db import models
from django.db.models.signals import pre_delete
from django.db import transaction
from django.dispatch import receiver
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from library.models import Category, ContentFile, ContentItem
from library.tasks import enqueue_ldraw_prebuild


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
    download_cost_points = models.PositiveIntegerField(
        default=10,
        help_text=_("Points required to unlock and download this content."),
    )
    award_points = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text=_("Override points awarded to the uploader on approval."),
    )
    price_vnd = models.PositiveIntegerField(
        default=0,
        help_text=_("Price in VND for paid content. Set 0 for free/points."),
    )
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
        effective_points = self.download_cost_points

        if existing_source:
            content = existing_source.content
            update_fields = []
            if content.download_cost_points != effective_points:
                content.download_cost_points = effective_points
                update_fields.append("download_cost_points")
            if getattr(content, "price_vnd", 0):
                content.price_vnd = 0
                update_fields.append("price_vnd")
            if update_fields:
                content.save(update_fields=update_fields)
            if self.category:
                content.categories.add(self.category)
            competition_category = self._get_or_create_competition_category()
            if competition_category:
                content.categories.add(competition_category)
            self._attach_preview(content)
            self._prebuild_ldraw(content, self.file_path)
            return
        if not default_storage.exists(self.file_path):
            return

        content = ContentItem.objects.create(
            owner=self.user,
            title=self.title,
            description=self.description,
            content_type=self._resolve_content_type(),
            download_cost_points=effective_points,
            price_vnd=0,
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
        self._prebuild_ldraw(content, self.file_path)

    def _prebuild_ldraw(self, content, file_path):
        if not getattr(settings, "PREBUILD_LDRAW_ON_APPROVAL", True):
            return
        if not content or not file_path:
            return
        ext = os.path.splitext(file_path)[1].lstrip(".").lower()
        if ext not in {"lxf", "io", "ldr", "mpd"}:
            return

        def enqueue():
            enqueue_ldraw_prebuild(content.id, file_path)

        try:
            transaction.on_commit(enqueue)
        except Exception:
            enqueue()

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

            if self.award_points is None:
                points = int(getattr(settings, "CONTRIBUTION_APPROVAL_POINTS", 10))
            else:
                points = int(self.award_points or 0)
            if points:
                PointLedger.record(self.user, points, f"Contribution approved #{self.id}")
            type(self).objects.filter(pk=self.pk).update(points_awarded=True)
            self.points_awarded = True

        self._publish_if_approved()


def _collect_contents_for_source(path, skip):
    if not path or skip:
        return []
    contents = {}
    for source in (
        ContentFile.objects.filter(
            storage_path=path,
            kind=ContentFile.FileKind.SOURCE,
        )
        .select_related("content")
        .only("content_id", "content")
    ):
        contents[source.content_id] = source.content
    return list(contents.values())


def _delete_storage_path(path, skip):
    if not path or skip:
        return
    if ContentFile.objects.filter(storage_path=path).exists():
        return
    try:
        if default_storage.exists(path):
            default_storage.delete(path)
    except Exception:
        return


def _delete_storage_entry(path):
    if not path:
        return
    try:
        if default_storage.exists(path):
            default_storage.delete(path)
    except Exception:
        return


def _delete_storage_tree(prefix):
    if not prefix:
        return
    local_path = ""
    try:
        local_path = default_storage.path(prefix)
    except Exception:
        local_path = ""
    if local_path and os.path.isdir(local_path):
        shutil.rmtree(local_path, ignore_errors=True)
        return
    try:
        dirs, files = default_storage.listdir(prefix)
    except Exception:
        _delete_storage_entry(prefix)
        return
    for filename in files:
        _delete_storage_entry(f"{prefix}/{filename}")
    for dirname in dirs:
        _delete_storage_tree(f"{prefix}/{dirname}")
    _delete_storage_entry(prefix)


@receiver(pre_delete, sender=ContributionSubmission)
def _cleanup_submission_files(sender, instance, using, **kwargs):
    file_path = instance.file_path or ""
    preview_path = instance.preview_path or ""

    other_source = False
    if file_path:
        other_source = (
            sender.objects.using(using).exclude(pk=instance.pk).filter(file_path=file_path).exists()
        )
    other_preview = False
    if preview_path:
        other_preview = (
            sender.objects.using(using)
            .exclude(pk=instance.pk)
            .filter(preview_path=preview_path)
            .exists()
        )

    contents = _collect_contents_for_source(file_path, other_source)
    for content in contents:
        content.delete()
        _delete_storage_tree(f"derived/lego/{content.id}")

    _delete_storage_path(file_path, other_source)
    _delete_storage_path(preview_path, other_preview)
