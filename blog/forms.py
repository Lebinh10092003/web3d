from django import forms
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

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


class BlogCommentForm(forms.Form):
    body = forms.CharField(
        widget=forms.Textarea(
            attrs={
                "rows": 3,
                "placeholder": _("Share a constructive note"),
                "class": "form-control",
            }
        )
    )
    parent_id = forms.IntegerField(required=False, widget=forms.HiddenInput)
