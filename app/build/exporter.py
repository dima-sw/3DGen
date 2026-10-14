"""Export e controllo qualita' del modello generato."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from app.core.config import SETTINGS
from app.core.logging_setup import get
from app.core.scene import Scene

log = get("exporter")

FORMATS = {
    "glb": "Modello glTF binario (consigliato: web, Unity, Unreal, Godot)",
    "obj": "Wavefront OBJ (compatibilita massima)",
    "stl": "STL (stampa 3D, nessun materiale)",
    "ply": "PLY (point cloud e ricerca)",
}


@dataclass
class Check:
    label: str
    ok: bool
    detail: str = ""

    def icon(self) -> str:
        return "OK " if self.ok else "!! "


# Nomi di dispositivo di Windows: non sono file. Scriverci sopra manda i dati
# al dispositivo e, nel caso di AUX, blocca il processo. Vale anche con
# un'estensione: "aux.glb" e' ancora il dispositivo AUX.
RESERVED_NAMES = frozenset(
    ["con", "prn", "aux", "nul"]
    + ["com%d" % i for i in range(1, 10)]
    + ["lpt%d" % i for i in range(1, 10)]
)


def safe_output_path(path: Path) -> Path:
    """Rende innocuo un percorso di destinazione, senza sorprendere l'utente."""
    stem = path.stem.lower()
    if stem in RESERVED_NAMES:
        safe = path.with_name("%s_%s" % (path.stem, "file") + path.suffix)
        log.warning("'%s' e' un nome di dispositivo riservato su Windows: "
                    "salvo come '%s'", path.name, safe.name)
        return safe
    return path


def write_scene(trimesh_scene, path: Path, fmt: str) -> Path:
    """Serializza in memoria e scrive noi il file.

    `trimesh.Scene.export(percorso)` restituisce i byte ma su Windows puo'
    lasciare il file vuoto: l'handle non e' ancora stato chiuso quando lo si
    legge. Serializzare e scrivere in due passi toglie di mezzo il problema.
    """
    data = trimesh_scene.export(file_type=fmt)
    if isinstance(data, str):
        path.write_text(data, encoding="utf-8")
    elif isinstance(data, (bytes, bytearray)):
        path.write_bytes(data)
    else:                                   # formati che scrivono da soli
        trimesh_scene.export(path)
    if not path.exists() or path.stat().st_size == 0:
        raise IOError("export vuoto: %s" % path)
    return path


def validate(scene: Scene, max_triangles: int = 250_000) -> list[Check]:
    """Controlli prima dell'export, nello spirito del punto 22 della roadmap."""
    checks: list[Check] = []
    checks.append(Check("Componenti generati", bool(scene.nodes),
                        "%d parti" % len(scene.nodes)))
    checks.append(Check("Nessun componente fallito", not scene.warnings,
                        "%d avvisi" % len(scene.warnings)))

    # I pezzi di una superficie fusa sono aperti per costruzione: il corpo
    # chiuso e' la loro unione, verificata al momento della composizione.
    broken = [n.id for n in scene.nodes
              if "fused" not in n.tags and not n.mesh.is_watertight]
    checks.append(Check("Mesh chiuse (watertight)", not broken,
                        "aperte: " + ", ".join(broken[:5]) if broken else "tutte chiuse"))

    degenerate = [n.id for n in scene.nodes
                  if "fused" not in n.tags and n.mesh.volume <= 1e-9]
    checks.append(Check("Nessun volume degenere", not degenerate,
                        ", ".join(degenerate[:5]) if degenerate else "-"))

    tris = scene.triangle_count
    checks.append(Check("Budget poligoni", tris <= max_triangles,
                        "%d triangoli" % tris))

    b = scene.bounds()
    on_ground = abs(float(b[0][1])) < 0.06
    checks.append(Check("Appoggiato al piano", on_ground,
                        "y minima = %.3f m" % float(b[0][1])))

    dims = scene.dimensions()
    plausible = all(0.01 < d < 200 for d in dims)
    checks.append(Check("Dimensioni plausibili", plausible,
                        "%.2f x %.2f x %.2f m" % dims))
    return checks


def export(scene: Scene, path: str | Path, save_plan: bool = True,
           textured: bool | None = None, texture_size: int = 0) -> Path:
    """Scrive la scena su file. `texture_size` a zero segue il profilo hardware."""
    out = safe_output_path(Path(path))
    if not out.is_absolute():
        out = SETTINGS.output_dir / out
    out.parent.mkdir(parents=True, exist_ok=True)
    fmt = out.suffix.lower().lstrip(".")
    if fmt not in FORMATS:
        raise ValueError("formato non supportato: .%s (disponibili: %s)"
                         % (fmt, ", ".join(FORMATS)))
    if not scene.nodes:
        raise ValueError("la scena e' vuota, niente da esportare")

    # STL e PLY non trasportano materiali: inutile generare texture.
    # `None` vuol dire "come vuole lo stile": lo stile lo conosce chi ha il
    # registry, non l'esportatore. Qui il predefinito e' il linguaggio del
    # prodotto — tinte piatte — e chi legge un `StyleProfile` passa un booleano.
    if textured is None:
        textured = False
    with_maps = textured and fmt in ("glb", "obj")
    if not texture_size:
        from app.core.hardware import current

        texture_size = current().texture_size
    ts = scene.to_trimesh_scene(textured=with_maps, texture_size=texture_size)
    write_scene(ts, out, fmt)
    log.info("esportato %s (%d parti, %d triangoli)", out, len(scene.nodes), scene.triangle_count)

    if save_plan and hasattr(scene.plan, "to_dict"):
        # Accanto al modello si scrive il **piano**, non i suoi metadati: e' cio'
        # che permette di rigenerarlo. Una scena senza piano — decimata, unita
        # per materiale, caricata da un file — semplicemente non lo scrive.
        plan_path = out.with_suffix(".plan.json")
        plan_path.write_text(
            json.dumps(scene.plan.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8")
        log.info("piano salvato in %s (rigenerabile e riproducibile)", plan_path)
    return out
