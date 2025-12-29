import os
import zipfile

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.utils import timezone

try:
    import fitz
except Exception:
    fitz = None


def build_preview_path(user_id, filename):
    safe_name = os.path.basename(filename)
    timestamp = timezone.now().strftime("%Y%m%d_%H%M%S")
    return f"previews/contrib/{user_id}/{timestamp}_{safe_name}"


def build_preview_filename(original_name):
    base_name = os.path.splitext(os.path.basename(original_name))[0] or "preview"
    return f"{base_name}.png"


def _render_pdf_first_page(pdf_bytes, target_width=1200):
    if not fitz:
        return None
    doc = None
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        if doc.page_count < 1:
            return None
        page = doc.load_page(0)
        page_width = page.rect.width or 1
        scale = target_width / page_width
        scale = max(0.5, min(scale, 2.0))
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        return pix.tobytes("png")
    except Exception:
        return None
    finally:
        if doc:
            doc.close()


def maybe_generate_pdf_preview(source_path, preview_path):
    max_mb = int(getattr(settings, "MAX_PDF_PREVIEW_MB", 20))
    try:
        size_bytes = default_storage.size(source_path)
    except Exception:
        size_bytes = None
    if size_bytes and size_bytes > max_mb * 1024 * 1024:
        return ""
    try:
        with default_storage.open(source_path, "rb") as pdf_file:
            pdf_bytes = pdf_file.read()
    except Exception:
        return ""
    preview_bytes = _render_pdf_first_page(pdf_bytes)
    if not preview_bytes:
        return ""
    return default_storage.save(preview_path, ContentFile(preview_bytes))


def maybe_generate_archive_preview(source_path, preview_path):
    if not source_path or not preview_path:
        return ""

    try:
        with default_storage.open(source_path, "rb") as handle:
            archive = zipfile.ZipFile(handle)
            with archive:
                candidates = [
                    info
                    for info in archive.infolist()
                    if not info.is_dir()
                    and info.file_size > 0
                    and info.filename.lower().endswith((".png", ".jpg", ".jpeg"))
                ]
                if not candidates:
                    return ""

                def score(info):
                    name = info.filename.replace("\\", "/")
                    base = os.path.basename(name).lower()
                    is_image100 = 0 if base == "image100.png" else 1
                    is_preview = 0 if any(
                        token in base for token in ("preview", "thumb", "thumbnail", "render")
                    ) else 1
                    depth = len(name.split("/"))
                    return (is_image100, is_preview, depth, -info.file_size)

                best = min(candidates, key=score)
                preview_bytes = archive.read(best)
    except zipfile.BadZipFile:
        return ""
    except Exception:
        return ""

    if not preview_bytes:
        return ""
    try:
        return default_storage.save(preview_path, ContentFile(preview_bytes))
    except Exception:
        return ""
