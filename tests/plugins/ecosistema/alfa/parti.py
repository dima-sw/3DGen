"""Componenti di prova. Nessuno di loro rappresenta qualcosa del mondo."""
from app.core.capability import Capability, mount
from app.core.component import Component, Piece
from app.core.params import DISTANCE, ParamSpec


def _niente(v, ctx):
    """Un componente puo' non avere geometria: esiste per contenerne altri."""
    return Piece(mesh=None, sockets={}, tags=("prova",))


NODO = Component(
    id="nodo",
    build=_niente,
    description="un nodo qualunque, con un innesto generico a sinistra",
    params={"taglia": ParamSpec(1.0, DISTANCE, min=0.1, max=10.0)},
    provides=(Capability("cosa_alfa"),),
    mounts=(mount("innesto_generico", socket_id="attacco", side="l"),),
    tags=frozenset({"prova", "alfa"}),
)

FOGLIA = Component(
    id="foglia",
    build=_niente,
    description="qualcosa che si attacca a un innesto generico",
    provides=(Capability("innesto_generico"), Capability("cosa_alfa")),
    tags=frozenset({"prova", "alfa"}),
)
