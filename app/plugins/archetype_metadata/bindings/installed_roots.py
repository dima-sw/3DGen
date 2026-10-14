"""Explicit third-party bindings; the geometry plugins remain untouched."""
from app.core.archetypes import ImplementationBinding


BINDINGS = (
    ImplementationBinding(
        id="fox_quadruped",
        implementation="fox_stylized:fox",
        supported_archetypes=("quadruped",)),
    ImplementationBinding(
        id="stylized_car",
        implementation="vehicle_stylized:car",
        supported_archetypes=("car_like",)),
    ImplementationBinding(
        id="stylized_tree",
        implementation="tree_stylized:tree",
        supported_archetypes=("tree",)),
)
