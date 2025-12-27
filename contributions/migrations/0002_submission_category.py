import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("library", "0001_initial"),
        ("contributions", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="contributionsubmission",
            name="content_type",
            field=models.CharField(max_length=20),
        ),
        migrations.AddField(
            model_name="contributionsubmission",
            name="category",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="submissions",
                to="library.category",
            ),
        ),
    ]
