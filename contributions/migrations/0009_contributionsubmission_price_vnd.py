from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("contributions", "0008_alter_contributionsubmission_download_cost_points"),
    ]

    operations = [
        migrations.AddField(
            model_name="contributionsubmission",
            name="price_vnd",
            field=models.PositiveIntegerField(
                default=0,
                help_text="Price in VND for paid content. Set 0 for free/points.",
            ),
        ),
    ]
