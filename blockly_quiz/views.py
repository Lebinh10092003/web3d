import json
import random
import secrets
from urllib.parse import urlencode
from uuid import uuid4

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Exists, OuterRef, Q
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from .models import Attempt, AttemptAnswer, Choice, Question, Quiz

SELECTION_TOKEN_MAX_AGE_SECONDS = 2 * 60 * 60
RANDOM_QUIZ_REQUIRED_GROUP_NAME = "Student V"
RANDOM_QUIZ_PRESET_COUNTS = {"easy": 5, "medium": 15, "hard": 10}
RANDOM_QUIZ_DEFAULT_TYPE = "blockly"


def _build_page_query_prefix(request, param_name: str) -> str:
    params = request.GET.copy()
    params.pop(param_name, None)
    base = params.urlencode()
    return f"{base}&" if base else ""


def _with_quiz_type_flags(quizzes):
    blockly_exists = Question.objects.filter(quiz=OuterRef("pk"), question_type="blockly")
    scratch_exists = Question.objects.filter(quiz=OuterRef("pk"), question_type="scratch")
    code_exists = Question.objects.filter(quiz=OuterRef("pk"), question_type="code")
    return quizzes.annotate(
        has_blockly=Exists(blockly_exists),
        has_scratch=Exists(scratch_exists),
        has_code=Exists(code_exists),
    )


def _user_can_use_random_quiz(user) -> bool:
    if user.is_authenticated and (user.is_staff or user.is_superuser):
        return True
    if not user.is_authenticated:
        return False
    return user.groups.filter(name=RANDOM_QUIZ_REQUIRED_GROUP_NAME).exists()


def _filter_quiz_queryset_for_user(quizzes, user):
    if user.is_authenticated and (user.is_staff or user.is_superuser):
        return quizzes
    if user.is_authenticated:
        group_ids = list(user.groups.values_list("id", flat=True))
        if group_ids:
            return quizzes.filter(
                Q(allowed_groups__isnull=True) | Q(allowed_groups__in=group_ids)
            ).distinct()
        return quizzes.filter(allowed_groups__isnull=True)
    return quizzes.filter(allowed_groups__isnull=True)


def _user_can_access_quiz(user, quiz: Quiz) -> bool:
    if not quiz:
        return False
    if user.is_authenticated and (user.is_staff or user.is_superuser):
        return True
    if not quiz.allowed_groups.exists():
        return True
    if not user.is_authenticated:
        return False
    return user.groups.filter(id__in=quiz.allowed_groups.values("id")).exists()


def _ensure_session_key(request) -> str:
    session_key = request.session.session_key
    if session_key:
        return session_key
    request.session.save()
    return request.session.session_key or ""


def _parse_int(raw, *, default: int, min_value: int | None = None, max_value: int | None = None) -> int:
    try:
        value = int((raw or "").strip())
    except (TypeError, ValueError):
        value = default
    if min_value is not None and value < min_value:
        value = min_value
    if max_value is not None and value > max_value:
        value = max_value
    return value


def _split_total_into_difficulties(total: int) -> tuple[int, int, int]:
    total = max(total, 0)
    base, remainder = divmod(total, 3)
    easy = base
    medium = base
    hard = base
    if remainder >= 1:
        medium += 1
    if remainder >= 2:
        easy += 1
    return easy, medium, hard


def _clamp_total_questions(*, easy: int, medium: int, hard: int, max_total: int) -> tuple[int, int, int]:
    easy = max(easy, 0)
    medium = max(medium, 0)
    hard = max(hard, 0)
    total = easy + medium + hard
    if total <= max_total:
        return easy, medium, hard

    overflow = total - max_total
    reduce_hard = min(hard, overflow)
    hard -= reduce_hard
    overflow -= reduce_hard

    reduce_medium = min(medium, overflow)
    medium -= reduce_medium
    overflow -= reduce_medium

    reduce_easy = min(easy, overflow)
    easy -= reduce_easy
    overflow -= reduce_easy

    return easy, medium, hard


def _question_bank_queryset_for_request(request):
    quizzes = _filter_quiz_queryset_for_user(Quiz.objects.filter(is_published=True), request.user)
    return Question.objects.filter(quiz__in=quizzes)


def _shuffle_choices(choices, *, seed: str):
    ordered = list(choices)
    if len(ordered) <= 1:
        return ordered
    rng = random.Random(str(seed))
    rng.shuffle(ordered)
    return ordered


def _get_playable_quiz_or_404(request, slug: str, *, include_type_flags: bool = False):
    quizzes = _filter_quiz_queryset_for_user(Quiz.objects.all(), request.user)
    if include_type_flags:
        quizzes = _with_quiz_type_flags(quizzes)
    quiz = get_object_or_404(quizzes, slug=slug)
    if quiz.is_published:
        return quiz
    if quiz.is_temporary:
        session_key = _ensure_session_key(request)
        if session_key and (quiz.temporary_session_key or "") == session_key:
            return quiz
    raise Http404


def _get_attempt_or_404(request, attempt_id: int) -> Attempt:
    attempt = get_object_or_404(
        Attempt.objects.select_related("quiz", "user"),
        pk=attempt_id,
    )
    if attempt.user_id:
        if not request.user.is_authenticated or attempt.user_id != request.user.id:
            raise Http404
        if not _user_can_access_quiz(request.user, attempt.quiz):
            raise Http404
        return attempt

    session_key = _ensure_session_key(request)
    if not attempt.session_key or attempt.session_key != session_key:
        raise Http404
    if not _user_can_access_quiz(request.user, attempt.quiz):
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


def _ordered_questions(attempt: Attempt) -> list[Question]:
    return list(Question.objects.filter(quiz=attempt.quiz).order_by("sort_order", "id"))


def _build_question_context(
    *,
    attempt: Attempt,
    question: Question,
    question_index: int | None = None,
    selected_choice_id: int | None = None,
    answered_count: int | None = None,
    total_questions: int | None = None,
):
    total_questions = total_questions or Question.objects.filter(quiz=attempt.quiz).count()
    answered_count = (
        answered_count
        if answered_count is not None
        else AttemptAnswer.objects.filter(attempt=attempt).count()
    )
    choices = _shuffle_choices(
        Choice.objects.filter(question=question).order_by("sort_order", "id"),
        seed=f"attempt:{attempt.id}:question:{question.id}",
    )
    question_number = question_index + 1 if question_index is not None else answered_count + 1
    return {
        "attempt": attempt,
        "quiz": attempt.quiz,
        "question": question,
        "choices": choices,
        "selected_choice_id": selected_choice_id,
        "question_number": question_number,
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
    quizzes = _filter_quiz_queryset_for_user(
        Quiz.objects.filter(is_published=True), request.user
    ).order_by("title", "id")

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

    quizzes = _with_quiz_type_flags(quizzes)
    paginator = Paginator(quizzes, getattr(settings, "QUIZ_PAGE_SIZE", 12))
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(
        request,
        "blockly_quiz/quiz_list.html",
        {
            "quizzes": page_obj.object_list,
            "page_obj": page_obj,
            "page_query_prefix": _build_page_query_prefix(request, "page"),
            "q": query,
            "filter_type": question_type,
            "filter_difficulty": difficulty,
            "can_use_random_quiz": _user_can_use_random_quiz(request.user),
        },
    )


@login_required
@require_GET
def attempt_list(request):
    attempts = (
        Attempt.objects.filter(user=request.user, completed_at__isnull=False)
        .select_related("quiz")
        .order_by("-completed_at", "-started_at", "-id")
    )
    paginator = Paginator(attempts, getattr(settings, "QUIZ_ATTEMPT_PAGE_SIZE", 10))
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(
        request,
        "blockly_quiz/attempt_list.html",
        {
            "attempts": page_obj.object_list,
            "page_obj": page_obj,
            "page_query_prefix": _build_page_query_prefix(request, "page"),
        },
    )


@require_GET
def random_quiz(request):
    max_total = 200

    if not _user_can_use_random_quiz(request.user):
        if not request.user.is_authenticated:
            login_url = reverse("accounts:login")
            next_url = reverse("blockly_quiz:random")
            return redirect(f"{login_url}?{urlencode({'next': next_url})}")
        messages.error(
            request,
            _("Random quiz is only available for %(group)s.") % {"group": RANDOM_QUIZ_REQUIRED_GROUP_NAME},
        )
        return redirect("blockly_quiz:list")

    question_type = (request.GET.get("type") or RANDOM_QUIZ_DEFAULT_TYPE).strip().lower()
    if question_type not in {"blockly", "scratch", "code"}:
        question_type = RANDOM_QUIZ_DEFAULT_TYPE

    mix_raw = (request.GET.get("mix") or "").strip().lower()
    mix = True
    if mix_raw in {"0", "false", "off", "no"}:
        mix = False
    elif mix_raw in {"1", "true", "on", "yes"}:
        mix = True

    mode_raw = (request.GET.get("mode") or "").strip().lower()
    if mode_raw in {"preset", "default"}:
        mode = "preset"
    elif mode_raw == "custom":
        mode = "custom"
    else:
        mode = (
            "custom"
            if any(
                key in request.GET
                for key in ("easy_count", "medium_count", "hard_count", "count", "difficulty")
            )
            else "preset"
        )

    preset_easy = int(RANDOM_QUIZ_PRESET_COUNTS["easy"])
    preset_medium = int(RANDOM_QUIZ_PRESET_COUNTS["medium"])
    preset_hard = int(RANDOM_QUIZ_PRESET_COUNTS["hard"])

    if mode == "preset":
        default_easy, default_medium, default_hard = preset_easy, preset_medium, preset_hard
    else:
        has_difficulty_counts = any(
            key in request.GET for key in ("easy_count", "medium_count", "hard_count")
        )
        if has_difficulty_counts:
            default_easy = _parse_int(
                request.GET.get("easy_count"),
                default=preset_easy,
                min_value=0,
                max_value=max_total,
            )
            default_medium = _parse_int(
                request.GET.get("medium_count"),
                default=preset_medium,
                min_value=0,
                max_value=max_total,
            )
            default_hard = _parse_int(
                request.GET.get("hard_count"),
                default=preset_hard,
                min_value=0,
                max_value=max_total,
            )
        elif request.GET.get("count") is None and request.GET.get("difficulty") is None:
            default_easy, default_medium, default_hard = preset_easy, preset_medium, preset_hard
        else:
            default_count = _parse_int(
                request.GET.get("count"),
                default=preset_easy + preset_medium + preset_hard,
                min_value=1,
                max_value=max_total,
            )
            legacy_difficulty = (request.GET.get("difficulty") or "").strip().lower()
            if legacy_difficulty in {"easy", "medium", "hard"}:
                default_easy = default_count if legacy_difficulty == "easy" else 0
                default_medium = default_count if legacy_difficulty == "medium" else 0
                default_hard = default_count if legacy_difficulty == "hard" else 0
            else:
                default_easy, default_medium, default_hard = _split_total_into_difficulties(
                    default_count
                )

    default_easy, default_medium, default_hard = _clamp_total_questions(
        easy=default_easy, medium=default_medium, hard=default_hard, max_total=max_total
    )

    questions_qs = _question_bank_queryset_for_request(request)
    availability_by_type: dict[str, dict[str, int]] = {
        "blockly": {"easy": 0, "medium": 0, "hard": 0},
        "scratch": {"easy": 0, "medium": 0, "hard": 0},
        "code": {"easy": 0, "medium": 0, "hard": 0},
    }
    for row in questions_qs.values("question_type", "difficulty").annotate(total=Count("id")):
        row_type = (row.get("question_type") or "").strip().lower() or "blockly"
        if row_type not in availability_by_type:
            continue
        difficulty = (row.get("difficulty") or "").strip().lower()
        count = int(row.get("total") or 0)
        if difficulty == "easy":
            availability_by_type[row_type]["easy"] += count
        elif difficulty == "hard":
            availability_by_type[row_type]["hard"] += count
        else:
            availability_by_type[row_type]["medium"] += count

    availability = availability_by_type.get(question_type, availability_by_type[RANDOM_QUIZ_DEFAULT_TYPE])

    return render(
        request,
        "blockly_quiz/random_quiz.html",
        {
            "default_mode": mode,
            "default_type": question_type,
            "default_easy_count": default_easy,
            "default_medium_count": default_medium,
            "default_hard_count": default_hard,
            "default_mix": mix,
            "preset_easy_count": preset_easy,
            "preset_medium_count": preset_medium,
            "preset_hard_count": preset_hard,
            "preset_total": preset_easy + preset_medium + preset_hard,
            "availability_by_type": availability_by_type,
            "available_easy": availability["easy"],
            "available_medium": availability["medium"],
            "available_hard": availability["hard"],
            "max_total": max_total,
        },
    )


@require_POST
def random_quiz_start(request):
    max_total = 200

    if not _user_can_use_random_quiz(request.user):
        if not request.user.is_authenticated:
            login_url = reverse("accounts:login")
            next_url = reverse("blockly_quiz:random")
            return redirect(f"{login_url}?{urlencode({'next': next_url})}")
        messages.error(
            request,
            _("Random quiz is only available for %(group)s.") % {"group": RANDOM_QUIZ_REQUIRED_GROUP_NAME},
        )
        return redirect("blockly_quiz:list")

    question_type = (request.POST.get("type") or RANDOM_QUIZ_DEFAULT_TYPE).strip().lower()
    if question_type not in {"blockly", "scratch", "code"}:
        question_type = RANDOM_QUIZ_DEFAULT_TYPE

    mix = (request.POST.get("mix") or "").strip().lower() in {"1", "true", "on", "yes"}

    mode_raw = (request.POST.get("mode") or "").strip().lower()
    if mode_raw in {"preset", "default"}:
        mode = "preset"
    elif mode_raw == "custom":
        mode = "custom"
    else:
        mode = (
            "custom"
            if any(
                key in request.POST
                for key in ("easy_count", "medium_count", "hard_count", "count", "difficulty")
            )
            else "preset"
        )

    if mode == "preset":
        desired_easy = int(RANDOM_QUIZ_PRESET_COUNTS["easy"])
        desired_medium = int(RANDOM_QUIZ_PRESET_COUNTS["medium"])
        desired_hard = int(RANDOM_QUIZ_PRESET_COUNTS["hard"])
    else:
        has_difficulty_counts = any(
            key in request.POST for key in ("easy_count", "medium_count", "hard_count")
        )
        if has_difficulty_counts:
            desired_easy = _parse_int(
                request.POST.get("easy_count"),
                default=int(RANDOM_QUIZ_PRESET_COUNTS["easy"]),
                min_value=0,
                max_value=max_total,
            )
            desired_medium = _parse_int(
                request.POST.get("medium_count"),
                default=int(RANDOM_QUIZ_PRESET_COUNTS["medium"]),
                min_value=0,
                max_value=max_total,
            )
            desired_hard = _parse_int(
                request.POST.get("hard_count"),
                default=int(RANDOM_QUIZ_PRESET_COUNTS["hard"]),
                min_value=0,
                max_value=max_total,
            )
        else:
            legacy_total = _parse_int(
                request.POST.get("count"),
                default=int(sum(RANDOM_QUIZ_PRESET_COUNTS.values())),
                min_value=1,
                max_value=max_total,
            )
            legacy_difficulty = (request.POST.get("difficulty") or "").strip().lower()
            if legacy_difficulty in {"easy", "medium", "hard"}:
                desired_easy = legacy_total if legacy_difficulty == "easy" else 0
                desired_medium = legacy_total if legacy_difficulty == "medium" else 0
                desired_hard = legacy_total if legacy_difficulty == "hard" else 0
            else:
                desired_easy, desired_medium, desired_hard = _split_total_into_difficulties(
                    legacy_total
                )

    before_clamp_total = desired_easy + desired_medium + desired_hard
    desired_easy, desired_medium, desired_hard = _clamp_total_questions(
        easy=desired_easy, medium=desired_medium, hard=desired_hard, max_total=max_total
    )
    if before_clamp_total > (desired_easy + desired_medium + desired_hard):
        messages.warning(request, _("Random quiz is limited to %(max)s questions.") % {"max": str(max_total)})

    desired_total = desired_easy + desired_medium + desired_hard
    if desired_total <= 0:
        messages.error(request, _("Please choose at least one question."))
        query = {
            "mode": "custom",
            "easy_count": "0",
            "medium_count": "0",
            "hard_count": "0",
            "type": question_type,
            "mix": "1" if mix else "0",
        }
        url = reverse("blockly_quiz:random")
        return redirect(f"{url}?{urlencode(query)}")

    questions_qs = _question_bank_queryset_for_request(request).filter(question_type=question_type)

    candidate_pairs = list(questions_qs.values_list("id", "difficulty"))
    if not candidate_pairs:
        messages.error(request, _("No questions match your filters."))
        query = {
            "mode": mode,
            "easy_count": str(desired_easy),
            "medium_count": str(desired_medium),
            "hard_count": str(desired_hard),
            "type": question_type,
            "mix": "1" if mix else "0",
        }
        url = reverse("blockly_quiz:random")
        return redirect(f"{url}?{urlencode(query)}")

    candidate_by_difficulty: dict[str, list[int]] = {"easy": [], "medium": [], "hard": []}
    for question_id, difficulty in candidate_pairs:
        difficulty_value = (difficulty or "").strip().lower()
        if difficulty_value == "easy":
            candidate_by_difficulty["easy"].append(question_id)
        elif difficulty_value == "hard":
            candidate_by_difficulty["hard"].append(question_id)
        else:
            candidate_by_difficulty["medium"].append(question_id)

    def _pick(question_ids: list[int], desired: int) -> list[int]:
        if desired <= 0 or not question_ids:
            return []
        return random.sample(question_ids, min(desired, len(question_ids)))

    selected_easy = _pick(candidate_by_difficulty["easy"], desired_easy)
    selected_medium = _pick(candidate_by_difficulty["medium"], desired_medium)
    selected_hard = _pick(candidate_by_difficulty["hard"], desired_hard)

    selected_ids = [*selected_easy, *selected_medium, *selected_hard]
    if mix and len(selected_ids) > 1:
        random.shuffle(selected_ids)

    actual_easy = len(selected_easy)
    actual_medium = len(selected_medium)
    actual_hard = len(selected_hard)
    actual_total = len(selected_ids)

    if actual_total <= 0:
        messages.error(request, _("No questions match your filters."))
        query = {
            "mode": mode,
            "easy_count": str(desired_easy),
            "medium_count": str(desired_medium),
            "hard_count": str(desired_hard),
            "type": question_type,
            "mix": "1" if mix else "0",
        }
        url = reverse("blockly_quiz:random")
        return redirect(f"{url}?{urlencode(query)}")

    difficulty_label = {
        "easy": _("Easy"),
        "medium": _("Medium"),
        "hard": _("Hard"),
    }
    shortages: list[str] = []
    if desired_easy and actual_easy < desired_easy:
        shortages.append(str(difficulty_label["easy"]))
    if desired_medium and actual_medium < desired_medium:
        shortages.append(str(difficulty_label["medium"]))
    if desired_hard and actual_hard < desired_hard:
        shortages.append(str(difficulty_label["hard"]))
    if shortages:
        messages.warning(
            request,
            _("Not enough questions for: %(levels)s. Using what is available.")
            % {"levels": ", ".join(shortages)},
        )

    selected_questions = list(
        Question.objects.filter(id__in=selected_ids).prefetch_related("choices")
    )
    question_map = {question.id: question for question in selected_questions}
    ordered_questions = [question_map[qid] for qid in selected_ids if qid in question_map]
    if not ordered_questions:
        messages.error(request, _("No questions match your filters."))
        return redirect("blockly_quiz:random")

    session_key = _ensure_session_key(request)
    quiz_slug = ""
    for attempt_index in range(6):
        quiz_slug = f"tmp-{uuid4().hex[:12]}"
        if not Quiz.objects.filter(slug=quiz_slug).exists():
            break
        quiz_slug = ""
    if not quiz_slug:
        raise Http404

    type_label = {"blockly": "Blockly", "scratch": "Scratch", "code": _("Code")}
    title_parts: list[str] = [_("Random quiz")]
    title_parts.append(str(type_label.get(question_type, question_type)))
    distribution_parts: list[str] = []
    if actual_easy:
        distribution_parts.append(f"{difficulty_label['easy']} {actual_easy}")
    if actual_medium:
        distribution_parts.append(f"{difficulty_label['medium']} {actual_medium}")
    if actual_hard:
        distribution_parts.append(f"{difficulty_label['hard']} {actual_hard}")
    if distribution_parts:
        title_parts.append(" / ".join(distribution_parts))
    title_parts.append(_("%(count)s questions") % {"count": str(actual_total)})
    quiz_title = " - ".join(title_parts)

    with transaction.atomic():
        quiz = Quiz.objects.create(
            title=quiz_title[:200],
            slug=quiz_slug,
            description="",
            is_published=False,
            is_temporary=True,
            temporary_session_key=session_key,
        )
        for index, original in enumerate(ordered_questions):
            new_question = Question.objects.create(
                quiz=quiz,
                sort_order=index,
                question_type=original.question_type,
                difficulty=original.difficulty,
                prompt=original.prompt,
                blockly_state=original.blockly_state,
                blockly_xml=original.blockly_xml,
                scratchblocks_text=original.scratchblocks_text,
                code_language=original.code_language,
                code_text=original.code_text,
                explanation=original.explanation,
            )
            for choice in original.choices.all().order_by("sort_order", "id"):
                Choice.objects.create(
                    question=new_question,
                    sort_order=choice.sort_order,
                    text=choice.text,
                    is_correct=bool(choice.is_correct),
                )

    play_url = reverse("blockly_quiz:play", kwargs={"slug": quiz.slug})
    return redirect(f"{play_url}?count={len(ordered_questions)}")


@require_POST
def random_quiz_discard(request, slug):
    quiz = get_object_or_404(Quiz.objects.filter(is_temporary=True), slug=slug)
    session_key = _ensure_session_key(request)
    if not session_key or (quiz.temporary_session_key or "") != session_key:
        raise Http404
    try:
        quiz.delete()
    except Exception:
        pass
    return redirect("blockly_quiz:random")


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
    quizzes = _filter_quiz_queryset_for_user(Quiz.objects.filter(is_published=True), request.user)
    quiz = get_object_or_404(_with_quiz_type_flags(quizzes), slug=slug)
    question_count = quiz.questions.count()
    return render(
        request,
        "blockly_quiz/quiz_detail.html",
        {
            "quiz": quiz,
            "question_count": question_count,
            "can_use_random_quiz": _user_can_use_random_quiz(request.user),
        },
    )


@require_GET
@ensure_csrf_cookie
def quiz_play(request, slug):
    quiz = _get_playable_quiz_or_404(request, slug, include_type_flags=True)
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
    quiz = get_object_or_404(
        _filter_quiz_queryset_for_user(Quiz.objects.filter(is_published=True), request.user),
        slug=slug,
    )
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

    ordered_questions = _ordered_questions(attempt)
    answers = {
        answer.question_id: answer
        for answer in AttemptAnswer.objects.filter(attempt=attempt).select_related("question")
    }
    next_question = None
    next_index = None
    for idx, q in enumerate(ordered_questions):
        if q.id not in answers:
            next_question = q
            next_index = idx
            break
    if not next_question:
        _finalize_attempt(attempt)
        return redirect("blockly_quiz:review", attempt_id=attempt.id)

    selected_choice_id = None
    answer = answers.get(next_question.id)
    if answer:
        selected_choice_id = answer.selected_choice_id

    return render(
        request,
        "blockly_quiz/attempt_take.html",
        _build_question_context(
            attempt=attempt,
            question=next_question,
            question_index=next_index,
            selected_choice_id=selected_choice_id,
            answered_count=len(answers),
            total_questions=len(ordered_questions),
        ),
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

    question_id_raw = request.POST.get("question_id")
    if not question_id_raw:
        raise Http404
    try:
        question_id = int(question_id_raw)
    except (TypeError, ValueError):
        raise Http404

    ordered_questions = _ordered_questions(attempt)
    index_map = {q.id: idx for idx, q in enumerate(ordered_questions)}
    if question_id not in index_map:
        raise Http404
    direction = (request.POST.get("direction") or "").strip().lower()

    answers = {
        answer.question_id: answer
        for answer in AttemptAnswer.objects.filter(attempt=attempt).select_related("question")
    }

    if direction == "prev":
        current_index = index_map[question_id]
        if current_index > 0:
            prev_question = ordered_questions[current_index - 1]
            prev_answer = answers.get(prev_question.id)
            selected_choice_id = getattr(prev_answer, "selected_choice_id", None)
            context = _build_question_context(
                attempt=attempt,
                question=prev_question,
                question_index=current_index - 1,
                selected_choice_id=selected_choice_id,
                answered_count=len(answers),
                total_questions=len(ordered_questions),
            )
            if request.headers.get("HX-Request") == "true":
                return render(request, "blockly_quiz/_question.html", context)
            return redirect("blockly_quiz:attempt", attempt_id=attempt.id)

    choice_id_raw = request.POST.get("choice_id")
    if not choice_id_raw:
        messages.error(request, _("Please choose an answer."))
        if request.headers.get("HX-Request") == "true":
            return _render_question_partial(
                request,
                attempt=attempt,
                question=get_object_or_404(Question, pk=question_id, quiz=attempt.quiz),
            )
        return redirect("blockly_quiz:attempt", attempt_id=attempt.id)

    question = get_object_or_404(Question, pk=question_id, quiz=attempt.quiz)
    choice = get_object_or_404(Choice, pk=choice_id_raw, question=question)
    AttemptAnswer.objects.update_or_create(
        attempt=attempt,
        question=question,
        defaults={
            "selected_choice": choice,
            "is_correct": bool(choice.is_correct),
        },
    )
    answers[question.id] = AttemptAnswer(
        attempt=attempt,
        question=question,
        selected_choice=choice,
        is_correct=bool(choice.is_correct),
    )

    next_question = None
    next_index = None
    for idx, q in enumerate(ordered_questions):
        if q.id not in answers:
            next_question = q
            next_index = idx
            break
    if not next_question:
        _finalize_attempt(attempt)
        messages.success(request, _("Quiz completed."))
        if request.headers.get("HX-Request") == "true":
            response = HttpResponse("")
            response["HX-Redirect"] = review_url
            return response
        return redirect(review_url)

    context = _build_question_context(
        attempt=attempt,
        question=next_question,
        question_index=next_index,
        answered_count=len(answers),
        total_questions=len(ordered_questions),
    )
    if request.headers.get("HX-Request") == "true":
        return render(request, "blockly_quiz/_question.html", context)
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
    response = render(
        request,
        "blockly_quiz/attempt_review.html",
        {
            "attempt": attempt,
            "quiz": attempt.quiz,
            "questions": questions,
        },
    )
    if getattr(attempt.quiz, "is_temporary", False):
        try:
            attempt.quiz.delete()
        except Exception:
            pass
    return response


def _parse_json_request(request):
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except (TypeError, ValueError, UnicodeDecodeError):
        payload = None
    if not isinstance(payload, dict):
        payload = None
    return payload


def _is_truthy_param(value) -> bool:
    normalized = str(value or "").strip().lower()
    return normalized in {"1", "true", "yes", "on"}


def _parse_count_param(request):
    DEFAULT_QUESTION_COUNT = 30
    if "count" not in request.GET:
        return DEFAULT_QUESTION_COUNT
    raw = str(request.GET.get("count") or "").strip()
    try:
        count = int(raw)
    except (TypeError, ValueError):
        return None
    if count <= 0:
        return None
    return min(count, 200)


def _select_questions_for_api(request, quiz: Quiz):
    question_type = (request.GET.get("type") or "").strip().lower()
    if question_type not in {"", "blockly", "scratch", "code"}:
        question_type = ""

    difficulty = (request.GET.get("difficulty") or "").strip().lower()
    if difficulty not in {"", "easy", "medium", "hard"}:
        difficulty = ""

    count = _parse_count_param(request)
    shuffle_mode = _is_truthy_param(request.GET.get("random")) or _is_truthy_param(
        request.GET.get("shuffle")
    )

    questions_qs = Question.objects.filter(quiz=quiz)
    if question_type:
        questions_qs = questions_qs.filter(question_type=question_type)
    if difficulty:
        questions_qs = questions_qs.filter(difficulty=difficulty)
    questions = list(questions_qs.prefetch_related("choices").order_by("sort_order", "id"))

    if shuffle_mode:
        random.shuffle(questions)

    if count is not None:
        questions = questions[:count]

    return questions


@require_GET
def api_quiz_payload(request, slug):
    quiz = _get_playable_quiz_or_404(request, slug)
    selected_questions = _select_questions_for_api(request, quiz)
    questions = []
    question_ids: list[int] = []
    choice_seed = secrets.token_hex(8)
    for question in selected_questions:
        question_ids.append(int(question.id))
        choices = _shuffle_choices(
            question.choices.all().order_by("sort_order", "id"),
            seed=f"{choice_seed}:{question.id}",
        )
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
    selection_token = signing.dumps(
        {"quiz_id": int(quiz.id), "question_ids": question_ids, "choice_seed": choice_seed},
        salt="blockly_quiz:selection",
    )
    return JsonResponse(
        {
            "quiz": {
                "slug": quiz.slug,
                "title": quiz.title,
                "description": quiz.description,
            },
            "questions": questions,
            "selection_token": selection_token,
        }
    )


@require_POST
def api_quiz_submit(request, slug):
    quiz = _get_playable_quiz_or_404(request, slug)
    payload = _parse_json_request(request)
    if payload is None:
        return JsonResponse({"error": "invalid_json"}, status=400)

    selection_token = str(payload.get("selection_token") or "").strip()
    if not selection_token:
        return JsonResponse({"error": "selection_token_required"}, status=400)
    try:
        selection = signing.loads(
            selection_token,
            salt="blockly_quiz:selection",
            max_age=SELECTION_TOKEN_MAX_AGE_SECONDS,
        )
    except signing.BadSignature:
        return JsonResponse({"error": "invalid_selection_token"}, status=400)
    if not isinstance(selection, dict):
        return JsonResponse({"error": "invalid_selection_token"}, status=400)
    if int(selection.get("quiz_id") or 0) != int(quiz.id):
        return JsonResponse({"error": "invalid_selection_token"}, status=400)
    expected_question_ids = selection.get("question_ids")
    if not isinstance(expected_question_ids, list) or not expected_question_ids:
        return JsonResponse({"error": "invalid_selection_token"}, status=400)
    try:
        expected_question_ids = [int(qid) for qid in expected_question_ids]
    except (TypeError, ValueError):
        return JsonResponse({"error": "invalid_selection_token"}, status=400)
    expected_question_ids = [qid for qid in expected_question_ids if qid > 0]
    if not expected_question_ids:
        return JsonResponse({"error": "invalid_selection_token"}, status=400)

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

    answer_map: dict[int, int] = {}
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
        answer_map[question_id] = choice_id

    expected_set = set(expected_question_ids)
    choice_ids = [cid for qid, cid in answer_map.items() if qid in expected_set and cid]
    choice_rows = Choice.objects.filter(
        id__in=choice_ids,
        question_id__in=expected_set,
    ).values("id", "question_id", "is_correct")
    choice_by_id = {row["id"]: row for row in choice_rows}

    for question_id in expected_question_ids:
        choice_id = answer_map.get(question_id)
        if not choice_id:
            continue
        row = choice_by_id.get(choice_id)
        if not row or int(row["question_id"]) != int(question_id):
            continue
        AttemptAnswer.objects.update_or_create(
            attempt=attempt,
            question_id=question_id,
            defaults={
                "selected_choice_id": choice_id,
                "is_correct": bool(row["is_correct"]),
            },
        )

    _finalize_attempt(attempt, total_questions_override=len(expected_question_ids))
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
