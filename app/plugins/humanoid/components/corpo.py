"""Il busto: corpo, torso, bacino, petto, collo.

La geometria viene dal plugin procedurale gia' collaudato — gli stessi profili,
gli stessi rapporti — portata al contratto nuovo. Non e' stata riscritta: era
giusta, e riscriverla avrebbe voluto dire ritarare tutto da capo.

## Le misure sono frazioni dell'altezza

Ogni parte deriva le proprie misure da `root.height`. Cosi' "alto 1,80" fa 1,80
**per costruzione**, senza un fattore di resa da rimisurare a ogni ritocco delle
proporzioni — che e' un errore che questo progetto ha gia' fatto due volte.

## Convenzione

Le parti del busto crescono lungo **+Y** (in su) e lo dichiarano con il proprio
socket `base`, che guarda verso -Y. E' esplicitamente ammesso dalla convenzione:
quello che conta non e' che tutti crescano nello stesso verso, e' che il socket
dica la verita'.
"""
from app.core.authoring import base_socket
from app.core.capability import Capability, Requirement, mount
from app.core.component import Attachment, Component, Piece
from app.core.params import DISTANCE, RATIO, ParamSpec
from app.core.socket import socket
from app.geometry.kernel import grow

LATI = 6            # lati della sezione: sei bastano, e si vedono

# Quanto ogni segmento entra nel precedente. Attaccati testa-coda si vedono i
# distacchi a ogni articolazione; un dito di sovrapposizione li chiude e non
# costa un triangolo, perche' i pezzi restano separati.
OVERLAP = 0.05


def _profilo(profilo, girth: float, lunghezza: float, flat: float,
             squash: float = 0.35):
    return grow([(t, girth * r) for t, r in profilo], sides=LATI,
                length=lunghezza, axis=1, flat=flat, squash=squash)


# --------------------------------------------------------------------------- #
# Il corpo: un contenitore, non una forma
# --------------------------------------------------------------------------- #
def _corpo(v, ctx) -> Piece:
    """Nessuna geometria propria: esiste per tenere insieme il resto."""
    altezza = v["height"]
    return Piece(mesh=None, tags=("body",), sockets={
        "base": base_socket(altezza * 0.1, axis="+Y"),
        "core": socket("core", (0.0, 0.0, 0.0), (0.0, 1.0, 0.0), up=(0.0, 0.0, 1.0),
                       radius=altezza * 0.12, provides="core_mount"),
    })


def _figli_del_corpo(v, ctx):
    return [Attachment(id="torso", component="torso", level=1, insert=0.0,
                       requirement=Requirement(capability="core_mount"))]


BODY = Component(
    id="body", build=_corpo, children=_figli_del_corpo,
    description="una figura umanoide: il contenitore di tutte le sue parti",
    params={"height": ParamSpec(1.8, DISTANCE, min=0.2, max=20.0,
                                semantic_role="length",
                                description="altezza totale della figura")},
    mounts=(mount("core_mount", socket_id="core"),),
    role="body", material="skin", tags=frozenset({"umanoide", "humanoid", "figura", "figure", "persona", "person", "body"}))


# --------------------------------------------------------------------------- #
# Torso
# --------------------------------------------------------------------------- #
def _torso(v, ctx) -> Piece:
    girth, lung, flat = v["girth"], v["length"], v["flat"]
    mesh = _profilo([(0.00, 0.72), (0.14, 0.94), (0.34, 0.82), (0.55, 0.88),
                     (0.78, 1.00), (0.94, 0.96), (1.00, 0.60)],
                    girth, lung, flat, v["squash"])
    spalla = girth * v["shoulder"]
    return Piece(mesh=mesh, material="skin", tags=("torso", "body"), sockets={
        "base": base_socket(girth * 0.7, axis="+Y"),
        "collo": socket("collo", (0, lung * 0.98, 0), (0, 1, 0), up=(0, 0, 1),
                        radius=girth * 0.42, provides="head_mount"),
        "spalla_l": socket("spalla_l", (-spalla * 0.86, lung * 0.84, 0),
                           (-0.24, -0.97, 0), up=(0, 0, 1), radius=girth * 0.40,
                           provides="limb_mount", side="l", tags=("alto",)),
        "spalla_r": socket("spalla_r", (spalla * 0.86, lung * 0.84, 0),
                           (0.24, -0.97, 0), up=(0, 0, 1), radius=girth * 0.40,
                           provides="limb_mount", side="r", tags=("alto",)),
        "anca_l": socket("anca_l", (-girth * 0.56, lung * 0.05, 0), (-0.06, -1, 0),
                         up=(0, 0, 1), radius=girth * 0.38,
                         provides="limb_mount", side="l", tags=("basso",)),
        "anca_r": socket("anca_r", (girth * 0.56, lung * 0.05, 0), (0.06, -1, 0),
                         up=(0, 0, 1), radius=girth * 0.38,
                         provides="limb_mount", side="r", tags=("basso",)),
        # dove vanno i due volumi che a livello alto prendono il posto del
        # torso: uno in basso e uno in alto, altrimenti finiscono uno dentro l'altro
        "core_basso": socket("core_basso", (0, 0, 0), (0, 1, 0), up=(0, 0, 1),
                             radius=girth * 0.7, provides="segment",
                             tags=("basso",)),
        "core_alto": socket("core_alto", (0, lung * 0.40, 0), (0, 1, 0),
                            up=(0, 0, 1), radius=girth * 0.7, provides="segment",
                            tags=("alto",)),
        "schiena": socket("schiena", (0, lung * 0.62, -girth * flat * 0.9),
                          (0, 0, -1), up=(0, 1, 0), radius=girth * 0.5,
                          provides="gear_mount"),
    })


def _figli_del_torso(v, ctx):
    """Al livello 3 il torso non e' piu' un pezzo unico.

    Bacino e petto **prendono il posto** della sua geometria: i suoi socket
    restano — le braccia si attaccano ancora alla spalla — ma il volume unico
    no, altrimenti sarebbe dentro il petto.

    Il collo non e' qui. Sta sullo stesso innesto della testa, e dichiararlo
    come figlio del torso vorrebbe dire mandarli tutti e due nello stesso
    posto. E' il piano a decidere se c'e' un collo fra le spalle e la testa:
    `torso -> collo -> testa` e' una catena come un'altra.
    """
    lung = v["length"]
    return [
        Attachment(id="bacino", component="pelvis", level=3, replaces_parent=True,
                   insert=0.0,
                   requirement=Requirement(capability="segment", tags=("basso",)),
                   params={"girth": v["girth"], "flat": v["flat"],
                           "length": lung * 0.44}),
        Attachment(id="petto", component="chest", level=3, replaces_parent=True,
                   insert=0.0,
                   requirement=Requirement(capability="segment", tags=("alto",)),
                   params={"girth": v["girth"], "flat": v["flat"],
                           "length": lung * 0.62}),
    ]


TORSO = Component(
    id="torso", build=_torso, children=_figli_del_torso,
    description="il busto, con collo, spalle e anche",
    params={
        "length": ParamSpec(0.54, DISTANCE, min=0.05, max=5.0,
                            semantic_role="length", derived="root.height * 0.3416"),
        "girth": ParamSpec(0.21, DISTANCE, min=0.02, max=3.0,
                           semantic_role="girth", derived="root.height * 0.1309"),
        "flat": ParamSpec(0.62, RATIO, min=0.30, max=1.20,
                          description="quanto e' schiacciato di profilo"),
        "squash": ParamSpec(0.35, RATIO, min=0.0, max=1.0,
                            description="quanto la sezione tende al rettangolo"),
        "shoulder": ParamSpec(1.05, RATIO, min=0.6, max=1.8,
                              description="apertura delle spalle"),
    },
    provides=(Capability("core_mount"),),
    mounts=(mount("head_mount", socket_id="collo"),
            mount("limb_mount", socket_id="spalla_l", side="l", tags=("alto",)),
            mount("limb_mount", socket_id="spalla_r", side="r", tags=("alto",)),
            mount("limb_mount", socket_id="anca_l", side="l", tags=("basso",)),
            mount("limb_mount", socket_id="anca_r", side="r", tags=("basso",)),
            mount("segment", socket_id="core_basso", tags=("basso",)),
            mount("segment", socket_id="core_alto", tags=("alto",)),
            mount("gear_mount", socket_id="schiena")),
    role="torso", material="skin", requires=frozenset({"connected"}),
    tags=frozenset({"umanoide", "humanoid", "torso", "body", "busto"}))


# --------------------------------------------------------------------------- #
# I pezzi del busto
# --------------------------------------------------------------------------- #
def _segmento(profilo, tag: str):
    """Fabbrica per i pezzi del busto: cambiano solo il profilo e i socket."""
    def costruisci(v, ctx) -> Piece:
        lung, girth = v["length"], v["girth"]
        mesh = _profilo(profilo, girth, lung, v["flat"])
        return Piece(mesh=mesh, material="skin", tags=(tag, "body"), sockets={
            "base": base_socket(girth * 0.7, axis="+Y"),
            "top": socket("top", (0, lung, 0), (0, 1, 0), up=(0, 0, 1),
                          radius=girth * 0.5, provides="segment"),
        })
    return costruisci


_PARAMETRI_SEGMENTO = {
    "length": ParamSpec(0.24, DISTANCE, min=0.02, max=3.0, semantic_role="length"),
    "girth": ParamSpec(0.21, DISTANCE, min=0.02, max=3.0, semantic_role="girth"),
    "flat": ParamSpec(0.62, RATIO, min=0.3, max=1.2),
}

PELVIS = Component(
    id="pelvis", build=_segmento([(0.0, 0.74), (0.35, 0.96), (1.0, 0.86)], "pelvis"),
    description="il bacino: la parte bassa del busto",
    params=dict(_PARAMETRI_SEGMENTO),
    provides=(Capability("segment"),),
    role="torso", material="skin", tags=frozenset({"umanoide", "humanoid", "torso", "body", "busto"}))


def _petto(v, ctx) -> Piece:
    lung, girth = v["length"], v["girth"]
    mesh = _profilo([(0.0, 0.95), (0.35, 1.0), (0.78, 0.98), (1.0, 0.58)],
                    girth, lung, v["flat"], 0.4)
    return Piece(mesh=mesh, material="skin", tags=("chest", "body"), sockets={
        "base": base_socket(girth * 0.8, axis="+Y"),
        "top": socket("top", (0, lung, 0), (0, 1, 0), up=(0, 0, 1),
                      radius=girth * 0.4, provides="segment"),
    })


CHEST = Component(
    id="chest", build=_petto,
    description="la cassa toracica",
    params=dict(_PARAMETRI_SEGMENTO),
    provides=(Capability("segment"),),
    role="torso", material="skin", tags=frozenset({"umanoide", "humanoid", "torso", "body", "busto"}))


def _collo(v, ctx) -> Piece:
    lung, girth = v["length"], v["girth"]
    mesh = grow([(0.0, girth), (1.0, girth * 0.92)], sides=LATI, length=lung, axis=1)
    return Piece(mesh=mesh, material="skin", tags=("neck",), sockets={
        "base": base_socket(girth, axis="+Y"),
        "tip": socket("tip", (0, lung, 0), (0, 1, 0), up=(0, 0, 1),
                      radius=girth * 0.92, provides="head_mount"),
    })


NECK = Component(
    id="neck", build=_collo,
    description="il collo: regge la testa e la stacca dalle spalle",
    params={"length": ParamSpec(0.081, DISTANCE, min=0.01, max=1.0,
                                semantic_role="length",
                                derived="root.height * 0.0512"),
            "girth": ParamSpec(0.063, DISTANCE, min=0.01, max=1.0,
                               semantic_role="girth",
                               derived="root.height * 0.0398")},
    provides=(Capability("head_mount"),),
    mounts=(mount("head_mount", socket_id="tip"),),
    role="neck", material="skin", tags=frozenset({"umanoide", "humanoid", "collo", "neck"}))
