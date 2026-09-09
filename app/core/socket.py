"""Socket, posa, innesto: la parte geometrica del contratto.

## CONVENZIONE DEL SISTEMA LOCALE — obbligatoria per ogni plugin

Ogni componente si costruisce nel proprio sistema di riferimento, e quel
sistema e' **dichiarato, non dedotto**:

    +X   asse di crescita: la parte si sviluppa da 0 verso +X a partire
         dalla propria base
    +Y   riferimento di rollio: e' il "dorso" della parte, cio' che decide
         come e' orientata girando attorno all'asse di crescita
    +Z   il terzo, destrorso: +Z = +X x +Y

Un componente che cresce verticalmente (un torso, un tronco) puo' costruirsi
lungo +Y e dichiararlo con il proprio socket di base: quello che conta e' che
**il socket dica la verita'**, non che tutti crescano nello stesso verso.

### Verso dei socket

Il `direction` di un socket punta **fuori** dal componente: e' la direzione in
cui va la parte che ci si attacca. Il figlio si posa in modo che il **verso
opposto** al proprio socket coincida con il `direction` del socket del padre —
cioe' il figlio "esce" dal padre nel verso in cui il padre lo manda.

`up` non e' decorativo: senza un secondo vettore la rotazione resterebbe
indeterminata attorno all'asse, e una testa attaccata di lato guarderebbe in
su. E' un errore che questo progetto ha gia' fatto una volta.

### Perche' e' scritto qui e non nella testa di chi programma

Un plugin di terze parti non puo' indovinare questa convenzione. Se la sbaglia,
le sue parti si attaccano ruotate — succede, e la diagnosi e' lenta perche' il
modello *sembra* costruito. Il test `test_orientation_follows_the_declared_frame`
la verifica su ogni socket di un componente di prova.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence

import numpy as np

from app.core.capability import Capability

# Come si porta il figlio dentro il padre, in frazione del raggio del socket.
# Senza compenetrazione, due pezzi adiacenti mostrano il distacco.
DEFAULT_INSERT = 0.35
# Limiti della scala all'innesto: oltre, un componente estraneo diventa un
# mostro invece di adattarsi.
SCALE_LIMITS = (0.05, 20.0)

# Modalita' di scala dichiarabili su un attacco.
#
#     none           il pezzo tiene le misure che ha dichiarato
#     socket         si porta al raggio dell'innesto: serve a cio' che viene da
#                    un altro vocabolario e deve adattarsi a dove si infila
#     fit_replaced   si porta alla **taglia di cio' che sostituisce**
#
# La terza e' nata da un caso vero. Una spada al posto di una gamba: con `none`
# resta lunga quanto una spada, e su un umanoide alto uno e ottanta una gamba e'
# lunga il doppio — il modello viene sbilenco. Con `socket` succede di peggio,
# perche' il raggio della sua lama e' un settimo di quello di un'anca e la spada
# diventa lunga sei metri. Quello che si vuole dire e' una terza cosa:
# «sostituisci quel pezzo, e stai grande come stava lui».
SCALE_MODE_NONE = "none"
SCALE_MODE_SOCKET = "socket"
SCALE_MODE_FIT_REPLACED = "fit_replaced"

SCALE_MODES = (SCALE_MODE_NONE, SCALE_MODE_SOCKET, SCALE_MODE_FIT_REPLACED)


def unit(vector, fallback=(0.0, 1.0, 0.0)) -> np.ndarray:
    v = np.asarray(vector, dtype=float)
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-9 else np.asarray(fallback, dtype=float)


def orthogonal_up(direction: np.ndarray, up) -> np.ndarray:
    """Rende `up` ortogonale alla direzione, scegliendone uno se degenere."""
    u = unit(up)
    u = u - direction * float(direction @ u)
    if float(np.linalg.norm(u)) < 1e-6:
        candidato = np.array([0.0, 1.0, 0.0])
        if abs(float(direction @ candidato)) > 0.9:
            candidato = np.array([0.0, 0.0, 1.0])
        u = candidato - direction * float(direction @ candidato)
    return unit(u)


@dataclass
class Socket:
    """Un punto di attacco: dove, in che verso, quanto grande, e per che cosa."""

    name: str
    position: np.ndarray
    direction: np.ndarray
    radius: float = 0.1
    up: np.ndarray = field(default_factory=lambda: np.array([0.0, 1.0, 0.0]))
    capabilities: tuple[Capability, ...] = ()
    side: str = ""
    tags: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        self.position = np.asarray(self.position, dtype=float)
        self.direction = unit(self.direction)
        self.up = orthogonal_up(self.direction, self.up)
        self.radius = max(float(self.radius), 1e-4)
        if isinstance(self.capabilities, (str, Capability)):
            self.capabilities = (self.capabilities,)
        self.capabilities = tuple(
            c if isinstance(c, Capability) else Capability(str(c))
            for c in self.capabilities)
        self.tags = frozenset(self.tags)

    # -------------------------------------------------------------- lettura #
    def provides(self, name: str) -> bool:
        return any(c.name == name for c in self.capabilities)

    def all_tags(self) -> frozenset[str]:
        """I tag propri piu' quelli delle capability che offre."""
        return self.tags.union(*(c.tags for c in self.capabilities)) \
            if self.capabilities else self.tags

    def frame(self) -> np.ndarray:
        """Terna ortonormale (direzione, dorso, laterale) come colonne."""
        terzo = np.cross(self.direction, self.up)
        return np.column_stack([self.direction, self.up, terzo])

    def describe(self) -> str:
        capacita = ", ".join(str(c) for c in self.capabilities) or "nessuna"
        return "%s [%s]%s r=%.3f" % (self.name, capacita,
                                     " lato %s" % self.side if self.side else "",
                                     self.radius)


@dataclass
class Placement:
    """Posa di una parte: rotazione rigida, traslazione, scala uniforme.

    La scala e' uniforme di proposito: una scala non uniforme ruotata non e'
    piu' una scala non uniforme, e comporre due pose diventerebbe sbagliato.
    Chi ha bisogno di schiacciare una parte lo fa **dentro** la propria
    geometria, dove sa che cosa sta schiacciando.
    """

    rotation: np.ndarray = field(default_factory=lambda: np.eye(3))
    translation: np.ndarray = field(default_factory=lambda: np.zeros(3))
    scale: float = 1.0

    def apply_point(self, p) -> np.ndarray:
        return self.scale * (self.rotation @ np.asarray(p, dtype=float)) + self.translation

    def apply_direction(self, d) -> np.ndarray:
        return self.rotation @ np.asarray(d, dtype=float)

    def socket_world(self, socket: Socket) -> Socket:
        """Lo stesso socket, visto dal sistema del modello."""
        return Socket(name=socket.name,
                      position=self.apply_point(socket.position),
                      direction=self.apply_direction(socket.direction),
                      radius=socket.radius * self.scale,
                      up=self.apply_direction(socket.up),
                      capabilities=socket.capabilities,
                      side=socket.side, tags=socket.tags)

    def matrix(self) -> np.ndarray:
        m = np.eye(4)
        m[:3, :3] = self.rotation * float(self.scale)
        m[:3, 3] = self.translation
        return m

    def then(self, outer: "Placement") -> "Placement":
        """Questa posa vista dentro un'altra: composizione di trasformazioni."""
        return Placement(rotation=outer.rotation @ self.rotation,
                         translation=outer.apply_point(self.translation),
                         scale=outer.scale * self.scale)


def roll_matrix(axis, degrees: float) -> np.ndarray:
    """Rotazione attorno a un asse, in gradi (formula di Rodrigues)."""
    a = unit(axis)
    t = np.radians(float(degrees))
    x, y, z = a
    c, s = np.cos(t), np.sin(t)
    return np.array([
        [c + x * x * (1 - c), x * y * (1 - c) - z * s, x * z * (1 - c) + y * s],
        [y * x * (1 - c) + z * s, c + y * y * (1 - c), y * z * (1 - c) - x * s],
        [z * x * (1 - c) - y * s, z * y * (1 - c) + x * s, c + z * z * (1 - c)],
    ])


def attach(parent: Placement, parent_socket: Socket, child_socket: Socket, *,
           scale_mode: str = "none", scale: float = 1.0,
           insert: float = DEFAULT_INSERT, roll: float = 0.0) -> Placement:
    """Posa che porta il socket del figlio a innestarsi in quello del padre.

    `scale_mode`:
      - `"none"`  il figlio tiene le misure che ha dichiarato;
      - `"socket"` il figlio si porta al raggio dell'innesto. Serve quando la
        parte viene da un altro vocabolario e non sa niente delle proporzioni
        di chi la ospita: una testa di drago sul collo di un umano.
    """
    bersaglio = parent.socket_world(parent_socket)

    # la parte cresce nel verso opposto al proprio socket di base
    crescita = -child_socket.direction
    terna_figlio = np.column_stack([crescita, child_socket.up,
                                    np.cross(crescita, child_socket.up)])
    terna_bersaglio = np.column_stack([bersaglio.direction, bersaglio.up,
                                       np.cross(bersaglio.direction, bersaglio.up)])
    rotazione = terna_bersaglio @ terna_figlio.T

    if abs(roll) > 1e-9:
        rotazione = roll_matrix(bersaglio.direction, roll) @ rotazione

    if scale_mode == "socket":
        fattore = bersaglio.radius / max(child_socket.radius, 1e-6)
    else:
        fattore = 1.0
    fattore = float(np.clip(fattore * float(scale), *SCALE_LIMITS))

    # spinta dentro il padre: senza compenetrazione il giunto si vede
    ancora = bersaglio.position - bersaglio.direction * (bersaglio.radius * float(insert))
    traslazione = ancora - fattore * (rotazione @ child_socket.position)
    return Placement(rotation=rotazione, translation=traslazione, scale=fattore)


def socket(name: str, position, direction, up=(0.0, 1.0, 0.0), radius: float = 0.1,
           provides: str | Iterable[str] = (), side: str = "",
           tags: Iterable[str] = ()) -> Socket:
    """Scorciatoia leggibile per dichiarare un socket dentro una regola."""
    if isinstance(provides, str):
        provides = (provides,)
    return Socket(name=name, position=np.asarray(position, dtype=float),
                  direction=np.asarray(direction, dtype=float),
                  up=np.asarray(up, dtype=float), radius=float(radius),
                  capabilities=tuple(Capability(str(c)) for c in provides),
                  side=side, tags=frozenset(tags))
