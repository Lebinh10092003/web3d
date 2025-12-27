from django.urls import path

from . import views

app_name = "library"

urlpatterns = [
    path("", views.home, name="home"),
    path("content/<int:pk>/", views.content_detail, name="content-detail"),
    path("content/<int:pk>/preview/", views.content_preview_image, name="content-preview"),
    path("content/<int:pk>/download/", views.content_download, name="content-download"),
]
