import os
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.core.files.storage import default_storage
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _

from contributions.models import ContributionSubmission
from gating.models import Unlock
from interactions.models import Favorite
from library.models import ContentFile, ContentItem

from .forms import ProfileForm, UserRegistrationForm


def _is_modal_request(request):
    return request.headers.get("HX-Request") == "true" or request.GET.get("modal") == "1"


def _upload_avatar(file_obj, user_id):
    safe_name = os.path.basename(getattr(file_obj, "name", "avatar"))
    timestamp = timezone.now().strftime("%Y%m%d_%H%M%S")
    storage_path = f"avatars/{user_id}/{timestamp}_{safe_name}"
    saved_path = default_storage.save(storage_path, file_obj)
    return default_storage.url(saved_path)


def _attach_previews(contents):
    content_ids = [content.id for content in contents if content]
    if not content_ids:
        return
    preview_files = (
        ContentFile.objects.filter(
            content_id__in=content_ids,
            kind=ContentFile.FileKind.PREVIEW,
        )
        .only("content_id", "storage_path")
        .order_by("content_id")
    )
    preview_map = {}
    for preview_file in preview_files:
        preview_map.setdefault(preview_file.content_id, preview_file)
    for content in contents:
        preview_file = preview_map.get(content.id)
        if preview_file:
            try:
                content.preview_url = preview_file.get_signed_url()
                continue
            except Exception:
                content.preview_url = ""
        else:
            content.preview_url = ""


def register(request):
    if request.method == "POST":
        form = UserRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, _("Welcome to V+ STEAM LAB Library."))
            if request.headers.get("HX-Request") == "true":
                response = HttpResponse("")
                response["HX-Redirect"] = reverse("library:home")
                return response
            return redirect("library:home")
    else:
        form = UserRegistrationForm()

    return render(request, "accounts/register_modal.html", {"form": form})


@login_required
def profile(request):
    if request.method == "POST":
        form = ProfileForm(request.POST, request.FILES, instance=request.user)
        if form.is_valid():
            user = form.save(commit=False)
            upload = form.cleaned_data.get("file_upload")
            if upload:
                try:
                    upload.seek(0)
                    user.avatar_path = _upload_avatar(upload, user.id)
                except Exception as exc:
                    messages.error(
                        request, _("Avatar upload failed: %(error)s") % {"error": exc}
                    )
                    return render(request, "accounts/profile.html", {"form": form})
            user.save()
            messages.success(request, _("Profile updated."))
            return redirect("accounts:profile")
    else:
        form = ProfileForm(instance=request.user)

    unlocks = (
        Unlock.objects.filter(user=request.user)
        .select_related("content")
        .order_by("-created_at")[:5]
    )
    submissions = list(
        ContributionSubmission.objects.filter(user=request.user)
        .order_by("-created_at")[:5]
    )
    submission_paths = [s.file_path for s in submissions if s.file_path]
    content_by_path = {}
    if submission_paths:
        sources = (
            ContentFile.objects.filter(
                storage_path__in=submission_paths,
                kind=ContentFile.FileKind.SOURCE,
            )
            .select_related("content")
            .only("storage_path", "content_id", "content")
        )
        for source in sources:
            content_by_path[source.storage_path] = source.content
    for submission in submissions:
        submission.published_content = content_by_path.get(submission.file_path)
    own_content = (
        ContentItem.objects.filter(owner=request.user).order_by("-created_at")[:5]
    )
    favorites = (
        Favorite.objects.filter(user=request.user)
        .select_related("content")
        .order_by("-created_at")[:5]
    )
    content_pool = {}
    for unlock in unlocks:
        content_pool[unlock.content_id] = unlock.content
    for favorite in favorites:
        content_pool[favorite.content_id] = favorite.content
    for item in own_content:
        content_pool[item.id] = item
    for submission in submissions:
        if submission.published_content:
            content_pool[submission.published_content.id] = submission.published_content
    _attach_previews(list(content_pool.values()))

    context = {
        "form": form,
        "unlocks": unlocks,
        "submissions": submissions,
        "own_content": own_content,
        "favorites": favorites,
    }
    return render(request, "accounts/profile.html", context)


class ModalLoginView(LoginView):
    def get_template_names(self):
        if _is_modal_request(self.request):
            return ["accounts/login_modal.html"]
        return ["accounts/login_page.html"]

    def render_to_response(self, context, **response_kwargs):
        response = super().render_to_response(context, **response_kwargs)
        if _is_modal_request(self.request):
            response["HX-Retarget"] = "#auth-modal-body"
            response["HX-Reswap"] = "innerHTML"
        return response

    def form_valid(self, form):
        response = super().form_valid(form)
        if _is_modal_request(self.request):
            redirect_to = self.get_success_url()
            hx_response = HttpResponse("")
            hx_response["HX-Redirect"] = redirect_to
            return hx_response
        return response
