"""Armi bianche: una spada fatta di lama, guardia e impugnatura.

La spada dichiara `limb_mount`. Non perche' sia un arto — non lo e' — ma perche'
e' cio' che serve per poterla mettere al posto di una gamba, che e' esattamente
il caso che vogliamo dimostrare. Il builder non sa che e' una spada: sa che c'e'
un pezzo che si attacca a un innesto per arti, e lo posa li'.

Convenzione: cresce lungo **+X** dall'impugnatura verso la punta, con `base`
all'origine rivolto verso -X.
"""
from app.core.authoring import base_socket
from app.core.capability import Capability, mount
from app.core.component import Component, Piece
from app.core.params import DISTANCE, ParamSpec
from app.core.socket import socket
from app.geometry.kernel import block, grow


def _spada(v, ctx) -> Piece:
    """Tre volumi distinti: nel low poly una spada si legge dagli spigoli."""
    lama_l, lama_w, lama_t = v["blade_length"], v["blade_width"], v["blade_thickness"]
    manico_l, guardia_w = v["handle_length"], v["guard_width"]

    # l'impugnatura parte dall'origine
    manico = grow([(0.0, lama_w * 0.42), (0.7, lama_w * 0.38), (1.0, lama_w * 0.52)],
                  sides=5, length=manico_l, axis=0, flat=0.8)

    # la guardia: una barra trasversale, il pezzo che rende leggibile l'arma
    guardia = block((lama_t * 2.4, guardia_w * 2.0, lama_w * 1.4), sides=4, axis=1)
    guardia.apply_translation([manico_l, 0.0, 0.0])

    # la lama: si assottiglia e finisce a punta
    lama = grow([(0.0, lama_w), (0.12, lama_w), (0.82, lama_w * 0.82), (1.0, 0.0)],
                sides=4, length=lama_l, axis=0, flat=lama_t / max(lama_w, 1e-6),
                point_end=True)
    lama.apply_translation([manico_l + lama_t * 0.6, 0.0, 0.0])

    mesh = manico + guardia + lama
    lunghezza = manico_l + lama_t * 0.6 + lama_l
    return Piece(mesh=mesh, material="metal", tags=("sword", "weapon"), sockets={
        "base": base_socket(lama_w * 0.42, axis="+X"),
        "impugnatura": socket("impugnatura", (manico_l * 0.5, 0, 0), (-1, 0, 0),
                              up=(0, 1, 0), radius=lama_w * 0.45,
                              provides="grip_mount"),
        "punta": socket("punta", (lunghezza, 0, 0), (1, 0, 0), up=(0, 1, 0),
                        radius=lama_w * 0.2, provides="anchor"),
    })


SWORD = Component(
    id="sword", build=_spada,
    description="una spada: impugnatura, guardia, lama",
    params={
        "blade_length": ParamSpec(0.62, DISTANCE, min=0.05, max=5.0,
                                  semantic_role="length"),
        "blade_width": ParamSpec(0.035, DISTANCE, min=0.003, max=0.5,
                                 semantic_role="girth"),
        "blade_thickness": ParamSpec(0.010, DISTANCE, min=0.001, max=0.2,
                                     semantic_role="girth"),
        "handle_length": ParamSpec(0.14, DISTANCE, min=0.01, max=1.0,
                                   semantic_role="length"),
        "guard_width": ParamSpec(0.055, DISTANCE, min=0.003, max=0.8,
                                 semantic_role="girth"),
    },
    provides=(Capability("limb_mount"), Capability("arma")),
    mounts=(mount("grip_mount", socket_id="impugnatura"),
            mount("anchor", socket_id="punta")),
    role="lama", material="metal",
    tags=frozenset({"arma", "weapon", "metallo", "metal", "spada", "sword", "lama", "blade"}))
