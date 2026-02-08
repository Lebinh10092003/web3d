import logging
import os
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.files.storage import default_storage
from django.db import transaction
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _

from .forms import ContributionSubmissionEditForm, ContributionSubmissionForm
from .models import ContributionSubmission
from .preview_utils import build_preview_filename, build_preview_path
from .tasks import enqueue_preview_generation

logger = logging.getLogger(__name__)


def _build_storage_path(user_id, filename):
    safe_name = os.path.basename(filename)
    timestamp = timezone.now().strftime("%Y%m%d_%H%M%S")
    return f"contrib/{user_id}/{timestamp}_{safe_name}"


def _save_upload(file_obj, destination):
    return default_storage.save(destination, file_obj)


def _cleanup_saved_files(*paths):
    for path in paths:
        if not path:
            continue
        try:
            if default_storage.exists(path):
                default_storage.delete(path)
        except Exception:
            # Best-effort clean-up; ignore failures to avoid masking the original error.
            continue


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
            # Enforce competition relevance: must match robotics/programming competitions
            competition = form.cleaned_data.get("competition") or ""
            allowed_competitions = {
                choice[0] for choice in ContributionSubmission.Competition.choices
            }
            if competition and competition not in allowed_competitions:
                messages.error(request, _("Invalid competition selection."))
                return render(request, "contributions/submit.html", {"form": form})
            if not competition:
                messages.warning(
                    request,
                    _("Please select a competition (WRO, FLL, Enjoy AI, Whalebot) or programming contest (HKICO, Python, Blockly, Scratch)."),
                )
                return render(request, "contributions/submit.html", {"form": form})
            storage_path = _build_storage_path(request.user.id, upload.name)
            preview_path = ""
            if preview_upload:
                preview_path = build_preview_path(request.user.id, preview_upload.name)
            try:
                upload.seek(0)
                saved_path = _save_upload(upload, storage_path)
                saved_preview_path = ""
                if preview_upload and preview_path:
                    preview_upload.seek(0)
                    saved_preview_path = _save_upload(preview_upload, preview_path)
                elif content_type in {"pdf", "lxf", "io"}:
                    auto_preview_name = build_preview_filename(upload.name)
                    saved_preview_path = build_preview_path(
                        request.user.id, auto_preview_name
                    )
            except Exception as exc:
                messages.error(request, _("Upload failed: %(error)s") % {"error": exc})
                return render(request, "contributions/submit.html", {"form": form})

            try:
                with transaction.atomic():
                    submission = form.save(commit=False)
                    submission.user = request.user
                    submission.content_type = content_type
                    submission.file_path = saved_path
                    submission.preview_path = saved_preview_path
                    submission.save()
            except Exception as exc:
                logger.exception("Failed to save contribution submission")
                _cleanup_saved_files(saved_path, saved_preview_path)
                messages.error(
                    request,
                    _("Could not save your submission right now. Please try again or contact support."),
                )
                return render(request, "contributions/submit.html", {"form": form})
            if not preview_upload and content_type in {"pdf", "lxf", "io"}:
                enqueue_preview_generation(submission.id)
            if request.LANGUAGE_CODE == "vi":
                success_message = (
                    "Đã nhận bài gửi để xét duyệt. "
                    "Bạn có thể gửi thêm tài liệu khác hoặc quay lại sau để kiểm tra kết quả."
                )
            else:
                success_message = (
                    "Submission received for review. "
                    "You can submit another file or check back later for the result."
                )
            messages.success(request, success_message)
            return redirect("contributions:submit")
    else:
        form = ContributionSubmissionForm()

    return render(request, "contributions/submit.html", {"form": form})


@login_required
def edit_submission(request, submission_id):
    submission = ContributionSubmission.objects.filter(pk=submission_id).first()
    if not submission:
        return redirect("contributions:submit")
    if not (request.user.is_staff or submission.user_id == request.user.id):
        return redirect("contributions:submit")

    if request.method == "POST":
        form = ContributionSubmissionEditForm(request.POST, instance=submission)
        if form.is_valid():
            submission = form.save(commit=False)
            submission.save()
            if request.LANGUAGE_CODE == "vi":
                success_message = "ÄÃ£ cáº­p nháº­t thÃ´ng tin bÃ i gá»­i."
            else:
                success_message = "Submission updated successfully."
            messages.success(request, success_message)
            return redirect("contributions:edit", submission_id=submission.id)
    else:
        form = ContributionSubmissionEditForm(instance=submission)

    return render(
        request,
        "contributions/submit.html",
        {"form": form, "submission": submission, "is_edit": True},
    )
