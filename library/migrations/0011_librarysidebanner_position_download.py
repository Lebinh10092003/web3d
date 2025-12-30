from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("library", "0010_contentitem_owner_nullable"),
    ]

    operations = [
        migrations.AlterField(
            model_name="librarysidebanner",
            name="position",
            field=models.CharField(
                choices=[("LEFT", "Left"), ("RIGHT", "Right"), ("DOWNLOAD", "Download")],
                default="LEFT",
                max_length=10,
            ),
        ),
    ]
