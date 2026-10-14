"""Reduced palette for the stylized tree benchmark."""
from app.core.material import MaterialSpec


MATERIALI = [
    MaterialSpec(name="wood", base_color="#6f4932", roughness=0.86,
                 description="shared matte warm wood for trunk and branches"),
    MaterialSpec(name="leaf", base_color="#4f8c4b", roughness=0.78,
                 description="shared graphic green foliage"),
    MaterialSpec(name="tree_leaf_shadow", base_color="#35643b", roughness=0.82,
                 description="darker foliage for rear and lower canopy planes"),
    MaterialSpec(name="tree_accent", base_color="#d2a34f", roughness=0.62,
                 description="small warm fruit accent"),
]
