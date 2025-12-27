from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Count
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from library.models import ContentItem

from .forms import CommentForm, RatingForm
from .models import Comment, Favorite, Rating


def _get_comments(content):
    return list(
        Comment.objects.filter(content=content, parent__isnull=True)
        .select_related("user")
        .prefetch_related("replies__user")
    )


def _render_comment_list(request, content, comments, edit_form=None, editing_comment_id=None):
    context = {
        "content": content,
        "comments": comments,
        "edit_form": edit_form,
        "editing_comment_id": editing_comment_id,
    }
    if request.headers.get("HX-Request") == "true":
        return render(request, "interactions/_comment_list.html", context)
    return redirect("library:content-detail", pk=content.id)


def _can_manage_comment(user, comment):
    return user.is_authenticated and (user.is_staff or comment.user_id == user.id)


@require_POST
@login_required
def add_comment(request, pk):
    content = get_object_or_404(ContentItem, pk=pk, is_public=True)
    form = CommentForm(request.POST)
    if form.is_valid():
        parent = None
        parent_id = form.cleaned_data.get("parent_id")
        if parent_id:
            parent = Comment.objects.filter(id=parent_id, content=content).first()
        Comment.objects.create(
            content=content,
            user=request.user,
            body=form.cleaned_data["body"],
            parent=parent,
        )
    else:
        messages.error(request, _("Comment could not be saved."))

    comments = _get_comments(content)
    return _render_comment_list(request, content, comments)


@login_required
def edit_comment(request, pk, comment_id):
    content = get_object_or_404(ContentItem, pk=pk, is_public=True)
    comment = get_object_or_404(Comment, pk=comment_id, content=content)
    if not _can_manage_comment(request.user, comment) or comment.is_deleted:
        return HttpResponse(status=403)

    if request.method == "POST":
        form = CommentForm(request.POST)
        if form.is_valid():
            comment.body = form.cleaned_data["body"]
            comment.save(update_fields=["body", "updated_at"])
        else:
            messages.error(request, _("Comment could not be updated."))
            comments = _get_comments(content)
            return _render_comment_list(
                request, content, comments, edit_form=form, editing_comment_id=comment.id
            )
        comments = _get_comments(content)
        return _render_comment_list(request, content, comments)

    if request.GET.get("cancel") == "1":
        comments = _get_comments(content)
        return _render_comment_list(request, content, comments)

    form = CommentForm(initial={"body": comment.body})
    comments = _get_comments(content)
    return _render_comment_list(
        request, content, comments, edit_form=form, editing_comment_id=comment.id
    )


@require_POST
@login_required
def delete_comment(request, pk, comment_id):
    content = get_object_or_404(ContentItem, pk=pk, is_public=True)
    comment = get_object_or_404(Comment, pk=comment_id, content=content)
    if not _can_manage_comment(request.user, comment) or comment.is_deleted:
        return HttpResponse(status=403)

    comment.is_deleted = True
    comment.save(update_fields=["is_deleted", "updated_at"])
    comments = _get_comments(content)
    return _render_comment_list(request, content, comments)


@require_POST
@login_required
def rate_content(request, pk):
    content = get_object_or_404(ContentItem, pk=pk, is_public=True)
    form = RatingForm(request.POST)
    if form.is_valid():
        Rating.objects.update_or_create(
            content=content,
            user=request.user,
            defaults={"score": int(form.cleaned_data["score"])},
        )
    else:
        messages.error(request, _("Rating could not be saved."))

    rating_stats = content.ratings.aggregate(avg=Avg("score"), count=Count("id"))
    user_rating = Rating.objects.filter(content=content, user=request.user).first()

    context = {
        "content": content,
        "rating_avg": rating_stats["avg"],
        "rating_count": rating_stats["count"],
        "user_rating": user_rating,
        "stars": [5, 4, 3, 2, 1],
    }

    if request.headers.get("HX-Request") == "true":
        return render(request, "interactions/_rating_widget.html", context)
    return redirect("library:content-detail", pk=pk)


@require_POST
@login_required
def toggle_favorite(request, pk):
    content = get_object_or_404(ContentItem, pk=pk, is_public=True)
    favorite = Favorite.objects.filter(content=content, user=request.user).first()
    if favorite:
        favorite.delete()
        is_favorited = False
    else:
        Favorite.objects.create(content=content, user=request.user)
        is_favorited = True

    favorites_count = content.favorites.count()
    context = {
        "content": content,
        "is_favorited": is_favorited,
        "favorites_count": favorites_count,
    }

    if request.headers.get("HX-Request") == "true":
        return render(request, "interactions/_favorite_button.html", context)
    return redirect("library:content-detail", pk=pk)
