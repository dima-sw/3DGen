"""Grammatica di forme su campi di distanza con segno.

Il punto di questo modulo: il sistema non deve conoscere "pesce", "lupo" o
"drago". Deve conoscere un piccolo insieme di **volumi** e un piccolo insieme di
**operazioni** con cui trasformarli e combinarli. Tutto il resto e' composizione.

    corpo di pesce = ellissoide + elongate + taper
    tentacolo      = capsula affusolata + bend + twist
    quattro zampe  = capsula + mirror + repeat

Perche' sui campi di distanza e non sulle mesh: piegare, torcere e rastremare
qui sono deformazioni della coordinata di interrogazione, cioe' tre righe di
numpy senza problemi di topologia. Sulle mesh triangolate le stesse operazioni
richiedono tessellazione fitta e producono autointersezioni.

Convenzioni: asse Y in alto, unita' in metri, un campo negativo dentro il solido.
"""
from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Iterable, Sequence

import numpy as np

FAR = 1.0e6          # valore per "molto fuori dal solido"
Vec3 = tuple[float, float, float]


def _v(value: Sequence[float] | float) -> np.ndarray:
    if isinstance(value, (int, float)):
        return np.array([value, value, value], dtype=float)
    return np.asarray(value, dtype=float)


# --------------------------------------------------------------------------- #
# Base
# --------------------------------------------------------------------------- #
class Field(ABC):
    """Un volume implicito. `sample` restituisce la distanza con segno."""

    @abstractmethod
    def sample(self, p: np.ndarray) -> np.ndarray:
        """p ha forma (..., 3); il risultato ha forma (...)."""

    @abstractmethod
    def bounds(self) -> tuple[np.ndarray, np.ndarray]:
        """Scatola che contiene il solido. Conservativa, mai stretta."""

    # ------------------------------------------------------------ comodita' #
    def __or__(self, other: "Field") -> "Field":
        return Union([self, other])

    def __and__(self, other: "Field") -> "Field":
        return Intersection([self, other])

    def __sub__(self, other: "Field") -> "Field":
        return Difference(self, other)

    def at(self, offset: Vec3) -> "Field":
        return Translate(self, offset)

    def eval_grid(self, origin: np.ndarray, step: float, shape: tuple[int, int, int]) -> np.ndarray:
        """Valuta su una griglia regolare. Le unioni ridefiniscono per andare
        piu' veloci valutando ogni figlio solo dentro la propria scatola."""
        axes = [origin[i] + step * np.arange(shape[i]) for i in range(3)]
        grid = np.stack(np.meshgrid(*axes, indexing="ij"), axis=-1)
        return self.sample(grid)


@dataclass
class Primitive(Field, ABC):
    pass


# --------------------------------------------------------------------------- #
# Volumi di base
# --------------------------------------------------------------------------- #
@dataclass
class Sphere(Primitive):
    radius: float = 0.5

    def sample(self, p):
        return np.linalg.norm(p, axis=-1) - self.radius

    def bounds(self):
        r = _v(self.radius)
        return -r, r


@dataclass
class Ellipsoid(Primitive):
    """Sfera scalata: la base di quasi ogni corpo organico."""

    radii: Vec3 = (0.5, 0.35, 0.25)

    def sample(self, p):
        r = _v(self.radii)
        q = p / r
        k0 = np.linalg.norm(q, axis=-1)
        k1 = np.linalg.norm(q / r, axis=-1)
        return np.where(k0 > 1e-9, k0 * (k0 - 1.0) / np.maximum(k1, 1e-9), -float(np.min(r)))

    def bounds(self):
        r = _v(self.radii)
        return -r, r


@dataclass
class Box(Primitive):
    size: Vec3 = (1.0, 1.0, 1.0)
    rounding: float = 0.0

    def sample(self, p):
        h = _v(self.size) / 2.0 - self.rounding
        q = np.abs(p) - h
        outside = np.linalg.norm(np.maximum(q, 0.0), axis=-1)
        inside = np.minimum(np.max(q, axis=-1), 0.0)
        return outside + inside - self.rounding

    def bounds(self):
        h = _v(self.size) / 2.0
        return -h, h


@dataclass
class Capsule(Primitive):
    """Segmento ingrossato, con raggio variabile: arti, code, tentacoli, rami."""

    a: Vec3 = (0.0, -0.5, 0.0)
    b: Vec3 = (0.0, 0.5, 0.0)
    radius: float = 0.2
    radius_end: float | None = None

    def sample(self, p):
        a, b = _v(self.a), _v(self.b)
        r0 = float(self.radius)
        r1 = r0 if self.radius_end is None else float(self.radius_end)
        ab = b - a
        denom = float(ab @ ab) or 1e-9
        t = np.clip(((p - a) @ ab) / denom, 0.0, 1.0)
        closest = a + t[..., None] * ab
        return np.linalg.norm(p - closest, axis=-1) - (r0 + (r1 - r0) * t)

    def bounds(self):
        a, b = _v(self.a), _v(self.b)
        r = max(float(self.radius), float(self.radius if self.radius_end is None else self.radius_end))
        return np.minimum(a, b) - r, np.maximum(a, b) + r


@dataclass
class Profile(Primitive):
    """Solido a sezioni ellittiche variabili lungo X: la forma organica di base.

    `stations` e' una successione di `(t, ry, rz)` con `t` da 0 (coda, x=-length)
    a 1 (muso, x=+length). Fra una stazione e l'altra i raggi si interpolano.

    E' la differenza fra un pesce e un panino. Un ellissoide sa dire solo "largo
    in mezzo"; un profilo sa dire dove il corpo e' alto e stretto, dove si
    strozza nel peduncolo e dove riparte. La stessa primitiva, con la sezione
    schiacciata (`rz` piccolo), da' pinne e ali con un vero bordo d'attacco.

    Interpolazione: `smooth=False` lascia le stazioni come sono, e le pieghe
    fra un tratto e l'altro diventano spigoli veri — che in low-poly si vogliono.
    `smooth=True` infittisce con Catmull-Rom **alla costruzione**, cosi' il
    campionamento resta una `np.interp` e non costa nulla in piu'.
    """

    stations: Any = ((0.0, 0.05, 0.05), (0.5, 0.4, 0.28), (1.0, 0.06, 0.06))
    length: float = 0.9
    smooth: bool = True

    def __post_init__(self) -> None:
        righe = np.asarray([[float(v) for v in s] for s in self.stations], dtype=float)
        if len(righe) < 2:
            raise ValueError("un profilo ha bisogno di almeno due stazioni")
        righe = righe[np.argsort(righe[:, 0])]
        righe[:, 0] = np.clip(righe[:, 0], 0.0, 1.0)
        # Un raggio esattamente zero renderebbe indefinita la direzione radiale:
        # si tiene una punta finissima invece di una punta impossibile.
        righe[:, 1:] = np.maximum(righe[:, 1:], 1e-4)
        if self.smooth and len(righe) >= 3:
            righe = _densify(righe)
        self._t = np.ascontiguousarray(righe[:, 0])
        self._ry = np.ascontiguousarray(righe[:, 1])
        self._rz = np.ascontiguousarray(righe[:, 2])
        # pendenza del profilo: serve a non sovrastimare la distanza sui tratti
        # inclinati, che e' cio' che fa "gonfiare" i coni nei campi approssimati
        passo = np.gradient(self._t) * 2.0 * max(float(self.length), 1e-6)
        pendenza = np.maximum(np.abs(np.gradient(self._ry) / passo),
                              np.abs(np.gradient(self._rz) / passo))
        self._scala = 1.0 / np.sqrt(1.0 + pendenza ** 2)

    def sample(self, p):
        lunghezza = max(float(self.length), 1e-6)
        t = np.clip((p[..., 0] + lunghezza) / (2.0 * lunghezza), 0.0, 1.0)
        ry = np.interp(t, self._t, self._ry)
        rz = np.interp(t, self._t, self._rz)

        y, z = p[..., 1], p[..., 2]
        raggio = np.sqrt(y * y + z * z)
        # raggio dell'ellisse nella direzione del punto: esatto per la sezione
        # circolare, ottimo per quelle poco eccentriche, e — a differenza della
        # metrica ellittica pura — si comporta bene quando la sezione va a zero
        norma = np.sqrt((y / ry) ** 2 + (z / rz) ** 2)
        atteso = np.where(norma > 1e-9, raggio / np.maximum(norma, 1e-9),
                          np.minimum(ry, rz))
        radiale = (raggio - atteso) * np.interp(t, self._t, self._scala)

        tappo = np.abs(p[..., 0]) - lunghezza
        fuori = np.sqrt(np.maximum(radiale, 0.0) ** 2 + np.maximum(tappo, 0.0) ** 2)
        return fuori + np.minimum(np.maximum(radiale, tappo), 0.0)

    def bounds(self):
        lunghezza = max(float(self.length), 1e-6)
        return (np.array([-lunghezza, -self._ry.max(), -self._rz.max()]),
                np.array([lunghezza, self._ry.max(), self._rz.max()]))


def _densify(righe: np.ndarray, per_tratto: int = 6) -> np.ndarray:
    """Infittisce un profilo con Catmull-Rom, una volta sola alla costruzione.

    Cosi' il campionamento resta una interpolazione lineare — vettoriale e
    veloce — pur avendo una curva continua invece di una spezzata.
    """
    estesi = np.vstack([righe[0] + (righe[0] - righe[1]), righe,
                        righe[-1] + (righe[-1] - righe[-2])])
    fuori = []
    for i in range(1, len(estesi) - 2):
        p0, p1, p2, p3 = estesi[i - 1], estesi[i], estesi[i + 1], estesi[i + 2]
        for passo in range(per_tratto):
            s = passo / per_tratto
            fuori.append(0.5 * ((2 * p1) + (-p0 + p2) * s
                                + (2 * p0 - 5 * p1 + 4 * p2 - p3) * s * s
                                + (-p0 + 3 * p1 - 3 * p2 + p3) * s * s * s))
    fuori.append(righe[-1])
    denso = np.asarray(fuori, dtype=float)
    denso[:, 0] = np.clip(denso[:, 0], 0.0, 1.0)
    denso[:, 1:] = np.maximum(denso[:, 1:], 1e-4)
    return denso[np.argsort(denso[:, 0])]


@dataclass
class Torus(Primitive):
    radius: float = 0.4
    tube: float = 0.12

    def sample(self, p):
        q = np.stack([np.linalg.norm(p[..., [0, 2]], axis=-1) - self.radius, p[..., 1]], axis=-1)
        return np.linalg.norm(q, axis=-1) - self.tube

    def bounds(self):
        r = self.radius + self.tube
        return np.array([-r, -self.tube, -r]), np.array([r, self.tube, r])


@dataclass
class Cone(Primitive):
    """Cono con base in basso e apice verso +Y."""

    radius: float = 0.4
    height: float = 1.0

    def sample(self, p):
        h, r = float(self.height), float(self.radius)
        y = p[..., 1] + h / 2.0
        radial = np.linalg.norm(p[..., [0, 2]], axis=-1)
        allowed = r * np.clip(1.0 - y / h, 0.0, 1.0)
        side = radial - allowed
        cap = np.maximum(-y, y - h)
        outside = np.sqrt(np.maximum(side, 0.0) ** 2 + np.maximum(cap, 0.0) ** 2)
        return outside + np.minimum(np.maximum(side, cap), 0.0)

    def bounds(self):
        r, h = self.radius, self.height / 2.0
        return np.array([-r, -h, -r]), np.array([r, h, r])


# --------------------------------------------------------------------------- #
# Operazioni: deformano la coordinata di interrogazione
# --------------------------------------------------------------------------- #
@dataclass
class Modifier(Field, ABC):
    child: Field


@dataclass
class Translate(Modifier):
    offset: Vec3 = (0.0, 0.0, 0.0)

    def sample(self, p):
        return self.child.sample(p - _v(self.offset))

    def bounds(self):
        lo, hi = self.child.bounds()
        o = _v(self.offset)
        return lo + o, hi + o


@dataclass
class Rotate(Modifier):
    """Rotazione in gradi, ordine XYZ."""

    angles: Vec3 = (0.0, 0.0, 0.0)

    def _matrix(self) -> np.ndarray:
        rx, ry, rz = (math.radians(a) for a in self.angles)
        cx, sx, cy, sy, cz, sz = (math.cos(rx), math.sin(rx), math.cos(ry),
                                  math.sin(ry), math.cos(rz), math.sin(rz))
        mx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
        my = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
        mz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
        return mz @ my @ mx

    def sample(self, p):
        return self.child.sample(p @ self._matrix())      # inversa = trasposta

    def bounds(self):
        lo, hi = self.child.bounds()
        corners = np.array([[x, y, z] for x in (lo[0], hi[0])
                            for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
        turned = corners @ self._matrix().T
        return turned.min(axis=0), turned.max(axis=0)


@dataclass
class Transform(Modifier):
    """Rototraslazione con scala uniforme.

    E' il nodo che usa il motore di composizione per portare una parte dal suo
    sistema locale a quello dell'assemblaggio. Con rotazione ortonormale e scala
    uniforme il campo resta una distanza esatta, quindi i coefficienti di
    fusione continuano a valere in metri.
    """

    rotation: np.ndarray = field(default_factory=lambda: np.eye(3))
    translation: Vec3 = (0.0, 0.0, 0.0)
    scale: float = 1.0

    def sample(self, p):
        s = float(self.scale) or 1e-9
        q = (p - _v(self.translation)) @ self.rotation / s   # R^-1 = R^T
        return self.child.sample(q) * s

    def bounds(self):
        lo, hi = self.child.bounds()
        corners = np.array([[x, y, z] for x in (lo[0], hi[0])
                            for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
        world = corners @ np.asarray(self.rotation).T * float(self.scale) + _v(self.translation)
        return world.min(axis=0), world.max(axis=0)


def align_rotation(source: np.ndarray, target: np.ndarray) -> np.ndarray:
    """Rotazione minima che porta il versore `source` su `target`."""
    a = np.asarray(source, dtype=float)
    b = np.asarray(target, dtype=float)
    a = a / (np.linalg.norm(a) or 1.0)
    b = b / (np.linalg.norm(b) or 1.0)
    v = np.cross(a, b)
    c = float(a @ b)
    if np.linalg.norm(v) < 1e-9:
        if c > 0:
            return np.eye(3)
        # versori opposti: mezzo giro attorno a un asse qualunque ortogonale
        axis = np.array([1.0, 0.0, 0.0])
        if abs(a[0]) > 0.9:
            axis = np.array([0.0, 1.0, 0.0])
        axis = np.cross(a, axis)
        axis = axis / np.linalg.norm(axis)
        x, y, z = axis
        return 2.0 * np.array([[x * x, x * y, x * z],
                               [x * y, y * y, y * z],
                               [x * z, y * z, z * z]]) - np.eye(3)
    vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + vx + vx @ vx / (1.0 + c)


@dataclass
class Scale(Modifier):
    """Scala non uniforme. Il campo resta un limite corretto della distanza,
    non la distanza esatta: sufficiente per marching cubes."""

    factor: Vec3 | float = 1.0

    def sample(self, p):
        f = _v(self.factor)
        return self.child.sample(p / f) * float(np.min(np.abs(f)))

    def bounds(self):
        lo, hi = self.child.bounds()
        f = _v(self.factor)
        a, b = lo * f, hi * f
        return np.minimum(a, b), np.maximum(a, b)


@dataclass
class Elongate(Modifier):
    """Stira il solido lungo un segmento: da sfera a capsula, da testa a muso."""

    amount: Vec3 = (0.0, 0.0, 0.0)

    def sample(self, p):
        h = _v(self.amount)
        q = p - np.clip(p, -h, h)
        return self.child.sample(q)

    def bounds(self):
        lo, hi = self.child.bounds()
        h = np.abs(_v(self.amount))
        return lo - h, hi + h


@dataclass
class Taper(Modifier):
    """Rastrema: il raggio cresce o cala lungo Y. E' cio' che rende un corpo
    affusolato invece che un ovale."""

    amount: float = 0.0
    axis: int = 1

    def sample(self, p):
        k = float(self.amount)
        scale = 1.0 + k * p[..., self.axis]
        scale = np.maximum(scale, 0.05)
        q = p.copy()
        for i in range(3):
            if i != self.axis:
                q[..., i] = q[..., i] / scale
        return self.child.sample(q) * np.minimum(scale, 1.0)

    def bounds(self):
        lo, hi = self.child.bounds()
        span = max(abs(lo[self.axis]), abs(hi[self.axis]))
        grow = max(1.0, 1.0 + abs(self.amount) * span)
        out_lo, out_hi = lo.copy(), hi.copy()
        for i in range(3):
            if i != self.axis:
                out_lo[i], out_hi[i] = lo[i] * grow, hi[i] * grow
        return out_lo, out_hi


def _rotate_pair(p: np.ndarray, angle: np.ndarray, i: int, j: int) -> np.ndarray:
    """Ruota le componenti (i, j) di un angolo che varia punto per punto."""
    c, s = np.cos(angle), np.sin(angle)
    q = p.copy()
    q[..., i] = c * p[..., i] - s * p[..., j]
    q[..., j] = s * p[..., i] + c * p[..., j]
    return q


@dataclass
class Bend(Modifier):
    """Curva il solido: l'angolo cresce lungo `axis`, la rotazione avviene
    attorno ad `around`. Pinne, corna, code, ali."""

    amount: float = 0.0
    axis: int = 0
    around: int = 2

    def _pair(self) -> tuple[int, int]:
        return tuple(i for i in range(3) if i != int(self.around) % 3)  # type: ignore[return-value]

    def sample(self, p):
        i, j = self._pair()
        return self.child.sample(_rotate_pair(p, float(self.amount) * p[..., int(self.axis) % 3], i, j))

    def bounds(self):
        lo, hi = self.child.bounds()
        reach = float(np.max(np.abs(np.concatenate([lo, hi]))))
        pad = abs(float(self.amount)) * reach * reach
        return lo - pad, hi + pad


@dataclass
class Twist(Modifier):
    """Torce attorno ad `axis`: tentacoli, conchiglie, canne rigate."""

    amount: float = 0.0
    axis: int = 1

    def sample(self, p):
        a = int(self.axis) % 3
        i, j = (k for k in range(3) if k != a)
        return self.child.sample(_rotate_pair(p, float(self.amount) * p[..., a], i, j))

    def bounds(self):
        lo, hi = self.child.bounds()
        a = int(self.axis) % 3
        r = max(max(abs(lo[k]), abs(hi[k])) for k in range(3) if k != a)
        out_lo, out_hi = np.full(3, -r), np.full(3, r)
        out_lo[a], out_hi[a] = lo[a], hi[a]
        return out_lo, out_hi


@dataclass
class Round(Modifier):
    """Smussa il solido di un raggio costante."""

    radius: float = 0.0

    def sample(self, p):
        return self.child.sample(p) - float(self.radius)

    def bounds(self):
        lo, hi = self.child.bounds()
        r = _v(self.radius)
        return lo - r, hi + r


@dataclass
class Shell(Modifier):
    """Svuota il solido lasciando un guscio: caschi, corazze, scafi."""

    thickness: float = 0.02

    def sample(self, p):
        return np.abs(self.child.sample(p)) - float(self.thickness) / 2.0

    def bounds(self):
        lo, hi = self.child.bounds()
        t = _v(self.thickness)
        return lo - t, hi + t


@dataclass
class Mirror(Modifier):
    """Simmetria: una parte descritta una volta, generata su entrambi i lati."""

    axis: int = 0

    def sample(self, p):
        q = p.copy()
        q[..., self.axis] = np.abs(q[..., self.axis])
        return self.child.sample(q)

    def bounds(self):
        lo, hi = self.child.bounds()
        reach = max(abs(lo[self.axis]), abs(hi[self.axis]))
        out_lo, out_hi = lo.copy(), hi.copy()
        out_lo[self.axis], out_hi[self.axis] = -reach, reach
        return out_lo, out_hi


@dataclass
class Repeat(Modifier):
    """Ripete lungo un asse un numero finito di volte: zampe, denti, segmenti."""

    count: int = 3
    spacing: float = 0.3
    axis: int = 0

    def sample(self, p):
        n = max(int(self.count), 1)
        s = float(self.spacing) or 1e-6
        half = (n - 1) / 2.0
        q = p.copy()
        # Il reticolo va spostato di half*s: con un numero pari di copie i centri
        # cadono a mezzo passo, e limitare l'indice a +-half le disallineerebbe.
        shifted = q[..., self.axis] + half * s
        idx = np.clip(np.round(shifted / s), 0.0, float(n - 1))
        q[..., self.axis] = shifted - s * idx
        return self.child.sample(q)

    def bounds(self):
        lo, hi = self.child.bounds()
        reach = (max(int(self.count), 1) - 1) / 2.0 * abs(self.spacing)
        out_lo, out_hi = lo.copy(), hi.copy()
        out_lo[self.axis] -= reach
        out_hi[self.axis] += reach
        return out_lo, out_hi


# --------------------------------------------------------------------------- #
# Combinatori
# --------------------------------------------------------------------------- #
def smooth_min(a: np.ndarray, b: np.ndarray, k: float) -> np.ndarray:
    """Unione morbida. k grande = fusione carnosa; k piccolo = parti distinte."""
    if k <= 1e-9:
        return np.minimum(a, b)
    h = np.clip(0.5 + 0.5 * (b - a) / k, 0.0, 1.0)
    return b * (1.0 - h) + a * h - k * h * (1.0 - h)


def smooth_max(a: np.ndarray, b: np.ndarray, k: float) -> np.ndarray:
    if k <= 1e-9:
        return np.maximum(a, b)
    h = np.clip(0.5 - 0.5 * (b - a) / k, 0.0, 1.0)
    return b * (1.0 - h) + a * h + k * h * (1.0 - h)


@dataclass
class Union(Field):
    """Unione, eventualmente morbida.

    `blend` puo' essere un solo valore o uno per figlio: e' il parametro che
    distingue "testa fusa nel corpo" da "pinna attaccata al corpo".
    """

    children: list[Field] = field(default_factory=list)
    blend: float | Sequence[float] = 0.0

    def _k(self, index: int) -> float:
        if isinstance(self.blend, (int, float)):
            return float(self.blend)
        seq = list(self.blend)
        return float(seq[index]) if index < len(seq) else 0.0

    def sample(self, p):
        if not self.children:
            return np.full(p.shape[:-1], FAR)
        out = self.children[0].sample(p)
        for i, child in enumerate(self.children[1:], start=1):
            out = smooth_min(out, child.sample(p), self._k(i))
        return out

    def bounds(self):
        if not self.children:
            return np.zeros(3), np.zeros(3)
        los, his = zip(*(c.bounds() for c in self.children))
        pad = max((self._k(i) for i in range(len(self.children))), default=0.0)
        return np.min(los, axis=0) - pad, np.max(his, axis=0) + pad

    # -- valutazione a banda stretta: e' qui che si guadagna il tempo -------- #
    def eval_grid(self, origin, step, shape):
        out = np.full(shape, FAR, dtype=float)
        for i, child in enumerate(self.children):
            k = self._k(i)
            lo, hi = child.bounds()
            # fuori dalla scatola allargata, il figlio non puo' cambiare il minimo
            margin = 4.0 * k + 3.0 * step
            i0 = np.maximum(np.floor((lo - margin - origin) / step).astype(int), 0)
            i1 = np.minimum(np.ceil((hi + margin - origin) / step).astype(int) + 1,
                            np.asarray(shape))
            if np.any(i1 <= i0):
                continue
            sub_shape = tuple(int(v) for v in (i1 - i0))
            sub_origin = origin + i0 * step
            values = child.eval_grid(sub_origin, step, sub_shape)
            box = (slice(i0[0], i1[0]), slice(i0[1], i1[1]), slice(i0[2], i1[2]))
            out[box] = smooth_min(out[box], values, k)
        return out


@dataclass
class Intersection(Field):
    children: list[Field] = field(default_factory=list)
    blend: float = 0.0

    def sample(self, p):
        if not self.children:
            return np.full(p.shape[:-1], FAR)
        out = self.children[0].sample(p)
        for child in self.children[1:]:
            out = smooth_max(out, child.sample(p), self.blend)
        return out

    def bounds(self):
        if not self.children:
            return np.zeros(3), np.zeros(3)
        los, his = zip(*(c.bounds() for c in self.children))
        return np.max(los, axis=0), np.min(his, axis=0)


@dataclass
class Difference(Field):
    base: Field
    tool: Field
    blend: float = 0.0

    def sample(self, p):
        return smooth_max(self.base.sample(p), -self.tool.sample(p), self.blend)

    def bounds(self):
        return self.base.bounds()


# --------------------------------------------------------------------------- #
# Registro: i nomi che l'LLM potra' usare nel piano
# --------------------------------------------------------------------------- #
VOLUMES = {
    "sphere": Sphere, "ellipsoid": Ellipsoid, "box": Box,
    "capsule": Capsule, "torus": Torus, "cone": Cone, "profile": Profile,
}

OPERATIONS = {
    "translate": Translate, "rotate": Rotate, "scale": Scale,
    "elongate": Elongate, "taper": Taper, "bend": Bend, "twist": Twist,
    "round": Round, "shell": Shell, "mirror": Mirror, "repeat": Repeat,
}

COMBINATORS = {"union": Union, "intersection": Intersection, "difference": Difference}


def grammar_summary() -> str:
    return ("volumi: %s\noperazioni: %s\ncombinatori: %s"
            % (", ".join(sorted(VOLUMES)), ", ".join(sorted(OPERATIONS)),
               ", ".join(sorted(COMBINATORS))))
