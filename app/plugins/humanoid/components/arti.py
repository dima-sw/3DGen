"""Gli arti: braccio, gamba, e i pezzi di cui sono fatti.

Gli arti crescono lungo **+X** dalla propria base — la convenzione predefinita —
e a livello 3 si aprono nei loro segmenti, che prendono il posto del pezzo
unico. I segmenti si posizionano con un `offset` lungo l'asse del padre invece
di attaccarsi in catena: e' il modo in cui il plugin collaudato lo faceva, e ha
il vantaggio che un'articolazione non accumula errore.

Il piede punta **avanti**, non di lato. Nel sistema locale della gamba, dopo
l'attacco all'anca, il "davanti" del mondo e' +Y e il fianco e' +Z: costruirlo
lungo Z lo faceva sporgere come una pinna, ed era il difetto piu' evidente del
modello a livello alto.
"""
from app.core.authoring import base_socket
from app.core.capability import Capability, Requirement, mount
from app.core.component import Attachment, Component, Piece
from app.core.params import DISTANCE, RATIO, ParamSpec
from app.core.socket import socket
from app.geometry.kernel import block, grow

LATI = 6
OVERLAP = 0.05          # quanto ogni segmento entra nel precedente


def _arto(profilo, tag: str):
    """Un arto intero: cresce lungo +X, con base e punta."""
    def costruisci(v, ctx) -> Piece:
        girth, lung = v["girth"], v["length"]
        mesh = grow([(t, girth * r) for t, r in profilo], sides=LATI,
                    length=lung, axis=0, flat=v["flat"], squash=v["squash"])
        # dove vanno i pezzi di cui e' fatto. Dichiararlo qui e' l'unico modo
        # perche' i segmenti si dispongano in fila invece di sovrapporsi: un
        # figlio si posa dove il padre lo manda, non dove crede di stare.
        return Piece(mesh=mesh, material="skin", tags=(tag, "limb"), sockets={
            "base": base_socket(girth, axis="+X"),
            "tip": socket("tip", (lung, 0, 0), (1, 0, 0), up=(0, 1, 0),
                          radius=girth * profilo[-1][1], provides="limb_mount"),
            "prossimale": socket("prossimale", (0, 0, 0), (1, 0, 0), up=(0, 1, 0),
                                 radius=girth, provides="segment",
                                 tags=("prossimale",)),
            "mediale": socket("mediale", (lung * (0.50 - OVERLAP), 0, 0),
                              (1, 0, 0), up=(0, 1, 0), radius=girth * 0.9,
                              provides="segment", tags=("mediale",)),
            "distale": socket("distale", (lung * (0.89 - OVERLAP), 0, 0),
                              (1, 0, 0), up=(0, 1, 0), radius=girth * 0.8,
                              provides="segment", tags=("distale",)),
        })
    return costruisci


def _segmento(profilo, tag: str, squash: float = 0.2):
    """Un pezzo di arto. Si costruisce dalla propria origine, come tutti."""
    def costruisci(v, ctx) -> Piece:
        girth, lung = v["girth"], v["length"]
        mesh = grow([(t, girth * r) for t, r in profilo], sides=LATI,
                    length=lung, axis=0, squash=squash)
        return Piece(mesh=mesh, material="skin", tags=(tag, "limb"), sockets={
            "base": base_socket(girth, axis="+X"),
            "tip": socket("tip", (lung, 0, 0), (1, 0, 0), up=(0, 1, 0),
                          radius=girth * profilo[-1][1], provides="segment"),
        })
    return costruisci


_PARAMETRI_SEGMENTO = {
    "length": ParamSpec(0.19, DISTANCE, min=0.01, max=3.0, semantic_role="length"),
    "girth": ParamSpec(0.034, DISTANCE, min=0.003, max=1.0, semantic_role="girth"),
}


# --------------------------------------------------------------------------- #
# Braccio
# --------------------------------------------------------------------------- #
def _figli_del_braccio(v, ctx):
    lung, girth = v["length"], v["girth"]
    return [
        Attachment(id="omero", component="upper_arm", level=3, replaces_parent=True,
                   insert=0.0,
                   requirement=Requirement(capability="segment",
                                           tags=("prossimale",)),
                   params={"length": lung * 0.50, "girth": girth}),
        Attachment(id="avambraccio", component="forearm", level=3,
                   replaces_parent=True, insert=0.0,
                   requirement=Requirement(capability="segment",
                                           tags=("mediale",)),
                   params={"length": lung * 0.44, "girth": girth * 0.86}),
        Attachment(id="mano", component="hand", level=3, replaces_parent=True,
                   insert=0.0,
                   requirement=Requirement(capability="segment",
                                           tags=("distale",)),
                   params={"length": lung * 0.22, "girth": girth * 0.90}),
    ]


ARM = Component(
    id="arm", build=_arto([(0.0, 0.55), (0.10, 1.30), (0.30, 1.04), (0.60, 0.88),
                           (0.86, 0.84), (1.0, 0.62)], "arm"),
    children=_figli_del_braccio,
    description="un braccio: spalla, gomito, mano",
    params={"length": ParamSpec(0.756, DISTANCE, min=0.05, max=5.0,
                                semantic_role="length",
                                derived="root.height * 0.4782"),
            "girth": ParamSpec(0.061, DISTANCE, min=0.005, max=1.0,
                               semantic_role="girth",
                               derived="root.height * 0.0387"),
            "flat": ParamSpec(1.0, RATIO, min=0.4, max=1.6),
            "squash": ParamSpec(0.2, RATIO, min=0.0, max=1.0)},
    provides=(Capability("limb_mount"),),
    mounts=(mount("segment", socket_id="prossimale", tags=("prossimale",)),
            mount("segment", socket_id="mediale", tags=("mediale",)),
            mount("segment", socket_id="distale", tags=("distale",)),
            mount("limb_mount", socket_id="tip")),
    role="arm", material="skin", tags=frozenset({"umanoide", "humanoid", "arto", "limb", "braccio", "arm"}))

UPPER_ARM = Component(
    id="upper_arm",
    build=_segmento([(0.0, 0.55), (0.10, 1.32), (0.34, 1.04), (1.0, 0.86)], "arm"),
    description="l'omero: dalla spalla al gomito",
    params=dict(_PARAMETRI_SEGMENTO),
    provides=(Capability("segment"),),
    role="arm", material="skin",
    tags=frozenset({"umanoide", "humanoid", "arto", "limb", "braccio", "arm"}))

FOREARM = Component(
    id="forearm",
    build=_segmento([(0.0, 1.0), (0.35, 0.95), (1.0, 0.70)], "arm"),
    description="l'avambraccio: dal gomito al polso",
    params=dict(_PARAMETRI_SEGMENTO),
    provides=(Capability("segment"),),
    role="arm", material="skin",
    tags=frozenset({"umanoide", "humanoid", "arto", "limb", "braccio", "arm"}))


def _mano(v, ctx) -> Piece:
    lung, girth = v["length"], v["girth"]
    palmo = block((lung * 0.9, girth * 1.15, girth * 1.9), sides=4, squash=1.0, axis=0)
    palmo.apply_translation([lung * 0.45, 0, 0])
    pollice = block((lung * 0.45, girth * 0.5, girth * 0.55), sides=4, axis=0)
    pollice.apply_translation([lung * 0.5, girth * 0.75, -girth * 0.45])
    return Piece(mesh=palmo + pollice, material="skin",
                 tags=("hand", "extremity"), sockets={
                     "base": base_socket(girth, axis="+X"),
                     "tip": socket("tip", (lung, 0, 0), (1, 0, 0),
                                   up=(0, 1, 0), radius=girth * 0.6,
                                   provides="segment")})


HAND = Component(
    id="hand", build=_mano,
    description="una mano: palmo e pollice, che nel low poly bastano a leggerla",
    params={"length": ParamSpec(0.153, DISTANCE, min=0.01, max=1.0,
                                semantic_role="length"),
            "girth": ParamSpec(0.054, DISTANCE, min=0.005, max=1.0,
                               semantic_role="girth")},
    provides=(Capability("segment"),),
    mounts=(mount("segment", socket_id="tip"),),
    role="hand", material="skin", tags=frozenset({"umanoide", "humanoid", "mano", "hand", "estremita",
                    "extremity", "braccio", "arm"}))


# --------------------------------------------------------------------------- #
# Gamba
# --------------------------------------------------------------------------- #
def _figli_della_gamba(v, ctx):
    lung, girth = v["length"], v["girth"]
    return [
        Attachment(id="coscia", component="thigh", level=3, replaces_parent=True,
                   insert=0.0,
                   requirement=Requirement(capability="segment",
                                           tags=("prossimale",)),
                   params={"length": lung * 0.52, "girth": girth}),
        Attachment(id="polpaccio", component="calf", level=3, replaces_parent=True,
                   insert=0.0,
                   requirement=Requirement(capability="segment",
                                           tags=("mediale",)),
                   params={"length": lung * 0.48, "girth": girth * 0.82}),
        Attachment(id="piede", component="foot", level=3, replaces_parent=True,
                   insert=0.0,
                   requirement=Requirement(capability="segment",
                                           tags=("distale",)),
                   params={"length": lung * 0.15, "girth": girth * 0.90}),
    ]


LEG = Component(
    id="leg", build=_arto([(0.0, 1.0), (0.22, 1.06), (0.5, 0.82), (0.8, 0.74),
                           (1.0, 0.66)], "leg"),
    children=_figli_della_gamba,
    description="una gamba: anca, ginocchio, piede",
    params={"length": ParamSpec(0.864, DISTANCE, min=0.05, max=5.0,
                                semantic_role="length",
                                derived="root.height * 0.5465"),
            "girth": ParamSpec(0.090, DISTANCE, min=0.005, max=1.0,
                               semantic_role="girth",
                               derived="root.height * 0.0569"),
            "flat": ParamSpec(1.0, RATIO, min=0.4, max=1.6),
            "squash": ParamSpec(0.2, RATIO, min=0.0, max=1.0)},
    provides=(Capability("limb_mount"),),
    mounts=(mount("segment", socket_id="prossimale", tags=("prossimale",)),
            mount("segment", socket_id="mediale", tags=("mediale",)),
            mount("segment", socket_id="distale", tags=("distale",)),
            mount("limb_mount", socket_id="tip")),
    role="leg", material="skin", tags=frozenset({"umanoide", "humanoid", "arto", "limb", "gamba", "leg"}))

THIGH = Component(
    id="thigh",
    build=_segmento([(0.0, 1.05), (0.25, 1.10), (1.0, 0.80)], "leg"),
    description="la coscia",
    params=dict(_PARAMETRI_SEGMENTO),
    provides=(Capability("segment"),),
    role="leg", material="skin",
    tags=frozenset({"umanoide", "humanoid", "arto", "limb", "gamba", "leg"}))

CALF = Component(
    id="calf",
    build=_segmento([(0.0, 1.0), (0.3, 1.02), (1.0, 0.62)], "leg"),
    description="il polpaccio",
    params=dict(_PARAMETRI_SEGMENTO),
    provides=(Capability("segment"),),
    role="leg", material="skin",
    tags=frozenset({"umanoide", "humanoid", "arto", "limb", "gamba", "leg"}))


def _piede(v, ctx) -> Piece:
    lung, girth = v["length"], v["girth"]
    spessore = girth * 1.9
    mesh = block((spessore, lung * 2.6, girth * 1.45), sides=4, squash=1.0, axis=1)
    # dalla caviglia in avanti (+Y nel sistema locale della gamba), appena sotto
    mesh.apply_translation([spessore * 0.28, lung * 0.85, 0.0])
    return Piece(mesh=mesh, material="skin", tags=("foot", "extremity"), sockets={
        "base": base_socket(girth, axis="+X"),
        "punta": socket("punta", (0, lung * 2.1, 0), (0, 1, 0), up=(1, 0, 0),
                        radius=girth * 0.6, provides="segment"),
    })


FOOT = Component(
    id="foot", build=_piede,
    description="un piede, che punta avanti e non di lato",
    params={"length": ParamSpec(0.108, DISTANCE, min=0.01, max=1.0,
                                semantic_role="length"),
            "girth": ParamSpec(0.081, DISTANCE, min=0.005, max=1.0,
                               semantic_role="girth")},
    provides=(Capability("segment"),),
    mounts=(mount("segment", socket_id="punta"),),
    role="foot", material="skin", tags=frozenset({"umanoide", "humanoid", "piede", "foot", "estremita",
                    "extremity", "gamba", "leg"}))
