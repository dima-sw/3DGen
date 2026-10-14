"""A reusable profile used to exercise deterministic profile materialization."""
from app.core.archetypes import ProfileSpec


COMPACT_QUADRUPED = ProfileSpec(
    id="compact_quadruped",
    aliases=("stocky_quadruped",),
    description="A reusable compact body-mass preference for quadrupeds.",
    archetypes=("quadruped",),
    default_traits=(
        {"trait": "std:body_mass", "value": 0.58, "scope": "subtree"},
    ),
)
