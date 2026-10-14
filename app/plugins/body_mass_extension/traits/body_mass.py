from app.core.params import RATIO, ParamSpec
from app.core.traits import ParamPatch, TraitMatch, TraitRule, TraitSpec


BODY_MASS = TraitSpec(
    id="std:body_mass",
    aliases=("body_mass",),
    description="perceived organic body fullness or mass",
    purpose="organic fullness/mass through public girth-like parameters",
    value=ParamSpec(0.5, RATIO, min=0.0, max=1.0),
    scopes=("local", "subtree"),
    operations=("set", "add"),
    owner="std",
    version="1.0.0",
)


HUMANOID_BODY_PARAM = TraitRule(
    id="body_root_param",
    trait="std:body_mass",
    match=TraitMatch(roles=("body",), tags=("humanoid",), params=("body_mass",)),
    patches=(ParamPatch(param="body_mass",
                        expression="1.0 + (trait - 0.5) * 0.70"),),
    description="map body mass to a public humanoid root mass parameter when present",
)

HUMANOID_TORSO_GIRTH = TraitRule(
    id="humanoid_torso_girth",
    trait="std:body_mass",
    match=TraitMatch(roles=("torso",), tags=("humanoid",),
                     param_roles=("girth",)),
    patches=(ParamPatch(semantic_role="girth",
                        expression="value * (1.0 + (trait - 0.5) * 0.42)"),),
)

HUMANOID_LIMB_GIRTH = TraitRule(
    id="humanoid_limb_girth",
    trait="std:body_mass",
    match=TraitMatch(roles=("arm", "leg", "hand", "foot", "neck"),
                     tags=("humanoid",), param_roles=("girth",)),
    patches=(ParamPatch(semantic_role="girth",
                        expression="value * (1.0 + (trait - 0.5) * 0.36)"),),
)

HUMANOID_HEAD_GIRTH = TraitRule(
    id="humanoid_head_girth",
    trait="std:body_mass",
    match=TraitMatch(roles=("head", "face"), tags=("humanoid",),
                     param_roles=("girth",)),
    patches=(ParamPatch(semantic_role="girth",
                        expression="value * (1.0 + (trait - 0.5) * 0.22)"),),
)

ANIMAL_BODY_GIRTH = TraitRule(
    id="animal_body_girth",
    trait="std:body_mass",
    match=TraitMatch(roles=("torso", "limb", "tail"), tags=("animal",),
                     param_roles=("girth",)),
    patches=(ParamPatch(semantic_role="girth",
                        expression="value * (1.0 + (trait - 0.5) * 0.30)"),),
)

ANIMAL_HEAD_GIRTH = TraitRule(
    id="animal_head_girth",
    trait="std:body_mass",
    match=TraitMatch(roles=("head",), tags=("animal",), param_roles=("girth",)),
    patches=(ParamPatch(semantic_role="girth",
                        expression="value * (1.0 + (trait - 0.5) * 0.24)"),),
)
