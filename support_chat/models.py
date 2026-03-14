from django.db import models


class SupportConversation(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        CLOSED = "closed", "Closed"

    conversation_code = models.CharField(max_length=16, unique=True, db_index=True)
    session_key = models.CharField(max_length=80, blank=True, db_index=True)
    visitor_name = models.CharField(max_length=120, blank=True)
    visitor_phone = models.CharField(max_length=40, blank=True)
    page_url = models.CharField(max_length=500, blank=True)
    page_title = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.OPEN)
    auto_reply_sent_at = models.DateTimeField(null=True, blank=True)
    last_customer_message_at = models.DateTimeField(null=True, blank=True)
    last_operator_message_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-id"]

    def __str__(self):
        return self.conversation_code


class SupportMessage(models.Model):
    class SenderType(models.TextChoices):
        CUSTOMER = "customer", "Customer"
        OPERATOR = "operator", "Operator"
        SYSTEM = "system", "System"

    class Source(models.TextChoices):
        WEB = "web", "Web"
        WHATSAPP = "whatsapp", "WhatsApp"
        SYSTEM = "system", "System"
        API = "api", "API"

    conversation = models.ForeignKey(
        SupportConversation,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    sender_type = models.CharField(max_length=12, choices=SenderType.choices)
    source = models.CharField(max_length=12, choices=Source.choices)
    body = models.TextField()
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.conversation.conversation_code} #{self.pk or 'new'}"
