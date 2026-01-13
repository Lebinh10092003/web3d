import json
import random

from django.conf import settings
from django.contrib import messages
from django.db.models import Exists, OuterRef, Q
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from .models import Attempt, AttemptAnswer, Choice, Question, Quiz


def _with_quiz_type_flags(quizzes):
    blockly_exists = Question.objects.filter(quiz=OuterRef("pk"), question_type="blockly")
    scratch_exists = Question.objects.filter(quiz=OuterRef("pk"), question_type="scratch")
    code_exists = Question.objects.filter(quiz=OuterRef("pk"), question_type="code")
    return quizzes.annotate(
        has_blockly=Exists(blockly_exists),
        has_scratch=Exists(scratch_exists),
        has_code=Exists(code_exists),
    )


def _ensure_session_key(request) -> str:
    session_key = request.session.session_key
    if session_key:
        return session_key
    request.session.save()
    return request.session.session_key or ""


def _get_attempt_or_404(request, attempt_id: int) -> Attempt:
    attempt = get_object_or_404(
        Attempt.objects.select_related("quiz", "user"),
        pk=attempt_id,
    )
    if attempt.user_id:
        if not request.user.is_authenticated or attempt.user_id != request.user.id:
            raise Http404
        return attempt

    session_key = _ensure_session_key(request)
    if not attempt.session_key or attempt.session_key != session_key:
        raise Http404
    return attempt


def _finalize_attempt(attempt: Attempt, *, total_questions_override: int | None = None) -> Attempt:
    if attempt.completed_at:
        return attempt
    if total_questions_override is None:
        total = Question.objects.filter(quiz=attempt.quiz).count()
    else:
        try:
            total = int(total_questions_override)
        except (TypeError, ValueError):
            total = 0
        if total < 0:
            total = 0
    correct = AttemptAnswer.objects.filter(attempt=attempt, is_correct=True).count()
    attempt.total_questions = total
    attempt.correct_count = correct
    attempt.score_percent = int((correct / total) * 100) if total else 0
    attempt.completed_at = timezone.now()
    attempt.save(
        update_fields=[
            "total_questions",
            "correct_count",
            "score_percent",
            "completed_at",
        ]
    )
    if (
        getattr(settings, "BLOCKLY_QUIZ_GSHEET_URL", "").strip()
        and not attempt.sheets_sent_at
        and not attempt.sheets_queued_at
    ):
        attempt.sheets_queued_at = timezone.now()
        attempt.sheets_error = ""
        attempt.save(update_fields=["sheets_queued_at", "sheets_error"])
        try:
            from .tasks import enqueue_attempt_export

            enqueue_attempt_export(attempt.id)
        except Exception:
            attempt.sheets_queued_at = None
            attempt.sheets_error = "Failed to enqueue Google Sheets export."
            attempt.save(update_fields=["sheets_queued_at", "sheets_error"])
    return attempt


def _build_question_context(*, attempt: Attempt, question: Question):
    total_questions = Question.objects.filter(quiz=attempt.quiz).count()
    answered_count = AttemptAnswer.objects.filter(attempt=attempt).count()
    choices = list(Choice.objects.filter(question=question).order_by("sort_order", "id"))
    return {
        "attempt": attempt,
        "quiz": attempt.quiz,
        "question": question,
        "choices": choices,
        "question_number": answered_count + 1,
        "answered_count": answered_count,
        "total_questions": total_questions,
    }


def _render_question_partial(request, *, attempt: Attempt, question: Question):
    return render(
        request,
        "blockly_quiz/_question.html",
        _build_question_context(attempt=attempt, question=question),
    )


@require_GET
def quiz_list(request):
    quizzes = Quiz.objects.filter(is_published=True).order_by("title", "id")

    query = (request.GET.get("q") or "").strip()
    if query:
        quizzes = quizzes.filter(Q(title__icontains=query) | Q(description__icontains=query))

    question_type = (request.GET.get("type") or "").strip().lower()
    if question_type in {"blockly", "scratch", "code"}:
        quizzes = quizzes.filter(questions__question_type=question_type).distinct()
    elif question_type:
        quizzes = quizzes.none()

    difficulty = (request.GET.get("difficulty") or "").strip().lower()
    if difficulty in {"easy", "medium", "hard"}:
        quizzes = quizzes.filter(questions__difficulty=difficulty).distinct()
    elif difficulty:
        quizzes = quizzes.none()

    if (request.GET.get("random") or "").strip() == "1":
        quiz_ids = list(quizzes.values_list("id", flat=True))
        if quiz_ids:
            picked = random.choice(quiz_ids)
            quiz = Quiz.objects.filter(id=picked).first()
            if quiz:
                return redirect(quiz.get_absolute_url())

    quizzes = _with_quiz_type_flags(quizzes)
    return render(
        request,
        "blockly_quiz/quiz_list.html",
        {
            "quizzes": quizzes,
            "q": query,
            "filter_type": question_type,
            "filter_difficulty": difficulty,
        },
    )


@require_GET
def tool_redirect(request, *args, **kwargs):
    return redirect("blockly_quiz:list")


@require_GET
def blockly_guide(request):
    return render(
        request,
        "blockly_quiz/blockly_tool.html",
        {"canonical_url": request.build_absolute_uri(request.path)},
    )


@require_GET
def quiz_detail(request, slug):
    quiz = get_object_or_404(
        _with_quiz_type_flags(Quiz.objects.filter(is_published=True)),
        slug=slug,
    )
    question_count = quiz.questions.count()
    return render(
        request,
        "blockly_quiz/quiz_detail.html",
        {
            "quiz": quiz,
            "question_count": question_count,
        },
    )


@require_GET
@ensure_csrf_cookie
def quiz_play(request, slug):
    quiz = get_object_or_404(
        _with_quiz_type_flags(Quiz.objects.filter(is_published=True)),
        slug=slug,
    )
    context = {
        "quiz": quiz,
        "initial_name": (request.GET.get("name") or "").strip(),
        "initial_dob": (request.GET.get("dob") or "").strip(),
        "initial_campus": (request.GET.get("campus") or "").strip(),
        "api_quiz_url": reverse("blockly_quiz:api-quiz", kwargs={"slug": quiz.slug}),
        "api_submit_url": reverse("blockly_quiz:api-submit", kwargs={"slug": quiz.slug}),
        "canonical_url": request.build_absolute_uri(request.path),
    }
    return render(request, "blockly_quiz/quiz_play.html", context)


@require_POST
def quiz_start(request, slug):
    quiz = get_object_or_404(Quiz, slug=slug, is_published=True)
    session_key = _ensure_session_key(request)
    participant_name = (request.POST.get("name") or "").strip()
    participant_dob = (request.POST.get("dob") or "").strip()
    participant_campus = (request.POST.get("campus") or "").strip()
    attempt = Attempt.objects.create(
        quiz=quiz,
        user=request.user if request.user.is_authenticated else None,
        session_key=session_key,
        participant_name=participant_name,
        participant_dob=participant_dob,
        participant_campus=participant_campus,
    )
    return redirect("blockly_quiz:attempt", attempt_id=attempt.id)


@require_GET
def attempt_take(request, attempt_id):
    attempt = _get_attempt_or_404(request, attempt_id)
    if attempt.completed_at:
        return redirect("blockly_quiz:review", attempt_id=attempt.id)

    answered_ids = AttemptAnswer.objects.filter(attempt=attempt).values_list(
        "question_id", flat=True
    )
    question = (
        Question.objects.filter(quiz=attempt.quiz)
        .exclude(id__in=answered_ids)
        .order_by("sort_order", "id")
        .first()
    )
    if not question:
        _finalize_attempt(attempt)
        return redirect("blockly_quiz:review", attempt_id=attempt.id)

    return render(
        request,
        "blockly_quiz/attempt_take.html",
        _build_question_context(attempt=attempt, question=question),
    )


@require_POST
def attempt_answer(request, attempt_id):
    attempt = _get_attempt_or_404(request, attempt_id)
    review_url = reverse("blockly_quiz:review", kwargs={"attempt_id": attempt.id})
    if attempt.completed_at:
        if request.headers.get("HX-Request") == "true":
            response = HttpResponse("")
            response["HX-Redirect"] = review_url
            return response
        return redirect(review_url)

    question_id = request.POST.get("question_id")
    choice_id = request.POST.get("choice_id")
    if not question_id:
        raise Http404

    question = get_object_or_404(Question, pk=question_id, quiz=attempt.quiz)
    if not choice_id:
        messages.error(request, _("Please choose an answer."))
        if request.headers.get("HX-Request") == "true":
            return _render_question_partial(request, attempt=attempt, question=question)
        return redirect("blockly_quiz:attempt", attempt_id=attempt.id)

    choice = get_object_or_404(Choice, pk=choice_id, question=question)
    AttemptAnswer.objects.update_or_create(
        attempt=attempt,
        question=question,
        defaults={
            "selected_choice": choice,
            "is_correct": bool(choice.is_correct),
        },
    )

    answered_ids = AttemptAnswer.objects.filter(attempt=attempt).values_list(
        "question_id", flat=True
    )
    next_question = (
        Question.objects.filter(quiz=attempt.quiz)
        .exclude(id__in=answered_ids)
        .order_by("sort_order", "id")
        .first()
    )
    if not next_question:
        _finalize_attempt(attempt)
        messages.success(request, _("Quiz completed."))
        if request.headers.get("HX-Request") == "true":
            response = HttpResponse("")
            response["HX-Redirect"] = review_url
            return response
        return redirect(review_url)

    if request.headers.get("HX-Request") == "true":
        return _render_question_partial(request, attempt=attempt, question=next_question)
    return redirect("blockly_quiz:attempt", attempt_id=attempt.id)


@require_GET
def attempt_review(request, attempt_id):
    attempt = _get_attempt_or_404(request, attempt_id)
    if not attempt.completed_at:
        answered_ids = AttemptAnswer.objects.filter(attempt=attempt).values_list(
            "question_id", flat=True
        )
        has_unanswered = (
            Question.objects.filter(quiz=attempt.quiz)
            .exclude(id__in=answered_ids)
            .exists()
        )
        if has_unanswered:
            messages.info(request, _("Finish the quiz to view the review screen."))
            return redirect("blockly_quiz:attempt", attempt_id=attempt.id)
        attempt = _finalize_attempt(attempt)

    answers = {
        answer.question_id: answer
        for answer in AttemptAnswer.objects.filter(attempt=attempt).select_related(
            "selected_choice"
        )
    }
    answered_question_ids = list(answers.keys())
    questions_qs = Question.objects.filter(quiz=attempt.quiz).prefetch_related("choices")
    if answered_question_ids and attempt.total_questions:
        total_quiz_questions = attempt.quiz.questions.count()
        if attempt.total_questions < total_quiz_questions:
            questions_qs = questions_qs.filter(id__in=answered_question_ids)
    questions = list(questions_qs.order_by("sort_order", "id"))
    for question in questions:
        question.answer = answers.get(question.id)
        question.correct_choice = next(
            (choice for choice in question.choices.all() if choice.is_correct),
            None,
        )
    return render(
        request,
        "blockly_quiz/attempt_review.html",
        {
            "attempt": attempt,
            "quiz": attempt.quiz,
            "questions": questions,
        },
    )


def _parse_json_request(request):
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except (TypeError, ValueError, UnicodeDecodeError):
        payload = None
    if not isinstance(payload, dict):
        payload = None
    return payload


@require_GET
def api_quiz_payload(request, slug):
    quiz = get_object_or_404(Quiz, slug=slug, is_published=True)
    questions_qs = (
        Question.objects.filter(quiz=quiz)
        .prefetch_related("choices")
        .order_by("sort_order", "id")
    )
    questions = []
    for question in questions_qs:
        choices = list(question.choices.all().order_by("sort_order", "id"))
        state = (question.blockly_state or "").strip()
        xml = (question.blockly_xml or "").strip()
        payload = state or xml
        kind = "state" if state else ("xml" if xml else "")
        scratchblocks_text = (question.scratchblocks_text or "").replace("\r\n", "\n").strip(
            "\n"
        )
        code_text = (question.code_text or "").replace("\r\n", "\n").strip("\n")
        code_language = (question.code_language or "").strip()
        if code_text and not code_language:
            code_language = "python"
        questions.append(
            {
                "id": question.id,
                "question_type": (question.question_type or "").strip(),
                "difficulty": (question.difficulty or "").strip(),
                "prompt": question.prompt,
                "blockly_payload": payload,
                "blockly_payload_kind": kind,
                "scratchblocks_text": scratchblocks_text,
                "code_text": code_text,
                "code_language": code_language,
                "choices": [{"id": choice.id, "text": choice.text} for choice in choices],
            }
        )
    return JsonResponse(
        {
            "quiz": {
                "slug": quiz.slug,
                "title": quiz.title,
                "description": quiz.description,
            },
            "questions": questions,
        }
    )


@require_POST
def api_quiz_submit(request, slug):
    quiz = get_object_or_404(Quiz, slug=slug, is_published=True)
    payload = _parse_json_request(request)
    if payload is None:
        return JsonResponse({"error": "invalid_json"}, status=400)

    answers_payload = payload.get("answers")
    if not isinstance(answers_payload, list):
        return JsonResponse({"error": "answers_required"}, status=400)

    session_key = _ensure_session_key(request)
    participant_name = payload.get("name")
    participant_dob = payload.get("dob")
    participant_campus = payload.get("campus")
    attempt = Attempt.objects.create(
        quiz=quiz,
        user=request.user if request.user.is_authenticated else None,
        session_key=session_key,
        participant_name=str(participant_name or "").strip(),
        participant_dob=str(participant_dob or "").strip(),
        participant_campus=str(participant_campus or "").strip(),
    )

    question_map = {
        question.id: question
        for question in Question.objects.filter(quiz=quiz).only("id")
    }

    valid_question_ids: set[int] = set()
    for entry in answers_payload:
        if not isinstance(entry, dict):
            continue
        question_id = entry.get("question_id")
        choice_id = entry.get("choice_id")
        if question_id is None or choice_id is None:
            continue
        try:
            question_id = int(question_id)
            choice_id = int(choice_id)
        except (TypeError, ValueError):
            continue
        question = question_map.get(question_id)
        if not question:
            continue
        choice = Choice.objects.filter(id=choice_id, question_id=question.id).only(
            "id", "is_correct"
        ).first()
        if not choice:
            continue
        AttemptAnswer.objects.update_or_create(
            attempt=attempt,
            question_id=question.id,
            defaults={
                "selected_choice_id": choice.id,
                "is_correct": bool(choice.is_correct),
            },
        )
        valid_question_ids.add(question.id)

    _finalize_attempt(attempt, total_questions_override=len(valid_question_ids))
    return JsonResponse(
        {
            "attempt_id": attempt.id,
            "quiz": {"slug": quiz.slug, "title": quiz.title},
            "total_questions": attempt.total_questions,
            "correct_count": attempt.correct_count,
            "score_percent": attempt.score_percent,
            "review_url": request.build_absolute_uri(attempt.get_review_url()),
        }
    )


@require_GET
def api_attempt_detail(request, attempt_id):
    attempt = _get_attempt_or_404(request, attempt_id)
    if not attempt.completed_at:
        answered_ids = AttemptAnswer.objects.filter(attempt=attempt).values_list(
            "question_id", flat=True
        )
        has_unanswered = (
            Question.objects.filter(quiz=attempt.quiz)
            .exclude(id__in=answered_ids)
            .exists()
        )
        if not has_unanswered:
            attempt = _finalize_attempt(attempt)
    answers = list(
        AttemptAnswer.objects.filter(attempt=attempt).values(
            "question_id",
            "selected_choice_id",
            "is_correct",
            "answered_at",
        )
    )
    for entry in answers:
        answered_at = entry.get("answered_at")
        entry["answered_at"] = answered_at.isoformat() if answered_at else None
    return JsonResponse(
        {
            "attempt_id": attempt.id,
            "quiz": {"slug": attempt.quiz.slug, "title": attempt.quiz.title},
            "started_at": attempt.started_at.isoformat() if attempt.started_at else None,
            "completed_at": attempt.completed_at.isoformat()
            if attempt.completed_at
            else None,
            "total_questions": attempt.total_questions,
            "correct_count": attempt.correct_count,
            "score_percent": attempt.score_percent,
            "answers": answers,
        }
    )
