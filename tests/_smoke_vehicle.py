from app.core.logging_setup import setup
from app.core.spec import GenerationPlan, MaterialSpec
from app.build.builder import build_scene
from app.ui.offscreen import render

setup("INFO")

plan = GenerationPlan(
    prompt="Crea una Jeep militare 4x4 verde con ruote grandi",
    object_type="jeep militare",
    template="vehicle",
    style="realistic",
    params={
        "body_style": "offroad",
        "length": 4.3, "width": 1.95, "height": 1.95,
        "wheel_radius": 0.46, "wheel_width": 0.32,
        "ground_clearance": 0.34, "door_count": 4,
        "has_roof": False, "has_roll_bar": True, "has_bull_bar": True,
        "has_spare_wheel": True, "has_snorkel": True, "fender_flare": 0.07,
        "windshield_tilt": 8,
    },
    materials=[MaterialSpec(name="body", base_color="#4a5533", roughness=0.75, metallic=0.15)],
)

scene = build_scene(plan)
print("SCENA:", scene.summary())
for w in scene.warnings:
    print("  WARN:", w)
print("nodi:", ", ".join(n.id for n in scene.nodes[:14]), "...")

render(scene, "output/preview_jeep.png", azimuth=42, elevation=17)
print("render -> output/preview_jeep.png")

glb = scene.to_trimesh_scene()
glb.export("output/jeep.glb")
print("export -> output/jeep.glb")
