"""Riduzione a pochi poligoni **scegliendo** i piani, non buttandone via a caso.

Il marching cubes produce superfici dense e uniformi: migliaia di triangolini
tutti uguali che, a qualunque risoluzione, danno la stessa cosa tonda.
Abbassare la risoluzione non basta — stessa forma con meno triangoli, piu' la
scalettatura della griglia. Raggruppare i vertici in celle nemmeno: i piani
finiscono dove capita la cella, non dove sta la forma, e si aprono ammaccature.

Qui c'e' l'algoritmo che i piani li sceglie: **quadric error metric** (Garland
& Heckbert, 1997). A ogni vertice si associa la somma delle quadriche dei piani
delle facce che lo toccano; fondere due vertici costa l'errore quadratico
rispetto a quei piani. Si fondono per primi gli spigoli che costano meno —
quelli in mezzo alle zone gia' piatte — e restano per ultimi quelli sulle
creste e sulle silhouette. Il risultato ha facce grandi dove la forma e' piatta
e triangoli fitti sui bordi: e' il low poly fatto apposta invece che subito.

Nessuna dipendenza nuova: `fast_simplification` e `open3d` fanno questo, ma per
duecento righe non vale una libreria in piu'.

**Nota di implementazione.** Il ciclo interno e' scritto in Python puro su
liste di float, non su array numpy. Sembra al contrario del buon senso, ma qui
ogni operazione tocca quattro numeri: la chiamata a numpy costa piu' del conto
che fa. Passando da array (4,4) a dieci float sciolti il tempo e' sceso da
11,6 s a 0,4 s per una testa. Le quadriche iniziali, che sono un conto su tutte
le facce insieme, restano vettoriali.
"""
from __future__ import annotations

import heapq

import numpy as np
import trimesh

from app.core.logging_setup import get

log = get("geometry.lowpoly")

# Sotto questo coseno fra la normale prima e dopo, la fusione ribalterebbe una
# faccia: si rifiuta, invece di produrre una mesh intrecciata.
FLIP_LIMIT = 0.05
# Un vertice con troppe facce incidenti e' quasi sempre un artefatto: fonderlo
# costa molto e rende poco.
MAX_VALENCE = 40


def decimate(mesh: trimesh.Trimesh, target_faces: int,
             preserve: float = 0.0) -> trimesh.Trimesh:
    """Riduce la mesh a circa `target_faces` triangoli, preservando la forma.

    `preserve` aggiunge un costo proporzionale a quanto un vertice si sposta:
    serve quando si vuole essere ancora piu' prudenti sulla silhouette di
    quanto lo sia gia' la metrica quadrica. Zero = solo la quadrica.
    """
    facce = np.asarray(mesh.faces, dtype=np.int64)
    if len(facce) <= target_faces or len(facce) < 4:
        return mesh
    stato = _Stato(np.asarray(mesh.vertices, dtype=float), facce, preserve)
    stato.run(int(target_faces))
    ridotta = stato.result()
    log.info("low poly: %d -> %d facce (obiettivo %d)",
             len(facce), len(ridotta.faces), target_faces)
    return ridotta


def _quadric_add(a: list, b: list) -> list:
    return [a[i] + b[i] for i in range(10)]


def _quadric_error(q: list, x: float, y: float, z: float) -> float:
    """v^T Q v con Q simmetrica, tenuta come dieci coefficienti sciolti."""
    return (q[0] * x * x + 2.0 * q[1] * x * y + 2.0 * q[2] * x * z + 2.0 * q[3] * x
            + q[4] * y * y + 2.0 * q[5] * y * z + 2.0 * q[6] * y
            + q[7] * z * z + 2.0 * q[8] * z + q[9])


class _Stato:
    """Tutta la contabilita' della decimazione, in un posto solo."""

    def __init__(self, vertici: np.ndarray, facce: np.ndarray, preserve: float):
        self.vx = [float(v) for v in vertici[:, 0]]
        self.vy = [float(v) for v in vertici[:, 1]]
        self.vz = [float(v) for v in vertici[:, 2]]
        self.f = [[int(i) for i in faccia] for faccia in facce]
        self.preserve = float(preserve)

        self.vivo_v = [True] * len(self.vx)
        self.vivo_f = [True] * len(self.f)
        self.facce_di: list[set] = [set() for _ in range(len(self.vx))]
        for indice, faccia in enumerate(self.f):
            for vertice in faccia:
                self.facce_di[vertice].add(indice)

        self.q = self._quadriche(vertici, facce)
        self.versione = [0] * len(self.vx)
        self.heap: list = []
        for a, b in self._spigoli(facce):
            self._proponi(int(a), int(b))

    # ------------------------------------------------------------ quadriche #
    def _quadriche(self, vertici: np.ndarray, facce: np.ndarray) -> list[list[float]]:
        """Somma, per ogni vertice, le quadriche dei piani che lo toccano.

        Questo conto e' su tutte le facce insieme, quindi qui numpy paga.
        """
        p0, p1, p2 = vertici[facce[:, 0]], vertici[facce[:, 1]], vertici[facce[:, 2]]
        normali = np.cross(p1 - p0, p2 - p0)
        aree = np.linalg.norm(normali, axis=1)
        # Una faccia degenere non ha un piano: contribuisce zero invece che
        # infinito, cosi' una mesh imperfetta non blocca la riduzione.
        n = normali / np.maximum(aree, 1e-12)[:, None]
        d = -np.einsum("ij,ij->i", n, p0)
        piani = np.concatenate([n, d[:, None]], axis=1) * np.sqrt(aree * 0.5)[:, None]

        a, b, c, e = piani[:, 0], piani[:, 1], piani[:, 2], piani[:, 3]
        coefficienti = np.stack([a * a, a * b, a * c, a * e, b * b, b * c,
                                 b * e, c * c, c * e, e * e], axis=1)
        accumulo = np.zeros((len(vertici), 10))
        for colonna in range(3):
            np.add.at(accumulo, facce[:, colonna], coefficienti)
        return accumulo.tolist()

    @staticmethod
    def _spigoli(facce: np.ndarray) -> np.ndarray:
        spigoli = np.vstack([facce[:, [0, 1]], facce[:, [1, 2]], facce[:, [2, 0]]])
        return np.unique(np.sort(spigoli, axis=1), axis=0)

    # ------------------------------------------------------------- proposte #
    def _migliore(self, a: int, b: int, q: list) -> tuple[float, float, float, float]:
        """Dove mettere il vertice fuso, e quanto costa metterlo li'.

        Tre candidati: i due estremi e il punto di mezzo. Il minimo esatto
        della quadrica darebbe qualche decimo di percento in piu' di fedelta',
        ma richiede di risolvere un sistema 4x4 per ogni spigolo di ogni
        iterazione, e su una superficie quasi piana quel sistema e' mal
        condizionato e propone punti lontanissimi da correggere a mano.
        """
        ax, ay, az = self.vx[a], self.vy[a], self.vz[a]
        bx, by, bz = self.vx[b], self.vy[b], self.vz[b]
        candidati = ((ax, ay, az), (bx, by, bz),
                     (0.5 * (ax + bx), 0.5 * (ay + by), 0.5 * (az + bz)))

        migliore, costo_migliore = candidati[2], float("inf")
        for x, y, z in candidati:
            costo = _quadric_error(q, x, y, z)
            if self.preserve:
                costo += self.preserve * (abs(x - ax) + abs(y - ay) + abs(z - az)
                                          + abs(x - bx) + abs(y - by) + abs(z - bz))
            if costo < costo_migliore:
                migliore, costo_migliore = (x, y, z), costo
        return (max(costo_migliore, 0.0), *migliore)

    def _proponi(self, a: int, b: int) -> None:
        if a == b or not (self.vivo_v[a] and self.vivo_v[b]):
            return
        costo = self._migliore(a, b, _quadric_add(self.q[a], self.q[b]))[0]
        heapq.heappush(self.heap, (costo, self.versione[a], self.versione[b], a, b))

    # -------------------------------------------------------------- fusione #
    def _ribalta(self, a: int, b: int, x: float, y: float, z: float) -> bool:
        """La fusione ribalterebbe qualche faccia?"""
        vx, vy, vz = self.vx, self.vy, self.vz
        condivise = self.facce_di[a] & self.facce_di[b]
        for indice in (self.facce_di[a] | self.facce_di[b]) - condivise:
            if not self.vivo_f[indice]:
                continue
            i, j, k = self.f[indice]
            p = [(x, y, z) if v in (a, b) else (vx[v], vy[v], vz[v]) for v in (i, j, k)]
            q = [(vx[v], vy[v], vz[v]) for v in (i, j, k)]

            u1x, u1y, u1z = q[1][0] - q[0][0], q[1][1] - q[0][1], q[1][2] - q[0][2]
            u2x, u2y, u2z = q[2][0] - q[0][0], q[2][1] - q[0][1], q[2][2] - q[0][2]
            n0x = u1y * u2z - u1z * u2y
            n0y = u1z * u2x - u1x * u2z
            n0z = u1x * u2y - u1y * u2x
            norma0 = (n0x * n0x + n0y * n0y + n0z * n0z) ** 0.5
            if norma0 < 1e-14:
                continue

            w1x, w1y, w1z = p[1][0] - p[0][0], p[1][1] - p[0][1], p[1][2] - p[0][2]
            w2x, w2y, w2z = p[2][0] - p[0][0], p[2][1] - p[0][1], p[2][2] - p[0][2]
            n1x = w1y * w2z - w1z * w2y
            n1y = w1z * w2x - w1x * w2z
            n1z = w1x * w2y - w1y * w2x
            norma1 = (n1x * n1x + n1y * n1y + n1z * n1z) ** 0.5
            if norma1 < 1e-14:
                return True
            if (n0x * n1x + n0y * n1y + n0z * n1z) / (norma0 * norma1) < FLIP_LIMIT:
                return True
        return False

    def run(self, target_faces: int) -> None:
        restano = len(self.f)
        heap = self.heap
        while restano > target_faces and heap:
            costo, va, vb, a, b = heapq.heappop(heap)
            if not (self.vivo_v[a] and self.vivo_v[b]):
                continue
            # voce scaduta: uno dei due vertici e' cambiato dopo la proposta
            if va != self.versione[a] or vb != self.versione[b]:
                continue
            if len(self.facce_di[a]) > MAX_VALENCE or len(self.facce_di[b]) > MAX_VALENCE:
                continue

            _, x, y, z = self._migliore(a, b, _quadric_add(self.q[a], self.q[b]))
            if self._ribalta(a, b, x, y, z):
                continue
            restano -= self._collassa(a, b, x, y, z)

    def _collassa(self, a: int, b: int, x: float, y: float, z: float) -> int:
        """Fonde b dentro a. Restituisce quante facce sono sparite."""
        condivise = self.facce_di[a] & self.facce_di[b]
        for indice in condivise:
            self.vivo_f[indice] = False

        self.vx[a], self.vy[a], self.vz[a] = x, y, z
        self.q[a] = _quadric_add(self.q[a], self.q[b])
        self.vivo_v[b] = False

        for indice in self.facce_di[b]:
            if not self.vivo_f[indice]:
                continue
            faccia = self.f[indice]
            for posizione in range(3):
                if faccia[posizione] == b:
                    faccia[posizione] = a
            self.facce_di[a].add(indice)
        self.facce_di[a] -= condivise
        self.facce_di[b] = set()

        self.versione[a] += 1
        vicini = set()
        for indice in self.facce_di[a]:
            if self.vivo_f[indice]:
                vicini.update(self.f[indice])
        vicini.discard(a)
        for vicino in vicini:
            if self.vivo_v[vicino]:
                self._proponi(a, vicino)
        return len(condivise)

    # --------------------------------------------------------------- uscita #
    def result(self) -> trimesh.Trimesh:
        facce = np.array([f for indice, f in enumerate(self.f) if self.vivo_f[indice]],
                         dtype=np.int64)
        if len(facce) == 0:
            return trimesh.Trimesh(vertices=np.zeros((0, 3)), faces=np.zeros((0, 3), int))
        # un triangolo con due indici uguali non e' un triangolo
        facce = facce[(facce[:, 0] != facce[:, 1]) & (facce[:, 1] != facce[:, 2])
                      & (facce[:, 0] != facce[:, 2])]
        vertici = np.stack([self.vx, self.vy, self.vz], axis=1)
        usati = np.unique(facce)
        rimappa = np.full(len(vertici), -1, dtype=np.int64)
        rimappa[usati] = np.arange(len(usati))
        mesh = trimesh.Trimesh(vertices=vertici[usati], faces=rimappa[facce],
                               process=False)
        mesh.merge_vertices()
        mesh.update_faces(mesh.nondegenerate_faces())
        mesh.remove_unreferenced_vertices()
        return mesh
