from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("library", "0009_course_models"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="CourseFavorite",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("course", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="favorites", to="library.course")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="course_favorites", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "unique_together": {("course", "user")},
            },
        ),
        migrations.CreateModel(
            name="CourseLessonProgress",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("is_completed", models.BooleanField(default=False)),
                ("last_watched_at", models.DateTimeField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("lesson", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="progresses", to="library.courselesson")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="course_lesson_progress", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "unique_together": {("lesson", "user")},
            },
        ),
    ]
