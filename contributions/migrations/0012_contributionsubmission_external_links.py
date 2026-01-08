from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("contributions", "0011_merge_20251230_1302"),
    ]

    operations = [
        migrations.AddField(
            model_name="contributionsubmission",
            name="external_links",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
