from app.core.params import ParamSpec
from app.core.structural import StructuralTarget, StructuralTraitRule, StructuralTraitSpec

WHEEL_COUNT = StructuralTraitSpec(
    id="vehicle:wheel_count",
    aliases=("wheel_count", "ruote"),
    description="ensure a requested count of compatible wheel instances",
    value=ParamSpec(4, min=0, max=64),
    max_count=64,
    owner="multi_wheel_extension",
)

WHEEL_COUNT_RULE = StructuralTraitRule(
    id="wheel_count",
    trait="vehicle:wheel_count",
    prototype="car/wheel_fl",
    component="vehicle_stylized:wheel",
    group="wheels",
    target=StructuralTarget(role="wheel", tags=("wheel",)),
    description="normalize vehicle wheel counts to generic ensure_count",
)
