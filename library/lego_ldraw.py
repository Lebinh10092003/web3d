import hashlib
import os
import re
import shutil
import shlex
import subprocess
import tempfile
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


LXF_PY_CONVERTER_VERSION = 2


def get_cached_ldraw_model_path(*, content_id, source_path):
    cache_variant = _ldraw_cache_variant(source_path)
    cache_path = f"derived/lego/{content_id}/model-{cache_variant}.ldr"
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
    mode = (os.environ.get("LXF_CONVERTER_MODE", "auto") or "auto").strip().lower()
    if mode not in {"auto", "cli", "python"}:
        mode = "auto"

    converter_cmd = (os.environ.get("LXF_CONVERTER_CMD") or "").strip()
    if mode == "auto" and not converter_cmd:
        converter_cmd = _detect_lxf_converter_cmd()
    if mode != "python" and converter_cmd:
        return _convert_lxf_to_ldraw_with_cli(source_path, converter_cmd)

    if mode == "cli":
        raise UnsupportedLegoModel(
            "LXF conversion requires an external converter. Set LXF_CONVERTER_CMD "
            "(e.g. lxf2ldr/ldd2ldraw)."
        )

    return _convert_lxf_to_ldraw_python(source_path)


def _detect_lxf_converter_cmd():
    for candidate in ("lxf2ldr", "ldd2ldraw"):
        if shutil.which(candidate):
            return candidate
    return ""


def _convert_lxf_to_ldraw_with_cli(source_path, converter_cmd):
    timeout_seconds = _parse_timeout_seconds(os.environ.get("LXF_CONVERTER_TIMEOUT", "30"))

    with tempfile.TemporaryDirectory(prefix="lxf-convert-") as tmpdir:
        input_path = _materialize_storage_file(source_path, tmpdir, suffix=".lxf")
        output_path = str(Path(tmpdir) / "model.ldr")

        attempts = _build_converter_attempts(converter_cmd, input_path, output_path)
        last_error = None

        for args in attempts:
            try:
                result = subprocess.run(
                    args,
                    cwd=tmpdir,
                    capture_output=True,
                    timeout=timeout_seconds,
                    check=False,
                )
            except FileNotFoundError as exc:
                raise UnsupportedLegoModel(
                    "LXF converter executable not found. Check LXF_CONVERTER_CMD."
                ) from exc
            except subprocess.TimeoutExpired as exc:
                last_error = exc
                continue

            if result.returncode != 0:
                last_error = result
                continue

            output_bytes = b""
            try:
                if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                    output_bytes = Path(output_path).read_bytes()
            except OSError:
                output_bytes = b""

            if not output_bytes:
                output_bytes = _find_converter_output_bytes(tmpdir)

            if not output_bytes:
                stdout = result.stdout or b""
                if stdout.strip():
                    output_bytes = stdout

            if output_bytes:
                return output_bytes

            last_error = result

        detail = ""
        if isinstance(last_error, subprocess.TimeoutExpired):
            detail = "Conversion timed out."
        elif isinstance(last_error, subprocess.CompletedProcess):
            stderr = (last_error.stderr or b"").decode("utf-8", errors="ignore").strip()
            if stderr:
                detail = stderr[:400]
        raise UnsupportedLegoModel(
            "Could not convert .lxf using the configured external converter."
            + (f" {detail}" if detail else "")
        )


def _find_converter_output_bytes(tmpdir):
    root = Path(tmpdir)
    candidates = []
    for suffix in (".ldr", ".mpd"):
        candidates.extend([path for path in root.rglob(f"*{suffix}") if path.is_file()])

    if not candidates:
        return b""

    def score(path):
        base = path.name.lower()
        is_model = 0 if base in {"model.ldr", "model.mpd"} else 1
        depth = len(path.parts)
        return (is_model, depth, len(base))

    best = min(candidates, key=score)
    try:
        if best.exists() and best.stat().st_size > 0:
            return best.read_bytes()
    except OSError:
        return b""
    return b""


def _build_converter_attempts(converter_cmd, input_path, output_path):
    cmd = (converter_cmd or "").strip()
    if not cmd:
        return []

    attempts = []
    formatted = ""
    if "{input}" in cmd or "{output}" in cmd:
        try:
            formatted = cmd.format(input=input_path, output=output_path)
        except Exception:
            formatted = cmd.replace("{input}", input_path).replace("{output}", output_path)

    if formatted:
        attempts.append(_split_converter_cmd(formatted))
    else:
        base_args = _split_converter_cmd(cmd)
        attempts.append([*base_args, input_path, output_path])
        attempts.append([*base_args, input_path])

    out = []
    for args in attempts:
        if not args:
            continue
        if args not in out:
            out.append(args)
    return out


def _split_converter_cmd(command):
    cmd = (command or "").strip()
    if not cmd:
        return []

    # On Windows, POSIX parsing treats backslashes as escapes (breaking paths like
    # C:\tools\lxf2ldr.exe). Use non-POSIX mode there.
    parts = shlex.split(cmd, posix=os.name != "nt")

    cleaned = []
    for part in parts:
        if len(part) >= 2 and part[0] == part[-1] and part[0] in {'"', "'"}:
            cleaned.append(part[1:-1])
        else:
            cleaned.append(part)
    return cleaned


def _materialize_storage_file(source_path, tmpdir, suffix=""):
    try:
        local_path = default_storage.path(source_path)
    except Exception:
        local_path = ""
    if local_path and os.path.exists(local_path):
        return local_path

    dest_path = Path(tmpdir) / f"input{suffix or ''}"
    with default_storage.open(source_path, "rb") as handle:
        dest_path.write_bytes(handle.read())
    return str(dest_path)


def _parse_timeout_seconds(value):
    try:
        parsed = float(str(value or "").strip() or "0")
    except ValueError:
        return 30.0
    if parsed <= 0:
        return 30.0
    return min(parsed, 300.0)


def _convert_lxf_to_ldraw_python(source_path):
    lxfml_bytes = _extract_lxfml_bytes(source_path)
    try:
        root = ElementTree.fromstring(lxfml_bytes)
    except ElementTree.ParseError as exc:
        raise UnsupportedLegoModel("Invalid LXFML payload.") from exc

    color_map = _load_ldd_to_ldraw_color_map()
    scale = float(os.environ.get("LXF_LDRAW_SCALE", "25") or "25")
    apply_axis_conversion = os.environ.get("LXF_LDRAW_AXIS_CONVERT", "1") != "0"

    lines = [
        "0 Generated from LXF",
        "0 Name: model.ldr",
        "0 Author: web3d",
    ]

    bone_transforms = _resolve_lxf_bone_transforms(root)
    rigid_transforms = _extract_lxf_rigid_transforms(root)

    for part in _iter_elements(root, "Part"):
        design_id = (part.attrib.get("designID") or "").strip()
        if not design_id:
            continue

        material_id = _extract_lxf_material_id(part)
        color = color_map.get(material_id, 16) if material_id is not None else 16

        transform_numbers = []
        bone_ref_id = _first_lxf_bone_ref_id(part)
        if bone_ref_id is not None:
            transform_numbers = bone_transforms.get(bone_ref_id, [])
            if not transform_numbers:
                transform_numbers = _find_transform_numbers(part)
            if not transform_numbers:
                transform_numbers = rigid_transforms.get(bone_ref_id, [])
        if not transform_numbers:
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


def _extract_lxf_rigid_transforms(root):
    mapping = {}
    for rigid in _iter_elements(root, "Rigid"):
        bone_refs = (rigid.attrib.get("boneRefs") or "").strip()
        transform = (rigid.attrib.get("transformation") or "").strip()
        if not bone_refs or not transform:
            continue
        numbers = _parse_number_list(transform)
        if len(numbers) not in {12, 16}:
            continue
        tokens = [token for token in re.split(r"[,\s]+", bone_refs) if token]
        if len(tokens) != 1:
            continue
        token = tokens[0]
        if token.isdigit():
            mapping[int(token)] = numbers
    return mapping


def _first_lxf_bone_ref_id(part):
    for bone in _iter_elements(part, "Bone"):
        ref = (bone.attrib.get("refID") or "").strip()
        if ref.isdigit():
            return int(ref)
    return None


def _resolve_lxf_bone_transforms(root):
    local_transforms = {}
    parent_map = {}

    def walk(node, parent_id=None):
        if _local_name(node.tag) == "Bone":
            ref = (node.attrib.get("refID") or "").strip()
            bone_id = int(ref) if ref.isdigit() else None
            if bone_id is not None:
                transform = (node.attrib.get("transformation") or "").strip()
                numbers = _parse_number_list(transform)
                if len(numbers) in {12, 16}:
                    local_transforms[bone_id] = numbers
                if parent_id is not None:
                    parent_map[bone_id] = parent_id
                parent_id = bone_id

        for child in list(node):
            walk(child, parent_id)

    walk(root)

    resolved = {}

    def resolve(bone_id):
        if bone_id in resolved:
            return resolved[bone_id]
        numbers = local_transforms.get(bone_id, [])
        if not numbers:
            resolved[bone_id] = []
            return []

        parent_id = parent_map.get(bone_id)
        if parent_id is None:
            resolved[bone_id] = numbers
            return numbers

        parent_numbers = resolve(parent_id)
        if not parent_numbers:
            resolved[bone_id] = numbers
            return numbers

        rotation_parent, translation_parent = _normalize_transform(parent_numbers)
        rotation_local, translation_local = _normalize_transform(numbers)

        rotation = _matmul_3x3(rotation_parent, rotation_local)
        translation_rotated = _matvec_3x3(rotation_parent, translation_local)
        translation = [
            translation_rotated[0] + translation_parent[0],
            translation_rotated[1] + translation_parent[1],
            translation_rotated[2] + translation_parent[2],
        ]

        composed = _flatten_transform(rotation, translation)
        resolved[bone_id] = composed
        return composed

    for bone_id in local_transforms:
        resolve(bone_id)

    return resolved


def _flatten_transform(rotation, translation):
    a, b, c = rotation[0]
    d, e, f = rotation[1]
    g, h, i = rotation[2]
    x, y, z = translation
    return [a, b, c, d, e, f, g, h, i, x, y, z]


def _extract_lxf_material_id(part):
    materials = (part.attrib.get("materials") or "").strip()
    material_id = _first_int(materials)
    if material_id is not None:
        return material_id

    for node in part.iter():
        if _local_name(node.tag) != "Material":
            continue
        ref = (node.attrib.get("refID") or "").strip()
        material_id = _first_int(ref)
        if material_id is not None:
            return material_id
    return None


def _ldraw_cache_variant(source_path):
    ext = _file_extension(source_path)
    if not ext:
        return "model"
    if ext == "lxf":
        cmd = (os.environ.get("LXF_CONVERTER_CMD") or "").strip()
        mode = (os.environ.get("LXF_CONVERTER_MODE", "auto") or "auto").strip().lower()
        if mode == "auto" and not cmd:
            cmd = _detect_lxf_converter_cmd()
        if mode == "python" or not cmd:
            scale = (os.environ.get("LXF_LDRAW_SCALE", "25") or "25").strip()
            axis = (os.environ.get("LXF_LDRAW_AXIS_CONVERT", "1") or "1").strip()
            key = f"py|v={LXF_PY_CONVERTER_VERSION}|scale={scale}|axis={axis}"
            digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:8]
            return f"lxf-py-{digest}"

        key = f"cli|cmd={cmd}"
        digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:8]
        return f"lxf-cli-{digest}"
    return ext


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
            preferred = []
            for info in members:
                name = info.filename.replace("\\", "/")
                if PurePosixPath(name).name.lower() == "image100.lxfml":
                    preferred.append(info)
            best_pool = preferred or members
            best = min(best_pool, key=lambda info: len(info.filename))
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
