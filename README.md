# 3DGen — motore universale di composizione

Descrivi un oggetto a parole, ottieni un modello 3D low poly fatto di parti
vere, modificane il piano, esportalo.

```
python main.py                                       interfaccia desktop
python cli.py "una persona con la testa di rana"     da riga di comando
python cli.py "un albero con un nido" --out albero.glb --png
python cli.py "una casa" --detail 3                  piu' parti, non piu' triangoli
python cli.py "una casa" --plan                      il piano JSON che l'LLM ha scritto
python cli.py "una casa" --explain                   perche' e' stato scelto cio' che c'e'
python cli.py "una spada" --save "Lama buona"        salva nella libreria
python cli.py --library                              elenca la libreria
python cli.py --find "qualcosa con le ali"           cerca per significato
python cli.py --load <id>                            ricarica un asset salvato
python cli.py --providers                            stato dei fornitori AI
python -m pytest -q                                  895 test
```

---

## Come funziona

```
USER PROMPT
    ↓
SESSION              l'unica porta: UI, riga di comando, test
    ↓
LLM PLANNER          una chiamata, al massimo una correzione
    ↓
COMPOSITION GRAPH    JSON: quali pezzi, appesi come, con che parametri
    ↓
REGISTRY             che cosa e' installato
    ↓
RESOLVER             che cosa e' compatibile con che cosa
    ↓
EFFECT PIPELINE      che cosa cambia, e in che ordine
    ↓
BUILDER              dove finisce ogni vertice
    ↓
REAL 3D MODEL
```

**Il core non sa che cosa sia una casa.** Non sa cosa siano un umanoide, un
pesce o un pianeta, e non deve saperlo. Sa che un componente **fornisce** certe
capability e ne **accetta** altre, e questo gli basta per mettere insieme pezzi
scritti da persone diverse che non si sono parlate.

L'LLM non produce geometria: produce un **piano**. Sceglie e combina cio' che
esiste nel registry, e non inventa un vertice.

---

## Che cosa c'e' dentro

**12 plugin, 44 componenti, 19 materiali, 8 effetti, 23 capability.**

| plugin | cosa porta |
|---|---|
| `humanoid` | corpo, torso, bacino, petto, collo, testa, occhi, naso, bocca, orecchie, capelli, braccia, gambe, mani, piedi |
| `creature` | testa di rana, testa di drago, occhio sporgente |
| `fish` | corpo, coda, pinna |
| `nature` | albero, chioma, nido, uccello |
| `fantasy` | ala, cristallo |
| `architecture` | casa, tetto, porta, finestra |
| `space` | pianeta |
| `weapon` | spada |
| `accessories` | mascherina, casco, visiera, piercing |
| `robot` | testa (solo per lo stile realistico: prova il rifiuto) |
| `primitives` | blocco, tubo, lo stile `low_poly`, i materiali di base |
| `fx` | lanky, chunky, bend, perspective_exaggeration, rotate, align, offset, mirror |

Nessuno di questi e' privilegiato. Aggiungerne uno non richiede una riga di
modifica al core: si copia una cartella e il vocabolario cambia da solo — anche
quello che il planner vede. Vedi **[PLUGIN-AUTORI.md](PLUGIN-AUTORI.md)**.

---

## Le idee che reggono tutto

**Il contratto e' cio' che una parte restituisce, non come e' fatta.** Un
componente e' una funzione che da' geometria e punti di attacco. Puo' usare il
kernel poligonale, una mesh importata o qualcosa che ancora non esiste.

**`provides` e `mounts` non sono la stessa cosa.** Un figlio *fornisce*
`head_mount`; un padre lo *accetta*. Invertirle vorrebbe dire che un torso "e'"
una testa.

**Il piano vince sulla dichiarazione, ma non la cancella.** Un componente
dichiara di che cosa e' fatto; il piano puo' sostituirne una parte, e
`on: "testa/naso"` permette di appendere qualcosa a una parte che il piano non
ha nominato — senza rimetterla e senza duplicarla.

**Un effetto non crea componenti.** Cambia parametri (prima del build),
vertici (dopo), o la posa (per ultimo). Sono sei stadi, e l'ordine e' il
contratto.

**La qualita' e' deterministica.** Planarita' misurata sulla geometria
*disegnata*, budget di triangoli, sagoma, giunti, compenetrazione: numeri,
sempre gli stessi. Nessun modello linguistico giudica un modello.

**Le descrizioni dei plugin sono dati.** Arrivano al planner ridotte a una riga
fra virgolette, senza delimitatori e senza marcatori di ruolo: un plugin
installato da qualcun altro non deve poter dare ordini al tuo planner.

---

## Salvare il lavoro

Un progetto `.my3d` contiene i **piani**, non le mesh: qualche kilobyte invece
di qualche megabyte, e il modello si rigenera — a un altro livello di dettaglio,
con un parametro cambiato, con un plugin aggiornato. Dentro c'e' anche quali
plugin e quali versioni erano installati, perche' un modello che si rigenera
diverso deve poterlo spiegare.

```python
from app.core.session import Options, Session

sessione = Session()
risultato = sessione.generate("una casa con un pianeta enorme sopra")

print(risultato.describe())
print("\n".join(risultato.explain()))     # perche' e' stato scelto cio' che c'e'
sessione.export("casa.glb")
sessione.save_project("lavoro.my3d")
```

---

## Senza rete

Senza una chiave configurata il sistema **genera lo stesso**: un planner locale
sceglie i componenti per corrispondenza fra le parole della richiesta e i nomi,
i tag e le descrizioni del vocabolario. E' peggio di un modello vero, ed e'
scritto nel risultato (`planner = "mock"`), perche' un ripiego silenzioso e'
peggio di un errore.

Le chiavi si mettono in `.env` (vedi `.env.example`). I fornitori sono
intercambiabili: il core non nomina nessuna API.

---

## Documenti

- **[PLUGIN-AUTORI.md](PLUGIN-AUTORI.md)** — scrivere un plugin senza leggere
  il core.
- **[ARCHITETTURA-CORE.md](ARCHITETTURA-CORE.md)** — perche' il core e' fatto
  cosi', e che cosa e' stato tolto per arrivarci.
- **[ARCHITETTURA-PLUGIN.md](ARCHITETTURA-PLUGIN.md)** — l'analisi da cui e'
  partito il sistema a plugin.
- **[TODO.md](TODO.md)** — che cosa manca.

---

## Prestazioni

Una generazione completa, senza rete, su una macchina normale:

| passo | mediana |
|---|---|
| caricamento dei plugin | 16 ms |
| vocabolario per il planner | 3 ms |
| planner locale | 1 ms |
| resolver | 0,2 ms |
| effetti | 0,1 ms |
| builder | 3–10 ms |
| controllo di qualita' | 1–3 ms |
| **totale** | **6–13 ms** |

`python tools/benchmark.py` per rimisurarle.
