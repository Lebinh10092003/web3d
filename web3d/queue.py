import logging

from django.conf import settings

logger = logging.getLogger(__name__)


def enqueue_task(func, *args, **kwargs):
    if not getattr(settings, "USE_BACKGROUND_JOBS", True):
        return func(*args, **kwargs)
    try:
        import django_rq
    except Exception:
        if settings.DEBUG:
            logger.warning("django_rq not available; running task inline.")
            return func(*args, **kwargs)
        logger.error("django_rq not available; background task skipped.")
        return None
    try:
        job_timeout = kwargs.pop(
            "job_timeout", getattr(settings, "RQ_DEFAULT_TIMEOUT", None)
        )
        if job_timeout:
            return django_rq.enqueue(func, *args, job_timeout=job_timeout, **kwargs)
        return django_rq.enqueue(func, *args, **kwargs)
    except Exception:
        if settings.DEBUG:
            logger.exception("Failed to enqueue task; running inline.")
            return func(*args, **kwargs)
        logger.exception("Failed to enqueue task; background task skipped.")
        return None
