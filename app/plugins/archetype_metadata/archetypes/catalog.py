"""Minimal semantic catalog for the V1 concept-resolution benchmarks."""
from app.core.archetypes import ArchetypeSpec


ARCHETYPES = (
    ArchetypeSpec(
        id="animal", aliases=("animale",),
        description="A complete animal subject.",
        required_capabilities=("animal",)),
    ArchetypeSpec(
        id="quadruped", aliases=("quadrupede",), parents=("animal",),
        description="An animal represented by a four-legged body plan.",
        preferred_roles=("body",), preferred_capabilities=("limb_mount",)),
    ArchetypeSpec(
        id="felid", aliases=("felino",), parents=("quadruped",),
        description="A cat-like quadruped body plan.",
        preferred_capabilities=("head_mount", "limb_mount")),
    ArchetypeSpec(
        id="bird", aliases=("uccello",), parents=("animal",),
        description="A bird body plan requiring an explicit bird implementation.",
        required_capabilities=("bird",)),
    ArchetypeSpec(
        id="raptor", aliases=("rapace",), parents=("bird",),
        description="A predatory bird body plan.",
        preferred_capabilities=("wing", "beak", "talon")),
    ArchetypeSpec(
        id="vehicle", aliases=("veicolo",),
        description="A complete vehicle subject.",
        required_capabilities=("vehicle",)),
    ArchetypeSpec(
        id="wheeled_vehicle", aliases=("veicolo_ruotato",), parents=("vehicle",),
        description="A vehicle body plan with wheels.",
        preferred_capabilities=("wheel_mount",)),
    ArchetypeSpec(
        id="car_like", aliases=("auto",), parents=("wheeled_vehicle",),
        description="A compact car-like vehicle basis."),
    ArchetypeSpec(
        id="tree", aliases=("albero",),
        description="A complete branching tree subject.",
        required_capabilities=("building",),
        preferred_capabilities=("branch_mount", "crown_mount")),
)
