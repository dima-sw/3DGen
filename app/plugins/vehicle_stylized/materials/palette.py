"""Small shared palette for the stylized vehicle plugin."""
from app.core.material import MaterialSpec

MATERIALI = [
    MaterialSpec(name="car_body", base_color="#d9583f", roughness=0.48,
                 description="warm compact-car body paint"),
    MaterialSpec(name="car_body_dark", base_color="#8f3a36", roughness=0.55,
                 description="darker body-side planes and fenders"),
    MaterialSpec(name="tire", base_color="#20232a", roughness=0.82,
                 description="matte low-poly tire rubber"),
    MaterialSpec(name="light_warm", base_color="#ffd36a", roughness=0.28,
                 description="simple warm headlight or marker light"),
    MaterialSpec(name="dark_accent", base_color="#2c3139", roughness=0.62,
                 description="reduced dark accent for grille, hubs and underbody"),
]
