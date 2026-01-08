from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="website_url",
            field=models.URLField(blank=True),
        ),
        migrations.AddField(
            model_name="user",
            name="facebook_url",
            field=models.URLField(blank=True),
        ),
        migrations.AddField(
            model_name="user",
            name="github_url",
            field=models.URLField(blank=True),
        ),
    ]
