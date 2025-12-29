import os

from django.core.management.base import BaseCommand

from library.lego_ldraw import UnsupportedLegoModel, get_cached_ldraw_model_path
from library.models import ContentFile


class Command(BaseCommand):
    help = "Prebuild cached LDraw models for existing LEGO content."

    def add_arguments(self, parser):
        parser.add_argument(
            "--content-id",
            action="append",
            dest="content_ids",
            help="Limit to a specific content ID (can be repeated).",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Limit the number of items processed.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Only list items that would be processed.",
        )

    def handle(self, *args, **options):
        content_ids = options.get("content_ids") or []
        limit = int(options.get("limit") or 0)
        dry_run = bool(options.get("dry_run"))

        ids = []
        for raw in content_ids:
            if raw is None:
                continue
            try:
                ids.append(int(raw))
            except ValueError:
                self.stderr.write(f"Skipping invalid content id: {raw}")

        qs = ContentFile.objects.filter(kind=ContentFile.FileKind.SOURCE).select_related(
            "content"
        )
        if ids:
            qs = qs.filter(content_id__in=ids)

        processed = 0
        succeeded = 0
        failed = 0
        skipped = 0
        seen_content = set()

        for source in qs.iterator():
            if limit and processed >= limit:
                break
            if source.content_id in seen_content:
                continue
            seen_content.add(source.content_id)

            path = source.storage_path or ""
            ext = os.path.splitext(path)[1].lstrip(".").lower()
            if ext not in {"lxf", "io", "ldr", "mpd"}:
                skipped += 1
                continue

            processed += 1
            label = f"{source.content_id}:{path}"
            if dry_run:
                self.stdout.write(f"Would prebuild {label}")
                continue

            try:
                cache_path = get_cached_ldraw_model_path(
                    content_id=source.content_id, source_path=path
                )
            except UnsupportedLegoModel as exc:
                failed += 1
                self.stderr.write(f"Skip {label}: {exc}")
                continue
            except Exception as exc:
                failed += 1
                self.stderr.write(f"Failed {label}: {exc}")
                continue

            succeeded += 1
            self.stdout.write(f"Prebuilt {label} -> {cache_path}")

        summary = (
            f"Processed={processed} succeeded={succeeded} failed={failed} skipped={skipped}"
        )
        self.stdout.write(summary)
