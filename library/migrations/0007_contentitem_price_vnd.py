from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("library", "0006_contentitem_indexes"),
    ]

    operations = [
        migrations.AddField(
            model_name="contentitem",
            name="price_vnd",
            field=models.PositiveIntegerField(default=0),
        ),
    ]
