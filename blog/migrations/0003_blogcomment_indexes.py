from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("blog", "0002_blogcomment"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="blogcomment",
            index=models.Index(
                fields=["post", "created_at"], name="blog_comment_post_created_idx"
            ),
        ),
    ]
