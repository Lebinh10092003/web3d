from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.templatetags.static import static as static_url
from django.urls import include, path
from django.views.generic.base import RedirectView

from . import views

FAVICON_URL = static_url("img/logoV+.png").replace("%", "%%")

urlpatterns = [
    path("admin/", admin.site.urls),
    path(
        "favicon.ico",
        RedirectView.as_view(url=FAVICON_URL, permanent=True),
    ),
    path("sitemap.xml", views.sitemap_xml, name="sitemap"),
    path("robots.txt", views.robots_txt, name="robots"),
    path("i18n/", include("django.conf.urls.i18n")),
    path("about/", views.about, name="about"),
    path("contact/", views.contact, name="contact"),
    path("privacy/", views.privacy, name="privacy"),
    path("courses/", views.courses, name="courses"),
    path("recaps/", views.recaps, name="recaps"),
    path("accounts/", include("accounts.urls")),
    path("interactions/", include("interactions.urls")),
    path("contributions/", include("contributions.urls")),
    path("payments/", include("gating.urls")),
    path("", include("library.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
