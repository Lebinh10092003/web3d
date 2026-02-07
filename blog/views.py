from django.shortcuts import get_object_or_404, render
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import HttpResponseRedirect, HttpResponseBadRequest, JsonResponse
from django.urls import reverse
from django.utils import timezone
import json
import os
import uuid
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile

from .models import Post, PostBlock, PostRevision
from .forms import PostQuickForm


def _seo_title(post):
    return post.seo_title or post.title


def _seo_description(post):
    if post.seo_description:
        return post.seo_description
    if post.summary:
        return post.summary
    return (post.body or "")[:155]


def post_list(request):
    # autopublish scheduled posts when due
    Post.objects.scheduled().filter(published_at__lte=timezone.now()).update(status=Post.Status.PUBLISHED)

    posts = Post.objects.live()
    context = {
        "posts": posts,
        "page_title": "Blog / Tin tức",
        "seo_title": "Blog STEAM & Robotics - V+ STEAM LAB Library",
        "seo_description": "Tin tức, phân tích luật thi, hướng dẫn lập trình robot và tài nguyên STEAM mới nhất từ V+ STEAM LAB Library.",
    }
    return render(request, "blog/list.html", context)


def post_detail(request, slug):
    qs = Post.objects
    if not request.user.is_staff and not request.user.is_superuser:
        qs = qs.live()
    post = get_object_or_404(qs, slug=slug)
    blocks = post.blocks.order_by("position", "created_at")
    context = {
        "post": post,
        "blocks": blocks,
        "seo_title": _seo_title(post),
        "seo_description": _seo_description(post),
        "canonical_url": request.build_absolute_uri(request.path),
    }
    return render(request, "blog/detail.html", context)


@login_required
@user_passes_test(lambda u: u.is_staff or u.is_superuser)
def post_quick_create(request):
    if request.method == "POST":
        form = PostQuickForm(request.POST)
        if form.is_valid():
            post = form.save(commit=False)
            post.author = request.user
            post.save()
            messages.success(request, "Đã tạo bài viết. Bạn có thể thêm block nội dung chi tiết.")
            return HttpResponseRedirect(reverse("blog:editor-edit", args=[post.pk]))
    else:
        form = PostQuickForm(initial={"status": Post.Status.DRAFT, "published_at": timezone.now()})
    return render(
        request,
        "blog/create.html",
        {
            "form": form,
            "seo_title": "Tạo bài blog - V+ STEAM LAB Library",
            "seo_description": "Soạn bài blog, đặt lịch xuất bản và thêm block nội dung.",
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
            return HttpResponseBadRequest("Title is required")
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

        messages.success(request, "Đã lưu bài viết. Bạn có thể tiếp tục chỉnh sửa.")
        return HttpResponseRedirect(reverse("blog:editor-edit", args=[post.id]))

    initial_blocks = []
    if post:
        initial_blocks = [b.to_dict() for b in post.blocks.order_by("position", "created_at")]

    context = {
        "post": post,
        "initial_blocks_json": json.dumps(initial_blocks),
        "seo_title": "Chỉnh sửa bài blog" if post else "Tạo bài blog",
        "seo_description": "Soạn bài blog với block nội dung, ảnh, video, gallery.",
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
