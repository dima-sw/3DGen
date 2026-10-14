from __future__ import annotations

from app.core.archetypes import (ArchetypeSpec, ConceptResolver,
                                 ImplementationBinding, ProfileSpec)
from app.core.registry import Registry
from app.core.session import Session


def registry() -> Registry:
    result = Registry()
    result.load_directory("app/plugins")
    return result


def profile_registry() -> Registry:
    reg = registry()
    reg.register_archetype(ArchetypeSpec("test:subject"))
    reg.register_implementation_binding(ImplementationBinding(
        "test:tree", "tree_stylized:tree", ("test:subject",)))
    return reg


def test_profile_include_child_overrides_included_default():
    reg = profile_registry()
    reg.register_profile(ProfileSpec(
        "test:base", archetypes=("test:subject",),
        default_traits=({"trait": "test:value", "value": 1},)))
    reg.register_profile(ProfileSpec(
        "test:child", archetypes=("test:subject",), includes=("test:base",),
        default_traits=({"trait": "test:value", "value": 2},)))
    plan = ConceptResolver(reg).resolve(
        "subject", archetypes=("test:subject",), profiles=("test:child",))
    assert plan.ok
    assert plan.materialized_traits == [{"trait": "test:value", "value": 2}]


def test_sibling_profiles_conflict_on_same_channel():
    reg = profile_registry()
    for name, value in (("a", 1), ("b", 2)):
        reg.register_profile(ProfileSpec(
            "test:" + name, archetypes=("test:subject",),
            default_traits=({"trait": "test:value", "value": value},)))
    plan = ConceptResolver(reg).resolve(
        "subject", archetypes=("test:subject",), profiles=("test:a", "test:b"))
    assert "TRAIT_DEFAULT_CONFLICT" in {d["code"] for d in plan.diagnostics}


def test_profile_include_cycle_and_missing_reference_are_rejected():
    reg = Registry()
    reg.register_archetype(ArchetypeSpec("test:subject"))
    reg.register_profile(ProfileSpec("test:a", includes=("test:b",)))
    reg.register_profile(ProfileSpec("test:b", includes=("test:a",)))
    reg.register_profile(ProfileSpec("test:missing", includes=("test:nope",)))
    codes = reg.verify().codes()
    assert "PROFILE_CYCLE" in codes
    assert "PROFILE_INCLUDE_MISSING" in codes


def test_profile_missing_trait_contract_is_rejected():
    reg = Registry()
    reg.register_archetype(ArchetypeSpec("test:subject"))
    reg.register_profile(ProfileSpec(
        "test:bad", archetypes=("test:subject",),
        default_traits=({"trait": "missing:trait", "value": 1},),
        structural_defaults=({"trait": "missing:structural", "value": 2},)))
    codes = reg.verify().codes()
    assert "PROFILE_TRAIT_MISSING" in codes
    assert "PROFILE_STRUCTURAL_TRAIT_MISSING" in codes


def test_profile_alias_ambiguity_is_explicit():
    reg = Registry()
    reg.register_profile(ProfileSpec("a:p", aliases=("shared",)))
    reg.register_profile(ProfileSpec("b:p", aliases=("shared",)))
    assert reg.profile("shared") is None
    assert reg.profile_ambiguous("shared")


def test_profile_archetype_compatibility_is_validated():
    reg = profile_registry()
    reg.register_archetype(ArchetypeSpec("test:other"))
    reg.register_profile(ProfileSpec("test:other_profile", archetypes=("test:other",)))
    plan = ConceptResolver(reg).resolve(
        "subject", archetypes=("test:subject",), profiles=("test:other_profile",))
    assert "PROFILE_INCOMPATIBLE" in {d["code"] for d in plan.diagnostics}


def test_explicit_request_precedence_uses_trait_channel():
    defaults = [{"trait": "std:body_mass", "value": 0.58}]
    explicit = [{"trait": "std:body_mass", "value": 0.91}]
    assert Session._merge_inferred_requests(defaults, explicit) == explicit
