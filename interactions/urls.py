from django.urls import path

from . import views

app_name = "interactions"

urlpatterns = [
    path("content/<int:pk>/comment/", views.add_comment, name="comment"),
    path(
        "content/<int:pk>/comment/<int:comment_id>/edit/",
        views.edit_comment,
        name="comment-edit",
    ),
    path(
        "content/<int:pk>/comment/<int:comment_id>/delete/",
        views.delete_comment,
        name="comment-delete",
    ),
    path("content/<int:pk>/rate/", views.rate_content, name="rate"),
    path("content/<int:pk>/favorite/", views.toggle_favorite, name="favorite"),
]
