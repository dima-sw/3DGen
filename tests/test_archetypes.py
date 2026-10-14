from __future__ import annotations

import json

from app.core.archetypes import (ArchetypeSpec, ConceptResolver,
                                 ImplementationBinding)
from app.core.planner.planner import LLMPlanner, PlanRequest, SISTEMA
from app.core.planner.schema import plan_schema
from app.core.planner.vocabulary import MAX_CONCEPT_SHORTLIST, build_vocabulary
from app.core.registry import Registry


def registry() -> Registry:
    result = Registry()
    result.load_directory("app/plugins")
    return result


def test_installed_archetype_registry_and_aliases_are_stable():
    reg = registry()
    assert reg.archetype("felino").id == "archetype_metadata:felid"
    assert reg.archetype("auto").id == "archetype_metadata:car_like"
    assert reg.archetype_ids() == sorted(reg.archetype_ids())
    assert len(reg.archetypes()) == 9


def test_severe_case_has_zero_lynx_metadata():
    reg = registry()
    assert reg.component("lynx") is None
    assert reg.archetype("lynx") is None
    assert reg.profile("lynx") is None
    assert all("lynx" not in alias for spec in reg.archetypes()
               for alias in spec.aliases)
    assert all("lynx" not in alias for spec in reg.profiles()
               for alias in spec.aliases)


def test_missing_parent_and_cycle_are_diagnostic():
    reg = Registry()
    reg.register_archetype(ArchetypeSpec("test:missing", parents=("test:nope",)))
    reg.register_archetype(ArchetypeSpec("test:a", parents=("test:b",)))
    reg.register_archetype(ArchetypeSpec("test:b", parents=("test:a",)))
    codes = reg.verify().codes()
    assert "ARCHETYPE_PARENT_MISSING" in codes
    assert "ARCHETYPE_CYCLE" in codes


def test_alias_ambiguity_never_uses_import_order():
    reg = Registry()
    reg.register_archetype(ArchetypeSpec("a:item", aliases=("shared",)))
    reg.register_archetype(ArchetypeSpec("b:item", aliases=("shared",)))
    assert reg.archetype("shared") is None
    assert reg.archetype_ambiguous("shared")
    assert "ARCHETYPE_ALIAS_AMBIGUOUS" in reg.verify().codes()


def test_multiple_parent_child_override_resolves_parent_conflict():
    reg = registry()
    reg.register_archetype(ArchetypeSpec(
        "test:a", default_traits=({"trait": "test:value", "value": 1},)))
    reg.register_archetype(ArchetypeSpec(
        "test:b", default_traits=({"trait": "test:value", "value": 2},)))
    reg.register_archetype(ArchetypeSpec(
        "test:hybrid", parents=("test:b", "test:a"),
        default_traits=({"trait": "test:value", "value": 3},)))
    reg.register_implementation_binding(ImplementationBinding(
        "test:hybrid_tree", "tree_stylized:tree", ("test:hybrid",)))
    plan = ConceptResolver(reg).resolve("hybrid", archetypes=("test:hybrid",))
    assert plan.ok
    assert [item["value"] for item in plan.materialized_traits
            if item["trait"] == "test:value"] == [3]
    assert not plan.conflicts


def test_multiple_parent_same_channel_without_child_override_conflicts():
    reg = registry()
    reg.register_archetype(ArchetypeSpec(
        "test:a", default_traits=({"trait": "test:value", "value": 1},)))
    reg.register_archetype(ArchetypeSpec(
        "test:b", default_traits=({"trait": "test:value", "value": 2},)))
    reg.register_archetype(ArchetypeSpec("test:hybrid", parents=("test:a", "test:b")))
    reg.register_implementation_binding(ImplementationBinding(
        "test:hybrid_tree", "tree_stylized:tree", ("test:hybrid",)))
    plan = ConceptResolver(reg).resolve("hybrid", archetypes=("test:hybrid",))
    assert "TRAIT_DEFAULT_CONFLICT" in {d["code"] for d in plan.diagnostics}
    assert plan.conflicts


def test_compact_index_is_global_and_detail_is_bounded():
    reg = registry()
    for index in range(MAX_CONCEPT_SHORTLIST + 7):
        reg.register_archetype(ArchetypeSpec("extra:a%02d" % index))
    vocabulary = build_vocabulary(reg)
    assert len(vocabulary.archetypes) == len(reg.archetypes())
    assert len(vocabulary.archetype_details) == MAX_CONCEPT_SHORTLIST
    assert len(json.dumps(vocabulary.to_dict()).encode("utf-8")) > 0


def test_compact_vocabulary_references_repeated_parameter_contracts_losslessly():
    vocabulary = build_vocabulary(registry())
    compact = vocabulary.to_compact_text()
    assert "## PARAM SETS (shared component contracts)" in compact
    assert "params=@P" in compact
    for component in vocabulary.components:
        signature = [p.to_text() for p in component.params if not p.derived]
        if signature:
            assert all(value in compact for value in signature[:12])


def test_compact_production_payload_stays_within_groq_budget():
    """Il corpo compatto sta nel budget **dichiarato** dal fornitore.

    La soglia era `24_576`, un margine scelto a mano piu' stretto del budget
    vero. V3.5 l'ha superata di 1,4 KB per due ragioni che sono il contenuto
    della milestone: il prompt di sistema adesso dichiara le chiavi `traits` e
    `structural_traits` (+1,1 KB) e ogni trait dice che cosa seleziona (+0,8 KB
    sulla libreria intera). Senza quelle due cose il planner non poteva
    scegliere uno structural trait — vedi `V3.5-RESULTS.md`.

    Rinumerare un margine a mano vuol dire rifarlo alla prossima riga di
    prompt. Si misura invece contro `PROVIDERS["groq"].input_budget`, che e'
    la soglia vera: e' quella che fa passare `LLMPlanner` alla forma compatta,
    quindi e' quella che questo test esisteva per proteggere. La verifica di
    crescita resta, e in una forma che non ha numeri da tarare: la forma
    compatta deve essere **piu' piccola** di quella piena.

    Questo e' comunque il caso peggiore: la libreria intera, senza la rosa che
    V1 ha messo davanti al planner.
    """
    from app.core.config import PROVIDERS

    vocabulary = build_vocabulary(registry())
    request = PlanRequest("crea una lince low-poly", vocabulary,
                          style="low_poly", detail_level=3, seed=17)
    user, _ = LLMPlanner._render_message(request, compact=True)
    pieno, _ = LLMPlanner._render_message(request, compact=False)
    estimate = LLMPlanner._estimate_payload(SISTEMA, user, plan_schema())

    budget = PROVIDERS["groq"].input_budget
    assert budget, "groq dichiara un input_budget: senza, questo test non dice niente"
    assert estimate < budget, estimate
    assert estimate < LLMPlanner._estimate_payload(SISTEMA, pieno, plan_schema())


def test_binding_must_reference_real_component_and_archetype():
    reg = Registry()
    reg.register_implementation_binding(ImplementationBinding(
        "third:bad", "missing:root", ("missing:archetype",)))
    codes = reg.verify().codes()
    assert "BINDING_IMPLEMENTATION_MISSING" in codes
    assert "BINDING_ARCHETYPE_MISSING" in codes


def test_third_party_metadata_and_cross_plugin_binding_registration():
    reg = registry()
    assert reg.register_archetype(ArchetypeSpec(
        "custom_archetype", aliases=("custom",)), plugin_id="thirdparty")
    assert reg.register_implementation_binding(ImplementationBinding(
        "external_tree", "tree_stylized:tree", ("custom_archetype",)),
        plugin_id="thirdparty")
    assert reg.archetype("custom").id == "thirdparty:custom_archetype"
    assert reg.implementation_binding("thirdparty:external_tree").implementation == \
        "tree_stylized:tree"
    assert any(item["id"] == "thirdparty:custom_archetype"
               for item in reg.concept_index())
    assert ConceptResolver(reg).resolve("custom").selected_root_implementation == \
        "tree_stylized:tree"
