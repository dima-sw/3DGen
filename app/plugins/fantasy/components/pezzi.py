"""Un'ala e un cristallo: due pezzi che non sono di nessuno.

Sono qui per il quarto scenario — «un robot con testa di drago, corpo di pesce,
ali e cristalli luminosi» — e sono scritti apposta senza appartenere a un
animale. Un'ala fornisce `limb_mount`, che e' cio' che offrono un braccio umano
e una pinna di pesce: chi ha un innesto per un arto puo' avere un'ala, e nessuno
dei due plugin ha dovuto sapere dell'altro.

Il cristallo dichiara `faceted`: una normale per faccia non e' il sintomo di una
forma campionata, e' cio' che un cristallo **e'**. Senza quella dichiarazione il
giudizio di stile lo scambierebbe per una bolla decimata.
"""
from app.core.authoring import base_socket
from app.core.capability import Capability, mount
from app.core.component import Component, Piece
from app.core.params import DISTANCE, RATIO, ParamSpec
from app.core.socket import socket
from app.geometry.kernel import grow


def _ala(v, ctx) -> Piece:
    """Una lamina che si allarga e poi si assottiglia. Cresce verso +X."""
    lunga, larga = v["length"], v["width"]
    mesh = grow([(0.0, larga * 0.30), (0.30, larga), (0.68, larga * 0.78),
                 (1.0, larga * 0.16)],
                sides=4, length=lunga, axis=0, flat=v["thickness"], squash=0.8)
    return Piece(mesh=mesh, material="membrane", tags=("wing", "fantasia"),
                 sockets={
                     "base": base_socket(larga * 0.30, axis="+X"),
                     "punta": socket("punta", (lunga, 0.0, 0.0), (1.0, 0.0, 0.0),
                                     up=(0.0, 1.0, 0.0), radius=larga * 0.16,
                                     provides="anchor"),
                     "dorso": socket("dorso", (lunga * 0.42, larga * 0.5, 0.0),
                                     (0.0, 1.0, 0.0), up=(1.0, 0.0, 0.0),
                                     radius=larga * 0.3, provides="gear_mount"),
                 })


WING = Component(
    id="wing", build=_ala,
    description="un'ala: una lamina larga alla radice e sottile in punta",
    params={"length": ParamSpec(0.55, DISTANCE, min=0.03, max=8.0,
                                semantic_role="length"),
            "width": ParamSpec(0.22, DISTANCE, min=0.01, max=4.0,
                               semantic_role="girth"),
            "thickness": ParamSpec(0.22, RATIO, min=0.05, max=1.0,
                                   description="quanto e' schiacciata di profilo")},
    provides=(Capability("limb_mount"), Capability("gear_mount")),
    mounts=(mount("anchor", socket_id="punta"),
            mount("gear_mount", socket_id="dorso", capacity=0)),
    role="ala", material="membrane",
    tags=frozenset({"fantasia", "ala", "arto", "volo"}))


def _cristallo(v, ctx) -> Piece:
    """Un prisma appuntito. Sei facce e una punta, e nient'altro."""
    alto, raggio = v["height"], v["radius"]
    mesh = grow([(0.0, raggio * 0.45), (0.22, raggio), (1.0, raggio * 0.02)],
                sides=int(v["sides"]), length=alto, axis=1, point_end=True)
    return Piece(mesh=mesh, material="crystal", tags=("crystal", "fantasia"),
                 sockets={
                     "base": base_socket(raggio * 0.45, axis="+Y"),
                     "punta": socket("punta", (0.0, alto, 0.0), (0.0, 1.0, 0.0),
                                     up=(0.0, 0.0, 1.0), radius=raggio * 0.1,
                                     provides="anchor"),
                 })


CRYSTAL = Component(
    id="crystal", build=_cristallo,
    description="un cristallo luminoso: un prisma appuntito, sfaccettato apposta",
    params={"height": ParamSpec(0.18, DISTANCE, min=0.01, max=6.0,
                                semantic_role="length"),
            "radius": ParamSpec(0.05, DISTANCE, min=0.003, max=2.0,
                                semantic_role="girth"),
            "sides": ParamSpec(6, "int", min=3, max=10,
                               description="quante facce ha il prisma")},
    provides=(Capability("anchor"), Capability("gear_mount"),
              Capability("face_mount")),
    mounts=(mount("anchor", socket_id="punta"),),
    role="cristallo", material="crystal",
    requires=frozenset({"faceted", "watertight"}),
    tags=frozenset({"fantasia", "cristallo", "luminoso", "gemma"}))
