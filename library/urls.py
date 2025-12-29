from django.urls import path

from . import views

app_name = "library"

urlpatterns = [
    path("", views.home, name="home"),
    path("ldraw/", views.ldraw_index, name="ldraw-index"),
    path("ldraw/<path:relative_path>", views.ldraw_asset, name="ldraw-asset"),
    path("protected-media/<path:blob_path>", views.protected_media, name="protected-media"),
    path("content/<int:pk>/", views.content_detail, name="content-detail"),
    path("content/<int:pk>/model.ldr", views.content_lego_model, name="content-lego-model"),
    path("content/<int:pk>/preview/", views.content_preview_image, name="content-preview"),
    path("content/<int:pk>/download/", views.content_download, name="content-download"),
]
