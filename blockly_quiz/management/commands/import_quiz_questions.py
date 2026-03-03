import sys
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from blockly_quiz.importer import import_questions_into_quiz, parse_bulk_questions
from blockly_quiz.models import Quiz


class Command(BaseCommand):
    help = "Import quiz questions from YAML/JSON into an existing quiz."

    def add_arguments(self, parser):
        parser.add_argument("quiz", help="Quiz slug or numeric id")
        parser.add_argument("source", help="Path to YAML/JSON file, or '-' for stdin")
        parser.add_argument(
            "--replace",
            action="store_true",
            help="Delete existing questions before importing (also deletes existing attempts for that quiz).",
        )

    def handle(self, *args, **options):
        quiz_value = str(options["quiz"]).strip()
        if not quiz_value:
            raise CommandError("Quiz slug/id is required.")

        quiz = None
        if quiz_value.isdigit():
            quiz = Quiz.objects.filter(pk=int(quiz_value)).first()
        if not quiz:
            quiz = Quiz.objects.filter(slug=quiz_value).first()
        if not quiz:
            raise CommandError(f"Quiz not found: {quiz_value}")

        source = str(options["source"]).strip()
        if not source:
            raise CommandError("Source is required.")

        if source == "-":
            raw_text = sys.stdin.read()
        else:
            path = Path(source)
            if not path.exists():
                raise CommandError(f"File not found: {path}")
            raw_text = path.read_text(encoding="utf-8")

        try:
            questions = parse_bulk_questions(raw_text)
            created_questions, created_choices = import_questions_into_quiz(
                quiz=quiz, questions=questions, replace_existing=bool(options["replace"])
            )
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages) if exc.messages else str(exc))

        self.stdout.write(
            self.style.SUCCESS(
                f"Imported {created_questions} questions ({created_choices} choices) into {quiz.slug}."
            )
        )
