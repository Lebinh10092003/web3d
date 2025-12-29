import os
import zipfile

from django import forms
from django.conf import settings
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from library.models import Category

from .models import ContributionSubmission


class ContributionSubmissionForm(forms.ModelForm):
    PDF_KEYWORDS = (
        "wro",
        "fll",
        "enjoy ai",
        "vex iq",
        "vex v5",
        "vex",
        "lego",
    )
    competition = forms.ChoiceField(
        choices=ContributionSubmission.Competition.choices,
        required=False,
        widget=forms.Select(attrs={"class": "select-input"}),
    )
    file_upload = forms.FileField(
        required=True,
        widget=forms.ClearableFileInput(
            attrs={"accept": ".pdf,.io,.lxf,.ldr,.mpd", "class": "file-input"}
        ),
    )
    preview_upload = forms.FileField(
        required=False,
        widget=forms.ClearableFileInput(
            attrs={"accept": "image/*", "class": "file-input"}
        ),
    )
    category = forms.ModelChoiceField(
        queryset=Category.objects.none(),
        required=False,
        empty_label=_("Select a category"),
    )
    new_category = forms.CharField(
        required=False,
        max_length=120,
        widget=forms.TextInput(attrs={"placeholder": _("New category")}),
    )

    class Meta:
        model = ContributionSubmission
        fields = (
            "title",
            "description",
            "competition",
        )
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["competition"].choices = [("", _("Select a competition"))] + list(
            ContributionSubmission.Competition.choices
        )
        self.fields["category"].queryset = Category.objects.filter(
            is_active=True
        ).order_by("name")

    def clean(self):
        cleaned_data = super().clean()
        category = cleaned_data.get("category")
        new_category = (cleaned_data.get("new_category") or "").strip()
        cleaned_data["new_category"] = new_category
        if not category and not new_category:
            raise forms.ValidationError(_("Select a category or add a new one."))
        return cleaned_data

    def clean_file_upload(self):
        upload = self.cleaned_data.get("file_upload")
        if not upload:
            return upload
        max_mb = int(getattr(settings, "MAX_CONTRIBUTION_UPLOAD_MB", 50))
        self._validate_upload_size(upload, max_mb, _("File"))
        ext = os.path.splitext(upload.name)[1].lower().lstrip(".")
        if not ext:
            raise forms.ValidationError(_("File extension is required."))
        allowed_ext = {"pdf", "io", "lxf", "ldr", "mpd"}
        if ext not in allowed_ext:
            raise forms.ValidationError(
                _("Allowed formats: pdf, io, lxf, ldr, mpd.")
            )
        if ext == "pdf":
            if not self._looks_like_pdf(upload):
                raise forms.ValidationError(_("Uploaded file does not look like a PDF."))
            self._validate_pdf_keywords(upload)
        if ext in {"io", "lxf"} and not self._looks_like_zip(upload):
            raise forms.ValidationError(
                _("Uploaded file does not look like a valid %(ext)s archive.")
                % {"ext": ext}
            )
        if ext == "io" and self._has_encrypted_zip_entries(upload):
            raise forms.ValidationError(
                _("This .io archive is password-protected. Please export without a password.")
            )
        self._inferred_content_type = ext[:20]
        return upload

    def clean_preview_upload(self):
        upload = self.cleaned_data.get("preview_upload")
        if not upload:
            return upload
        max_mb = int(getattr(settings, "MAX_PREVIEW_UPLOAD_MB", 5))
        self._validate_upload_size(upload, max_mb, _("Preview image"))
        content_type = getattr(upload, "content_type", "")
        ext = os.path.splitext(upload.name)[1].lower()
        allowed_ext = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
        if content_type and not content_type.startswith("image/"):
            raise forms.ValidationError(_("Please upload an image file."))
        if ext and ext not in allowed_ext:
            raise forms.ValidationError(_("Allowed formats: jpg, jpeg, png, webp, gif."))
        return upload

    def _validate_upload_size(self, upload, max_mb, label):
        if not upload:
            return
        max_bytes = max_mb * 1024 * 1024
        if getattr(upload, "size", 0) > max_bytes:
            raise forms.ValidationError(
                _("%(label)s must be smaller than %(size)s MB.")
                % {"label": label, "size": max_mb}
            )

    def _looks_like_pdf(self, upload):
        try:
            header = upload.read(4)
        except Exception:
            return False
        finally:
            try:
                upload.seek(0)
            except Exception:
                pass
        return header == b"%PDF"

    def _looks_like_zip(self, upload):
        try:
            header = upload.read(2)
        except Exception:
            return False
        finally:
            try:
                upload.seek(0)
            except Exception:
                pass
        return header == b"PK"

    def _has_encrypted_zip_entries(self, upload):
        try:
            upload.seek(0)
            with zipfile.ZipFile(upload) as archive:
                for info in archive.infolist():
                    if info.flag_bits & 0x1:
                        return True
        except zipfile.BadZipFile:
            return False
        except RuntimeError:
            return True
        finally:
            try:
                upload.seek(0)
            except Exception:
                pass
        return False

    def _validate_pdf_keywords(self, upload):
        try:
            from pypdf import PdfReader
        except Exception as exc:
            raise forms.ValidationError(
                _("PDF keyword validation requires the pypdf package.")
            ) from exc

        try:
            upload.seek(0)
            reader = PdfReader(upload)
            text_parts = []
            max_pages = 5
            max_chars = 20000
            for page in reader.pages[:max_pages]:
                text = page.extract_text() or ""
                if text:
                    text_parts.append(text)
                if sum(len(part) for part in text_parts) >= max_chars:
                    break
        except Exception as exc:
            raise forms.ValidationError(
                _("Could not read PDF content. Please upload a text-based PDF.")
            ) from exc
        finally:
            upload.seek(0)

        combined = " ".join(text_parts).lower()
        if not combined:
            raise forms.ValidationError(
                _("PDF content is empty. Please upload a text-based PDF.")
            )
        if not any(keyword in combined for keyword in self.PDF_KEYWORDS):
            raise forms.ValidationError(
                _("PDF must mention competitions like WRO, FLL, Enjoy AI, or VEX.")
            )

    def _resolve_category(self):
        category = self.cleaned_data.get("category")
        new_category = (self.cleaned_data.get("new_category") or "").strip()
        if new_category:
            category = self._get_or_create_category(new_category)
        return category

    def _get_or_create_category(self, name):
        category = Category.objects.filter(name__iexact=name).first()
        if category:
            if not category.is_active:
                category.is_active = True
                category.save(update_fields=["is_active"])
            return category

        base_slug = slugify(name)[:140] or "category"
        slug = base_slug
        counter = 2
        while Category.objects.filter(slug=slug).exists():
            suffix = f"-{counter}"
            slug = f"{base_slug[:140 - len(suffix)]}{suffix}"
            counter += 1
        return Category.objects.create(name=name, slug=slug)

    def save(self, commit=True):
        submission = super().save(commit=False)
        submission.category = self._resolve_category()
        if commit:
            submission.save()
            self.save_m2m()
        return submission

    @property
    def inferred_content_type(self):
        return getattr(self, "_inferred_content_type", None)
