import logging
import os

from web3d.queue import enqueue_task

from .lego_ldraw import UnsupportedLegoModel, get_cached_ldraw_model_path

logger = logging.getLogger(__name__)


def enqueue_ldraw_prebuild(content_id, source_path):
    return enqueue_task(prebuild_ldraw_model, content_id, source_path)


def prebuild_ldraw_model(content_id, source_path):
    if not content_id or not source_path:
        return
    ext = os.path.splitext(source_path)[1].lstrip(".").lower()
    if ext not in {"lxf", "io", "ldr", "mpd"}:
        return
    try:
        get_cached_ldraw_model_path(content_id=content_id, source_path=source_path)
    except UnsupportedLegoModel as exc:
        logger.warning("LDraw prebuild skipped for content %s: %s", content_id, exc)
    except Exception:
        logger.exception("Unexpected LDraw prebuild failure for content %s", content_id)
