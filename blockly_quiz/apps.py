from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class BlocklyQuizConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "blockly_quiz"
    verbose_name = _("Blockly quizzes")

