import re
from urllib.parse import parse_qs, urlparse, urlunparse

from django.conf import settings

from django.db import models
from django.db.models.signals import post_delete, pre_save
from django.dispatch import receiver
from django.urls import reverse
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _


def _extract_iframe_src(value):
    if "<iframe" not in value:
        return ""
    match = re.search(r'src=["\']([^"\']+)', value)
    return match.group(1).strip() if match else ""


def _normalize_youtube_id(value):
    value = (value or "").strip()
    if not value:
        return ""
    iframe_src = _extract_iframe_src(value)
    if iframe_src:
        value = iframe_src
    if "youtu" not in value:
        return value
    try:
        parsed = urlparse(value)
    except Exception:
        return value
    host = parsed.hostname or ""
    if host in ("youtu.be", "www.youtu.be"):
        path = parsed.path.lstrip("/")
        return path.split("/")[0] if path else value
    if host in (
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "youtube-nocookie.com",
        "www.youtube-nocookie.com",
    ):
        if parsed.path.startswith("/watch"):
            query = parse_qs(parsed.query)
            return query.get("v", [value])[0] or value
        if parsed.path.startswith("/embed/") or parsed.path.startswith("/shorts/"):
            parts = parsed.path.split("/")
            if len(parts) > 2:
                return parts[2]
    return value


def _normalize_playlist_id(value):
    value = (value or "").strip()
    if not value:
        return ""
    iframe_src = _extract_iframe_src(value)
    if iframe_src:
        value = iframe_src
    if "list=" not in value and "youtube" not in value and "youtu.be" not in value:
        return value
    try:
        parsed = urlparse(value)
    except Exception:
        return value
    query = parse_qs(parsed.query or "")
    playlist_id = query.get("list", [""])[0]
    return playlist_id or value


class Category(models.Model):
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True)
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        related_name="children",
        on_delete=models.SET_NULL,
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "Categories"
        ordering = ["name"]

    def __str__(self):
        return self.name


class ContentItem(models.Model):
    class ContentType(models.TextChoices):
        PDF = "PDF", _("PDF")
        LEGO_3D = "LEGO_3D", _("LEGO 3D")

    class Status(models.TextChoices):
        DRAFT = "DRAFT", _("Draft")
        PENDING = "PENDING", _("Pending")
        PUBLISHED = "PUBLISHED", _("Published")
        REJECTED = "REJECTED", _("Rejected")

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="contents",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    description = models.TextField(blank=True)
    external_links = models.URLField(blank=True, max_length=500)
    content_type = models.CharField(max_length=20, choices=ContentType.choices)
    categories = models.ManyToManyField(Category, blank=True, related_name="items")
    download_cost_points = models.PositiveIntegerField(default=0)
    price_vnd = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PUBLISHED)
    is_public = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["is_public", "status", "created_at"],
                name="content_pub_status_created_idx",
            ),
            models.Index(fields=["title"], name="content_title_idx"),
        ]

    def __str__(self):
        return self.title

    def _build_unique_slug(self):
        base = slugify(self.title)[:200] or "content"
        slug = base
        counter = 2
        qs = type(self).objects.exclude(pk=self.pk)
        while qs.filter(slug=slug).exists():
            suffix = f"-{counter}"
            trimmed = base[: max(1, 200 - len(suffix))]
            slug = f"{trimmed}{suffix}"
            counter += 1
        return slug

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = self._build_unique_slug()
        super().save(*args, **kwargs)

    def _clean_external_link(self):
        link = (self.external_links or "").strip()
        if not link:
            return ""
        if (link.startswith('"') and link.endswith('"')) or (
            link.startswith("'") and link.endswith("'")
        ):
            link = link[1:-1].strip()
        return link

    @property
    def external_link_url(self):
        link = self._clean_external_link()
        if not link:
            return ""
        parsed = urlparse(link)
        if not parsed.scheme:
            return f"https://{link}"
        return link

    @property
    def external_link_label(self):
        link = self.external_link_url
        if not link:
            return ""
        parsed = urlparse(link)
        host = (parsed.netloc or "").strip()
        if host.startswith("www."):
            host = host[4:]
        return host or link


class ContentFile(models.Model):
    class FileKind(models.TextChoices):
        SOURCE = "SOURCE", "Source"
        PREVIEW = "PREVIEW", "Preview"

    content = models.ForeignKey(ContentItem, related_name="files", on_delete=models.CASCADE)
    kind = models.CharField(max_length=20, choices=FileKind.choices)
    storage_path = models.CharField(max_length=500)
    mime_type = models.CharField(max_length=100)
    size_bytes = models.BigIntegerField(default=0)
    checksum = models.CharField(max_length=128, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("content", "kind", "storage_path")

    def __str__(self):
        return f"{self.content_id}:{self.kind}"

    def get_signed_url(self, expires_in=None, method="GET", user_id=None, download=False):
        from .storage import build_signed_url

        return build_signed_url(
            self.storage_path,
            expires_in=expires_in,
            method=method,
            user_id=user_id,
            download=download,
        )


class RecapVideo(models.Model):
    class VideoProvider(models.TextChoices):
        YOUTUBE = "YOUTUBE", "YouTube"
        TIKTOK = "TIKTOK", "TikTok"

    competition = models.CharField(max_length=120, verbose_name=_("Competition"))
    competition_slug = models.SlugField(max_length=140, blank=True, verbose_name=_("Competition slug"))
    year = models.PositiveSmallIntegerField(verbose_name=_("Year"))
    video_provider = models.CharField(
        max_length=20,
        choices=VideoProvider.choices,
        default=VideoProvider.YOUTUBE,
        verbose_name=_("Video provider"),
    )
    video_id = models.CharField(
        max_length=200,
        blank=True,
        help_text=_("Paste a YouTube/TikTok URL, ID, or full iframe embed code."),
        verbose_name=_("Video ID"),
    )
    title = models.CharField(max_length=200, verbose_name=_("Title"))
    summary = models.TextField(blank=True, verbose_name=_("Summary"))
    is_published = models.BooleanField(default=True, verbose_name=_("Published"))
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Created at"))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("Updated at"))

    class Meta:
        ordering = ["competition_slug", "-year", "title"]
        unique_together = ("competition_slug", "year")
        verbose_name = _("Recap video")
        verbose_name_plural = _("Recap videos")

    def __str__(self):
        return f"{self.competition} {self.year}"

    def save(self, *args, **kwargs):
        if self.competition:
            slug = slugify(self.competition)[:140]
            self.competition_slug = slug or "competition"
        if self.video_id:
            provider, video_id = self._normalize_video_reference(self.video_id)
            if provider:
                self.video_provider = provider
            self.video_id = video_id
        super().save(*args, **kwargs)

    def get_embed_url(self):
        video_id = (self.video_id or "").strip()
        if not video_id:
            return ""
        if self.video_provider == self.VideoProvider.TIKTOK:
            if video_id.startswith("http") and "tiktok.com/embed" in video_id:
                return video_id
            if not video_id.isdigit():
                return ""
            return f"https://www.tiktok.com/embed/v2/{video_id}"
        if video_id.startswith("http") and "youtu" in video_id and "/embed/" in video_id:
            return self._normalize_youtube_embed_url(video_id)
        if not re.match(r"^[A-Za-z0-9_-]{11}$", video_id):
            return ""
        return f"https://www.youtube-nocookie.com/embed/{video_id}?rel=0"

    def get_watch_url(self):
        video_id = (self.video_id or "").strip()
        if not video_id:
            return ""
        if video_id.startswith("http"):
            if "tiktok" in video_id:
                tiktok_id = self._extract_tiktok_id(video_id)
                if tiktok_id:
                    return f"https://www.tiktok.com/video/{tiktok_id}"
                return video_id
            if "youtu" in video_id:
                youtube_id = self._normalize_youtube_id(video_id)
                if youtube_id:
                    return f"https://www.youtube.com/watch?v={youtube_id}"
            return video_id
        if self.video_provider == self.VideoProvider.TIKTOK:
            return f"https://www.tiktok.com/video/{video_id}" if video_id.isdigit() else ""
        return (
            f"https://www.youtube.com/watch?v={video_id}"
            if re.match(r"^[A-Za-z0-9_-]{11}$", video_id)
            else ""
        )

    def _normalize_video_reference(self, value):
        value = (value or "").strip()
        if not value:
            return "", ""
        iframe_src = self._extract_iframe_src(value)
        if iframe_src:
            value = iframe_src
            if self._is_youtube_embed_url(value):
                return self.VideoProvider.YOUTUBE, self._normalize_youtube_embed_url(value)
            if "tiktok.com/embed" in value:
                return self.VideoProvider.TIKTOK, value
        tiktok_id = self._extract_tiktok_id(value)
        if tiktok_id:
            return self.VideoProvider.TIKTOK, tiktok_id
        if "tiktok" in value:
            return self.VideoProvider.TIKTOK, value
        youtube_id = self._normalize_youtube_id(value)
        if youtube_id:
            return self.VideoProvider.YOUTUBE, youtube_id
        if value.isdigit():
            return self.VideoProvider.TIKTOK, value
        provider = self.video_provider or self.VideoProvider.YOUTUBE
        return provider, value

    @staticmethod
    def _extract_iframe_src(value):
        if "<iframe" not in value:
            return ""
        match = re.search(r'src=["\']([^"\']+)', value)
        return match.group(1).strip() if match else ""

    @staticmethod
    def _is_youtube_embed_url(value):
        return "youtu" in value and "/embed/" in value

    @staticmethod
    def _normalize_youtube_embed_url(value):
        if not value:
            return ""
        try:
            parsed = urlparse(value)
        except Exception:
            return value
        host = (parsed.hostname or "").lower()
        if "youtu" not in host or "/embed/" not in (parsed.path or ""):
            return value
        scheme = parsed.scheme or "https"
        return urlunparse(
            (
                scheme,
                "www.youtube-nocookie.com",
                parsed.path,
                "",
                parsed.query or "",
                "",
            )
        )

    @staticmethod
    def _extract_tiktok_id(value):
        value = (value or "").strip()
        if not value:
            return ""
        if value.isdigit() and len(value) >= 15:
            return value
        if "tiktok" not in value:
            return ""
        try:
            parsed = urlparse(value)
        except Exception:
            return ""
        path = parsed.path or ""
        match = re.search(r"/video/(\\d+)", path)
        if match:
            return match.group(1)
        match = re.search(r"/embed(?:/v2)?/(\\d+)", path)
        if match:
            return match.group(1)
        return ""

    @staticmethod
    def _normalize_youtube_id(value):
        value = (value or "").strip()
        if not value:
            return value
        if "youtu" not in value:
            if len(value) == 11 and re.match(r"^[A-Za-z0-9_-]{11}$", value):
                return value
            return ""
        try:
            parsed = urlparse(value)
        except Exception:
            return value
        host = parsed.hostname or ""
        if host in ("youtu.be", "www.youtu.be"):
            path = parsed.path.lstrip("/")
            return path.split("/")[0] if path else value
        if host in (
            "youtube.com",
            "www.youtube.com",
            "m.youtube.com",
            "youtube-nocookie.com",
            "www.youtube-nocookie.com",
        ):
            if parsed.path.startswith("/watch"):
                query = parse_qs(parsed.query)
                return query.get("v", [value])[0] or value
            if parsed.path.startswith("/embed/") or parsed.path.startswith("/shorts/"):
                parts = parsed.path.split("/")
                if len(parts) > 2:
                    return parts[2]
        return ""


class Course(models.Model):
    title = models.CharField(max_length=200)
    slug = models.SlugField(
        max_length=220,
        unique=True,
        blank=True,
        help_text="Leave blank to auto-generate from the title.",
    )
    description = models.TextField(blank=True)
    playlist_id = models.CharField(
        max_length=200,
        blank=True,
        help_text="Paste a YouTube playlist ID or URL; it will be normalized.",
    )
    featured_video_id = models.CharField(
        max_length=200,
        blank=True,
        help_text="Paste a YouTube video ID, URL, or iframe; it will be normalized.",
    )
    is_published = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "title"]

    def __str__(self):
        return self.title

    def _build_unique_slug(self):
        base = slugify(self.title)[:200] or "course"
        slug = base
        counter = 2
        qs = type(self).objects.exclude(pk=self.pk)
        while qs.filter(slug=slug).exists():
            suffix = f"-{counter}"
            trimmed = base[: max(1, 200 - len(suffix))]
            slug = f"{trimmed}{suffix}"
            counter += 1
        return slug

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = self._build_unique_slug()
        if self.playlist_id:
            self.playlist_id = _normalize_playlist_id(self.playlist_id)
        if self.featured_video_id:
            self.featured_video_id = _normalize_youtube_id(self.featured_video_id)
        super().save(*args, **kwargs)

    @property
    def playlist_embed_url(self):
        playlist_id = (self.playlist_id or "").strip()
        return (
            f"https://www.youtube-nocookie.com/embed/videoseries?list={playlist_id}"
            if playlist_id
            else ""
        )

    @property
    def playlist_url(self):
        playlist_id = (self.playlist_id or "").strip()
        return (
            f"https://www.youtube.com/playlist?list={playlist_id}"
            if playlist_id
            else ""
        )

    def get_video_embed_url(self, video_id):
        video_id = (video_id or "").strip()
        playlist_id = (self.playlist_id or "").strip()
        if not video_id:
            return self.playlist_embed_url
        base = "https://www.youtube-nocookie.com/embed"
        if playlist_id:
            return f"{base}/{video_id}?list={playlist_id}"
        return f"{base}/{video_id}"

    @property
    def featured_embed_url(self):
        return self.get_video_embed_url(self.featured_video_id)

    def get_absolute_url(self):
        return reverse("course-detail", kwargs={"slug": self.slug})


class CourseLesson(models.Model):
    course = models.ForeignKey(Course, related_name="lessons", on_delete=models.CASCADE)
    title = models.CharField(max_length=200)
    video_id = models.CharField(
        max_length=200,
        blank=True,
        help_text="Paste a YouTube video ID, URL, or iframe; it will be normalized.",
    )
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sort_order", "id"]

    def __str__(self):
        return f"{self.course_id}: {self.title}"

    def save(self, *args, **kwargs):
        if self.video_id:
            self.video_id = _normalize_youtube_id(self.video_id)
        super().save(*args, **kwargs)


class CourseFavorite(models.Model):
    course = models.ForeignKey(Course, related_name="favorites", on_delete=models.CASCADE)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="course_favorites",
        on_delete=models.CASCADE,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("course", "user")

    def __str__(self):
        return f"Course favorite {self.course_id}"


class CourseLessonProgress(models.Model):
    lesson = models.ForeignKey(
        CourseLesson, related_name="progresses", on_delete=models.CASCADE
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="course_lesson_progress",
        on_delete=models.CASCADE,
    )
    is_completed = models.BooleanField(default=False)
    last_watched_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("lesson", "user")

    def __str__(self):
        return f"Course progress {self.lesson_id}"


class RecapHeroBanner(models.Model):
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    eyebrow = models.CharField(max_length=80, blank=True)
    background_image = models.FileField(
        upload_to="banners/recaps/",
        blank=True,
        help_text=_("Recommended size: 1600x900px (16:9)."),
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        verbose_name = "Recap hero banner"
        verbose_name_plural = "Recap hero banners"

    def __str__(self):
        title = (self.title or "").strip()
        return title or "Recap hero banner"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.is_active:
            RecapHeroBanner.objects.exclude(pk=self.pk).update(is_active=False)


class LibrarySideBanner(models.Model):
    class Position(models.TextChoices):
        LEFT = "LEFT", _("Left")
        RIGHT = "RIGHT", _("Right")
        DOWNLOAD = "DOWNLOAD", _("Download")

    title = models.CharField(max_length=120, blank=True)
    image = models.FileField(
        upload_to="banners/library/",
        help_text=_("Recommended size: 600x900px for side banners, 1200x800px for download banner."),
    )
    link_url = models.URLField(blank=True)
    position = models.CharField(max_length=10, choices=Position.choices, default=Position.LEFT)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["position", "sort_order", "-updated_at"]

    def __str__(self):
        label = self.title or "Library banner"
        return f"{label} ({self.position})"


def _delete_file_field_file(instance, field_name, using=None):
    field = getattr(instance, field_name, None)
    if not field or not getattr(field, "name", ""):
        return
    file_name = field.name
    model = type(instance)
    qs = model.objects.using(using) if using else model.objects
    if qs.filter(**{field_name: file_name}).exclude(pk=instance.pk).exists():
        return
    storage = field.storage
    try:
        if storage.exists(file_name):
            storage.delete(file_name)
    except Exception:
        return


def _delete_replaced_file(sender, instance, field_name, using=None):
    if not instance.pk:
        return
    try:
        qs = sender.objects.using(using) if using else sender.objects
        old = qs.get(pk=instance.pk)
    except sender.DoesNotExist:
        return
    old_field = getattr(old, field_name, None)
    new_field = getattr(instance, field_name, None)
    old_name = getattr(old_field, "name", "")
    new_name = getattr(new_field, "name", "")
    if not old_name or old_name == new_name:
        return
    _delete_file_field_file(old, field_name, using=using)


@receiver(post_delete, sender=RecapHeroBanner)
def _delete_recap_hero_banner_file(sender, instance, using, **kwargs):
    _delete_file_field_file(instance, "background_image", using=using)


@receiver(pre_save, sender=RecapHeroBanner)
def _delete_recap_hero_banner_replaced_file(sender, instance, using, **kwargs):
    _delete_replaced_file(sender, instance, "background_image", using=using)


@receiver(post_delete, sender=LibrarySideBanner)
def _delete_library_side_banner_file(sender, instance, using, **kwargs):
    _delete_file_field_file(instance, "image", using=using)


@receiver(pre_save, sender=LibrarySideBanner)
def _delete_library_side_banner_replaced_file(sender, instance, using, **kwargs):
    _delete_replaced_file(sender, instance, "image", using=using)
