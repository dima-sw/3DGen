"""Un componente con lo stesso nome locale di uno di alfa.

L'id qualificato basta a distinguerli: `alfa:nodo` e `beta:nodo` convivono
senza che nessuno dei due debba sapere dell'altro.
"""
from app.core.capability import Capability, mount
from app.core.component import Component, Piece


def _niente(v, ctx):
    return Piece(mesh=None, sockets={}, tags=("prova",))


NODO = Component(
    id="nodo",
    build=_niente,
    description="lo stesso nome di alfa:nodo, un altro componente",
    provides=(Capability("cosa_beta"),),
    mounts=(mount("innesto_generico", socket_id="attacco", side="r"),),
    tags=frozenset({"prova", "beta"}),
)
