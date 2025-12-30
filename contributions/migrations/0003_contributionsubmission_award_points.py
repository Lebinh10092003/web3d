from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("contributions", "0002_submission_category"),
    ]

    operations = [
        migrations.AddField(
            model_name="contributionsubmission",
            name="award_points",
            field=models.PositiveIntegerField(
                blank=True,
                help_text="Override points awarded to the uploader on approval.",
                null=True,
            ),
        ),
    ]
