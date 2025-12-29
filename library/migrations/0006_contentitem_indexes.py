from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("library", "0005_alter_recapvideo_options_and_more"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="contentitem",
            index=models.Index(
                fields=["is_public", "status", "created_at"],
                name="content_pub_status_created_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="contentitem",
            index=models.Index(fields=["title"], name="content_title_idx"),
        ),
    ]
