"""Prova a registrare un componente nel namespace di un altro plugin."""
from app.core.component import Component, Piece


def _niente(v, ctx):
    return Piece(mesh=None)


INTRUSO = Component(id="alfa:nodo", build=_niente,
                    description="occupa il namespace di alfa")
PROPRIO = Component(id="mio", build=_niente,
                    description="questo invece e' legittimo")
DOPPIONE = Component(id="mio", build=_niente,
                     description="stesso id di PROPRIO, nello stesso plugin")
