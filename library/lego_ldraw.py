import os
import re
import zipfile
from functools import lru_cache
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree

from django.contrib.staticfiles import finders
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage


class LegoModelError(Exception):
    pass


class UnsupportedLegoModel(LegoModelError):
    pass


def get_cached_ldraw_model_path(*, content_id, source_path):
    cache_path = f"derived/lego/{content_id}/model.ldr"
    if default_storage.exists(cache_path):
        return cache_path

    model_bytes = build_ldraw_model_bytes(source_path)
    default_storage.save(cache_path, ContentFile(model_bytes))
    return cache_path


def build_ldraw_model_bytes(source_path):
    ext = _file_extension(source_path)
    if ext in {"ldr", "mpd"}:
        return _read_storage_bytes(source_path)
    if ext == "io":
        return _extract_ldraw_from_io(source_path)
    if ext == "lxf":
        return _convert_lxf_to_ldraw(source_path)
    raise UnsupportedLegoModel(f"Unsupported LEGO source: {ext}")


def _file_extension(path):
    if not path:
        return ""
    _, ext = os.path.splitext(path)
    return ext.lstrip(".").lower()


def _read_storage_bytes(path):
    with default_storage.open(path, "rb") as handle:
        return handle.read()


def _extract_ldraw_from_io(source_path):
    with default_storage.open(source_path, "rb") as handle:
        try:
            archive = zipfile.ZipFile(handle)
        except zipfile.BadZipFile:
            handle.seek(0)
            return handle.read()

        with archive:
            candidates = [
                info
                for info in archive.infolist()
                if not info.is_dir()
                and info.filename.lower().endswith((".ldr", ".mpd"))
                and info.file_size > 0
            ]
            if not candidates:
                raise UnsupportedLegoModel("No LDraw files found inside .io archive.")
            best = min(candidates, key=_score_ldraw_candidate)
            return archive.read(best)


def _score_ldraw_candidate(info):
    name = info.filename.replace("\\", "/")
    base = PurePosixPath(name).name.lower()
    depth = len(PurePosixPath(name).parts)
    is_model = 0 if base in {"model.ldr", "model.mpd"} else 1
    return (is_model, depth, len(base))


def _convert_lxf_to_ldraw(source_path):
    lxfml_bytes = _extract_lxfml_bytes(source_path)
    try:
        root = ElementTree.fromstring(lxfml_bytes)
    except ElementTree.ParseError as exc:
        raise UnsupportedLegoModel("Invalid LXFML payload.") from exc

    color_map = _load_ldd_to_ldraw_color_map()
    scale = float(os.environ.get("LXF_LDRAW_SCALE", "1") or "1")
    apply_axis_conversion = os.environ.get("LXF_LDRAW_AXIS_CONVERT", "1") != "0"

    lines = [
        "0 Generated from LXF",
        "0 Name: model.ldr",
        "0 Author: web3d",
    ]

    for part in _iter_elements(root, "Part"):
        design_id = (part.attrib.get("designID") or "").strip()
        if not design_id:
            continue

        materials = (part.attrib.get("materials") or "").strip()
        material_id = _first_int(materials)
        color = color_map.get(material_id, 16) if material_id is not None else 16

        transform_numbers = _find_transform_numbers(part)
        if not transform_numbers:
            continue

        rotation, translation = _normalize_transform(transform_numbers)
        translation = [value * scale for value in translation]

        if apply_axis_conversion:
            rotation, translation = _convert_ldd_axes_to_ldraw(rotation, translation)

        a, b, c = rotation[0]
        d, e, f = rotation[1]
        g, h, i = rotation[2]
        x, y, z = translation

        part_filename = f"{design_id}.dat"
        lines.append(
            "1 {color} {x} {y} {z} {a} {b} {c} {d} {e} {f} {g} {h} {i} {part}".format(
                color=int(color),
                x=_fmt_num(x),
                y=_fmt_num(y),
                z=_fmt_num(z),
                a=_fmt_num(a),
                b=_fmt_num(b),
                c=_fmt_num(c),
                d=_fmt_num(d),
                e=_fmt_num(e),
                f=_fmt_num(f),
                g=_fmt_num(g),
                h=_fmt_num(h),
                i=_fmt_num(i),
                part=part_filename,
            )
        )

    return ("\n".join(lines) + "\n").encode("utf-8")


def _extract_lxfml_bytes(source_path):
    with default_storage.open(source_path, "rb") as handle:
        try:
            archive = zipfile.ZipFile(handle)
        except zipfile.BadZipFile as exc:
            raise UnsupportedLegoModel(".lxf file is not a valid zip archive.") from exc

        with archive:
            members = [
                info
                for info in archive.infolist()
                if not info.is_dir() and info.filename.lower().endswith(".lxfml")
            ]
            if not members:
                raise UnsupportedLegoModel("No .lxfml file found inside .lxf archive.")
            best = min(members, key=lambda info: len(info.filename))
            return archive.read(best)


def _iter_elements(root, local_name):
    for element in root.iter():
        if _local_name(element.tag) == local_name:
            yield element


def _local_name(tag):
    return tag.split("}", 1)[-1] if tag else ""


def _first_int(value):
    if not value:
        return None
    match = re.search(r"\d+", value)
    return int(match.group(0)) if match else None


def _find_transform_numbers(element):
    for candidate in _iter_transform_sources(element):
        numbers = _parse_number_list(candidate)
        if len(numbers) in {12, 16}:
            return numbers
    return []


def _iter_transform_sources(element):
    attribute_names = ("transformation", "transform", "matrix", "transformationMatrix")
    for name in attribute_names:
        value = element.attrib.get(name)
        if value:
            yield value

    for node in element.iter():
        for name in attribute_names:
            value = node.attrib.get(name)
            if value:
                yield value
        if node.text and _local_name(node.tag).lower() in {"transform", "transformation", "matrix"}:
            yield node.text


def _parse_number_list(value):
    if not value:
        return []
    cleaned = value.replace(",", " ").replace(";", " ")
    parts = [part for part in cleaned.split() if part]
    numbers = []
    for part in parts:
        try:
            numbers.append(float(part))
        except ValueError:
            continue
    return numbers


def _normalize_transform(numbers):
    if len(numbers) == 12:
        a, b, c, d, e, f, g, h, i, x, y, z = numbers
        rotation = [
            [a, b, c],
            [d, e, f],
            [g, h, i],
        ]
        translation = [x, y, z]
        return rotation, translation

    if len(numbers) == 16:
        rotation = [
            [numbers[0], numbers[1], numbers[2]],
            [numbers[4], numbers[5], numbers[6]],
            [numbers[8], numbers[9], numbers[10]],
        ]
        translation = [numbers[3], numbers[7], numbers[11]]
        return rotation, translation

    raise UnsupportedLegoModel("Unsupported transform matrix size.")


def _convert_ldd_axes_to_ldraw(rotation, translation):
    basis = [
        [1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0],
        [0.0, -1.0, 0.0],
    ]
    basis_t = _transpose_3x3(basis)
    rotation_converted = _matmul_3x3(_matmul_3x3(basis, rotation), basis_t)
    translation_converted = _matvec_3x3(basis, translation)
    return rotation_converted, translation_converted


def _transpose_3x3(matrix):
    return [
        [matrix[0][0], matrix[1][0], matrix[2][0]],
        [matrix[0][1], matrix[1][1], matrix[2][1]],
        [matrix[0][2], matrix[1][2], matrix[2][2]],
    ]


def _matmul_3x3(left, right):
    out = [[0.0, 0.0, 0.0] for _ in range(3)]
    for row in range(3):
        for col in range(3):
            out[row][col] = (
                left[row][0] * right[0][col]
                + left[row][1] * right[1][col]
                + left[row][2] * right[2][col]
            )
    return out


def _matvec_3x3(matrix, vector):
    return [
        matrix[0][0] * vector[0] + matrix[0][1] * vector[1] + matrix[0][2] * vector[2],
        matrix[1][0] * vector[0] + matrix[1][1] * vector[1] + matrix[1][2] * vector[2],
        matrix[2][0] * vector[0] + matrix[2][1] * vector[1] + matrix[2][2] * vector[2],
    ]


def _fmt_num(value):
    if abs(value - round(value)) < 1e-6:
        return str(int(round(value)))
    return f"{value:.6f}".rstrip("0").rstrip(".")


@lru_cache(maxsize=1)
def _load_ldd_to_ldraw_color_map():
    ldconfig_path = finders.find("ldraw/LDConfig.ldr")
    if not ldconfig_path:
        return {}
    mapping = {}
    current_legoid = None
    try:
        text = Path(ldconfig_path).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return mapping

    for line in text.splitlines():
        match = re.match(r"^0\s*//\s*LEGOID\s+([0-9]+)", line)
        if match:
            current_legoid = int(match.group(1))
            continue

        if current_legoid is None:
            continue

        if "!COLOUR" in line and " CODE" in line:
            code_match = re.search(r"\bCODE\s+([0-9]+)", line)
            if code_match:
                mapping[current_legoid] = int(code_match.group(1))
            current_legoid = None
    return mapping
