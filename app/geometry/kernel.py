"""Costruzione di poligoni per regola, non campionamento di un campo.

## Perche' esiste questo file

La pipeline precedente era: campo di distanza, fusione morbida, marching cubes,
decimazione. Produce superfici organiche continue, ed e' ottima per fondere
volumi — ma **non puo' produrre topologia intenzionale**. Ogni vertice sta dove
la griglia ha incrociato l'isosuperficie; nessuno spigolo e' una decisione.

Misurato sul torso dell'umanoide costruito cosi': 493 facce, **296 direzioni di
normale distinte**, il piu' grande gruppo di facce complanari e' di 7 facce,
angolo diedro mediano 6,8 gradi. Cioe': nessuna superficie piatta e nessuno
spigolo. Una bolla liscia campionata a 493 triangoli.

Il low poly vero e' il contrario: **poche facce grandi, piatte, con spigoli
netti dove la forma gira**. Non si ottiene semplificando una bolla, si ottiene
costruendo direttamente i poligoni.

## Come funziona

Una parte e' una **regola** che emette anelli di vertici; il kernel li cuce.

    anelli = [ring(n=8, y=0.0, rx=0.20, rz=0.12),
              ring(n=8, y=0.5, rx=0.24, rz=0.14),
              ring(n=8, y=1.0, rx=0.10, rz=0.07)]
    mesh = sweep(anelli)

Il conto dei poligoni e' **noto in partenza**: `(anelli-1) x n` quadrilateri
piu' i tappi. Otto lati e sei stazioni fanno 80 quadrilateri, 160 triangoli.
Non c'e' niente da decimare, e la topologia e' la stessa a ogni generazione —
il che serve anche per le animazioni e per i livelli di dettaglio.
"""
from __future__ import annotations

import numpy as np
import trimesh

from app.core.logging_setup import get

log = get("geometry.kernel")


def ring(sides: int, height: float, rx: float, rz: float,
         centre: tuple[float, float, float] = (0.0, 0.0, 0.0),
         twist: float = 0.0, squash: float = 0.0) -> np.ndarray:
    """Un anello di `sides` vertici su un piano orizzontale.

    `squash` schiaccia l'anello verso un rettangolo: a zero e' un poligono
    regolare inscritto in un'ellisse, a uno tocca i lati di un rettangolo. E'
    la manopola che fa la differenza fra un tubo e una trave — nel cartoon
    servono entrambi.
    """
    angoli = np.linspace(0.0, 2.0 * np.pi, int(sides), endpoint=False) + float(twist)
    coseno, seno = np.cos(angoli), np.sin(angoli)
    if squash > 0.0:
        # interpolazione fra cerchio e quadrato: x = cos/|max(cos,sin)|
        massimo = np.maximum(np.abs(coseno), np.abs(seno))
        massimo[massimo < 1e-9] = 1.0
        coseno = coseno * (1 - squash) + (coseno / massimo) * squash
        seno = seno * (1 - squash) + (seno / massimo) * squash
    punti = np.stack([coseno * float(rx),
                      np.full(int(sides), float(height)),
                      seno * float(rz)], axis=1)
    return punti + np.asarray(centre, dtype=float)


def sweep(rings: list[np.ndarray], cap_start: bool = True,
          cap_end: bool = True) -> trimesh.Trimesh:
    """Cuce una successione di anelli in una superficie chiusa.

    Tutti gli anelli devono avere lo stesso numero di vertici: e' quello che
    rende la topologia prevedibile. Un anello degenere (raggio zero) diventa un
    vertice solo e chiude la forma a punta, senza tappo.
    """
    if len(rings) < 2:
        raise ValueError("servono almeno due anelli")
    lati = len(rings[0])
    if any(len(r) != lati for r in rings):
        raise ValueError("tutti gli anelli devono avere lo stesso numero di vertici")

    vertici = np.concatenate(rings, axis=0)
    facce: list[tuple[int, int, int]] = []
    for indice in range(len(rings) - 1):
        base_a = indice * lati
        base_b = (indice + 1) * lati
        for k in range(lati):
            k2 = (k + 1) % lati
            a, b = base_a + k, base_a + k2
            c, d = base_b + k2, base_b + k
            # due triangoli per quadrilatero: la faccia resta piatta a coppie
            facce.append((a, b, c))
            facce.append((a, c, d))

    if cap_start:
        facce += _cap(range(0, lati), inverti=True)
    if cap_end:
        base = (len(rings) - 1) * lati
        facce += _cap(range(base, base + lati), inverti=False)

    mesh = trimesh.Trimesh(vertices=vertici, faces=np.asarray(facce, dtype=np.int64),
                           process=False)
    mesh.merge_vertices()
    mesh.update_faces(mesh.nondegenerate_faces())
    mesh.remove_unreferenced_vertices()
    try:
        mesh.fix_normals()
    except Exception:                      # una forma degenere non deve fermare tutto
        pass
    return mesh


def _cap(indici, inverti: bool) -> list[tuple[int, int, int]]:
    """Chiude un anello a ventaglio. Piatto per costruzione: e' un poligono."""
    indici = list(indici)
    facce = []
    for k in range(1, len(indici) - 1):
        a, b, c = indici[0], indici[k], indici[k + 1]
        facce.append((a, c, b) if inverti else (a, b, c))
    return facce


def profile_sweep(stations, sides: int = 6, length: float = 1.0,
                  axis: int = 0, squash: float = 0.0,
                  point_start: bool = False, point_end: bool = False) -> trimesh.Trimesh:
    """Un solido a sezioni variabili, costruito per regola.

    `stations` e' la stessa tabella che usava il profilo implicito — `(t, r1,
    r2)` — ma qui produce poligoni invece di distanze. Stesso vocabolario,
    risultato completamente diverso: facce piatte, spigoli netti, conteggio
    noto.

    L'asse di sviluppo e' X per coerenza con il catalogo delle ricette
    ("ogni parte cresce lungo +X dalla propria base").
    """
    tabella = [[float(v) for v in s] for s in stations]
    if len(tabella) < 2:
        raise ValueError("un profilo ha bisogno di almeno due stazioni")
    tabella.sort(key=lambda s: s[0])

    # Gli anelli si costruiscono **circolari** e la sezione ellittica arriva da
    # una scala non uniforme applicata alla fine. Non e' un dettaglio: con
    # anelli gia' ellittici i quadrilateri del fianco non sono piani, e ogni
    # triangolo esce con una normale sua — 78 normali su 108 facce, cioe' di
    # nuovo una bolla. Una trasformazione affine manda piani in piani, quindi
    # facendola dopo ogni quadrilatero resta piatto: 26 normali su 56 facce.
    rapporti = [s[2] / max(s[1], 1e-9) for s in tabella]
    schiacciamento = float(np.mean(rapporti))

    anelli = []
    for indice, (t, r1, _r2) in enumerate(tabella):
        x = (t * 2.0 - 1.0) * float(length)
        primo, ultimo = indice == 0, indice == len(tabella) - 1
        raggio = 0.0 if (primo and point_start) or (ultimo and point_end) else r1
        anelli.append(ring(sides, x, raggio, raggio, squash=squash))

    # gli anelli nascono con l'altezza su Y: si porta l'asse su quello voluto
    if axis != 1:
        for anello in anelli:
            anello[:, [1, axis]] = anello[:, [axis, 1]]

    mesh = sweep(anelli, cap_start=not point_start, cap_end=not point_end)
    trasversale = [i for i in (0, 1, 2) if i != axis][1]
    scala = [1.0, 1.0, 1.0]
    scala[trasversale] = schiacciamento
    mesh.apply_scale(scala)
    return mesh


def faces_per_normal(mesh: trimesh.Trimesh) -> float:
    """Quante facce condividono la stessa direzione di normale, in media.

    **E' la misura che distingue una mesh disegnata da una campionata.** Una
    mesh fatta di quadrilateri piani vale almeno 2: i due triangoli di ogni
    quadrilatero hanno la stessa normale, e le facce complanari si sommano.
    Una isosuperficie decimata vale circa 1, perche' ogni triangolo guarda da
    una parte sua — ed e' esattamente il sintomo del "pongo".
    """
    if not len(mesh.faces):
        return 0.0
    normali = {tuple(n) for n in np.round(mesh.face_normals, 2)}
    return len(mesh.faces) / max(len(normali), 1)


def stats(mesh: trimesh.Trimesh) -> str:
    """Le misure che dicono se una mesh e' disegnata o campionata."""
    if not len(mesh.faces):
        return "vuota"
    normali = {tuple(n) for n in np.round(mesh.face_normals, 2)}
    angoli = np.degrees(mesh.face_adjacency_angles) if len(mesh.face_adjacency) else np.zeros(1)
    return ("%3d facce, %3d normali, %.2f facce/normale, spigoli duri %2.0f%%, "
            "diedro mediano %.1f gradi"
            % (len(mesh.faces), len(normali), faces_per_normal(mesh),
               100 * (angoli > 25).mean(), float(np.median(angoli))))


def grow(stations, sides: int = 6, length: float = 1.0, axis: int = 0,
         squash: float = 0.0, flat: float = 1.0,
         point_end: bool = False, twist: float = 0.0) -> trimesh.Trimesh:
    """Un solido che **cresce dalla base**, da 0 a `length` lungo `axis`.

    E' la forma naturale per una parte che si attacca: la base sta all'origine,
    dove sta anche il socket. `stations` sono coppie `(t, raggio)` con t da 0
    (base) a 1 (punta); `flat` schiaccia la sezione sull'asse trasversale, e
    viene applicato **dopo** la cucitura perche' una scala non uniforme manda
    piani in piani e lascia i quadrilateri piatti.
    """
    tabella = sorted([[float(v) for v in s] for s in stations], key=lambda s: s[0])
    if len(tabella) < 2:
        raise ValueError("servono almeno due stazioni")

    anelli = []
    for indice, (t, raggio) in enumerate(tabella):
        ultimo = indice == len(tabella) - 1
        r = 0.0 if (ultimo and point_end) else float(raggio)
        anelli.append(ring(sides, t * float(length), r, r, squash=squash,
                           twist=twist * t))
    if axis != 1:
        for anello in anelli:
            anello[:, [1, axis]] = anello[:, [axis, 1]]

    mesh = sweep(anelli, cap_start=True, cap_end=not point_end)
    if abs(flat - 1.0) > 1e-9:
        trasversale = [i for i in (0, 1, 2) if i != axis][1]
        scala = [1.0, 1.0, 1.0]
        scala[trasversale] = float(flat)
        mesh.apply_scale(scala)
    return mesh


def block(size, sides: int = 4, squash: float = 1.0, taper: float = 1.0,
          axis: int = 1) -> trimesh.Trimesh:
    """Un blocco squadrato: la forma piu' onesta del low poly.

    Con `sides=4` e `squash=1` e' una scatola; alzando i lati si smussa. Serve
    per tutto cio' che nel cartoon e' spigoloso — mani, piedi, casse, casse
    toraciche — dove un tubo tondo direbbe la cosa sbagliata.
    """
    sx, sy, sz = (float(v) for v in size)
    lungo = (sx, sy, sz)[axis]
    trasversali = [v for i, v in enumerate((sx, sy, sz)) if i != axis]
    stazioni = [(0.0, 0.5), (1.0, 0.5 * float(taper))]
    mesh = grow(stazioni, sides=sides, length=lungo, axis=axis, squash=squash)
    # gli anelli nascono di raggio 0.5: si portano alle misure volute
    scala = [1.0, 1.0, 1.0]
    altri = [i for i in (0, 1, 2) if i != axis]
    scala[altri[0]] = trasversali[0]
    scala[altri[1]] = trasversali[1]
    mesh.apply_scale(scala)
    mesh.apply_translation([0.0 if i != axis else -lungo * 0.5 for i in (0, 1, 2)])
    return mesh
