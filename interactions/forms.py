from django import forms


class CommentForm(forms.Form):
    body = forms.CharField(
        widget=forms.Textarea(
            attrs={
                "rows": 3,
                "placeholder": "Share a constructive note",
                "class": "form-control",
            }
        )
    )
    parent_id = forms.IntegerField(required=False, widget=forms.HiddenInput)


class RatingForm(forms.Form):
    score = forms.ChoiceField(
        choices=[(i, str(i)) for i in range(1, 6)],
        widget=forms.RadioSelect,
    )
