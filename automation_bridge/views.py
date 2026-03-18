import json
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import Http404, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from blog.models import Post, PostRevision
from blog.views import _parse_iso_datetime

from .models import BlogAutomationRun
from .services import (
    build_post_response,
    create_post_from_payload,
    ingest_media_items,
    prepare_blog_payload,
)


def _ensure_enabled():
    if not getattr(settings, "BLOG_AUTOMATION_ENABLED", False):
        raise Http404


def _json_body(request):
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        payload = {}
    return payload if isinstance(payload, dict) else {}


def _error(message, *, status=400, request_id=""):
    payload = {"ok": False, "error": message}
    if request_id:
        payload["request_id"] = request_id
    return JsonResponse(payload, status=status)


def _check_token(request):
    token = (settings.BLOG_AUTOMATION_TOKEN or "").strip()
    if not token:
        return False, _error("Blog automation token is not configured.", status=503)
    auth_header = request.headers.get("Authorization", "")
    if auth_header != f"Bearer {token}":
        return False, _error("Unauthorized.", status=403)
    return True, None


def _make_request_id(raw_value):
    text = str(raw_value or "").strip()[:80] or uuid.uuid4().hex
    if BlogAutomationRun.objects.filter(request_id=text).exists():
        text = uuid.uuid4().hex
    return text


def _get_run_or_error(request_id):
    run = BlogAutomationRun.objects.select_related("created_post").filter(request_id=request_id).first()
    if run is None:
        return None, _error("Request not found.", status=404, request_id=request_id)
    return run, None


def _lookup_latest_params(request, *, payload=None):
    data = payload if isinstance(payload, dict) else {}
    source_channel = str(
        data.get("source_channel") or request.GET.get("source_channel") or "whatsapp"
    ).strip()[:40] or "whatsapp"
    requested_by = str(
        data.get("requested_by") or data.get("from") or request.GET.get("requested_by") or ""
    ).strip()[:120]
    if not requested_by:
        return None, None, _error("requested_by is required.")
    return source_channel, requested_by, None


def _get_latest_run_or_error(source_channel, requested_by):
    run = (
        BlogAutomationRun.objects.select_related("created_post")
        .filter(
            source_channel=source_channel,
            requested_by=requested_by,
            status=BlogAutomationRun.Status.CREATED,
            created_post__isnull=False,
        )
        .first()
    )
    if run is None:
        return None, _error("No blog request found for this sender.", status=404)
    return run, None


def _serialize_run(run, *, request_obj=None):
    post_payload = None
    if run.created_post_id:
        block_count = run.created_post.blocks.count()
        post_payload = build_post_response(run.created_post, block_count=block_count, request_obj=request_obj)
        post_payload["title"] = run.created_post.title

    payload = run.payload if isinstance(run.payload, dict) else {}
    return {
        "request_id": run.request_id,
        "status": run.status,
        "source_channel": run.source_channel,
        "requested_by": run.requested_by,
        "command_text": run.command_text,
        "input": payload.get("input", {}),
        "resolved": payload.get("resolved", {}),
        "publish_request": payload.get("publish_request", {}),
        "post": post_payload,
        "sources": run.sources or [],
        "media": run.media_results or [],
        "error_detail": run.error_detail,
        "created_at": run.created_at.isoformat(),
        "updated_at": run.updated_at.isoformat(),
    }


def _publish_run(run, payload, *, request_obj):
    if run.created_post is None:
        return _error("Request does not have a created post.", status=409, request_id=run.request_id)

    published_raw = payload.get("published_at") or payload.get("publish_at")
    published_at = _parse_iso_datetime(published_raw) if published_raw else None
    if published_raw and not published_at:
        return _error("invalid_published_at", status=400, request_id=run.request_id)

    post = run.created_post
    now = timezone.now()
    if not published_at and post.status == Post.Status.PUBLISHED and post.published_at <= now:
        return JsonResponse(
            {
                "ok": True,
                "request_id": run.request_id,
                "already_published": True,
                "post": build_post_response(
                    post,
                    block_count=post.blocks.count(),
                    request_obj=request_obj,
                ),
            }
        )

    effective_publish_at = published_at or now
    target_status = Post.Status.SCHEDULED if effective_publish_at > now else Post.Status.PUBLISHED

    with transaction.atomic():
        post.status = target_status
        post.published_at = effective_publish_at
        post.save(update_fields=["status", "published_at", "updated_at"])
        PostRevision.objects.create(
            post=post,
            created_by=post.author,
            is_autosave=False,
            payload=post.snapshot(),
        )

        stored_payload = dict(run.payload or {})
        stored_payload["publish_request"] = {
            "requested_at": now.isoformat(),
            "published_at": effective_publish_at.isoformat(),
            "status": target_status,
        }
        run.payload = stored_payload
        run.save(update_fields=["payload", "updated_at"])

    return JsonResponse(
        {
            "ok": True,
            "request_id": run.request_id,
            "post": build_post_response(
                run.created_post,
                block_count=run.created_post.blocks.count(),
                request_obj=request_obj,
            ),
        }
    )


@csrf_exempt
@require_POST
def media_ingest(request):
    _ensure_enabled()
    ok, error_response = _check_token(request)
    if not ok:
        return error_response

    payload = _json_body(request)
    items = payload.get("items") or []
    if not isinstance(items, list) or not items:
        single_url = str(payload.get("url") or "").strip()
        if single_url:
            items = [{"url": single_url, "kind": payload.get("kind") or "auto"}]
        else:
            items = []
    if not items:
        return _error("No media items provided.")

    try:
        results = ingest_media_items(items, request_obj=request)
    except ValidationError as exc:
        message = exc.messages[0] if getattr(exc, "messages", None) else str(exc)
        return _error(message)

    return JsonResponse({"ok": True, "items": results})


@csrf_exempt
@require_POST
def blog_publish(request):
    _ensure_enabled()
    ok, error_response = _check_token(request)
    if not ok:
        return error_response

    payload = _json_body(request)
    provided_request_id = str(payload.get("request_id") or "").strip()[:80]
    existing_run = None
    if provided_request_id:
        existing_run = (
            BlogAutomationRun.objects.select_related("created_post")
            .filter(request_id=provided_request_id)
            .first()
        )
    if existing_run and existing_run.status == BlogAutomationRun.Status.CREATED and existing_run.created_post_id:
        return JsonResponse(
            {
                "ok": True,
                "duplicate": True,
                "request_id": existing_run.request_id,
                "post": build_post_response(
                    existing_run.created_post,
                    block_count=existing_run.created_post.blocks.count(),
                    request_obj=request,
                ),
                "media": existing_run.media_results or [],
                "sources": existing_run.sources or [],
            }
        )
    if existing_run:
        return _error("request_id already exists.", status=409, request_id=existing_run.request_id)

    request_id = _make_request_id(provided_request_id)
    run = BlogAutomationRun.objects.create(
        request_id=request_id,
        source_channel=str(payload.get("source_channel") or "whatsapp").strip()[:40],
        requested_by=str(payload.get("requested_by") or payload.get("from") or "").strip()[:120],
        command_text=str(payload.get("command_text") or payload.get("command") or "").strip(),
        payload={"input": payload},
        status=BlogAutomationRun.Status.RECEIVED,
    )

    try:
        prepared_payload, media_results, sources = prepare_blog_payload(payload, request_obj=request)
        post, normalized_blocks = create_post_from_payload(prepared_payload)
    except ValidationError as exc:
        message = exc.messages[0] if getattr(exc, "messages", None) else str(exc)
        run.status = BlogAutomationRun.Status.FAILED
        run.error_detail = message
        run.save(update_fields=["status", "error_detail", "updated_at"])
        return _error(message, request_id=request_id)
    except Exception as exc:
        run.status = BlogAutomationRun.Status.FAILED
        run.error_detail = str(exc)
        run.save(update_fields=["status", "error_detail", "updated_at"])
        return _error("Unexpected automation error.", status=500, request_id=request_id)

    run.payload = {"input": payload, "resolved": prepared_payload}
    run.sources = sources
    run.media_results = media_results
    run.created_post = post
    run.status = BlogAutomationRun.Status.CREATED
    run.error_detail = ""
    run.save(
        update_fields=[
            "payload",
            "sources",
            "media_results",
            "created_post",
            "status",
            "error_detail",
            "updated_at",
        ]
    )

    return JsonResponse(
        {
            "ok": True,
            "request_id": request_id,
            "post": build_post_response(post, block_count=len(normalized_blocks), request_obj=request),
            "media": media_results,
            "sources": sources,
        },
        status=201,
    )


@require_GET
def blog_request_detail(request, request_id):
    _ensure_enabled()
    ok, error_response = _check_token(request)
    if not ok:
        return error_response

    run, error_response = _get_run_or_error(request_id)
    if error_response:
        return error_response

    return JsonResponse({"ok": True, "request": _serialize_run(run, request_obj=request)})


@require_GET
def blog_request_latest_detail(request):
    _ensure_enabled()
    ok, error_response = _check_token(request)
    if not ok:
        return error_response

    source_channel, requested_by, error_response = _lookup_latest_params(request)
    if error_response:
        return error_response

    run, error_response = _get_latest_run_or_error(source_channel, requested_by)
    if error_response:
        return error_response

    return JsonResponse({"ok": True, "request": _serialize_run(run, request_obj=request)})


@csrf_exempt
@require_POST
def blog_request_publish(request, request_id):
    _ensure_enabled()
    ok, error_response = _check_token(request)
    if not ok:
        return error_response

    run, error_response = _get_run_or_error(request_id)
    if error_response:
        return error_response

    payload = _json_body(request)
    return _publish_run(run, payload, request_obj=request)


@csrf_exempt
@require_POST
def blog_request_latest_publish(request):
    _ensure_enabled()
    ok, error_response = _check_token(request)
    if not ok:
        return error_response

    payload = _json_body(request)
    source_channel, requested_by, error_response = _lookup_latest_params(request, payload=payload)
    if error_response:
        return error_response

    run, error_response = _get_latest_run_or_error(source_channel, requested_by)
    if error_response:
        return error_response

    return _publish_run(run, payload, request_obj=request)
