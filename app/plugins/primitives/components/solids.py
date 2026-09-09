"""Blocco e tubo: due solidi, nessun significato.

Sono il caso piu' semplice possibile di plugin nel formato nuovo, e servono a
due cose: dare a chiunque un vocabolario di partenza da annidare, e dimostrare
che il percorso `plugin.json -> modulo -> registry` regge con componenti veri —
geometria costruita, socket dichiarati, parametri tipati.

Rispettano la convenzione del sistema locale: la parte cresce da 0 verso +X,
+Y e' il dorso, +Z il terzo destrorso. Con l'asse di crescita preso come
"avanti" e +Y come "su", `destra = avanti x su = +Z`: per questo l'innesto
laterale su +Z dichiara lato `r` e quello su -Z lato `l`.
"""
from app.core.capability import Capability, mount
from app.core.component import BuildContext, Component, Piece
from app.core.params import BOOL, DISTANCE, INT, RATIO, ParamSpec
from app.core.socket import socket
from app.geometry.kernel import block, grow

SOLID = Capability("solid", frozenset({"geometria"}))

# Gli innesti che entrambi i solidi espongono. Dichiarati qui una volta: il
# registry li indicizza senza costruire niente, il builder li ritrova come
# socket veri dentro il `Piece`.
INNESTI = (
    mount("end_mount", socket_id="base", description="la base, verso -X"),
    mount("end_mount", socket_id="tip", description="la punta, verso +X"),
    mount("surface_mount", socket_id="top", side="top"),
    mount("surface_mount", socket_id="bottom", side="bottom"),
    mount("surface_mount", socket_id="left", side="l"),
    mount("surface_mount", socket_id="right", side="r"),
)


def _facce_laterali(lunghezza: float, alto: float, largo: float) -> dict:
    """I quattro innesti di superficie, a meta' del solido."""
    meta = lunghezza * 0.5
    raggio = min(alto, largo) * 0.35
    return {
        "top": socket("top", (meta, alto * 0.5, 0.0), (0.0, 1.0, 0.0),
                      up=(1.0, 0.0, 0.0), radius=raggio,
                      provides="surface_mount", side="top"),
        "bottom": socket("bottom", (meta, -alto * 0.5, 0.0), (0.0, -1.0, 0.0),
                         up=(1.0, 0.0, 0.0), radius=raggio,
                         provides="surface_mount", side="bottom"),
        "right": socket("right", (meta, 0.0, largo * 0.5), (0.0, 0.0, 1.0),
                        up=(0.0, 1.0, 0.0), radius=raggio,
                        provides="surface_mount", side="r"),
        "left": socket("left", (meta, 0.0, -largo * 0.5), (0.0, 0.0, -1.0),
                       up=(0.0, 1.0, 0.0), radius=raggio,
                       provides="surface_mount", side="l"),
    }


def _estremita(lunghezza: float, raggio_base: float, raggio_punta: float) -> dict:
    return {
        "base": socket("base", (0.0, 0.0, 0.0), (-1.0, 0.0, 0.0),
                       radius=raggio_base, provides="end_mount"),
        "tip": socket("tip", (lunghezza, 0.0, 0.0), (1.0, 0.0, 0.0),
                      radius=raggio_punta, provides="end_mount"),
    }


def costruisci_blocco(v: dict, ctx: BuildContext) -> Piece:
    lunghezza, alto, largo = v["length"], v["height"], v["width"]
    mesh = block((lunghezza, alto, largo), sides=int(v["sides"]),
                 taper=v["taper"], axis=0)
    mesh.apply_translation([lunghezza * 0.5, 0.0, 0.0])   # base all'origine

    sockets = _estremita(lunghezza, min(alto, largo) * 0.5,
                         min(alto, largo) * 0.5 * v["taper"])
    sockets.update(_facce_laterali(lunghezza, alto, largo))
    return Piece(mesh=mesh, sockets=sockets, tags=("solido", "spigoloso"))


def costruisci_tubo(v: dict, ctx: BuildContext) -> Piece:
    lunghezza = v["length"]
    base, punta = v["radius"], v["radius"] * v["taper"]
    mesh = grow([(0.0, base), (1.0, punta)], sides=int(v["sides"]),
                length=lunghezza, axis=0, point_end=bool(v["pointed"]))

    sockets = _estremita(lunghezza, base, 0.0 if v["pointed"] else punta)
    sockets.update(_facce_laterali(lunghezza, base * 2.0, base * 2.0))
    return Piece(mesh=mesh, sockets=sockets, tags=("solido", "tondo"))


BLOCCO = Component(
    id="block",
    build=costruisci_blocco,
    description="un blocco squadrato che cresce lungo +X",
    params={
        "length": ParamSpec(1.0, DISTANCE, min=0.01, max=100.0),
        "height": ParamSpec(1.0, DISTANCE, min=0.01, max=100.0),
        "width": ParamSpec(1.0, DISTANCE, min=0.01, max=100.0),
        "sides": ParamSpec(4, INT, min=3, max=24),
        "taper": ParamSpec(1.0, RATIO, min=0.0, max=4.0),
    },
    provides=(SOLID,),
    mounts=INNESTI,
    tags=frozenset({"primitiva", "spigoloso"}),
)

TUBO = Component(
    id="tube",
    build=costruisci_tubo,
    description="un tubo che cresce lungo +X, rastremabile fino alla punta",
    params={
        "length": ParamSpec(1.0, DISTANCE, min=0.01, max=100.0),
        "radius": ParamSpec(0.25, DISTANCE, min=0.005, max=50.0),
        "sides": ParamSpec(8, INT, min=3, max=48),
        "taper": ParamSpec(1.0, RATIO, min=0.0, max=4.0),
        "pointed": ParamSpec(False, BOOL),
    },
    provides=(SOLID,),
    mounts=INNESTI,
    tags=frozenset({"primitiva", "tondo"}),
)
