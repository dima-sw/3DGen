"""Quanto costa la variabilita' semantica, e che cosa fa su sei richieste vere.

    python tools/variability_benchmark.py [ripetizioni] [--json FILE]

Due parti, e la seconda e' quella che vale.

**Prestazioni** (§18 della milestone): i cinque passi nuovi di V5, misurati
contro una build senza niente. Nessuno di loro dovrebbe spostare l'ordine di
grandezza, perche' nessuno di loro aggiunge un motore: un trait scrive dei
numeri, un `ParamEffect` scrive una richiesta di effetto, il confronto dei frame
confronta due stringhe.

**Richieste** (§15): le sei richieste della milestone, e per ciascuna quattro
colonne separate, perche' `ok=True` non e' una risposta —

    intento      il trait che esprime la richiesta e' **nel vocabolario** che
                 il modello vede per quel prompt? (la lezione di V3.5: cio' che
                 non e' nel testo reso non esiste)
    applicato    il piano scritto per quella richiesta produce `traits.applied`
                 non vuoto, oppure un effetto in programma
    geometria    i limiti del modello cambiano, e di quanto
    visivo       la misura che la richiesta nominava si muove nel verso giusto
                 (la testa piu' grande della testa, non del modello intero)

Il planner usato e' un fornitore deterministico che **legge il prompt** e
scrive il trait: cosi' la misura si riproduce senza rete e senza chiavi. Quello
che questa parte dimostra e' che la richiesta e' esprimibile e cablata fino
alla geometria; che un modello di frontiera scelga davvero quel trait e' una
misura diversa, e va fatta con una chiave vera.
"""
from __future__ import annotations

import json
import statistics
import sys
import tempfile
import time
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RADICE))
sys.path.insert(0, str(RADICE / "tests"))

import numpy as np                                               # noqa: E402

from app.ai.provider import OfflineProvider                      # noqa: E402
from app.build.visual import analyse                             # noqa: E402
from app.core.frame import POLICY_DIAGNOSE, POLICY_STRICT, compare  # noqa: E402
from app.core.planner.planner import MockPlanner                 # noqa: E402
from app.core.registry import load                               # noqa: E402
from app.core.session import Options, Session                     # noqa: E402

PLUGIN = RADICE / "app" / "plugins"
PROBE = RADICE / "tests" / "plugins" / "variabilita"

# Le sei richieste della milestone, con il piano che le esprime. Il piano e'
# scritto a mano qui perche' questa parte misura il **motore**, non il modello:
# la riga «trait» e' esattamente quella che il vocabolario offre per quel prompt.
RICHIESTE = [
    {"prompt": "a humanoid with a huge head",
     "ref": "humanoid_anatomical:body",
     "traits": [{"trait": "head_scale", "value": 2.4}],
     "misura": ("role", "head", "max")},
    {"prompt": "a humanoid with short legs",
     "ref": "humanoid_anatomical:body",
     "traits": [{"trait": "limb_length", "value": 0.55}],
     "misura": ("role", "leg", "max")},
    {"prompt": "a humanoid with huge hands",
     "ref": "humanoid_anatomical:body",
     "traits": [{"trait": "hand_scale", "value": 2.2}],
     "misura": ("role", "hand", "max")},
    {"prompt": "a very wide cartoon creature",
     "ref": "fox_stylized:body",
     "traits": [{"trait": "width", "value": 1.8}],
     "misura": ("model", "", "x")},
    {"prompt": "a long curved tail",
     "ref": "fish:tail",
     "traits": [{"trait": "length", "value": 1.9}],
     "effects": [{"type": "fx:bend", "scope": "part:subject", "amount": 0.8}],
     "misura": ("model", "", "max")},
    {"prompt": "a tall slender slightly curved house",
     "ref": "architecture:house",
     "traits": [{"trait": "length", "value": 1.6}, {"trait": "width", "value": 0.7}],
     "effects": [{"type": "fx:bend", "scope": "part:subject", "amount": 0.2}],
     "misura": ("model", "", "y")},
]


def cronometra(quante: int, fai) -> tuple[float, float]:
    tempi = []
    for _ in range(quante):
        inizio = time.perf_counter()
        fai()
        tempi.append((time.perf_counter() - inizio) * 1000.0)
    return statistics.median(tempi), max(tempi)


def sessione(registry) -> Session:
    return Session(registry=registry, provider=OfflineProvider(),
                   planner=MockPlanner())


def piano(ref, *, traits=None, effects=None, params=None, detail=2):
    root = {"id": "subject", "ref": ref}
    if params:
        root["params"] = params
    if effects:
        root["effects"] = effects
    return {"version": "1.3", "style": "low_poly", "detail_level": detail,
            "seed": 7, "traits": traits or [], "root": root}


def misura(result, kind, value, asse):
    """La misura che la richiesta nominava, non quella del modello intero."""
    if kind == "model":
        limiti = result.scene().bounds()
        estensione = limiti[1] - limiti[0]
    else:
        nodi = [n for n in result.resolved.walk() if n.component.role == value]
        costruiti = [result.build.nodes.get(n.id) for n in nodi]
        mesh = [c.mesh for c in costruiti
                if c is not None and c.mesh is not None and len(c.mesh.vertices)]
        if not mesh:
            return 0.0
        return float(sum(np.max(m.extents) for m in mesh))
    if asse == "max":
        return float(np.max(estensione))
    return float(estensione["xyz".index(asse)])


# --------------------------------------------------------------------------- #
# Parte 1: prestazioni
# --------------------------------------------------------------------------- #
def prestazioni(quante: int) -> dict:
    from data_plugin_fixtures import write_variable_plugin

    cartella = write_variable_plugin(Path(tempfile.mkdtemp()))
    registry = load([PLUGIN, PROBE, cartella]).freeze()
    s = sessione(registry)
    fuori: dict[str, dict] = {}

    def voce(nome, fai):
        mediana, peggiore = cronometra(quante, fai)
        fuori[nome] = {"median_ms": round(mediana, 3), "worst_ms": round(peggiore, 3)}

    voce("riferimento: build senza niente",
         lambda: s.build(piano("mesh_variable:head")))
    voce("parametro transform (scala su mesh)",
         lambda: s.build(piano("mesh_variable:head", params={"width": 1.7})))
    voce("parametro effect-backed (fx:bend da curvature)",
         lambda: s.build(piano("mesh_variable:tail", params={"curvature": 0.8})))
    voce("trait semantico su mesh-backed",
         lambda: s.build(piano("mesh_variable:head",
                               traits=[{"trait": "std:width", "value": 1.8}])))
    voce("trait semantico su procedurale",
         lambda: s.build(piano("procedural_probe:head",
                               traits=[{"trait": "std:width", "value": 1.8}])))
    voce("trait semantico su albero misto",
         lambda: s.build({**piano("mesh_variable:host",
                                  traits=[{"trait": "std:width", "value": 1.8,
                                            "scope": "subtree"}]),
                          "root": {"id": "subject", "ref": "mesh_variable:host",
                                   "children": [
                                       {"id": "proc", "ref": "procedural_probe:head",
                                        "at": {"capability": "head_mount"},
                                        "insert": 0.0}]}}))
    voce("trait sulla libreria procedurale intera (37 nodi)",
         lambda: s.build(piano("humanoid_anatomical:body",
                               traits=[{"trait": "std:part_scale", "value": 1.6}])))
    voce("riferimento: la stessa libreria senza trait",
         lambda: s.build(piano("humanoid_anatomical:body")))

    chimera = {"version": "1.3", "style": "low_poly", "detail_level": 2, "seed": 7,
               "root": {"id": "subject", "ref": "fish:fish_body", "children": [
                   {"id": "head", "ref": "creature:dragon_head",
                    "at": {"capability": "head_mount"}},
                   {"id": "wing_l", "ref": "fantasy:wing",
                    "at": {"capability": "limb_mount", "side": "l"}},
                   {"id": "wing_r", "ref": "fantasy:wing",
                    "at": {"capability": "limb_mount", "side": "r"}}]}}
    voce("validazione dei frame (chimera, 3 innesti discordanti)",
         lambda: s.build(chimera, Options(frame_policy=POLICY_DIAGNOSE)))
    voce("validazione dei frame, politica strict",
         lambda: s.build(chimera, Options(frame_policy=POLICY_STRICT)))
    voce("confronto di due frame, da solo (10 000 volte)",
         lambda: [compare(registry.component("fish:fish_body"),
                          registry.component("creature:dragon_head"))
                  for _ in range(10000)])
    return fuori


# --------------------------------------------------------------------------- #
# Parte 2: le sei richieste
# --------------------------------------------------------------------------- #
def richieste() -> list[dict]:
    registry = load([PLUGIN]).freeze()
    s = sessione(registry)
    fuori = []
    for caso in RICHIESTE:
        vocabolario = s.vocabulary("low_poly", prompt=caso["prompt"])
        offerti = {t.id for t in vocabolario.traits}
        voluti = set()
        for richiesta in caso["traits"]:
            spec = registry.trait(richiesta["trait"])
            voluti.add(spec.id if spec is not None else richiesta["trait"])
        reso = vocabolario.to_text()

        base = s.build(piano(caso["ref"]))
        dopo = s.build(piano(caso["ref"], traits=caso["traits"],
                             effects=caso.get("effects")))
        kind, value, asse = caso["misura"]
        prima_m = misura(base, kind, value, asse)
        dopo_m = misura(dopo, kind, value, asse)
        limiti_prima = base.scene().bounds()
        limiti_dopo = dopo.scene().bounds()

        fuori.append({
            "prompt": caso["prompt"],
            "intento": {
                "trait richiesto": sorted(voluti),
                "nel vocabolario": sorted(voluti & offerti),
                "nel testo reso": all(t in reso for t in voluti),
            },
            "applicato": {
                "traits": sorted({a["trait"] for a in dopo.traits.applied}),
                "canali": len(dopo.traits.applied),
                "effetti in programma": [e.id for e in dopo.effects.planned],
            },
            "geometria": {
                "triangoli": [base.triangles, dopo.triangles],
                "limiti prima": np.round(limiti_prima, 3).tolist(),
                "limiti dopo": np.round(limiti_dopo, 3).tolist(),
                "cambiata": not bool(np.allclose(limiti_prima, limiti_dopo)),
            },
            "visivo": {
                "misura": "%s %s (%s)" % (kind, value or "-", asse),
                "prima": round(prima_m, 4), "dopo": round(dopo_m, 4),
                "rapporto": round(dopo_m / prima_m, 3) if prima_m else None,
                # le diagnostiche visive che c'erano, sulla scena vera: non un
                # giudizio, due numeri confrontabili prima e dopo
                "riempimento": [round(analyse(base.scene()).blobbiness, 3),
                                 round(analyse(dopo.scene()).blobbiness, 3)],
                "proporzioni": [
                    [round(v, 3) for v in analyse(base.scene()).aspect],
                    [round(v, 3) for v in analyse(dopo.scene()).aspect]],
            },
            "ok": dopo.ok,
            "report ok": dopo.report.ok,
        })
    return fuori


def stampa(dati: dict) -> None:
    print("\n== prestazioni (mediana / peggiore, ms) ==")
    for nome, valori in dati["prestazioni"].items():
        print("  %-52s %8.3f %8.3f" % (nome, valori["median_ms"],
                                        valori["worst_ms"]))
    print("\n== le sei richieste ==")
    for caso in dati["richieste"]:
        print("\n  %s" % caso["prompt"])
        print("    intento    : richiesto %s, offerto %s, nel testo %s"
              % (caso["intento"]["trait richiesto"],
                 caso["intento"]["nel vocabolario"],
                 caso["intento"]["nel testo reso"]))
        print("    applicato  : %s su %d canali, effetti %s"
              % (caso["applicato"]["traits"], caso["applicato"]["canali"],
                 caso["applicato"]["effetti in programma"] or "nessuno"))
        print("    geometria  : cambiata=%s triangoli %s"
              % (caso["geometria"]["cambiata"], caso["geometria"]["triangoli"]))
        print("    visivo     : %s  %.4f -> %.4f  (x%s)"
              % (caso["visivo"]["misura"], caso["visivo"]["prima"],
                 caso["visivo"]["dopo"], caso["visivo"]["rapporto"]))
        print("    silhouette : riempimento %s, proporzioni %s -> %s"
              % (caso["visivo"]["riempimento"],
                 caso["visivo"]["proporzioni"][0],
                 caso["visivo"]["proporzioni"][1]))


def main(argv: list[str]) -> int:
    quante = 5
    destinazione = None
    resto = [a for a in argv if not a.startswith("--")]
    if resto:
        quante = max(1, int(resto[0]))
    if "--json" in argv:
        destinazione = Path(argv[argv.index("--json") + 1])
    dati = {"ripetizioni": quante, "prestazioni": prestazioni(quante),
            "richieste": richieste()}
    stampa(dati)
    if destinazione is not None:
        destinazione.write_text(json.dumps(dati, indent=2, ensure_ascii=False),
                                encoding="utf-8")
        print("\nscritto %s" % destinazione)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
