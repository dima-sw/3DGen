from app.core.params import ParamSpec
from app.core.structural import StructuralTarget, StructuralTraitRule, StructuralTraitSpec

TAIL_COUNT = StructuralTraitSpec(
    id="fantasy:tail_count",
    aliases=("tail_count",),
    description="ensure a requested count of compatible tail instances",
    value=ParamSpec(1, min=0, max=64),
    max_count=64,
    owner="multi_tail_extension",
)

TAIL_COUNT_RULE = StructuralTraitRule(
    id="tail_count",
    trait="fantasy:tail_count",
    prototype="fox/body/tail",
    component="fox_stylized:tail",
    group="tails",
    target=StructuralTarget(role="tail", tags=("tail",)),
    description="normalize fantasy tail counts to generic ensure_count",
)
