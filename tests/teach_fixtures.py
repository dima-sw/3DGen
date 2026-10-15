"""Risposte AI deterministiche, e un GLB vero. Niente rete, mai.

Non e' codice di prodotto ed e' solo strumento di test: produce le **stesse**
stringhe che un modello restituirebbe, nella forma che gli schemi di
`app/teach/schema.py` descrivono. E' il modo in cui il banco del drago e il
test end-to-end di §50 girano senza una chiave API e senza una connessione: la
modalita' esterna di §5 non e' un ripiego, e' una feature — quindi una risposta
incollata a mano e una risposta di un fixture sono la stessa cosa per il
sistema.

Il drago di `dragon_decomposition()` e' una decomposizione **realistica**, non
una scelta per far tornare i colori: parti mandatory e optional come un modello
le scriverebbe, e nessuna e' stata aggiunta o togliuta per ottenere una
copertura piu' bella. §46 lo chiede con queste parole.
"""
from __future__ import annotations

import json
from pathlib import Path

from tests.authoring_fixtures import box


# --------------------------------------------------------------------------- #
# Pass 1: la decomposizione concettuale
# --------------------------------------------------------------------------- #
def dragon_decomposition() -> dict:
    """La prima risposta: superficiale di proposito, come lo e' un pass 1.

    Ha i difetti che §7 chiede al raffinamento di correggere: nomi al plurale
    («eyes», «wings», «legs») invece di un nodo con `count`, un `claw` troppo
    granulare sotto la zampa, e nessun ruolo semantico.
    """
    return {
        "concept": "dragon",
        "description": ("a large winged reptile with a long neck, a horned head "
                        "and a scaled tail"),
        "root": {
            "name": "dragon", "mandatory": True, "count": 1, "importance": 1.0,
            "detail_level": 1,
            "description": "the whole creature",
            "children": [
                {"name": "body", "mandatory": True, "count": 1,
                 "importance": 1.0, "detail_level": 1,
                 "description": "the main trunk the limbs hang from"},
                {"name": "head", "mandatory": True, "count": 1,
                 "importance": 0.95, "detail_level": 1,
                 "description": "the horned, long-snouted head",
                 "children": [
                     {"name": "eyes", "mandatory": True, "count": 1,
                      "importance": 0.6, "detail_level": 2,
                      "description": "the pair of eyes"},
                     {"name": "snout", "mandatory": True, "count": 1,
                      "importance": 0.7, "detail_level": 2,
                      "description": "the long jawed muzzle"},
                     {"name": "horns", "mandatory": False, "count": 1,
                      "importance": 0.4, "detail_level": 2,
                      "description": "the pair of swept horns"},
                     {"name": "teeth", "mandatory": False, "count": 1,
                      "importance": 0.2, "detail_level": 3,
                      "description": "the visible fangs"},
                 ]},
                {"name": "wings", "mandatory": True, "count": 1,
                 "importance": 0.9, "detail_level": 1,
                 "description": "the pair of membranous wings"},
                {"name": "legs", "mandatory": True, "count": 1,
                 "importance": 0.8, "detail_level": 1,
                 "description": "the four legs",
                 "children": [
                     {"name": "claw", "mandatory": False, "count": 1,
                      "importance": 0.15, "detail_level": 4,
                      "description": "a single claw on a toe"},
                 ]},
                {"name": "tail", "mandatory": True, "count": 1,
                 "importance": 0.75, "detail_level": 1,
                 "description": "the long tapering tail"},
            ]}}


# --------------------------------------------------------------------------- #
# Pass 2: il raffinamento
# --------------------------------------------------------------------------- #
def dragon_refinement() -> dict:
    """La seconda risposta: singolari con `count`, ruoli, e il claw fuso.

    Fa esattamente le cose che §7 elenca: unisce il nodo inutilmente granulare,
    corregge i plurali in `count`, assegna i ruoli semantici, e sistema i
    livelli di dettaglio.
    """
    return {
        "concept": "dragon",
        "description": ("a large winged reptile with a long neck, a horned head "
                        "and a scaled tail"),
        "changes": [
            "eyes -> eye with count 2 (a repeated part is one node)",
            "wings -> wing with count 2",
            "legs -> leg with count 4",
            "horns -> horn with count 2, still optional",
            "claw merged into leg: a single claw is not reusable on its own",
            "roles assigned: body, head, eye, snout, horn, tooth, wing, leg, tail",
        ],
        "root": {
            "name": "dragon", "role": "creature", "mandatory": True, "count": 1,
            "importance": 1.0, "detail_level": 1,
            "description": "the whole creature",
            "children": [
                {"name": "body", "role": "body", "mandatory": True, "count": 1,
                 "importance": 1.0, "detail_level": 1,
                 "description": "the main trunk the limbs hang from"},
                {"name": "head", "role": "head", "mandatory": True, "count": 1,
                 "importance": 0.95, "detail_level": 1,
                 "description": "the horned, long-snouted head",
                 "children": [
                     {"name": "eye", "role": "eye", "mandatory": True,
                      "count": 2, "importance": 0.6, "detail_level": 2,
                      "description": "a slit-pupilled predatory eye"},
                     {"name": "snout", "role": "snout", "mandatory": True,
                      "count": 1, "importance": 0.7, "detail_level": 2,
                      "description": "the long jawed muzzle"},
                     {"name": "horn", "role": "horn", "mandatory": False,
                      "count": 2, "importance": 0.4, "detail_level": 2,
                      "description": "a swept horn above the brow"},
                     {"name": "tooth", "role": "tooth", "mandatory": False,
                      "count": 6, "importance": 0.2, "detail_level": 3,
                      "description": "a visible fang"},
                 ]},
                {"name": "wing", "role": "wing", "mandatory": True, "count": 2,
                 "importance": 0.9, "detail_level": 1,
                 "description": "a membranous wing on a long spar"},
                {"name": "leg", "role": "leg", "mandatory": True, "count": 4,
                 "importance": 0.8, "detail_level": 1,
                 "description": "a clawed walking leg"},
                {"name": "tail", "role": "tail", "mandatory": True, "count": 1,
                 "importance": 0.75, "detail_level": 1,
                 "description": "the long tapering tail"},
            ]}}


# --------------------------------------------------------------------------- #
# Le risposte di idoneita'
# --------------------------------------------------------------------------- #
def suitable_with_parameters(params: dict | None = None) -> dict:
    """`SUITABLE_WITH_PARAMETERS`: il caso che porta un giallo al verde (§18)."""
    return {"status": "SUITABLE_WITH_PARAMETERS", "confidence": 0.91,
            "reason": ("the shape reads as an eye; a predatory slit pupil needs "
                       "it wider and flatter than the default"),
            "suggested_params": dict(params or {})}


def suitable() -> dict:
    return {"status": "SUITABLE", "confidence": 0.9,
            "reason": "it declares exactly the requested role and mounts there"}


def needs_visual_check() -> dict:
    return {"status": "NEEDS_VISUAL_CHECK", "confidence": 0.55,
            "reason": "the metadata do not say how the silhouette reads"}


def not_suitable() -> dict:
    return {"status": "NOT_SUITABLE", "confidence": 0.93,
            "reason": "it is a different part of a different kind of creature"}


def visual_verdicts() -> dict:
    return {"best": "B",
            "verdicts": [
                {"variant": "A", "status": "NOT_SUITABLE",
                 "reason": "too round for a predatory eye"},
                {"variant": "B", "status": "SUITABLE_WITH_PARAMETERS",
                 "reason": "wide and flat: this reads as a dragon eye"},
                {"variant": "C", "status": "NEEDS_VISUAL_CHECK",
                 "reason": "hard to tell at this angle"}]}


# --------------------------------------------------------------------------- #
# Le risposte di implementazione
# --------------------------------------------------------------------------- #
def python_component(plugin_id: str, name: str, *, capability: str,
                     role: str = "", budget: int = 240,
                     broken: bool = False, hostile: bool = False) -> dict:
    """Un componente procedurale, nella forma dell'inviluppo di §28.

    `broken=True` restituisce un modulo che non registra nessun `Component`:
    serve a far fallire la validazione per davvero e a esercitare il prompt di
    riparazione di §34 su una diagnostica vera.

    `hostile=True` aggiunge gli import che `inspect_python` deve segnalare.
    Non e' un attacco: e' il caso che l'ispezione statica esiste per mostrare.
    """
    imports = ("import os\nimport subprocess\n" if hostile else "")
    body = '''"""%(name)s: a procedural part generated for a Teach concept."""
%(imports)sfrom app.core.capability import Capability, mount
from app.core.component import BuildContext, Component, Piece
from app.core.params import DISTANCE, RATIO, ParamSpec
from app.core.socket import socket
from app.geometry.kernel import grow

%(upper)s = Capability("%(capability)s")


def build_%(name)s(values: dict, ctx: BuildContext) -> Piece:
    length = float(values["length"])
    girth = float(values["girth"])
    mesh = grow([(0.0, girth), (1.0, girth * 0.35)], sides=6, length=length,
                axis=1)
    sockets = {
        "base": socket("base", (0.0, 0.0, 0.0), (0.0, -1.0, 0.0),
                       up=(0.0, 0.0, 1.0), radius=girth,
                       provides="%(capability)s"),
        "tip": socket("tip", (0.0, length, 0.0), (0.0, 1.0, 0.0),
                      up=(0.0, 0.0, 1.0), radius=girth * 0.35),
    }
    return Piece(mesh=mesh, sockets=sockets, tags=("%(name)s",))
'''
    tail = '''

%(upper)s_COMPONENT = Component(
    id="%(name)s",
    build=build_%(name)s,
    description="a generated %(name)s for a taught concept",
    role="%(role)s",
    params={
        "length": ParamSpec(0.35, DISTANCE, min=0.05, max=2.0,
                            semantic_role="length"),
        "girth": ParamSpec(0.09, DISTANCE, min=0.01, max=1.0,
                           semantic_role="girth"),
    },
    provides=(%(upper)s,),
    tags=frozenset({"%(name)s", "%(role)s"}),
)
'''
    values = {"name": name, "upper": name.upper(), "capability": capability,
              "role": role or name, "imports": imports}
    source = body % values
    if not broken:
        source += tail % values
    manifest = {"id": plugin_id, "version": "1.0.0", "name": name,
                "description": "generated by Teach 3DGen",
                "components": ["components/%s.py" % name],
                "capabilities": [{"name": capability,
                                  "description": "where a %s mounts" % name}],
                "tags": [name]}
    return {"files": [
        {"path": "plugin.json", "content": json.dumps(manifest, indent=2,
                                                      sort_keys=True)},
        {"path": "components/%s.py" % name, "content": source}],
        "notes": "triangle budget respected: a 6-sided sweep is %d tri"
                 % min(budget, 36)}


def data_component(plugin_id: str, name: str, *, capability: str,
                   mesh: str, role: str = "") -> dict:
    """Un componente **dati** contro un GLB fornito (§26). Nessun byte inventato."""
    definition = {
        "id": "%s:%s" % (plugin_id, name),
        "description": "a generated %s declared against a supplied mesh" % name,
        "mesh": "../meshes/%s" % mesh,
        "role": role or name,
        "tags": [name, role or name],
        "provides": [capability],
        "sockets": [{"name": "base", "position": [0.0, 0.0, 0.0],
                     "direction": [0.0, -1.0, 0.0], "up": [0.0, 0.0, 1.0],
                     "radius": 0.08}],
        "params": {"width": {"default": 1.0, "min": 0.3, "max": 2.5,
                             "type": "float", "transform": "scale_x",
                             "semantic_role": "width"}},
    }
    manifest = {"id": plugin_id, "version": "1.0.0", "name": name,
                "type": "data",
                "description": "generated by Teach 3DGen",
                "components": ["components/%s.json" % name],
                "materials": [],
                "capabilities": [{"name": capability,
                                  "description": "where a %s mounts" % name}],
                "tags": [name]}
    return {"files": [
        {"path": "plugin.json", "content": json.dumps(manifest, indent=2,
                                                      sort_keys=True)},
        {"path": "components/%s.json" % name,
         "content": json.dumps(definition, indent=2, sort_keys=True)}],
        "notes": "the mesh is the supplied asset; no geometry was invented"}


def composite_component(plugin_id: str, name: str, *, children,
                        capability: str = "") -> dict:
    """Un composite dichiarativo (§27): nessuna mesh, nessun Python."""
    definition = {
        "id": "%s:%s" % (plugin_id, name),
        "description": "a composite of already validated parts",
        "sockets": [{"name": "core", "position": [0.0, 0.0, 0.0],
                     "direction": [0.0, 1.0, 0.0], "up": [0.0, 0.0, 1.0],
                     "radius": 0.2,
                     "capabilities": [c["capability"] for c in children]}],
        "mounts": [{"capability": c["capability"], "socket_id": "core"}
                   for c in children],
        "children": [{"id": c["id"], "component": c["component"], "level": 1,
                      "requirement": {"capability": c["capability"]}}
                     for c in children],
    }
    if capability:
        definition["provides"] = [capability]
    manifest = {"id": plugin_id, "version": "1.0.0", "name": name,
                "type": "data", "description": "generated by Teach 3DGen",
                "components": ["components/%s.json" % name], "materials": [],
                "tags": [name]}
    return {"files": [
        {"path": "plugin.json", "content": json.dumps(manifest, indent=2,
                                                      sort_keys=True)},
        {"path": "components/%s.json" % name,
         "content": json.dumps(definition, indent=2, sort_keys=True)}],
        "notes": "a declarative composite: no mesh, no Python"}


# --------------------------------------------------------------------------- #
# Un GLB vero da fornire come asset
# --------------------------------------------------------------------------- #
def write_part_glb(root, name: str = "horn.glb", *,
                   extents=(0.08, 0.3, 0.08)) -> Path:
    """Un GLB con un solo oggetto, byte veri, da usare come asset fornito."""
    import trimesh

    target = Path(root) / name
    target.parent.mkdir(parents=True, exist_ok=True)
    scene = trimesh.Scene()
    scene.add_geometry(box(extents, (0.0, extents[1] / 2.0, 0.0),
                           (90, 80, 70, 255)),
                       node_name="Part", geom_name="Part")
    raw = scene.export(file_type="glb")
    target.write_bytes(raw if isinstance(raw, bytes) else bytes(raw))
    return target


# --------------------------------------------------------------------------- #
# Risposte malformate: una per ciascun rifiuto che §6 e §28 richiedono
# --------------------------------------------------------------------------- #
BAD_DECOMPOSITIONS = {
    "not json": "{not json at all",
    "not an object": "[1, 2, 3]",
    "no root": {"concept": "dragon"},
    "root is a list": {"concept": "dragon", "root": [{"name": "a",
                                                      "mandatory": True}]},
    "unknown field": {"concept": "dragon", "mesh": "x.glb",
                      "root": {"name": "dragon", "mandatory": True}},
    "unknown node field": {"concept": "dragon",
                           "root": {"name": "dragon", "mandatory": True,
                                    "triangles": 400}},
    "count zero": {"concept": "dragon",
                   "root": {"name": "dragon", "mandatory": True, "count": 0}},
    "count negative": {"concept": "dragon",
                       "root": {"name": "dragon", "mandatory": True,
                                "count": -2}},
    "count huge": {"concept": "dragon",
                   "root": {"name": "dragon", "mandatory": True,
                            "count": 10000}},
    "count not a number": {"concept": "dragon",
                           "root": {"name": "dragon", "mandatory": True,
                                    "count": "two"}},
    "empty name": {"concept": "dragon",
                   "root": {"name": "", "mandatory": True}},
    "children not a list": {"concept": "dragon",
                            "root": {"name": "dragon", "mandatory": True,
                                     "children": {"name": "head"}}},
}


def too_deep(depth: int = 12) -> dict:
    """Una gerarchia piu' profonda del tetto dichiarato (§6)."""
    node: dict = {"name": "leaf", "mandatory": True}
    for index in range(depth):
        node = {"name": "level_%d" % index, "mandatory": True,
                "children": [node]}
    return {"concept": "deep", "root": node}


def too_wide(count: int = 200) -> dict:
    """Una gerarchia con piu' nodi del tetto dichiarato (§6)."""
    return {"concept": "wide",
            "root": {"name": "wide", "mandatory": True,
                     "children": [{"name": "part_%d" % i, "mandatory": True}
                                  for i in range(count)]}}


BAD_ENVELOPES = {
    "not json": "nope",
    "not an object": "[]",
    "no files": {"notes": "here you go"},
    "files empty": {"files": []},
    "unknown key": {"files": [{"path": "plugin.json", "content": "{}"}],
                    "extra": 1},
    "unknown file key": {"files": [{"path": "plugin.json", "content": "{}",
                                    "mode": "0777"}]},
    "content not a string": {"files": [{"path": "plugin.json", "content": 7}]},
    "traversal": {"files": [{"path": "../../evil.py", "content": "x = 1"},
                            {"path": "plugin.json", "content": "{}"}]},
    "nested traversal": {"files": [{"path": "components/../../evil.json",
                                    "content": "{}"},
                                   {"path": "plugin.json", "content": "{}"}]},
    "absolute posix": {"files": [{"path": "/etc/passwd", "content": "x"},
                                 {"path": "plugin.json", "content": "{}"}]},
    "absolute windows": {"files": [{"path": "C:/Windows/win.ini", "content": "x"},
                                   {"path": "plugin.json", "content": "{}"}]},
    "unc": {"files": [{"path": "//server/share/x.json", "content": "{}"},
                      {"path": "plugin.json", "content": "{}"}]},
    "null byte": {"files": [{"path": "a\x00.json", "content": "{}"},
                            {"path": "plugin.json", "content": "{}"}]},
    "bad extension": {"files": [{"path": "mesh.glb", "content": "glTF"},
                                {"path": "plugin.json", "content": "{}"}]},
    "duplicate path": {"files": [{"path": "plugin.json", "content": "{}"},
                                 {"path": "plugin.json", "content": "{}"}]},
    "no manifest": {"files": [{"path": "components/x.json", "content": "{}"}]},
}
