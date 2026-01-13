from django import forms


class BulkQuestionImportForm(forms.Form):
    data = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 18, "spellcheck": "false"}),
        help_text="Paste YAML or JSON that contains a list of questions (optional: question_type, difficulty).",
    )
    replace_existing = forms.BooleanField(
        required=False,
        help_text="Delete existing questions before importing (blocked if attempts exist).",
    )
