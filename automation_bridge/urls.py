from django.urls import path

from . import views

app_name = "automation_bridge"

urlpatterns = [
    path("media/ingest/", views.media_ingest, name="media-ingest"),
    path("blog/publish/", views.blog_publish, name="blog-publish"),
    path("blog/requests/<str:request_id>/", views.blog_request_detail, name="blog-request-detail"),
    path(
        "blog/requests/<str:request_id>/publish/",
        views.blog_request_publish,
        name="blog-request-publish",
    ),
]
