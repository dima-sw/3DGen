"""Le API pubbliche, congelate.

Da questa fase in poi le classi qui sotto sono un **contratto**. Non perche'
siano perfette: perche' un plugin di terze parti ci si appoggia, e cambiarle in
silenzio vuol dire rompere il lavoro di qualcun altro senza accorgersene.

Questo test non impedisce di cambiarle. Impedisce di cambiarle **per sbaglio**:
chi aggiunge un campo aggiorna anche questo file, e quella riga di diff e' la
decisione presa. Chi ne toglie uno scopre subito chi lo usava.

    aggiungere    si aggiorna l'elenco qui, e il diff lo racconta
    togliere      va detto perche', e in quale versione
    rinominare    e' togliere piu' aggiungere: due decisioni, non zero

Non e' congelato tutto: i metodi che cominciano con `_` restano privati e
cambiano quando serve, e le classi non elencate qui sono libere.
"""
from __future__ import annotations

import dataclasses

import pytest

from app.build.assembler import Builder
from app.core.capability import Capability, Mount, Requirement
from app.core.component import Attachment, Component, Piece
from app.core.constraints import Constraint
from app.core.graph import CompositionGraph
from app.core.material import MaterialSpec
from app.core.params import ParamSpec
from app.core.planner.planner import Planner
from app.core.registry import PluginInfo, Registry
from app.core.resolver import Resolver
from app.core.session import GenerationResult, Options, Session
from app.core.socket import Socket
from app.core.vocabulary import EffectSpec, StyleProfile

# classe: (campi, metodi pubblici)
CONGELATE = {
    "Capability": (["name", "tags"], []),
    "Mount": (["allow_fallback", "capability", "capacity", "description", "side",
               "socket_id", "tags"],
              ["all_tags", "matches"]),
    "Requirement": (["allow_fallback", "capability", "description", "side",
                     "socket_id", "tags"],
                    ["describe", "score"]),
    "Attachment": (["component", "id", "insert", "level", "material", "on",
                    "on_request", "optional", "own_socket", "params", "replaces",
                    "replaces_parent", "requirement", "roll", "scale_mode", "tags"],
                   ["wanted_at"]),
    "Component": (["build", "children", "constraints", "description", "id",
                   "material", "mounts", "params", "provides", "requires", "role",
                   "styles", "tags"],
                  ["accepts", "describe", "expand", "provides_capability",
                   "supports_style"]),
    "Piece": (["material", "mesh", "metadata", "sockets", "tags"], ["socket"]),
    "Socket": (["capabilities", "direction", "name", "position", "radius", "side",
                "tags", "up"],
               ["all_tags", "describe", "frame", "provides"]),
    "ParamSpec": (["choices", "default", "derived", "description", "max", "min",
                   "required", "semantic_role", "type", "unit"],
                  ["coerce", "describe"]),
    "Constraint": (["expression", "message", "severity", "source", "target", "to"],
                   ["describe"]),
    "EffectSpec": (["amount", "applies_to", "apply", "changes", "conflicts",
                    "deform", "description", "id", "name", "on_failure", "params",
                    "priority", "scopes", "socket_policy", "stage", "tags"],
                   ["conflicts_with", "describe", "fits", "fits_scope",
                    "map_points", "transform"]),
    "StyleProfile": (["base", "description", "extends", "id", "name", "params",
                      "tags"],
                     ["chain", "describe", "get", "values"]),
    "MaterialSpec": (["base_color", "description", "metallic", "name", "opacity",
                      "roughness"],
                     ["describe", "rgba"]),
    "PluginInfo": (["author", "capabilities", "dependencies", "description",
                    "homepage", "id", "license", "metadata", "name", "notes",
                    "path", "sources", "tags", "version"],
                   ["describe"]),
    "Registry": ([],
                 ["capabilities", "capability", "component", "components",
                  "dependencies", "describe", "effect", "effects", "effects_for",
                  "freeze", "knows_material", "load_directory", "load_plugin",
                  "material", "materials", "missing_dependencies", "named",
                  "plugin", "plugins", "providers", "register_component",
                  "register_effect", "register_material", "register_plugin",
                  "register_style", "search", "socket_providers", "style",
                  "styles", "summary", "tags", "verify"]),
    "CompositionGraph": (["detail_level", "nodes", "operations", "order",
                          "parents", "root_id", "seed", "style", "swaps",
                          "version"],
                         ["add_child", "ancestors", "attach", "children",
                          "describe", "effect", "node", "override", "parent",
                          "path", "providers", "resolved_ref", "set_root",
                          "subtree", "swap", "swapped", "to_dict", "validate",
                          "walk", "wanted"]),
    "Resolver": ([], ["run"]),
    "Builder": ([], ["run"]),
    "Session": (["autosave", "cursor", "history", "library", "missing_plugins",
                 "planner", "plugin_paths", "provider", "registry"],
                ["animations", "build", "can_redo", "can_undo", "catalog",
                 "checks", "export", "export_animated", "generate", "goto",
                 "load_from_library", "open_project", "plan", "redo",
                 "regenerate", "restore", "save_project", "save_to_library",
                 "skeleton", "start_autosave", "stop_autosave", "undo",
                 "vocabulary"]),
    "GenerationResult": (["build", "effects", "options", "plan", "plan_json",
                          "planner", "prompt", "repaired", "report", "resolved",
                          "seconds"],
                         ["changes", "describe", "explain", "mesh", "scene",
                          "skipped", "to_dict", "trimesh_scene"]),
    "Options": (["budget", "check", "detail_level", "repair", "seed", "style"],
                ["to_dict"]),
    "Planner": ([], ["plan"]),
}

CLASSI = {c.__name__: c for c in (
    Capability, Mount, Requirement, Attachment, Component, Piece, Socket,
    ParamSpec, Constraint, EffectSpec, StyleProfile, MaterialSpec, PluginInfo,
    Registry, CompositionGraph, Resolver, Builder, Session, GenerationResult,
    Options, Planner)}


def campi(classe) -> list[str]:
    if dataclasses.is_dataclass(classe):
        return sorted(f.name for f in dataclasses.fields(classe))
    if hasattr(classe, "model_fields"):
        return sorted(classe.model_fields)
    return []


def metodi(classe) -> list[str]:
    return sorted(n for n, v in vars(classe).items()
                  if not n.startswith("_") and callable(v))


@pytest.mark.parametrize("nome", sorted(CONGELATE))
def test_the_public_fields_are_frozen(nome):
    attesi, _ = CONGELATE[nome]
    trovati = campi(CLASSI[nome])
    assert trovati == sorted(attesi), (
        "%s: campi cambiati.\n  in piu': %s\n  in meno: %s\n"
        "Se il cambiamento e' voluto, aggiorna CONGELATE in questo file: "
        "quella riga di diff e' la decisione."
        % (nome, sorted(set(trovati) - set(attesi)),
           sorted(set(attesi) - set(trovati))))


@pytest.mark.parametrize("nome", sorted(CONGELATE))
def test_the_public_methods_are_frozen(nome):
    _, attesi = CONGELATE[nome]
    trovati = metodi(CLASSI[nome])
    assert trovati == sorted(attesi), (
        "%s: metodi cambiati.\n  in piu': %s\n  in meno: %s\n"
        "Se il cambiamento e' voluto, aggiorna CONGELATE in questo file."
        % (nome, sorted(set(trovati) - set(attesi)),
           sorted(set(attesi) - set(trovati))))


def test_every_frozen_class_is_reachable_from_its_own_module():
    """Un contratto che si importa da tre posti diversi non e' un contratto."""
    import importlib

    posti = {
        "Capability": "app.core.capability", "Mount": "app.core.capability",
        "Requirement": "app.core.capability", "Attachment": "app.core.component",
        "Component": "app.core.component", "Piece": "app.core.component",
        "Socket": "app.core.socket", "ParamSpec": "app.core.params",
        "Constraint": "app.core.constraints", "EffectSpec": "app.core.vocabulary",
        "StyleProfile": "app.core.vocabulary", "MaterialSpec": "app.core.material",
        "PluginInfo": "app.core.registry", "Registry": "app.core.registry",
        "CompositionGraph": "app.core.graph", "Resolver": "app.core.resolver",
        "Builder": "app.build.assembler", "Session": "app.core.session",
        "GenerationResult": "app.core.session", "Options": "app.core.session",
        "Planner": "app.core.planner.planner",
    }
    for nome, modulo in posti.items():
        assert getattr(importlib.import_module(modulo), nome) is CLASSI[nome], nome


def test_the_frozen_list_covers_what_a_plugin_touches():
    """Le classi che un autore di plugin usa davvero devono essere congelate."""
    per_i_plugin = {"Component", "Attachment", "Piece", "Socket", "Capability",
                    "Mount", "Requirement", "ParamSpec", "Constraint",
                    "EffectSpec", "StyleProfile", "MaterialSpec"}
    assert per_i_plugin <= set(CONGELATE)
