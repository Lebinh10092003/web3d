import uuid
from django.conf import settings
from django.db import models, transaction
from django.template.defaultfilters import slugify
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class PostQuerySet(models.QuerySet):
    def live(self):
        now = timezone.now()
        return self.filter(
            models.Q(status=Post.Status.PUBLISHED, published_at__lte=now)
            | models.Q(status=Post.Status.SCHEDULED, published_at__lte=now)
        )

    def scheduled(self):
        now = timezone.now()
        return self.filter(status=Post.Status.SCHEDULED, published_at__gt=now)


class Post(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", _("Draft")
        PENDING_REVIEW = "PENDING_REVIEW", _("Pending review")
        SCHEDULED = "SCHEDULED", _("Scheduled")
        PUBLISHED = "PUBLISHED", _("Published")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=220, verbose_name=_("Title"))
    slug = models.SlugField(max_length=240, unique=True, blank=True, verbose_name=_("Slug"))
    summary = models.CharField(max_length=320, blank=True, verbose_name=_("Summary"))
    body = models.TextField(blank=True, verbose_name=_("Body (legacy / fallback)"))
    hero_image_url = models.URLField(blank=True, max_length=500, verbose_name=_("Hero image URL"))
    seo_title = models.CharField(max_length=240, blank=True, verbose_name=_("SEO title"))
    seo_description = models.CharField(max_length=320, blank=True, verbose_name=_("SEO description"))
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        verbose_name=_("Status"),
    )
    published_at = models.DateTimeField(default=timezone.now, verbose_name=_("Publish at"))
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="blog_posts",
        verbose_name=_("Author"),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = PostQuerySet.as_manager()

    class Meta:
        ordering = ["-published_at", "-created_at"]
        verbose_name = _("Blog post")
        verbose_name_plural = _("Blog posts")

    def __str__(self):
        return self.title

    def _ensure_slug(self):
        if self.slug:
            return
        base = slugify(self.title)[:220] or "post"
        slug = base
        counter = 2
        while Post.objects.exclude(pk=self.pk).filter(slug=slug).exists():
            suffix = f"-{counter}"
            slug = f"{base[: max(1, 220 - len(suffix))]}{suffix}"
            counter += 1
        self.slug = slug

    def save(self, *args, **kwargs):
        self._ensure_slug()
        if not self.seo_title:
            self.seo_title = self.title
        if not self.seo_description and self.summary:
            self.seo_description = self.summary[:320]
        super().save(*args, **kwargs)

    @property
    def is_live(self):
        now = timezone.now()
        return self.status in {self.Status.PUBLISHED, self.Status.SCHEDULED} and self.published_at <= now

    def snapshot(self):
        blocks = [
            block.to_dict()
            for block in self.blocks.order_by("position", "created_at").all()
        ]
        return {
            "post": {
                "title": self.title,
                "slug": self.slug,
                "summary": self.summary,
                "body": self.body,
                "hero_image_url": self.hero_image_url,
                "seo_title": self.seo_title,
                "seo_description": self.seo_description,
                "status": self.status,
                "published_at": self.published_at.isoformat() if self.published_at else None,
            },
            "blocks": blocks,
        }

    def apply_snapshot(self, payload):
        data = payload or {}
        post_data = data.get("post") or {}
        fields = [
            "title",
            "slug",
            "summary",
            "body",
            "hero_image_url",
            "seo_title",
            "seo_description",
            "status",
        ]
        for field in fields:
            if field in post_data:
                setattr(self, field, post_data[field])
        if post_data.get("published_at"):
            try:
                self.published_at = timezone.datetime.fromisoformat(post_data["published_at"])
            except Exception:
                pass
        with transaction.atomic():
            self.save()
            self.blocks.all().delete()
            blocks = data.get("blocks") or []
            objs = [PostBlock.from_dict(self, item, idx) for idx, item in enumerate(blocks, start=1)]
            PostBlock.objects.bulk_create([obj for obj in objs if obj])

    def publish_if_due(self):
        if self.status == self.Status.SCHEDULED and self.published_at <= timezone.now():
            self.status = self.Status.PUBLISHED
            self.save(update_fields=["status", "updated_at"])


class BlogComment(models.Model):
    post = models.ForeignKey(Post, related_name="comments", on_delete=models.CASCADE)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="blog_comments", on_delete=models.CASCADE
    )
    parent = models.ForeignKey(
        "self", null=True, blank=True, related_name="replies", on_delete=models.CASCADE
    )
    body = models.TextField()
    is_deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name = _("Blog comment")
        verbose_name_plural = _("Blog comments")

    def __str__(self):
        return f"Blog comment {self.id} on {self.post_id}"


class PostBlock(models.Model):
    class BlockType(models.TextChoices):
        TEXT = "TEXT", _("Text")
        IMAGE = "IMAGE", _("Image")
        VIDEO = "VIDEO", _("Video")
        GALLERY = "GALLERY", _("Gallery")
        QUOTE = "QUOTE", _("Quote")
        DIVIDER = "DIVIDER", _("Divider")

    post = models.ForeignKey(Post, related_name="blocks", on_delete=models.CASCADE)
    position = models.PositiveIntegerField(default=1, verbose_name=_("Order"))
    type = models.CharField(max_length=20, choices=BlockType.choices, verbose_name=_("Type"))
    text = models.TextField(blank=True)
    media_url = models.URLField(blank=True, max_length=600)
    caption = models.CharField(max_length=300, blank=True)
    alt_text = models.CharField(max_length=200, blank=True)
    align = models.CharField(max_length=20, blank=True, help_text=_("left|center|right|wide|full"))
    data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["position", "created_at"]
        verbose_name = _("Block")
        verbose_name_plural = _("Blocks")

    def __str__(self):
        return f"{self.get_type_display()} #{self.position} - {self.post.title}"

    def to_dict(self):
        return {
            "position": self.position,
            "type": self.type,
            "text": self.text,
            "media_url": self.media_url,
            "caption": self.caption,
            "alt_text": self.alt_text,
            "align": self.align,
            "data": self.data or {},
        }

    @classmethod
    def from_dict(cls, post, payload, position):
        payload = payload or {}
        return cls(
            post=post,
            position=payload.get("position") or position,
            type=payload.get("type") or cls.BlockType.TEXT,
            text=payload.get("text", ""),
            media_url=payload.get("media_url", ""),
            caption=payload.get("caption", ""),
            alt_text=payload.get("alt_text", ""),
            align=payload.get("align", ""),
            data=payload.get("data") or {},
        )


class PostRevision(models.Model):
    post = models.ForeignKey(Post, related_name="revisions", on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    is_autosave = models.BooleanField(default=False)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("Revision")
        verbose_name_plural = _("Revisions")

    def __str__(self):
        return f"{self.post.title} @ {self.created_at:%Y-%m-%d %H:%M}"
