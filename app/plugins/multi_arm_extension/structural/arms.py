from app.core.params import ParamSpec
from app.core.structural import StructuralTarget, StructuralTraitRule, StructuralTraitSpec

ARM_COUNT = StructuralTraitSpec(
    id="character:arm_count",
    aliases=("arm_count", "braccia"),
    description="ensure a requested count of compatible arm instances",
    value=ParamSpec(2, min=0, max=64),
    max_count=64,
    owner="multi_arm_extension",
)

ARM_COUNT_RULE = StructuralTraitRule(
    id="arm_count",
    trait="character:arm_count",
    prototype="corpo/torso/arm_l",
    component="humanoid_anatomical:arm",
    group="arms",
    target=StructuralTarget(role="arm", tags=("arm",)),
    description="normalize character arm counts to generic ensure_count",
)
