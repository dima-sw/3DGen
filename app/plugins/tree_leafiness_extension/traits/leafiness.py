from app.core.params import RATIO, ParamSpec
from app.core.traits import ParamPatch, TraitMatch, TraitRule, TraitSpec


LEAFINESS = TraitSpec(
    id="botany:leafiness",
    aliases=("leafiness",),
    description="deformational amount of existing foliage volume",
    purpose="foliage volume on compatible vegetation components",
    value=ParamSpec(1.0, RATIO, min=0.0, max=1.0),
    scopes=("local", "subtree"),
    operations=("set", "add"),
    owner="botany",
    version="1.0.0",
)


CROWN_WIDTH = TraitRule(
    id="crown_width",
    trait="botany:leafiness",
    match=TraitMatch(roles=("tree_crown",), tags=("tree", "crown", "foliage"),
                     params=("crown_width",)),
    patches=(ParamPatch(param="crown_width",
                        expression="value * (0.55 + trait * 0.45)"),),
)

CROWN_HEIGHT = TraitRule(
    id="crown_height",
    trait="botany:leafiness",
    match=TraitMatch(roles=("tree_crown",), tags=("tree", "crown", "foliage"),
                     params=("crown_height",)),
    patches=(ParamPatch(param="crown_height",
                        expression="value * (0.58 + trait * 0.42)"),),
)
