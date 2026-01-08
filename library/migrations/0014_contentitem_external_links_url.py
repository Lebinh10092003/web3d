from django.db import migrations, models


def _coerce_external_links_to_string(apps, schema_editor):
    ContentItem = apps.get_model("library", "ContentItem")
    for item in ContentItem.objects.all().only("id", "external_links"):
        value = item.external_links
        url = ""
        if isinstance(value, list):
            if value:
                first = value[0]
                if isinstance(first, dict):
                    url = first.get("url", "") or ""
                elif isinstance(first, str):
                    url = first
        elif isinstance(value, dict):
            url = value.get("url", "") or ""
        elif isinstance(value, str):
            url = value
        if url is None:
            url = ""
        if url != value:
            item.external_links = url
            item.save(update_fields=["external_links"])


class Migration(migrations.Migration):
    dependencies = [
        ("library", "0013_contentitem_external_links"),
    ]

    operations = [
        migrations.RunPython(_coerce_external_links_to_string, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="contentitem",
            name="external_links",
            field=models.URLField(blank=True, max_length=500),
        ),
    ]
