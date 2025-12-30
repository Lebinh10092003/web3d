from collections import defaultdict

from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext as _

from library.models import ContentItem, RecapHeroBanner, RecapVideo


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


def sitemap_xml(request):
    base_url = f"{request.scheme}://{request.get_host()}"
    now = timezone.now()
    urls = [
        {"loc": f"{base_url}{reverse('library:home')}", "lastmod": now},
        {"loc": f"{base_url}{reverse('about')}", "lastmod": now},
        {"loc": f"{base_url}{reverse('contact')}", "lastmod": now},
        {"loc": f"{base_url}{reverse('policies')}", "lastmod": now},
        {"loc": f"{base_url}{reverse('recaps')}", "lastmod": now},
    ]

    items = ContentItem.objects.filter(
        is_public=True, status=ContentItem.Status.PUBLISHED
    ).only("id", "updated_at")
    for item in items:
        urls.append(
            {
                "loc": f"{base_url}{reverse('library:content-detail', args=[item.id])}",
                "lastmod": item.updated_at,
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
