"""Animazioni di parti rigide: rotazioni sui giunti, niente skinning.

I modelli di 3DGen sono composti di pezzi: una coscia, uno stinco, un piede.
Deformare i vertici con dei pesi (skinning) sarebbe la soluzione per un
personaggio scolpito come una superficie unica; qui la strada naturale e'
ruotare ogni pezzo attorno al socket che lo tiene, che e' esattamente il
giunto. Costa niente da calcolare, si esporta in glTF senza pelle ne' pesi, e
ogni motore lo legge.

**Limite dichiarato, non aggirato**: il corpo di un assemblaggio e' una
superficie fusa e continua. Ruotando una coscia si vede la cucitura all'anca
aprirsi, perche' i triangoli attorno al giunto appartengono a due parti che si
muovono in modo diverso. Per le andature ampie e' visibile. Nasconderlo
richiederebbe pesi di skinning, cioe' proprio la cosa che qui non si vuole.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from app.anim.skeleton import Joint, Skeleton
from app.core.logging_setup import get

log = get("anim.clip")

SAMPLES = 16            # campioni per ciclo: una sinusoide in LINEAR non chiede di piu'


def quaternion(axis: np.ndarray, degrees: float) -> np.ndarray:
    """Quaternione (x, y, z, w), l'ordine che vuole il glTF."""
    asse = np.asarray(axis, dtype=float)
    norma = float(np.linalg.norm(asse))
    if norma < 1e-9:
        return np.array([0.0, 0.0, 0.0, 1.0])
    asse = asse / norma
    mezzo = np.radians(float(degrees)) * 0.5
    return np.concatenate([asse * np.sin(mezzo), [np.cos(mezzo)]])


@dataclass
class Channel:
    """La rotazione di un giunto nel tempo."""

    joint: str
    times: np.ndarray            # secondi, crescenti
    rotations: np.ndarray        # (n, 4), quaternioni xyzw

    def at(self, t: float) -> np.ndarray:
        """Il campione piu' vicino: serve ai test e all'anteprima, non all'export."""
        return self.rotations[int(np.argmin(np.abs(self.times - t)))]


@dataclass
class Clip:
    """Un'animazione completa e ciclica."""

    name: str
    duration: float
    channels: list[Channel] = field(default_factory=list)
    loop: bool = True

    @property
    def joints(self) -> list[str]:
        return [c.joint for c in self.channels]

    def channel(self, joint: str) -> Channel | None:
        return next((c for c in self.channels if c.joint == joint), None)

    def is_closed(self) -> bool:
        """Un ciclo che non torna al punto di partenza scatta a ogni giro."""
        return all(np.allclose(c.rotations[0], c.rotations[-1], atol=1e-6)
                   for c in self.channels)


def swing(joint: Joint, axis: np.ndarray, degrees: float, duration: float,
          phase: float = 0.0, cycles: int = 1, bias: float = 0.0) -> Channel:
    """Oscillazione sinusoidale di un giunto attorno a un asse del mondo.

    Il primo e l'ultimo campione coincidono per costruzione, cosi' il ciclo si
    richiude senza scatti.
    """
    n = SAMPLES * cycles
    times = np.linspace(0.0, duration, n + 1)
    fasi = 2.0 * np.pi * (cycles * times / max(duration, 1e-6) + phase)
    angoli = bias + degrees * np.sin(fasi)
    rotations = np.stack([quaternion(axis, a) for a in angoli])
    return Channel(joint=joint.name, times=times, rotations=rotations)


# --------------------------------------------------------------------------- #
# Le animazioni
# --------------------------------------------------------------------------- #
def idle(skeleton: Skeleton, duration: float = 3.0) -> Clip:
    """Respiro: quello che un modello fermo deve comunque fare.

    Ampiezze piccole di proposito. Un idle che si nota e' un idle sbagliato, e
    ampiezze piccole non aprono le cuciture fra le parti.
    """
    laterale = skeleton.axis_vector("lat")
    verticale = skeleton.axis_vector("up")
    canali: list[Channel] = []

    radice = skeleton.root
    if radice is not None:
        canali.append(swing(radice, laterale, 1.2, duration))
    for testa in skeleton.find("head"):
        canali.append(swing(testa, verticale, 2.5, duration, phase=0.25))
    for coda in skeleton.find("tail"):
        canali.append(swing(coda, verticale, 4.0, duration, phase=0.1))
    longitudinale = skeleton.axis_vector("long")
    for ala in skeleton.find("wing"):
        # segno per lato: senza, un'ala si alza mentre l'altra si abbassa
        canali.append(swing(ala, longitudinale, 3.0 * skeleton.lateral_sign(ala),
                            duration))
    return Clip(name="idle", duration=duration, channels=canali)


def walk(skeleton: Skeleton, duration: float = 1.0) -> Clip:
    """Camminata: gli arti oscillano avanti e indietro, in diagonale.

    L'asse e' quello **laterale del corpo**, uguale per tutti gli arti: usando
    la terna di ciascun socket, due gambe simmetriche ruoterebbero in versi
    opposti e il passo alterno diventerebbe un passo simultaneo.
    """
    asse = skeleton.axis_vector("lat")
    fasi_gambe = skeleton.gait_phases("leg")
    fasi_braccia = skeleton.gait_phases("arm")
    canali: list[Channel] = []

    # Ampiezze decrescenti lungo l'arto: l'anca fa il passo, il piede lo rifinisce.
    ampiezze = {"leg": 20.0, "arm": 14.0}
    ritardi = {"leg": 0.0, "arm": 0.5}          # le braccia contrastano le gambe

    for tag, fasi in (("leg", fasi_gambe), ("arm", fasi_braccia)):
        for giunto in skeleton.find(tag):
            if giunto.name not in fasi:
                continue
            profondita = _depth_in_limb(skeleton, giunto, tag)
            gradi = ampiezze[tag] * (0.55 ** profondita)
            canali.append(swing(giunto, asse, gradi, duration,
                                phase=fasi[giunto.name] + ritardi[tag]
                                + 0.08 * profondita))

    for coda in skeleton.find("tail"):
        canali.append(swing(coda, skeleton.axis_vector("up"), 7.0, duration))
    return Clip(name="walk", duration=duration, channels=canali)


def wing_beat(skeleton: Skeleton, duration: float = 0.8) -> Clip:
    """Battito d'ali: le due ali salgono e scendono insieme.

    L'asse e' quello longitudinale del corpo, e il segno dipende dal lato:
    senza il segno, un'ala salirebbe mentre l'altra scende.
    """
    asse = skeleton.axis_vector("long")
    canali: list[Channel] = []
    ali = skeleton.find("wing")
    for ala in ali:
        segno = skeleton.lateral_sign(ala)
        canali.append(swing(ala, asse, 32.0 * segno, duration))
        for figlio in skeleton.descendants(ala.name):
            canali.append(swing(figlio, asse, 12.0 * segno, duration, phase=0.1))
    if not ali:
        return Clip(name="wing_beat", duration=duration, channels=[])

    for coda in skeleton.find("tail"):
        canali.append(swing(coda, skeleton.axis_vector("lat"), 5.0, duration))
    return Clip(name="wing_beat", duration=duration, channels=canali)


def _depth_in_limb(skeleton: Skeleton, joint: Joint, tag: str) -> int:
    """Quanti giunti dello stesso arto ci sono sopra questo: 0 e' l'attacco."""
    profondita = 0
    corrente = joint
    while corrente.parent:
        padre = skeleton.get(corrente.parent)
        if padre is None or not padre.has(tag):
            break
        profondita += 1
        corrente = padre
    return profondita


BUILDERS = {"idle": idle, "walk": walk, "wing_beat": wing_beat}


def make(name: str, skeleton: Skeleton) -> Clip:
    """Un'animazione per nome. Un nome sconosciuto e' un errore, non un silenzio."""
    if name not in BUILDERS:
        raise KeyError("animazione sconosciuta: %s (note: %s)"
                       % (name, ", ".join(BUILDERS)))
    return BUILDERS[name](skeleton)


def default_clips(skeleton: Skeleton) -> list[Clip]:
    """Le animazioni che hanno senso per *questo* scheletro.

    Un pesce non ha una camminata e un cavallo non batte le ali: si esporta
    solo cio' che il modello puo' davvero fare, invece di riempire il file di
    canali vuoti.
    """
    clips = [idle(skeleton)]
    if skeleton.gait_phases("leg"):
        clips.append(walk(skeleton))
    if skeleton.find("wing"):
        clips.append(wing_beat(skeleton))
    vuote = [c.name for c in clips if not c.channels]
    if vuote:
        log.info("animazioni senza canali, scartate: %s", ", ".join(vuote))
    return [c for c in clips if c.channels]
