from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("library", "0019_contentitem_allowed_groups"),
    ]

    operations = [
        migrations.AddField(
            model_name="contentitem",
            name="source_blocks",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
