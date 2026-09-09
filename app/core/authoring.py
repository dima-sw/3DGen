"""Scrivere un componente: il minimo che serve, e come verificarlo.

Questo modulo non aggiunge niente al modello: mette a portata di mano le due
cose che un autore di plugin sbaglia sempre la prima volta, e un modo di
accorgersene subito.

## La convenzione, in tre righe

    la parte cresce da 0 verso un asse dichiarato   (+X per gli arti, +Y per cio' che sta in piedi)
    il socket `base` sta all'origine e guarda **indietro**, verso -asse
    ogni altro socket guarda **fuori**: e' il verso in cui esce chi si attacca

Il figlio si posa in modo che il **verso opposto** al proprio socket coincida
con il `direction` del socket del padre: cioe' esce dal padre nel verso in cui
il padre lo manda. Se `base` guardasse in avanti invece che indietro, la parte
si costruirebbe all'incontrario — e il modello sembrerebbe costruito, il che e'
il modo peggiore di essere sbagliato.

## Perche' un verificatore e non solo una regola scritta

Perche' una regola scritta la si legge una volta e la si sbaglia lo stesso.
`verify_frame` guarda la geometria vera e dice se la parte cresce dove ha
dichiarato di crescere, se il socket di base e' dove dovrebbe, e se tutti i
socket hanno un verso. Serve all'autore mentre scrive, non al core mentre
costruisce.
"""
from __future__ import annotations

import numpy as np

from app.core.errors import Report
from app.core.socket import Socket, socket

# Gli assi nominabili, e il vettore che ciascuno indica.
ASSI = {
    "+X": np.array([1.0, 0.0, 0.0]), "-X": np.array([-1.0, 0.0, 0.0]),
    "+Y": np.array([0.0, 1.0, 0.0]), "-Y": np.array([0.0, -1.0, 0.0]),
    "+Z": np.array([0.0, 0.0, 1.0]), "-Z": np.array([0.0, 0.0, -1.0]),
}

# Il dorso predefinito per ciascun asse di crescita: serve a fissare la
# rotazione attorno all'asse, che altrimenti resterebbe indeterminata.
DORSO = {"+X": (0.0, 1.0, 0.0), "-X": (0.0, 1.0, 0.0),
         "+Y": (0.0, 0.0, 1.0), "-Y": (0.0, 0.0, 1.0),
         "+Z": (0.0, 1.0, 0.0), "-Z": (0.0, 1.0, 0.0)}


def direction(axis: str) -> np.ndarray:
    return ASSI.get(str(axis).upper(), ASSI["+X"]).copy()


def base_socket(radius: float, axis: str = "+X", *, name: str = "base",
                provides=(), position=(0.0, 0.0, 0.0)) -> Socket:
    """Il socket con cui una parte si posa su chi la contiene.

    Guarda **all'indietro** rispetto alla crescita: e' il verso da cui la parte
    arriva, non quello in cui va.
    """
    return socket(name, position, -direction(axis), up=DORSO.get(axis.upper(),
                                                                 (0.0, 1.0, 0.0)),
                  radius=radius, provides=provides)


def tip_socket(length: float, radius: float, axis: str = "+X", *,
               name: str = "tip", provides=(), side: str = "",
               tags=()) -> Socket:
    """Il socket all'estremita' opposta: guarda **fuori**, nel verso di crescita."""
    verso = direction(axis)
    return socket(name, verso * float(length), verso,
                  up=DORSO.get(axis.upper(), (0.0, 1.0, 0.0)),
                  radius=radius, provides=provides, side=side, tags=tags)


def growth_axis(piece) -> str:
    """Lungo quale asse questa geometria si estende di piu'."""
    if piece.mesh is None or len(piece.mesh.vertices) == 0:
        return ""
    misura = piece.mesh.bounds[1] - piece.mesh.bounds[0]
    indice = int(np.argmax(misura))
    verso = "+" if abs(piece.mesh.bounds[1][indice]) >= \
        abs(piece.mesh.bounds[0][indice]) else "-"
    return "%s%s" % (verso, "XYZ"[indice])


def verify_frame(piece, axis: str = "+X", *, name: str = "",
                 report: Report | None = None) -> Report:
    """Questa parte rispetta la convenzione? Detto guardando la geometria vera.

    Da usare mentre si scrive un plugin, non mentre si costruisce un modello:
    e' un aiuto per l'autore, e il core non lo chiama mai da solo.
    """
    # `or` non basta: un `Report` vuoto e' falso, e le diagnosi
    # finirebbero in un referto diverso da quello di chi lo ha passato.
    report = report if report is not None else Report()
    dove = name or "componente"
    verso = direction(axis)

    base = piece.sockets.get("base")
    if base is None:
        report.add("NO_BASE_SOCKET",
                   "%s non ha un socket 'base'" % dove, where=dove,
                   why="e' il socket con cui una parte si posa su chi la contiene",
                   alternatives=sorted(piece.sockets)[:6])
    elif float(base.direction @ verso) > -0.5:
        report.add("BASE_SOCKET_REVERSED",
                   "%s: il socket 'base' non guarda all'indietro" % dove, where=dove,
                   why="cresce verso %s, quindi 'base' deve guardare verso l'opposto; "
                       "guarda invece %s" % (axis, np.round(base.direction, 2)))

    if piece.mesh is not None and len(piece.mesh.vertices):
        minimo, massimo = piece.mesh.bounds
        indice = "XYZ".index(axis[-1].upper())
        estensione = float(massimo[indice] - minimo[indice])
        misura = float(np.max(massimo - minimo))
        if misura > 0 and estensione < misura * 0.34:
            report.warn("GROWTH_AXIS_MISMATCH",
                        "%s dichiara di crescere lungo %s ma si estende altrove"
                        % (dove, axis), where=dove,
                        why="misurato %s, il lato lungo e' %s"
                            % (np.round(massimo - minimo, 3), growth_axis(piece)))
        partenza = minimo[indice] if axis[0] != "-" else -massimo[indice]
        if misura > 0 and abs(partenza) > misura * 0.25:
            report.warn("BASE_NOT_AT_ORIGIN",
                        "%s non comincia all'origine" % dove, where=dove,
                        why="la base della geometria e' a %.3f lungo %s"
                            % (partenza, axis))

    for nome, s in sorted(piece.sockets.items()):
        if float(np.linalg.norm(s.direction)) < 1e-6:
            report.add("SOCKET_WITHOUT_DIRECTION",
                       "%s: il socket '%s' non ha un verso" % (dove, nome),
                       where=dove,
                       why="senza direzione non si sa da che parte esce il figlio")
        elif not np.all(np.isfinite(s.position)):
            report.add("SOCKET_NOT_FINITE",
                       "%s: il socket '%s' ha coordinate non finite" % (dove, nome),
                       where=dove)
    return report


def describe_frame(piece, axis: str = "+X") -> str:
    """Un riassunto leggibile, per chi sta scrivendo un plugin."""
    righe = ["cresce lungo %s (misurato: %s)" % (axis, growth_axis(piece) or "niente")]
    for nome, s in sorted(piece.sockets.items()):
        righe.append("  %-12s %s -> %s  r=%.3f  %s"
                     % (nome, np.round(s.position, 3), np.round(s.direction, 2),
                        s.radius,
                        ", ".join(c.name for c in s.capabilities) or "-"))
    return "\n".join(righe)
