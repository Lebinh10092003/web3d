from django.urls import path

from . import views

app_name = "blog"

urlpatterns = [
    path("", views.post_list, name="list"),
    path("create/", views.post_quick_create, name="create"),
    path("editor/", views.post_editor_new, name="editor-new"),
    path("editor/<uuid:post_id>/", views.post_editor_edit, name="editor-edit"),
    path("upload/", views.upload_media, name="upload-media"),
    path("<slug:slug>/comment/", views.add_comment, name="comment"),
    path(
        "<slug:slug>/comment/<int:comment_id>/edit/",
        views.edit_comment,
        name="comment-edit",
    ),
    path(
        "<slug:slug>/comment/<int:comment_id>/delete/",
        views.delete_comment,
        name="comment-delete",
    ),
    path("<slug:slug>/", views.post_detail, name="detail"),
]
