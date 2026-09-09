"""Un vocabolario che il core non conosce, e non deve conoscere.

Tre componenti annidati uno dentro l'altro:

    quantum_blob
        crystal
            glow

Nessuno dei tre e' un umanoide, un animale, un edificio o un veicolo. Se il
registry li indicizza lo stesso e li restituisce nelle sue query, vuol dire che
il core non ha categorie nascoste da qualche parte.

Il plugin non modifica niente del core: importa i contratti e basta.
"""
from app.core.capability import Capability, Requirement, mount
from app.core.component import Attachment, BuildContext, Component, Piece
from app.core.params import DISTANCE, INT, ParamSpec
from app.core.socket import socket
from app.core.vocabulary import SCOPE_PART, EffectSpec, StyleProfile
from app.geometry.kernel import grow

MISTERIOSO = Capability("mysterious_object", frozenset({"quantistico"}))


def _blob(v, ctx: BuildContext) -> Piece:
    """Costruito con il kernel poligonale, ma potrebbe essere qualunque cosa."""
    raggio = float(v["raggio"])
    mesh = grow([(0.0, raggio * 0.6), (0.5, raggio), (1.0, raggio * 0.4)],
                sides=int(v["lati"]), length=raggio * 2.4, axis=0)
    return Piece(mesh=mesh,
                 sockets={"risonanza": socket("risonanza", (raggio, raggio, 0.0),
                                              (0.0, 1.0, 0.0), radius=raggio * 0.3,
                                              provides="resonance_mount")},
                 tags=("quantistico",))


def _figli_del_blob(v, ctx: BuildContext) -> list:
    return [Attachment(id="cristallo", component="external_test_plugin:crystal",
                       requirement=Requirement(capability="resonance_mount"),
                       level=2, scale_mode="socket")]


def _cristallo(v, ctx: BuildContext) -> Piece:
    lungo = float(v["lunghezza"])
    mesh = grow([(0.0, lungo * 0.18), (1.0, 0.0)], sides=5, length=lungo,
                axis=0, point_end=True)
    return Piece(mesh=mesh,
                 sockets={"punta": socket("punta", (lungo, 0.0, 0.0),
                                          (1.0, 0.0, 0.0), radius=lungo * 0.05,
                                          provides="resonance_mount")},
                 tags=("quantistico",))


def _figli_del_cristallo(v, ctx: BuildContext) -> list:
    return [Attachment(id="bagliore", component="external_test_plugin:glow",
                       requirement=Requirement(capability="resonance_mount"),
                       level=3, optional=True)]


def _bagliore(v, ctx: BuildContext) -> Piece:
    """Senza geometria: un componente non e' obbligato ad averne."""
    return Piece(mesh=None, sockets={}, tags=("luce",))


QUANTUM_BLOB = Component(
    id="quantum_blob",
    build=_blob,
    children=_figli_del_blob,
    description="una massa che risuona, di natura non specificata",
    params={"raggio": ParamSpec(0.4, DISTANCE, min=0.05, max=5.0),
            "lati": ParamSpec(7, INT, min=3, max=24)},
    provides=(MISTERIOSO,),
    mounts=(mount("resonance_mount", socket_id="risonanza"),),
    tags=frozenset({"quantistico", "strano"}),
)

CRYSTAL = Component(
    id="crystal",
    build=_cristallo,
    children=_figli_del_cristallo,
    description="un cristallo che cresce sulla risonanza del blob",
    params={"lunghezza": ParamSpec(0.3, DISTANCE, min=0.02, max=3.0)},
    provides=(MISTERIOSO, Capability("resonance_mount")),
    mounts=(mount("resonance_mount", socket_id="punta"),),
    tags=frozenset({"quantistico", "cristallo"}),
)

GLOW = Component(
    id="glow",
    build=_bagliore,
    description="un bagliore sulla punta del cristallo",
    provides=(Capability("resonance_mount"),),
    tags=frozenset({"quantistico", "luce"}),
)

RISUONA = EffectSpec(
    id="risuona",
    description="fa vibrare cio' che risuona",
    scopes=(SCOPE_PART,),
    applies_to=frozenset({"mysterious_object"}),
)

CRISTALLINO = StyleProfile(
    id="cristallino",
    description="sfaccettato, pochi lati, spigoli vivi",
    params={"lati": 5, "spigoli": "vivi"},
)
