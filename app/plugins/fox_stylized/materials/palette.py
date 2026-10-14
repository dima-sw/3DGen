"""Reduced flat palette for the stylized fox benchmark."""
from app.core.material import MaterialSpec


MATERIALI = [
    MaterialSpec(name="fox_orange", base_color="#d86b32", roughness=0.62,
                 description="warm graphic orange fox body"),
    MaterialSpec(name="fox_dark", base_color="#36252a", roughness=0.78,
                 description="dark paws, nose, inner ears and eyes"),
    MaterialSpec(name="fox_cream", base_color="#f1c78d", roughness=0.68,
                 description="reduced cream muzzle, chest and tail tip"),
    MaterialSpec(name="fox_eye", base_color="#15151b", roughness=0.42,
                 description="bold dark eye accent"),
]
