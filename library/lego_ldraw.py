import hashlib
import math
import os
import re
import shutil
import shlex
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional, Tuple
from xml.etree import ElementTree

from django.contrib.staticfiles import finders
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage


class LegoModelError(Exception):
    pass


class UnsupportedLegoModel(LegoModelError):
    pass


LXF_PY_CONVERTER_VERSION = 3


@dataclass(frozen=True)
class Transform:
    translation: List[float]
    rotation: List[List[float]]


@dataclass(frozen=True)
class SimpleSubstitute:
    datfile: str
    overwrite: bool


@dataclass(frozen=True)
class Substitute:
    datfile: str
    transformation: Optional[Transform]


@dataclass(frozen=True)
class DecorMatch:
    usecolor: int
    colors: List[Dict[int, SimpleSubstitute]]
    decorations: Dict[str, Substitute]


@dataclass(frozen=True)
class ColorSubstitute:
    usecolor: int
    substitute: Optional[Substitute]


@dataclass(frozen=True)
class Counted:
    count: int
    transformation: Optional[Transform]


@dataclass(frozen=True)
class BiCounted:
    before: int
    after: int
    transformation: Optional[Transform]


@dataclass(frozen=True)
class Flexible:
    type: str
    head: Optional[Counted]
    body: Optional[BiCounted]
    tail: Optional[Counted]
    head_plus: Optional[Substitute]
    tail_plus: Optional[Substitute]


def get_cached_ldraw_model_path(*, content_id, source_path):
    ext = _file_extension(source_path)
    if ext == "lxf":
        return _get_cached_lxf_model_path(content_id=content_id, source_path=source_path)

    cache_variant = _ldraw_cache_variant(source_path)
    cache_path = f"derived/lego/{content_id}/model-{cache_variant}.ldr"
    if default_storage.exists(cache_path):
        return cache_path

    model_bytes = build_ldraw_model_bytes(source_path)
    default_storage.save(cache_path, ContentFile(model_bytes))
    return cache_path


def find_cached_ldraw_model_path(*, content_id, source_path):
    ext = _file_extension(source_path)
    if ext == "lxf":
        mode, cmd = _resolve_lxf_converter_settings()
        variants = _lxf_cache_variants_for_mode(mode, cmd)
        for variant in variants:
            cache_path = f"derived/lego/{content_id}/model-{variant}.ldr"
            if default_storage.exists(cache_path):
                return cache_path
        return ""

    cache_variant = _ldraw_cache_variant(source_path)
    cache_path = f"derived/lego/{content_id}/model-{cache_variant}.ldr"
    if default_storage.exists(cache_path):
        return cache_path
    return ""


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
            readable = [info for info in candidates if not (info.flag_bits & 0x1)]
            if not readable:
                raise UnsupportedLegoModel(
                    "The .io archive is encrypted. Please export without a password."
                )
            best = min(readable, key=_score_ldraw_candidate)
            try:
                return archive.read(best)
            except RuntimeError as exc:
                if "password" in str(exc).lower() or "encrypted" in str(exc).lower():
                    raise UnsupportedLegoModel(
                        "The .io archive is encrypted. Please export without a password."
                    ) from exc
                raise


def _score_ldraw_candidate(info):
    name = info.filename.replace("\\", "/")
    base = PurePosixPath(name).name.lower()
    depth = len(PurePosixPath(name).parts)
    is_model = 0 if base in {"model.ldr", "model.mpd"} else 1
    return (is_model, depth, len(base))


def _convert_lxf_to_ldraw(source_path):
    mode, converter_cmd = _resolve_lxf_converter_settings()
    if mode != "python" and converter_cmd:
        try:
            return _convert_lxf_to_ldraw_with_cli(source_path, converter_cmd)
        except UnsupportedLegoModel:
            if mode != "auto":
                raise

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


_IDENTITY_ROT = [
    [1.0, 0.0, 0.0],
    [0.0, 1.0, 0.0],
    [0.0, 0.0, 1.0],
]

_AXIS_BASIS = [
    [1.0, 0.0, 0.0],
    [0.0, -1.0, 0.0],
    [0.0, 0.0, -1.0],
]


def _axis_angle_to_matrix(ax, ay, az, angle_deg):
    length = math.sqrt(ax * ax + ay * ay + az * az)
    if length < 1e-12:
        return _IDENTITY_ROT
    ux = ax / length
    uy = ay / length
    uz = az / length
    angle = math.radians(angle_deg)
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)
    one_c = 1.0 - cos_a
    return [
        [
            one_c * ux * ux + cos_a,
            one_c * ux * uy - sin_a * uz,
            one_c * ux * uz + sin_a * uy,
        ],
        [
            one_c * ux * uy + sin_a * uz,
            one_c * uy * uy + cos_a,
            one_c * uy * uz - sin_a * ux,
        ],
        [
            one_c * ux * uz - sin_a * uy,
            one_c * uy * uz + sin_a * ux,
            one_c * uz * uz + cos_a,
        ],
    ]


def _apply_axis_basis(rotation, translation):
    rotation = _matmul_3x3(_matmul_3x3(_AXIS_BASIS, rotation), _AXIS_BASIS)
    translation = _matvec_3x3(_AXIS_BASIS, translation)
    return rotation, translation


@lru_cache(maxsize=1)
def _load_ldraw_xml_maps():
    xml_path = finders.find("cli/ldraw.xml")
    if not xml_path:
        return {}, {}, {}
    try:
        root = ElementTree.parse(xml_path).getroot()
    except OSError:
        return {}, {}, {}

    lego_to_part = {}
    lego_to_color = {}
    ldraw_to_transform = {}

    for elem in root.iter():
        tag = _local_name(elem.tag)
        if tag == "Material":
            lego = elem.attrib.get("lego")
            ldraw = elem.attrib.get("ldraw")
            if lego and ldraw and lego.isdigit():
                try:
                    lego_to_color[int(lego)] = int(ldraw)
                except ValueError:
                    continue
        elif tag in {"Brick", "Assembly"}:
            lego = elem.attrib.get("lego")
            ldraw = elem.attrib.get("ldraw") or ""
            if lego and lego.isdigit() and ldraw:
                lego_to_part[int(lego)] = ldraw.lower()
        elif tag == "Transformation":
            ldraw = (elem.attrib.get("ldraw") or "").lower()
            if not ldraw:
                continue
            try:
                tx = float(elem.attrib.get("tx", "0") or "0")
                ty = float(elem.attrib.get("ty", "0") or "0")
                tz = float(elem.attrib.get("tz", "0") or "0")
                ax = float(elem.attrib.get("ax", "0") or "0")
                ay = float(elem.attrib.get("ay", "0") or "0")
                az = float(elem.attrib.get("az", "0") or "0")
                angle = float(elem.attrib.get("angle", "0") or "0")
            except ValueError:
                continue
            rotation = _axis_angle_to_matrix(ax, ay, az, -math.degrees(angle))
            translation = [-tx, -ty, -tz]
            ldraw_to_transform[ldraw] = Transform(translation, rotation)

    return lego_to_part, lego_to_color, ldraw_to_transform


@lru_cache(maxsize=1)
def _load_decors_map():
    yaml_path = finders.find("cli/decors_lxf2ldr.yaml")
    if not yaml_path:
        return {}
    try:
        import yaml
    except ImportError:
        return {}

    try:
        raw = Path(yaml_path).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return {}

    data = yaml.safe_load(raw)
    if not data:
        return {}

    decors = {}
    for lego_key, entry in data.items():
        if entry is None:
            continue
        try:
            lego_id = int(lego_key)
        except (TypeError, ValueError):
            continue

        usecolor = int(entry.get("usecolor", 0) or 0)
        colors = _parse_decor_colors(entry.get("colors"))
        decorations = _parse_decor_decorations(entry.get("decorations"))
        decors[lego_id] = DecorMatch(usecolor, colors, decorations)

    return decors


def _parse_decor_colors(node):
    if node is None:
        return []
    colors = []
    for item in node:
        if item is None:
            colors.append({})
            continue
        if not isinstance(item, dict):
            colors.append({})
            continue
        colormap = {}
        for key, value in item.items():
            try:
                color_id = int(key)
            except (TypeError, ValueError):
                continue
            if value is None:
                continue
            parts = str(value).split()
            if not parts:
                continue
            datfile = parts[0].lower()
            overwrite = len(parts) > 1 and parts[1].upper() == "OW"
            colormap[color_id] = SimpleSubstitute(datfile, overwrite)
        colors.append(colormap)
    return colors


def _parse_decor_decorations(node):
    if node is None:
        return {}

    local_rot = {
        "x": _axis_angle_to_matrix(1, 0, 0, 90),
        "xx": _axis_angle_to_matrix(1, 0, 0, 180),
        "xxx": _axis_angle_to_matrix(1, 0, 0, -90),
        "y": _axis_angle_to_matrix(0, 1, 0, 90),
        "yy": _axis_angle_to_matrix(0, 1, 0, 180),
        "yyy": _axis_angle_to_matrix(0, 1, 0, -90),
        "z": _axis_angle_to_matrix(0, 0, 1, 90),
        "zz": _axis_angle_to_matrix(0, 0, 1, 180),
        "zzz": _axis_angle_to_matrix(0, 0, 1, -90),
    }
    special_rot = re.compile(r"\A([xyz])(\d+)\Z")

    decorations = {}
    for key, value in node.items():
        if value is None:
            continue
        parts = str(value).split()
        if not parts:
            continue
        datfile = parts[0].lower()
        rotation = parts[1] if len(parts) > 1 else ""

        transform = None
        if rotation in local_rot:
            transform = Transform([0.0, 0.0, 0.0], local_rot[rotation])
        else:
            match = special_rot.match(rotation)
            if match:
                axis = match.group(1)
                angle = float(match.group(2))
                if axis == "x":
                    rot = _axis_angle_to_matrix(1, 0, 0, angle)
                elif axis == "y":
                    rot = _axis_angle_to_matrix(0, 1, 0, angle)
                else:
                    rot = _axis_angle_to_matrix(0, 0, 1, angle)
                transform = Transform([0.0, 0.0, 0.0], rot)

        decorations[str(key)] = Substitute(datfile, transform)

    return decorations


@lru_cache(maxsize=1)
def _load_flex_map():
    yaml_path = finders.find("cli/flex_lxf2ldr.yaml")
    if not yaml_path:
        return {}
    try:
        import yaml
    except ImportError:
        return {}

    try:
        raw = Path(yaml_path).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return {}

    data = yaml.safe_load(raw)
    if not data:
        return {}

    flex = {}
    for lego_key, entry in data.items():
        if entry is None:
            continue
        try:
            lego_id = int(lego_key)
        except (TypeError, ValueError):
            continue
        if not isinstance(entry, dict):
            continue

        flex_type = str(entry.get("type", "") or "")
        head = _parse_flex_counted(entry.get("head"))
        body = _parse_flex_bicounted(entry.get("body"))
        tail = _parse_flex_counted(entry.get("tail"))
        head_plus = _parse_flex_substitute(entry.get("head+"))
        tail_plus = _parse_flex_substitute(entry.get("tail+"))
        flex[lego_id] = Flexible(flex_type, head, body, tail, head_plus, tail_plus)

    return flex


def _parse_flex_transformation(value):
    if not value:
        return None
    parts = str(value).split(",")
    if len(parts) != 7:
        return None
    try:
        tx, ty, tz, ax, ay, az, angle = [float(part) for part in parts]
    except ValueError:
        return None
    rotation = _axis_angle_to_matrix(ax, ay, az, angle)
    return Transform([tx, ty, tz], rotation)


def _parse_flex_counted(value):
    if not value:
        return None
    parts = str(value).split()
    try:
        count = int(parts[0])
    except (IndexError, ValueError):
        return None
    transform = _parse_flex_transformation(parts[1]) if len(parts) > 1 else None
    return Counted(count, transform)


def _parse_flex_bicounted(value):
    if not value:
        return None
    parts = str(value).split()
    counts = parts[0].split(",")
    if len(counts) != 2:
        return None
    try:
        before = int(counts[0])
        after = int(counts[1])
    except ValueError:
        return None
    transform = _parse_flex_transformation(parts[1]) if len(parts) > 1 else None
    return BiCounted(before, after, transform)


def _parse_flex_substitute(value):
    if not value:
        return None
    parts = str(value).split()
    if not parts:
        return None
    datfile = parts[0].lower()
    transform = _parse_flex_transformation(parts[1]) if len(parts) > 1 else None
    return Substitute(datfile, transform)


def _resolve_decor_substitute(lego_id, decorations, colors):
    decors = _load_decors_map()
    decor = decors.get(lego_id)
    if not decor:
        return ColorSubstitute(0, None)

    substitute = None
    maxcol = min(len(colors), len(decor.colors))
    for idx in range(maxcol):
        cur_color = colors[idx] if colors[idx] != 0 else colors[0]
        color_map = decor.colors[idx]
        if cur_color in color_map:
            candidate = color_map[cur_color]
            if substitute is None or candidate.overwrite:
                substitute = Substitute(candidate.datfile, None)

    if decorations in decor.decorations:
        substitute = decor.decorations[decorations]

    return ColorSubstitute(decor.usecolor, substitute)


def _extract_lxf_colors(part):
    materials = (part.attrib.get("materials") or "").strip()
    if not materials:
        return []
    colors = []
    for token in materials.split(","):
        token = token.split(":", 1)[0].strip()
        if not token:
            continue
        try:
            colors.append(int(token))
        except ValueError:
            continue
    return colors


def _extract_lxf_part_transforms(part):
    positions = []
    rotations = []
    for bone in list(part):
        if _local_name(bone.tag) != "Bone":
            continue
        numbers = _parse_number_list(bone.attrib.get("transformation") or "")
        if len(numbers) not in {12, 16}:
            continue
        rotation, translation = _normalize_transform(numbers)
        positions.append(translation)
        rotations.append(rotation)

    if not positions:
        numbers = _find_transform_numbers(part)
        if numbers:
            rotation, translation = _normalize_transform(numbers)
            positions.append(translation)
            rotations.append(rotation)

    return positions, rotations


def _compose_ldraw_transform(ldd_pos, ldd_rot, x2l_tr, local_tr, scale, axis_conversion):
    x2l_rot = x2l_tr.rotation if x2l_tr else _IDENTITY_ROT
    x2l_trans = x2l_tr.translation if x2l_tr else [0.0, 0.0, 0.0]
    local_rot = local_tr.rotation if local_tr else _IDENTITY_ROT
    local_trans = local_tr.translation if local_tr else [0.0, 0.0, 0.0]

    rot_base = _matmul_3x3(ldd_rot, x2l_rot)
    move = [
        local_trans[0] + x2l_trans[0],
        local_trans[1] + x2l_trans[1],
        local_trans[2] + x2l_trans[2],
    ]
    pos = _vec_add(ldd_pos, _matvec_3x3(rot_base, move))
    rot_final = _matmul_3x3(rot_base, local_rot)

    if axis_conversion:
        rot_final, pos = _apply_axis_basis(rot_final, pos)

    if scale:
        pos = [value * scale for value in pos]
    return rot_final, pos


def _format_ldraw_line(color, part, ldd_pos, ldd_rot, x2l_tr, local_tr, scale, axis_conversion):
    rotation, translation = _compose_ldraw_transform(
        ldd_pos, ldd_rot, x2l_tr, local_tr, scale, axis_conversion
    )
    a, b, c = rotation[0]
    d, e, f = rotation[1]
    g, h, i = rotation[2]
    x, y, z = translation
    return (
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
            part=part,
        )
    )


def _format_flexnode(ldd_pos, ldd_rot, x2l_tr, local_tr, scale, axis_conversion):
    rotation, translation = _compose_ldraw_transform(
        ldd_pos, ldd_rot, x2l_tr, local_tr, scale, axis_conversion
    )
    a, b, c = rotation[0]
    d, e, f = rotation[1]
    g, h, i = rotation[2]
    x, y, z = translation
    return (
        "0 LXF2LDR FLEXNODE {x} {y} {z} {a} {b} {c} {d} {e} {f} {g} {h} {i}".format(
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
        )
    )


def _convert_lxf_to_ldraw_python(source_path):
    lxfml_bytes = _extract_lxfml_bytes(source_path)
    try:
        root = ElementTree.fromstring(lxfml_bytes)
    except ElementTree.ParseError as exc:
        raise UnsupportedLegoModel("Invalid LXFML payload.") from exc

    ldraw_parts, ldraw_colors, ldraw_transforms = _load_ldraw_xml_maps()
    fallback_colors = _load_ldd_to_ldraw_color_map()
    flex_map = _load_flex_map()
    scale = float(os.environ.get("LXF_LDRAW_SCALE", "25") or "25")
    apply_axis_conversion = os.environ.get("LXF_LDRAW_AXIS_CONVERT", "1") != "0"

    lines = [
        "0 Generated from LXF",
        "0 Name: model.ldr",
        "0 Author: web3d",
    ]

    for part in _iter_elements(root, "Part"):
        design_id = (part.attrib.get("designID") or "").split(";", 1)[0].strip()
        if not design_id or not design_id.isdigit():
            continue
        lego_id = int(design_id)
        colors = _extract_lxf_colors(part)
        if not colors:
            continue

        decorations = (part.attrib.get("decoration") or "").strip()
        positions, rotations = _extract_lxf_part_transforms(part)
        if not positions:
            continue

        part_filename = ldraw_parts.get(lego_id, f"{lego_id}.dat")
        x2l_tr = ldraw_transforms.get(part_filename)

        csub = _resolve_decor_substitute(lego_id, decorations, colors)
        if csub.substitute and csub.substitute.datfile:
            part_filename = csub.substitute.datfile

        def map_color(value):
            if value in ldraw_colors:
                return ldraw_colors[value]
            if value in fallback_colors:
                return fallback_colors[value]
            return value

        main_color = map_color(colors[0])
        mapped_colors = []
        for color in colors:
            mapped_colors.append(map_color(color) if color else main_color)

        usecolor = csub.usecolor if csub.usecolor < len(mapped_colors) else 0
        main_color = mapped_colors[usecolor]

        if len(rotations) == 1:
            lines.append(
                _format_ldraw_line(
                    main_color,
                    part_filename,
                    positions[0],
                    rotations[0],
                    x2l_tr,
                    csub.substitute.transformation if csub.substitute else None,
                    scale,
                    apply_axis_conversion,
                )
            )
            continue

        lines.append("0 LXF2LDR BEGIN FLEXIBLE PART")

        flex = flex_map.get(lego_id)
        if not flex:
            lines.append(
                _format_ldraw_line(
                    main_color,
                    part_filename,
                    positions[0],
                    rotations[0],
                    x2l_tr,
                    csub.substitute.transformation if csub.substitute else None,
                    scale,
                    apply_axis_conversion,
                )
            )
            for idx in range(1, len(rotations)):
                lines.append(
                    _format_flexnode(
                        positions[idx],
                        rotations[idx],
                        x2l_tr,
                        csub.substitute.transformation if csub.substitute else None,
                        scale,
                        apply_axis_conversion,
                    )
                )
            lines.append("0 LXF2LDR END FLEXIBLE PART")
            continue

        color_ends = mapped_colors[1] if len(mapped_colors) > 1 else main_color

        if flex.head_plus:
            lines.append(
                _format_ldraw_line(
                    color_ends,
                    flex.head_plus.datfile,
                    positions[0],
                    rotations[0],
                    None,
                    flex.head_plus.transformation,
                    scale,
                    apply_axis_conversion,
                )
            )

        if flex.type:
            lines.append(f"0 SYNTH BEGIN {flex.type} {int(main_color)}")
        else:
            lines.append(f"0 SYNTH BEGIN  {int(main_color)}")

        max_count = len(rotations)
        if flex.head:
            for idx in range(min(flex.head.count, max_count)):
                lines.append(
                    _format_ldraw_line(
                        2,
                        "ls01.dat",
                        positions[idx],
                        rotations[idx],
                        None,
                        flex.head.transformation,
                        scale,
                        apply_axis_conversion,
                    )
                )
        if flex.body:
            start = max(0, flex.body.before)
            end = max(0, max_count - flex.body.after)
            for idx in range(start, min(end, max_count)):
                lines.append(
                    _format_ldraw_line(
                        main_color,
                        "ls01.dat",
                        positions[idx],
                        rotations[idx],
                        None,
                        flex.body.transformation,
                        scale,
                        apply_axis_conversion,
                    )
                )
        if flex.tail:
            start = max(0, max_count - flex.tail.count)
            for idx in range(start, max_count):
                lines.append(
                    _format_ldraw_line(
                        4,
                        "ls01.dat",
                        positions[idx],
                        rotations[idx],
                        None,
                        flex.tail.transformation,
                        scale,
                        apply_axis_conversion,
                    )
                )

        lines.append("0 SYNTH END")

        if flex.tail_plus:
            lines.append(
                _format_ldraw_line(
                    color_ends,
                    flex.tail_plus.datfile,
                    positions[-1],
                    rotations[-1],
                    None,
                    flex.tail_plus.transformation,
                    scale,
                    apply_axis_conversion,
                )
            )

        lines.append("0 LXF2LDR END FLEXIBLE PART")

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
        mode, cmd = _resolve_lxf_converter_settings()
        if mode == "python" or not cmd:
            return _lxf_python_variant()
        return _lxf_cli_variant(cmd)
    return ext


def _resolve_lxf_converter_settings():
    mode = (os.environ.get("LXF_CONVERTER_MODE", "auto") or "auto").strip().lower()
    if mode not in {"auto", "cli", "python"}:
        mode = "auto"
    cmd = (os.environ.get("LXF_CONVERTER_CMD") or "").strip()
    if mode == "auto" and not cmd:
        cmd = _detect_lxf_converter_cmd()
    return mode, cmd


def _lxf_python_variant():
    scale = (os.environ.get("LXF_LDRAW_SCALE", "25") or "25").strip()
    axis = (os.environ.get("LXF_LDRAW_AXIS_CONVERT", "1") or "1").strip()
    key = f"py|v={LXF_PY_CONVERTER_VERSION}|scale={scale}|axis={axis}"
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:8]
    return f"lxf-py-{digest}"


def _lxf_cli_variant(cmd):
    key = f"cli|cmd={cmd}"
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:8]
    return f"lxf-cli-{digest}"


def _lxf_cache_variants_for_mode(mode, cmd):
    if mode == "cli":
        return [_lxf_cli_variant(cmd)] if cmd else []
    if mode == "python" or not cmd:
        return [_lxf_python_variant()]
    return [_lxf_cli_variant(cmd), _lxf_python_variant()]


def _get_cached_lxf_model_path(*, content_id, source_path):
    mode, cmd = _resolve_lxf_converter_settings()
    variants = _lxf_cache_variants_for_mode(mode, cmd)
    for variant in variants:
        cache_path = f"derived/lego/{content_id}/model-{variant}.ldr"
        if default_storage.exists(cache_path):
            return cache_path

    if mode != "python" and cmd:
        try:
            model_bytes = _convert_lxf_to_ldraw_with_cli(source_path, cmd)
            variant = _lxf_cli_variant(cmd)
        except UnsupportedLegoModel:
            if mode != "auto":
                raise
            model_bytes = _convert_lxf_to_ldraw_python(source_path)
            variant = _lxf_python_variant()
    else:
        if mode == "cli":
            raise UnsupportedLegoModel(
                "LXF conversion requires an external converter. Set LXF_CONVERTER_CMD "
                "(e.g. lxf2ldr/ldd2ldraw)."
            )
        model_bytes = _convert_lxf_to_ldraw_python(source_path)
        variant = _lxf_python_variant()

    cache_path = f"derived/lego/{content_id}/model-{variant}.ldr"
    default_storage.save(cache_path, ContentFile(model_bytes))
    return cache_path


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
        rotation = [
            [numbers[0], numbers[3], numbers[6]],
            [numbers[1], numbers[4], numbers[7]],
            [numbers[2], numbers[5], numbers[8]],
        ]
        translation = [numbers[9], numbers[10], numbers[11]]
        return rotation, translation

    if len(numbers) == 16:
        rotation = [
            [numbers[0], numbers[4], numbers[8]],
            [numbers[1], numbers[5], numbers[9]],
            [numbers[2], numbers[6], numbers[10]],
        ]
        translation = [numbers[12], numbers[13], numbers[14]]
        return rotation, translation

    raise UnsupportedLegoModel("Unsupported transform matrix size.")


def _convert_ldd_axes_to_ldraw(rotation, translation):
    return _apply_axis_basis(rotation, translation)


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


def _vec_add(left, right):
    return [
        left[0] + right[0],
        left[1] + right[1],
        left[2] + right[2],
    ]


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
