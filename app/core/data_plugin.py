"""Data-only authoring: JSON + GLB/glTF become ordinary Component callables.

There is no plugin code path here. Definitions translate to the existing
dataclasses; the sole geometric parameter vocabulary is positive axis/uniform
scaling. Meshes are loaded once, with node transforms baked, and copied for
each build. External glTF resources are preloaded through a confined reader;
trimesh receives only bytes and a dictionary, never a filesystem/network
resolver. Geometry quality remains the responsibility of build.validate.
"""
from __future__ import annotations

import copy
import io
import json
import math
from pathlib import Path, PureWindowsPath
import struct
from urllib.parse import unquote, urlsplit

import numpy as np
import trimesh

from app.core.authoring import ASSI, verify_frame
from app.core.capability import SIDES, Capability, Mount, Requirement
from app.core.component import Attachment, BuildContext, Component, Piece
from app.core.layout import LayoutRegion
from app.core.material import MaterialSpec, default_material
from app.core.params import ParamSpec
from app.core.socket import SCALE_MODES, Socket


class DataPluginError(ValueError):
    """A stable diagnostic code plus a message for Registry's report."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def _error(message: str, code: str = "DATA_SCHEMA_INVALID"):
    raise DataPluginError(code, message)


def safe_path(root: Path, relative: str | Path, base: Path | None = None) -> Path:
    """Resolve a relative resource, permitting '..' only inside plugin root.

    Both Windows and POSIX absolute paths are rejected on every platform;
    resolve() checks symlink/junction targets, not just lexical prefixes.
    """
    value = str(relative)
    if (not value or "\x00" in value or ":" in value or
            Path(value).is_absolute() or PureWindowsPath(value).is_absolute() or
            PureWindowsPath(value).drive or value.startswith(("/", "\\"))):
        _error("Risorsa non relativa al plugin: %r" % value, "DATA_PATH_UNSAFE")
    try:
        boundary = Path(root).resolve()
        anchor = (Path(base) if base is not None else boundary).resolve()
        candidate = (anchor / value.replace("\\", "/")).resolve()
        if not anchor.is_relative_to(boundary) or not candidate.is_relative_to(boundary):
            _error("Risorsa fuori dalla directory del plugin: %r" % value,
                   "DATA_PATH_UNSAFE")
        return candidate
    except (OSError, RuntimeError, ValueError) as exc:
        if isinstance(exc, DataPluginError):
            raise
        _error("Percorso non valido %r: %s" % (value, exc), "DATA_PATH_UNSAFE")


def _inside_file(path: Path, root: Path) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = safe_path(root, candidate)
    try:
        candidate = candidate.resolve()
        if not candidate.is_relative_to(Path(root).resolve()):
            _error("File fuori dalla directory del plugin: %s" % path,
                   "DATA_PATH_UNSAFE")
    except (OSError, RuntimeError) as exc:
        _error("Percorso non valido: %s" % exc, "DATA_PATH_UNSAFE")
    if not candidate.is_file():
        _error("File del plugin mancante: %s" % candidate, "DATA_FILE_MISSING")
    return candidate


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _error("Chiave JSON duplicata: %s" % key)
        result[key] = value
    return result


def _json(raw: bytes, where: str):
    try:
        return json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_pairs,
                          parse_constant=lambda v: _error(
                              "Numero JSON non finito: " + v, "DATA_JSON_INVALID"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        _error("JSON non valido in %s: %s" % (where, exc), "DATA_JSON_INVALID")


def _object(value, allowed, where):
    if not isinstance(value, dict):
        _error("%s deve essere un oggetto JSON" % where)
    unknown = set(value) - set(allowed)
    if unknown:
        _error("%s: campi non supportati: %s" % (where, ", ".join(sorted(unknown))))
    return dict(value)


def _string(value, where, *, nonempty=False):
    if not isinstance(value, str) or (nonempty and not value.strip()):
        _error("%s deve essere una stringa%s" % (where, " non vuota" if nonempty else ""))
    return value


def _list(value, where):
    if not isinstance(value, list):
        _error("%s deve essere una lista" % where)
    return value


def _strings(value, where):
    return tuple(_string(v, where, nonempty=True) for v in _list(value, where))


def _number(value, where, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        _error("%s deve essere un numero finito" % where)
    if positive and value <= 0:
        _error("%s deve essere positivo" % where)
    return float(value)


def _integer(value, where, *, minimum=0):
    if type(value) is not int or value < minimum:
        _error("%s deve essere un intero >= %s" % (where, minimum))
    return value


def _boolean(value, where):
    if type(value) is not bool:
        _error("%s deve essere booleano" % where)
    return value


def _vector(value, where):
    values = _list(value, where)
    if len(values) != 3:
        _error("%s deve contenere tre coordinate" % where)
    return np.array([_number(v, where) for v in values])


def _capabilities(value, where):
    result = []
    for item in _list(value, where):
        if isinstance(item, str):
            result.append(Capability(_string(item, where, nonempty=True)))
        else:
            data = _object(item, ("name", "tags"), where)
            result.append(Capability(_string(data.get("name"), where, nonempty=True),
                                     _strings(data.get("tags", []), where)))
    return tuple(result)


def _contract(value, kind, where):
    fields = ("capability", "socket_id", "side", "tags", "description", "allow_fallback")
    data = _object(value, (*fields, "capacity") if kind is Mount else fields, where)
    for key in ("capability", "socket_id", "side", "description"):
        if key in data:
            _string(data[key], where + "." + key)
    if data.get("side", "") not in ("", *SIDES):
        _error("%s: lato sconosciuto" % where)
    if "tags" in data:
        data["tags"] = _strings(data["tags"], where + ".tags")
    if "allow_fallback" in data:
        _boolean(data["allow_fallback"], where + ".allow_fallback")
    if "capacity" in data:
        _integer(data["capacity"], where + ".capacity")
    if kind is Mount:
        _string(data.get("capability"), where + ".capability", nonempty=True)
    return kind(**data)


def _socket(value):
    data = _object(value, ("name", "position", "direction", "up", "radius",
                           "capabilities", "side", "tags"), "socket")
    name = _string(data.get("name"), "socket.name", nonempty=True)
    position = _vector(data.get("position"), name + ".position")
    direction = _vector(data.get("direction"), name + ".direction")
    up = _vector(data.get("up", [0, 1, 0]), name + ".up")
    if np.linalg.norm(direction) < 1e-9 or np.linalg.norm(up) < 1e-9 or np.linalg.norm(np.cross(direction, up)) < 1e-9:
        _error("Socket %s: direction/up devono essere non nulli e non paralleli" % name,
               "DATA_FRAME_INVALID")
    side = _string(data.get("side", ""), name + ".side")
    if side not in ("", *SIDES):
        _error("Socket %s: lato sconosciuto" % name)
    return Socket(name=name, position=position, direction=direction, up=up,
                  radius=_number(data.get("radius", .1), name + ".radius", positive=True),
                  capabilities=_capabilities(data.get("capabilities", []), name + ".capabilities"),
                  side=side, tags=_strings(data.get("tags", []), name + ".tags"))


def _params(value):
    if not isinstance(value, dict):
        _error("params deve essere un oggetto")
    specs, transforms = {}, {}
    for name, item in value.items():
        data = _object(item, ("default", "type", "min", "max", "unit", "description",
                              "semantic_role", "required", "transform"), "params." + name)
        transform = data.pop("transform", None)
        if transform not in ("scale_x", "scale_y", "scale_z", "uniform_scale"):
            _error("Parametro %s: dichiarare transform scale_x/scale_y/scale_z/uniform_scale" % name,
                   "DATA_PARAM_UNSUPPORTED")
        if data.get("type", "float") not in ("float", "ratio", "int"):
            _error("Parametro %s: una scala richiede float, ratio o int" % name,
                   "DATA_PARAM_UNSUPPORTED")
        data["default"] = _number(data.get("default", 1), name + ".default", positive=True)
        for key in ("min", "max"):
            if key in data and data[key] is not None:
                _number(data[key], name + "." + key, positive=True)
        if data.get("min") is not None and data.get("max") is not None and data["min"] > data["max"]:
            _error("Parametro %s: min supera max" % name)
        if ((data.get("min") is not None and data["default"] < data["min"]) or
                (data.get("max") is not None and data["default"] > data["max"])):
            _error("Parametro %s: default fuori intervallo" % name)
        for key in ("unit", "description", "semantic_role"):
            if key in data:
                _string(data[key], name + "." + key)
        if "required" in data:
            _boolean(data["required"], name + ".required")
        specs[name], transforms[name] = ParamSpec(**data), transform
    return specs, transforms


def _attachment(value):
    data = _object(value, ("id", "component", "requirement", "own_socket", "level", "optional",
                           "on_request", "replaces", "replaces_parent", "on", "scale_mode",
                           "insert", "roll", "params", "material", "tags"), "child")
    for key in ("id", "component"):
        _string(data.get(key), "child." + key, nonempty=True)
    for key in ("own_socket", "replaces", "on", "scale_mode", "material"):
        if key in data:
            _string(data[key], "child." + key)
    if data.get("scale_mode", "none") not in SCALE_MODES:
        _error("child.scale_mode non supportato")
    if "requirement" in data:
        data["requirement"] = _contract(data["requirement"], Requirement, "child.requirement")
    if "level" in data:
        _integer(data["level"], "child.level", minimum=1)
    for key in ("optional", "on_request", "replaces_parent"):
        if key in data:
            _boolean(data[key], "child." + key)
    for key in ("insert", "roll"):
        if key in data:
            _number(data[key], "child." + key)
    if "tags" in data:
        data["tags"] = _strings(data["tags"], "child.tags")
    params = data.get("params", {})
    if not isinstance(params, dict):
        _error("child.params deve essere un oggetto di valori letterali")
    for name, value in params.items():
        # A string is a literal enum/string, never an expression. The existing
        # resolver only evaluates ParamSpec.derived, which this loader forbids.
        if isinstance(value, list):
            for item in value:
                _number(item, "child.params." + name)
        elif not isinstance(value, (str, bool)):
            _number(value, "child.params." + name)
    return Attachment(**data)


def _region(value):
    """A declared layout region: the same dataclass a Python plugin returns.

    Regions are static data here. A procedural component may compute them from
    its parameters; a fixed mesh has nothing to compute them from.
    """
    numbers = ("capacity", "span", "spread_angle", "min_spacing", "min_scale",
               "max_scale", "elevation_span", "depth_offset")
    vectors = ("center", "direction", "up", "axis")
    data = _object(value, ("id", "anchor_socket", "allows_role", "allows_capability",
                           "allows_tags", "default_policy", "allowed_policies",
                           "allow_scale_to_fit", "symmetry_group", "side",
                           *numbers, *vectors), "layout_region")
    _string(data.get("id"), "layout_region.id", nonempty=True)
    for key in ("anchor_socket", "allows_role", "allows_capability",
                "default_policy", "symmetry_group", "side"):
        if key in data:
            _string(data[key], "layout_region." + key)
    if data.get("side", "") not in ("", *SIDES):
        _error("layout_region.side: lato sconosciuto")
    for key in ("allows_tags", "allowed_policies"):
        if key in data:
            data[key] = _strings(data[key], "layout_region." + key)
    if "allow_scale_to_fit" in data:
        _boolean(data["allow_scale_to_fit"], "layout_region.allow_scale_to_fit")
    if "capacity" in data:
        data["capacity"] = _integer(data["capacity"], "layout_region.capacity")
    for key in numbers:
        if key in data and key != "capacity":
            data[key] = _number(data[key], "layout_region." + key)
    for key in vectors:
        if key in data:
            data[key] = tuple(_vector(data[key], "layout_region." + key).tolist())
    if "default_policy" in data and "allowed_policies" not in data:
        data["allowed_policies"] = (data["default_policy"],)
    region = LayoutRegion(**data)
    errors = region.validate()
    if errors:
        _error("layout_region %s non valida: %s" % (region.id, ", ".join(errors)))
    return region


def _frame(value):
    data = _object(value, ("growth_axis", "front", "up"), "frame")
    for name, axis in data.items():
        if axis not in ASSI:
            _error("frame.%s: asse atteso fra %s" % (name, ", ".join(ASSI)),
                   "DATA_FRAME_INVALID")
    if "front" in data and "up" in data and abs(ASSI[data["front"]] @ ASSI[data["up"]]) > 0:
        _error("frame.front e frame.up devono essere ortogonali", "DATA_FRAME_INVALID")
    return data


def _gltf_document(raw: bytes, suffix: str, where: str):
    if suffix == ".gltf":
        result = _json(raw, where)
    else:
        if len(raw) < 20:
            _error("GLB troncato: " + where, "DATA_MESH_INVALID")
        magic, version, length, size, kind = struct.unpack_from("<4sIIII", raw)
        if magic != b"glTF" or version != 2 or length != len(raw) or kind != 0x4E4F534A or size > len(raw) - 20:
            _error("Header GLB non valido: " + where, "DATA_MESH_INVALID")
        result = _json(raw[20:20 + size], where)
    if not isinstance(result, dict) or result.get("asset", {}).get("version") != "2.0":
        _error("Richiesto glTF 2.0: " + where, "DATA_MESH_INVALID")
    return result


def _resources(document, mesh_path, root):
    resources, paths = {}, []

    def visit(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "uri":
                    uri = _string(item, "glTF uri", nonempty=True)
                    if uri.startswith("data:"):
                        if ";base64," not in uri:
                            _error("glTF supporta solo data URI base64", "DATA_MESH_INVALID")
                        continue
                    decoded = unquote(uri)
                    parsed = urlsplit(decoded)
                    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
                        _error("URI glTF non locale: %s" % uri, "DATA_PATH_UNSAFE")
                    path = _inside_file(safe_path(root, decoded, base=mesh_path.parent), root)
                    resources[uri] = path.read_bytes()
                    paths.append(path)
                else:
                    visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(document)
    return resources, paths


def _face_colors(mesh):
    if not mesh.visual.defined:
        return None
    try:
        visual = mesh.visual.to_color() if mesh.visual.kind == "texture" else mesh.visual
        if visual.kind == "vertex":
            return np.asarray(visual.vertex_colors)[mesh.faces].mean(axis=1).astype(np.uint8)
        if visual.kind == "face":
            return np.asarray(visual.face_colors).copy()
    except (ValueError, TypeError, IndexError, AttributeError):
        pass
    # A plain PBR baseColorFactor can exist without UVs or per-vertex data.
    material = getattr(mesh.visual, "material", None)
    color = getattr(material, "baseColorFactor", None)
    if color is None:
        color = getattr(material, "diffuse", None)
    if color is not None and np.asarray(color).shape == (4,):
        return np.tile(np.asarray(color, dtype=np.uint8), (len(mesh.faces), 1))
    return None


def _load_mesh(path, root):
    suffix = path.suffix.lower()
    if suffix not in (".glb", ".gltf"):
        _error("Formato mesh non supportato: %s (GLB/glTF soltanto)" % suffix,
               "DATA_MESH_FORMAT")
    path = _inside_file(path, root)
    try:
        raw = path.read_bytes()
        document = _gltf_document(raw, suffix, str(path))
        resources, paths = _resources(document, path, root)
        loaded = trimesh.load(io.BytesIO(raw), file_type=suffix[1:], resolver=resources,
                              force="scene", process=False, allow_remote=False)
        meshes, colors = [], []
        for node in sorted(loaded.graph.nodes_geometry):
            transform, geometry_name = loaded.graph[node]
            source = loaded.geometry[geometry_name]
            if not isinstance(source, trimesh.Trimesh):
                _error("Il glTF contiene geometria non triangolare", "DATA_MESH_INVALID")
            if len(source.vertices) == 0 or len(source.faces) == 0:
                _error("Primitiva glTF vuota: " + str(node), "DATA_MESH_EMPTY")
            mesh = source.copy()
            face_colors = _face_colors(mesh)
            mesh.apply_transform(transform)
            meshes.append(mesh)
            colors.append(face_colors)
        if not meshes:
            _error("La scena GLB/glTF non contiene triangoli", "DATA_MESH_EMPTY")
        # Explicit construction avoids visual concatenation inventing a
        # default material, and leaves malformed geometry to the quality gate.
        vertices, faces = trimesh.util.append_faces([m.vertices for m in meshes],
                                                    [m.faces for m in meshes])
        merged = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
        usable = any(c is not None for c in colors)
        if usable:
            fallback = np.round(np.array(default_material().rgba()) * 255).astype(np.uint8)
            merged.visual.face_colors = np.vstack([
                c if c is not None else np.tile(fallback, (len(m.faces), 1))
                for m, c in zip(meshes, colors)])
        return merged, usable, tuple([path, *paths])
    except DataPluginError:
        raise
    except Exception as exc:
        _error("Mesh GLB/glTF non valida in %s: %s" % (path, exc), "DATA_MESH_INVALID")


def load_material(path: Path, plugin_root: Path) -> MaterialSpec:
    path = _inside_file(path, plugin_root)
    data = _object(_json(path.read_bytes(), str(path)),
                   ("name", "base_color", "roughness", "metallic", "opacity", "description"),
                   "material")
    _string(data.get("name"), "material.name", nonempty=True)
    for key in ("base_color", "description"):
        if key in data:
            _string(data[key], "material." + key)
    for key in ("roughness", "metallic", "opacity"):
        if key in data:
            _number(data[key], "material." + key)
    try:
        return MaterialSpec(**data)
    except ValueError as exc:
        _error("Materiale non valido: %s" % exc)


def load_component(path: Path, plugin_root: Path) -> Component:
    """Read a component definition and return the existing Component model."""
    path = _inside_file(path, plugin_root)
    data = _object(_json(path.read_bytes(), str(path)),
                   ("id", "name", "description", "mesh", "role", "tags", "provides", "mounts",
                    "sockets", "params", "material", "children", "requires", "styles",
                    "frame", "layout_regions"),
                   "component")
    component_id = _string(data.get("id"), "component.id", nonempty=True)
    if ":" not in component_id or not all(component_id.split(":")):
        _error("component.id deve essere qualificato plugin:nome")
    mesh_path = safe_path(plugin_root, _string(data.get("mesh"), "mesh", nonempty=True), base=path.parent)
    mesh, usable_colors, files = _load_mesh(mesh_path, plugin_root)
    sockets = [_socket(item) for item in _list(data.get("sockets", []), "sockets")]
    if len({s.name for s in sockets}) != len(sockets):
        _error("Nomi socket duplicati")
    specs, transforms = _params(data.get("params", {}))
    children = [_attachment(item) for item in _list(data.get("children", []), "children")]
    if len({c.id for c in children}) != len(children):
        _error("Id child duplicati")
    regions = tuple(_region(item) for item in
                    _list(data.get("layout_regions", []), "layout_regions"))
    if len({r.id for r in regions}) != len(regions):
        _error("Id layout_region duplicati")
    for region in regions:
        if region.anchor_socket and region.anchor_socket not in {s.name for s in sockets}:
            _error("layout_region %s: innesto di ancoraggio inesistente: %s"
                   % (region.id, region.anchor_socket))
    frame = _frame(data.get("frame", {}))
    material = _string(data.get("material", "" if usable_colors else "default"), "material")
    tags = _strings(data.get("tags", []), "tags")

    def build(values: dict, ctx: BuildContext) -> Piece:
        scale = np.ones(3)
        for name, transform in transforms.items():
            factor = _number(values.get(name, specs[name].default), name, positive=True)
            if transform == "uniform_scale":
                scale *= factor
            else:
                scale["xyz".index(transform[-1])] *= factor
        result_mesh = mesh.copy()
        result_mesh.vertices = np.asarray(result_mesh.vertices) * scale
        result_sockets = {}
        for source in sockets:
            # A scalar radius represents the area of the deformed socket disc:
            # use its equivalent-circle radius under the same affine scale.
            area_scale = np.prod(scale) * np.linalg.norm(source.direction / scale)
            result_sockets[source.name] = Socket(
                name=source.name, position=source.position * scale,
                direction=source.direction * scale, up=source.up * scale,
                radius=source.radius * math.sqrt(area_scale),
                capabilities=source.capabilities, side=source.side, tags=source.tags)
        piece = Piece(mesh=result_mesh, sockets=result_sockets, material=material, tags=tags,
                      metadata={"frame": dict(frame)} if frame else {})
        if "growth_axis" in frame:
            report = verify_frame(piece, frame["growth_axis"], name=component_id)
            if ctx.report is not None:
                ctx.report.extend(report)
            if report:
                piece.metadata["frame_diagnostics"] = [d.code for d in report]
        return piece

    description = _string(data.get("description", ""), "description")
    if "name" in data:
        # Component.name is deliberately id-derived. Preserve the artist's
        # display name in searchable description without a parallel model.
        description = (_string(data["name"], "name", nonempty=True) + ". " + description).strip()
    component = Component(
        id=component_id, build=build, params=specs,
        children=(lambda values, ctx: copy.deepcopy(children)) if children else None,
        provides=_capabilities(data.get("provides", []), "provides"),
        mounts=tuple(_contract(item, Mount, "mount") for item in _list(data.get("mounts", []), "mounts")),
        tags=tags, role=_string(data.get("role", ""), "role"),
        requires=_strings(data.get("requires", []), "requires"), material=material,
        description=description, styles=_strings(data.get("styles", []), "styles"),
        layout_regions=regions)
    # Registry uses these safe inputs for identity/fingerprint invalidation.
    # This is loader provenance, not a geometry backend flag.
    component._data_files = tuple(dict.fromkeys([path, *files]))
    return component
