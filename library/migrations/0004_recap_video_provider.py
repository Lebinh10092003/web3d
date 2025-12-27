from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("library", "0003_recap_hero_banner"),
    ]

    operations = [
        migrations.AddField(
            model_name="recapvideo",
            name="video_provider",
            field=models.CharField(
                choices=[("YOUTUBE", "YouTube"), ("TIKTOK", "TikTok")],
                default="YOUTUBE",
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="recapvideo",
            name="video_id",
            field=models.CharField(
                blank=True,
                help_text="Paste a YouTube/TikTok URL or ID.",
                max_length=200,
            ),
        ),
    ]
