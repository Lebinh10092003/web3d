from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("library", "0009_library_side_banner"),
    ]

    operations = [
        migrations.AlterField(
            model_name="contentitem",
            name="owner",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="contents",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
