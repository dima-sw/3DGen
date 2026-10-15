# V7-RESULTS — Insegnare un drago, e poi costruirlo senza AI

Milestone V7, chiusa il **15 ottobre 2026**. Branch `v5-semantic-variability`,
partenza dichiarata e verificata prima di toccare qualunque cosa: V6 completa,
**1761 test verdi**, authoring service in `app/authoring/` indipendente da Qt,
Component Lab funzionante su procedurale e mesh-backed, variant recipe
disponibile, plugin data-only generabile e installabile senza riavvio,
`SemanticIndex` invalidabile, i quattro stati di copertura rappresentabili e
**collegati a niente**. Teach 3DGen inesistente.

**Esito: completa.** Suite da 1761 a **2070 test verdi** (309 nuovi, zero
rossi).

Quattro cose vanno dette in testa, perche' cambiano la lettura di tutto il
resto.

**1. La prova finale non e' il drago: e' il drago costruito senza l'AI.**
Dopo che il concetto e' `LEARNED`, una `Session` **normale** — fuori da Teach,
con il planner locale e nessuna rete — fa `shortlist("dragon")` e trova
`dragon_pack:dragon` al primo posto, poi `generate("a cartoon dragon")`
costruisce 976 triangoli scegliendo quel componente come radice, e
`{"concept": {"requested": "dragon"}}` lo costruisce con **zero** diagnostiche
di degradazione — e' un'implementazione esatta, non un'approssimazione. Se
quella riga non passasse, tutto il resto sarebbe teatro
(`test_a_normal_session_finds_and_builds_the_learned_concept`).

**2. La copertura non e' una soglia su un punteggio, ed e' misurabile che non
lo sia.** §11 lo chiedeva; la forma che ha preso e' che ogni candidato porta
**evidenze nominate** e che lo stato si legge dai *nomi*, non dalla loro
somma. Un punteggio di retrieval di 1.0 senza identita' non produce un giallo
(`test_a_perfect_retrieval_score_alone_is_not_a_candidate`), e **nessuna
quantita' di evidenza produce un verde** — il verde lo scrivono quattro metodi
che un utente chiama (§5).

**3. Il Python generato non viene eseguito, e lo si misura dal lato
dell'effetto.** Non «e' sicuro perche' lo ispezioniamo»: dopo lo staging, un
modulo che se girasse lascerebbe un file su disco non lo lascia, `sys.modules`
non cresce, i `.py` restano chiusi, e `validate_artifact` **alza**
`TEACH_TRUST_REQUIRED` invece di importare. Solo dopo un gesto esplicito entra
in gioco il normale meccanismo dei plugin di codice. E niente qui si chiama
sandbox, perche' non ce n'e' una (§11, §12 di questo documento).

**4. V7 ha chiuso un debito di V2/V3 che nessuno aveva chiesto di chiudere.**
Il debito 13 di `PROJECT-INDEX` dice: «il retrieval mette le parti davanti agli
interi, e `subject_capabilities()` di V2 sa gia' riconoscere un soggetto, e il
retrieval non lo chiama». Qui si vedeva subito: senza quel filtro, il miglior
candidato per **un drago** era `creature:dragon_head`, cioe' una testa — e il
guasto non si fermava li', perche' i figli leggono l'evidenza `capability` da
cio' che il padre accetta, quindi una radice sbagliata sposta ogni figlio. La
radice di un concetto adesso accetta soltanto candidati che forniscono una
capability che nessuno accetta. Nel vocabolario del planner il debito resta
aperto (§21).

---

## 1. Lo schema del TeachProject

`app/teach/model.py` (1079 righe). Il formato e' `.teach3d`, JSON, `format: 1`,
e **non** e' `.my3d`: quello rappresenta un modello generativo, questo
rappresenta il **processo attraverso cui 3DGen impara un concetto**. Nemmeno
`.3dgenproj`, che rappresenta un plugin in lavorazione.

### Le due meta', e perche' stanno separate

```text
TeachProject
├ concept, description, style, style_target, detail_target
├ plugin_id, destination, completion, root_component
├ root: TeachNode          ← l'ONTOLOGIA: che cosa l'oggetto e'
├ states: {id: NodeState}  ← lo STATO: che cosa sappiamo del coprirlo
├ recipes: {nome: VariantRecipe}
├ artifacts: {id: ArtifactRecord}
├ exchanges: (Exchange, ...)      prompt + risposte, entrambi
├ fingerprints: {plugin: "versione#impronta"}
└ passes: {decomposition: ..., refinement: ...}
```

| oggetto | che cos'e' |
| --- | --- |
| `TeachNode` | `id`, `name`, `role`, `mandatory`, `count`, `importance`, `detail_level`, `description`, `children`. **Nessuna geometria, nessun id di componente** |
| `NodeState` | `coverage`, `candidates`, `solution`, `suitability`, `attempts`, `backend`, `locked`, `asset` |
| `Candidate` | `component_id`, `score`, `verdict`, `evidence`, `reason` |
| `Evidence` | `kind`, `detail`, `weight` — un nome, non un numero |
| `Solution` | `ref` (sempre un componente installato), `recipe`, `params`, `origin`, `decided_by` |
| `SuitabilityRecord` | la raccomandazione di un modello: `status`, `confidence`, `reason`, `suggested_params` |
| `Attempt` | un giro di generazione: `index`, `backend`, `artifact`, `ok`, `codes`, `repaired_from` |
| `ArtifactRecord` | un artefatto in staging: `path`, `files`, `trusted`, `accepted` |
| `Exchange` | `kind`, `node`, `prompt`, `response`, `mode`, `provider`, `accepted` |

**Perche' separate.** La milestone chiedeva «informazioni equivalenti» per
nodo (§2), non una struttura unica, e tenerle separate non e' ordine: e' la
ragione per cui un secondo giro di raffinamento puo' riscrivere la gerarchia
senza perdere una decisione validata, e per cui la copertura si ricalcola dopo
**ogni** installazione senza toccare l'ontologia. `TeachProject.tree()` le
rimette insieme per chi deve solo leggerle, ed e' la vista che la UI disegna.

### L'identita' di un nodo non e' l'id di un Component

`dragon.head.eye` e' un **percorso concettuale**: esiste prima che esista
un'implementazione e sopravvive al fatto che quella implementazione sia un
componente dedicato, una `VariantRecipe`, un composite o un proxy. E' derivato
dai nomi — `genitore.slug(nome)` — e **non arriva dalla risposta**: lo schema
non ha nemmeno il campo. E' la regola 15 di `PROJECT-INDEX` («l'id che il
planner scrive non e' l'identita' di un nodo») applicata all'ontologia, e serve
alla stessa cosa: un modello non deve poter scegliere l'identita' di niente.

Due fratelli con lo stesso nome prendono `_2`, `_3` — non e' un errore
dell'autore, e' un plurale scritto due volte — e nessun id contiene `:`
(`test_a_node_id_is_never_a_component_id`).

Il limite dichiarato: gli stati sopravvivono **per id**, quindi un nodo che il
raffinamento rinomina e' un nodo nuovo e la sua decisione cade. Non cade in
silenzio: `TEACH_DECISION_LOST` lo dice, con il perche'
(`test_a_decision_on_a_node_the_refinement_removed_is_declared_lost`).

### Un composite ha tre plugin, non uno

Un concetto genera componenti in **plugin distinti**: `dragon_snout`,
`dragon_horn`, `dragon_head`, e `dragon_pack` per la radice. Tre ragioni, e
nessuna e' estetica:

1. un plugin **dati** rifiuta un `components` che nomini un `.py` (V4 §2),
   quindi un pezzo procedurale e un pezzo dichiarato in JSON non possono stare
   nella stessa cartella;
2. mettere piu' componenti nello stesso plugin vorrebbe dire **fondere** due
   manifest a ogni accettazione, e una fusione di manifest e' un formato nuovo
   scritto per sbaglio;
3. un pezzo che vive da solo si installa e si disinstalla da solo, ed e' cio'
   che serve a §39: imparare `wyvern` riusa l'ala del drago senza portarsi
   dietro il drago.

### Il ciclo, e perche' non c'e' un controllo per lui

§6 chiede di rifiutare «un ciclo nella gerarchia». La risposta onesta e' che
**in questa forma un ciclo non si puo' esprimere**: un figlio e' un oggetto
annidato, non un riferimento a un nodo per nome, quindi non esiste un arco che
torni indietro. La forma in cui qualcuno proverebbe a scriverne uno — un figlio
che e' una stringa — e' rifiutata, e un test lo fissa; lo stesso nome annidato
resta legale e prende percorsi distinti (`a`, `a.a`, `a.a.a`), perche' «la
testa della testa» non e' un errore, e' un percorso. Un controllo che non puo'
scattare sarebbe un controllo che mente, e `TEACH_HIERARCHY_CYCLE` e' stato
**togliato** dai codici invece di restare come decorazione.

---

## 2. Il pass 1: decomposizione concettuale

`prompts.decomposition_prompt()` — 4209 caratteri per «dragon». Che cosa dice,
e che cosa **non** dice:

```text
You decompose a concept into the parts an object of that kind is made of.

This is an ontology task, not a modelling task. Do NOT write code, geometry,
meshes, vertices, triangles, coordinates, transforms, file formats, or anything
about any 3D engine or its API. Do NOT choose or name existing assets or
components. Describe only WHAT THE OBJECT IS MADE OF.
```

Nessuna API compare nel testo: un test cerca `Component(`, `Piece(`,
`ParamSpec(`, `build(values` e non li trova. E **nessuna parola di dominio**:
un test cerca `dragon`, `horn`, `snout`, `claw`, `fang` con i confini di parola
nel prompt generato per un concetto qualunque e non ne trova nessuna.

I prompt sono in **inglese**, e il resto del progetto no. La differenza e'
deliberata: `SISTEMA` del planner e' italiano e va a un fornitore configurato,
mentre questi vengono **copiati dall'utente** in ChatGPT, Claude, Codex o
Gemini, e lo schema di risposta ha i campi in inglese. Un prompt e il suo
schema in due lingue diverse sono un prompt che si fraintende.

Lo schema (`app/teach/schema.py`) e' stretto: `additionalProperties: false`
ovunque, `count` intero in 1..64, `importance` in 0..1, `detail_level` in 1..5,
ricorsione sui `children` con `maxItems: 24`. Non nomina nessun componente
installato, per la stessa ragione per cui `PLAN_SCHEMA` non lo fa: uno schema
che elenca gli id installati non e' un contratto, e' una fotografia.

---

## 3. L'import: che cosa viene rifiutato, e niente viene eseguito

`build_tree()` deriva gli id e fa valere i limiti di forma. **Rifiuta, non
interpreta** — dodici casi parametrizzati piu' due di dimensione:

| caso | codice |
| --- | --- |
| non e' JSON | `TEACH_RESPONSE_INVALID` |
| non e' un oggetto | `TEACH_RESPONSE_INVALID` |
| manca `root` | `TEACH_SCHEMA_INVALID` |
| `root` e' una lista (radici multiple) | `TEACH_SCHEMA_INVALID` |
| campo sconosciuto nella risposta | `TEACH_SCHEMA_INVALID` |
| campo sconosciuto in un nodo | `TEACH_SCHEMA_INVALID` |
| `count` 0, negativo, enorme, non numerico | `TEACH_SCHEMA_INVALID` |
| nome vuoto | `TEACH_SCHEMA_INVALID` |
| `children` non e' una lista | `TEACH_SCHEMA_INVALID` |
| un figlio che e' un riferimento e non un oggetto | `TEACH_SCHEMA_INVALID` |
| profondita' oltre `MAX_DEPTH = 6` | `TEACH_HIERARCHY_TOO_DEEP` |
| piu' di `MAX_NODES = 120` nodi | `TEACH_HIERARCHY_TOO_LARGE` |
| oltre 64 fratelli omonimi | `TEACH_DUPLICATE_NODE` |

E **non esegue niente**: un test mette
`__import__('pathlib').Path(...).write_text('x')` nella `description` di un
nodo, importa, e verifica che il file non esista e che la stringa sia ancora li'
come testo (`test_import_does_not_execute_anything`).

---

## 4. Il pass 2: raffinamento

`prompts.refinement_prompt()` — 6829 caratteri. Riceve concetto, descrizione,
style target, detail target, le regole di granularita' e la gerarchia del pass 1
**senza gli id e senza lo stato**: gli id li deriva il sistema, e mandarli
inviterebbe il modello a riscriverli; lo stato non si manda perche' il
raffinamento riguarda che cosa l'oggetto e', non che cosa la libreria ha
(`test_the_refinement_prompt_shows_pass_one_without_the_node_ids`).

Sul drago di prova il pass 1 e' deliberatamente **superficiale**, come lo e' un
pass 1 vero: plurali (`eyes`, `wings`, `legs`), un `claw` troppo granulare
sotto la zampa, nessun ruolo. Il pass 2 fa esattamente le cose che §7 elenca:

```text
eyes -> eye con count 2 (una parte ripetuta e' un nodo)
wings -> wing con count 2
legs -> leg con count 4
horns -> horn con count 2, ancora optional
claw fuso nella zampa: un singolo artiglio non e' riutilizzabile da solo
ruoli assegnati: body, head, eye, snout, horn, tooth, wing, leg, tail
```

Da 11 nodi a 10, e `dragon.leg.claw` non esiste piu'. L'utente puo' saltare il
raffinamento: §7 lo ammette, e `import_refinement` e' una chiamata separata.

Entrambe le risposte restano nel progetto (`exchanges`), con il prompt che le ha
chieste.

### Le regole di granularita' (§8)

Nel prompt, per esteso, e **generiche**:

```text
WHEN TO CREATE A SUB-PART - create one when at least one of these is true:
  it can be reused on a different object;
  it can vary independently from its parent;
  it has a recognisable semantic role of its own;
  it can itself hold sub-parts;
  it can be left out (optional);
  it appears more than once;
  it is only needed at a higher level of detail.

WHEN NOT TO - do not split when the split adds no capability: do not go down to
materials, surfaces, polygons, cells, molecules or atoms. [...] Stop at the
level a person would name when describing the object out loud.

REPEATED PARTS - a part that appears N times is ONE node with "count": N. Never
one node per instance, never a node whose name is a plural, and never a left
node beside a right node: one node, counted.
```

---

## 5. Il motore di copertura

`app/teach/coverage.py` (649 righe). Tre vincoli lo definiscono prima di
qualunque dettaglio, e sono tre **non**:

**Non c'e' un secondo motore di ricerca.** I candidati arrivano dal
`SemanticIndex` di V1 attraverso `ComponentIndex.search` — lo stesso oggetto che
la `Session` usa per la rosa del planner — piu' i fornitori di una capability
letti dal `Registry`. Nessun indice nuovo, nessun corpus nuovo, nessun punteggio
calcolato qui dentro (regola 10 di `PROJECT-INDEX`).

**Non c'e' una soglia che decide.** §11 lo chiede, e la ragione e' che un
punteggio di retrieval misura la somiglianza di due **documenti di testo**: dice
che `humanoid:leg` assomiglia alla parola «leg», non che una gamba umanoide sia
una gamba di drago.

**Non c'e' una parola di dominio.** Un test legge `coverage.py`, `spec.py`,
`model.py`, `schema.py`, `prompts.py`, `contracts.py`, `staging.py`,
`service.py`, `knowledge.py` e `_runner.py` **senza commenti e senza
docstring** — solo cio' che esegue — e cerca `dragon`, `wyvern`, `horn`,
`snout`, `wing`, `tail`, `claw`, `fang`, `eye`, `leg`, `tooth`, `scale` con i
confini di parola. Zero riscontri. La distinzione fra codice e commento e'
deliberata e non e' indulgenza: un commento che spiega **una misura** — «cercare
`dragon horn` trova `creature:dragon_head`, misurato» — e' documentazione
preziosa, e toglierla per far passare un grep renderebbe il codice peggiore.
Una parola di dominio dentro una stringa che il programma **usa** e'
conoscenza di dominio, e quella e' la regressione.

### Le tredici evidenze

```text
identita'     prior_validation   un record di validazione per (ruolo, nome)
              role               component.role == node.role
              name               il nome o il ruolo del nodo fra i tag/nome

contesto      family             il pezzo nomina il **concetto** o un antenato
              capability         fornisce cio' che il padre accetta davvero
              subject            (solo radice) fornisce una capability che
                                 nessuno accetta: e' un oggetto intero

somiglianza   retrieval          punteggio sulle interrogazioni **della parte**

adattabilita' children           puo' ospitare i figli mandatory del nodo
              params             ha parametri pubblici
              semantic_roles     i suoi parametri dichiarano ruoli semantici
              variability        quanti trait installati lo raggiungono
              style              compatibile con lo stile del progetto
              frame              la terna concorda con quella del padre
```

Le ultime sei ordinano i candidati e non decidono niente; i pesi stanno in una
sola costante (`WEIGHTS`) perche' un peso nascosto in una funzione e' un numero
che nessuno rivede.

### I quattro stati, e la regola per esteso

```text
CANDIDATE   identita' **e** contesto
PROXY       identita' senza contesto, oppure contesto con somiglianza
MISSING     ne' l'una ne' l'altro
VALIDATED   mai da un'evidenza: solo da una soluzione confermata
```

Le due righe centrali sono la risposta che §10 pone con due esempi.

* Un occhio umanoide su una testa di drago ha identita' (`name: eye`) **e**
  contesto (`capability: face_mount`, che la testa scelta accetta davvero): e'
  un occhio ed e' montabile li' — `CANDIDATE`, da verificare.
* Una gamba umanoide per una zampa di drago ha identita' (`role: leg`) e
  **nessun** contesto: niente la lega a questo soggetto — `PROXY`,
  un'approssimazione consapevole.
* Una cosa che sta nel socket giusto ma non e' la parte richiesta (contesto
  senza identita') e' un proxy soltanto se almeno i testi si somigliano;
  altrimenti «ci sta» non e' una ragione, e il nodo e' `MISSING`.

`family` usa le parole del **concetto e degli antenati**, non del nodo: se
usasse quelle del nodo direbbe la stessa cosa di `name` e la distinzione fra
giallo e blu collasserebbe. E lo **stile non entra**: `cartoon low-poly` non
dice che cosa l'oggetto e', e lasciarlo entrare darebbe parentela a ogni pezzo
che dichiara il tag `low_poly`, cioe' a mezza libreria, per una ragione che non
riguarda il soggetto.

### Due filtri strutturali, e perche' esistono

**La radice di un concetto accetta solo soggetti interi.** Senza, il miglior
candidato per un drago e' una testa di drago, e i figli — che leggono
`capability` da cio' che il padre accetta — vengono spostati tutti. Si riusa
`subject_capabilities()` di V2: una capability fornita da qualcuno e accettata
da nessuno. E' il debito 13 chiuso dove c'e' un concetto di cui si sa che e' un
oggetto intero (`test_the_root_only_accepts_whole_subjects`).

**Una parte deve potersi montare.** Un componente che non fornisce nessuna
capability non e' montabile da nessuno: `humanoid:body` e' il caso vero — e' la
radice del proprio plugin e `provides` e' vuoto — e proporlo come zampa
vorrebbe dire portare chi costruisce fino al composite per poi dirgli li' che
non si attacca (`test_a_part_must_be_mountable_or_it_is_not_offered`).

### La somiglianza si misura solo sulle parole della parte

Una misura, non una preferenza. Cercare «dragon horn» trova
`creature:dragon_head` con 0.40 — perche' la parola «dragon» pesa in entrambi i
documenti — e una testa di drago non e' un corno. Se quel punteggio contasse
come somiglianza, **ogni** parte di un drago avrebbe la testa di drago come
proxy e nessun nodo risulterebbe mai `MISSING`. Quindi:

| funzione | a che serve |
| --- | --- |
| `node_queries` | **trovare** i candidati e ordinarli: nome, ruolo, singolari, «concetto + nome», descrizione |
| `part_queries` | **misurare la somiglianza**: solo nome, ruolo, singolari, descrizione |

`variants("wings")` da' `("wings", "wing")`, ed e' un'interrogazione in piu' dal
lato della domanda — dove interrogazioni multiple sono gia' la norma
(`query_groups`) — non un cambiamento del motore. Il debito «la ricerca non fa
stemming» resta quello che era.

### L'ordine di calcolo e' dall'alto in basso

L'evidenza `capability` di un figlio guarda che cosa il **padre** accetta,
quindi i padri si calcolano prima dei figli (`TeachNode.walk()` lo garantisce) e
il «padre» e' la sua soluzione se c'e', altrimenti i suoi candidati.

### Che cosa un ricalcolo non tocca

| cosa | perche' |
| --- | --- |
| una soluzione confermata | resta `VALIDATED`, e i candidati si aggiornano comunque: una scelta fatta non si disfa perche' e' arrivato un plugin |
| uno stato bloccato (`locked`) | l'utente ha deciso (§43), e un ricalcolo che cancella una decisione non e' un ricalcolo |
| una soluzione sparita | **decade**: se il componente non e' piu' installato la copertura torna a quella delle evidenze, e il referto lo dice (`report.dropped`) |

---

## 6. Il banco del drago: la copertura misurata (§46)

Libreria reale, 23 plugin e 97 componenti, nessun ranking manipolato. Questo e'
cio' che esce:

```text
RED    dragon
BLUE     body   fox_stylized:body
YELLOW   head   creature:dragon_head
YELLOW     eye x2   creature:bulging_eye
BLUE       snout    creature:dragon_head
RED        horn x2
RED        tooth x6
BLUE     wing x2  fantasy:wing
BLUE     leg x4   humanoid:leg
BLUE     tail     fish:tail

VALIDATED 0, CANDIDATE 2, MISSING 3, PROXY 5
```

Perche' ciascuno sta dove sta, letto dalle evidenze vere:

| nodo | stato | evidenze del migliore |
| --- | --- | --- |
| `dragon` | 🔴 | nessun candidato: nessun componente installato fornisce una capability di soggetto **e** somiglia a «dragon» |
| `head` | 🟡 | `role` (head), `name` (tag `head`), `family` (`dragon`, `reptile`), `capability`, `frame`, `retrieval 0.58` |
| `eye` ×2 | 🟡 | `name` (tag `eye`), `capability` (`face_mount`, che `creature:dragon_head` accetta), `family` (`creature`), `retrieval 0.52` |
| `snout` | 🔵 | `family` + `retrieval 0.40`, nessuna identita': non dichiara di essere un muso |
| `horn` ×2, `tooth` ×6 | 🔴 | niente: per quelle parole la libreria non ha nulla, e «ci sta in un socket» non e' una ragione |
| `body`, `wing`, `leg`, `tail` | 🔵 | identita' (`role` o `name`) **senza** contesto: la parte giusta di un soggetto diverso |

Tutti e quattro gli stati compaiono, e **niente e' verde dopo un'analisi**: il
verde e' una decisione, non una misura.

Il drago era mandatory/optional come §46 chiede: body, head, eye, snout, wing,
leg, tail mandatory; horn e tooth optional.

---

## 7. La lista dei candidati e il dossier (§12, §13)

```text
creature:bulging_eye  0.52  CANDIDATE  [capability, family, frame, name,
                                        params, retrieval, semantic_roles,
                                        style, variability]
   name: nome/tag: eye
   capability: face_mount, che creature:dragon_head, creature:frog_head,
               fox_stylized:head accetta
   family: parole del concetto: creature
   params: 1 parametri pubblici
   semantic_roles: girth
   variability: 2 trait installati lo raggiungono
   style: compatibile con low_poly
   frame: frame compatibili su up, front
   retrieval: punteggio 0.516 sulla parte
humanoid:eye          0.66  CANDIDATE  [...]
humanoid_anatomical:eye 0.48 CANDIDATE [...]
fox_stylized:head     0.14  PROXY      [...]
```

L'ordine e' **evidenza prima, punteggio dopo**: `creature:bulging_eye` precede
`humanoid:eye` nonostante un punteggio piu' basso, perche' ha un'evidenza in
piu' (`family`, dal plugin `creature`, che e' il ruolo che il raffinamento ha
dato alla radice). Un elenco ordinato per punteggio metterebbe davanti l'occhio
umano.

Il **dossier** di §13 e' la modalita' economica: metadata e comportamento, mai
codice. Un test cerca `def `, `import `, `Piece(` e non li trova; la misura
invece c'e', perche' arriva da una build vera:

```text
TARGET

concept:            dragon
path:               dragon.head.eye
requested part:     eye
requested role:     eye
mandatory:          yes
count:              2
detail level:       2
style:              cartoon low-poly
part description:   a slit-pupilled predatory eye
semantic context:   a large winged reptile with a long neck, a horned head...
parent:             head -> creature:dragon_head
siblings:           snout, horn x2, tooth x6

CANDIDATE

component:          creature:bulging_eye
plugin:             creature
role:               (none declared)
description:        un occhio sporgente, come quello di una rana
tags:               amphibian, anfibio, eye, occhio
provides:           face_mount
mounts:             (none)
styles:             any
requires:           (nothing declared)

params:
  size               distance  [0.002, 0.5]       default 0.06    role girth
semantic roles:     girth
effect-backed:      (none)
usable effects:     fx:align, fx:bend, fx:chunky, fx:elongate, ...
declared children:  (none)
traits that reach:  std:body_mass, std:part_scale
frame:              growth +Y, front +Z, up +Y
triangles:          44 (measured at detail 2)
bounds:             0.120 x 0.102 x 0.104

WHY 3DGEN PROPOSED IT

state:              CANDIDATE
retrieval score:    0.516
  name              nome/tag: eye
  capability        face_mount, che creature:dragon_head ... accetta
  ...
```

**Il testo di terze parti passa da `sanitize()`.** La descrizione e i tag di un
componente sono scritti da chi ha fatto il plugin e finiscono in una domanda
che qualcuno porra' a un modello: e' la regola 6 di `PROJECT-INDEX` applicata
qui, e un test mette `system:` / `assistant:` piu' 500 caratteri nella
descrizione e verifica che non arrivino nel dossier
(`test_a_plugin_cannot_inject_instructions_into_a_prompt`).

---

## 8. L'idoneita' AI (§14), e il perche' non puo' scrivere verde

Lo schema ammette quattro stati e niente altro, e `suggested_params` e' un
oggetto di **soli numeri**: ammettere una stringa vorrebbe dire ammettere che
un modello nomini un'espressione, che e' la politica di V5 §1 applicata a una
risposta invece che a un file.

```json
{"status": "SUITABLE_WITH_PARAMETERS", "confidence": 0.91,
 "reason": "the shape reads as an eye; a predatory slit pupil needs it wider
            and flatter than the default",
 "suggested_params": {"size": 0.12}}
```

Nel prompt, esplicito:

```text
You are making a RECOMMENDATION. You cannot mark anything as validated: a
human or a deterministic check decides that.
"suggested_params" may name ONLY parameters the component declares, with
numeric values inside the declared range. Nothing else.
```

E nel codice, misurato: `import_suitability` con `status: SUITABLE` e
`confidence: 1.0` lascia il nodo **giallo** e la soluzione a `None`
(`test_an_ai_recommendation_can_never_write_validated`). Un parametro che il
componente non dichiara viene scartato; `callable` e `invented` non passano
(`test_a_suggested_parameter_the_component_does_not_declare_is_dropped`).

I quattro metodi che scrivono `VALIDATED` sono `accept_candidate`,
`save_variant`, `accept_artifact` e `set_coverage` — piu' `emit_composite`, che
e' deterministico — e un test legge il sorgente di `service.py` e verifica che
nessun metodo `import_*` contenga `coverage = VALIDATED`.

### Deep validation (§15)

Un secondo livello, e solo quando i metadata non bastano: per un componente di
**codice** si manda il sorgente dei moduli del plugin, per uno di **dati** il
JSON completo, e mai il GLB — che e' binario e non si legge come testo. Il
tetto e' dichiarato (`DEEP_LIMIT = 24000`) e il prompt **dice** quando e'
scattato invece di troncare in silenzio:

```text
--- components/testa.py: omitted, the 200 character limit was reached ---
```

Costa piu' del doppio del prompt economico, e un test lo misura
(`test_the_deep_prompt_is_not_the_default_economy_mode`).

### Validazione visiva (§17)

`render_variants` costruisce il predefinito, il suggerimento dell'AI e due
randomizzazioni **dentro gli intervalli dichiarati** (`randomize` di V6, che non
inventa un intervallo a un parametro che non ne ha), le rende con l'offscreen
che c'era, e il prompt le nomina:

```text
VARIANTS SHOWN

  A          defaults
             image: .../eye_A.png
  C          size=0.31
             image: .../eye_C.png

TASK
For each variant say whether it could be the 'eye' of a dragon, and name the
best match.
```

Nessuna API vision nuova: un test cerca `b64encode`, `base64.`, `image_url`,
`multimodal`, `openai`, `requests`, `httpx`, `urllib` in `prompts.py` e non ne
trova nessuna. Il verdetto si importa e **resta una raccomandazione**.

---

## 9. Da giallo a verde con una VariantRecipe (§18, §47)

Il percorso completo, misurato:

```text
dragon.head.eye  CANDIDATE
  -> Validate with AI    SUITABLE_WITH_PARAMETERS 0.91, {"size": 0.12}
  -> coverage            ancora CANDIDATE          ← l'AI ha raccomandato
  -> Apply AI Suggestion livello 2 | 44 triangoli | 0.240 x 0.204 x 0.208 | ok
  -> Save Variant        dragon_eye (da creature:bulging_eye): size = 0.12
  -> coverage            VALIDATED
     solution            ref creature:bulging_eye, recipe dragon_eye
```

Si riusa `VariantRecipe` di V6 e **non si duplica geometria**: il file pesa meno
di 700 byte, non contiene `mesh`, `glb`, `vertices` ne' `faces`, e salvarlo non
scrive nessun `.glb` accanto (`test_the_variant_duplicates_no_geometry`). Prima
di promuovere, `save_variant` **costruisce**: una configurazione che non
costruisce non diventa una soluzione, e `decided_by` dice
`deterministic` invece di `user`.

Questa e' la proprieta' che la milestone chiama fondamentale: **3DGen puo'
imparare conoscenza nuova senza creare geometria nuova.**

E il Component Lab e' quello di V6, non un secondo: un test randomizza, applica
un trait, chiama `reset()` e verifica che l'ingombro sia tornato esattamente
quello di partenza e che il registry sia ancora congelato
(`test_the_lab_never_modifies_the_library`).

---

## 10. Da blu a rosso, e la coda (§20, §21)

Un proxy che non basta diventa `MISSING` **per decisione di chi costruisce**:
`reject_candidate` lo toglie dall'elenco, e quando non resta nessun candidato il
nodo e' rosso e `locked`. E' il percorso di §20, e non c'e' niente di
automatico in esso.

La coda e' **topologica sui discendenti**, poi per profondita' decrescente, poi
per importanza **crescente** — i dettagli utili prima delle parti principali,
che e' la frase di §21 — poi per id, cosi' e' deterministica:

```text
 1. dragon.head.eye     profondita' 2  importanza 0.60  procedural_python
 2. dragon.head.snout   profondita' 2  importanza 0.70  procedural_python
 3. dragon.tail         profondita' 1  importanza 0.75  procedural_python
 4. dragon.leg          profondita' 1  importanza 0.80  procedural_python
 5. dragon.wing         profondita' 1  importanza 0.90  procedural_python
 6. dragon.head         profondita' 1  importanza 0.95  procedural_python
 7. dragon.body         profondita' 1  importanza 1.00  procedural_python
 8. dragon              profondita' 0  importanza 1.00  procedural_python
```

Gli optional non entrano. Un nodo con figli ancora mancanti **non e' bloccato**
se la sua implementazione e' indipendente: §21 lo dice con queste parole, e
`next_buildable` lo applica — un pezzo procedurale non ha bisogno dei suoi figli
per esistere, un composite si'.

`advance()` e' il ciclo di §36, e dice che cosa fare **senza farlo**:

```python
{"action": "validate_candidate", "node": "dragon.head.eye",
 "candidate": "creature:bulging_eye", "coverage": "CANDIDATE",
 "why": "c'e' un candidato da verificare"}
```

Niente lavoro in background: un test cerca `threading`, `asyncio`, `Thread(`,
`QThread`, `Timer(`, `multiprocessing`, `schedule` in `service.py` e non ne
trova nessuno.

---

## 11. La specifica tecnica, e la raccomandazione di backend (§22, §23)

`app/teach/spec.py` (517 righe). **La decide 3DGen, non l'AI**, e questa e' la
frase che definisce il modulo: quando un nodo e' `MISSING`, cio' che manca e'
geometria, non un contratto. Il contratto lo possiede il sistema.

```python
{'node': 'dragon.head.snout',
 'id': 'dragon_snout:snout', 'plugin': 'dragon_snout', 'name': 'snout',
 'role': 'snout', 'mandatory': True, 'count': 1, 'detail_level': 2,
 'importance': 0.7, 'style': 'low_poly', 'style_target': 'cartoon low-poly',
 'backend': 'procedural_python',
 'backend_candidates': ['procedural_python', 'data_mesh', 'composite'],
 'backend_reason': "nessun asset fornito e il nodo non ha figli mandatory a "
                   "questo livello: 3DGen non puo' generare un GLB da un "
                   "testo, quindi la sola forma ottenibile e' parametrica",
 'provides': ['face_mount'], 'declares_capability': False,
 'parent': 'dragon.head', 'parent_component': 'creature:dragon_head',
 'mounts': [], 'required_sockets': [{'name': 'base', 'purpose': 'own_socket: ...'}],
 'semantic_parameters': ['girth', 'height', 'length', 'ratio', 'scale', 'width'],
 'children': [],
 'siblings': [{'node': 'dragon.head.eye', 'name': 'eye', 'role': 'eye',
               'count': 2, 'coverage': 'VALIDATED',
               'component': 'creature:bulging_eye'}, ...],
 'frame': {'growth_axis': '+Y', 'front': '+Z', 'up': '+Y'},
 'triangle_budget': 240,
 'reference_components': [],
 'notes': ['budget dichiarato (nessun riferimento da misurare)', ...]}
```

Tutto si deriva da dati dichiarati: la capability dal **padre scelto** (prima
una che un pezzo installato con lo stesso ruolo fornisce davvero, poi una che un
candidato del nodo fornisce, poi la prima); i `mounts` dai figli; il `frame` da
chi lo dichiara in quel punto dell'albero, **vuoto** quando nessuno lo fa
(regola 27: un frame inventato insegna una convenzione che nessuno ha scritto);
i `semantic_parameters` dai ruoli che i componenti con lo stesso ruolo
dichiarano, e in mancanza da quelli che i trait installati sanno pilotare.

Il **budget di triangoli** si misura quando si puo': si costruiscono i
componenti di riferimento e si prende la mediana piu' il 50%. Quando non ci sono
riferimenti resta il valore dichiarato (240) e **la nota lo dice** — un numero
presentato come misura quando non lo e' sarebbe la bugia peggiore di tutte.

### La raccomandazione di backend e' strutturale

§23 vieta di cablare «tail», «horn» o qualunque nome nel motore. La regola sta
in tre righe:

| backend | quando | perche' |
| --- | --- | --- |
| `composite` | tutti i figli mandatory di questo livello sono validati | non c'e' niente da modellare: il nodo **e'** la disposizione di pezzi che esistono |
| `data_mesh` | per questo nodo e' stato fornito un GLB | la forma esiste e va dichiarata, non generata |
| `procedural_python` | tutto il resto | **3DGen non puo' generare un GLB da un testo** (§23 lo dice), quindi raccomandare `data_mesh` senza un asset vorrebbe dire raccomandare una cosa che il sistema non sa fare |

I tre restano sempre in `backend_candidates`, in quest'ordine di preferenza, e
`set_backend` li cambia: la ragione diventa «scelto dall'utente (data_mesh); la
raccomandazione era procedural_python».

---

## 12. Il compilatore di prompt (§24-§27), e il contratto che si genera

`prompts.implementation_prompt()` — 14055 caratteri per il muso. Non «crea una
coda 3D»: un contratto.

```text
TARGET

component id:       dragon_snout:snout
plugin id:          dragon_snout   (the manifest MUST declare exactly this id)
concept node:       dragon.head.snout
part:               snout
role:               snout
mandatory:          yes
count:              1
detail level:       2

PURPOSE             the long jawed muzzle
STYLE               cartoon low-poly

CONTRACT

must provide:       face_mount
attaches to:        creature:dragon_head
own socket:         base
sockets:
  base           own_socket: dove questa parte si attacca a chi la contiene

PUBLIC PARAMETERS

Declare at least one parameter for each of these semantic roles, so the
installed semantic traits reach this component without a new rule:
  girth, height, length, ratio, scale, width

FRAME (the convention that holds here)
  {"front": "+Z", "growth_axis": "+Y", "up": "+Y"}
  Declare it, and build consistently with it.

TRIANGLE BUDGET
  at most 240 triangles at detail 2

NOTES
  - budget dichiarato (nessun riferimento da misurare)
  - nessun asset fornito e ...

BACKEND
  procedural_python   (...)

[il contratto delle API, generato: vedi sotto]

MANDATORY SELF-CHECKS
  the component declares the capability it was told to provide;
  every socket named above exists, with a non-zero direction and up that are
  not parallel, and a positive radius;
  ...

TASK
Write the files of a plugin that installs dragon_snout:snout exactly as
specified.

RESPONSE SCHEMA (strict; every other key is refused)
{ ... }
```

E nel sistema: *«The contract below is not a suggestion and not a starting
point [...] Do NOT modify 3DGen itself.»*

### Il contratto si genera leggendo 3DGen

`app/teach/contracts.py` (245 righe), e la decisione vale la pena di essere
scritta: la tentazione e' scrivere quel testo a mano una volta. E' la cosa
sbagliata — diventerebbe falso al primo campo aggiunto a `Component`, e un
prompt falso produce codice che non si carica, che e' il modo peggiore di
scoprire un errore di documentazione.

Quindi **tutto si genera**: i campi da `dataclasses.fields`, le firme da
`inspect.signature`, le chiavi del formato dati dalle costanti che il loader fa
valere, i tipi di parametro da `app/core/params.py:TYPES`.

```text
Component - Una regola che sa costruire una parte, e che cosa ci si attacca.
    id               str                          obbligatorio
    build            Callable[[dict, BuildContext], Piece] obbligatorio
    params           dict[str, ParamSpec]         {}
    children         Callable[...] | None
    ...
Piece - Cio' che una regola restituisce: geometria e punti di attacco.
    mesh             trimesh.Trimesh | None
    sockets          dict[str, Socket]            {}
    ...
app/geometry/kernel.py - l'unico costruttore di geometria procedurale installato
    grow(stations, sides: int = 6, length: float = 1.0, axis: int = 0, ...)
        Tubo generalizzato: una sequenza di (t, raggio) lungo un asse.
```

Un test confronta il testo generato con `dataclasses.fields` di ciascuna classe:
se qualcuno aggiunge un campo a `Piece`, il prompt lo dice il giorno dopo senza
che nessuno lo aggiorni, e il test lo verifica. E il core **non** c'e': un test
cerca `Resolver`, `Builder`, `EffectPipeline`, `Session`, `CompositionGraph`,
`Registry` nel contratto e non li trova — un modello che implementa un
componente non deve conoscerli e non deve poterli modificare.

I tre contratti sono **ASCII**, perche' vengono copiati in un terminale e in una
chat (`test_the_contracts_are_ascii_so_they_survive_a_copy_paste`).

### Il prompt per i dati non chiede byte

§26: la geometria esiste gia' ed e' l'asset che l'utente ha fornito.

```text
THE MESH
  The geometry already exists and is NOT yours to invent: it is the file
  below, and it will be placed at `meshes/horn.glb` inside the plugin.
  Write the JSON that declares it: do not emit GLB bytes, do not emit
  base64, do not emit vertices.
  asset: C:/.../assets/horn.glb
```

### Il composite, 3DGen se lo scrive

§27 preferisce un data composite senza Python quando basta, e quando ogni figlio
e' validato **non c'e' niente da decidere**: componenti, requirement, parametri
e conteggi stanno nella specifica. Quindi `emit_composite()` lo scrive da se',
senza rete e senza fiducia da concedere — e lo scrive con `AuthoringService` di
V6, non con un emettitore nuovo: un secondo produttore di plugin dati sarebbe un
secondo formato che divergera'. Il prompt `composite_prompt` resta per chi
volesse che un modello decida la disposizione, e anche allora riceve un
contratto.

Un figlio con `count: N` diventa **N archi** sullo stesso componente, ciascuno
con il suo socket: e' cosi' che due occhi sono due occhi. Gli innesti si
distribuiscono su una circonferenza nel piano XZ guardando verso l'esterno, con
una quota che sale — una **convenzione dichiarata**, non una posizione casuale,
e chi vuole di meglio ha le `LayoutRegion` o l'authoring.

---

## 13. Lo staging e l'inviluppo (§28, §29)

```json
{"files": [{"path": "plugin.json", "content": "..."},
           {"path": "components/snout.py", "content": "..."}],
 "notes": "..."}
```

I limiti sono dichiarati, non impliciti:

| limite | valore |
| --- | --- |
| estensioni ammesse | `.json`, `.py`, `.md`, `.txt` |
| file per inviluppo | 24 |
| byte per file | 200 000 |
| byte totali | 600 000 |
| percorsi | relativi, nessun `..`, nessun assoluto, nessun drive, nessun UNC, nessun byte nullo |
| manifest | obbligatorio: senza, non c'e' un plugin da installare |

Diciassette inviluppi malformati e undici percorsi ostili sono parametrizzati, e
ciascuno ha un codice invece di un'eccezione generica:

```text
../../secret.py   ../secret.json   components/../../secret.json
/etc/passwd       C:/Windows/win.ini   //server/share/x.json
\\server\share\x.json   a\x00.json   file:///secret.json
..\..\secret.json   C:x.json          -> TEACH_PATH_UNSAFE
mesh.glb .gltf .exe .sh .dll .pyc .so .bat .bin (nessuna) -> TEACH_EXTENSION_REFUSED
```

Lo staging scrive sotto `<staging>/<artefatto>/<plugin>` e **mai** nella
libreria installata. Il manifest decide il nome della cartella, e **un id
diverso da quello che la specifica aveva dichiarato e' un errore**: il resto del
sistema ha gia' deciso che il componente si chiamera' `plugin:nome`, e un plugin
con un altro id installerebbe un componente che nessuno sta aspettando.

La specie si legge dai **file**, non dal manifest: un `.py` rende l'artefatto
codice anche se il manifest dicesse `type: "data"`, perche' la specie la decide
cio' che verrebbe importato.

---

## 14. Python generato: non e' sicuro, e non viene chiamato sicuro (§30, §31)

Il requisito di prodotto di §30, implementato letteralmente.

### L'ispezione statica dice cio' che vede, non cio' che fara'

`inspect_python` apre il file con l'**AST** e riporta: sintassi, import, import
segnalati, chiamate che raggiungono qualunque cosa, import fuori dall'API
dichiarata, dimensione, e se dichiara un `Component` di livello modulo — senza
il quale il registry non registrerebbe niente.

```text
components/snout.py: 1281 byte, 6 import, registra un Component, 2 avvisi
  importa moduli che un componente non ha motivo di usare: os, subprocess
  nomina chiamate che raggiungono qualunque cosa: eval, open
```

`FLAGGED_MODULES` e' **configurabile** e non e' un elenco di cose proibite: e'
un elenco di cose che chi legge il codice vuole sapere che ci sono. I risultati
sono `warnings`, e `report.ok` resta vero.

E nel referto, per iscritto:

> controlli statici: dicono quali moduli e quali chiamate il testo nomina, non
> che cosa il codice fara'. **Non c'e' nessuna sandbox**, e il codice va letto.

Un test legge `staging.py` e `_runner.py` riga per riga e verifica che la parola
«sandbox» compaia solo per **negarla**.

Perche' non e' sicurezza, detto una volta: un AST dice quali import compaiono
nel testo. `importlib`, `getattr` e una stringa bastano a raggiungere qualunque
modulo, e non e' un difetto di questi controlli — e' il motivo per cui non sono
sicurezza.

### Niente esecuzione senza un gesto esplicito

| azione | senza `trusted` |
| --- | --- |
| `import_implementation` | scrive i file, li ispeziona, **non importa niente** |
| `validate_artifact` | alza `TEACH_TRUST_REQUIRED` |
| `accept_artifact` | alza `TEACH_TRUST_REQUIRED` |
| `artifact_lab` | alza `TEACH_TRUST_REQUIRED` |

Misurato dal lato dell'effetto: un modulo che se girasse scriverebbe un file non
lo scrive, `sys.modules` non cresce, i `.py` restano sul disco chiusi. E un
plugin **dati** non ha bisogno di fiducia, perche' non c'e' niente da eseguire:
un test mette un `boom.py` accanto ai file di un artefatto dati, lo valida, e
quel file e' ancora li' (`test_a_data_plugin_in_staging_never_has_its_python_opened`).

Nella finestra il gesto e' una domanda che dice che cosa concede:

> Il codice generato verra' importato ed eseguito da questo processo. I
> controlli statici non sono una sandbox: leggi i file prima di continuare.

### Il sottoprocesso e' robustezza, e lo dice

`validate_artifact(..., isolate=True)` carica in un processo separato con un
timeout. Serve a non far morire chi chiama su un ciclo infinito o un crash, e un
test lo prova con un modulo che alza `RuntimeError` all'import. **Non e'
confinamento**: quel processo ha lo stesso accesso al filesystem, alla rete e ai
processi di chi lo ha lanciato. Parte con `-E` (ignora le variabili d'ambiente)
e **non** con `-I`, perche' `-I` toglie anche il sito dei pacchetti e senza
`numpy` e `trimesh` non si costruisce niente — un referto che dice soltanto
«manca un modulo» non misura nulla. Parte nella cartella del repository e non
nello staging, cosi' un modulo piantato accanto ai file generati non finisce
davanti a quelli veri.

Costa **2887 ms** contro 5.4 ms in processo, cioe' ~530 volte: per questo e'
spento per predefinito e c'e' una casella nella finestra.

---

## 15. Validazione, riparazione, installazione (§32, §34, §35)

Nessun validatore nuovo. `validate_artifact` carica il plugin in una `Session`
usa e getta, costruisce il componente con `check=True` e lo cerca nell'indice:

```text
ok | 1 componenti | 20 triangoli | trovabile | in processo
```

Che cosa gira, e chi parla:

| passo | chi |
| --- | --- |
| manifest, schema, percorsi | `Registry` + `app/core/data_plugin.py` |
| dipendenze, effetti dichiarati, materiali | `Registry.verify()` |
| socket, capability, frame, collegamenti | `Resolver` |
| geometria, giunti, compenetrazioni, budget, stile | `app/build/validate.py` |
| trovabilita' | il `SemanticIndex` |

Un fallimento ha un codice vero e finisce nel tentativo:
`TEACH_COMPONENT_NOT_INSTALLED` quando il modulo non registra nessun
`Component`, e `attempts[0].codes` lo conserva.

Il **prompt di riparazione** porta la specifica, i file come sono arrivati, le
**diagnostiche reali** (codice, messaggio, perche', dove) e il comportamento
atteso. Una riparazione e' un **tentativo nuovo** con `repaired_from`, non una
sovrascrittura, e la cronologia resta nel progetto. Non c'e' un ciclo: chi
chiama decide se farne un'altra.

### L'installazione, e perche' registra la libreria e non lo staging

```text
accept_artifact
  -> copia  <staging>/<artefatto>/<plugin>  ->  <destinazione>/<plugin>
  -> reload_plugins(<destinazione>)
  -> verifica che il componente ci sia
  -> verifica che l'indice non sia piu' quello di prima
  -> ricalcola la copertura di **tutta** la gerarchia
```

L'ordine conta: registrare lo staging e poi la destinazione darebbe lo stesso
plugin da due percorsi, e il registry lo scarta con `DUPLICATE_PLUGIN` —
correttamente, perche' due copie dello stesso id sono ambigue. Questo e' un
difetto che la prima scrittura aveva, e si vedeva
(`test_installing_registers_the_library_folder_and_not_the_staging`).

L'ultima riga e' quella che la milestone chiama fondamentale: installare un
componente puo' rendere verdi o gialli **altri** nodi, e la coda cambia da sola.
Per questo `analyse()` gira dentro `accept_artifact`.

---

## 16. Il completamento (§37, §38)

`LEARNED` non e' un interruttore: la condizione si **misura**, voce per voce.

```text
si ogni mandatory rilevante e' VALIDATED
si i count sono soddisfatti nel composite
si il composite della radice e' installato
si il composite della radice costruisce
si la radice e' trovabile dal retrieval
si la validazione e' ok
-> LEARNED
```

Gli optional non bloccano, e non e' una dichiarazione: il drago e' `LEARNED` con
`dragon.head.tooth` **rosso**
(`test_every_mandatory_node_is_green_and_the_optional_ones_do_not_block`).

I **count** si verificano leggendo i figli dichiarati dal composite, non
fidandosi:

```python
refs.count("fantasy:wing") == 2
refs.count("humanoid:leg") == 4
refs.count("fish:tail") == 1
head_children.count("creature:bulging_eye") == 2
```

La radice dichiara una capability con il nome del concetto (`dragon`). Non e'
conoscenza di dominio nel core — e' una stringa che arriva dal progetto
dell'utente, come `fox_stylized` dichiara `animal` nel proprio manifest — ed e'
cio' che rende il concetto un **soggetto intero** per
`subject_capabilities()`: fornita da qualcuno, accettata da nessuno. Senza, la
degradazione semantica di V2 non potrebbe mai sceglierlo.

### La prova finale

```text
shortlist("dragon")   ['dragon_pack:dragon', 'dragon_head:head',
                       'creature:dragon_head', 'dragon_snout:snout', ...]

build({"root": {"ref": "dragon_pack:dragon"}})   ok=True, 862 triangoli
  dragon: dragon_pack:dragon (senza geometria)
    head: dragon_head:head (senza geometria)
      head/eye_1: creature:bulging_eye (44 triangoli)
      head/eye_2: creature:bulging_eye (44 triangoli)
      head/snout: dragon_snout:snout (20 triangoli)
      head/horn_1: dragon_horn:horn (12 triangoli)
      head/horn_2: dragon_horn:horn (12 triangoli)
    body: fox_stylized:body (64)  + i figli che quel corpo dichiara
    wing_1 / wing_2: fantasy:wing (28 ciascuna)
    leg_1 ... leg_4: humanoid:leg (56 ciascuna)
    tail: fish:tail (38)

build({"concept": {"requested": "dragon"}})   ok=True, 862 triangoli,
                                              degradation() == []

generate("a cartoon dragon")                  ok=True, 976 triangoli
                                              root ref = dragon_pack:dragon
```

`planner: mock`. Nessuna rete, nessun provider, nessuna modalita' Teach — e
`degradation()` **vuota**, cioe' un'implementazione esatta e non
un'approssimazione. E si esporta in `.glb` con l'esportatore che c'era.

I 976 di `generate` non sono i 862 della radice, e vale la pena dire perche':
il planner **locale** sceglie `dragon_pack:dragon` come radice e poi, per
corrispondenza di parole, appende anche una `creature:dragon_head` accanto al
composite. Non e' un difetto di Teach — e' il planner a regole che fa il suo
lavoro su un vocabolario piu' ricco di prima — e i 114 triangoli in piu' sono
quella testa con i suoi figli. Il referto lo dice:
`l'innesto 'head' di 'dragon_pack:dragon' porta gia' 1 componenti`.

Il plugin della radice non porta geometria propria: `dragon.json` non contiene
`"mesh"`, la cartella non contiene nessun `.glb` e nessun `.py`.

---

## 17. La memoria delle validazioni, e perche' non in `Component` (§19)

§19 chiede di valutare se l'associazione «questa parte, questo componente,
questa ricetta, validato» debba poter essere esportata, dice di **non**
aggiungere `validated_for` a `Component` senza necessita', e chiede di
documentare la decisione. Questa e' la decisione.

**Non in `Component`.** Un `Component` installato non **ha** una validazione,
cosi' come non ha una copertura (V6 §2): e' nella libreria o non c'e'.
«`creature:eye` va bene come occhio di drago» non e' una proprieta'
dell'occhio — e' il giudizio di chi ha costruito un drago, e domani qualcuno
costruira' una lucertola e avra' un giudizio diverso sullo stesso pezzo.
Metterlo nel componente vorrebbe dire un campo che cresce con il numero di
concetti imparati dentro un oggetto congelato nel registry, un plugin di terze
parti che dichiara di essere stato validato per qualcosa (una dichiarazione che
chi la legge non puo' verificare) e — soprattutto — una conoscenza che
**sparisce disinstallando il plugin del concetto**, mentre riguarda il
componente di un altro plugin. Un test legge i campi di `Component` e verifica
che non ne esista nessuno con «valid» nel nome.

**In un file a parte**, `teach_knowledge.json`, accanto alla libreria:

```text
concept   dragon          il concetto durante il quale si e' deciso
path      dragon.head.eye il nodo concettuale
role/name eye             come si chiamava la parte: e' la chiave di riuso
component creature:bulging_eye
recipe    dragon_eye      la VariantRecipe, se c'era
params    {...}           i parametri confermati
```

La chiave di riuso e' **(role, name)**, non il percorso: e' cio' che fa si' che
imparare `wyvern` ritrovi l'occhio del drago. Le ricette viaggiano con i record,
perche' una validazione che nomina `recipe dragon_eye` senza portare la ricetta
non si puo' riusare — e sono piccole per costruzione.

I componenti che **questo** Teach ha generato non diventano validazioni
riusabili: li trova il retrieval come qualunque altro componente, e un record
che lo dicesse sarebbe rumore.

---

## 18. Il riuso: wyvern (§39)

Installata la conoscenza del drago, si importa l'ontologia di un wyvern e si
analizza. Senza toccare niente:

```text
YELLOW wyvern  dragon_pack:dragon
YELLOW   body  fox_stylized:body
YELLOW   head  creature:dragon_head
YELLOW     eye x2  creature:bulging_eye
YELLOW   wing x2  fantasy:wing
YELLOW   leg x2  humanoid:leg
YELLOW   tail  fish:tail

stati: VALIDATED 0, CANDIDATE 7, MISSING 0, PROXY 0
```

Ogni parte parte da un **candidato** invece che da zero, e le evidenze dicono
perche':

```text
wyvern.head.eye -> creature:bulging_eye
   [prior_validation, name, capability, family, params, semantic_roles,
    variability, style, frame, retrieval]
wyvern.wing -> fantasy:wing
   [prior_validation, name, capability, params, semantic_roles, variability,
    style, retrieval]
wyvern.tail -> fish:tail
   [prior_validation, role, name, capability, params, ...]
```

Due cose valgono la pena di essere notate. La prima: le parti del wyvern
guadagnano `capability` perche' la radice ha un candidato — `dragon_pack:dragon`,
che accetta `head_mount`, `limb_mount`, `tail_mount` — cioe' **il composite del
drago da' contesto alle parti del wyvern**. La seconda: **niente e' verde.** Un
giudizio dato su un drago non e' un giudizio dato su un wyvern, e fingere il
contrario sarebbe la bugia che §10 vieta. Il record si vede, e chi costruisce
decide.

---

## 19. Il livello programmatico e la UI (§40)

`app/teach/service.py` (1622 righe). Stessa regola di V6 (regola 28 di
`PROJECT-INDEX`): ogni operazione esiste come metodo, **niente in `app/teach/`
importa Qt**, e un test insegna un concetto intero senza aprire una finestra
(`test_a_whole_concept_can_be_taught_without_any_user_interface`). V6 l'ha fatto
perche' «un domani che decompone un concetto con un modello deve poter costruire
un plugin senza pilotare widget»: questo e' quel domani, e la strada c'era.

```python
svc = TeachService()                       # tiene una Session, nient'altro
svc.create_project("dragon", style_target="cartoon low-poly", detail_target=2,
                   destination="...")
svc.decomposition_prompt(); svc.import_decomposition(raw)
svc.refinement_prompt();    svc.import_refinement(raw)
svc.ask(bundle)                            # il provider configurato, se c'e'
svc.analyse(); svc.tree(); svc.progress(); svc.summary(); svc.node_detail(id)
svc.candidates(id); svc.dossier(id, component)
svc.suitability_prompt(id); svc.import_suitability(id, raw)
svc.deep_validation_prompt(id); svc.visual_validation_prompt(id)
svc.render_variants(id); svc.import_visual(id, raw)
svc.lab(id); svc.apply_suggestion(id); svc.save_variant(id, "dragon_eye")
svc.choose_candidate(id, c); svc.accept_candidate(id); svc.reject_candidate(id)
svc.set_coverage(id, PROXY); svc.set_backend(id, DATA_MESH)
svc.set_node(id, count=2); svc.add_node(parent, "brow"); svc.remove_node(id)
svc.supply_asset(id, "horn.glb")
svc.queue(); svc.next_node(); svc.advance(); svc.spec(id)
svc.implementation_prompt(id); svc.import_implementation(id, raw)
svc.inspect_artifact(a); svc.trust_artifact(a); svc.validate_artifact(a)
svc.artifact_lab(a); svc.accept_artifact(a); svc.reject_artifact(a)
svc.repair_prompt(a); svc.import_repair(id, raw)
svc.emit_composite(); svc.completion_report(); svc.finish()
svc.export_knowledge(); svc.changed_components()
svc.save_project(); svc.load_project(path); svc.close()
```

### La finestra

`app/ui/teach_window.py` (995 righe), cinque schede, piu' un pannello che non
cambia mai:

```text
1. CONCEPT -> 2. HIERARCHY -> 3. CANDIDATES -> 4. GENERATE -> 5. COMPLETE
```

E' l'ordine in cui le cose **diventano possibili**: non si analizza senza una
gerarchia, non si valuta un candidato senza una copertura, non si genera un
componente prima di sapere che manca, non si chiude il concetto prima che i
mandatory siano verdi. A destra, sempre: il prompt generato, il bottone per
copiarlo, il bottone per chiedere al provider, e la casella in cui si incolla la
risposta. Sotto, sempre: il progresso.

```text
Progresso  [########################----------]  72%
mandatory 72% (peso), 75% per nodi | optional 0%
green VALIDATED 6 | yellow CANDIDATE 1 | blue PROXY 2 | red MISSING 1
LEARNING
```

**La specie di una risposta non si indovina dal testo**: la sa il prompt che
l'utente ha generato, e un'importazione senza prompt diventa una riga di stato.

Un errore e' una riga di stato e non un traceback, e la selezione del nodo
sopravvive a ogni ridisegno — ridisegnare l'albero dopo ogni passo perderebbe il
nodo su cui si stava lavorando, e il passo successivo non avrebbe un bersaglio.

E `test_the_window_holds_no_teach_logic` legge il file **per token** e verifica
che non contenga `TeachProject`, `TeachNode`, `build_tree`, `candidates_for`,
`evidence_for`, `verdict_for`, `build_spec`, `recommend_backend`, `build_queue`,
`next_buildable`, `parse_envelope`, `inspect_python`, `emit_plugin`,
`load_component`, `Registry`, `AuthoringService`, `VariantRecipe`,
`TeachKnowledge`, `json`, `trimesh`, `np`, `ComponentLab`, `prompts`,
`staging`. E che importi una riga sola dal livello:

```python
from app.teach import BACKENDS, COVERAGE, TeachError, TeachService
```

La terza porta in `app/ui/main_window.py` condivide la **stessa** `Session`: un
componente imparato e' subito generabile dalla finestra principale, senza
riavviare.

---

## 20. Il progresso, e la formula (§42)

Due misure, e nessuna nasconde l'altra:

```text
mandatory_percent        per PESO: somma di (importance x count) dei nodi
                         mandatory rilevanti validati sul totale. E' la misura
                         primaria, perche' un occhio e una zampa non valgono
                         uguale e il modello lo ha dichiarato
mandatory_node_percent   per CONTEGGIO: quanti nodi su quanti. E' la misura
                         onesta quando le importanze sono tutte uguali, cioe'
                         quando il peso non dice niente
optional_percent         gli optional, separati, e non bloccano
counts                   quanti nodi in ciascuno dei quattro stati
```

«Rilevanti» vuol dire `detail_level <= detail_target`: il completamento richiede
i mandatory **del livello richiesto**, non tutti, e un'iride dichiarata a
livello 4 non blocca un drago chiesto a 2. Sul drago: 8 mandatory rilevanti a
livello 2, 6 a livello 1, 8 a livello 3.

---

## 21. Prestazioni

`python tools/teach_benchmark.py 7`, stessa macchina, nessuna rete, mediana di
7. La soglia dichiarata e' quella di V6: 100 ms.

| passo | mediana | peggiore | interattivo |
| --- | --- | --- | --- |
| prompt: decomposizione (testo reso) | 0.04 ms | 0.09 | si |
| import: decomposizione (11 nodi) | 0.13 ms | 0.17 | si |
| prompt: raffinamento | 0.09 ms | 0.12 | si |
| import: raffinamento (10 nodi) | 0.13 ms | 0.15 | si |
| **ANALISI DI COPERTURA (10 nodi, 97 componenti)** | **29.48 ms** | 55.24 | si |
| candidati di un nodo | 7.94 ms | 14.32 | si |
| dossier di un candidato (con la misura) | 5.41 ms | 108.52¹ | si |
| prompt: idoneita' | 4.92 ms | 5.35 | si |
| prompt: deep validation (con il sorgente) | 5.31 ms | 6.05 | si |
| progresso e albero | 0.03 ms | 0.07 | si |
| coda dependency-aware | 0.02 ms | 0.03 | si |
| Component Lab: una build | 2.47 ms | 3.80 | si |
| apply AI suggestion | 2.62 ms | 14.95 | si |
| save variant (giallo -> verde) | 4.47 ms | 4.47 | si |
| **SPECIFICA TECNICA (con la misura dei riferimenti)** | **0.75 ms** | 1.64 | si |
| **PROMPT DI IMPLEMENTAZIONE** | **1.43 ms** | 2.69 | si |
| parse dell'inviluppo | 0.16 ms | 0.54 | si |
| **STAGING DI UNA RISPOSTA (2 file, con ispezione)** | **6.64 ms** | 8.15 | si |
| validazione in processo (carica, costruisce, cerca) | 5.40 ms | 5.81 | — |
| **validazione in un sottoprocesso** | **2887.73 ms** | 3037.45 | — |
| accept: installa, reindicizza, ricalcola | 91.13 ms | 91.13 | — |
| validazione di un plugin dati (nessuna fiducia) | 65.94 ms | 75.86 | — |
| composite intermedio (emesso e installato) | 184.60 ms | 184.60 | — |
| **COMPOSITE DELLA RADICE (emesso e installato)** | **467.06 ms** | 467.06 | — |
| referto di completamento (costruisce la radice) | 127.79 ms | 172.72 | — |
| esporta la conoscenza | 0.46 ms | 0.94 | si |
| salva il progetto | 2.49 ms | 3.77 | si |
| riapri il progetto | 59.53 ms | 59.87 | — |
| `Session.shortlist(concetto)` | 4.28 ms | 13.15 | si |
| `Session.generate(concetto)` fuori da Teach | 153.41 ms | 157.28 | — |
| copertura di un secondo concetto (con la conoscenza) | 32.34 ms | 38.73 | si |

¹ il peggiore del dossier e' il primo giro: la prima build di un componente
paga l'import di `trimesh` e la costruzione dell'indice. La mediana e' la
misura.

Lettura onesta:

* **la riga che conta e' l'analisi di copertura: 29 ms** per 10 nodi su 97
  componenti, cioe' ~3 ms per nodo. Si rifa' dopo **ogni** installazione (§35),
  quindi doveva stare sotto la soglia e ci sta con margine. Il costo e' quasi
  tutto nelle interrogazioni dell'indice — cinque per nodo — piu' il calcolo
  della variabilita', che riusa `TraitResolver._matches` su 19 regole per
  candidato;
* **la specifica tecnica e' gratis (0.75 ms)** anche quando misura i
  riferimenti, perche' sul muso non ce ne sono: su un nodo con tre riferimenti
  sale a quanto costano tre build;
* **lo staging di una risposta costa 6.6 ms**, ispezione AST compresa: tra «il
  modello ha risposto» e «posso guardare il codice» non c'e' attesa;
* **il sottoprocesso costa 2.9 secondi**, cioe' 530 volte il caricamento in
  processo: e' l'avvio di un interprete piu' `trimesh`. Per questo e' spento
  per predefinito ed e' una casella;
* **il composite della radice costa 467 ms** per nove archi: emette il plugin
  con `AuthoringService`, lo valida con tutti i validatori e ricarica il
  registry. E' un gesto che si fa una volta per concetto;
* **`accept` costa 91 ms**: installa, ricarica 24+ plugin, reindicizza e
  ricalcola la copertura di tutta la gerarchia. E' il prezzo di §35, e la
  copertura ricalcolata e' 29 di quei 91;
* **la copertura di un secondo concetto costa come la prima** (32 vs 29 ms): lo
  store di conoscenza si legge una volta e la ricerca per (ruolo, nome) e'
  lineare su sei record. Con migliaia di record andra' indicizzato, ed e' fra i
  debiti.

I numeri di V5 e V6 non sono cambiati: nessuna modifica di V7 tocca il percorso
di generazione, e la sola modifica al core e' una **rimozione di duplicazione**
(§23).

---

## 22. L'audit con un modello vero (§51)

`python tools/teach_provider_audit.py dragon`. **Evidenza, non Definition of
Done**, e §51 lo chiede con queste parole. Girato una volta, con la catena di
failover configurata:

```text
pass 1: prompt di 4254 caratteri
  schema: conforme
  nodi: 13 (11 mandatory, 2 optional)

dragon / body / head / wing x2 / tail / leg x4 / claw x4 / eye x2 /
nostril x2 / tooth / scale / horn x2 (optional) / ear x2 (optional)

pass 2: prompt di 7459 caratteri
  schema: conforme
  nodi: 13
  - Merged leg and claw into a single leg component with child claw.
  - Grouped eye, nostril, tooth, horn, ear as children of head.
  - Grouped wing, tail, leg, scale as children of body.
  - Removed duplicate count nodes by consolidating counts.
  - Adjusted mandatory flags: horn and ear set to optional.

BLUE   dragon  fox_stylized:fox
YELLOW   body  humanoid:torso
YELLOW     head  creature:dragon_head
YELLOW       eye x2  humanoid:eye
RED          nostril x2
BLUE         tooth  humanoid:mouth
BLUE         horn x2  humanoid:head
YELLOW       ear x2  humanoid:ear
YELLOW     wing x2  fish:fin
YELLOW     tail  fish:tail
YELLOW     leg x4  humanoid:leg
BLUE         claw  humanoid:foot
BLUE       scale  humanoid:chest

stati: VALIDATED 0, CANDIDATE 7, MISSING 1, PROXY 5
coda: 11 nodi mandatory da costruire
copertura calcolata in 76.2 ms
prompt di implementazione per dragon.body.head.nostril: 14225 caratteri
```

Cio' che si legge, e che i test deterministici non potevano misurare:

* **entrambe le risposte sono conformi allo schema dichiarato**, verificate con
  `jsonschema` e non a occhio;
* **il pass 2 fa il lavoro che §7 descrive**, e lo dichiara: fonde il nodo
  troppo granulare, raggruppa i figli, consolida i `count`, corregge i
  mandatory. E produce un'ontologia **diversa** dalla nostra — mette ala, coda e
  zampe sotto `body` invece che sotto la radice — e il motore la gestisce senza
  una riga di differenza;
* **i quattro stati compaiono** su un'ontologia che nessuno aveva previsto, con
  `nostril` rosso e `advance()` che offre un prompt di implementazione;
* `dragon` e' **blu** con `fox_stylized:fox`: un animale quadrupede intero come
  approssimazione consapevole di un drago. E' esattamente cio' che `PROXY`
  significa, su un candidato che il filtro della radice ha ammesso perche'
  fornisce `animal`.

E cio' che e' andato storto, scritto perche' e' la parte utile: **Groq ha
rifiutato lo schema** con `400 json_validate_failed`, Gemini ha risposto `503`
e poi e' andato in timeout, Mistral `429`. La catena di failover ha trovato chi
rispondesse. Il primo e' il piu' interessante: lo schema di decomposizione e'
ricorsivo (`$ref: "#/$defs/node"`) e il backend di structured output di Groq non
lo accetta. Non e' un difetto di Teach — la modalita' esterna funziona
identica — ma e' un limite misurato, ed e' fra i debiti.

---

## 23. File modificati

Nuovi:

| File | Righe | Che cosa |
| --- | --- | --- |
| `app/teach/__init__.py` | 67 | la faccia del pacchetto |
| `app/teach/errors.py` | 59 | `TeachError` e i codici stabili |
| `app/teach/model.py` | 1079 | `TeachProject`, `TeachNode`, `NodeState`, `Candidate`, `Evidence`, `Solution`, `Progress`, `.teach3d` |
| `app/teach/schema.py` | 192 | i quattro schemi stretti |
| `app/teach/coverage.py` | 649 | le evidenze, i quattro stati, il ricalcolo |
| `app/teach/spec.py` | 517 | la specifica tecnica, il backend, la coda |
| `app/teach/contracts.py` | 245 | le API di 3DGen, **generate** leggendo 3DGen |
| `app/teach/prompts.py` | 730 | i sette prompt e il dossier |
| `app/teach/staging.py` | 732 | inviluppo, percorsi, ispezione AST, fiducia, validazione |
| `app/teach/_runner.py` | 103 | il caricamento in un sottoprocesso (robustezza) |
| `app/teach/knowledge.py` | 240 | la memoria delle validazioni, fuori da `Component` |
| `app/teach/service.py` | 1622 | le operazioni, cioe' il contratto che la UI chiama |
| `app/ui/teach_window.py` | 995 | `TeachWindow` (5 schede) |
| `tests/conftest.py` | 39 | le due fixture condivise |
| `tests/teach_fixtures.py` | 412 | le risposte AI deterministiche e un GLB vero |
| `tests/test_teach_model.py` | 521 | 58 test |
| `tests/test_teach_coverage.py` | 414 | 44 test |
| `tests/test_teach_prompts.py` | 442 | 48 test |
| `tests/test_teach_staging.py` | 577 | 81 test |
| `tests/test_teach_endtoend.py` | 742 | 43 test |
| `tests/test_teach_ui.py` | 537 | 35 test |
| `tools/teach_benchmark.py` | 300 | le misure del §21 |
| `tools/teach_provider_audit.py` | 136 | l'audit del §22 |
| `V7-RESULTS.md` | — | questo documento |

Modificati:

| File | Che cosa |
| --- | --- |
| `app/core/data_plugin.py` | le chiavi del formato dati promosse a **costanti** (`SOCKET_KEYS`, `PARAM_KEYS`, `EFFECT_KEYS`, `CHILD_KEYS`, `COMPONENT_KEYS`, `DATA_MANIFEST_KEYS`) e usate dove erano letterali |
| `app/core/registry.py` | il manifest dati legge `DATA_MANIFEST_KEYS` invece di tenerne una copia |
| `app/authoring/emit.py` | `MANIFEST_KEYS` importato da `data_plugin` invece di essere ricopiato |
| `app/ui/main_window.py` | una terza azione in barra, «Teach», sulla **stessa** `Session` |

**Niente altro nel core.** La modifica a `data_plugin.py`/`registry.py`/
`emit.py` e' una **rimozione di duplicazione**, non un'aggiunta: l'elenco delle
chiavi del formato dati era scritto in tre posti — il loader che le fa valere,
il registry che valida il manifest, l'emettitore che lo scrive — e V7 avrebbe
dovuto aggiungere il quarto, perche' deve **dire** a un modello quali chiavi
esistono. Adesso sono una tupla sola, e un test del prompt confronta il testo
generato con quella tupla.

I grep che tengono il confine:

```bash
$ grep -rn "app.teach" app/core/ app/build/ app/geometry/ app/authoring/ --include=*.py
$                                        # nessuna riga

$ grep -rn "PySide6\|QtWidgets" app/teach/
$                                        # nessuna riga

$ grep -rn "mesh_backed\|is_mesh\|kind == \"data\"" app/build/ app/core/ \
      --include=*.py | grep -v data_plugin.py | grep -v registry.py
$                                        # nessuna riga (invariato da V4)
```

---

## 24. Test

**2070 passed** (`python -m pytest -q`), da 1761. I 309 nuovi:

| file | quanti | che cosa |
| --- | --- | --- |
| `tests/test_teach_model.py` | 58 | l'identita' dei nodi (percorsi derivati dai nomi, mai id di Component, fratelli omonimi distinti, slug), i dodici import malformati piu' profondita' e dimensione, il ciclo che non si puo' esprimere e il riferimento che si rifiuta, l'import che non esegue niente, i due passi e le decisioni che sopravvivono o che si dichiarano perse, i quattro stati nel round-trip, il progresso con le due formule e il detail target, la persistenza con prompt, risposte, tentativi, artefatti e ricette, un formato sconosciuto rifiutato, il progetto senza geometria a nessuna profondita', la conoscenza che non e' un campo di `Component`, la chiave (ruolo, nome), i tre plugin di un concetto |
| `tests/test_teach_coverage.py` | 44 | lo stato letto dai nomi delle evidenze nei sei casi, nessuna quantita' di evidenza che faccia un verde, un punteggio perfetto che non fa un giallo, identita' senza contesto e contesto con somiglianza, le parole del contesto e quelle del componente, i singolari, le interrogazioni della parte distinte da quelle del concetto, il filtro della radice con `subject_capabilities`, la parte che deve potersi montare, il banco del drago con i quattro stati e i candidati veri, la lista capata e ordinata per evidenza, il ricalcolo che non tocca una soluzione ne' una decisione, una soluzione sparita che decade, la conoscenza come evidenza e non come promozione, e il grep delle parole di dominio sul **codice** di dieci moduli |
| `tests/test_teach_prompts.py` | 48 | i quattro schemi che rifiutano chiavi sconosciute e sono JSON Schema validi, il pass 1 che vieta geometria e API, le regole di granularita', il pass 2 senza id e senza stato, il prompt e lo schema che sono lo stesso oggetto, il dossier che e' metadata e non codice, `sanitize` su una descrizione ostile, l'idoneita' con i quattro stati e il divieto di validare, la deep validation con il suo tetto dichiarato, la validazione visiva senza nessuna API vision, il contratto **generato** confrontato con `dataclasses.fields`, il kernel, i tipi, l'assenza del core, le chiavi del formato dati lette dal loader, il contratto ASCII, il prompt di implementazione come contratto, l'inviluppo delimitato, un contratto per backend, i riferimenti resi con la funzione di produzione, la riparazione con le diagnostiche vere |
| `tests/test_teach_staging.py` | 81 | l'inviluppo (oggetto, testo, blocco markdown), diciassette forme malformate, undici percorsi ostili, dieci estensioni rifiutate, i tre tetti di dimensione, lo staging sotto la cartella del plugin, il manifest che non puo' rinominare il plugin, l'asset copiato byte per byte, la specie letta dai file, l'ispezione AST (import, chiamate, sintassi, `Component` di livello modulo, API inattesa, elenco configurabile), nessun messaggio che si chiami sandbox, **niente esecuzione senza fiducia** in quattro punti e misurata dal lato dell'effetto, la fiducia che sopravvive nel progetto, un plugin dati che non ha bisogno di fiducia e il cui `.py` non viene aperto, il sottoprocesso che riporta la stessa cosa e che sopravvive a un plugin che esplode, la validazione con i validatori veri, il tentativo registrato con i suoi codici, la riparazione come tentativo nuovo, l'installazione che registra la libreria e non lo staging, l'indice invalidato, il rifiuto che conserva la cronologia |
| `tests/test_teach_endtoend.py` | 43 | il banco del drago (parti, plurali in count, mandatory/optional, **copertura misurata**, coda, prossimo nodo), giallo -> verde con la variant e senza duplicare geometria, l'AI che non puo' scrivere verde nemmeno con confidenza 1.0, un parametro inventato scartato, il verdetto visivo, le varianti rese dentro gli intervalli, blu -> rosso per decisione, la specifica tecnica, le tre raccomandazioni di backend e l'override, la capability dichiarata nuova, il dato validato senza eseguire niente, il Python staged e non eseguito fino alla fiducia, l'installazione che ricalcola la copertura, **il giro completo** fino a `LEARNED`, i count nel composite, la radice senza mesh, **una Session normale che trova e costruisce il concetto**, l'export, il completamento anticipato che resta `LEARNING`, la persistenza a metà con l'artefatto ritrovato dal disco, il plugin cambiato dopo il Teach, il riuso su wyvern, nessun lavoro in background, nessun Qt, e un concetto intero insegnato senza interfaccia |
| `tests/test_teach_ui.py` | 35 | le cinque schede, il progetto che arriva al servizio, le due modalita' e il prompt che e' un oggetto, un'importazione senza prompt e una risposta rifiutata che diventano righe di stato, la tabella degli scambi, l'albero con i quattro colori e nessun verde, la barra e i conteggi letti dal servizio, il form di un nodo, la modifica che arriva al servizio, lo stato forzato e il verde rifiutato senza soluzione, l'aggiunta e la rimozione di un nodo, la tabella dei candidati, il dossier vero, i quattro prompt, il flusso giallo -> verde dalla finestra, «This Works» e «Reject», il Component Lab sul candidato scelto, la coda, il pannello della specifica, i soli backend installati, **il flusso di generazione intero dalla finestra** con il sorgente visibile prima della fiducia e il rifiuto senza di essa, la domanda che la fiducia pone, il prompt di riparazione, la tabella del completamento, il salvataggio e la riapertura, il provider che non risponde, **la finestra che non contiene logica** letta per token, e la terza porta sulla stessa `Session` |

I 53 punti della milestone, e dove sono:

| # | richiesta | dove |
| --- | --- | --- |
| 1 | dominio Teach Project separato, serializzabile | §1; `test_the_project_round_trips_with_prompts_responses_and_attempts` |
| 2 | Teach node con le informazioni equivalenti | §1; `test_a_node_carries_the_information_the_milestone_asks_for` |
| 3 | mandatory vs optional, e il completamento solo sui mandatory | §16, §20; `test_every_mandatory_node_is_green_and_the_optional_ones_do_not_block` |
| 4 | prima iterazione AI: solo decomposizione | §2; `test_the_decomposition_prompt_forbids_geometry_and_the_engine_api` |
| 5 | provider agnostic, due modalita' identiche | §2, §19; `test_the_prompt_and_the_schema_are_the_same_in_both_modes` |
| 6 | import validato, niente eseguito | §3; 14 test parametrizzati + `test_import_does_not_execute_anything` |
| 7 | seconda iterazione: raffinamento | §4; `test_the_refinement_prompt_shows_pass_one_without_the_node_ids` |
| 8 | granularita': nessuna decomposizione infinita | §4; `test_the_decomposition_prompt_carries_the_granularity_rules` |
| 9 | coverage engine sulle capacita' esistenti | §5; `test_the_dossier_says_why_3dgen_proposed_it` |
| 10 | i quattro stati di V6 | §5, §6; importati da `app/authoring/model.py` |
| 11 | la copertura non e' una soglia | §5; `test_the_state_is_read_from_the_names_of_the_evidence_not_from_a_sum` |
| 12 | candidate list | §7; `test_the_candidate_list_shows_what_the_milestone_asks_for` |
| 13 | candidate dossier, senza codice | §7; `test_the_dossier_is_metadata_and_never_source_code` |
| 14 | AI suitability validation, che non valida | §8; `test_an_ai_recommendation_can_never_write_validated` |
| 15 | deep validation con un tetto | §8; `test_the_deep_prompt_respects_a_small_limit_and_says_it_did` |
| 16 | Component Lab sul candidato | §9; `test_the_component_lab_opens_on_the_chosen_candidate` |
| 17 | visual AI prompt | §8; `test_the_visual_prompt_needs_no_new_vision_api` |
| 18 | giallo -> verde con VariantRecipe | §9; `test_a_yellow_candidate_becomes_green_through_a_variant` |
| 19 | validation memory, fuori da `Component` | §17; `test_knowledge_is_not_a_field_on_component` |
| 20 | proxy workflow | §10; `test_a_proxy_that_is_not_enough_becomes_missing` |
| 21 | missing queue dependency-aware | §10; `test_the_queue_goes_from_the_fine_parts_up_to_the_root` |
| 22 | technical component specification | §11; `test_a_missing_node_produces_a_technical_specification` |
| 23 | backend recommendation, non obbligo | §11; tre test, uno per backend |
| 24 | component prompt compiler | §12; `test_the_implementation_prompt_is_a_contract_and_not_a_request` |
| 25 | prompt per procedural Python, solo le API necessarie | §12; `test_the_python_contract_is_generated_from_the_real_dataclasses` |
| 26 | prompt per data component | §12; `test_the_data_prompt_never_asks_a_text_model_to_invent_bytes` |
| 27 | prompt per composite, preferito dichiarativo | §12; `test_each_backend_gets_its_own_contract` |
| 28 | envelope stretto | §13; 17 + 11 + 10 casi |
| 29 | staging area | §13; `test_staging_writes_the_files_under_the_declared_plugin_folder` |
| 30 | Python generato e' codice, non dati | §14; 4 test di rifiuto + 3 dal lato dell'effetto |
| 31 | ispezione statica, presentata come avvisi | §14; 7 test + `test_nothing_in_the_staging_layer_calls_itself_a_sandbox` |
| 32 | generated component validation, senza validatori nuovi | §15; `test_validation_uses_the_real_validators_and_names_what_failed` |
| 33 | render e accept/reject | §15; `test_rejecting_an_artifact_leaves_the_node_missing_and_keeps_the_history` |
| 34 | repair prompt, una per tentativo | §15; `test_a_repair_is_a_new_attempt_and_keeps_its_lineage` |
| 35 | installazione, reindex, nuova coverage | §15; `test_installing_a_component_recomputes_the_coverage` |
| 36 | loop dependency-aware, niente background | §10; `test_the_cycle_never_runs_in_the_background` |
| 37 | completion | §16; `test_finishing_early_stays_learning_and_says_what_is_missing` |
| 38 | final root component, e `Session` normale | §16; `test_a_normal_session_finds_and_builds_the_learned_concept` |
| 39 | knowledge reuse | §18; `test_a_second_concept_reuses_what_the_first_one_taught` |
| 40 | UI Teach | §19; `test_the_declared_flow_is_five_pages` |
| 41 | colori e stati | §19; `test_green_never_appears_because_a_score_is_high` |
| 42 | progress con la formula documentata | §20; `test_progress_has_two_measures_and_the_formula_is_documented` |
| 43 | manual override su tutto | §19; 5 test |
| 44 | persistenza | §1; `test_closing_halfway_and_reopening_keeps_everything` |
| 45 | riproducibilita' per fingerprint | §1; `test_a_plugin_that_changed_after_the_teach_is_detected` |
| 46 | benchmark Dragon, non manipolato | §6; `test_the_initial_coverage_is_measured_and_not_arranged` |
| 47 | yellow candidate benchmark | §9; `test_a_yellow_candidate_becomes_green_through_a_variant` |
| 48 | missing component benchmark | §15; `test_a_data_only_response_is_validated_without_executing_anything` |
| 49 | Python codegen benchmark | §14; `test_a_python_response_is_staged_but_not_run_until_trusted` |
| 50 | end-to-end benchmark | §16; `test_the_whole_cycle_ends_with_a_learned_concept` |
| 51 | optional real-provider audit | §22; `tools/teach_provider_audit.py` |
| 52 | niente fuori scope | §26 |
| 53 | output | questo documento, `PROJECT-INDEX.md`, `TODO.md` |

---

## 25. Regressioni e contratti cambiati

**Zero test rossi**, e nessun test esistente indebolito. Nessun file di test
preesistente e' stato modificato, e `tests/test_api_freeze.py` **non e' stato
toccato**: V7 non aggiunge niente alla superficie congelata di `Session`,
`Options`, `GenerationResult`, `Component`, `Piece`, `Socket`, `ParamSpec` o
`PluginInfo`.

Un cambiamento dichiarato, e non e' un'aggiunta:

**Le chiavi del formato dati sono costanti di modulo.** Erano letterali dentro
`_socket`, `_binding`, `_params`, `_attachment` e `load_component`, e lo stesso
elenco era **ricopiato** in `Registry._read_manifest` e in
`app/authoring/emit.py`. Adesso sono sei tuple in `app/core/data_plugin.py`, e
chi le fa valere, chi le emette e chi le documenta leggono le stesse. Il
comportamento e' identico — `tests/test_data_plugin.py` (101 test) passa senza
una modifica — e il motivo per cui si e' fatto adesso e' che V7 avrebbe dovuto
scriverne una quarta copia.

### Due difetti trovati e corretti scrivendo

* **L'installazione registrava due percorsi per lo stesso plugin.** Copiare lo
  staging nella libreria e poi registrare entrambe le cartelle da' lo stesso id
  da due posti, e il registry lo scarta con `DUPLICATE_PLUGIN` — correttamente.
  Si vedeva come una validazione che tornava «non ok» con un codice che non
  riguardava il componente. Corretto invertendo l'ordine: prima si copia, poi si
  registra **solo** la libreria.
* **`refresh_tree` perdeva la selezione.** Ridisegnare l'albero dopo ogni passo
  azzerava il nodo corrente, e il passo successivo non aveva un bersaglio: si
  vedeva come un bottone che non faceva niente. Corretto conservando l'id.

### Difetti preesistenti non toccati

* `MATERIAL_REDECLARED` su `tree_stylized`: invariato, e adesso compare anche
  nei referti di validazione di Teach, perche' quei referti includono quello del
  registry;
* `repair_brief` che mescola le `alternatives` fra voci dello stesso codice
  (debito 26): invariato;
* un figlio dichiarato nel piano che scompare in silenzio a `detail_level 1`
  (debito 21): invariato;
* l'impronta di contenuto ricalcolata a ogni caricamento (debito 20): adesso si
  paga anche a ogni `accept`, e con una libreria grande di componenti imparati
  sara' la prima cosa da mettere in cache;
* lo staging a freddo dell'authoring (debito 32), che `emit_composite` paga due
  volte per concetto.

---

## 26. Definition of Done

| # | Criterio | Esito |
| --- | --- | --- |
| 1 | suite completa verde | ✅ **2070 passed** (erano 1761) |
| 2 | un concetto si decompone via prompt/schema in una hierarchy Teach | ✅ §2, §3 |
| 3 | il refinement pass funziona | ✅ §4: 11 nodi -> 10, plurali in `count`, `claw` fuso |
| 4 | coverage produce VALIDATED/CANDIDATE/PROXY/MISSING | ✅ §5, §6: tutti e quattro sul drago reale |
| 5 | un candidato giallo si analizza e si apre nel Component Lab | ✅ §7, §9 |
| 6 | una VariantRecipe lo trasforma in soluzione validata | ✅ §9: `dragon_eye`, < 700 byte, nessun `.glb` |
| 7 | un nodo missing produce una specifica tecnica | ✅ §11 |
| 8 | da quella spec si genera un prompt implementativo | ✅ §12: 14055 caratteri di contratto |
| 9 | un response AI esterno si importa in staging | ✅ §13 |
| 10 | data-only si valida senza esecuzione | ✅ §14: 12 triangoli, `boom.py` mai aperto |
| 11 | Python NON viene eseguito senza trust esplicito | ✅ §14: 4 rifiuti + 3 misure dal lato dell'effetto |
| 12 | un componente accettato si installa e il SemanticIndex si aggiorna | ✅ §15 |
| 13 | la coverage si ricalcola dopo ogni installazione | ✅ §15: `analyse()` dentro `accept_artifact` |
| 14 | il workflow procede dependency-aware dai pezzi ai composite | ✅ §10 |
| 15 | tutti i mandatory green rendono il concetto `LEARNED` | ✅ §16, con un optional rosso |
| 16 | il root composite viene installato | ✅ §16: `dragon_pack:dragon`, nessuna mesh propria |
| 17 | una normale Session trova e costruisce quel concetto | ✅ §16: `generate("a cartoon dragon")`, planner locale |
| 18 | tutto persistibile/riprendibile | ✅ §1: a metà, con l'artefatto ritrovato dal disco |
| 19 | l'utente puo' sovrascrivere ogni decisione AI | ✅ §19: 5 test, compreso verde -> giallo |
| 20 | nessuna conoscenza di dominio «dragon» nel core | ✅ §5: grep sul **codice** di dieci moduli, piu' i tre grep del §23 |

Fuori scope e **non iniziati**, come chiesto (§52): marketplace, cloud
execution, background jobs, cicli autonomi infiniti, fiducia automatica del
Python, sandbox finta, generazione neurale di mesh, generazione automatica di
GLB da testo, face segmentation automatica, rig, animation authoring,
`Session.modify`, plugin store, agent swarm permanente. E non sono stati
generati componenti artistici per riempire il drago: il banco dimostra il
workflow, e la libreria installata resta 23 plugin e 97 componenti.

---

## 27. Debiti verso V8

* **Lo schema ricorsivo non passa per tutti i backend di structured output.**
  Groq risponde `400 json_validate_failed` sullo schema di decomposizione, che
  usa `$ref: "#/$defs/node"`. La modalita' esterna funziona identica, e la via
  dichiarata e' uno schema «appiattito» a profondita' fissa come **variante**
  per i provider che non accettano la ricorsione — non la sostituzione di quello
  vero, perche' un'ontologia non ha una profondita' nota.
* **Il `MockPlanner` non sceglie un composite imparato per un prompt
  qualunque.** Lo trova perche' il nome combacia («a cartoon dragon» ->
  `dragon_pack:dragon`); un prompt che dice la stessa cosa con altre parole
  («a winged fire-breathing reptile») dipende dai sinonimi che il manifest
  dichiara. `emit_composite` dichiara un solo ponte — il nome del concetto — e
  dichiararne di piu' vorrebbe dire chiedere all'utente quali, che e' una
  domanda ragionevole e non e' stata fatta.
* **La disposizione degli innesti di un composite e' una convenzione.** Si
  distribuiscono su una circonferenza guardando verso l'esterno: strutturalmente
  corretto, visivamente mediocre, ed e' la stessa distinzione che `TODO` fa al
  punto 4-bis fra correttezza strutturale e qualita' di layout. La via e'
  dichiarare `LayoutRegion` sul composite, che `AuthoringService` sa gia' fare e
  che nessuno gli chiede da qui.
* **La validazione di un componente generato non lo prova sul padre.** Si
  carica, si costruisce, si misura e si cerca — da solo. La compatibilita' con
  il padre e con i figli la esercita il composite quando viene emesso, cioe' piu'
  tardi. Provarla subito vorrebbe dire costruire un piano `padre + figlio` dentro
  la validazione, ed e' il prossimo passo evidente.
* **Lo store di conoscenza e' lineare.** Sei record si cercano in niente;
  migliaia andranno indicizzati per (ruolo, nome), e la domanda vera e' se lo
  store debba diventare un `Corpus` dell'indice semantico — che sarebbe la
  risposta coerente con la regola 10 — invece di una tabella.
* **Un record di validazione non sa quando e' scaduto.** Registra il plugin ma
  non la sua impronta, quindi un `creature:bulging_eye` cambiato dopo resta un
  `prior_validation` valido. `changed_components()` lo rileva **dentro** un
  progetto; lo store non lo fa, e dovrebbe.
* **Il sottoprocesso costa 2.9 secondi.** E' l'avvio di un interprete piu'
  `trimesh`. Un processo di servizio riusato fra le validazioni lo
  ammortizzerebbe, e il motivo per cui non c'e' e' che un processo che resta
  vivo e che ha importato codice generato e' esattamente la cosa che §30 chiede
  di non avere per sbaglio.
* **`emit_composite` paga lo staging dell'authoring due volte per concetto**
  (debito 32 di V6, ora piu' visibile): 184 ms per il composite intermedio, 467
  per la radice. La via resta la stessa: riemettere solo i file cambiati.
* **Il `detail_target` non si puo' alzare dopo l'analisi senza rifare la
  coda.** Funziona — `project.detail_target = 3` e la copertura si ricalcola —
  ma i nodi che diventano rilevanti partono da zero, e nessuna diagnostica lo
  dice. E' la stessa famiglia del `TEACH_DECISION_LOST`, dal lato opposto.
* **Il debito 12 di `PROJECT-INDEX` resta aperto.** Il filtro di rilevanza del
  vocabolario mostra un trait quando un pezzo **della rosa** soddisfa il
  bersaglio della sua regola; il Component Lab fa la domanda giusta (V6 §13) e
  adesso anche la copertura di Teach la fa giusta per i soggetti (il debito 13).
  Nel vocabolario la correzione resta seguire gli `Attachment` dichiarati in
  modo transitivo.
* **Nessun plugin imparato e' entrato nella libreria installata.** Come in V4,
  V5 e V6: i plugin di V7 nascono nei test e in cartelle temporanee, e la
  libreria resta 23 plugin e 97 componenti, tutti di codice. Il giorno in cui un
  drago imparato entra in `app/plugins/` sara' una milestone di contenuto con la
  sua misura — ed e' anche il modo di scoprire quali parti di questo strumento
  sono davvero fastidiose.
* **I debiti di V6 restano tutti**: il gizmo che non si trascina, la selezione
  per nodo e non per facce, il plugin riaperto che non recupera la selezione,
  la variant con trait che non si incorpora, lo staging a freddo, l'impronta di
  contenuto ricalcolata. E quelli di V5, V4, V3.5 e V3: il conflitto fra un
  trait generico `subtree` e uno selettivo, un parametro dati che pilota solo
  knob numerici, i 259 ruoli semantici non riassegnati, 18 plugin su 23 senza
  frame, il frame che non converte, `repair_brief` che mescola le alternative,
  il retrieval che mette le parti davanti agli interi nel **vocabolario**, il
  `MockPlanner` che non scrive trait strutturali, `fx:bend` con `scope: "model"`
  che si perde, un figlio che scompare a `detail_level 1`.

---

## 28. Riprodurre le misure

```bash
python -m pytest -q                                  # 2070 passed
python -m pytest -q tests/test_teach_model.py        # i 58 del modello
python -m pytest -q tests/test_teach_coverage.py     # i 44 della copertura
python -m pytest -q tests/test_teach_prompts.py      # i 48 dei prompt
python -m pytest -q tests/test_teach_staging.py      # gli 81 dello staging
python -m pytest -q tests/test_teach_endtoend.py     # i 43 del giro completo
python -m pytest -q tests/test_teach_ui.py           # i 35 della finestra
python tools/teach_benchmark.py 7                    # la tabella del §21
python tools/teach_provider_audit.py dragon          # l'audit del §22
```

I contratti, letti dal codice invece che da questo documento:

```bash
grep -rn "app.teach" app/core/ app/build/ app/geometry/ app/authoring/ --include=*.py
grep -rn "PySide6\|QtWidgets" app/teach/
grep -rn "mesh_backed\|is_mesh\|kind == \"data\"" app/build/ app/core/ --include=*.py \
  | grep -v data_plugin.py | grep -v registry.py
```

Il contratto che un modello riceve, stampato:

```bash
python -c "
from app.teach.contracts import python_contract, data_contract, composite_contract
print(python_contract()); print(); print(data_contract())"
```

Un concetto imparato per intero senza aprire una finestra, su disco da
ispezionare a mano:

```bash
python -c "
import sys, tempfile; sys.path[:0] = ['.']
from pathlib import Path
from app.ai.provider import OfflineProvider
from app.core.session import Options, Session
from app.teach import TeachService, tree_text
from tests.teach_fixtures import *
tmp = Path(tempfile.mkdtemp())
session = Session(provider=OfflineProvider())
svc = TeachService(session=session, staging_root=tmp / 'staging')
svc.create_project('dragon', style_target='cartoon low-poly',
                   detail_target=2, destination=str(tmp / 'library'))
svc.decomposition_prompt(); svc.import_decomposition(dragon_decomposition())
svc.refinement_prompt();    svc.import_refinement(dragon_refinement())
svc.analyse()
print(tree_text(svc.project))
eye = svc.candidates('dragon.head.eye')[0].component_id
svc.suitability_prompt('dragon.head.eye', eye)
svc.import_suitability('dragon.head.eye',
                       suitable_with_parameters({'size': 0.12}),
                       component_id=eye)
svc.apply_suggestion('dragon.head.eye', eye)
svc.save_variant('dragon.head.eye', 'dragon_eye', component_id=eye)
for proxy in ('dragon.body', 'dragon.wing', 'dragon.leg', 'dragon.tail'):
    svc.accept_candidate(proxy, svc.candidates(proxy)[0].component_id)
for c in list(svc.candidates('dragon.head.snout')):
    svc.reject_candidate('dragon.head.snout', c.component_id)
spec = svc.spec('dragon.head.snout')
print(svc.implementation_prompt('dragon.head.snout').text[:2000])
a = svc.import_implementation('dragon.head.snout',
        python_component(spec.plugin_id, 'snout',
                         capability=spec.provides[0], role='snout'))
svc.trust_artifact(a.id); svc.validate_artifact(a.id); svc.accept_artifact(a.id)
svc.emit_composite('dragon.head'); svc.emit_composite()
print(svc.finish().describe())
print(session.shortlist('dragon').ids[:3])
print(session.generate('a cartoon dragon', Options(detail_level=2)).describe())
print(svc.save_project(tmp / 'dragon'))"
```

E la finestra, per guardarla:

```bash
python -c "
from PySide6.QtWidgets import QApplication
from app.ui.viewport import configure_opengl
configure_opengl(); app = QApplication([])
from app.ui.teach_window import TeachWindow
w = TeachWindow(); w.show(); app.exec()"
```
