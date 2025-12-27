from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("library", "0002_recap_video"),
    ]

    operations = [
        migrations.CreateModel(
            name="RecapHeroBanner",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=200)),
                ("body", models.TextField(blank=True)),
                ("eyebrow", models.CharField(blank=True, max_length=80)),
                ("background_image", models.FileField(blank=True, upload_to="banners/recaps/")),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["-updated_at"],
                "verbose_name": "Recap hero banner",
                "verbose_name_plural": "Recap hero banners",
            },
        ),
    ]
