from app.core.params import ParamSpec
from app.core.structural import StructuralTarget, StructuralTraitRule, StructuralTraitSpec

# `purpose` says what the trait *means*, not what the engine does with it: how
# many arm parts the model has. The planner needs that sentence to tell this
# apart from a trait that changes an existing part, and the sentence belongs
# here — in the library that owns the word "arm" — and not in the core.
# `aliases` are the words a request uses for the same thing, in both languages
# the library is written in.
ARM_COUNT = StructuralTraitSpec(
    id="character:arm_count",
    aliases=("arm_count", "braccia", "arms", "arm"),
    description="ensure a requested count of compatible arm instances",
    purpose="how many arm parts the model has: desired number of parts with "
            "role 'arm'; changes the count, not the proportions",
    value=ParamSpec(2, min=0, max=64),
    max_count=64,
    owner="multi_arm_extension",
)

ARM_COUNT_RULE = StructuralTraitRule(
    id="arm_count",
    trait="character:arm_count",
    component="humanoid_anatomical:arm",
    group="arms",
    target=StructuralTarget(role="arm", tags=("arm",)),
    description="normalize character arm counts to generic ensure_count",
)
