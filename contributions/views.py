import os

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _

from .forms import ContributionSubmissionForm

try:
    import fitz
except Exception:
    fitz = None


def _build_storage_path(user_id, filename):
    safe_name = os.path.basename(filename)
    timestamp = timezone.now().strftime("%Y%m%d_%H%M%S")
    return f"contrib/{user_id}/{timestamp}_{safe_name}"


def _build_preview_path(user_id, filename):
    safe_name = os.path.basename(filename)
    timestamp = timezone.now().strftime("%Y%m%d_%H%M%S")
    return f"previews/contrib/{user_id}/{timestamp}_{safe_name}"


def _save_upload(file_obj, destination):
    return default_storage.save(destination, file_obj)


def _build_preview_filename(original_name):
    base_name = os.path.splitext(os.path.basename(original_name))[0] or "preview"
    return f"{base_name}.png"


def _render_pdf_first_page(pdf_bytes, target_width=1200):
    if not fitz:
        return None
    doc = None
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        if doc.page_count < 1:
            return None
        page = doc.load_page(0)
        page_width = page.rect.width or 1
        scale = target_width / page_width
        scale = max(0.5, min(scale, 2.0))
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        return pix.tobytes("png")
    except Exception:
        return None
    finally:
        if doc:
            doc.close()


def _maybe_generate_pdf_preview(source_path, preview_path):
    max_mb = int(getattr(settings, "MAX_PDF_PREVIEW_MB", 20))
    try:
        size_bytes = default_storage.size(source_path)
    except Exception:
        size_bytes = None
    if size_bytes and size_bytes > max_mb * 1024 * 1024:
        return ""
    try:
        with default_storage.open(source_path, "rb") as pdf_file:
            pdf_bytes = pdf_file.read()
    except Exception:
        return ""
    preview_bytes = _render_pdf_first_page(pdf_bytes)
    if not preview_bytes:
        return ""
    return default_storage.save(preview_path, ContentFile(preview_bytes))


@login_required
def submit(request):
    if request.method == "POST":
        form = ContributionSubmissionForm(request.POST, request.FILES)
        if form.is_valid():
            upload = form.cleaned_data["file_upload"]
            preview_upload = form.cleaned_data.get("preview_upload")
            content_type = form.inferred_content_type
            if not content_type:
                messages.error(request, _("Could not determine file type."))
                return render(request, "contributions/submit.html", {"form": form})
            storage_path = _build_storage_path(request.user.id, upload.name)
            preview_path = ""
            if preview_upload:
                preview_path = _build_preview_path(request.user.id, preview_upload.name)
            try:
                upload.seek(0)
                saved_path = _save_upload(upload, storage_path)
                saved_preview_path = ""
                if preview_upload and preview_path:
                    preview_upload.seek(0)
                    saved_preview_path = _save_upload(preview_upload, preview_path)
                elif content_type == "pdf":
                    auto_preview_name = _build_preview_filename(upload.name)
                    auto_preview_path = _build_preview_path(request.user.id, auto_preview_name)
                    saved_preview_path = _maybe_generate_pdf_preview(
                        saved_path, auto_preview_path
                    )
            except Exception as exc:
                messages.error(request, _("Upload failed: %(error)s") % {"error": exc})
                return render(request, "contributions/submit.html", {"form": form})

            submission = form.save(commit=False)
            submission.user = request.user
            submission.content_type = content_type
            submission.file_path = saved_path
            submission.preview_path = saved_preview_path
            submission.save()
            messages.success(request, _("Submission received for review."))
            return redirect("accounts:profile")
    else:
        form = ContributionSubmissionForm()

    return render(request, "contributions/submit.html", {"form": form})
