from app.core.params import ParamSpec
from app.core.structural import StructuralTarget, StructuralTraitRule, StructuralTraitSpec

# See `multi_arm_extension/structural/arms.py` for why `purpose` and the extra
# aliases are declared here: the library owns the word "wheel", the core does
# not, and the planner cannot choose a count trait it cannot tell apart from a
# parameter.
WHEEL_COUNT = StructuralTraitSpec(
    id="vehicle:wheel_count",
    aliases=("wheel_count", "ruote", "wheels"),
    description="ensure a requested count of compatible wheel instances",
    purpose="how many wheel parts the model has: desired number of parts with "
            "role 'wheel'; changes the count, not the size",
    value=ParamSpec(4, min=0, max=64),
    max_count=64,
    owner="multi_wheel_extension",
)

WHEEL_COUNT_RULE = StructuralTraitRule(
    id="wheel_count",
    trait="vehicle:wheel_count",
    component="vehicle_stylized:wheel",
    group="wheels",
    target=StructuralTarget(role="wheel", tags=("wheel",)),
    description="normalize vehicle wheel counts to generic ensure_count",
)
