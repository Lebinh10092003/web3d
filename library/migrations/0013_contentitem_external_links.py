from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("library", "0012_banner_help_texts"),
    ]

    operations = [
        migrations.AddField(
            model_name="contentitem",
            name="external_links",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
