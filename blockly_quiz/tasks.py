import logging
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings
from django.utils import timezone

from web3d.queue import enqueue_task

from .models import Attempt


logger = logging.getLogger(__name__)


def enqueue_attempt_export(attempt_id: int):
    return enqueue_task(export_attempt_to_google_sheets, attempt_id)


def _get_attempt_name(attempt: Attempt) -> str:
    if (attempt.participant_name or "").strip():
        return attempt.participant_name.strip()
    user = attempt.user
    if not user:
        return ""
    return (
        (getattr(user, "display_name", "") or "").strip()
        or (getattr(user, "get_full_name", lambda: "")() or "").strip()
        or (getattr(user, "username", "") or "").strip()
    )


def export_attempt_to_google_sheets(attempt_id: int):
    url = (getattr(settings, "BLOCKLY_QUIZ_GSHEET_URL", "") or "").strip()
    if not url:
        return
    try:
        attempt = Attempt.objects.select_related("quiz", "user").get(pk=attempt_id)
    except Attempt.DoesNotExist:
        return

    if not attempt.completed_at:
        return
    if attempt.sheets_sent_at:
        return

    payload = {
        "name": _get_attempt_name(attempt),
        "dob": (attempt.participant_dob or "").strip(),
        "campus": (attempt.participant_campus or "").strip(),
        "score": str(attempt.correct_count),
        "total": str(attempt.total_questions),
        "test_name": (attempt.quiz.title or attempt.quiz.slug or "").strip(),
    }

    timeout = int(getattr(settings, "BLOCKLY_QUIZ_GSHEET_TIMEOUT", 10) or 10)
    encoded = urlencode(payload).encode("utf-8")
    request = Request(
        url,
        data=encoded,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            response.read()
    except Exception as exc:
        Attempt.objects.filter(pk=attempt_id).update(
            sheets_queued_at=None,
            sheets_error=str(exc)[:500],
        )
        logger.exception("Failed to export quiz attempt %s to Google Sheets", attempt_id)
        return

    Attempt.objects.filter(pk=attempt_id).update(
        sheets_sent_at=timezone.now(),
        sheets_error="",
    )

