import os

from django import forms
from django.contrib.auth.forms import UserCreationForm

from .models import User


class UserRegistrationForm(UserCreationForm):
    email = forms.EmailField(required=False)

    class Meta:
        model = User
        fields = (
            "username",
            "email",
            "display_name",
            "role",
            "password1",
            "password2",
        )


class ProfileForm(forms.ModelForm):
    file_upload = forms.FileField(
        required=False,
        widget=forms.ClearableFileInput(
            attrs={"accept": "image/*", "class": "file-input"}
        ),
    )

    class Meta:
        model = User
        fields = ("display_name", "role", "bio", "website_url", "facebook_url", "github_url")
        widgets = {
            "bio": forms.Textarea(attrs={"rows": 4}),
        }

    def clean_file_upload(self):
        upload = self.cleaned_data.get("file_upload")
        if not upload:
            return upload
        content_type = getattr(upload, "content_type", "")
        ext = os.path.splitext(upload.name)[1].lower()
        allowed_ext = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
        if content_type and not content_type.startswith("image/"):
            raise forms.ValidationError("Please upload an image file.")
        if ext and ext not in allowed_ext:
            raise forms.ValidationError("Allowed formats: jpg, jpeg, png, webp, gif.")
        return upload
