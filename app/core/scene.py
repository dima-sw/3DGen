"""Scene graph: la rappresentazione viva del modello generato.

Ogni nodo ha un id stabile (body, tire_fl, roof, ...). E' questo che permette
l'editing incrementale: "ingrandisci le ruote" tocca solo i nodi taggati wheel.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import trimesh

from app.core.logging_setup import get
from app.core.material import MaterialSpec

log = get("scene")


@dataclass
class SceneNode:
    id: str
    name: str
    mesh: trimesh.Trimesh
    material: MaterialSpec
    tags: list[str] = field(default_factory=list)
    # Colori gia' presenti sulla mesh, quando nessun materiale nominato li
    # sostituisce. Il materiale resta la tinta rappresentativa per le viste
    # che disegnano un solo colore per nodo.
    preserve_visual: bool = False

    @property
    def triangles(self) -> int:
        return len(self.mesh.faces)


@dataclass
class Scene:
    # Il piano da cui la scena viene. Non e' tipizzato apposta: puo' essere un
    # `CompositionGraph` (la strada nuova) o qualunque cosa lo sostituisca. La
    # scena ne legge **un campo solo**, il seme, e non deve saperne altro —
    # legarla a una classe di piano vorrebbe dire rifarla a ogni cambiamento.
    plan: Any
    nodes: list[SceneNode] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # Pose delle parti composte (PlacedPart), quando la scena viene da un
    # assemblaggio. Non e' geometria: e' la struttura su cui lavorano i
    # validatori semantici e, in futuro, il rigging.
    placements: dict = field(default_factory=dict)
    # Esito dei vincoli semantici (list[Issue]): serve alla UI e ai test
    issues: list = field(default_factory=list)
    # Di quanto le mesh sono state alzate per appoggiarle a terra. Le pose in
    # `placements` non lo sanno, perche' condividono gli oggetti con la
    # composizione: chi le usa nel sistema della scena somma questo.
    ground_offset: Any = None
    # Strategia che ha prodotto la scena e tentativi fatti: l'utente deve
    # poter vedere da dove viene cio' che guarda.
    strategy: str = "template"
    attempts: list = field(default_factory=list)

    def add(self, node: SceneNode) -> None:
        self.nodes.append(node)

    def by_tag(self, tag: str) -> list[SceneNode]:
        return [n for n in self.nodes if tag in n.tags]

    def by_id(self, node_id: str) -> SceneNode | None:
        return next((n for n in self.nodes if n.id == node_id), None)

    # ---------------------------------------------------------------- stats #
    @property
    def triangle_count(self) -> int:
        return sum(n.triangles for n in self.nodes)

    def bounds(self) -> np.ndarray:
        if not self.nodes:
            return np.zeros((2, 3))
        mins = np.min([n.mesh.bounds[0] for n in self.nodes], axis=0)
        maxs = np.max([n.mesh.bounds[1] for n in self.nodes], axis=0)
        return np.array([mins, maxs])

    def dimensions(self) -> tuple[float, float, float]:
        b = self.bounds()
        d = b[1] - b[0]
        return (float(d[0]), float(d[1]), float(d[2]))

    def summary(self) -> str:
        w, h, d = self.dimensions()
        return ("%d parti | %d triangoli | %.2f x %.2f x %.2f m"
                % (len(self.nodes), self.triangle_count, w, h, d))

    # ------------------------------------------------------------- trimesh #
    def to_trimesh_scene(self, textured: bool | None = None,
                         texture_size: int = 256) -> trimesh.Scene:
        """Converte in una trimesh.Scene pronta per l'export.

        Con `textured` ogni materiale che ha una finitura procedurale riceve le
        proprie mappe PBR e delle UV a proiezione di scatola. Senza, resta la
        tinta piatta.

        `None` significa "come vuole lo stile", ed e' il valore normale: il
        cartoon low poly vive di tinte piatte e silhouette, non di superfici. Le
        texture restano disponibili, ma sono una richiesta esplicita.
        """
        # `None` vuol dire "come vuole lo stile", e lo stile lo conosce chi ha
        # il registry — non una scena. Qui il predefinito e' il linguaggio del
        # prodotto: tinte piatte. Chi vuole le texture le chiede, e chi legge
        # un `StyleProfile` passa un booleano vero.
        if textured is None:
            textured = False
        from app.geometry.uv import box_uv, uv_bounds_are_reasonable
        from app.materials.library import maps_for

        scene = trimesh.Scene()
        seed = int(getattr(self.plan, "seed", 0) or 0) % 10000

        for n in self.nodes:
            mesh = n.mesh.copy()
            if n.preserve_visual and getattr(mesh.visual, "defined", False):
                scene.add_geometry(mesh, node_name=n.id, geom_name=n.id)
                continue
            r, g, b, a = n.material.rgba()
            maps = None
            if textured:
                try:
                    maps = maps_for(n.material.name, (r, g, b),
                                    float(n.material.roughness), float(n.material.metallic),
                                    size=texture_size, seed=seed)
                except Exception as exc:      # una texture non deve bloccare l'export
                    log.warning("texture non generata per '%s': %s", n.id, exc)

            try:
                if maps is not None:
                    mesh, uv = box_uv(mesh, texel=float(maps["tiling"]))
                    if not uv_bounds_are_reasonable(uv):
                        raise ValueError("UV fuori scala")
                    material = trimesh.visual.material.PBRMaterial(
                        name=n.material.name,
                        baseColorFactor=[1.0, 1.0, 1.0, a],
                        baseColorTexture=maps["base_color"],
                        metallicRoughnessTexture=maps["metallic_roughness"],
                        normalTexture=maps["normal"],
                        metallicFactor=1.0, roughnessFactor=1.0,
                        alphaMode="BLEND" if a < 0.999 else "OPAQUE",
                    )
                    mesh.visual = trimesh.visual.TextureVisuals(uv=uv, material=material)
                else:
                    pbr = trimesh.visual.material.PBRMaterial(
                        name=n.material.name,
                        baseColorFactor=[r, g, b, a],
                        metallicFactor=float(n.material.metallic),
                        roughnessFactor=float(n.material.roughness),
                        alphaMode="BLEND" if a < 0.999 else "OPAQUE",
                    )
                    mesh.visual = trimesh.visual.TextureVisuals(material=pbr)
            except Exception:
                mesh.visual.face_colors = [int(r * 255), int(g * 255), int(b * 255), int(a * 255)]

            scene.add_geometry(mesh, node_name=n.id, geom_name=n.id)
        return scene
