"""Cose che si portano addosso: piercing, mascherina, casco, visiera.

**Non esiste una classe `Decoration`.** Sono `Component` come tutti gli altri:
cio' che li rende accessori e' l'attacco con cui si montano — facoltativo e su
richiesta — non il loro tipo. E' la ragione per cui un casco puo' avere una
visiera che a sua volta puo' avere qualcos'altro, senza una riga di codice
dedicata all'annidamento delle decorazioni.
"""
from app.core.authoring import base_socket
from app.core.capability import Capability, Requirement, mount
from app.core.component import Attachment, Component, Piece
from app.core.params import DISTANCE, RATIO, ParamSpec
from app.core.socket import socket
from app.geometry.kernel import block, grow

LATI = 6


def _piercing(v, ctx) -> Piece:
    """Un anellino: un tubo corto e sottile che attraversa cio' su cui sta."""
    raggio, spessore = v["radius"], v["thickness"]
    mesh = grow([(0.0, spessore), (1.0, spessore)], sides=LATI,
                length=raggio * 2.4, axis=0)
    mesh.apply_translation([-raggio * 1.2, 0.0, 0.0])
    # il raggio del socket e' quello dell'**anello**, non del filo: e' la
    # misura con cui l'anello va confrontato quando si adatta a un innesto
    return Piece(mesh=mesh, material="metal", tags=("piercing", "gioiello"),
                 sockets={"base": base_socket(raggio, axis="+X",
                                              position=(-raggio * 1.2, 0.0, 0.0))})


PIERCING = Component(
    id="piercing", build=_piercing,
    description="un anellino da mettere dove c'e' un aggancio",
    params={"radius": ParamSpec(0.010, DISTANCE, min=0.001, max=0.2,
                                semantic_role="girth"),
            "thickness": ParamSpec(0.003, DISTANCE, min=0.0005, max=0.05,
                                   semantic_role="girth")},
    provides=(Capability("anchor"),),
    role="gioiello", material="metal", tags=frozenset({"gioiello", "accessorio"}))


def _mascherina(v, ctx) -> Piece:
    """Una scocca piatta che copre il viso, con una fessura per gli occhi."""
    largo, alto, spessore = v["width"], v["height"], v["thickness"]
    scocca = block((largo * 2.0, alto * 2.0, spessore * 2.0), sides=4, axis=2)
    fessura = block((largo * 1.6, alto * 0.34, spessore * 0.9), sides=4, axis=2)
    fessura.apply_translation([0.0, alto * 0.30, spessore * 1.5])
    mesh = scocca + fessura
    return Piece(mesh=mesh, material="metal", tags=("mask", "accessorio"), sockets={
        "base": base_socket(largo, axis="+Z"),
        "fronte": socket("fronte", (0, alto * 0.9, spessore), (0, 1, 0),
                         up=(0, 0, 1), radius=largo * 0.5, provides="gear_mount"),
    })


MASK = Component(
    id="mask", build=_mascherina,
    description="una mascherina che copre il viso",
    params={"width": ParamSpec(0.075, DISTANCE, min=0.005, max=1.0,
                               semantic_role="girth"),
            "height": ParamSpec(0.085, DISTANCE, min=0.005, max=1.0,
                                semantic_role="length"),
            "thickness": ParamSpec(0.010, DISTANCE, min=0.001, max=0.2,
                                   semantic_role="girth")},
    provides=(Capability("face_mount"), Capability("anchor")),
    mounts=(mount("gear_mount", socket_id="fronte"),),
    role="maschera", material="metal",
    tags=frozenset({"accessorio", "maschera", "metallo"}))


def _casco(v, ctx) -> Piece:
    """Una calotta con una cresta: due volumi, e si legge da lontano."""
    raggio, alto = v["radius"], v["height"]
    calotta = grow([(0.0, raggio * 1.02), (0.45, raggio * 1.06),
                    (0.82, raggio * 0.88), (1.0, raggio * 0.42)],
                   sides=LATI, length=alto, axis=1, squash=0.3)
    mesh = calotta
    if v["crest"] > 0.01:
        cresta = block((raggio * 0.26, alto * v["crest"], raggio * 1.9),
                       sides=4, axis=1)
        cresta.apply_translation([0.0, alto * 0.72, 0.0])
        mesh = mesh + cresta
    return Piece(mesh=mesh, material="metal", tags=("helmet", "accessorio"),
                 sockets={
                     "base": base_socket(raggio, axis="+Y"),
                     "cima": socket("cima", (0, alto * (1.0 + v["crest"] * 0.5), 0),
                                    (0, 1, 0), up=(0, 0, 1), radius=raggio * 0.3,
                                    provides="gear_mount"),
                     "fessura": socket("fessura", (0, alto * 0.35, raggio * 0.95),
                                       (0, -0.2, 1), up=(0, 1, 0),
                                       radius=raggio * 0.55,
                                       provides="visor_mount"),
                 })


def _figli_del_casco(v, ctx):
    """La visiera: facoltativa, e chiesta quando serve."""
    return [Attachment(id="visiera", component="visor", level=3,
                       optional=True, on_request=True, insert=0.2,
                       scale_mode="socket",
                       requirement=Requirement(capability="visor_mount"),
                       params={"width": v["radius"] * 0.9,
                               "height": v["height"] * 0.28})]


HELMET = Component(
    id="helmet", build=_casco, children=_figli_del_casco,
    description="un casco: calotta, cresta, e una fessura dove sta la visiera",
    params={"radius": ParamSpec(0.125, DISTANCE, min=0.01, max=1.0,
                                semantic_role="girth"),
            "height": ParamSpec(0.150, DISTANCE, min=0.01, max=1.0,
                                semantic_role="length"),
            "crest": ParamSpec(0.35, RATIO, min=0.0, max=1.5,
                               description="altezza della cresta")},
    provides=(Capability("gear_mount"), Capability("hair_mount"),
              Capability("head_mount")),
    mounts=(mount("gear_mount", socket_id="cima"),
            mount("visor_mount", socket_id="fessura")),
    role="copricapo", material="metal",
    tags=frozenset({"accessorio", "casco", "metallo"}))


def _visiera(v, ctx) -> Piece:
    """Una lamina curva davanti alla fessura."""
    largo, alto = v["width"], v["height"]
    mesh = grow([(0.0, largo * 0.9), (0.5, largo * 1.0), (1.0, largo * 0.75)],
                sides=5, length=alto, axis=1, flat=0.22)
    return Piece(mesh=mesh, material="glass", tags=("visor", "accessorio"),
                 sockets={"base": base_socket(largo * 0.9, axis="+Y")})


VISOR = Component(
    id="visor", build=_visiera,
    description="una visiera: la lamina davanti alla fessura di un casco",
    params={"width": ParamSpec(0.11, DISTANCE, min=0.005, max=1.0,
                               semantic_role="girth"),
            "height": ParamSpec(0.042, DISTANCE, min=0.003, max=1.0,
                                semantic_role="length")},
    provides=(Capability("visor_mount"), Capability("face_mount")),
    role="visiera", material="glass",
    tags=frozenset({"accessorio", "visiera"}))
