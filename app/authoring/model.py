"""Lo stato temporaneo dell'authoring, e perche' non e' un secondo modello.

Durante l'editing serve uno stato che il plugin finale non ha: quale GLB e'
aperto, quali oggetti della scena sono selezionati, quale componente si sta
modificando, dove verra' salvato, che cosa non e' ancora valido. Scriverlo
dentro il plugin installato a ogni click sarebbe sbagliato due volte — si
ricaricherebbe il registry a ogni carattere digitato, e il plugin conterrebbe
campi che riguardano l'editor e non la libreria.

## Che cosa questi oggetti **non** sono

Non sono una seconda rappresentazione permanente dei `Component`:

* nessun `Draft*` ha un `build`, e nessuno entra mai nel `Registry`;
* al salvataggio producono il formato dati V4/V5 e **spariscono**: cio' che
  resta su disco e' JSON + GLB che `app/core/data_plugin.py` sa leggere, non
  questo modello;
* riaprire un plugin salvato ricostruisce i draft **dal JSON** (vedi
  `AuthoringService.open_data_plugin`), quindi non c'e' una seconda verita' da
  tenere sincronizzata;
* portano campi che il plugin non deve avere — selezione, visibilita',
  copertura — ed e' esattamente per questo che esistono separati.

## La copertura, e dove vive

`DraftComponent.coverage` dice quanto quella parte e' affidabile:

    VALIDATED   esiste, e qualcuno l'ha guardata
    CANDIDATE   esiste, e va ispezionata
    MISSING     manca: il posto c'e', il pezzo no
    PROXY       c'e' un sostituto, e non e' la cosa chiesta

Serve a V7 (verde / giallo / rosso / blu) e **non appartiene a `Component`**:
non e' una proprieta' del pezzo, e' il giudizio di chi sta costruendo un
concetto. Un `Component` installato non ha una copertura — ci sta dentro, o non
c'e'. Per questo il campo sta qui e non viene emesso nel JSON del plugin: un
test lo verifica.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.authoring import errors
from app.authoring.errors import AuthoringError

FORMAT_VERSION = 1

# Lo stato di copertura di una parte. Quattro valori, e nessun provider AI
# dietro: V6 lo rappresenta, V7 lo decidera'.
VALIDATED = "VALIDATED"
CANDIDATE = "CANDIDATE"
MISSING = "MISSING"
PROXY = "PROXY"
COVERAGE = (VALIDATED, CANDIDATE, MISSING, PROXY)

# Come un riferimento nella gerarchia nomina cio' che indica.
DRAFT_PREFIX = "draft:"
VARIANT_PREFIX = "variant:"

NAME_OK = set("abcdefghijklmnopqrstuvwxyz0123456789_-")


def check_name(value: str, what: str = "nome") -> str:
    """Un nome che puo' diventare un id di componente e un nome di file.

    Minuscole, cifre, `_` e `-`. Non e' pignoleria: questo nome finisce in
    `plugin:nome` e in `meshes/nome.glb`, quindi un `..` o uno spazio
    sarebbero un percorso e un id insieme.
    """
    text = str(value or "").strip()
    if not text or set(text) - NAME_OK:
        raise AuthoringError(errors.NAME_INVALID,
                             "%s non valido: %r (minuscole, cifre, '_' e '-')"
                             % (what, value))
    return text


def _vector(value, fallback=(0.0, 0.0, 0.0)) -> tuple[float, float, float]:
    if value is None:
        return tuple(float(v) for v in fallback)
    items = list(value)
    if len(items) != 3:
        raise AuthoringError(errors.PROJECT_INVALID,
                             "serve un vettore di tre numeri, non %r" % (value,))
    return (float(items[0]), float(items[1]), float(items[2]))


def _strings(value) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(v) for v in value)


# --------------------------------------------------------------------------- #
# Il modello importato
# --------------------------------------------------------------------------- #
@dataclass
class SceneObject:
    """Un nodo di geometria del GLB importato, come lo si guarda.

    `key` e' l'identita' stabile dell'oggetto dentro il progetto: il nome del
    file piu' il nome del nodo glTF. I draft la nominano, quindi non puo'
    dipendere dall'ordine di importazione.
    """

    key: str
    name: str
    triangles: int = 0
    bounds: tuple[tuple[float, float, float], tuple[float, float, float]] = (
        (0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
    transform: tuple[float, ...] = ()        # 16 numeri, righe in ordine
    color: str = ""                          # tinta rappresentativa, se c'e'
    source: str = ""                         # il file da cui viene
    visible: bool = True

    @property
    def extents(self) -> tuple[float, float, float]:
        low, high = self.bounds
        return tuple(float(h - l) for l, h in zip(low, high))

    @property
    def center(self) -> tuple[float, float, float]:
        low, high = self.bounds
        return tuple((float(l) + float(h)) * 0.5 for l, h in zip(low, high))

    def to_dict(self) -> dict:
        return {"key": self.key, "name": self.name, "triangles": self.triangles,
                "bounds": [list(self.bounds[0]), list(self.bounds[1])],
                "transform": list(self.transform), "color": self.color,
                "source": self.source, "visible": self.visible}

    @classmethod
    def from_dict(cls, data: dict) -> "SceneObject":
        bounds = data.get("bounds") or [[0, 0, 0], [0, 0, 0]]
        return cls(key=str(data["key"]), name=str(data.get("name", data["key"])),
                   triangles=int(data.get("triangles", 0)),
                   bounds=(_vector(bounds[0]), _vector(bounds[1])),
                   transform=tuple(float(v) for v in data.get("transform", ())),
                   color=str(data.get("color", "")),
                   source=str(data.get("source", "")),
                   visible=bool(data.get("visible", True)))

    def describe(self) -> str:
        w, h, d = self.extents
        return "%s  %d tri  %.3f x %.3f x %.3f%s" % (
            self.name, self.triangles, w, h, d,
            "  " + self.color if self.color else "")


@dataclass
class SourceModel:
    """Un file importato e cio' che contiene. Non si modifica mai.

    Il GLB sorgente e' **sola lettura**: parentela, socket e parametri non
    toccano la geometria originale (punto 6 della milestone). Al salvataggio si
    estrae una copia degli oggetti che servono, con le loro trasformazioni.
    """

    path: str
    objects: list[SceneObject] = field(default_factory=list)

    @property
    def name(self) -> str:
        return Path(self.path).name

    @property
    def triangles(self) -> int:
        return sum(o.triangles for o in self.objects)

    def object(self, key: str) -> SceneObject | None:
        return next((o for o in self.objects if o.key == key), None)

    def to_dict(self) -> dict:
        return {"path": self.path, "objects": [o.to_dict() for o in self.objects]}

    @classmethod
    def from_dict(cls, data: dict) -> "SourceModel":
        return cls(path=str(data["path"]),
                   objects=[SceneObject.from_dict(o) for o in data.get("objects", [])])


# --------------------------------------------------------------------------- #
# I pezzi di un componente in lavorazione
# --------------------------------------------------------------------------- #
@dataclass
class DraftSocket:
    """Un innesto in lavorazione. Diventa un `Socket` normale, non un MeshSocket.

    I campi sono quelli di `app/core/socket.py:Socket`, uno per uno: la milestone
    chiede che il salvataggio produca normali `Socket`, e il modo di esserne
    certi e' non avere campi in piu'.
    """

    name: str
    position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    direction: tuple[float, float, float] = (0.0, 1.0, 0.0)
    up: tuple[float, float, float] = (0.0, 0.0, 1.0)
    radius: float = 0.1
    capabilities: tuple[str, ...] = ()
    side: str = ""
    tags: tuple[str, ...] = ()

    def to_data(self) -> dict:
        """La forma che `data_plugin._socket` legge."""
        data: dict[str, Any] = {"name": self.name,
                                "position": list(self.position),
                                "direction": list(self.direction),
                                "up": list(self.up),
                                "radius": round(float(self.radius), 6)}
        if self.capabilities:
            data["capabilities"] = list(self.capabilities)
        if self.side:
            data["side"] = self.side
        if self.tags:
            data["tags"] = list(self.tags)
        return data

    def to_socket(self):
        """Il `Socket` vero, per la preview e il gizmo. Nessun tipo nuovo."""
        from app.core.socket import Socket

        return Socket(name=self.name, position=self.position,
                      direction=self.direction, up=self.up, radius=self.radius,
                      capabilities=self.capabilities, side=self.side,
                      tags=frozenset(self.tags))

    def check(self) -> "DraftSocket":
        """La stessa validazione che il loader fara' su questo socket.

        Non quella di `Socket`, che e' piu' indulgente di proposito:
        `orthogonal_up` **ripara** un `up` parallelo alla direzione, perche' un
        componente procedurale che sbaglia di un epsilon non deve morire. Il
        loader dei plugin dati invece rifiuta una terna degenere
        (`DATA_FRAME_INVALID`), e chi sta disegnando un innesto deve sapere
        adesso cio' che scoprirebbe al salvataggio. Si chiama il loader, non si
        riscrive la sua regola: una sola idea di socket valido.
        """
        from app.core.data_plugin import _socket

        _socket(self.to_data())
        return self

    def to_dict(self) -> dict:
        return self.to_data()

    @classmethod
    def from_dict(cls, data: dict) -> "DraftSocket":
        return cls(name=str(data["name"]),
                   position=_vector(data.get("position")),
                   direction=_vector(data.get("direction"), (0.0, 1.0, 0.0)),
                   up=_vector(data.get("up"), (0.0, 0.0, 1.0)),
                   radius=float(data.get("radius", 0.1)),
                   capabilities=_strings(data.get("capabilities")),
                   side=str(data.get("side", "")),
                   tags=_strings(data.get("tags")))


@dataclass
class DraftParam:
    """Un parametro in lavorazione, con la sua strategia dichiarata.

    Le due strategie sono quelle di V5 e non ce n'e' una terza: `transform`
    (una scala positiva per asse) **oppure** `effect` (il valore pilota un
    effetto installato). Qui possono essere entrambe vuote mentre si scrive —
    un parametro a meta' e' uno stato dell'editor — ma `validate()` lo segnala
    e il loader lo rifiuterebbe. Nessun codice arbitrario: `effect` ha le
    quattro chiavi di `ParamEffect` e nient'altro.
    """

    name: str
    type: str = "float"
    default: float = 1.0
    min: float | None = None
    max: float | None = None
    semantic_role: str = ""
    description: str = ""
    unit: str = ""
    transform: str = ""
    effect: dict | None = None

    @property
    def strategy(self) -> str:
        if self.transform and self.effect:
            return "both"
        if self.transform:
            return "transform"
        if self.effect:
            return "effect"
        return "none"

    def to_data(self) -> dict:
        data: dict[str, Any] = {"default": float(self.default), "type": self.type}
        for key in ("min", "max"):
            value = getattr(self, key)
            if value is not None:
                data[key] = float(value)
        for key in ("semantic_role", "description", "unit"):
            value = getattr(self, key)
            if value:
                data[key] = value
        if self.transform:
            data["transform"] = self.transform
        if self.effect:
            data["effect"] = dict(self.effect)
        return data

    def to_dict(self) -> dict:
        return dict(self.to_data(), name=self.name)

    @classmethod
    def from_dict(cls, data: dict) -> "DraftParam":
        effect = data.get("effect")
        return cls(name=str(data["name"]), type=str(data.get("type", "float")),
                   default=float(data.get("default", 1.0)),
                   min=None if data.get("min") is None else float(data["min"]),
                   max=None if data.get("max") is None else float(data["max"]),
                   semantic_role=str(data.get("semantic_role", "")),
                   description=str(data.get("description", "")),
                   unit=str(data.get("unit", "")),
                   transform=str(data.get("transform", "")),
                   effect=dict(effect) if isinstance(effect, dict) else None)


@dataclass
class DraftChild:
    """Un arco della gerarchia. Diventa un normale `Attachment`.

    `ref` nomina tre cose diverse con lo stesso campo, e il prefisso dice
    quale: `draft:<key>` un componente di questo progetto, `variant:<nome>` una
    variant recipe dichiarata qui, e qualunque altra stringa un componente
    **installato** (`creature:eye`). E' cio' che rende possibile il punto 7
    della milestone — una gerarchia mista fra pezzi importati e libreria
    esistente — senza un secondo tipo di arco.
    """

    id: str
    ref: str
    level: int = 2
    optional: bool = False
    on_request: bool = False
    replaces: str = ""
    replaces_parent: bool = False
    on: str = ""
    own_socket: str = "base"
    scale_mode: str = "none"
    insert: float | None = None
    roll: float | None = None
    requirement: dict | None = None
    params: dict = field(default_factory=dict)
    material: str = ""
    tags: tuple[str, ...] = ()

    @property
    def draft_key(self) -> str:
        return self.ref[len(DRAFT_PREFIX):] if self.ref.startswith(DRAFT_PREFIX) else ""

    @property
    def variant_name(self) -> str:
        return self.ref[len(VARIANT_PREFIX):] if self.ref.startswith(VARIANT_PREFIX) else ""

    @property
    def installed_ref(self) -> str:
        """Il riferimento, quando punta alla libreria installata."""
        return "" if (self.draft_key or self.variant_name) else self.ref

    def to_data(self, component: str, *, params: dict | None = None) -> dict:
        """La forma che `data_plugin._attachment` legge.

        `component` arriva risolto da chi sa tradurre i prefissi: questo
        oggetto non conosce il progetto.
        """
        data: dict[str, Any] = {"id": self.id, "component": component,
                                "level": int(self.level)}
        for key in ("optional", "on_request", "replaces_parent"):
            if getattr(self, key):
                data[key] = True
        for key in ("replaces", "on", "material"):
            if getattr(self, key):
                data[key] = getattr(self, key)
        if self.own_socket and self.own_socket != "base":
            data["own_socket"] = self.own_socket
        if self.scale_mode and self.scale_mode != "none":
            data["scale_mode"] = self.scale_mode
        for key in ("insert", "roll"):
            value = getattr(self, key)
            if value is not None:
                data[key] = float(value)
        if self.requirement:
            data["requirement"] = dict(self.requirement)
        merged = dict(self.params)
        merged.update(params or {})
        if merged:
            data["params"] = merged
        if self.tags:
            data["tags"] = list(self.tags)
        return data

    def to_dict(self) -> dict:
        data = {"id": self.id, "ref": self.ref, "level": self.level,
                "optional": self.optional, "on_request": self.on_request,
                "replaces": self.replaces, "replaces_parent": self.replaces_parent,
                "on": self.on, "own_socket": self.own_socket,
                "scale_mode": self.scale_mode, "params": dict(self.params),
                "material": self.material, "tags": list(self.tags)}
        for key in ("insert", "roll"):
            value = getattr(self, key)
            if value is not None:
                data[key] = float(value)
        if self.requirement:
            data["requirement"] = dict(self.requirement)
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "DraftChild":
        requirement = data.get("requirement")
        return cls(id=str(data["id"]), ref=str(data["ref"]),
                   level=int(data.get("level", 2)),
                   optional=bool(data.get("optional", False)),
                   on_request=bool(data.get("on_request", False)),
                   replaces=str(data.get("replaces", "")),
                   replaces_parent=bool(data.get("replaces_parent", False)),
                   on=str(data.get("on", "")),
                   own_socket=str(data.get("own_socket", "base")),
                   scale_mode=str(data.get("scale_mode", "none")),
                   insert=None if data.get("insert") is None else float(data["insert"]),
                   roll=None if data.get("roll") is None else float(data["roll"]),
                   requirement=dict(requirement) if isinstance(requirement, dict) else None,
                   params=dict(data.get("params", {})),
                   material=str(data.get("material", "")),
                   tags=_strings(data.get("tags")))


@dataclass
class DraftComponent:
    """Un componente in lavorazione. Al salvataggio e' un JSON V4/V5 e basta.

    Tre modi di avere geometria, e sono esclusivi:

        objects       gli oggetti del GLB importato che gli appartengono: al
                      salvataggio si estrae **solo** quella geometria, con le
                      trasformazioni dei nodi bakeate
        mesh_source   un GLB che esiste gia' e va copiato cosi' com'e': e' la
                      strada di chi riapre un plugin salvato, dove la mesh per
                      componente e' gia' quella giusta
        nessuno dei due  un **composite**: `Piece.mesh = None` e la geometria
                      la portano i figli. E' il caso del cavaliere fatto di
                      corpo, testa, spada e scudo, e il caso normale di un
                      concetto complesso.
    """

    key: str
    name: str
    description: str = ""
    role: str = ""
    material: str = ""
    tags: tuple[str, ...] = ()
    provides: tuple[str, ...] = ()
    styles: tuple[str, ...] = ()
    requires: tuple[str, ...] = ()
    synonyms: tuple[str, ...] = ()
    mounts: list[dict] = field(default_factory=list)
    objects: tuple[str, ...] = ()
    mesh_source: str = ""
    sockets: list[DraftSocket] = field(default_factory=list)
    params: list[DraftParam] = field(default_factory=list)
    children: list[DraftChild] = field(default_factory=list)
    layout_regions: list[dict] = field(default_factory=list)
    frame: dict = field(default_factory=dict)
    # Editor-only: non entra nel JSON del plugin. Vedi la testata del file.
    coverage: str = CANDIDATE
    notes: str = ""

    @property
    def composite(self) -> bool:
        """Nessuna geometria propria: esiste per contenere."""
        return not self.objects and not self.mesh_source

    def socket(self, name: str) -> DraftSocket | None:
        return next((s for s in self.sockets if s.name == name), None)

    def param(self, name: str) -> DraftParam | None:
        return next((p for p in self.params if p.name == name), None)

    def child(self, child_id: str) -> DraftChild | None:
        return next((c for c in self.children if c.id == child_id), None)

    def component_id(self, plugin_id: str) -> str:
        return "%s:%s" % (plugin_id, self.name)

    def to_dict(self) -> dict:
        return {"key": self.key, "name": self.name, "description": self.description,
                "role": self.role, "material": self.material,
                "tags": list(self.tags), "provides": list(self.provides),
                "styles": list(self.styles), "requires": list(self.requires),
                "synonyms": list(self.synonyms),
                "mounts": [dict(m) for m in self.mounts],
                "objects": list(self.objects), "mesh_source": self.mesh_source,
                "sockets": [s.to_dict() for s in self.sockets],
                "params": [p.to_dict() for p in self.params],
                "children": [c.to_dict() for c in self.children],
                "layout_regions": [dict(r) for r in self.layout_regions],
                "frame": dict(self.frame), "coverage": self.coverage,
                "notes": self.notes}

    @classmethod
    def from_dict(cls, data: dict) -> "DraftComponent":
        coverage = str(data.get("coverage", CANDIDATE))
        return cls(key=str(data["key"]), name=str(data["name"]),
                   description=str(data.get("description", "")),
                   role=str(data.get("role", "")),
                   material=str(data.get("material", "")),
                   tags=_strings(data.get("tags")),
                   provides=_strings(data.get("provides")),
                   styles=_strings(data.get("styles")),
                   requires=_strings(data.get("requires")),
                   synonyms=_strings(data.get("synonyms")),
                   mounts=[dict(m) for m in data.get("mounts", [])],
                   objects=_strings(data.get("objects")),
                   mesh_source=str(data.get("mesh_source", "")),
                   sockets=[DraftSocket.from_dict(s) for s in data.get("sockets", [])],
                   params=[DraftParam.from_dict(p) for p in data.get("params", [])],
                   children=[DraftChild.from_dict(c) for c in data.get("children", [])],
                   layout_regions=[dict(r) for r in data.get("layout_regions", [])],
                   frame=dict(data.get("frame", {})),
                   coverage=coverage if coverage in COVERAGE else CANDIDATE,
                   notes=str(data.get("notes", "")))


# --------------------------------------------------------------------------- #
# Il progetto
# --------------------------------------------------------------------------- #
@dataclass
class AuthoringProject:
    """Il lavoro in corso: sorgenti, componenti, gerarchia, destinazione.

    Serializzabile per riprendere domani cio' che si e' lasciato ieri, e
    **non** un formato di libreria: non lo legge il `Registry`, non lo legge il
    planner, non lo legge il resolver. Lo legge solo l'authoring.
    """

    plugin_id: str = "my_plugin"
    version: str = "1.0.0"
    name: str = ""
    description: str = ""
    author: str = ""
    license: str = ""
    tags: tuple[str, ...] = ()
    frame: dict = field(default_factory=dict)
    synonyms: dict = field(default_factory=dict)
    sources: list[SourceModel] = field(default_factory=list)
    components: list[DraftComponent] = field(default_factory=list)
    materials: list[dict] = field(default_factory=list)
    variants: list = field(default_factory=list)       # list[VariantRecipe]
    # Stato dell'editor: dove sta l'utente adesso. Non esce mai nel plugin.
    selection: tuple[str, ...] = ()
    hidden: tuple[str, ...] = ()
    current: str = ""
    destination: str = ""

    def __post_init__(self) -> None:
        self.plugin_id = check_name(self.plugin_id, "plugin_id")

    # ------------------------------------------------------------- lettura #
    def component(self, key: str) -> DraftComponent | None:
        return next((c for c in self.components if c.key == key), None)

    def component_by_name(self, name: str) -> DraftComponent | None:
        return next((c for c in self.components if c.name == name), None)

    def objects(self) -> list[SceneObject]:
        return [o for source in self.sources for o in source.objects]

    def object(self, key: str) -> SceneObject | None:
        return next((o for o in self.objects() if o.key == key), None)

    def variant(self, name: str):
        return next((v for v in self.variants if v.name == name), None)

    def owner_of(self, object_key: str) -> DraftComponent | None:
        """Quale componente possiede questo oggetto della scena. Uno al massimo."""
        return next((c for c in self.components if object_key in c.objects), None)

    def parents_of(self, key: str) -> list[tuple[DraftComponent, DraftChild]]:
        ref = DRAFT_PREFIX + key
        return [(c, child) for c in self.components
                for child in c.children if child.ref == ref]

    def roots(self) -> list[DraftComponent]:
        """I componenti che nessuno contiene: le radici della gerarchia."""
        contained = {child.draft_key for c in self.components
                     for child in c.children if child.draft_key}
        return [c for c in self.components if c.key not in contained]

    def component_ids(self) -> list[str]:
        return [c.component_id(self.plugin_id) for c in self.components]

    def resolve_ref(self, child: DraftChild) -> str:
        """Il riferimento di un arco, come id di componente installato.

        Un `variant:` si risolve sulla **base** della variant: la ricetta porta
        i parametri, non una geometria nuova (vedi `app/authoring/variant.py`).
        """
        if child.draft_key:
            target = self.component(child.draft_key)
            if target is None:
                raise AuthoringError(errors.UNKNOWN_COMPONENT,
                                     "l'arco '%s' punta a un draft che non c'e': %s"
                                     % (child.id, child.draft_key))
            return target.component_id(self.plugin_id)
        if child.variant_name:
            recipe = self.variant(child.variant_name)
            if recipe is None:
                raise AuthoringError(errors.UNKNOWN_COMPONENT,
                                     "l'arco '%s' punta a una variant che non c'e': %s"
                                     % (child.id, child.variant_name))
            return recipe.base
        return child.ref

    def resolve_params(self, child: DraftChild) -> dict:
        """I parametri che l'arco porta: i suoi, piu' quelli della variant."""
        values = {}
        if child.variant_name:
            recipe = self.variant(child.variant_name)
            if recipe is not None:
                values.update(recipe.params)
        values.update(child.params)
        return values

    # --------------------------------------------------- serializzazione #
    def to_dict(self) -> dict:
        return {"format": FORMAT_VERSION, "plugin_id": self.plugin_id,
                "version": self.version, "name": self.name,
                "description": self.description, "author": self.author,
                "license": self.license, "tags": list(self.tags),
                "frame": dict(self.frame), "synonyms": {k: list(v) for k, v
                                                        in self.synonyms.items()},
                "sources": [s.to_dict() for s in self.sources],
                "components": [c.to_dict() for c in self.components],
                "materials": [dict(m) for m in self.materials],
                "variants": [v.to_dict() for v in self.variants],
                "selection": list(self.selection), "hidden": list(self.hidden),
                "current": self.current, "destination": self.destination}

    @classmethod
    def from_dict(cls, data: dict) -> "AuthoringProject":
        from app.authoring.variant import VariantRecipe

        if not isinstance(data, dict):
            raise AuthoringError(errors.PROJECT_INVALID,
                                 "un progetto di authoring e' un oggetto JSON")
        version = int(data.get("format", 0))
        if version != FORMAT_VERSION:
            raise AuthoringError(errors.PROJECT_INVALID,
                                 "formato di progetto %r: atteso %d"
                                 % (data.get("format"), FORMAT_VERSION))
        return cls(plugin_id=str(data.get("plugin_id", "my_plugin")),
                   version=str(data.get("version", "1.0.0")),
                   name=str(data.get("name", "")),
                   description=str(data.get("description", "")),
                   author=str(data.get("author", "")),
                   license=str(data.get("license", "")),
                   tags=_strings(data.get("tags")),
                   frame=dict(data.get("frame", {})),
                   synonyms={str(k): _strings(v)
                             for k, v in (data.get("synonyms") or {}).items()},
                   sources=[SourceModel.from_dict(s) for s in data.get("sources", [])],
                   components=[DraftComponent.from_dict(c)
                               for c in data.get("components", [])],
                   materials=[dict(m) for m in data.get("materials", [])],
                   variants=[VariantRecipe.from_dict(v) for v in data.get("variants", [])],
                   selection=_strings(data.get("selection")),
                   hidden=_strings(data.get("hidden")),
                   current=str(data.get("current", "")),
                   destination=str(data.get("destination", "")))

    def save(self, path) -> Path:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True),
                               encoding="utf-8")
        return destination

    @classmethod
    def load(cls, path) -> "AuthoringProject":
        source = Path(path)
        if not source.is_file():
            raise AuthoringError(errors.FILE_MISSING,
                                 "progetto di authoring assente: %s" % source)
        try:
            data = json.loads(source.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as exc:
            raise AuthoringError(errors.PROJECT_INVALID,
                                 "progetto illeggibile: %s" % exc) from exc
        return cls.from_dict(data)

    def fingerprint(self) -> str:
        """L'identita' di cio' che finirebbe nel plugin.

        Esclude lo stato dell'editor — selezione, visibilita', componente
        corrente, destinazione, copertura — perche' muovere uno slider o
        cambiare pannello non deve far riscrivere un plugin. Serve a sapere
        quando la preview va rigenerata e quando no.
        """
        import hashlib

        data = self.to_dict()
        for key in ("selection", "hidden", "current", "destination"):
            data.pop(key, None)
        for component in data.get("components", []):
            component.pop("coverage", None)
            component.pop("notes", None)
        raw = json.dumps(data, sort_keys=True).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()
