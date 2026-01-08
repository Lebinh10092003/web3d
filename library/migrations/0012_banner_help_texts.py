from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("library", "0011_librarysidebanner_position_download"),
    ]

    operations = [
        migrations.AlterField(
            model_name="recapherobanner",
            name="background_image",
            field=models.FileField(
                blank=True,
                help_text="Recommended size: 1600x900px (16:9).",
                upload_to="banners/recaps/",
            ),
        ),
        migrations.AlterField(
            model_name="librarysidebanner",
            name="image",
            field=models.FileField(
                help_text="Recommended size: 600x900px for side banners, 1200x800px for download banner.",
                upload_to="banners/library/",
            ),
        ),
    ]
