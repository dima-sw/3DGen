"""Teste di creature: rana e drago.

Una testa di rana non e' una testa umana con parametri diversi: ha il cranio
schiacciato, gli occhi **sopra** invece che davanti, e un muso largo. La cosa
che le rende intercambiabili non e' la forma, e' il contratto — entrambe
dichiarano `head_mount` e un socket `base` orientato allo stesso modo.

Convenzione: crescono lungo +Y, come una testa umana, e lo dichiarano con
`base`. Chi le monta non deve sapere nient'altro.
"""
from app.core.authoring import base_socket
from app.core.capability import Capability, Requirement, mount
from app.core.component import Attachment, Component, Piece
from app.core.params import DISTANCE, RATIO, ParamSpec
from app.core.socket import socket
from app.geometry.kernel import block, grow

LATI = 6


def _testa_di_rana(v, ctx) -> Piece:
    """Cranio basso e largo, occhi in cima, muso che sporge in avanti."""
    larghezza, altezza = v["width"], v["height"]
    profondita = v["depth"]

    # il cranio: largo, schiacciato, con la fronte piatta
    cranio = grow([(0.00, larghezza * 0.62), (0.22, larghezza * 0.98),
                   (0.62, larghezza * 1.00), (0.88, larghezza * 0.86),
                   (1.00, larghezza * 0.58)],
                  sides=LATI, length=altezza, axis=1,
                  flat=profondita / max(larghezza, 1e-6), squash=0.55)

    # il muso: un blocco davanti, con gli spigoli. Nel low poly una sporgenza
    # senza spigoli sparisce nell'ombreggiatura piatta.
    muso = block((v["mouth_width"] * 2.0, altezza * 0.34, v["snout_depth"] * 2.0),
                 sides=4, squash=1.0, axis=2)
    muso.apply_translation([0.0, altezza * 0.30, profondita * 0.55 + v["snout_depth"]])
    mesh = cranio + muso

    occhio = v["eye_size"]
    return Piece(mesh=mesh, material="skin", tags=("head", "anfibio"), sockets={
        "base": base_socket(larghezza * 0.5, axis="+Y"),
        "cima": socket("cima", (0, altezza * 0.96, 0), (0, 1, 0), up=(0, 0, 1),
                       radius=larghezza * 0.7, provides="hair_mount"),
        "muso": socket("muso", (0, altezza * 0.34,
                                profondita * 0.55 + v["snout_depth"] * 2.0),
                       (0, 0, 1), up=(0, 1, 0), radius=v["mouth_width"],
                       provides="face_mount"),
        # dove si appende qualcosa di piccolo: un anello, un orecchino
        "narice": socket("narice", (v["mouth_width"] * 0.45, altezza * 0.42,
                                    profondita * 0.55 + v["snout_depth"] * 1.6),
                         (0.3, 0.4, 1), up=(0, 1, 0),
                         radius=v["snout_depth"] * 0.35, provides="anchor"),
        "viso": socket("viso", (0, altezza * 0.42, profondita * 0.6), (0, 0, 1),
                       up=(0, 1, 0), radius=larghezza * 0.6, provides="face_mount"),
        # gli occhi stanno **sopra**: e' cio' che rende una rana una rana
        "occhio_l": socket("occhio_l", (-larghezza * 0.52, altezza * 0.86,
                                        profondita * 0.10),
                           (-0.45, 0.88, 0.15), up=(0, 0, 1), radius=occhio,
                           provides="face_mount", side="l", tags=("occhio",)),
        "occhio_r": socket("occhio_r", (larghezza * 0.52, altezza * 0.86,
                                        profondita * 0.10),
                           (0.45, 0.88, 0.15), up=(0, 0, 1), radius=occhio,
                           provides="face_mount", side="r", tags=("occhio",)),
    })


def _figli_della_rana(v, ctx):
    """Gli occhi sporgenti: due bulbi sopra il cranio."""
    return [Attachment(id="occhio_" + lato, component="bulging_eye", level=3,
                       insert=0.30, material="eye",
                       requirement=Requirement(capability="face_mount", side=lato,
                                               tags=("occhio",)),
                       params={"size": v["eye_size"]})
            for lato in ("l", "r")]


FROG_HEAD = Component(
    id="frog_head", build=_testa_di_rana, children=_figli_della_rana,
    description="una testa di rana: cranio basso e largo, occhi sopra, muso sporgente",
    params={
        "width": ParamSpec(0.13, DISTANCE, min=0.01, max=2.0, semantic_role="girth",
                           description="mezza larghezza del cranio"),
        "height": ParamSpec(0.16, DISTANCE, min=0.01, max=2.0,
                            semantic_role="length"),
        "depth": ParamSpec(0.12, DISTANCE, min=0.01, max=2.0, semantic_role="girth"),
        "eye_size": ParamSpec(0.045, DISTANCE, min=0.002, max=0.5,
                              semantic_role="girth"),
        "mouth_width": ParamSpec(0.10, DISTANCE, min=0.005, max=1.0,
                                 semantic_role="girth"),
        "snout_depth": ParamSpec(0.05, DISTANCE, min=0.002, max=1.0,
                                 semantic_role="girth"),
    },
    provides=(Capability("head_mount"),),
    mounts=(mount("face_mount", socket_id="muso"),
            mount("face_mount", socket_id="viso"),
            mount("anchor", socket_id="narice"),
            mount("face_mount", socket_id="occhio_l", side="l", tags=("occhio",)),
            mount("face_mount", socket_id="occhio_r", side="r", tags=("occhio",)),
            mount("hair_mount", socket_id="cima")),
    role="head", material="skin", requires=frozenset({"connected"}),
    tags=frozenset({"anfibio", "testa", "creatura"}))


def _occhio_sporgente(v, ctx) -> Piece:
    """Mezza sfera sfaccettata: il bulbo che una rana ha sopra la testa."""
    s = v["size"]
    mesh = grow([(0.0, s * 0.7), (0.45, s * 1.0), (0.80, s * 0.9), (1.0, s * 0.35)],
                sides=LATI, length=s * 1.7, axis=1)
    return Piece(mesh=mesh, material="eye", tags=("eye", "detail"),
                 sockets={"base": base_socket(s * 0.7, axis="+Y")})


BULGING_EYE = Component(
    id="bulging_eye", build=_occhio_sporgente,
    description="un occhio sporgente, come quello di una rana",
    params={"size": ParamSpec(0.045, DISTANCE, min=0.002, max=0.5,
                              semantic_role="girth")},
    provides=(Capability("face_mount"),),
    role="", material="eye", tags=frozenset({"anfibio", "occhio"}))


def _testa_di_drago(v, ctx) -> Piece:
    """Muso lungo e corna: due blocchi affusolati sopra il cranio."""
    larghezza, altezza = v["width"], v["height"]
    cranio = grow([(0.00, larghezza * 0.55), (0.25, larghezza * 0.95),
                   (0.70, larghezza * 0.92), (1.00, larghezza * 0.48)],
                  sides=LATI, length=altezza, axis=1, flat=0.85, squash=0.5)
    muso = grow([(0.0, larghezza * 0.72), (0.6, larghezza * 0.58),
                 (1.0, larghezza * 0.30)],
                sides=5, length=v["snout_depth"] * 3.0, axis=2, squash=0.5)
    muso.apply_translation([0.0, altezza * 0.34, larghezza * 0.5])
    mesh = cranio + muso

    if v["horns"] > 0.01:
        for segno in (-1.0, 1.0):
            corno = grow([(0.0, larghezza * 0.16), (1.0, 0.0)], sides=4,
                         length=altezza * v["horns"], axis=1, point_end=True)
            corno.apply_translation([segno * larghezza * 0.55, altezza * 0.82, 0.0])
            mesh = mesh + corno

    return Piece(mesh=mesh, material="scale", tags=("head", "rettile"), sockets={
        "base": base_socket(larghezza * 0.5, axis="+Y"),
        "cima": socket("cima", (0, altezza * 0.98, 0), (0, 1, 0), up=(0, 0, 1),
                       radius=larghezza * 0.6, provides="hair_mount"),
        "muso": socket("muso", (0, altezza * 0.34,
                                larghezza * 0.5 + v["snout_depth"] * 3.0),
                       (0, 0, 1), up=(0, 1, 0), radius=larghezza * 0.3,
                       provides="face_mount"),
        "viso": socket("viso", (0, altezza * 0.5, larghezza * 0.62), (0, 0, 1),
                       up=(0, 1, 0), radius=larghezza * 0.5, provides="face_mount"),
    })


DRAGON_HEAD = Component(
    id="dragon_head", build=_testa_di_drago,
    description="una testa di drago: muso lungo, corna, squame",
    params={
        "width": ParamSpec(0.17, DISTANCE, min=0.01, max=3.0, semantic_role="girth"),
        "height": ParamSpec(0.20, DISTANCE, min=0.01, max=3.0,
                            semantic_role="length"),
        "snout_depth": ParamSpec(0.08, DISTANCE, min=0.005, max=1.0,
                                 semantic_role="girth"),
        "horns": ParamSpec(0.5, RATIO, min=0.0, max=2.0,
                           description="lunghezza delle corna, in frazione dell'altezza"),
    },
    provides=(Capability("head_mount"),),
    mounts=(mount("face_mount", socket_id="muso"),
            mount("face_mount", socket_id="viso"),
            mount("hair_mount", socket_id="cima")),
    role="head", material="scale",
    tags=frozenset({"rettile", "testa", "fantasia", "creatura"}))
