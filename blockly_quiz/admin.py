from django import forms
from django.conf import settings
from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.db import models
from django.forms import Textarea
from django.http import Http404
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html

from .forms import BulkQuestionImportForm
from .importer import import_questions_into_quiz, parse_bulk_questions
from .models import (
    Attempt,
    AttemptAnswer,
    Choice,
    Classroom,
    ClassroomMembership,
    Question,
    Quiz,
    QuizAssignment,
)


QUESTION_ADMIN_PREVIEW_VENDOR_JS = tuple(
    url
    for url in [
        *getattr(settings, "BLOCKLY_QUIZ_BLOCKLY_JS_URLS", []),
        getattr(settings, "BLOCKLY_QUIZ_SCRATCHBLOCKS_JS_URL", "").strip(),
    ]
    if url
)


class QuestionAdminForm(forms.ModelForm):
    class Meta:
        model = Question
        fields = "__all__"

    class Media:
        css = {"all": ("css/admin_question_preview.css",)}
        js = QUESTION_ADMIN_PREVIEW_VENDOR_JS + ("js/admin_question_preview.js",)


class ChoiceInline(admin.TabularInline):
    model = Choice
    extra = 2


@admin.register(Quiz)
class QuizAdmin(admin.ModelAdmin):
    list_display = ("title", "slug", "is_published", "created_at", "updated_at")
    list_filter = ("is_published",)
    search_fields = ("title", "slug")
    prepopulated_fields = {"slug": ("title",)}
    filter_horizontal = ("allowed_groups",)
    change_form_template = "admin/blockly_quiz/quiz/change_form.html"

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "<int:quiz_id>/import-questions/",
                self.admin_site.admin_view(self.import_questions_view),
                name="blockly_quiz_quiz_import_questions",
            ),
        ]
        return custom_urls + urls

    def import_questions_view(self, request, quiz_id: int):
        quiz = self.get_object(request, quiz_id)
        if not quiz:
            raise Http404
        if not self.has_change_permission(request, obj=quiz):
            raise Http404

        if request.method == "POST":
            form = BulkQuestionImportForm(request.POST)
            if form.is_valid():
                try:
                    questions = parse_bulk_questions(form.cleaned_data["data"])
                    created_questions, created_choices = import_questions_into_quiz(
                        quiz=quiz,
                        questions=questions,
                        replace_existing=form.cleaned_data.get("replace_existing", False),
                    )
                except ValidationError as exc:
                    form.add_error("data", "; ".join(exc.messages) if exc.messages else str(exc))
                else:
                    self.message_user(
                        request,
                        f"Imported {created_questions} questions ({created_choices} choices).",
                        level=messages.SUCCESS,
                    )
                    return redirect(
                        reverse("admin:blockly_quiz_quiz_change", args=(quiz.id,))
                    )
        else:
            form = BulkQuestionImportForm()

        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "quiz": quiz,
            "title": f"Import questions: {quiz.title}",
            "form": form,
        }
        return TemplateResponse(
            request,
            "admin/blockly_quiz/quiz/import_questions.html",
            context,
        )


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    form = QuestionAdminForm
    list_display = ("quiz", "sort_order", "question_type", "difficulty", "short_prompt")
    list_filter = ("quiz", "question_type", "difficulty")
    search_fields = ("=id", "prompt")
    ordering = ("quiz", "sort_order", "id")
    inlines = [ChoiceInline]
    readonly_fields = ("live_preview",)
    fieldsets = (
        (None, {"fields": ("quiz", "sort_order", "question_type", "difficulty", "prompt")}),
        ("Blockly", {"fields": ("blockly_state", "blockly_xml")}),
        ("Scratch", {"fields": ("scratchblocks_text",)}),
        ("Code", {"fields": ("code_language", "code_text")}),
        ("Live preview", {"fields": ("live_preview",)}),
        ("Review", {"fields": ("explanation",)}),
    )
    formfield_overrides = {
        models.TextField: {"widget": Textarea(attrs={"rows": 6})},
    }

    def get_search_results(self, request, queryset, search_term):
        term = (search_term or "").strip()
        if term.isdigit():
            return queryset.filter(pk=int(term)), False
        return super().get_search_results(request, queryset, search_term)

    @admin.display(description="Prompt")
    def short_prompt(self, obj):
        prompt = (obj.prompt or "").strip()
        return prompt if len(prompt) <= 80 else f"{prompt[:77]}..."

    @admin.display(description="Live preview")
    def live_preview(self, obj):
        media_url = getattr(settings, "BLOCKLY_QUIZ_BLOCKLY_MEDIA_URL", "")
        return format_html(
            """
<div class="admin-question-preview" data-admin-question-preview data-blockly-media-url="{0}">
  <p class="help">
    One preview area, auto-rendered from <code>question_type</code> and available data:
    <code>blockly_state</code> (JSON), <code>blockly_xml</code>, <code>scratchblocks_text</code>, or <code>code_text</code>.
  </p>
  <section class="admin-question-preview__card">
    <div class="admin-question-preview__heading">
      <h3 class="admin-question-preview__title">Preview</h3>
      <div class="admin-question-preview__actions">
        <span class="admin-question-preview__badge" data-admin-preview-kind>Auto</span>
        <button type="button" class="button admin-question-preview__refresh" data-admin-preview-refresh>
          Load preview
        </button>
      </div>
    </div>
    <div class="admin-question-preview__note" data-admin-preview-note hidden></div>
    <div class="admin-question-preview__empty" data-admin-preview-empty>
      Enter question data to preview.
    </div>
    <div class="admin-question-preview__surface admin-question-preview__surface--blockly" data-admin-preview-blockly></div>
    <div class="admin-question-preview__surface admin-question-preview__surface--scratch" data-admin-preview-scratch></div>
    <pre class="admin-question-preview__code" data-admin-preview-code><code data-admin-preview-code-text></code></pre>
  </section>
</div>
            """,
            media_url,
        )


class AttemptAnswerInline(admin.TabularInline):
    model = AttemptAnswer
    extra = 0
    readonly_fields = ("question", "selected_choice", "is_correct", "answered_at")
    can_delete = False


@admin.register(Attempt)
class AttemptAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "quiz",
        "user",
        "participant_name",
        "participant_campus",
        "started_at",
        "completed_at",
        "score_percent",
        "correct_count",
        "total_questions",
        "sheets_sent_at",
    )
    list_filter = ("quiz", "completed_at")
    search_fields = (
        "id",
        "participant_name",
        "participant_campus",
        "user__username",
        "user__email",
        "session_key",
    )
    readonly_fields = (
        "quiz",
        "user",
        "session_key",
        "started_at",
        "completed_at",
        "total_questions",
        "correct_count",
        "score_percent",
        "sheets_queued_at",
        "sheets_sent_at",
        "sheets_error",
    )
    inlines = [AttemptAnswerInline]


@admin.register(AttemptAnswer)
class AttemptAnswerAdmin(admin.ModelAdmin):
    list_display = ("attempt", "question", "selected_choice", "is_correct", "answered_at")
    list_filter = ("is_correct", "attempt__quiz")
    search_fields = ("attempt__id", "question__prompt", "selected_choice__text")
    readonly_fields = ("attempt", "question", "selected_choice", "is_correct", "answered_at")


@admin.register(Classroom)
class ClassroomAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "owner", "created_at")
    search_fields = ("name", "slug", "owner__username", "owner__email")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(ClassroomMembership)
class ClassroomMembershipAdmin(admin.ModelAdmin):
    list_display = ("classroom", "user", "role", "joined_at")
    list_filter = ("role",)
    search_fields = ("classroom__name", "user__username", "user__email")


@admin.register(QuizAssignment)
class QuizAssignmentAdmin(admin.ModelAdmin):
    list_display = ("quiz", "classroom", "title", "due_at", "max_attempts", "created_at")
    list_filter = ("classroom", "quiz")
    search_fields = ("quiz__title", "classroom__name", "title")
