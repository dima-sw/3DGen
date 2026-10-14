# V2-RESULTS — Degradazione semantica spiegabile

Milestone V2 di `VISION-GAP.md`, implementata il **14 ottobre 2026**.
Branch `v1-semantic-index`, partenza `a05c0d4` (V1).

**Esito: completa.** I dieci criteri della Definition of Done sono soddisfatti e
misurati. Con un LLM reale gli otto prompt del `PRODUCT-AUDIT` passano da **6/8 a
7/8**, con **zero `413`**; offline `jeep` smette di essere un casco e diventa
un'auto. L'ottavo fallimento non è più il ramo `concept`.

---

## 1. Decisioni architetturali

### 1.1 Una sola fase di risoluzione, non due pipeline

Prima, `_risolvi_concept` veniva chiamato da `_compose`, cioè solo da
`generate()`. Un piano `concept` passato a `build()` moriva con
`un piano concept deve essere materializzato dal backend`.

La materializzazione è stata spostata **dentro `_verifica`**, che è il punto in
cui passano già `generate()`, `build()`, il planner reale, il `MockPlanner` e un
piano scritto a mano. Nessuna seconda pipeline: una fase sola, spostata di un
livello.

```python
def _verifica(self, piano, risultato, opzioni, *, semantic_source="local"):
    ...
    piano = self._risolvi_concept(piano, risultato, opzioni,
                                  semantic_source=semantic_source)
```

Conseguenza verificata: `build(piano_con_concept)` e `generate()` producono la
stessa risoluzione e lo stesso numero di triangoli.

### 1.2 La gerarchia semantica si ricava dai dati, non da un catalogo

Il pezzo che evita il catalogo parallelo è una regola **strutturale**:

```python
def subject_capabilities(registry) -> frozenset[str]:
    """Fornita da qualcuno e accettata da nessuno: e' un soggetto intero."""
    return frozenset(fornite - accettate)
```

Sulla libreria attuale produce `{animal, arma, building, nest_mount, solid,
vehicle}` senza che nessun nome sia scritto nel core. Un plugin che domani porti
`spacecraft` entra nell'elenco da solo — c'è un test che lo verifica.

È la regola che fa vincere l'auto sulla ruota: per «jeep» la ruota ha punteggio
semantico più alto (0.551) dell'auto (0.588 solo dopo l'espansione dei
sinonimi), ma `vehicle` è una capability soggetto e `wheel_mount` no.

L'ordinamento dei candidati è una **chiave a gradini**, non una somma pesata:

```python
fuori.sort(key=lambda voce: (not voce[2],            # prima i soggetti
                             not voce[0].mounts,      # poi chi ospita figli
                             -round(voce[1], 6),      # poi il punteggio
                             voce[0].id))             # poi l'id
```

Deterministico, e senza numeri magici da tarare.

### 1.3 La scala, per intero

```text
1. id esatto                       fox_stylized:fox        → direct implementation
2. nome del componente             fox                     → declared component name
3. archetipi e binding             (quando esistono)       → exact / ancestor / specialization
4. approssimazione semantica       jeep                    → semantic subject proxy
5. radice scritta nel piano        (se il concetto cede)   → root supplied by the plan
6. niente di adatto                → diagnosi esplicita, nessuna geometria
```

I gradini 3 e 4 **non si escludono**: se il catalogo degli archetipi non copre
il concetto, o se nessun binding regge, si scende al gradino semantico invece di
fallire. `ArchetypeSpec` e `ImplementationBinding` restano come override
dell'autore — nessun binding nuovo è stato aggiunto in V2.

### 1.4 Un concetto sbagliato non distrugge una radice valida

Due regole, non una:

* se il concetto **non si risolve** e il piano porta una radice, si usa la
  radice e le diagnosi scendono ad avviso;
* se il concetto si risolve **per approssimazione** e il piano porta una radice,
  vince ancora la radice.

La seconda è la meno ovvia ed è venuta da un test fallito: un `concept` con un
archetipo allucinato veniva normalizzato in `animal`, sceglieva una volpe, e la
volpe sostituiva una `architecture:house` che il planner aveva scritto
esplicitamente. Fra una scelta del planner e una supposizione del risolutore si
tiene la scelta. Un concetto **esatto** invece comanda, perché lì non si sta
indovinando niente.

### 1.5 Normalizzazione prudente, senza casi speciali

```python
def normalize_reference(raw, lookup, ambiguous=None) -> tuple[str, str]:
    """Si tolgono i segmenti iniziali uno alla volta e ci si ferma al primo
    resto che identifica una cosa sola."""
```

`registered:archetype_metadata:felid` → `archetype_metadata:felid`. La stringa
`registered:` non compare da nessuna parte nel codice: la regola è generica, si
ferma su un alias ambiguo, e ogni normalizzazione emette
`CONCEPT_ID_NORMALIZED`. Un id che non identifica niente resta non risolto.

### 1.6 La rosa in ordine di rilevanza

Difetto trovato misurando, non previsto: offline `jeep` continuava a dare
`accessories:helmet`. Causa — la rosa veniva consegnata **ordinata per id**, e un
planner che a pari punteggio prende il primo prendeva il primo in ordine
alfabetico.

Due righe, in due punti:

* `shortlist()` restituisce i componenti nell'ordine in cui li ha scelti
  (rilevanza, poi chiusura) invece che ordinati per id;
* `MockPlanner` rompe la parità con la posizione nel vocabolario invece che con
  l'id.

Senza questo, un prompt che non contiene nessuna parola del vocabolario
sceglieva per alfabeto. È il motivo per cui «una jeep» era un casco.

---

## 2. File modificati

| File | Che cosa |
| --- | --- |
| `app/core/archetypes.py` | `subject_capabilities`, `normalize_reference`, `ConceptResolver.index/by_name/candidates/_approximate`, costanti `MATCH_*`, campi `match`/`confidence`/`strategy`, `describe()`, `approximate` |
| `app/core/session.py` | `_verifica` diventa la fase comune; scala di ripiego in `_risolvi_concept`; `GenerationResult.degradation()` e `explain()` |
| `app/core/planner/retrieval.py` | la rosa esce in ordine di rilevanza |
| `app/core/planner/vocabulary.py` | con una rosa, l'ordine è informazione e si conserva |
| `app/core/planner/planner.py` | `MockPlanner` rompe la parità con la rilevanza, non con l'id |
| `tests/test_api_freeze.py` | elenco congelato aggiornato (additivo) |
| `tests/test_degradation.py` | **nuovo**, 33 test |

Nessun file nuovo nel core: la degradazione vive dove viveva già la risoluzione
dei concetti. Nessun secondo motore semantico: `ConceptResolver.index()` usa
`build_index` di V1.

I valori di `match` già scritti nei progetti salvati (`direct implementation`,
`exact`, `ancestor/body-plan proxy`,
`descendant/specialization implementation`) sono rimasti **identici parola per
parola**; i tre nuovi seguono la stessa lingua.

---

## 3. Comportamento prima e dopo

| Caso | V1 | V2 |
| --- | --- | --- |
| `build()` con un piano `concept` | `CONCEPT_REQUIRES_RESOLUTION`, 0 triangoli | risolto come in `generate()` |
| `concept` sconosciuto | `CONCEPT_UNKNOWN` fatale, 0 triangoli | avviso + approssimazione |
| `concept` allucinato + root valido | il concept uccideva la generazione | la radice sopravvive |
| id con prefisso inventato | `Archetype non disponibile` fatale | normalizzato e dichiarato |
| nessun binding compatibile | `IMPLEMENTATION_NOT_FOUND` fatale | avviso + approssimazione |
| `jeep` offline | `accessories:helmet`, 56 tris | `vehicle_stylized:car`, 228 tris |
| approssimazione | invisibile | `degradation()`, `explain()`, `.my3d` |

### 3.1 La degradazione, misurata

```text
jeep         -> vehicle_stylized:car       semantic subject proxy   0.588
suv          -> vehicle_stylized:car       semantic subject proxy   0.588
camion       -> vehicle_stylized:car       semantic subject proxy   0.588
casa         -> architecture:house         semantic subject proxy   0.636
volpe        -> fox_stylized:fox           semantic subject proxy   0.197
fox          -> fox_stylized:fox           direct implementation    —
albero       -> tree_stylized:tree         exact                    —
drago        -> creature:dragon_head       weak semantic proxy      0.247
pesce        -> fish:fish_body             weak semantic proxy      0.666
robot        -> NIENTE                     (nessun candidato)
sottomarino  -> NIENTE                     (nessun candidato)
```

`robot` e `sottomarino` non hanno risposta perché la libreria non contiene
niente di correlato: `robot:head` esiste ma è dichiarato per lo stile
realistico. **Dichiarare che non c'è niente di adatto è il comportamento
voluto**, non un difetto da mascherare con un ripiego generico.

### 3.2 La spiegazione

`GenerationResult.degradation()` — accessibile programmaticamente, non solo nei
log, e riusa `ConceptCoverage` invece di una seconda struttura:

```text
richiesto: 'jeep'
implementazione esatta: non installata
scelto per approssimazione: vehicle_stylized:car
tipo di corrispondenza: semantic subject proxy
punteggio semantico: 0.588
gradini provati: id esatto -> nome del componente -> archetipi e binding -> approssimazione semantica
```

Le stesse righe aprono `explain()`. Un'implementazione esatta non produce
nessuna riga: non è un'approssimazione e non merita una spiegazione.

### 3.3 La persistenza

`CompositionGraph.to_dict()` esportava già `concept_resolution`, e `_versione()`
salva il grafo: la spiegazione sopravvive al `.my3d` senza cambiare il formato.
Verificato con un salva-e-riapri: `requested_concept`, root scelto, `match` e
`approximate` tornano identici, e `describe()` funziona sul progetto riaperto.

Retrocompatibilità: `ConceptResolutionPlan.from_dict` accetta un progetto
anteriore a V2, dove `match` è `""` e `strategy` è vuota. C'è un test.

---

## 4. Gli 8 prompt del PRODUCT-AUDIT

### 4.1 Con LLM reale

| # | Prompt | V1 | V2 |
| --- | --- | --- | --- |
| 1 | volpe | ✅ 412, 3,0 s, groq | ✅ 412, **2,2 s**, groq, fo 0 |
| 2 | umanoide | ✅ 264, 170,0 s | ✅ 80, **20,8 s**, gemini, fo 1 |
| 3 | robot 4 braccia | ❌ 0 | ❌ 0, groq, fo 0 |
| 4 | jeep 6 ruote | ✅ 228, 48,8 s | ✅ 228, 42,0 s, gemini, fo 1 |
| 5 | pesce+umano | ✅ 412, 2,5 s | ✅ 198, 19,7 s, groq, fo 0 |
| 6 | casa | ✅ 32, 13,5 s | ✅ 32, 30,5 s, gemini, fo 1 |
| 7 | drago | ❌ 0 | ✅ **256**, 37,5 s, cloudflare, fo 3 |
| 8 | albero | ✅ 400, 32,5 s | ✅ 400, **2,6 s**, groq, fo 0 |

```text
generazioni riuscite    6/8  →  7/8
413 payload_too_large   0/8  →  0/8
failover totali          17  →  6
mediana                14,5s →  20,3s
```

**La mediana è peggiorata e non è colpa di V2.** Il costo della degradazione
misurato è **0,66 ms per chiamata**; i failover totali sono scesi da 17 a 6. La
differenza è varianza di rete e limiti di frequenza dei fornitori gratuiti:
nello stesso run il prompt 1 scende da 3,0 a 2,2 s e l'8 da 32,5 a 2,6 s, mentre
il 6 sale da 13,5 a 30,5 s. Un singolo giro di otto richieste su fornitori
free-tier non è un campione da cui dedurre una regressione di latenza.

### 4.2 Il prompt 7, che V2 ha sbloccato

V1: `concept.archetypes = ["registered:archetype_metadata:animal"]` →
`Archetype non disponibile` → `concept non registrato` → 0 triangoli.

V2: l'id viene normalizzato, e il modello ha comunque scritto un `root` valido
(`fish:fish_body` + `creature:dragon_head` + ali) che adesso sopravvive. 256
triangoli.

### 4.3 Il prompt 3, che resta rosso — e perché non è più il concept

```json
{"concept": {"requested": "robot with four arms",
             "archetypes": ["archetype_metadata:quadruped"],
             "adaptations": [{"trait": "instance_count", "value": 4}]},
 "root": {"id": "fox", "ref": "fox_stylized:fox", ...}}
```

```text
trait non disponibile: 'instance_count'   [traits[1]]
   alternative: botany:leafiness, std:body_mass
```

Il concetto **si risolve**. La radice **sopravvive**. La generazione muore su un
`trait` inventato dal modello, che `validate_plan` rifiuta come errore fatale.

È lo stesso difetto di forma del concept — un campo facoltativo allucinato che
uccide un piano per il resto valido — ma è una decisione diversa, fissata da un
test esistente che pretende `graph is None` per un trait sconosciuto
(`tests/test_traits.py:299`). Cambiarla qui avrebbe voluto dire indebolire un
test per far passare un benchmark. È registrata come debito, con la forma esatta
della correzione, al §8.

### 4.4 Offline (MockPlanner), 8/8 prima e dopo

| # | V1 | V2 | Radice scelta |
| --- | ---: | ---: | --- |
| 1 volpe | 412 | 412 | `fox_stylized:fox` |
| 2 umanoide | 264 | 264 | `humanoid_anatomical:head` |
| 3 robot | 12 | 32 | `architecture:house` |
| 4 jeep | 56 | **228** | `vehicle_stylized:car` |
| 5 pesce+umano | 414 | 414 | `humanoid_anatomical:body` |
| 6 casa | 32 | 32 | `architecture:house` |
| 7 drago | 82 | 82 | `creature:dragon_head` |
| 8 albero | 50 | 50 | `fantasy:wing` |

Il 4 è il caso che V2 esisteva per sistemare. Il 3 e l'8 restano semanticamente
sbagliati: il planner locale sceglie per corrispondenza di parole, «fantasy»
colpisce il plugin `fantasy` prima di `tree_stylized`, e un robot in stile
`low_poly` nella libreria non c'è. Nessuno dei due passa dalla degradazione —
il `MockPlanner` scrive una radice, non un concetto.

### 4.5 Carico del vocabolario: invariato

| # | V1 | V2 |
| --- | ---: | ---: |
| 1 | ~3 474 | ~3 474 |
| 2 | ~3 480 | ~3 480 |
| 3 | ~1 469 | ~1 469 |
| 4 | ~2 572 | ~2 572 |
| 5 | ~3 788 | ~3 788 |
| 6 | ~2 318 | ~2 318 |
| 7 | ~2 753 | ~2 753 |
| 8 | ~3 396 | ~3 396 |

Nessuna regressione: V2 non tocca ciò che si manda al modello, solo come si
interpreta la risposta.

---

## 5. Test

**33 test nuovi** in `tests/test_degradation.py`; suite completa **1287 passed**
(erano 1254).

| Area | Test |
| --- | --- |
| capability soggetto | 2 — ricavate dai dati; una capability nuova entra da sola |
| normalizzazione id | 4 — prefisso inventato, id corretto, id inesistente, diagnosi |
| **B** esatto vince | 3 — id, nome, concetto esatto contro radice del piano |
| **C** antenato/soggetto | 4 — degrada a un veicolo, mai a un casco, soggetto prima del pezzo, deterministico |
| **A** radice preservata | 3 — concetto allucinato, concetto approssimato, concetto solo |
| **E** niente di adatto | 2 — lo dice invece di inventare |
| **D** composizione | 2 — due famiglie nella rosa, il planner le compone |
| **F** `generate` = `build` | 2 — stessa risoluzione, un piano concept si costruisce |
| spiegazione | 4 — programmatica, in `explain()`, vuota se esatta, `ConceptCoverage` riusato |
| persistenza | 2 — sopravvive al `.my3d`, un progetto vecchio si riapre |
| **crescita libreria** | 5 — prima non c'è, installare basta, sinonimi dichiarati, soggetto automatico, senza il plugin sparisce |

L'ultimo blocco è la prova del §12: un `mare:submarine` installato con solo id,
descrizione, tag, capability e i sinonimi del suo plugin diventa candidato
immediatamente. Il test verifica esplicitamente
`registro.implementation_bindings() == []` e `registro.archetypes() == []`:
nessun binding scritto a mano, nessuna modifica al core.

Tre test nuovi hanno fallito scrivendoli, e tutti e tre hanno trovato qualcosa:
la precedenza concetto/radice (§1.4), la rosa ordinata per id (§1.6) e una mia
assunzione sbagliata sui punteggi, corretta nel test.

Nessun test esistente indebolito. `tests/test_api_freeze.py` è aggiornato con i
campi e i metodi nuovi, che è il meccanismo che quel file documenta.

---

## 6. Definition of Done

| # | Criterio | Esito |
| --- | --- | --- |
| 1 | suite verde | ✅ 1287 passed |
| 2 | un concept errato non distrugge un root valido | ✅ 3 test, prompt 7 sbloccato |
| 3 | l'exact match continua a vincere | ✅ 3 test |
| 4 | i concept mancanti degradano verso alternative correlate | ✅ `jeep`/`suv`/`camion` → auto |
| 5 | la degradazione è spiegata programmaticamente | ✅ `degradation()`, `describe()` |
| 6 | la spiegazione è salvata nel progetto | ✅ round-trip `.my3d` |
| 7 | `generate()` e `build()` non differiscono | ✅ test F |
| 8 | nessuna logica di dominio nel core | ✅ regola strutturale, zero nomi |
| 9 | installare un componente migliora la degradazione senza binding | ✅ 5 test |
| 10 | gli 8 benchmark non peggiorano | ✅ 6/8 → 7/8, offline 8/8 → 8/8 |

---

## 7. Regressioni

Nessuna rossa. Tre cose da dire comunque:

1. **La mediana con LLM reale sale da 14,5 a 20,3 s.** Non è V2 (0,66 ms per
   degradazione, failover scesi da 17 a 6): è varianza dei fornitori gratuiti.
   Resta da riconfermare con più giri.
2. **Prompt 5 da 412 a 198 triangoli.** Il modello ha scritto un piano più
   piccolo; entrambi compongono pesce + umanoide, nessuno dei due è sbagliato.
3. **Prompt 2 da 264 a 80 triangoli**, stessa ragione: provider diverso, piano
   diverso. Nessuno dei due soddisfa «testa enorme, gambe corte, mani grandi» —
   quel vocabolario non esiste ancora (è M4 nella roadmap del PRODUCT-AUDIT).

---

## 8. Debiti rimasti a V3

* **Un trait allucinato uccide ancora un piano valido** (prompt 3). La
  correzione è della stessa forma di V2 §1.4: un `trait` sconosciuto diventa un
  avviso e viene ignorato, invece di essere un errore fatale. Richiede di
  cambiare `tests/test_traits.py:299`, che oggi pretende `graph is None` — è una
  decisione deliberata, non un adeguamento, e per questo non è stata presa
  dentro V2. Lo stesso vale per uno `structural_trait` o un `effect` inventato.
* **Il gradino «composizione» è passivo.** V2 fornisce i candidati e lascia
  comporre al planner, come da §5. Quando nessun singolo componente basta e il
  planner non compone, non c'è nessuno che costruisca la combinazione. Potrebbe
  non servire mai.
* **`ProfileSpec` resta a un solo profilo installato.** V2 non lo ha toccato;
  `VISION-GAP.md` lo considera sovradimensionato finché resta uno.
* **I trait strutturali restano legati a un percorso letterale** — è V3 di
  `VISION-GAP.md`, non toccato qui.
* **La soglia `MIN_CONFIDENCE = 0.08` è tarata su una libreria da 97
  componenti.** Con migliaia, va verificata: troppo bassa produce omonimie,
  troppo alta rifiuta approssimazioni legittime.
* **`robot` non ha risposta** perché la libreria non ha un robot `low_poly`.
  È il comportamento corretto; la soluzione è un componente, non un algoritmo.

---

## 9. Riprodurre le misure

```bash
python -m pytest -q tests/test_degradation.py
python audit-images/run_audit.py offline audit-images/v2
python audit-images/run_audit.py llm audit-images/v2 groq     # richiede rete
python audit-images/v1_measure.py audit-images/v2_vocabulary.json
```

Artefatti in `audit-images/` (non versionati):

```text
v2/metrics_llm.json       gli 8 prompt con LLM reale
v2/metrics_offline.json   gli 8 prompt offline
v2_vocabulary.json        carico del vocabolario dopo V2
v2_degradation.json       la tabella della degradazione
v2/*.png                  3 angolazioni per generazione riuscita
```

Il confronto è con `audit-images/v1/` e `audit-images/v1_vocabulary.json`.
