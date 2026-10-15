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
from app.core.archetypes import (ArchetypeSpec, ConceptCoverage, ConceptResolver,
                                 ConceptDiagnostic, ConceptResolutionPlan,
                                 ImplementationBinding, ProfileSpec)
from app.core.component import Attachment, Component, Piece
from app.core.constraints import Constraint
from app.core.graph import CompositionGraph
from app.core.layout import (LayoutPlacement, LayoutPlan, LayoutPolicy,
                             LayoutProblem, LayoutRegion)
from app.core.material import MaterialSpec
from app.core.params import ParamSpec
from app.core.planner.planner import Planner
from app.core.registry import PluginInfo, Registry
from app.core.resolver import Resolver
from app.core.session import GenerationResult, Options, Session
from app.core.socket import Socket
from app.core.structural import (EnsureCountOperation, GraphRewritePlan,
                                 StructuralTraitRequest, StructuralTraitResolution,
                                 StructuralTraitRule, StructuralTraitSpec)
from app.core.traits import (ParamPatch, TraitMatch, TraitRequest,
                             TraitResolution, TraitRule, TraitSpec)
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
    # [V5] `frame` e `param_effects` sono due campi nuovi, additivi: la
    # convenzione d'asse dichiarata (`app/core/frame.py`) e i parametri che
    # pilotano un effetto installato. Un componente che non li dichiara si
    # comporta come prima.
    "Component": (["build", "children", "constraints", "description", "frame",
                   "id", "material", "mounts", "param_effects", "params",
                   "provides", "requires", "role", "styles", "tags",
                   "layout_regions"],
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
    # V1: `synonyms` sono i ponti fra parole dichiarati nel manifest. Dati, non
    # codice: servono al retrieval semantico a sapere che una jeep e' un'auto
    # senza che il core lo sappia.
    # [V5] `frame` e' additivo: la convenzione d'asse che il manifest dichiara
    # per i componenti del plugin, prima prosa libera in `metadata`.
    "PluginInfo": (["author", "capabilities", "dependencies", "description",
                    "homepage", "id", "license", "metadata", "name", "notes",
                    "path", "sources", "synonyms", "tags", "version",
                    "kind", "data_components", "data_materials", "fingerprint",
                    "frame"],
                   ["describe"]),
    "Registry": ([],
                 ["capabilities", "capability", "component", "components",
                  "dependencies", "describe", "effect", "effects", "effects_for",
                  "freeze", "knows_material", "load_directory", "load_plugin",
                  "material", "materials", "missing_dependencies", "named",
                  "plugin", "plugins", "providers", "register_component",
                  "register_effect", "register_material", "register_plugin",
                  "register_style", "register_trait", "register_trait_rule",
                  "register_layout_policy", "register_structural_trait",
                  "register_structural_trait_rule",
                  "search", "socket_providers", "style", "styles", "summary",
                  "tags", "trait", "trait_ambiguous", "trait_rules", "traits",
                  "layout_policies", "layout_policy", "structural_trait",
                  "structural_trait_rules", "structural_traits",
                  "archetype", "archetype_ambiguous", "archetype_ids",
                  "archetypes", "concept_index", "implementation_binding",
                  "implementation_bindings", "profile", "profile_ambiguous",
                  "profile_ids", "profiles", "register_archetype",
                  "register_implementation_binding", "register_profile",
                  "synonyms",      # V1: i ponti fra parole dei plugin installati
                  "verify"]),
    # V3: `identity`/`identities`/`by_identity` sono l'identita' stabile dei
    # nodi — derivata, non un campo, per questo sono metodi e non attributi.
    # `structural_provenance` e' da dove vengono i nodi nati da una riscrittura.
    "CompositionGraph": (["detail_level", "nodes", "operations", "order",
                          "parents", "root_id", "seed", "style", "swaps",
                          "traits", "structural_traits", "graph_rewrite_plan",
                          "layout_plan", "structural_resolution",
                          "concept_resolution", "structural_provenance",
                          "version"],
                         ["add_child", "ancestors", "attach", "by_identity",
                          "children",
                          "describe", "effect", "identities", "identity",
                          "node", "override", "parent",
                          "path", "providers", "resolved_ref", "set_root",
                          "subtree", "swap", "swapped", "to_dict", "validate",
                          "walk", "wanted"]),
    "Resolver": ([], ["run"]),
    "Builder": ([], ["run"]),
    # V1: `component_index` e `shortlist` sono lo stadio di retrieval davanti al
    # planner. `vocabulary` resta, con due parametri facoltativi in piu'.
    # V4: `changed_plugins` e' additivo e sta accanto a `missing_plugins`. Un
    # progetto riaperto con un plugin dati modificato a versione ferma va
    # ricostruito con la libreria di adesso, e questo lo dice.
    "Session": (["autosave", "changed_plugins", "cursor", "history", "library",
                 "missing_plugins", "planner", "plugin_paths", "provider",
                 "registry"],
                ["animations", "build", "can_redo", "can_undo", "catalog",
                 "checks", "component_index", "configure_ai", "export",
                 "export_animated", "generate", "goto",
                 "load_from_library", "open_project", "plan", "redo",
                 "regenerate", "reload_plugins", "restore", "save_project",
                 "save_to_library",
                 "shortlist", "skeleton", "start_autosave", "stop_autosave",
                 "undo", "vocabulary"]),
    # V1: `shortlist` e' la rosa di componenti che il planner ha avuto davanti,
    # e `retrieval()` la racconta. Senza, un piano non e' spiegabile: non si
    # saprebbe fra che cosa il modello stava scegliendo.
    "GenerationResult": (["build", "concept_resolution", "effects", "layout", "options", "plan", "plan_json",
                          "planner", "prompt", "provenance", "repaired", "report", "resolved",
                          "seconds", "shortlist", "structural", "traits"],
                         # V3.5: `structural_changes()` dice quali richieste
                         # strutturali sono state **applicate**. E' il
                         # complemento di `skipped()`: senza i due insieme,
                         # `ok=True` non distingueva una richiesta soddisfatta
                         # da una persa. Additivo, come il resto di questo file.
                         ["changes", "degradation", "describe", "explain",
                          "mesh", "retrieval", "scene", "skipped",
                          "structural_changes", "to_dict",
                          "trimesh_scene"]),
    # [V5] `frame_policy` e' la politica del progetto sulle convenzioni d'asse
    # discordanti: `diagnose` (il predefinito, come prima) o `strict`.
    "Options": (["budget", "check", "detail_level", "frame_policy", "repair",
                 "seed", "style"],
                ["to_dict"]),
    "Planner": ([], ["plan"]),
    "TraitSpec": (["aliases", "description", "id", "operations", "owner",
                   "purpose", "scopes", "value", "version"], []),
    "TraitRequest": (["on", "op", "scope", "trait", "value"], []),
    "TraitMatch": (["capabilities", "components", "param_roles", "params",
                    "roles", "styles", "tags"], []),
    "ParamPatch": (["expression", "param", "semantic_role"], ["targets"]),
    "TraitRule": (["description", "effects", "id", "match", "patches",
                   "trait"], []),
    "TraitResolution": (["applied", "conflicts", "diagnostics", "skipped",
                         "unsupported", "values"], ["to_dict"]),
    "LayoutRegion": (["id", "anchor_socket", "allows_role", "allows_capability",
                       "allows_tags", "default_policy", "allowed_policies",
                       "capacity", "span", "spread_angle", "min_spacing",
                       "min_scale", "max_scale", "allow_scale_to_fit",
                       "symmetry_group", "side", "center", "direction", "up",
                       "axis", "elevation_span", "depth_offset"], ["allows", "validate"]),
    "LayoutPolicy": (["id", "apply", "description"], []),
    "LayoutPlacement": (["node", "parent", "region", "policy", "frame_index",
                          "socket", "scale", "frame"], ["to_dict"]),
    "LayoutProblem": (["code", "parent", "child_group", "requested", "placed",
                        "remaining", "region", "required_span", "available_span",
                        "min_scale", "max_scale", "attempts"], ["to_dict"]),
    "LayoutPlan": (["placements", "problems", "provenance"],
                    ["by_parent", "to_dict"]),
    "StructuralTraitSpec": (["id", "aliases", "description", "value", "modes",
                              "max_count", "owner", "version", "purpose"], []),
    "StructuralTraitRequest": (["trait", "value", "on", "mode", "scope", "target"],
                                ["normalized_target"]),
    "StructuralTraitRule": (["id", "trait", "prototype", "component", "group",
                              "target", "description"], []),
    # V3: `on` e' l'ambito in cui cercare il prototipo, non il prototipo.
    # `prototype` resta, e resta un percorso, ma adesso e' facoltativo.
    "EnsureCountOperation": (["op", "prototype", "count", "group", "mode", "trait",
                               "rule", "component", "target", "on"], ["to_dict"]),
    "GraphRewritePlan": (["operations"], ["to_dict"]),
    "StructuralTraitResolution": (["plan", "applied", "created", "skipped",
                                    "conflicts", "diagnostics"], ["to_dict"]),
    "ArchetypeSpec": (["aliases", "component_preferences", "default_traits",
                        "description", "id", "layout_preferences", "owner",
                        "parents", "preferred_capabilities", "preferred_roles",
                        "required_capabilities", "required_roles",
                        "structural_expectations", "tags", "version"], ["to_dict"]),
    "ProfileSpec": (["aliases", "archetypes", "component_preferences",
                      "default_traits", "description", "id", "includes", "owner",
                      "param_role_preferences", "structural_defaults",
                      "style_preferences", "version"], ["to_dict"]),
    "ImplementationBinding": (["id", "implementation", "owner",
                                "supported_archetypes", "version"], ["to_dict"]),
    "ConceptDiagnostic": (["code", "message", "severity", "where"], ["to_dict"]),
    "ConceptCoverage": (["candidate", "conflicting", "hard_compatible", "match",
                          "preferred_hits", "reasons", "score", "supported",
                          "unsupported"], ["to_dict"]),
    # V2: `match`, `confidence` e `strategy` dicono **come** si e' arrivati al
    # risultato, e `describe()` lo racconta. Senza, un'approssimazione sarebbe
    # indistinguibile da una scelta esatta nel progetto salvato.
    "ConceptResolutionPlan": (["adaptations", "archetypes", "candidate_bindings",
                                "component_preferences", "confidence", "conflicts",
                                "coverage", "diagnostics", "match",
                                "materialized_params",
                                "materialized_structural_traits",
                                "materialized_traits", "param_role_preferences",
                                "profiles", "provenance",
                                "requested_concept", "selected_binding",
                                "selected_root_implementation", "semantic_source",
                                "strategy",
                                "style_preferences", "unsupported"],
                               ["describe", "to_dict"]),
    # V2: la degradazione lavora sui componenti installati, quindi il resolver
    # espone l'indice semantico, i candidati e il nome esatto.
    "ConceptResolver": ([], ["by_name", "candidates", "index", "resolve"]),
}

CLASSI = {c.__name__: c for c in (
    Capability, Mount, Requirement, Attachment, Component, Piece, Socket,
    ParamSpec, Constraint, EffectSpec, StyleProfile, MaterialSpec, PluginInfo,
    Registry, CompositionGraph, Resolver, Builder, Session, GenerationResult,
    Options, Planner, TraitSpec, TraitRequest, TraitMatch, ParamPatch, TraitRule,
    TraitResolution, LayoutRegion, LayoutPolicy, LayoutPlacement, LayoutProblem,
    LayoutPlan, StructuralTraitSpec, StructuralTraitRequest, StructuralTraitRule,
    EnsureCountOperation, GraphRewritePlan, StructuralTraitResolution,
    ArchetypeSpec, ProfileSpec, ImplementationBinding, ConceptDiagnostic,
    ConceptCoverage, ConceptResolutionPlan, ConceptResolver)}


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
        "TraitSpec": "app.core.traits", "TraitRequest": "app.core.traits",
        "TraitMatch": "app.core.traits", "ParamPatch": "app.core.traits",
        "TraitRule": "app.core.traits", "TraitResolution": "app.core.traits",
        "LayoutRegion": "app.core.layout", "LayoutPolicy": "app.core.layout",
        "LayoutPlacement": "app.core.layout", "LayoutProblem": "app.core.layout",
        "LayoutPlan": "app.core.layout",
        "StructuralTraitSpec": "app.core.structural",
        "StructuralTraitRequest": "app.core.structural",
        "StructuralTraitRule": "app.core.structural",
        "EnsureCountOperation": "app.core.structural",
        "GraphRewritePlan": "app.core.structural",
        "StructuralTraitResolution": "app.core.structural",
        "ArchetypeSpec": "app.core.archetypes",
        "ProfileSpec": "app.core.archetypes",
        "ImplementationBinding": "app.core.archetypes",
        "ConceptDiagnostic": "app.core.archetypes",
        "ConceptCoverage": "app.core.archetypes",
        "ConceptResolutionPlan": "app.core.archetypes",
        "ConceptResolver": "app.core.archetypes",
    }
    for nome, modulo in posti.items():
        assert getattr(importlib.import_module(modulo), nome) is CLASSI[nome], nome


def test_the_frozen_list_covers_what_a_plugin_touches():
    """Le classi che un autore di plugin usa davvero devono essere congelate."""
    per_i_plugin = {"Component", "Attachment", "Piece", "Socket", "Capability",
                    "Mount", "Requirement", "ParamSpec", "Constraint",
                    "EffectSpec", "StyleProfile", "MaterialSpec", "TraitSpec",
                    "TraitRequest", "TraitMatch", "ParamPatch", "TraitRule",
                    "TraitResolution", "StructuralTraitSpec", "StructuralTraitRequest",
                    "StructuralTraitRule", "EnsureCountOperation", "GraphRewritePlan",
                    "StructuralTraitResolution", "LayoutRegion", "LayoutPolicy",
                    "LayoutPlacement", "LayoutProblem", "LayoutPlan",
                    "ArchetypeSpec", "ProfileSpec", "ImplementationBinding"}
    assert per_i_plugin <= set(CONGELATE)
