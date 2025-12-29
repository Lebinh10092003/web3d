from django.conf import settings
from django.db import models
from django.db.models import F

from library.models import ContentItem


class PointLedger(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="point_entries", on_delete=models.CASCADE
    )
    delta = models.IntegerField()
    reason = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user_id}:{self.delta}"

    @classmethod
    def record(cls, user, delta, reason):
        entry = cls.objects.create(user=user, delta=delta, reason=reason)
        type(user).objects.filter(id=user.id).update(points_balance=F("points_balance") + delta)
        user.refresh_from_db(fields=["points_balance"])
        return entry


class Unlock(models.Model):
    class Method(models.TextChoices):
        POINTS = "POINTS", "Points"
        AD = "AD", "Ad"
        SOCIAL = "SOCIAL", "Social"
        CONTRIBUTION = "CONTRIBUTION", "Contribution"
        PAYMENT = "PAYMENT", "Payment"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="unlocks", on_delete=models.CASCADE
    )
    content = models.ForeignKey(ContentItem, related_name="unlocks", on_delete=models.CASCADE)
    method = models.CharField(max_length=20, choices=Method.choices)
    cost_points = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "content")

    def __str__(self):
        return f"{self.user_id}:{self.content_id}"


class PaymentTransaction(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        PAID = "PAID", "Paid"
        FAILED = "FAILED", "Failed"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="payment_transactions", on_delete=models.CASCADE
    )
    content = models.ForeignKey(
        ContentItem, related_name="payment_transactions", on_delete=models.CASCADE
    )
    amount = models.PositiveIntegerField()
    currency = models.CharField(max_length=6, default="VND")
    provider = models.CharField(max_length=30, default="ZALOPAY")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    app_trans_id = models.CharField(max_length=64, unique=True)
    zp_trans_id = models.CharField(max_length=64, blank=True)
    app_time = models.BigIntegerField(default=0)
    raw_callback = models.JSONField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.app_trans_id}:{self.status}"
