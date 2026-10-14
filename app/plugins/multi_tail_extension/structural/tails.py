from app.core.params import ParamSpec
from app.core.structural import StructuralTarget, StructuralTraitRule, StructuralTraitSpec

# See `multi_arm_extension/structural/arms.py` for why `purpose` and the extra
# aliases are declared here instead of in the core.
TAIL_COUNT = StructuralTraitSpec(
    id="fantasy:tail_count",
    aliases=("tail_count", "tails", "code"),
    description="ensure a requested count of compatible tail instances",
    purpose="how many tail parts the model has: desired number of parts with "
            "role 'tail'; changes the count, not the length",
    value=ParamSpec(1, min=0, max=64),
    max_count=64,
    owner="multi_tail_extension",
)

TAIL_COUNT_RULE = StructuralTraitRule(
    id="tail_count",
    trait="fantasy:tail_count",
    component="fox_stylized:tail",
    group="tails",
    target=StructuralTarget(role="tail", tags=("tail",)),
    description="normalize fantasy tail counts to generic ensure_count",
)
