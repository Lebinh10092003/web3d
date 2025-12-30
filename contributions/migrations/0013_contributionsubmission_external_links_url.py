from django.db import migrations, models


def _coerce_external_links_to_string(apps, schema_editor):
    ContributionSubmission = apps.get_model("contributions", "ContributionSubmission")
    for submission in ContributionSubmission.objects.all().only("id", "external_links"):
        value = submission.external_links
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
            submission.external_links = url
            submission.save(update_fields=["external_links"])


class Migration(migrations.Migration):
    dependencies = [
        ("contributions", "0012_contributionsubmission_external_links"),
    ]

    operations = [
        migrations.RunPython(_coerce_external_links_to_string, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="contributionsubmission",
            name="external_links",
            field=models.URLField(blank=True, max_length=500),
        ),
    ]
