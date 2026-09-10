"""Parti robotiche, dichiarate per lo stile **realistico**.

Esistono per dimostrare una cosa sola, e importante: uno stile incompatibile
viene **rifiutato**, non convertito. Un piano che chiede `low_poly` e nomina
questa testa riceve `STYLE_INCOMPATIBLE` con l'elenco di chi quello stile lo
parla — non una versione sfaccettata di una testa pensata per altro.
"""
from app.core.authoring import base_socket
from app.core.capability import Capability, mount
from app.core.component import Component, Piece
from app.core.params import DISTANCE, ParamSpec
from app.core.socket import socket
from app.geometry.kernel import block


def _testa_robot(v, ctx) -> Piece:
    larghezza, altezza = v["width"], v["height"]
    mesh = block((larghezza, altezza, larghezza * 0.9), sides=4, axis=1)
    mesh.apply_translation([0.0, altezza * 0.5, 0.0])
    return Piece(mesh=mesh, material="metal", tags=("head", "robot"), sockets={
        "base": base_socket(larghezza * 0.5, axis="+Y"),
        "viso": socket("viso", (0, altezza * 0.55, larghezza * 0.45), (0, 0, 1),
                       up=(0, 1, 0), radius=larghezza * 0.4, provides="face_mount"),
        "cima": socket("cima", (0, altezza, 0), (0, 1, 0), up=(0, 0, 1),
                       radius=larghezza * 0.3, provides="gear_mount"),
    })


HEAD = Component(
    id="head", build=_testa_robot,
    description="una testa robotica, modellata per lo stile realistico",
    params={"width": ParamSpec(0.20, DISTANCE, min=0.02, max=2.0,
                               semantic_role="girth"),
            "height": ParamSpec(0.24, DISTANCE, min=0.02, max=2.0,
                                semantic_role="length")},
    provides=(Capability("head_mount"),),
    mounts=(mount("face_mount", socket_id="viso"),
            mount("gear_mount", socket_id="cima")),
    styles=frozenset({"realistic"}),
    role="head", material="metal",
    tags=frozenset({"robot", "testa", "head", "metallo", "metal"}))
