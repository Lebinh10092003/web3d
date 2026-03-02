from collections import defaultdict

from django.contrib.auth.decorators import login_required
from django.db.models import Prefetch
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from library.models import (
    ContentItem,
    Course,
    CourseFavorite,
    CourseLesson,
    CourseLessonProgress,
    RecapHeroBanner,
    RecapVideo,
    _normalize_youtube_id,
)


def about(request):
    return render(request, "pages/about.html")


def contact(request):
    return render(request, "pages/contact.html")


def privacy(request):
    return redirect(f"{reverse('policies')}?tab=privacy")

def policies(request):
    return render(request, "pages/policies.html")

def terms(request):
    return redirect(f"{reverse('policies')}?tab=terms")


def payment_policy(request):
    return redirect(f"{reverse('policies')}?tab=payment")


def refund_policy(request):
    return redirect(f"{reverse('policies')}?tab=refund")


def delivery_policy(request):
    return redirect(f"{reverse('policies')}?tab=delivery")


def complaint_policy(request):
    return redirect(f"{reverse('policies')}?tab=complaints")


def courses(request):
    courses_qs = Course.objects.filter(is_published=True).order_by(
        "sort_order", "title"
    )
    courses_qs = courses_qs.prefetch_related(
        Prefetch("lessons", queryset=CourseLesson.objects.order_by("sort_order", "id"))
    )
    favorite_ids = set()
    if request.user.is_authenticated:
        favorite_ids = set(
            CourseFavorite.objects.filter(user=request.user, course__in=courses_qs)
            .values_list("course_id", flat=True)
            .distinct()
        )
    courses = []
    for course in courses_qs:
        lessons = list(course.lessons.all())
        preview_video_id = course.featured_video_id
        if not preview_video_id:
            preview_video_id = next(
                (lesson.video_id for lesson in lessons if lesson.video_id), ""
            )
        courses.append(
            {
                "course": course,
                "lessons": lessons,
                "preview_embed_url": course.get_video_embed_url(preview_video_id),
                "is_favorite": course.id in favorite_ids,
            }
        )
    context = {
        "course_playlists": courses,
        "canonical_url": request.build_absolute_uri(request.path),
    }
    return render(request, "pages/courses.html", context)


def course_detail(request, slug):
    course = get_object_or_404(
        Course.objects.prefetch_related(
            Prefetch("lessons", queryset=CourseLesson.objects.order_by("sort_order", "id"))
        ),
        slug=slug,
        is_published=True,
    )
    lessons = list(course.lessons.all())
    selected = _normalize_youtube_id(request.GET.get("v"))
    lesson_video_ids = [lesson.video_id for lesson in lessons if lesson.video_id]
    if selected and selected not in lesson_video_ids:
        selected = ""
    active_video_id = (
        selected
        or course.featured_video_id
        or next((vid for vid in lesson_video_ids if vid), "")
    )
    progress_map = {}
    if request.user.is_authenticated:
        progress_qs = CourseLessonProgress.objects.filter(
            user=request.user, lesson__in=lessons
        ).select_related("lesson")
        progress_map = {progress.lesson_id: progress for progress in progress_qs}
        if active_video_id:
            active_lesson = next(
                (lesson for lesson in lessons if lesson.video_id == active_video_id),
                None,
            )
            if active_lesson:
                progress, _ = CourseLessonProgress.objects.get_or_create(
                    user=request.user, lesson=active_lesson
                )
                progress.last_watched_at = timezone.now()
                progress.save(update_fields=["last_watched_at", "updated_at"])

    lesson_rows = []
    for lesson in lessons:
        progress = progress_map.get(lesson.id)
        lesson_rows.append(
            {
                "lesson": lesson,
                "is_completed": bool(progress and progress.is_completed),
                "is_active": bool(
                    lesson.video_id and lesson.video_id == active_video_id
                ),
            }
        )
    is_favorite = False
    if request.user.is_authenticated:
        is_favorite = CourseFavorite.objects.filter(
            user=request.user, course=course
        ).exists()
    context = {
        "course": course,
        "lesson_rows": lesson_rows,
        "active_video_id": active_video_id,
        "active_embed_url": course.get_video_embed_url(active_video_id),
        "is_favorite": is_favorite,
        "canonical_url": request.build_absolute_uri(request.path),
    }
    return render(request, "pages/course_detail.html", context)


@login_required
@require_POST
def course_lesson_toggle(request, slug, lesson_id):
    course = get_object_or_404(Course, slug=slug, is_published=True)
    lesson = get_object_or_404(CourseLesson, pk=lesson_id, course=course)
    progress, _ = CourseLessonProgress.objects.get_or_create(
        user=request.user, lesson=lesson
    )
    progress.is_completed = not progress.is_completed
    if not progress.last_watched_at:
        progress.last_watched_at = timezone.now()
    progress.save(update_fields=["is_completed", "last_watched_at", "updated_at"])
    next_url = request.POST.get("next") or course.get_absolute_url()
    return redirect(next_url)


@login_required
@require_POST
def course_favorite_toggle(request, slug):
    course = get_object_or_404(Course, slug=slug, is_published=True)
    favorite = CourseFavorite.objects.filter(user=request.user, course=course).first()
    if favorite:
        favorite.delete()
    else:
        CourseFavorite.objects.create(user=request.user, course=course)
    next_url = request.POST.get("next") or course.get_absolute_url()
    return redirect(next_url)


def _load_recaps():
    recaps = []
    items = (
        RecapVideo.objects.filter(is_published=True)
        .only(
            "competition",
            "competition_slug",
            "year",
            "video_id",
            "video_provider",
            "title",
            "summary",
        )
    )
    for item in items:
        competition_label = (item.competition or "").strip()
        if not competition_label:
            competition_label = _("Competition")
        competition_slug = (
            (item.competition_slug or slugify(competition_label) or "competition").strip()
        )
        recaps.append(
            {
                "competition": competition_slug,
                "competition_label": competition_label,
                "year": item.year,
                "video_id": (item.video_id or "").strip(),
                "video_provider": item.video_provider,
                "video_embed_url": item.get_embed_url(),
                "video_watch_url": item.get_watch_url(),
                "title": (item.title or f"{competition_label} {item.year} recap").strip(),
                "summary": (item.summary or "").strip(),
            }
        )
    return recaps


def recaps(request):
    recaps = _load_recaps()
    competitions = []
    seen_competitions = set()
    years_by_competition = defaultdict(set)
    for recap in recaps:
        comp = recap["competition"]
        if comp not in seen_competitions:
            competitions.append(
                {
                    "slug": comp,
                    "label": recap["competition_label"],
                }
            )
            seen_competitions.add(comp)
        if recap["year"] is not None:
            years_by_competition[comp].add(recap["year"])

    years_by_competition = {
        comp: sorted(years, reverse=True) for comp, years in years_by_competition.items()
    }

    default_competition = competitions[0]["slug"] if competitions else ""
    default_year = (
        years_by_competition.get(default_competition, [None])[0]
        if default_competition
        else None
    )
    initial_years = years_by_competition.get(default_competition, [])
    initial_recap = None
    for recap in recaps:
        if (
            recap["competition"] == default_competition
            and recap["year"] == default_year
        ):
            initial_recap = recap
            break

    order_map = {item["slug"]: idx for idx, item in enumerate(competitions)}
    recaps_sorted = sorted(
        recaps,
        key=lambda item: (
            order_map.get(item["competition"], 0),
            item["year"] is None,
            -(item["year"] or 0),
            item["title"],
        ),
    )

    default_intro_title = _("Recap library")
    default_intro_body = _(
        "Choose a competition and year to watch the recap and revisit past seasons."
    )
    default_intro_eyebrow = _("Recap Library")
    recap_banner = (
        RecapHeroBanner.objects.filter(is_active=True)
        .only("title", "body", "eyebrow", "background_image", "updated_at")
        .first()
    )
    recap_intro_title = default_intro_title
    recap_intro_body = default_intro_body
    recap_intro_eyebrow = default_intro_eyebrow
    if recap_banner:
        banner_title = (recap_banner.title or "").strip()
        banner_body = (recap_banner.body or "").strip()
        banner_eyebrow = (recap_banner.eyebrow or "").strip()
        if banner_title:
            recap_intro_title = banner_title
        if banner_body:
            recap_intro_body = banner_body
        if banner_eyebrow:
            recap_intro_eyebrow = banner_eyebrow

    context = {
        "competitions": competitions,
        "years_by_competition": years_by_competition,
        "recaps": recaps_sorted,
        "initial_recap": initial_recap,
        "initial_years": initial_years,
        "canonical_url": request.build_absolute_uri(request.path),
        "recap_banner": recap_banner,
        "recap_intro_title": recap_intro_title,
        "recap_intro_body": recap_intro_body,
        "recap_intro_eyebrow": recap_intro_eyebrow,
    }
    return render(request, "pages/recaps.html", context)


def _build_main_sitemap_urls(request):
    base_url = f"{request.scheme}://{request.get_host()}"
    now = timezone.now()
    urls = [
        {"loc": f"{base_url}{reverse('library:home')}", "lastmod": now},
        {"loc": f"{base_url}{reverse('about')}", "lastmod": now},
        {"loc": f"{base_url}{reverse('contact')}", "lastmod": now},
        {"loc": f"{base_url}{reverse('policies')}", "lastmod": now},
        {"loc": f"{base_url}{reverse('courses')}", "lastmod": now},
        {"loc": f"{base_url}{reverse('recaps')}", "lastmod": now},
    ]

    items = (
        ContentItem.objects.filter(is_public=True, status=ContentItem.Status.PUBLISHED)
        .filter(allowed_groups__isnull=True)
        .only("id", "updated_at")
    )
    for item in items:
        urls.append(
            {
                "loc": f"{base_url}{reverse('library:content-detail', args=[item.id])}",
                "lastmod": item.updated_at,
            }
        )

    courses = Course.objects.filter(is_published=True).only("slug", "updated_at")
    for course in courses:
        urls.append(
            {
                "loc": f"{base_url}{reverse('course-detail', args=[course.slug])}",
                "lastmod": course.updated_at,
            }
        )

    return urls


def sitemap_xml(request):
    base_url = f"{request.scheme}://{request.get_host()}"
    sitemaps = [
        {"loc": f"{base_url}{reverse('sitemap-main')}", "lastmod": timezone.now()},
        {"loc": f"{base_url}{reverse('sitemap-blog')}", "lastmod": timezone.now()},
    ]
    return render(
        request,
        "sitemap_index.xml",
        {"sitemaps": sitemaps},
        content_type="application/xml",
    )


def sitemap_main_xml(request):
    urls = _build_main_sitemap_urls(request)
    return render(request, "sitemap.xml", {"urls": urls}, content_type="application/xml")


def sitemap_blog_xml(request):
    from blog.models import Post

    base_url = f"{request.scheme}://{request.get_host()}"
    urls = []
    posts = Post.objects.live().only("slug", "updated_at", "published_at")
    for post in posts:
        urls.append(
            {
                "loc": f"{base_url}{reverse('blog:detail', args=[post.slug])}",
                "lastmod": post.updated_at or post.published_at,
            }
        )

    return render(request, "sitemap.xml", {"urls": urls}, content_type="application/xml")


def robots_txt(request):
    sitemap_url = request.build_absolute_uri("/sitemap.xml")
    lines = [
        "User-agent: *",
        "Allow: /",
        f"Sitemap: {sitemap_url}",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain")
