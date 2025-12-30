from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("library", "0008_contentitem_slug"),
    ]

    operations = [
        migrations.CreateModel(
            name="LibrarySideBanner",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(blank=True, max_length=120)),
                ("image", models.FileField(upload_to="banners/library/")),
                ("link_url", models.URLField(blank=True)),
                (
                    "position",
                    models.CharField(
                        choices=[("LEFT", "Left"), ("RIGHT", "Right")],
                        default="LEFT",
                        max_length=10,
                    ),
                ),
                ("sort_order", models.PositiveIntegerField(default=0)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["position", "sort_order", "-updated_at"],
            },
        ),
    ]
