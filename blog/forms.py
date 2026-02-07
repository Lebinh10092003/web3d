from django import forms
from django.utils import timezone

from .models import Post


class PostQuickForm(forms.ModelForm):
    class Meta:
        model = Post
        fields = ["title", "summary", "hero_image_url", "status", "published_at"]
        widgets = {
            "published_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }

    def clean_published_at(self):
        value = self.cleaned_data.get("published_at")
        if not value:
            return timezone.now()
        return value
