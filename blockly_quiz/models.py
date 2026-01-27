from django.conf import settings
from django.contrib.auth.models import Group
from django.db import models
from django.urls import reverse
from django.utils.translation import gettext_lazy as _


class Quiz(models.Model):
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True)
    description = models.TextField(blank=True)
    is_published = models.BooleanField(default=False)
    is_temporary = models.BooleanField(
        default=False,
        help_text=_("Temporary quizzes are generated for random practice."),
    )
    temporary_session_key = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text=_("Owner session key for temporary quizzes."),
    )
    allowed_groups = models.ManyToManyField(
        Group,
        blank=True,
        related_name="blockly_quizzes",
        help_text=_("Optional: only members of these groups can access this quiz."),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["title", "id"]

    def __str__(self) -> str:
        return self.title

    def get_absolute_url(self):
        return reverse("blockly_quiz:detail", kwargs={"slug": self.slug})


class Question(models.Model):
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name="questions")
    sort_order = models.PositiveIntegerField(default=0)
    question_type = models.CharField(
        max_length=16,
        blank=True,
        default="blockly",
        choices=[
            ("blockly", _("Blockly")),
            ("scratch", _("Scratch")),
            ("code", _("Code")),
        ],
        help_text=_("Used for filtering and random quiz generation."),
    )
    difficulty = models.CharField(
        max_length=16,
        blank=True,
        default="medium",
        choices=[
            ("easy", _("Easy")),
            ("medium", _("Medium")),
            ("hard", _("Hard")),
        ],
        help_text=_("Used for filtering and random quiz generation."),
    )
    prompt = models.TextField()
    blockly_state = models.TextField(
        blank=True,
        help_text=_(
            "Optional: Blockly workspace JSON (from Blockly.serialization.workspaces.save) for editor-accurate preview."
        ),
    )
    blockly_xml = models.TextField(
        blank=True,
        help_text=_("Optional: Blockly XML used for the block preview."),
    )
    scratchblocks_text = models.TextField(
        blank=True,
        help_text=_(
            "Optional: Scratch blocks text (scratchblocks syntax) for Scratch-style preview."
        ),
    )
    code_language = models.CharField(
        max_length=32,
        blank=True,
        default="",
        help_text=_("Optional: language name for code snippet (e.g., python)."),
    )
    code_text = models.TextField(
        blank=True,
        help_text=_("Optional: code snippet shown under the prompt."),
    )
    explanation = models.TextField(
        blank=True,
        help_text=_("Optional: shown on the review screen."),
    )

    class Meta:
        ordering = ["sort_order", "id"]

    def __str__(self) -> str:
        return f"{self.quiz.title}: {self.prompt[:40]}".strip()


class Choice(models.Model):
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="choices")
    sort_order = models.PositiveIntegerField(default=0)
    text = models.CharField(max_length=300)
    is_correct = models.BooleanField(default=False)

    class Meta:
        ordering = ["sort_order", "id"]

    def __str__(self) -> str:
        return self.text


class Classroom(models.Model):
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="quiz_classrooms",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name", "id"]

    def __str__(self) -> str:
        return self.name

    def get_absolute_url(self):
        return reverse("blockly_quiz:classroom-detail", kwargs={"slug": self.slug})


class ClassroomMembership(models.Model):
    ROLE_CHOICES = (
        ("teacher", _("Teacher")),
        ("student", _("Student")),
    )
    classroom = models.ForeignKey(Classroom, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    role = models.CharField(max_length=16, choices=ROLE_CHOICES, default="student")
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("classroom", "user")]
        ordering = ["-joined_at", "-id"]

    def __str__(self) -> str:
        return f"{self.user} in {self.classroom} ({self.role})"


class QuizAssignment(models.Model):
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name="assignments")
    classroom = models.ForeignKey(
        Classroom, on_delete=models.CASCADE, related_name="assignments"
    )
    title = models.CharField(max_length=220, blank=True)
    due_at = models.DateTimeField(null=True, blank=True)
    max_attempts = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("quiz", "classroom")]
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return self.title or f"{self.quiz.title} @ {self.classroom.name}"


class Attempt(models.Model):
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name="attempts")
    quiz_title_snapshot = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text=_("Snapshot of quiz title at submission time."),
    )
    quiz_slug_snapshot = models.CharField(
        max_length=220,
        blank=True,
        default="",
        help_text=_("Snapshot of quiz slug at submission time."),
    )
    quiz_is_temporary_snapshot = models.BooleanField(
        default=False,
        help_text=_("Snapshot of quiz temporary status at submission time."),
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="blockly_quiz_attempts",
    )
    session_key = models.CharField(
        max_length=64,
        blank=True,
        help_text=_("Used to bind anonymous attempts to a browser session."),
    )
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    total_questions = models.PositiveIntegerField(default=0)
    correct_count = models.PositiveIntegerField(default=0)
    score_percent = models.PositiveIntegerField(default=0)
    participant_name = models.CharField(max_length=120, blank=True)
    participant_dob = models.CharField(max_length=50, blank=True)
    participant_campus = models.CharField(max_length=120, blank=True)
    sheets_queued_at = models.DateTimeField(null=True, blank=True)
    sheets_sent_at = models.DateTimeField(null=True, blank=True)
    sheets_error = models.TextField(blank=True)
    assignment = models.ForeignKey(
        QuizAssignment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="attempts",
    )

    class Meta:
        ordering = ["-started_at", "-id"]

    def __str__(self) -> str:
        return f"{self.quiz.title} (#{self.id})"

    @property
    def is_completed(self) -> bool:
        return bool(self.completed_at)

    def get_absolute_url(self):
        return reverse("blockly_quiz:attempt", kwargs={"attempt_id": self.id})

    def get_review_url(self):
        return reverse("blockly_quiz:review", kwargs={"attempt_id": self.id})


class AttemptAnswer(models.Model):
    attempt = models.ForeignKey(Attempt, on_delete=models.CASCADE, related_name="answers")
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="attempt_answers")
    selected_choice = models.ForeignKey(
        Choice,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    is_correct = models.BooleanField(default=False)
    answered_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [
            ("attempt", "question"),
        ]
        ordering = ["answered_at", "id"]

    def __str__(self) -> str:
        return f"Attempt #{self.attempt_id}: Q#{self.question_id}"
