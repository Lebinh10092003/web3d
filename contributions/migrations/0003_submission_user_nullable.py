from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("contributions", "0002_submission_category"),
    ]

    operations = [
        migrations.AlterField(
            model_name="contributionsubmission",
            name="user",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="submissions",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
