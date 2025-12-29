import logging
import os

from django.core.files.storage import default_storage

from library.models import ContentFile
from web3d.queue import enqueue_task

from .models import ContributionSubmission
from .preview_utils import (
    build_preview_filename,
    build_preview_path,
    maybe_generate_archive_preview,
    maybe_generate_pdf_preview,
)

logger = logging.getLogger(__name__)


def enqueue_preview_generation(submission_id):
    return enqueue_task(generate_submission_preview, submission_id)


def generate_submission_preview(submission_id):
    submission = (
        ContributionSubmission.objects.filter(pk=submission_id)
        .select_related("user")
        .first()
    )
    if not submission or not submission.file_path:
        return

    if submission.preview_path and default_storage.exists(submission.preview_path):
        _attach_preview_if_ready(submission)
        return

    preview_path = submission.preview_path
    if not preview_path:
        auto_name = build_preview_filename(submission.file_path)
        preview_path = build_preview_path(submission.user_id, auto_name)
        submission.preview_path = preview_path
        submission.save(update_fields=["preview_path"])

    ext = os.path.splitext(submission.file_path)[1].lstrip(".").lower()
    saved_path = ""
    if ext == "pdf":
        saved_path = maybe_generate_pdf_preview(submission.file_path, preview_path)
    elif ext in {"lxf", "io"}:
        saved_path = maybe_generate_archive_preview(submission.file_path, preview_path)

    if saved_path and saved_path != submission.preview_path:
        submission.preview_path = saved_path
        submission.save(update_fields=["preview_path"])

    if saved_path:
        _attach_preview_if_ready(submission)


def _attach_preview_if_ready(submission):
    if submission.status != submission.Status.APPROVED:
        return
    if not submission.preview_path or not default_storage.exists(submission.preview_path):
        return
    source = (
        ContentFile.objects.filter(
            storage_path=submission.file_path,
            kind=ContentFile.FileKind.SOURCE,
        )
        .select_related("content")
        .first()
    )
    if not source:
        return
    submission._attach_preview(source.content)
