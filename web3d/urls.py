from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from . import views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("sitemap.xml", views.sitemap_xml, name="sitemap"),
    path("robots.txt", views.robots_txt, name="robots"),
    path("i18n/", include("django.conf.urls.i18n")),
    path("about/", views.about, name="about"),
    path("contact/", views.contact, name="contact"),
    path("privacy/", views.privacy, name="privacy"),
    path("recaps/", views.recaps, name="recaps"),
    path("accounts/", include("accounts.urls")),
    path("interactions/", include("interactions.urls")),
    path("contributions/", include("contributions.urls")),
    path("", include("library.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
