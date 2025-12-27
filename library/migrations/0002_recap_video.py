from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("library", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="RecapVideo",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("competition", models.CharField(max_length=120)),
                ("competition_slug", models.SlugField(blank=True, max_length=140)),
                ("year", models.PositiveSmallIntegerField()),
                ("video_id", models.CharField(blank=True, help_text="Paste a YouTube ID or full URL.", max_length=40)),
                ("title", models.CharField(max_length=200)),
                ("summary", models.TextField(blank=True)),
                ("is_published", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["competition_slug", "-year", "title"],
                "unique_together": {("competition_slug", "year")},
            },
        ),
    ]
