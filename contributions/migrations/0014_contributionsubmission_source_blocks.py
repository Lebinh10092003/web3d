from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("contributions", "0013_contributionsubmission_external_links_url"),
    ]

    operations = [
        migrations.AddField(
            model_name="contributionsubmission",
            name="source_blocks",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
