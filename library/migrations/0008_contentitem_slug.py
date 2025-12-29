from django.db import migrations, models
from django.utils.text import slugify


def populate_content_slugs(apps, schema_editor):
    ContentItem = apps.get_model("library", "ContentItem")
    for item in ContentItem.objects.all().only("id", "title", "slug"):
        if item.slug:
            continue
        base = slugify(item.title)[:200] or "content"
        slug = base
        counter = 2
        while ContentItem.objects.filter(slug=slug).exclude(pk=item.pk).exists():
            suffix = f"-{counter}"
            trimmed = base[: max(1, 200 - len(suffix))]
            slug = f"{trimmed}{suffix}"
            counter += 1
        item.slug = slug
        item.save(update_fields=["slug"])


class Migration(migrations.Migration):

    dependencies = [
        ("library", "0007_contentitem_price_vnd"),
    ]

    operations = [
        migrations.AddField(
            model_name="contentitem",
            name="slug",
            field=models.SlugField(blank=True, max_length=220, null=True, unique=True),
        ),
        migrations.RunPython(populate_content_slugs, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="contentitem",
            name="slug",
            field=models.SlugField(blank=True, max_length=220, unique=True),
        ),
    ]
