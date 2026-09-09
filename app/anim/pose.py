"""Cinematica diretta: da un'animazione a una posa concreta.

Serve a due cose molto pratiche. La prima e' poter **verificare** che quanto
viene scritto nel glTF faccia davvero quello che deve: un giunto ruotato deve
restare attaccato dove sta, e il pezzo in fondo all'arto deve muoversi piu' di
quello attaccato al corpo. La seconda e' poter mostrare o esportare un
fotogramma senza passare da un motore esterno.

Le formule sono quelle del glTF, applicate nello stesso ordine: ogni nodo e'
`traslazione * rotazione`, e la posa nel mondo e' il prodotto lungo la catena.
"""
from __future__ import annotations

import numpy as np

from app.anim.clip import Clip
from app.anim.skeleton import Skeleton


def matrix_from_quaternion(q) -> np.ndarray:
    """Matrice di rotazione 3x3 da un quaternione (x, y, z, w)."""
    x, y, z, w = (float(v) for v in q)
    norma = np.sqrt(x * x + y * y + z * z + w * w)
    if norma < 1e-12:
        return np.eye(3)
    x, y, z, w = x / norma, y / norma, z / norma, w / norma
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


def sample(clip: Clip, joint: str, t: float) -> np.ndarray:
    """Rotazione di un giunto all'istante `t`, interpolata linearmente.

    Interpolazione lineare sulle componenti come nel glTF con `LINEAR`, con
    rinormalizzazione: fra due campioni vicini la differenza dalla slerp e'
    sotto il decimo di grado, e i campioni qui sono sedici per ciclo.
    """
    canale = clip.channel(joint)
    if canale is None or len(canale.times) == 0:
        return np.array([0.0, 0.0, 0.0, 1.0])
    tempi = np.asarray(canale.times, dtype=float)
    if clip.loop and clip.duration > 0:
        t = float(t) % clip.duration
    indice = int(np.searchsorted(tempi, t, side="right")) - 1
    indice = int(np.clip(indice, 0, len(tempi) - 1))
    if indice >= len(tempi) - 1:
        return canale.rotations[-1]

    intervallo = tempi[indice + 1] - tempi[indice]
    alfa = 0.0 if intervallo <= 1e-12 else (t - tempi[indice]) / intervallo
    a, b = canale.rotations[indice], canale.rotations[indice + 1]
    if float(np.dot(a, b)) < 0.0:
        b = -b                       # verso piu' corto: senza, la rotazione gira al contrario
    q = (1.0 - alfa) * a + alfa * b
    norma = float(np.linalg.norm(q))
    return q / norma if norma > 1e-12 else np.array([0.0, 0.0, 0.0, 1.0])


def pose(skeleton: Skeleton, clip: Clip | None, t: float = 0.0) -> dict[str, np.ndarray]:
    """Matrice 4x4 nel mondo per ogni giunto, all'istante `t`.

    Senza clip si ottiene la posa a riposo, che per costruzione riporta ogni
    parte esattamente dov'era: e' la prova che la gerarchia e' corretta.
    """
    matrici: dict[str, np.ndarray] = {}

    def risolvi(nome: str) -> np.ndarray:
        if nome in matrici:
            return matrici[nome]
        giunto = skeleton.get(nome)
        padre = skeleton.get(giunto.parent) if giunto.parent else None
        locale = np.asarray(giunto.pivot, dtype=float) - (
            np.asarray(padre.pivot, dtype=float) if padre is not None else np.zeros(3))

        nodo = np.eye(4)
        nodo[:3, :3] = matrix_from_quaternion(
            sample(clip, nome, t) if clip is not None else (0, 0, 0, 1))
        nodo[:3, 3] = locale
        mondo = (risolvi(padre.name) @ nodo) if padre is not None else nodo
        matrici[nome] = mondo
        return mondo

    for giunto in skeleton.joints:
        risolvi(giunto.name)
    return matrici


def transform_for(skeleton: Skeleton, clip: Clip | None, joint: str,
                  t: float = 0.0) -> np.ndarray:
    """Trasformazione da applicare alla mesh **in coordinate mondo** di un giunto.

    La mesh e' salvata nel mondo, il nodo la vuole relativa al proprio pivot:
    la si porta nel pivot, si applica la catena, e si torna nel mondo.
    """
    return _to_world(pose(skeleton, clip, t), skeleton, joint)


def _to_world(matrici: dict[str, np.ndarray], skeleton: Skeleton,
              joint: str) -> np.ndarray:
    verso_pivot = np.eye(4)
    verso_pivot[:3, 3] = -np.asarray(skeleton.get(joint).pivot, dtype=float)
    return matrici[joint] @ verso_pivot


def posed_scene(scene, skeleton: Skeleton, clip: Clip | None, t: float = 0.0):
    """Una copia della scena con le parti spostate come all'istante `t`.

    Serve per le anteprime e per i test: e' l'unico modo di guardare
    un'animazione senza aprire il file in un motore.
    """
    import copy

    matrici = pose(skeleton, clip, t)
    posata = copy.copy(scene)
    posata.nodes = []
    for nodo in scene.nodes:
        if skeleton.get(nodo.id) is None:
            posata.nodes.append(nodo)
            continue
        copia = copy.copy(nodo)
        copia.mesh = nodo.mesh.copy()
        copia.mesh.apply_transform(_to_world(matrici, skeleton, nodo.id))
        posata.nodes.append(copia)
    return posata
