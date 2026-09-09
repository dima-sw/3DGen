"""Contratto dati fra AI e motore geometrico.

Regola architetturale: l'LLM non produce mai codice, produce SOLO questo JSON,
che viene validato con Pydantic prima di toccare la geometria.
"""
from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Vec3 = tuple[float, float, float]
HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


# --------------------------------------------------------------------------- #
# Materiali
# --------------------------------------------------------------------------- #
class MaterialSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    base_color: str = "#9aa0a6"
    roughness: float = Field(0.6, ge=0.0, le=1.0)
    metallic: float = Field(0.0, ge=0.0, le=1.0)
    opacity: float = Field(1.0, ge=0.05, le=1.0)

    @field_validator("base_color")
    @classmethod
    def _hex(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith("#"):
            v = "#" + v
        if not HEX_RE.match(v):
            return "#9aa0a6"
        return v.lower()

    def rgba(self) -> tuple[float, float, float, float]:
        h = self.base_color.lstrip("#")
        r, g, b = (int(h[i : i + 2], 16) / 255.0 for i in (0, 2, 4))
        return (r, g, b, self.opacity)


# --------------------------------------------------------------------------- #
# Componenti di basso livello (primitive posizionate)
# --------------------------------------------------------------------------- #
class ComponentSpec(BaseModel):
    """Una parte concreta della scena. Prodotta dai template o, in freeform, dall'LLM."""

    model_config = ConfigDict(extra="ignore")

    id: str
    name: str = ""
    primitive: Literal[
        "box", "rounded_box", "sphere", "cylinder", "cone", "capsule",
        "torus", "wedge", "prism", "tube", "plane", "hexahedron",
    ] = "box"
    params: dict[str, Any] = Field(default_factory=dict)
    position: Vec3 = (0.0, 0.0, 0.0)
    rotation: Vec3 = (0.0, 0.0, 0.0)  # gradi, XYZ
    scale: Vec3 = (1.0, 1.0, 1.0)
    material: str = "default"
    parent: str | None = None
    tags: list[str] = Field(default_factory=list)

    @field_validator("position", "rotation", "scale", mode="before")
    @classmethod
    def _vec(cls, v: Any) -> Vec3:
        if isinstance(v, (int, float)):
            return (float(v), float(v), float(v))
        if isinstance(v, (list, tuple)) and len(v) == 3:
            return tuple(float(x) for x in v)  # type: ignore[return-value]
        return (0.0, 0.0, 0.0)


# --------------------------------------------------------------------------- #
# Assemblaggio: grafo di parti componibili
# --------------------------------------------------------------------------- #
class AttachSpec(BaseModel):
    """Come una parte si innesta nel socket di un'altra."""

    model_config = ConfigDict(extra="ignore")

    parent: str
    socket: str
    own_socket: str = "base"
    # "none" e' il default: la parte tiene le misure dichiarate.
    # "socket" adatta la scala al raggio del socket padre, comodo per
    # gli arti ma disastroso sulle lame, dove gonfia anche lo spessore.
    scale_mode: Literal["socket", "parent", "none"] = "none"
    scale: float = Field(1.0, ge=0.05, le=20.0)
    insert: float = Field(0.45, ge=0.0, le=2.0)
    roll: float = Field(0.0, ge=-360.0, le=360.0)


class PartSpec(BaseModel):
    """Un nodo del grafo: quale ricetta, con quali parametri, attaccata dove."""

    model_config = ConfigDict(extra="ignore")

    id: str
    recipe: str
    params: dict[str, Any] = Field(default_factory=dict)
    attach: AttachSpec | None = None
    material: str = ""
    tags: list[str] = Field(default_factory=list)
    blend: float | None = None
    hard: bool = False
    scale: float = Field(1.0, ge=0.01, le=100.0)


class AssemblySpec(BaseModel):
    """Il grafo completo. Sostituisce la lista piatta di componenti."""

    model_config = ConfigDict(extra="ignore")

    root: str = ""
    parts: list[PartSpec] = Field(default_factory=list)
    blend: float = Field(0.06, ge=0.0, le=1.0)
    symmetry: Literal["none", "bilateral"] = "bilateral"
    semantic_class: str = ""      # pesce, umanoide, quadrupede: guida i vincoli

    def by_id(self, part_id: str) -> PartSpec | None:
        return next((p for p in self.parts if p.id == part_id), None)

    def children_of(self, part_id: str) -> list[PartSpec]:
        return [p for p in self.parts if p.attach and p.attach.parent == part_id]


# --------------------------------------------------------------------------- #
# Piano di generazione
# --------------------------------------------------------------------------- #
class GenerationPlan(BaseModel):
    """Output dell'AI Planner. E' l'unica sorgente di verita' del modello."""

    model_config = ConfigDict(extra="ignore")

    prompt: str = ""
    object_type: str = "generic"        # etichetta leggibile ("jeep militare")
    template: str = "freeform"          # chiave nel registry dei generatori
    strategy: Literal["template", "assembly", "library", "ai_mesh"] = "template"
    # Lo stile non e' un campo: 3DGen fa cartoon low-poly e basta
    # (app/core/style.py). Quello che resta e' **quanto fitta** viene la
    # superficie: serve ai livelli di dettaglio e alle macchine modeste, e non
    # cambia l'aspetto, solo il conto dei triangoli.
    density: float = Field(1.0, ge=0.3, le=2.4)
    params: dict[str, Any] = Field(default_factory=dict)
    materials: list[MaterialSpec] = Field(default_factory=list)
    components: list[ComponentSpec] = Field(default_factory=list)  # solo per template=freeform
    # Grafo di parti componibili: la strada per gli oggetti non previsti
    # dai template. Quando c'e', ha la precedenza sul template.
    assembly: AssemblySpec | None = None
    seed: int = 0
    # Parametri e materiali chiesti esplicitamente: le varianti non li toccano.
    locked: list[str] = Field(default_factory=list)
    # Parametri prima del disturbo: permette di rigenerare varianti
    # senza che gli scostamenti si accumulino.
    base_params: dict[str, Any] = Field(default_factory=dict)
    notes: str = ""
    version: str = "0.1"

    def material_map(self) -> dict[str, MaterialSpec]:
        m = {mat.name: mat for mat in self.materials}
        m.setdefault("default", MaterialSpec(name="default"))
        return m


# --------------------------------------------------------------------------- #
# Editing incrementale: comandi strutturati, mai codice
# --------------------------------------------------------------------------- #
class EditOp(BaseModel):
    model_config = ConfigDict(extra="ignore")

    op: Literal[
        "set_param",      # path=nome parametro, value
        "scale_param",    # path=nome parametro, factor
        "set_material",   # target=nome materiale, color/roughness/metallic
        "set_density",    # value: quanto fitta la superficie
        "set_template",   # value (cambio radicale di oggetto)
        "noop",
    ]
    path: str = ""
    target: str = ""
    value: Any = None
    factor: float = 1.0
    reason: str = ""


class EditPlan(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ops: list[EditOp] = Field(default_factory=list)
    summary: str = ""
