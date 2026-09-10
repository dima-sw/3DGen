"""Corpi celesti.

Un pianeta e' una superficie molto grande, e il sistema non ha bisogno di sapere
altro: dichiara `surface`, e una casa che cerca dove appoggiare lo trova. Che sia
grande ottanta metri e la casa quattro non cambia niente al ragionamento — e'
esattamente il punto del secondo caso del vertical slice.

Un pianeta e' **legittimamente sfaccettato**: una normale per faccia non e' il
sintomo di una forma campionata, e' cio' che una sfera low poly deve essere. Lo
dichiara con `requires={"faceted"}`, e il giudizio di stile lo salta.
"""
import numpy as np
import trimesh

from app.core.authoring import base_socket
from app.core.capability import Capability, mount
from app.core.component import Component, Piece
from app.core.params import DISTANCE, RATIO, ParamSpec
from app.core.socket import socket


def _pianeta(v, ctx) -> Piece:
    """Una sfera geodetica schiacciata ai poli, come un pianeta vero."""
    raggio = v["radius"]
    suddivisioni = 1 if raggio < 4.0 else 2
    mesh = trimesh.creation.icosphere(subdivisions=suddivisioni, radius=raggio)

    schiacciamento = float(v["flattening"])
    if schiacciamento > 1e-6:
        vertici = np.asarray(mesh.vertices, dtype=float).copy()
        vertici[:, 1] *= (1.0 - schiacciamento)
        mesh.vertices = vertici

    polo = raggio * (1.0 - schiacciamento)
    return Piece(mesh=mesh, material="rock", tags=("planet", "astronomia"), sockets={
        "base": base_socket(raggio * 0.4, axis="+Y", position=(0.0, -polo, 0.0)),
        "superficie": socket("superficie", (0.0, polo, 0.0), (0.0, 1.0, 0.0),
                             up=(0.0, 0.0, 1.0), radius=raggio * 0.25,
                             provides="surface"),
        "equatore": socket("equatore", (raggio, 0.0, 0.0), (1.0, 0.0, 0.0),
                           up=(0.0, 1.0, 0.0), radius=raggio * 0.25,
                           provides="surface"),
    })


PLANET = Component(
    id="planet", build=_pianeta,
    description="un pianeta: una superficie molto grande su cui posare qualcosa",
    params={"radius": ParamSpec(80.0, DISTANCE, min=0.5, max=100000.0,
                                semantic_role="girth"),
            "flattening": ParamSpec(0.06, RATIO, min=0.0, max=0.6,
                                    description="schiacciamento ai poli")},
    provides=(Capability("surface"),),
    mounts=(mount("surface", socket_id="superficie", capacity=0),
            mount("surface", socket_id="equatore", capacity=0)),
    role="corpo_celeste", material="rock",
    requires=frozenset({"watertight", "faceted"}),
    tags=frozenset({"astronomia", "astronomy", "pianeta", "planet", "sfera", "sphere"}))
