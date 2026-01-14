import os

from django import forms
from django.contrib.auth.models import Group
from django.contrib.auth.forms import UserCreationForm
from django.db import OperationalError, ProgrammingError
from django.db.models import Case, IntegerField, Value, When
from django.utils.translation import gettext_lazy as _

from .groups import (
    ROLE_BY_GROUP_NAME,
    ROLE_GROUP_NAME_BY_ROLE,
    ROLE_GROUP_NAMES,
    ensure_default_groups,
)
from .models import User


class UserRegistrationForm(UserCreationForm):
    email = forms.EmailField(required=False)

    group = forms.ModelChoiceField(
        queryset=Group.objects.none(),
        empty_label=_("Select a group"),
        required=True,
    )

    class Meta:
        model = User
        fields = (
            "username",
            "email",
            "display_name",
            "password1",
            "password2",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        try:
            ensure_default_groups()
            qs = Group.objects.filter(name__in=ROLE_GROUP_NAMES)
            order = Case(
                When(name=ROLE_GROUP_NAME_BY_ROLE[User.Role.STUDENT], then=Value(0)),
                When(name=ROLE_GROUP_NAME_BY_ROLE[User.Role.TEACHER], then=Value(1)),
                When(name=ROLE_GROUP_NAME_BY_ROLE[User.Role.PARENT], then=Value(2)),
                default=Value(99),
                output_field=IntegerField(),
            )
            self.fields["group"].queryset = qs.annotate(_order=order).order_by(
                "_order", "name", "id"
            )
        except (OperationalError, ProgrammingError):
            self.fields["group"].queryset = Group.objects.none()

    def clean_group(self):
        group = self.cleaned_data.get("group")
        if not group:
            raise forms.ValidationError(_("Please select a group."))
        if (group.name or "").strip() not in ROLE_GROUP_NAMES:
            raise forms.ValidationError(_("Invalid group selection."))
        return group

    def save(self, commit=True):
        user = super().save(commit=False)
        group = self.cleaned_data.get("group")
        if group:
            user.role = ROLE_BY_GROUP_NAME.get((group.name or "").strip(), "")
        if commit:
            user.save()
            self.save_m2m()
        return user


class ProfileForm(forms.ModelForm):
    file_upload = forms.FileField(
        required=False,
        help_text=_("Recommended size: 400x400px (square)."),
        widget=forms.ClearableFileInput(
            attrs={"accept": "image/*", "class": "file-input"}
        ),
    )

    class Meta:
        model = User
        fields = ("display_name", "bio", "website_url", "facebook_url", "github_url")
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
