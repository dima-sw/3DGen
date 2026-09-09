"""Albero, nido, uccello: il minimo per «un albero con un nido e un uccello».

Tre componenti, nati da uno scenario e non da un'idea di completezza. Un albero
non ha radici, un nido non ha rametti e un uccello non ha zampe, perche' niente
di tutto questo serviva a far vedere che un vocabolario nuovo si incastra con
quelli che c'erano gia'.

Quello che invece serviva, e c'e', e' la catena di innesti:

    albero  accetta  branch_mount    sul ramo
    nido    fornisce branch_mount    e accetta perch_mount
    uccello fornisce perch_mount     e accetta limb_mount (le ali di chiunque)

`limb_mount` non e' di questo plugin: e' quello degli arti umanoidi e delle
pinne. Un uccello che accetta un'ala di un altro vocabolario non e' una
concessione, e' il punto.

Convenzione: albero e nido crescono verso **+Y**; l'uccello verso **+Z**, cioe'
in avanti, come un corpo che ha un davanti.
"""
from app.core.authoring import base_socket
from app.core.capability import Capability, Requirement, mount
from app.core.component import Attachment, Component, Piece
from app.core.params import DISTANCE, ParamSpec
from app.core.socket import socket
from app.geometry.kernel import block, grow

LATI = 6


# --------------------------------------------------------------------------- #
# Albero
# --------------------------------------------------------------------------- #
def _albero(v, ctx) -> Piece:
    """Un tronco che si assottiglia. La chioma e' un figlio, non una palla qui."""
    alto, raggio = v["height"], v["trunk_radius"]
    tronco = grow([(0.0, raggio * 1.35), (0.12, raggio), (0.75, raggio * 0.8),
                   (1.0, raggio * 0.55)],
                  sides=LATI, length=alto, axis=1)
    return Piece(mesh=tronco, material="wood", tags=("tree", "natura"), sockets={
        "base": base_socket(raggio * 1.35, axis="+Y"),
        "fondamenta": socket("fondamenta", (0.0, 0.0, 0.0), (0.0, -1.0, 0.0),
                             up=(0.0, 0.0, 1.0), radius=raggio * 1.35,
                             provides="surface", side="bottom"),
        "cima": socket("cima", (0.0, alto, 0.0), (0.0, 1.0, 0.0), up=(0.0, 0.0, 1.0),
                       radius=raggio * 0.55, provides="crown_mount"),
        "ramo_l": socket("ramo_l", (-raggio * 0.9, alto * 0.78, 0.0),
                         (-0.55, 0.83, 0.0), up=(0.0, 1.0, 0.0),
                         radius=raggio * 0.9, provides="branch_mount", side="l"),
        "ramo_r": socket("ramo_r", (raggio * 0.9, alto * 0.78, 0.0),
                         (0.55, 0.83, 0.0), up=(0.0, 1.0, 0.0),
                         radius=raggio * 0.9, provides="branch_mount", side="r"),
    })


def _figli_dell_albero(v, ctx):
    return [Attachment(id="chioma", component="foliage", level=2, insert=0.35,
                       requirement=Requirement(capability="crown_mount"),
                       params={"radius": v["crown_radius"],
                               "height": v["crown_radius"] * 1.4})]


TREE = Component(
    id="tree", build=_albero, children=_figli_dell_albero,
    description="un albero: un tronco, una chioma e due rami dove posare qualcosa",
    params={
        "height": ParamSpec(4.0, DISTANCE, min=0.4, max=60.0,
                            semantic_role="length"),
        "trunk_radius": ParamSpec(0.22, DISTANCE, min=0.02, max=4.0,
                                  semantic_role="girth"),
        "crown_radius": ParamSpec(1.3, DISTANCE, min=0.1, max=20.0,
                                  semantic_role="girth",
                                  derived="height * 0.32"),
    },
    # Un albero **sta** su una superficie: la accetta, non la fornisce. E' la
    # stessa asimmetria della casa sul pianeta, e sbagliarla qui vorrebbe dire
    # poter appoggiare un pianeta sopra un albero.
    provides=(Capability("building"),),
    mounts=(mount("crown_mount", socket_id="cima"),
            mount("surface", socket_id="fondamenta", side="bottom"),
            mount("branch_mount", socket_id="ramo_l", side="l"),
            mount("branch_mount", socket_id="ramo_r", side="r")),
    role="albero", material="wood", tags=frozenset({"natura", "albero", "pianta"}))


def _chioma(v, ctx) -> Piece:
    """Una chioma sfaccettata: pochi lati, e lo dichiara."""
    raggio, alto = v["radius"], v["height"]
    mesh = grow([(0.0, raggio * 0.45), (0.3, raggio), (0.72, raggio * 0.92),
                 (1.0, raggio * 0.3)], sides=LATI, length=alto, axis=1, flat=0.9)
    return Piece(mesh=mesh, material="leaf", tags=("foliage", "natura"), sockets={
        "base": base_socket(raggio * 0.45, axis="+Y"),
        "cima": socket("cima", (0.0, alto, 0.0), (0.0, 1.0, 0.0), up=(0.0, 0.0, 1.0),
                       radius=raggio * 0.3, provides="branch_mount"),
    })


FOLIAGE = Component(
    id="foliage", build=_chioma,
    description="la chioma di un albero",
    params={"radius": ParamSpec(1.3, DISTANCE, min=0.05, max=20.0,
                                semantic_role="girth"),
            "height": ParamSpec(1.8, DISTANCE, min=0.05, max=30.0,
                                semantic_role="length")},
    provides=(Capability("crown_mount"),),
    mounts=(mount("branch_mount", socket_id="cima"),),
    role="chioma", material="leaf", tags=frozenset({"natura", "chioma", "foglie"}))


# --------------------------------------------------------------------------- #
# Nido
# --------------------------------------------------------------------------- #
def _nido(v, ctx) -> Piece:
    """Una ciotola: un anello di paglia con dentro il vuoto.

    Costruita come due volumi — la parete e il fondo — e non come un toro:
    l'interno concavo di una ciotola low poly si vede meglio con una parete
    inclinata che con una superficie curva, e costa meno triangoli.
    """
    raggio, alto = v["radius"], v["height"]
    parete = grow([(0.0, raggio * 0.72), (1.0, raggio)], sides=LATI * 2,
                  length=alto, axis=1)
    interno = grow([(0.0, raggio * 0.5), (1.0, raggio * 0.78)], sides=LATI * 2,
                   length=alto * 0.92, axis=1)
    interno.apply_translation([0.0, alto * 0.22, 0.0])
    interno.invert()
    return Piece(mesh=parete + interno, material="straw",
                 tags=("nest", "natura"), sockets={
                     "base": base_socket(raggio * 0.72, axis="+Y"),
                     "dentro": socket("dentro", (0.0, alto * 0.55, 0.0),
                                      (0.0, 1.0, 0.0), up=(0.0, 0.0, 1.0),
                                      radius=raggio * 0.6,
                                      provides="perch_mount")})


NEST = Component(
    id="nest", build=_nido,
    description="un nido di paglia, con dentro il posto per chi ci sta",
    params={"radius": ParamSpec(0.30, DISTANCE, min=0.03, max=4.0,
                                semantic_role="girth"),
            "height": ParamSpec(0.16, DISTANCE, min=0.02, max=2.0,
                                semantic_role="length")},
    provides=(Capability("branch_mount"), Capability("nest_mount")),
    mounts=(mount("perch_mount", socket_id="dentro", capacity=0),),
    role="nido", material="straw", tags=frozenset({"natura", "nido"}))


# --------------------------------------------------------------------------- #
# Uccello
# --------------------------------------------------------------------------- #
def _uccello(v, ctx) -> Piece:
    """Corpo affusolato piu' becco. Cresce in avanti, verso +Z."""
    lungo, largo = v["length"], v["girth"]
    corpo = grow([(0.0, largo * 0.55), (0.28, largo), (0.7, largo * 0.86),
                  (1.0, largo * 0.42)], sides=LATI, length=lungo, axis=2, flat=0.88)
    becco = block((largo * 0.4, largo * 0.34, v["beak"]), sides=4, taper=0.15,
                  axis=2)
    becco.apply_translation([0.0, largo * 0.25, lungo * 0.96])
    return Piece(mesh=corpo + becco, material="feather",
                 tags=("bird", "natura"), sockets={
                     "base": base_socket(largo * 0.55, axis="+Z"),
                     "ala_l": socket("ala_l", (-largo * 0.9, largo * 0.18,
                                               lungo * 0.42),
                                     (-1.0, 0.15, 0.0), up=(0.0, 1.0, 0.0),
                                     radius=largo * 0.5, provides="limb_mount",
                                     side="l", tags=("alto",)),
                     "ala_r": socket("ala_r", (largo * 0.9, largo * 0.18,
                                               lungo * 0.42),
                                     (1.0, 0.15, 0.0), up=(0.0, 1.0, 0.0),
                                     radius=largo * 0.5, provides="limb_mount",
                                     side="r", tags=("alto",)),
                     "testa": socket("testa", (0.0, largo * 0.55, lungo * 0.82),
                                     (0.0, 1.0, 0.35), up=(0.0, 0.0, 1.0),
                                     radius=largo * 0.35, provides="head_mount"),
                 })


BIRD = Component(
    id="bird", build=_uccello,
    description="un uccello: un corpo, un becco, e due innesti per le ali",
    params={"length": ParamSpec(0.26, DISTANCE, min=0.03, max=4.0,
                                semantic_role="length"),
            "girth": ParamSpec(0.09, DISTANCE, min=0.01, max=2.0,
                               semantic_role="girth"),
            "beak": ParamSpec(0.06, DISTANCE, min=0.005, max=1.0,
                              semantic_role="length")},
    provides=(Capability("perch_mount"), Capability("anchor")),
    mounts=(mount("limb_mount", socket_id="ala_l", side="l", tags=("alto",)),
            mount("limb_mount", socket_id="ala_r", side="r", tags=("alto",)),
            mount("head_mount", socket_id="testa")),
    role="uccello", material="feather",
    tags=frozenset({"natura", "uccello", "animale"}))
