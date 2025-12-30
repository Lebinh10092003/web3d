from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings


def seed_point_packages(apps, schema_editor):
    PointPackage = apps.get_model("gating", "PointPackage")
    defaults = [
        (10, 10000),
        (100, 100000),
        (500, 500000),
        (1000, 1000000),
        (5000, 5000000),
    ]
    for index, (points, price_vnd) in enumerate(defaults, start=1):
        PointPackage.objects.update_or_create(
            points=points,
            defaults={
                "name": f"{points} points",
                "price_vnd": price_vnd,
                "is_active": True,
                "sort_order": index,
            },
        )


class Migration(migrations.Migration):
    dependencies = [
        ("gating", "0003_alter_unlock_method"),
    ]

    operations = [
        migrations.CreateModel(
            name="PointPackage",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=80)),
                ("points", models.PositiveIntegerField(unique=True)),
                ("price_vnd", models.PositiveIntegerField()),
                ("is_active", models.BooleanField(default=True)),
                ("sort_order", models.PositiveIntegerField(default=0)),
            ],
            options={
                "ordering": ["sort_order", "points"],
            },
        ),
        migrations.CreateModel(
            name="PointTopupTransaction",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("points", models.PositiveIntegerField()),
                ("amount", models.PositiveIntegerField()),
                ("currency", models.CharField(default="VND", max_length=6)),
                ("provider", models.CharField(default="ZALOPAY", max_length=30)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("PENDING", "Pending"),
                            ("PAID", "Paid"),
                            ("FAILED", "Failed"),
                        ],
                        default="PENDING",
                        max_length=20,
                    ),
                ),
                ("points_awarded", models.BooleanField(default=False)),
                ("app_trans_id", models.CharField(max_length=64, unique=True)),
                ("zp_trans_id", models.CharField(blank=True, max_length=64)),
                ("app_time", models.BigIntegerField(default=0)),
                ("raw_callback", models.JSONField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "package",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="transactions",
                        to="gating.pointpackage",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="point_topups",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.RunPython(seed_point_packages, migrations.RunPython.noop),
    ]
