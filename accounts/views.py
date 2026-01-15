import os
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.core.files.storage import default_storage
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.db.models import Count
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _

from contributions.models import ContributionSubmission
from gating.models import Unlock
from interactions.models import Favorite
from library.models import (
    ContentFile,
    ContentItem,
    CourseFavorite,
    CourseLesson,
    CourseLessonProgress,
)

from .forms import ProfileForm, UserRegistrationForm
from .groups import sync_user_role_from_groups


def _is_modal_request(request):
    return request.headers.get("HX-Request") == "true" or request.GET.get("modal") == "1"


def _build_page_query_prefix(request, param_name):
    if not request:
        return ""
    params = request.GET.copy()
    params.pop(param_name, None)
    base = params.urlencode()
    return f"{base}&" if base else ""


def _build_pagination_context(page_obj, param_name, query_prefix=""):
    if not page_obj:
        return {}

    def _url(page_number):
        return f"?{query_prefix}{param_name}={page_number}"

    total = page_obj.paginator.num_pages
    current = page_obj.number
    pages = []

    def _add(num):
        pages.append(
            {
                "number": num,
                "url": _url(num),
                "is_current": num == current,
            }
        )

    # Cap at 3 numbered pages
    if total <= 3:
        for num in page_obj.paginator.page_range:
            _add(num)
    else:
        start = max(1, current - 1)
        end = min(total, start + 2)
        start = max(1, end - 2)
        if start > 1:
            pages.append({"ellipsis": True})
        for num in range(start, end + 1):
            _add(num)
        if end < total:
            pages.append({"ellipsis": True})

    return {
        "has_prev": page_obj.has_previous(),
        "has_next": page_obj.has_next(),
        "prev_url": _url(page_obj.previous_page_number()) if page_obj.has_previous() else "",
        "next_url": _url(page_obj.next_page_number()) if page_obj.has_next() else "",
        "pages": pages,
    }


def _upload_avatar(file_obj, user_id):
    safe_name = os.path.basename(getattr(file_obj, "name", "avatar"))
    timestamp = timezone.now().strftime("%Y%m%d_%H%M%S")
    storage_path = f"avatars/{user_id}/{timestamp}_{safe_name}"
    saved_path = default_storage.save(storage_path, file_obj)
    return default_storage.url(saved_path)


def _attach_previews(contents):
    content_ids = [content.id for content in contents if content]
    if not content_ids:
        return
    preview_files = (
        ContentFile.objects.filter(
            content_id__in=content_ids,
            kind=ContentFile.FileKind.PREVIEW,
        )
        .only("content_id", "storage_path")
        .order_by("content_id")
    )
    preview_map = {}
    for preview_file in preview_files:
        preview_map.setdefault(preview_file.content_id, preview_file)
    for content in contents:
        preview_file = preview_map.get(content.id)
        if preview_file:
            try:
                content.preview_url = preview_file.get_signed_url()
                continue
            except Exception:
                content.preview_url = ""
        else:
            content.preview_url = ""


def _build_profile_lists(user):
    unlocks = (
        Unlock.objects.filter(user=user)
        .select_related("content")
        .order_by("-created_at")[:5]
    )
    submissions = list(
        ContributionSubmission.objects.filter(user=user)
        .order_by("-created_at")[:5]
    )
    submission_paths = [s.file_path for s in submissions if s.file_path]
    content_by_path = {}
    if submission_paths:
        sources = (
            ContentFile.objects.filter(
                storage_path__in=submission_paths,
                kind=ContentFile.FileKind.SOURCE,
            )
            .select_related("content")
            .only("storage_path", "content_id", "content")
        )
        for source in sources:
            content_by_path[source.storage_path] = source.content
    for submission in submissions:
        submission.published_content = content_by_path.get(submission.file_path)
    own_content = ContentItem.objects.filter(owner=user).order_by("-created_at")[:5]
    favorites = (
        Favorite.objects.filter(user=user)
        .select_related("content")
        .order_by("-created_at")[:5]
    )
    content_pool = {}
    for unlock in unlocks:
        content_pool[unlock.content_id] = unlock.content
    for favorite in favorites:
        content_pool[favorite.content_id] = favorite.content
    for item in own_content:
        content_pool[item.id] = item
    for submission in submissions:
        if submission.published_content:
            content_pool[submission.published_content.id] = submission.published_content
    _attach_previews(list(content_pool.values()))

    return {
        "unlocks": unlocks,
        "submissions": submissions,
        "own_content": own_content,
        "favorites": favorites,
    }


def _build_course_overview(user, *, request=None, per_page=5, page_param="lesson_page"):
    course_favorites = (
        CourseFavorite.objects.filter(user=user, course__is_published=True)
        .select_related("course")
        .order_by("-created_at")
    )
    favorite_courses = [favorite.course for favorite in course_favorites]
    recent_lessons_qs = (
        CourseLessonProgress.objects.filter(
            user=user, last_watched_at__isnull=False
        )
        .select_related("lesson__course")
        .order_by("-last_watched_at")
    )
    paginator = Paginator(recent_lessons_qs, per_page)
    page_number = request.GET.get(page_param) if request else 1
    recent_lessons_page = paginator.get_page(page_number)
    recent_lessons = list(recent_lessons_page)

    course_ids = {
        progress.lesson.course_id for progress in recent_lessons if progress.lesson_id
    }
    course_ids.update(course.id for course in favorite_courses if course)
    course_stats = {}
    if course_ids:
        totals = (
            CourseLesson.objects.filter(course_id__in=course_ids)
            .values("course_id")
            .annotate(total=Count("id"))
        )
        completed = (
            CourseLessonProgress.objects.filter(
                user=user,
                lesson__course_id__in=course_ids,
                is_completed=True,
            )
            .values("lesson__course_id")
            .annotate(total=Count("id"))
        )
        total_map = {row["course_id"]: row["total"] for row in totals}
        completed_map = {row["lesson__course_id"]: row["total"] for row in completed}
        for course_id in course_ids:
            total = total_map.get(course_id, 0)
            done = completed_map.get(course_id, 0)
            percent = int((done / total) * 100) if total else 0
            course_stats[course_id] = {
                "total": total,
                "completed": done,
                "percent": percent,
            }

    for course in favorite_courses:
        course.progress = course_stats.get(course.id, {"total": 0, "completed": 0, "percent": 0})

    page_query_prefix = _build_page_query_prefix(request, page_param)
    pagination = _build_pagination_context(recent_lessons_page, page_param, page_query_prefix)

    return (
        favorite_courses,
        recent_lessons,
        course_stats,
        recent_lessons_page,
        page_query_prefix,
        pagination,
    )


def register(request):
    if request.method == "POST":
        form = UserRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            sync_user_role_from_groups(user)
            login(request, user)
            messages.success(request, _("Welcome to V+ STEAM LAB Library."))
            if request.headers.get("HX-Request") == "true":
                response = HttpResponse("")
                response["HX-Redirect"] = reverse("library:home")
                return response
            return redirect("library:home")
    else:
        form = UserRegistrationForm()

    return render(request, "accounts/register_modal.html", {"form": form})


@login_required
def profile(request):
    valid_sections = {"personal", "public", "favorites", "courses"}
    section = request.GET.get("section", "personal")
    if section not in valid_sections:
        section = "personal"

    if request.method == "POST":
        form = ProfileForm(request.POST, request.FILES, instance=request.user)
        if form.is_valid():
            user = form.save(commit=False)
            upload = form.cleaned_data.get("file_upload")
            if upload:
                try:
                    upload.seek(0)
                    user.avatar_path = _upload_avatar(upload, user.id)
                except Exception as exc:
                    form.add_error(
                        None,
                        _("Avatar upload failed: %(error)s") % {"error": exc},
                    )
                    context = _build_profile_lists(request.user)
                    (
                        favorite_courses,
                        recent_lessons,
                        course_stats,
                        recent_lessons_page,
                        lesson_page_query_prefix,
                        lesson_pagination,
                    ) = _build_course_overview(request.user, request=request)
                    context.update(
                        {
                            "form": form,
                            "section": section,
                            "favorite_courses": favorite_courses,
                            "recent_lessons": recent_lessons,
                            "recent_lessons_page": recent_lessons_page,
                            "lesson_page_query_prefix": lesson_page_query_prefix,
                            "lesson_pagination": lesson_pagination,
                            "course_stats": course_stats,
                        }
                    )
                    return render(request, "accounts/profile.html", context)
            user.save()
            messages.success(request, _("Profile updated."))
            return redirect(f"{reverse('accounts:profile')}?section=personal")
    else:
        form = ProfileForm(instance=request.user)

    context = _build_profile_lists(request.user)
    (
        favorite_courses,
        recent_lessons,
        course_stats,
        recent_lessons_page,
        lesson_page_query_prefix,
        lesson_pagination,
    ) = _build_course_overview(request.user, request=request)
    context.update(
        {
            "form": form,
            "section": section,
            "favorite_courses": favorite_courses,
            "recent_lessons": recent_lessons,
            "recent_lessons_page": recent_lessons_page,
            "lesson_page_query_prefix": lesson_page_query_prefix,
            "lesson_pagination": lesson_pagination,
            "course_stats": course_stats,
        }
    )
    return render(request, "accounts/profile.html", context)


@login_required
def profile_section(request, section):
    valid_sections = {"personal", "public", "favorites", "courses"}
    if section not in valid_sections:
        section = "personal"

    form = None
    is_htmx = request.headers.get("HX-Request") == "true"
    if section == "personal":
        if request.method == "POST":
            form = ProfileForm(request.POST, request.FILES, instance=request.user)
            if form.is_valid():
                user = form.save(commit=False)
                upload = form.cleaned_data.get("file_upload")
                if upload:
                    try:
                        upload.seek(0)
                        user.avatar_path = _upload_avatar(upload, user.id)
                    except Exception as exc:
                        form.add_error(
                            None,
                            _("Avatar upload failed: %(error)s") % {"error": exc},
                        )
                        context = _build_profile_lists(request.user)
                        context.update({"form": form, "section": section})
                        return render(request, "accounts/profile_modal.html", context)
                user.save()
                messages.success(request, _("Profile updated."))
                form = ProfileForm(instance=request.user)
        else:
            form = ProfileForm(instance=request.user)
    elif request.method == "POST" and not is_htmx:
        return redirect(f"{reverse('accounts:profile')}?section={section}")

    if not is_htmx:
        return redirect(f"{reverse('accounts:profile')}?section={section}")

    (
        favorite_courses,
        recent_lessons,
        course_stats,
        recent_lessons_page,
        lesson_page_query_prefix,
        lesson_pagination,
    ) = _build_course_overview(request.user, request=request)
    context = _build_profile_lists(request.user)
    context.update(
        {
            "section": section,
            "form": form,
            "favorite_courses": favorite_courses,
            "recent_lessons": recent_lessons,
            "recent_lessons_page": recent_lessons_page,
            "lesson_page_query_prefix": lesson_page_query_prefix,
            "lesson_pagination": lesson_pagination,
            "course_stats": course_stats,
        }
    )
    return render(request, "accounts/profile_modal.html", context)


@login_required
def my_library(request):
    favorites = (
        Favorite.objects.filter(user=request.user)
        .select_related("content")
        .order_by("-created_at")
    )
    favorite_contents = [favorite.content for favorite in favorites]
    _attach_previews(favorite_contents)

    (
        favorite_courses,
        recent_lessons,
        course_stats,
        recent_lessons_page,
        lesson_page_query_prefix,
        lesson_pagination,
    ) = _build_course_overview(request.user, request=request, per_page=5)
    context = {
        "favorite_contents": favorite_contents,
        "favorite_courses": favorite_courses,
        "recent_lessons": recent_lessons,
        "recent_lessons_page": recent_lessons_page,
        "lesson_page_query_prefix": lesson_page_query_prefix,
        "lesson_pagination": lesson_pagination,
        "course_stats": course_stats,
    }
    return render(request, "accounts/my_library.html", context)

class ModalLoginView(LoginView):
    def get_template_names(self):
        if _is_modal_request(self.request):
            return ["accounts/login_modal.html"]
        return ["accounts/login_page.html"]

    def render_to_response(self, context, **response_kwargs):
        response = super().render_to_response(context, **response_kwargs)
        if _is_modal_request(self.request):
            response["HX-Retarget"] = "#auth-modal-body"
            response["HX-Reswap"] = "innerHTML"
        return response

    def form_valid(self, form):
        response = super().form_valid(form)
        if _is_modal_request(self.request):
            redirect_to = self.get_success_url()
            hx_response = HttpResponse("")
            hx_response["HX-Redirect"] = redirect_to
            return hx_response
        return response
