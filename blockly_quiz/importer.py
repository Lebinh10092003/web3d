import json

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max

from .models import Attempt, Choice, Question


def _load_structured_text(raw_text: str):
    text = (raw_text or "").strip()
    if not text:
        raise ValidationError("Import data is empty.")

    parsed = None
    json_error = None
    if text[:1] in {"{", "["}:
        try:
            parsed = json.loads(text)
        except (TypeError, ValueError) as exc:
            json_error = exc

    if parsed is not None:
        return parsed

    try:
        import yaml
    except Exception:
        if json_error:
            raise ValidationError(f"Invalid JSON: {json_error}")
        raise ValidationError("PyYAML is not available; please paste JSON instead.")

    try:
        parsed = yaml.safe_load(text)
    except Exception as exc:
        raise ValidationError(f"Invalid YAML: {exc}")
    return parsed


def _normalize_questions_payload(payload):
    if isinstance(payload, dict):
        questions = payload.get("questions")
    else:
        questions = payload

    if not isinstance(questions, list):
        raise ValidationError("Expected a list of questions or a {'questions': [...]} object.")

    normalized = []
    for idx, item in enumerate(questions, start=1):
        if not isinstance(item, dict):
            raise ValidationError(f"Question #{idx}: expected an object.")
        prompt = str(item.get("prompt") or "").strip()
        if not prompt:
            raise ValidationError(f"Question #{idx}: 'prompt' is required.")
        blockly_xml = str(item.get("blockly_xml") or "").strip()
        blockly_state = item.get("blockly_state")
        if blockly_state is None:
            blockly_state = item.get("blockly_json")
        blockly_state_text = ""
        if isinstance(blockly_state, (dict, list)):
            blockly_state_text = json.dumps(blockly_state, ensure_ascii=False)
        else:
            blockly_state_text = str(blockly_state or "").strip()

        scratchblocks_text = str(
            item.get("scratchblocks_text")
            or item.get("scratch_text")
            or item.get("scratchblocks")
            or ""
        ).strip()

        raw_question_type = (
            item.get("question_type")
            or item.get("type")
            or item.get("kind")
            or item.get("language_type")
            or ""
        )
        question_type = str(raw_question_type or "").strip().lower()

        raw_code_text = item.get("code_text")
        if raw_code_text is None:
            raw_code_text = item.get("python_code")
        if raw_code_text is None:
            raw_code_text = item.get("code")
        code_text = str(raw_code_text or "").replace("\r\n", "\n").strip("\n")
        code_language = str(item.get("code_language") or item.get("language") or "").strip()
        if code_text and not code_language:
            code_language = "python"
        explanation = str(item.get("explanation") or "").strip()

        raw_difficulty = item.get("difficulty")
        if raw_difficulty is None:
            raw_difficulty = item.get("level")
        difficulty = str(raw_difficulty or "").strip().lower()

        sort_order = item.get("sort_order")
        if sort_order is not None:
            try:
                sort_order = int(sort_order)
            except (TypeError, ValueError):
                raise ValidationError(f"Question #{idx}: 'sort_order' must be an integer.")

        raw_choices = item.get("choices")
        if not isinstance(raw_choices, list) or len(raw_choices) < 2:
            raise ValidationError(f"Question #{idx}: 'choices' must be a list with 2+ items.")

        choices = []
        correct_count = 0
        for c_idx, choice in enumerate(raw_choices, start=1):
            if not isinstance(choice, dict):
                raise ValidationError(f"Question #{idx} choice #{c_idx}: expected an object.")
            text = str(choice.get("text") or "").strip()
            if not text:
                raise ValidationError(f"Question #{idx} choice #{c_idx}: 'text' is required.")
            is_correct = bool(choice.get("is_correct", False))
            if is_correct:
                correct_count += 1

            c_sort_order = choice.get("sort_order")
            if c_sort_order is not None:
                try:
                    c_sort_order = int(c_sort_order)
                except (TypeError, ValueError):
                    raise ValidationError(
                        f"Question #{idx} choice #{c_idx}: 'sort_order' must be an integer."
                    )
            else:
                c_sort_order = c_idx - 1

            choices.append(
                {
                    "sort_order": c_sort_order,
                    "text": text,
                    "is_correct": is_correct,
                }
            )

        if correct_count != 1:
            raise ValidationError(
                f"Question #{idx}: expected exactly 1 correct choice, got {correct_count}."
            )

        if not question_type:
            if scratchblocks_text:
                question_type = "scratch"
            elif code_text:
                question_type = "code"
            else:
                question_type = "blockly"

        valid_question_types = {"blockly", "scratch", "code"}
        if question_type not in valid_question_types:
            raise ValidationError(
                f"Question #{idx}: invalid 'question_type' ({question_type}); expected one of {sorted(valid_question_types)}."
            )

        if not difficulty:
            difficulty = "medium"
        if difficulty in {"1", "easy"}:
            difficulty = "easy"
        elif difficulty in {"2", "medium", "normal"}:
            difficulty = "medium"
        elif difficulty in {"3", "hard"}:
            difficulty = "hard"
        valid_difficulties = {"easy", "medium", "hard"}
        if difficulty not in valid_difficulties:
            raise ValidationError(
                f"Question #{idx}: invalid 'difficulty' ({difficulty}); expected one of {sorted(valid_difficulties)}."
            )

        normalized.append(
            {
                "sort_order": sort_order,
                "question_type": question_type,
                "difficulty": difficulty,
                "prompt": prompt,
                "blockly_state": blockly_state_text,
                "blockly_xml": blockly_xml,
                "scratchblocks_text": scratchblocks_text,
                "code_language": code_language,
                "code_text": code_text,
                "explanation": explanation,
                "choices": choices,
            }
        )

    if not normalized:
        raise ValidationError("No questions found in import payload.")
    return normalized


def parse_bulk_questions(raw_text: str):
    payload = _load_structured_text(raw_text)
    return _normalize_questions_payload(payload)


def import_questions_into_quiz(*, quiz, questions, replace_existing: bool = False):
    if replace_existing and Attempt.objects.filter(quiz=quiz).exists():
        raise ValidationError("Cannot replace questions because attempts already exist.")

    with transaction.atomic():
        if replace_existing:
            quiz.questions.all().delete()
            base_sort = 0
        else:
            base_sort = (
                Question.objects.filter(quiz=quiz).aggregate(max_sort=Max("sort_order"))[
                    "max_sort"
                ]
                or 0
            )
            base_sort = base_sort + 1

        created_questions = 0
        created_choices = 0
        for idx, item in enumerate(questions):
            sort_order = item.get("sort_order")
            if sort_order is None:
                sort_order = base_sort + idx

            question = Question.objects.create(
                quiz=quiz,
                sort_order=sort_order,
                question_type=item.get("question_type", "blockly"),
                difficulty=item.get("difficulty", "medium"),
                prompt=item["prompt"],
                blockly_state=item.get("blockly_state", ""),
                blockly_xml=item.get("blockly_xml", ""),
                scratchblocks_text=item.get("scratchblocks_text", ""),
                code_language=item.get("code_language", ""),
                code_text=item.get("code_text", ""),
                explanation=item.get("explanation", ""),
            )
            created_questions += 1

            for choice in item["choices"]:
                Choice.objects.create(
                    question=question,
                    sort_order=int(choice.get("sort_order", 0) or 0),
                    text=choice["text"],
                    is_correct=bool(choice.get("is_correct", False)),
                )
                created_choices += 1

    return created_questions, created_choices
