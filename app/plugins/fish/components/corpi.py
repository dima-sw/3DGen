"""Corpi acquatici: un tronco con pinne e coda.

Il punto di questo plugin non e' che sia un bel pesce. E' che dichiara
`core_mount` — la stessa capability del busto umano — e quindi puo' prendere il
posto di un torso senza che una riga di core lo sappia. Le braccia umane si
attaccheranno alle pinne, perche' anche quelle dichiarano `limb_mount`.

Convenzione: il corpo cresce lungo **+Y** come un busto, cosi' una figura con un
corpo di pesce resta in piedi invece di sdraiarsi.
"""
from app.core.authoring import base_socket
from app.core.capability import Capability, Requirement, mount
from app.core.component import Attachment, Component, Piece
from app.core.params import DISTANCE, RATIO, ParamSpec
from app.core.socket import socket
from app.geometry.kernel import grow

LATI = 7            # dispari: la silhouette non ha due facce parallele piatte


def _corpo(v, ctx) -> Piece:
    """Un fuso: stretto alla base, grosso a un terzo, affusolato in cima."""
    lung, largo, alto = v["length"], v["width"], v["height"]
    mesh = grow([(0.00, largo * 0.42), (0.18, largo * 0.86), (0.42, largo * 1.00),
                 (0.72, largo * 0.82), (0.92, largo * 0.52), (1.00, largo * 0.30)],
                sides=LATI, length=lung, axis=1,
                flat=alto / max(largo, 1e-6), squash=0.25)

    fianco = largo * (alto / max(largo, 1e-6))
    return Piece(mesh=mesh, material="scale", tags=("body", "pesce"), sockets={
        "base": base_socket(largo * 0.42, axis="+Y"),
        "testa": socket("testa", (0, lung * 0.98, 0), (0, 1, 0), up=(0, 0, 1),
                        radius=largo * 0.34, provides="head_mount"),
        "coda": socket("coda", (0, 0, 0), (0, -1, 0), up=(0, 0, 1),
                       radius=largo * 0.4, provides="tail_mount"),
        "pinna_l": socket("pinna_l", (-largo * 0.92, lung * 0.46, 0),
                          (-0.9, -0.3, 0), up=(0, 0, 1), radius=largo * 0.30,
                          provides="limb_mount", side="l", tags=("alto",)),
        "pinna_r": socket("pinna_r", (largo * 0.92, lung * 0.46, 0),
                          (0.9, -0.3, 0), up=(0, 0, 1), radius=largo * 0.30,
                          provides="limb_mount", side="r", tags=("alto",)),
        "ventrale_l": socket("ventrale_l", (-largo * 0.62, lung * 0.14, 0),
                             (-0.6, -0.8, 0), up=(0, 0, 1), radius=largo * 0.24,
                             provides="limb_mount", side="l", tags=("basso",)),
        "ventrale_r": socket("ventrale_r", (largo * 0.62, lung * 0.14, 0),
                             (0.6, -0.8, 0), up=(0, 0, 1), radius=largo * 0.24,
                             provides="limb_mount", side="r", tags=("basso",)),
        "corpo": socket("corpo", (0, 0, 0), (0, 1, 0), up=(0, 0, 1),
                        radius=largo * 0.5, provides="segment"),
        "dorso": socket("dorso", (0, lung * 0.55, fianco * 0.5), (0, 0.2, 1),
                        up=(0, 1, 0), radius=largo * 0.3, provides="gear_mount"),
    })


def _figli_del_corpo(v, ctx):
    return [Attachment(id="coda", component="tail", level=2, insert=0.4,
                       requirement=Requirement(capability="tail_mount"),
                       params={"length": v["tail_length"],
                               "width": v["width"] * 0.9,
                               "height": v["height"] * 0.5})]


FISH_BODY = Component(
    id="fish_body", build=_corpo, children=_figli_del_corpo,
    description="un corpo di pesce: fuso, pinne laterali, coda",
    params={
        "length": ParamSpec(0.62, DISTANCE, min=0.03, max=20.0,
                            semantic_role="length"),
        "width": ParamSpec(0.19, DISTANCE, min=0.01, max=8.0,
                           semantic_role="girth"),
        "height": ParamSpec(0.13, DISTANCE, min=0.01, max=8.0,
                            semantic_role="girth",
                            description="spessore di profilo"),
        "tail_length": ParamSpec(0.22, DISTANCE, min=0.01, max=8.0,
                                 semantic_role="length"),
        "fin_size": ParamSpec(0.11, DISTANCE, min=0.005, max=5.0,
                              semantic_role="girth"),
    },
    provides=(Capability("core_mount"),),
    mounts=(mount("head_mount", socket_id="testa"),
            mount("tail_mount", socket_id="coda"),
            mount("limb_mount", socket_id="pinna_l", side="l", tags=("alto",)),
            mount("limb_mount", socket_id="pinna_r", side="r", tags=("alto",)),
            mount("limb_mount", socket_id="ventrale_l", side="l", tags=("basso",)),
            mount("limb_mount", socket_id="ventrale_r", side="r", tags=("basso",)),
            mount("segment", socket_id="corpo", capacity=0),
            mount("gear_mount", socket_id="dorso")),
    role="torso", material="scale", requires=frozenset({"connected"}),
    tags=frozenset({"pesce", "fish", "torso", "body", "acquatico", "aquatic"}))


def _coda(v, ctx) -> Piece:
    """Una coda che si assottiglia e finisce in una pinna piatta."""
    lung, largo, alto = v["length"], v["width"], v["height"]
    peduncolo = grow([(0.0, largo * 0.5), (0.55, largo * 0.26),
                      (1.0, largo * 0.18)],
                     sides=5, length=lung * 0.62, axis=0,
                     flat=alto / max(largo, 1e-6))
    pinna = grow([(0.0, largo * 0.20), (1.0, largo * 0.95)], sides=4,
                 length=lung * 0.42, axis=0, flat=0.16)
    pinna.apply_translation([lung * 0.58, 0.0, 0.0])
    mesh = peduncolo + pinna
    return Piece(mesh=mesh, material="scale", tags=("tail", "pesce"), sockets={
        "base": base_socket(largo * 0.5, axis="+X"),
        "punta": socket("punta", (lung, 0, 0), (1, 0, 0), up=(0, 1, 0),
                        radius=largo * 0.3, provides="anchor"),
    })


TAIL = Component(
    id="tail", build=_coda,
    description="una coda: peduncolo affusolato e pinna piatta",
    params={"length": ParamSpec(0.22, DISTANCE, min=0.01, max=8.0,
                                semantic_role="length"),
            "width": ParamSpec(0.17, DISTANCE, min=0.005, max=5.0,
                               semantic_role="girth"),
            "height": ParamSpec(0.07, DISTANCE, min=0.003, max=5.0,
                                semantic_role="girth")},
    provides=(Capability("tail_mount"), Capability("limb_mount")),
    mounts=(mount("anchor", socket_id="punta"),),
    role="tail", material="scale", tags=frozenset({"pesce", "fish", "coda", "tail"}))


def _pinna(v, ctx) -> Piece:
    """Una lamina piatta: nel low poly bastano quattro facce a leggerla."""
    lung, largo = v["length"], v["width"]
    mesh = grow([(0.0, largo * 0.55), (0.6, largo * 0.9), (1.0, largo * 0.35)],
                sides=4, length=lung, axis=0, flat=0.14)
    return Piece(mesh=mesh, material="scale", tags=("fin", "pesce"), sockets={
        "base": base_socket(largo * 0.5, axis="+X"),
        "punta": socket("punta", (lung, 0, 0), (1, 0, 0), up=(0, 1, 0),
                        radius=largo * 0.2, provides="anchor"),
    })


FIN = Component(
    id="fin", build=_pinna,
    description="una pinna: una lamina, non un tubo",
    params={"length": ParamSpec(0.18, DISTANCE, min=0.01, max=5.0,
                                semantic_role="length"),
            "width": ParamSpec(0.11, DISTANCE, min=0.005, max=3.0,
                               semantic_role="girth")},
    # una pinna e' un arto, ma anche qualcosa che si puo' montare addosso:
    # e' cio' che permette di usarla come ala senza inventare un componente
    provides=(Capability("limb_mount"), Capability("gear_mount")),
    mounts=(mount("anchor", socket_id="punta"),),
    role="fin", material="scale", tags=frozenset({"pesce", "fish", "pinna", "fin", "arto", "limb", "ala", "wing"}))
