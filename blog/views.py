from django.shortcuts import get_object_or_404, redirect, render
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse, HttpResponseRedirect, HttpResponseBadRequest, JsonResponse
from django.urls import reverse
from django.core.paginator import Paginator
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST
import json
import os
import uuid
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile

from .models import BlogComment, Post, PostBlock, PostRevision
from .forms import BlogCommentForm, PostQuickForm


def _seo_title(post):
    return post.seo_title or post.title


def _seo_description(post):
    if post.seo_description:
        return post.seo_description
    if post.summary:
        return post.summary
    return (post.body or "")[:155]


def _get_client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        ip = forwarded.split(",")[0].strip()
        return ip or None
    ip = request.META.get("REMOTE_ADDR")
    return ip if ip else None


def _rate_limit(request, key, limit, window):
    if not limit or limit <= 0:
        return True
    if request.user.is_authenticated:
        identity = f"user:{request.user.id}"
    else:
        identity = _get_client_ip(request) or "anon"
    cache_key = f"rl:{key}:{identity}"
    try:
        count = cache.incr(cache_key)
    except ValueError:
        cache.set(cache_key, 1, timeout=window)
        count = 1
    return count <= limit


def _rate_limit_response(window):
    response = HttpResponse("Too Many Requests", status=429, content_type="text/plain")
    response["Retry-After"] = str(window)
    return response


def _get_visible_post_or_404(request, slug):
    qs = Post.objects
    if not request.user.is_staff and not request.user.is_superuser:
        qs = qs.live()
    return get_object_or_404(qs, slug=slug)


def _get_related_posts(request, post, limit=6):
    qs = Post.objects
    if not request.user.is_staff and not request.user.is_superuser:
        qs = qs.live()
    return list(
        qs.exclude(pk=post.pk).order_by("-published_at", "-created_at")[:limit]
    )


def _get_comments(post):
    return list(
        BlogComment.objects.filter(post=post, parent__isnull=True)
        .select_related("user")
        .prefetch_related("replies__user")
    )


def _render_comment_list(request, post, comments, edit_form=None, editing_comment_id=None):
    context = {
        "post": post,
        "comments": comments,
        "edit_form": edit_form,
        "editing_comment_id": editing_comment_id,
    }
    if request.headers.get("HX-Request") == "true":
        return render(request, "blog/_comment_list.html", context)
    return redirect("blog:detail", slug=post.slug)


def _can_manage_comment(user, comment):
    return user.is_authenticated and (user.is_staff or comment.user_id == user.id)


def post_list(request):
    # autopublish scheduled posts when due
    Post.objects.scheduled().filter(published_at__lte=timezone.now()).update(status=Post.Status.PUBLISHED)

    posts = Post.objects.live().select_related("author")
    paginator = Paginator(posts, 9)
    page_obj = paginator.get_page(request.GET.get("page") or 1)
    page_range = paginator.get_elided_page_range(
        number=page_obj.number, on_each_side=1, on_ends=1
    )
    context = {
        "page_obj": page_obj,
        "page_range": page_range,
        "page_title": _("Blog / News"),
        "seo_title": _("STEAM & Robotics Blog - V+ STEAM LAB Library"),
        "seo_description": _("News, competition insights, robot tutorials, and new STEAM resources from V+ STEAM LAB Library."),
    }
    return render(request, "blog/list.html", context)


def post_detail(request, slug):
    post = _get_visible_post_or_404(request, slug)
    blocks = post.blocks.order_by("position", "created_at")
    related_posts = _get_related_posts(request, post)
    comments = _get_comments(post)
    context = {
        "post": post,
        "blocks": blocks,
        "related_posts_sidebar": related_posts[:4],
        "related_posts_bottom": related_posts[:4],
        "comments": comments,
        "edit_form": None,
        "editing_comment_id": None,
        "seo_title": _seo_title(post),
        "seo_description": _seo_description(post),
        "canonical_url": request.build_absolute_uri(request.path),
    }
    return render(request, "blog/detail.html", context)


@require_POST
@login_required
def add_comment(request, slug):
    limit = int(getattr(settings, "RATE_LIMIT_BLOG_COMMENT_PER_MIN", 12) or 12)
    if not _rate_limit(request, "blog:comment", limit, 60):
        return _rate_limit_response(60)
    post = _get_visible_post_or_404(request, slug)
    form = BlogCommentForm(request.POST)
    if form.is_valid():
        parent = None
        parent_id = form.cleaned_data.get("parent_id")
        if parent_id:
            parent = BlogComment.objects.filter(id=parent_id, post=post).first()
        BlogComment.objects.create(
            post=post,
            user=request.user,
            body=form.cleaned_data["body"],
            parent=parent,
        )
    else:
        messages.error(request, _("Comment could not be saved."))

    comments = _get_comments(post)
    return _render_comment_list(request, post, comments)


@login_required
def edit_comment(request, slug, comment_id):
    post = _get_visible_post_or_404(request, slug)
    comment = get_object_or_404(BlogComment, pk=comment_id, post=post)
    if not _can_manage_comment(request.user, comment) or comment.is_deleted:
        return HttpResponse(status=403)

    if request.method == "POST":
        form = BlogCommentForm(request.POST)
        if form.is_valid():
            comment.body = form.cleaned_data["body"]
            comment.save(update_fields=["body", "updated_at"])
        else:
            messages.error(request, _("Comment could not be updated."))
            comments = _get_comments(post)
            return _render_comment_list(
                request, post, comments, edit_form=form, editing_comment_id=comment.id
            )
        comments = _get_comments(post)
        return _render_comment_list(request, post, comments)

    if request.GET.get("cancel") == "1":
        comments = _get_comments(post)
        return _render_comment_list(request, post, comments)

    form = BlogCommentForm(initial={"body": comment.body})
    comments = _get_comments(post)
    return _render_comment_list(
        request, post, comments, edit_form=form, editing_comment_id=comment.id
    )


@require_POST
@login_required
def delete_comment(request, slug, comment_id):
    post = _get_visible_post_or_404(request, slug)
    comment = get_object_or_404(BlogComment, pk=comment_id, post=post)
    if not _can_manage_comment(request.user, comment) or comment.is_deleted:
        return HttpResponse(status=403)

    comment.is_deleted = True
    comment.save(update_fields=["is_deleted", "updated_at"])
    comments = _get_comments(post)
    return _render_comment_list(request, post, comments)


@login_required
@user_passes_test(lambda u: u.is_staff or u.is_superuser)
def post_quick_create(request):
    if request.method == "POST":
        form = PostQuickForm(request.POST)
        if form.is_valid():
            post = form.save(commit=False)
            post.author = request.user
            post.save()
            messages.success(request, _("Post created. You can add detailed content blocks."))
            return HttpResponseRedirect(reverse("blog:editor-edit", args=[post.pk]))
    else:
        form = PostQuickForm(initial={"status": Post.Status.DRAFT, "published_at": timezone.now()})
    return render(
        request,
        "blog/create.html",
        {
            "form": form,
            "seo_title": _("Create blog post - V+ STEAM LAB Library"),
            "seo_description": _("Compose blog posts, schedule publishing, and add content blocks."),
        },
    )


def _staff_required(user):
    return user.is_staff or user.is_superuser


@login_required
@user_passes_test(_staff_required)
def post_editor_new(request):
    return post_editor_edit(request, post_id=None)


@login_required
@user_passes_test(_staff_required)
def post_editor_edit(request, post_id=None):
    post = None
    if post_id:
        post = get_object_or_404(Post, pk=post_id)

    if request.method == "POST":
        title = request.POST.get("title", "").strip()
        if not title:
            return HttpResponseBadRequest(_("Title is required"))
        summary = request.POST.get("summary", "").strip()
        hero_image_url = request.POST.get("hero_image_url", "").strip()
        status = request.POST.get("status") or Post.Status.DRAFT
        published_at_raw = request.POST.get("published_at")
        try:
            published_at = timezone.datetime.fromisoformat(published_at_raw) if published_at_raw else timezone.now()
            if not published_at.tzinfo:
                published_at = timezone.make_aware(published_at)
        except Exception:
            published_at = timezone.now()

        blocks_json = request.POST.get("blocks_json") or "[]"
        try:
            blocks_payload = json.loads(blocks_json)
        except Exception:
            blocks_payload = []

        if post is None:
            post = Post(author=request.user)
        post.title = title
        post.summary = summary
        post.hero_image_url = hero_image_url
        post.status = status
        post.published_at = published_at
        post.save()

        # replace blocks
        PostBlock.objects.filter(post=post).delete()
        block_objs = []
        for idx, item in enumerate(blocks_payload, start=1):
            if not isinstance(item, dict):
                continue
            block_objs.append(
                PostBlock(
                    post=post,
                    position=item.get("position") or idx,
                    type=item.get("type") or PostBlock.BlockType.TEXT,
                    text=item.get("text", ""),
                    media_url=item.get("media_url", ""),
                    caption=item.get("caption", ""),
                    alt_text=item.get("alt_text", ""),
                    align=item.get("align", ""),
                    data=item.get("data") or {},
                )
            )
        if block_objs:
            PostBlock.objects.bulk_create(block_objs)

        PostRevision.objects.create(
            post=post,
            created_by=request.user,
            is_autosave=False,
            payload=post.snapshot(),
        )

        messages.success(request, _("Post saved. You can continue editing."))
        return HttpResponseRedirect(reverse("blog:editor-edit", args=[post.id]))

    initial_blocks = []
    if post:
        initial_blocks = [b.to_dict() for b in post.blocks.order_by("position", "created_at")]

    context = {
        "post": post,
        "initial_blocks_json": json.dumps(initial_blocks),
        "seo_title": _("Edit blog post") if post else _("Create blog post"),
        "seo_description": _("Compose blog posts with content blocks, images, videos, and galleries."),
    }
    return render(request, "blog/editor.html", context)


@login_required
@user_passes_test(_staff_required)
def upload_media(request):
    if request.method != "POST" or "file" not in request.FILES:
        return JsonResponse({"error": "No file"}, status=400)
    file = request.FILES["file"]
    ext = os.path.splitext(file.name)[1] or ""
    key = f"blog/{uuid.uuid4().hex}{ext}"
    path = default_storage.save(key, ContentFile(file.read()))
    url = default_storage.url(path)
    return JsonResponse({"url": url})
