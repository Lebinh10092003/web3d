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


class BulkPostImportForm(forms.Form):
    data = forms.CharField(
        label=_("JSON data"),
        widget=forms.Textarea(
            attrs={
                "rows": 24,
                "class": "vLargeTextField",
                "spellcheck": "false",
                "placeholder": '{"posts":[{"title":"...","status":"DRAFT","blocks":[...]}]}',
            }
        ),
        help_text=_("Paste JSON with top-level key 'posts' (or a plain list of posts)."),
    )
    replace_existing = forms.BooleanField(
        required=False,
        initial=False,
        label=_("Replace existing post when slug matches"),
        help_text=_("If checked, matching slug will be updated and old blocks will be replaced."),
    )
