"""Edifici: casa, tetto, porta, finestra.

Un vocabolario che non ha niente in comune con una figura — nessun arto, nessuna
testa, nessun ruolo anatomico — e che passa esattamente dallo stesso resolver e
dallo stesso builder. E' il secondo caso del vertical slice, e serve a provare
che l'architettura non e' antropocentrica.

Convenzione: la casa cresce lungo **+Y** (verso l'alto) e appoggia con
`fondamenta`, che guarda in giu'.
"""
import numpy as np
import trimesh

from app.core.authoring import base_socket
from app.core.capability import Capability, Requirement, mount
from app.core.component import Attachment, Component, Piece
from app.core.params import DISTANCE, RATIO, ParamSpec
from app.core.socket import socket
from app.geometry.kernel import block, grow


def _casa(v, ctx) -> Piece:
    largo, alto, prof = v["width"], v["height"], v["depth"]
    mesh = block((largo, alto, prof), sides=4, axis=1)
    mesh.apply_translation([0.0, alto * 0.5, 0.0])
    return Piece(mesh=mesh, material="masonry", tags=("house", "building"), sockets={
        "base": base_socket(min(largo, prof) * 0.5, axis="+Y"),
        "fondamenta": socket("fondamenta", (0, 0, 0), (0, -1, 0), up=(0, 0, 1),
                             radius=min(largo, prof) * 0.5, provides="surface",
                             side="bottom"),
        "facciata": socket("facciata", (0, alto * 0.28, -prof * 0.5), (0, 0, -1),
                           up=(0, 1, 0), radius=min(largo, alto) * 0.18,
                           provides="opening", tags=("porta",)),
        "finestra_l": socket("finestra_l", (-largo * 0.28, alto * 0.62, -prof * 0.5),
                             (0, 0, -1), up=(0, 1, 0),
                             radius=min(largo, alto) * 0.12, provides="opening",
                             side="l", tags=("finestra",)),
        "finestra_r": socket("finestra_r", (largo * 0.28, alto * 0.62, -prof * 0.5),
                             (0, 0, -1), up=(0, 1, 0),
                             radius=min(largo, alto) * 0.12, provides="opening",
                             side="r", tags=("finestra",)),
        "colmo": socket("colmo", (0, alto, 0), (0, 1, 0), up=(0, 0, 1),
                        radius=min(largo, prof) * 0.5, provides="roof_mount"),
    })


def _figli_della_casa(v, ctx):
    return [
        Attachment(id="tetto", component="roof", level=1, insert=0.05,
                   requirement=Requirement(capability="roof_mount"),
                   params={"width": v["width"], "depth": v["depth"],
                           "pitch": v["roof_pitch"]}),
        Attachment(id="porta", component="door", level=2, insert=0.2,
                   requirement=Requirement(capability="opening", tags=("porta",))),
        Attachment(id="finestra_l", component="window", level=3, insert=0.2,
                   requirement=Requirement(capability="opening", side="l",
                                           tags=("finestra",))),
        Attachment(id="finestra_r", component="window", level=3, insert=0.2,
                   requirement=Requirement(capability="opening", side="r",
                                           tags=("finestra",))),
    ]


HOUSE = Component(
    id="house", build=_casa, children=_figli_della_casa,
    description="una casa: quattro muri, un tetto, una porta e due finestre",
    params={
        "width": ParamSpec(6.0, DISTANCE, min=0.5, max=200.0, semantic_role="girth"),
        "height": ParamSpec(4.0, DISTANCE, min=0.5, max=200.0,
                            semantic_role="length"),
        "depth": ParamSpec(5.0, DISTANCE, min=0.5, max=200.0, semantic_role="girth"),
        "roof_pitch": ParamSpec(0.45, RATIO, min=0.05, max=2.0,
                                description="pendenza del tetto, in frazione della larghezza"),
    },
    provides=(Capability("building"),),
    mounts=(mount("surface", socket_id="fondamenta", side="bottom"),
            mount("opening", socket_id="facciata", tags=("porta",)),
            mount("opening", socket_id="finestra_l", side="l", tags=("finestra",)),
            mount("opening", socket_id="finestra_r", side="r", tags=("finestra",)),
            mount("roof_mount", socket_id="colmo")),
    role="edificio", material="masonry", requires=frozenset({"connected"}),
    tags=frozenset({"edificio", "casa"}))


def _tetto(v, ctx) -> Piece:
    """Un prisma a due falde: due facce inclinate, due timpani, una base.

    Scritto a mano invece che con `grow`, perche' un tetto finisce su un
    **colmo** e non su una punta. Con una punta le falde diventano ventagli di
    triangoli, ognuno con la sua normale, e in ombreggiatura piatta si vede una
    piramide sfaccettata invece di due piani — che e' esattamente cio' che la
    metrica di stile ha segnalato la prima volta che l'ho costruito cosi'.
    """
    largo, prof, pendenza = v["width"] * 1.06, v["depth"] * 1.06, v["pitch"]
    alto = v["width"] * pendenza
    mx, mz = largo * 0.5, prof * 0.5
    vertici = np.array([
        [-mx, 0.0, -mz], [mx, 0.0, -mz], [mx, 0.0, mz], [-mx, 0.0, mz],
        [0.0, alto, -mz], [0.0, alto, mz],
    ], dtype=float)
    facce = np.array([
        [0, 2, 1], [0, 3, 2],            # la base
        [1, 2, 5], [1, 5, 4],            # la falda verso +X
        [3, 0, 4], [3, 4, 5],            # la falda verso -X
        [0, 4, 1], [3, 2, 5],            # i due timpani
    ], dtype=int)
    mesh = trimesh.Trimesh(vertices=vertici, faces=facce, process=False)
    return Piece(mesh=mesh, material="tile", tags=("roof", "building"), sockets={
        "base": base_socket(largo * 0.5, axis="+Y"),
        "colmo": socket("colmo", (0, alto, 0), (0, 1, 0), up=(0, 0, 1),
                        radius=largo * 0.1, provides="gear_mount"),
    })


ROOF = Component(
    id="roof", build=_tetto,
    description="un tetto a due falde",
    params={"width": ParamSpec(6.0, DISTANCE, min=0.5, max=200.0,
                               semantic_role="girth"),
            "depth": ParamSpec(5.0, DISTANCE, min=0.5, max=200.0,
                               semantic_role="girth"),
            "pitch": ParamSpec(0.45, RATIO, min=0.05, max=2.0)},
    provides=(Capability("roof_mount"),),
    mounts=(mount("gear_mount", socket_id="colmo"),),
    role="tetto", material="tile", tags=frozenset({"edificio", "tetto"}))


def _porta(v, ctx) -> Piece:
    alto, largo = v["height"], v["width"]
    mesh = block((largo, alto, v["thickness"]), sides=4, axis=1)
    mesh.apply_translation([0.0, alto * 0.5, 0.0])
    return Piece(mesh=mesh, material="wood", tags=("door", "building"), sockets={
        "base": base_socket(largo * 0.5, axis="+Y"),
        "maniglia": socket("maniglia", (largo * 0.32, alto * 0.5, v["thickness"]),
                           (0, 0, 1), up=(0, 1, 0), radius=largo * 0.08,
                           provides="anchor"),
    })


DOOR = Component(
    id="door", build=_porta,
    description="una porta",
    params={"height": ParamSpec(2.0, DISTANCE, min=0.3, max=20.0,
                                semantic_role="length",
                                derived="parent.height * 0.5"),
            "width": ParamSpec(0.9, DISTANCE, min=0.2, max=10.0,
                               semantic_role="girth"),
            "thickness": ParamSpec(0.10, DISTANCE, min=0.01, max=1.0,
                                   semantic_role="girth")},
    provides=(Capability("opening"),),
    mounts=(mount("anchor", socket_id="maniglia"),),
    role="apertura", material="wood", tags=frozenset({"edificio", "porta"}))


def _finestra(v, ctx) -> Piece:
    """Telaio e vetro: due volumi, cosi' il materiale li distingue."""
    largo, alto, spessore = v["width"], v["height"], v["thickness"]
    telaio = block((largo, alto, spessore), sides=4, axis=1)
    telaio.apply_translation([0.0, alto * 0.5, 0.0])
    vetro = block((largo * 0.74, alto * 0.74, spessore * 0.4), sides=4, axis=1)
    vetro.apply_translation([0.0, alto * 0.5, spessore * 0.35])
    return Piece(mesh=telaio + vetro, material="wood",
                 tags=("window", "building"), sockets={
                     "base": base_socket(largo * 0.5, axis="+Y")})


WINDOW = Component(
    id="window", build=_finestra,
    description="una finestra: telaio e vetro",
    params={"width": ParamSpec(0.8, DISTANCE, min=0.1, max=10.0,
                               semantic_role="girth"),
            "height": ParamSpec(0.9, DISTANCE, min=0.1, max=10.0,
                                semantic_role="length"),
            "thickness": ParamSpec(0.08, DISTANCE, min=0.01, max=1.0,
                                   semantic_role="girth")},
    provides=(Capability("opening"),),
    role="apertura", material="wood", tags=frozenset({"edificio", "finestra"}))
