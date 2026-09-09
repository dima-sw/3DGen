"""Un componente che dipende dal vocabolario di alfa."""
from app.core.capability import Capability
from app.core.component import Component, Piece


def _niente(v, ctx):
    return Piece(mesh=None, sockets={}, tags=("prova",))


PEZZO = Component(
    id="pezzo",
    build=_niente,
    description="si attacca all'innesto generico di alfa",
    provides=(Capability("innesto_generico"),),
    tags=frozenset({"prova", "zeta"}),
)
