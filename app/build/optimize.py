"""Ottimizzazione e preparazione per i motori di gioco.

Un sistema procedurale ha un vantaggio che una pipeline basata su mesh non ha:
per un livello di dettaglio piu' basso non deve **decimare**, puo' **rigenerare**.
Ricostruire lo stesso piano a risoluzione minore da una mesh pulita, con la
stessa topologia di partenza, invece di un residuo di semplificazione.

Serve comunque una decimazione per le mesh che non si possono rigenerare (un
asset importato, o domani una mesh prodotta da un modello AI). Qui e' fatta per
raggruppamento di vertici su griglia: poche righe di numpy, nessuna dipendenza
nuova, risultato prevedibile.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import trimesh

from app.core.logging_setup import get
from app.core.scene import Scene, SceneNode


log = get("build.optimize")


# --------------------------------------------------------------------------- #
# Decimazione per raggruppamento di vertici
# --------------------------------------------------------------------------- #
def cluster_decimate(mesh: trimesh.Trimesh, cell: float) -> trimesh.Trimesh:
    """Fonde i vertici che cadono nella stessa cella di una griglia.

    Non e' una decimazione a errore quadrico: e' piu' rozza, ma non ha bisogno
    di librerie esterne, non introduce buchi e degrada in modo prevedibile.
    """
    if len(mesh.faces) == 0 or cell <= 0:
        return mesh.copy()

    vertices = np.asarray(mesh.vertices, dtype=float)
    keys = np.floor(vertices / cell).astype(np.int64)
    _, inverse, counts = np.unique(keys, axis=0, return_inverse=True, return_counts=True)

    # rappresentante di ogni cella: il baricentro dei vertici che contiene
    merged = np.zeros((len(counts), 3))
    np.add.at(merged, inverse, vertices)
    merged /= counts[:, None]

    faces = inverse[np.asarray(mesh.faces)]
    keep = (faces[:, 0] != faces[:, 1]) & (faces[:, 1] != faces[:, 2]) & (faces[:, 0] != faces[:, 2])
    faces = faces[keep]
    if len(faces) == 0:
        return mesh.copy()

    out = trimesh.Trimesh(vertices=merged, faces=faces, process=False)
    out.remove_unreferenced_vertices()
    out.update_faces(out.unique_faces())
    try:
        out.fix_normals()
    except Exception:
        pass
    return out


def decimate_to(mesh: trimesh.Trimesh, target_faces: int,
                attempts: int = 12) -> trimesh.Trimesh:
    """Cerca la dimensione di cella che avvicina il bersaglio, per bisezione."""
    if len(mesh.faces) <= target_faces or target_faces < 4:
        return mesh.copy()

    diagonal = float(np.linalg.norm(mesh.bounds[1] - mesh.bounds[0])) or 1.0
    low, high = diagonal * 1e-4, diagonal * 0.5
    best = mesh.copy()
    for _ in range(attempts):
        cell = (low + high) / 2.0
        candidate = cluster_decimate(mesh, cell)
        if len(candidate.faces) > target_faces:
            low = cell                    # celle piu' grandi, meno facce
        else:
            best = candidate
            high = cell
        if abs(len(candidate.faces) - target_faces) < max(target_faces * 0.05, 8):
            return candidate
    return best


# --------------------------------------------------------------------------- #
# Livelli di dettaglio
# --------------------------------------------------------------------------- #
# Quanto resta di un modello a ogni livello, quando lo si decima. Serve al
# ripiego: un LOD **rigenerato** non decima niente, costruisce meno parti.
LOD_RATIOS = [1.0, 0.5, 0.2, 0.06]


@dataclass
class Lod:
    level: int
    scene: Scene
    ratio: float

    @property
    def triangles(self) -> int:
        return self.scene.triangle_count


def regenerate_lod(plan, level: int, session=None) -> Scene | None:
    """Ricostruisce il modello a un **dettaglio** inferiore, quando si puo'.

    E' il vantaggio di avere un piano invece di una mesh: un livello di
    dettaglio lontano non e' l'originale decimato, e' lo stesso oggetto
    costruito con meno parti — mesh pulite, giunti veri, materiali interi.

    Il livello di dettaglio e' un numero piccolo e discreto: `1` sono le parti
    principali, `3` e' il volto con occhi e naso. Scendere di un LOD vuol dire
    scendere di un livello, e sotto il primo non si scende: li' si torna alla
    decimazione, e chi chiama se ne accorge perche' riceve `None`.
    """
    if level <= 0 or plan is None:
        return None
    corrente = int(getattr(plan, "detail_level", 0) or 0)
    voluto = corrente - level
    if corrente <= 1 or voluto < 1:
        return None

    from app.core.session import Options, Session

    sessione = session if session is not None else Session()
    try:
        risultato = sessione.build(plan, Options(detail_level=voluto, check=False))
        return risultato.scene(sessione.catalog()) if risultato.build else None
    except Exception as exc:                              # noqa: BLE001
        log.warning("LOD %d non rigenerato: %s", level, exc)
        return None


def decimate_scene(scene: Scene, ratio: float) -> Scene:
    """Riduce ogni parte mantenendo materiali e identita'."""
    out = Scene(plan=scene.plan, warnings=list(scene.warnings))
    for node in scene.nodes:
        target = max(int(len(node.mesh.faces) * ratio), 4)
        out.add(SceneNode(id=node.id, name=node.name,
                          mesh=decimate_to(node.mesh, target),
                          material=node.material, tags=list(node.tags)))
    return out


def make_lods(scene: Scene, levels: int = 4, prefer_regeneration: bool = True) -> list[Lod]:
    """Catena di livelli di dettaglio, dal piu' fine al piu' grossolano.

    La catena e' **garantita decrescente**. Non lo era: mescolando livelli
    rigenerati e livelli decimati usciva 1668, 140, 398, perche' la
    rigenerazione scendeva a scatti mentre la decimazione ripartiva ogni volta
    dall'originale. Un livello piu' grossolano ma piu' pesante di quello sopra
    non e' un livello di dettaglio, e il motore che lo carica sceglierebbe male.
    """
    lods = [Lod(0, scene, 1.0)]
    for level in range(1, max(levels, 1)):
        precedente = lods[-1].scene
        rebuilt = regenerate_lod(scene.plan, level) if prefer_regeneration else None

        # la rigenerazione vale solo se ha davvero alleggerito
        if (rebuilt is not None and rebuilt.nodes
                and rebuilt.triangle_count < precedente.triangle_count):
            scelto = rebuilt
        else:
            # si decima **il livello precedente**, non l'originale: e' l'unico
            # modo di garantire che ogni gradino sia piu' leggero di quello sopra
            voluto = LOD_RATIOS[min(level, len(LOD_RATIOS) - 1)] * scene.triangle_count
            quota = min(voluto / max(precedente.triangle_count, 1), 0.8)
            scelto = decimate_scene(precedente, quota)
        lods.append(Lod(level, scelto,
                        scelto.triangle_count / max(scene.triangle_count, 1)))
    return lods


# --------------------------------------------------------------------------- #
# Fusione per materiale e collisione
# --------------------------------------------------------------------------- #
def merge_by_material(scene: Scene) -> Scene:
    """Un nodo per materiale: meno draw call, stessa immagine."""
    groups: dict[str, list[SceneNode]] = {}
    for node in scene.nodes:
        groups.setdefault(node.material.name, []).append(node)

    out = Scene(plan=scene.plan, warnings=list(scene.warnings))
    for material_name, nodes in groups.items():
        meshes = [n.mesh for n in nodes]
        merged = trimesh.util.concatenate(meshes) if len(meshes) > 1 else meshes[0].copy()
        tags = sorted({t for n in nodes for t in n.tags})
        out.add(SceneNode(id=material_name, name=material_name.title(),
                          mesh=merged, material=nodes[0].material, tags=tags))
    log.info("fusione per materiale: %d nodi -> %d", len(scene.nodes), len(out.nodes))
    return out


# Un volume di collisione con migliaia di facce non serve a nessuno: la fisica
# vuole poche facce, e l'hull convesso di una mesh liscia ne ha tante.
COLLISION_BUDGET = 256


def _ensure_encloses(hull: trimesh.Trimesh, original: trimesh.Trimesh,
                     margin: float = 0.01) -> trimesh.Trimesh:
    """Riporta il volume a contenere il modello dopo la decimazione.

    Il raggruppamento di vertici sposta i punti verso il centro della cella,
    quindi restringe l'inviluppo. Un volume di collisione piu' piccolo del
    modello lascerebbe compenetrare gli oggetti: meglio un filo piu' grande.
    """
    if len(hull.faces) == 0:
        return hull
    centre = hull.centroid
    reference = np.asarray(original.vertices, dtype=float) - centre
    current = np.asarray(hull.vertices, dtype=float) - centre

    # I due versi vanno trattati separatamente: con un modello asimmetrico
    # il massimo dei valori assoluti coprirebbe un lato e non l'altro.
    ratios = [1.0]
    for side in (1.0, -1.0):
        ref = np.max(reference * side, axis=0)
        cur = np.max(current * side, axis=0)
        usable = cur > 1e-9
        if np.any(usable):
            ratios.append(float(np.max(ref[usable] / cur[usable])))
    factor = max(ratios) * (1.0 + margin)

    out = hull.copy()
    out.apply_translation(-centre)
    out.apply_scale(factor)
    out.apply_translation(centre)
    return out


def collision_mesh(scene: Scene, method: str = "convex",
                   budget: int = COLLISION_BUDGET) -> trimesh.Trimesh:
    """Volume semplificato per la fisica: pochi triangoli, nessun dettaglio."""
    # tutto cio' che si vede si puo' anche urtare: niente esclusioni
    meshes = [n.mesh for n in scene.nodes if len(n.mesh.faces)]
    if not meshes:
        raise ValueError("scena senza geometria: nessuna collisione da calcolare")
    combined = trimesh.util.concatenate(meshes) if len(meshes) > 1 else meshes[0].copy()

    if method == "box":
        return combined.bounding_box.copy()
    if method == "convex":
        try:
            return _ensure_encloses(decimate_to(combined.convex_hull, budget), combined)
        except Exception as exc:
            log.warning("hull convesso non calcolabile (%s): uso la scatola", exc)
            return combined.bounding_box.copy()
    return decimate_to(combined, budget)


# --------------------------------------------------------------------------- #
# Preset per i motori
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class GamePreset:
    """Cosa si aspetta un motore. Sono convenzioni, non magie."""

    name: str
    triangle_budget: int
    lod_levels: int
    file_format: str = "glb"
    merge_materials: bool = True
    collision: str = "convex"
    scale: float = 1.0
    note: str = ""


PRESETS: dict[str, GamePreset] = {
    "unity": GamePreset("unity", 40_000, 4, "glb", True, "convex", 1.0,
                        "metri, Y in alto, glTF importato nativamente"),
    "unreal": GamePreset("unreal", 60_000, 4, "glb", True, "convex", 1.0,
                         "importa glTF; le unita' del motore sono centimetri, "
                         "la conversione la fa l'import"),
    "godot": GamePreset("godot", 30_000, 3, "glb", True, "convex", 1.0,
                        "glTF e' il formato nativo"),
    "generic": GamePreset("generic", 50_000, 3, "glb", False, "convex", 1.0,
                          "nessuna assunzione sul motore"),
}


@dataclass
class GameReadyResult:
    """Cio' che si consegna al motore."""

    lods: list[Lod] = field(default_factory=list)
    collision: trimesh.Trimesh | None = None
    preset: GamePreset | None = None
    within_budget: bool = True
    notes: list[str] = field(default_factory=list)

    def summary(self) -> str:
        chain = ", ".join("LOD%d %d tri" % (l.level, l.triangles) for l in self.lods)
        collision = len(self.collision.faces) if self.collision is not None else 0
        return "%s | collisione %d tri | budget %s" % (
            chain, collision, "rispettato" if self.within_budget else "superato")


def prepare_for_game(scene: Scene, preset: str | GamePreset = "generic") -> GameReadyResult:
    """Fonde per materiale, costruisce i LOD e la mesh di collisione."""
    spec = preset if isinstance(preset, GamePreset) else PRESETS.get(str(preset), PRESETS["generic"])
    result = GameReadyResult(preset=spec)

    base = merge_by_material(scene) if spec.merge_materials else scene
    result.lods = make_lods(base, levels=spec.lod_levels)

    top = result.lods[0].triangles
    if top > spec.triangle_budget:
        # il primo livello sfora: si decima fino a rientrare
        ratio = spec.triangle_budget / max(top, 1)
        result.lods[0] = Lod(0, decimate_scene(base, ratio), ratio)
        result.notes.append("LOD0 ridotto da %d a %d triangoli per rientrare nel budget"
                            % (top, result.lods[0].triangles))
    result.within_budget = result.lods[0].triangles <= spec.triangle_budget * 1.05

    try:
        result.collision = collision_mesh(base, spec.collision)
    except Exception as exc:
        result.notes.append("collisione non calcolata: %s" % exc)

    log.info("game ready (%s): %s", spec.name, result.summary())
    return result


def export_game_ready(scene: Scene, folder, preset: str | GamePreset = "generic",
                      basename: str = "modello") -> list:
    """Scrive LOD e collisione in una cartella, pronti per l'import."""
    from pathlib import Path

    from app.build.exporter import write_scene

    target = Path(folder)
    target.mkdir(parents=True, exist_ok=True)
    result = prepare_for_game(scene, preset)
    spec = result.preset
    written = []

    for lod in result.lods:
        path = target / ("%s_LOD%d.%s" % (basename, lod.level, spec.file_format))
        write_scene(lod.scene.to_trimesh_scene(textured=lod.level == 0),
                    path, spec.file_format)
        written.append(path)

    if result.collision is not None:
        path = target / ("%s_collision.%s" % (basename, spec.file_format))
        collision_scene = trimesh.Scene()
        collision_scene.add_geometry(result.collision, geom_name="collision")
        write_scene(collision_scene, path, spec.file_format)
        written.append(path)

    return written
