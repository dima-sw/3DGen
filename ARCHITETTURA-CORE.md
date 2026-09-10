# 3DGen — motore universale di composizione: analisi e proposta

Risposta alla specifica architetturale. Contiene: cosa della specifica reggo e
cosa contesto, l'analisi del repository esistente (riuso / generalizza / sposta
/ elimina), il modello dati proposto, la struttura delle directory, le API, il
formato del composition graph, registry, resolver, pipeline degli effetti e
test.

Stato del repo al momento dell'analisi: **762 casi di test verdi**, 503
funzioni, 13.100 righe in `app/`.

---

## 1. Giudizio sulla specifica

### Quello che regge, e va adottato così com'è

**Il principio centrale è giusto.** «3DGen non genera categorie di oggetti,
genera grafi di componenti compatibili» è la formulazione corretta, ed è la
stessa cosa che il progetto ha già dimostrato di saper fare quando ha prodotto
"un pesce con il corpo di una persona e quattro braccia" senza un template per
quella combinazione.

**Capability e socket al posto dei nomi (§15, §16, §57).** Questo non è
teorico: un'ora fa, per attaccare le braccia dell'umanoide a un torso preso da
un altro plugin, ho dovuto scrivere `find_socket` che cerca **per tipo e lato**
perché un corpo di pesce non ha un socket chiamato `shoulder_l`. La specifica
arriva alla stessa conclusione per la stessa ragione.

**Core = contratto, plugin = implementazione (§84, §93).** È il punto più
importante di tutto il documento. Il core non deve imporre `ring + sweep`: deve
imporre *cosa* una parte deve restituire, non *come* lo costruisce. L'attuale
`PartRule.build` è già una funzione qualsiasi, quindi su questo siamo allineati
per caso — ma va reso esplicito e documentato.

**Più implementazioni dello stesso concetto (§82, §91).**
`humanoid_lowpoly`, `humanoid_realistic` e `dragon` che dichiarano tutti di
fornire `head_mount`. Corretto, e sblocca il futuro senza costare niente adesso.

**Terminazione a budget invece che a profondità fissa (§9, §54).** Ho un
`MAX_DEPTH = 8` nel builder ed è un cerotto. Budget di triangoli, di tempo e di
espansione sono il criterio giusto; la profondità massima resta solo come
salvagente contro i cicli.

**Errori diagnostici con alternative (§72).** Sottovalutato nella specifica ma
prezioso: è quello che rende possibile la singola correzione dell'LLM senza un
ciclo di giudizio visivo.

**Determinismo e hash stabile (§51).** Già corretto oggi: `hash()` di Python
sulle stringhe è randomizzato per processo, l'ho trovato e sostituito con CRC32.

### Quello che contesto

**a) `Decoration` come primitiva separata è duplicazione.**

La specifica dice (§12, §13) che una decoration può contenere componenti e
altre decoration, può essere applicata a qualsiasi componente compatibile, e ha
socket propri. A quel punto **è un Component**. Le differenze reali sono tre, e
sono tutte e tre proprietà dell'*attacco*, non del tipo:

| differenza | dove sta davvero |
|---|---|
| è facoltativa | `Attachment.optional` |
| non compare con il `detail_level`, ma su richiesta | `Attachment.on_request` |
| non sostituisce mai il genitore | `Attachment.replaces = False` |

Tenerle separate significa duplicare tutta la macchina della ricorsione,
dell'espansione, dei socket e degli effetti. **Proposta: una primitiva sola,
`Component`, più un `Attachment` che porta quei tre flag.** Tutto il
comportamento descritto nella specifica resta possibile, con metà del codice —
compreso `Head → Helmet → Visor → Light`, che diventa semplicemente un albero
di componenti con attacchi facoltativi.

**b) Il sistema di relazioni (§60) è un risolutore di vincoli, e non serve
ancora.**

`relative_to`, `align_with`, `scale_to`, `center_on`, `mirror_of`, `follow`,
`attach_to`, `offset_from`: otto verbi sono un mini-CAD. Il caso che la
specifica porta a esempio — `planet.scale = house.width * 1.5` — è coperto dai
**parametri derivati** (§19), che sono molto meno lavoro e che il progetto ha
già in forma sicura (valutatore di espressioni con AST su lista bianca, in
`app/geometry/recipe.py`). Propongo: parametri derivati subito, verbi di
relazione **quando un caso reale li chiederà**. Costruire un solver che nessuno
usa è il modo classico di bloccarsi per un mese.

**c) SQLite per il registry (§35) è prematuro.**

Un indice in memoria costruito all'avvio dai manifest regge comodamente da 10 a
10.000 componenti. Un database aggiunge uno schema da migrare e un secondo
punto di verità. Se un giorno l'avvio diventa lento, si aggiunge una cache su
disco — che è una decisione reversibile, mentre uno schema no.

**d) «Non creare un sistema parallelo» (§68) è giusto, ma oggi il sistema
parallelo *esiste già* — e la specifica non dice come chiuderlo.**

Questo è il punto su cui vale la pena essere scomodi. Nel repo convivono:

| | vecchio | nuovo |
|---|---|---|
| forma | SDF + marching cubes + decimazione | kernel poligonale |
| composizione | `app/geometry/composition.py` | `app/plugins/build.py` |
| parti | `app/geometry/parts/*.json` + `recipe.py` | `PartRule` in Python |
| chi lo usa | planner, prompts, builder, validation, **i 5 banchi** | solo `test_plugins.py` |

I 5 banchi di prova e circa 300 test stanno **sul vecchio**. Non si può
sostituirlo in un passo senza spegnere metà della suite. Quindi un periodo di
transizione è inevitabile: la domanda vera non è *se* ci sarà, ma **come si
garantisce che finisca**. Propongo la regola operativa al § 8 di questo
documento: nessun modulo nuovo può importare il vecchio percorso, e i banchi
migrano uno alla volta con il vecchio che viene rimosso nello stesso passo.

**e) I cinque casi del vertical slice (§77) non provano tutti la stessa cosa.**

- **Caso A** (umanoide + testa di rana + gambe di spada) prova: swap
  cross-plugin, risoluzione per capability, sostituzione strutturale.
- **Caso B** (casa + pianeta) prova: composizione non antropocentrica,
  scala relativa fra componenti di plugin diversi, socket generico di
  superficie.
- **Casi C, D, E** aggiungono *contenuto*, non architettura: se A e B
  funzionano, C/D/E funzionano per costruzione.

Propongo di implementare **A e B** come vertical slice, e di tenere C/D/E come
banchi da riempire man mano che i plugin esistono. Fare otto plugin prima di
avere le fondamenta è esattamente l'errore che la specifica stessa mette in
guardia al §64.

### Due cose che la specifica non dice, e che servono

**f) Riconciliazione della scala fra plugin.** Una testa di drago costruita con
le sue misure non sta su un collo umano. Il socket dice *dove* e *in che verso*,
non *quanto grande*. Serve una modalità dichiarata sull'attacco — «tieni le tue
misure» oppure «portati al raggio dell'innesto» — altrimenti ogni swap
cross-plugin produce un mostro fuori scala. L'ho già incontrato e risolto oggi
(`scale_mode`), ma va messo nel contratto.

**g) Convenzione di orientamento.** Oggi il catalogo assume «ogni parte cresce
lungo +X dalla propria base, con il dorso verso +Y». Se un plugin di terze parti
non lo sa, le sue parti si attaccano ruotate. Poche ore fa ho perso tempo su un
piede che sporgeva di lato perché nel sistema locale della gamba il "davanti"
era +Y e non +Z. **La convenzione va scritta nel contratto e verificata da un
test**, non lasciata al buon senso di chi scrive il plugin.

---

## 2. Analisi del repository

### Riusabile così com'è (nessuna modifica)

| modulo | perché |
|---|---|
| `app/geometry/kernel.py` | costruzione poligonale, già generica: `ring`, `sweep`, `grow`, `block`, `faces_per_normal` |
| `app/geometry/lowpoly.py` | decimazione a errore quadrico, indipendente dal dominio |
| `app/geometry/surface.py` | marching cubes, resta come strumento per l'SDF |
| `app/build/visual.py` | quality gate visivo: silhouette, riempimento, parti visibili |
| `app/anim/` | scheletro dal grafo, animazione rigida, glTF composto a mano |
| `app/core/project.py`, `recovery.py`, `hardware.py` | infrastruttura, nessun legame con la geometria |
| `app/assets/`, `app/materials/` | libreria e finiture |

### Da generalizzare (buona sostanza, contratto troppo stretto)

| oggi | problema | dove va |
|---|---|---|
| `Socket` in `geometry/recipe.py` | ottimo (posizione, direzione, **up**, raggio, kind) ma sepolto nel modulo delle ricette SDF | `core/socket.py`, più `capability` e `side` |
| `Placement` + `attachment_placement` in `geometry/composition.py` | già geometria-agnostico, usato da entrambi i sistemi | `core/socket.py` |
| valutatore di espressioni in `geometry/recipe.py` | AST su lista bianca, sicuro | `core/params.py`, diventa il motore dei parametri derivati |
| `app/core/style.py` | profilo unico cartoon | `StyleProfile` plurale, registrabile dai plugin |
| `app/plugins/base.py` | `PartRule`/`Child`/`Slot` sono già la forma giusta | diventa `core/component.py` con capability e attachment |
| `app/plugins/build.py` | il walk ricorsivo funziona | si separa in `resolver` (chi con chi) e `builder` (come) |
| `app/build/validation.py` | regole semantiche buone, ma cablate su classi ("fish", "humanoid") | vincoli **dichiarati dal componente** |

### Da spostare dentro un plugin

| oggi in core | dove va |
|---|---|
| `app/ai/creature.py` (archetipi, preset di specie, tabelle corpo/testa/coda) | `plugins/creature/` |
| `app/geometry/templates/*.py` (veicolo, casa, arma, mobili, natura, personaggio) | `plugins/vehicle/`, `plugins/architecture/`, `plugins/weapon/`, … |
| `app/geometry/parts/*.json` (9 ricette organiche) | `plugins/creature/components/` |
| `app/geometry/templates/humanoid_body.py` | `plugins/humanoid/` |
| `APPENDAGE_RATIO`, `RULES` per classe semantica in `validation.py` | vincoli dei rispettivi componenti |

### Da eliminare quando la migrazione è completa

| cosa | quando |
|---|---|
| `app/build/builder.py` percorso template | quando i template sono plugin |
| `app/build/strategy.py` (4 strategie) | il resolver le sostituisce |
| `STYLE_DENSITY`, i residui dei quattro stili | subito: già ridotti a densità |
| il ramo di composizione per fusione SDF in `composition.py` | quando i banchi 3-5 girano sul kernel |
| `MAX_DEPTH = 8` | quando c'è il budget |
| `app/ai/shape_match.py` | il riconoscimento per sagoma vale poco con uno stile unico |

**Non si elimina niente prima che il sostituto passi gli stessi test.**

---

## 3. Modello dati proposto

Undici primitive. Nessuna nomina una categoria del mondo.

```
Capability   un contratto nominato: "head_mount", "limb_mount", "surface",
             "decoration_anchor". Stringa + tag, niente gerarchia obbligatoria.

Socket       dove ci si attacca: posizione, direzione, up, raggio, side, e le
             capability che FORNISCE. Vive nello spazio locale del componente.

Requirement  cosa un attacco CERCA: capability, side preferito, vincoli di
             scala. È l'altra metà del contratto.

ParamSpec    parametro tipato: tipo, default, min, max, unità, ruolo semantico,
             se derivato (espressione).

Expression   valore derivato, valutato su uno scope (self, parent, root) con un
             linguaggio ristretto. Nessun codice arbitrario.

Constraint   regola dichiarativa sui parametri risolti, con messaggio.

Component    una regola che, dati i parametri, produce: mesh (o niente),
             socket, figli, effetti propri, vincoli. Il COME è del plugin.

Attachment   come un figlio sta appeso: socket o requirement, insert,
             scale_mode, roll, e i tre flag — optional, on_request, replaces.

Effect       trasformazione dichiarativa: tipo, scope, parametri con range,
             stadio della pipeline, conflitti.

StyleProfile budget, proporzioni ammesse, tolleranze, materiali, aspettative
             di topologia.

Plugin       manifest + componenti + effetti + stili + capability fornite.
```

E sopra:

```
CompositionNode / CompositionGraph   il piano
Registry                             l'indice interrogabile
Resolver                             grafo + registry -> grafo risolto
Builder                              grafo risolto -> mesh
```

**Decoration non è una primitiva.** È un `Component` attaccato con
`Attachment(optional=True, on_request=True, replaces=False)` su un socket che
fornisce `decoration_anchor`. Tutto ciò che la specifica descrive resta
esprimibile — inclusa una decoration che contiene componenti e altre
decoration, perché è un componente e i componenti si annidano già.

---

## 4. Struttura delle directory

```
app/
  core/                 SOLO contratti. Nessuna geometria, nessun nome di categoria.
    capability.py         Capability, Requirement, compatibilità
    socket.py             Socket, Placement, attachment_placement   [da geometry/]
    params.py             ParamSpec, tipi, resolve, espressioni     [da recipe.py]
    constraints.py        Constraint e valutazione
    component.py          Component, Attachment, Piece
    effect.py             EffectSpec, Scope, stadi, ordinamento
    style.py              StyleProfile (registrabile)               [generalizza]
    graph.py              CompositionNode, CompositionGraph, cicli
    registry.py           indice e query
    resolver.py           risoluzione socket/capability/implementazioni
    budget.py             triangoli, tempo, espansione
    errors.py             diagnostica strutturata
    session.py            unica porta per UI e CLI                  [esiste]

  geometry/             STRUMENTI che un plugin PUÒ usare. Nessun obbligo.
    kernel.py             poligonale: ring, sweep, grow, block      [esiste]
    sdf.py                impliciti: boolean, organico              [esiste]
    surface.py            marching cubes                            [esiste]
    lowpoly.py            decimazione a errore quadrico             [esiste]

  build/
    builder.py            grafo risolto -> mesh
    validate.py           pipeline di validazione
    visual.py             quality gate visivo                       [esiste]

  plugins/
    humanoid/             plugin.py + components/
    creature/
    architecture/
    weapon/
    accessories/

  ai/                   planner e prompt costruiti DAL registry
  anim/  ui/  assets/  materials/
```

Regola strutturale, verificabile con un test: **nessun file sotto `app/core/`
può nominare un plugin o una categoria del mondo.**

---

## 5. Composition graph

```json
{
  "version": "1.0",
  "style": "low_poly",
  "detail_level": 3,
  "seed": 481516,
  "budget": { "triangles": 8000, "seconds": 5 },

  "root": {
    "id": "corpo",
    "ref": "humanoid:humanoid",
    "params": { "height": 1.85 },

    "children": [
      { "id": "testa", "ref": "amphibian:frog_head",
        "at": { "capability": "head_mount" }, "scale_mode": "socket" },

      { "id": "gamba_l", "ref": "weapon:sword",
        "at": { "capability": "limb_mount", "side": "l" },
        "replaces": "gamba_l", "scale_mode": "socket" },

      { "id": "piercing", "ref": "accessories:piercing",
        "on": "testa/naso", "at": { "capability": "decoration_anchor" },
        "optional": true }
    ],

    "effects": [
      { "type": "lanky",  "scope": "model",     "amount": 0.9 },
      { "type": "bend",   "scope": "role:tail", "axis": "X", "amount": 0.35 }
    ]
  }
}
```

Decisioni, e il perché:

- **`ref` sempre qualificato** `plugin:component`. Nessuna ambiguità, e il
  registry può dire subito se manca.
- **`at` è una query, non un nome.** Copre l'ordine di risoluzione del §16
  senza casi speciali: se c'è `"socket": "neck"` si prova prima quello.
- **`on` indirizza per percorso** (`testa/naso`), così una decorazione profonda
  non obbliga ad annidare il JSON fino a lì. Serve al §55: un piercing su una
  testa semplice senza dover alzare il `detail_level` di tutto l'albero.
- **`replaces` nomina il figlio sostituito**, che è diverso da `params` che
  cambia solo una misura (§56).
- **`scale_mode`** è il punto (f) del § 1: senza, ogni swap fra plugin sballa.

### La sostituzione è tracciabile nel piano, singola nel risolto

Uno swap conserva due informazioni — cosa era e cosa è diventato — e produce
**un solo componente**:

| livello | contenuto | quante cose |
|---|---|---|
| piano | `Humanoid.Head` + swap → `Dragon.Head` | due, per il debug |
| risolto | `Dragon.Head` | una |
| geometria | una testa | una mesh |

`Humanoid.Head` e `Dragon.Head` non coesistono mai come geometria: dopo lo swap
il componente di partenza non viene più costruito né interrogato per i socket, e
il piano non guadagna un nodo (`len(graph)` non cambia). Quello che resta è il
nome in `node.ref` e la coppia `from`/`to` nel registro delle operazioni.

In codice: `graph.providers()` è la vista che il builder deve usare — un nodo,
un `ref` — mentre `graph.swapped()` dà le coppie `(da, a)` per la diagnostica.
Chi vuole *entrambe* le teste non fa uno swap: chiama `attach`, che aggiunge un
nodo. Sono due intenzioni diverse e restano due chiamate diverse.

---

## 6. Plugin

```
plugins/magical_crystals/
    plugin.json            manifest: id, versione, capability, tag, dipendenze
    components/            un file per componente, o un modulo Python
    effects/
    styles/
```

Un componente può essere **dati** (JSON con profilo e socket, per le forme
regolari) oppure **codice** (una funzione che emette una mesh, per tutto il
resto). Il contratto è l'output, non il metodo:

```python
def build(params: dict, ctx: BuildContext) -> Piece
```

`Piece` = mesh (o `None`) + socket + materiale + tag. Il core non guarda dentro.

Perché entrambi: una lama o un pilastro sono una tabella di sezioni, e in JSON
si leggono meglio; una mano con le dita, o un albero ricorsivo, in JSON
diventano illeggibili. Costringere tutto in JSON produce un linguaggio di
programmazione mascherato da dati — che è il difetto che le ricette attuali
stanno già cominciando ad avere.

---

## 7. Registry, Resolver, Effetti

### Registry — implementato al passo 3

Indice in memoria, costruito dai manifest. Query:

```python
registry.component("humanoid:head")
registry.providers(capability="head_mount", tags={"dragon"})   # tutti, non il migliore
registry.socket_providers("head_mount", side="l")              # chi ha l'innesto
registry.effects_for(capability="cosa")                        # effetti applicabili
registry.search("testa di rana")        # id + nome + descrizione + tag
```

L'ultima è quella che alimenta il prompt di sistema: **l'LLM vede solo ciò che
il registry dichiara.**

Il manifest reale (`plugin.json`) dichiara **quali file** contengono il
vocabolario, non che cosa contengono: aggiungere un componente non obbliga a
tenere allineate due descrizioni.

```json
{
  "id": "primitives", "version": "1.0.0", "name": "Primitives",
  "description": "…", "author": "…", "license": "MIT", "homepage": "…",
  "tags": ["primitive"],
  "components": ["components/solids.py"],
  "effects": [], "styles": [],
  "capabilities": [ { "name": "end_mount", "description": "…", "tags": [] } ],
  "dependencies": [], "metadata": {}
}
```

Un modulo dichiara i suoi `Component`, `EffectSpec` e `StyleProfile` a livello
di modulo e basta: nessuna funzione `register()`, nessun decoratore. Gli id si
scrivono nudi (`"block"`) e il registry li qualifica (`primitives:block`);
scrivere l'id di un altro plugin è rifiutato.

**Cosa un componente dichiara a freddo.** I socket veri nascono dentro `build`
e portano posizione e raggio: informazioni che esistono solo con la geometria.
Per indicizzare senza costruire, `Component.mounts` dichiara la metà non
geometrica — capability, socket_id, lato, tag (`Mount`). È una promessa che può
divergere dalla realtà: verificarla tocca al build layer, che ha in mano il
`Piece`.

### Resolver — implementato al passo 4

Due domande separate, in quest'ordine — ed è la distinzione su cui gira tutto:

```
1. il PADRE ha un innesto che soddisfa il requisito?    Component.mounts
2. il FIGLIO sa riempire quell'innesto?                 Component.provides
```

Invertirle sembra indifferente e non lo è: un torso che *fornisce* `head_mount`
vorrebbe dire che il torso **è** una testa. `providers()` nel registry unisce i
due lati per comodità di ricerca; il resolver li tiene distinti perché lì la
direzione decide chi va dentro chi.

**Ordine di risoluzione dell'attacco**

1. id di socket esatto
2. capability + side
3. capability + tag compatibili
4. capability
5. qualunque socket che accetti il requirement
6. **fallimento diagnostico**, con le alternative:

```
Non posso attaccare 'dragon:head' a 'architecture:window_frame'.
  richiede:  head_mount
  disponibili su window_frame:  window_mount, decoration_anchor
  alternative che forniscono head_mount:
      humanoid:neck, creature:neck, dragon:neck
```

Serve all'utente e serve alla singola correzione dell'LLM.

**La scelta dell'innesto, in ordine di criterio.** Il punteggio da solo non
basta: due innesti possono valere uguale e non essere intercambiabili.

| # | criterio | perché |
|---|---|---|
| 1 | compatibile | un innesto che non accetta il requisito non è un'alternativa, per quanto sia libero |
| 2 | libero | due pezzi nello stesso posto sono due pezzi compenetrati, e non si vede finché non si guarda |
| 3 | punteggio | la scala dei cinque livelli qui sopra |
| 4 | tag in comune | `spalla_l` e `anca_l` sono entrambi arti a sinistra: senza i tag il braccio finisce dove va la gamba |
| 5 | il figlio lo sa riempire | risolve i pareggi con l'unica informazione pertinente |
| 6 | il nome | perché niente resti al caso |

**Cosa il resolver non decide.** Un socket vero ha posizione, verso e raggio, e
nasce dentro `build`. Il resolver vede solo le dichiarazioni (`Component.mounts`)
e quindi risponde a *chi si collega a chi*; *dove esattamente, come, con che
scala* è del builder. `scale_mode` viene conservato, non applicato.

**Debito noto per il build layer:** `Component.mounts` è una promessa,
`Piece.sockets` è il fatto. Quando il builder avrà il `Piece` in mano dovrà
confrontarli e diagnosticare la divergenza — un componente che dichiara
`head_mount` e poi non lo costruisce. Non è una verifica del resolver: qui il
`Piece` non esiste ancora.

### Pipeline degli effetti — stadi espliciti

| stadio | agisce su | esempi |
|---|---|---|
| 1 strutturale | grafo | swap, replace, count |
| 2 proporzione | **parametri**, prima della geometria | lanky, chibi, eroico |
| 3 deformazione locale | vertici di una parte | bend, twist, taper |
| 4 deformazione globale | vertici del modello | shear, perspective_exaggeration |
| 5 esagerazione di stile | vertici | cartoon_exaggeration |
| 6 posa finale | trasformazioni | grounding, centratura |

La distinzione fra **2** e **3-5** è la chiave: le proporzioni cambiano *cosa
si costruisce*, le deformazioni cambiano *ciò che è stato costruito*. Confonderle
è ciò che ha fatto esplodere il chibi ieri.

Ogni stadio è ordinato in modo deterministico; dentro uno stadio, per priorità
e poi per `id` dell'effetto. Mai per ordine di dizionario.

**Una volta per responsabilità (§29):** un effetto di proporzione si applica al
primo antenato che porta quel ruolo. Già implementato e coperto da test.

### Dove finisce il passo 5

I due stadi che vengono **prima della geometria** si applicano subito: i
parametri esistono già. I quattro geometrici si **programmano** — la mesh non
c'è ancora, e inventarla per poterla deformare sarebbe sbagliare due volte. Il
builder riceverà un elenco ordinato di operazioni con i bersagli già risolti e i
numeri già validati.

```
ResolvedComposition  ->  EffectPipeline  ->  EffectedComposition
                                              .applied   parametri già cambiati
                                              .planned   istruzioni per il builder
```

**Ricalcolo dei derivati.** Dopo un effetto di proporzione i parametri derivati
si ricalcolano: `porta.altezza = parent.altezza * 0.5` era stata calcolata prima
che l'effetto alzasse la casa, e senza il ricalcolo la casa cresce intorno a una
porta rimasta com'era. Un parametro che un effetto ha toccato **non** si
ricalcola: la decisione più recente vince.

**Un effetto dichiara come cambia un parametro, non lo programma.** `ParamRule`
punta a un **ruolo semantico** (`length`, `girth`), non a un nome: un effetto che
allunga non deve sapere che in un plugin il parametro si chiama `length` e in un
altro `lunghezza_totale`. Il risultato ripassa sempre dal `ParamSpec` — un
effetto può spingere, non sfondare.

**Conflitti.** Due effetti dichiarati incompatibili si scartano **entrambi**, con
`EFFECT_CONFLICT`. Tenerne uno vorrebbe dire scegliere al posto di chi ha scritto
il piano, e nessuno dei due è più voluto dell'altro.

---

## 8. Regola per non restare con due sistemi

Il rischio vero non è progettare male: è restare per sempre a metà. Tre regole
operative, verificabili:

1. **Nessun modulo nuovo importa il vecchio percorso.** Un test controlla che
   niente sotto `app/core/`, `app/plugins/` e i nuovi `app/build/assembler.py`,
   `app/build/validate.py` importi `geometry.recipe`, `geometry.composition`,
   `build.strategy`, `build.builder` o `core.spec`.

   **Perché `assembler.py` e non `builder.py`:** quel nome è occupato dal
   vecchio orchestratore, che serve i plugin non ancora migrati ed è collegato a
   `Session`. Prenderlo adesso vorrebbe dire spegnere metà della suite in un
   commit. Il nuovo builder prende il nome `builder.py` nello stesso passo in
   cui il vecchio esce — regola 2.
2. **I banchi migrano uno alla volta, e il vecchio esce nello stesso passo.**
   Un banco non può girare su entrambi i sistemi: quando il banco 3 passa al
   kernel, il ramo SDF che lo serviva viene rimosso in quel commit.
3. **Il conteggio dei test non cala mai.** Se una migrazione toglie un test,
   deve aggiungerne uno che copre lo stesso comportamento sul nuovo percorso.

---

## 9. Test

Ai 762 attuali si aggiungono, per gruppi:

**Architettura**
- nessun file di `app/core/` nomina un plugin o una categoria
- nessun modulo nuovo importa il vecchio percorso
- ogni plugin è caricabile da solo, senza gli altri

**Registry e discovery**
- scoperta di un plugin aggiunto a runtime in una cartella temporanea
- query per capability, tag, id; ricerca testuale
- manifest non valido: rifiutato con diagnosi, non fa cadere il caricamento

**Composizione**
- annidamento arbitrario (profondità 6+)
- componente dentro decorazione dentro componente
- decorazione su decorazione
- sostituzione strutturale senza geometria doppia
- swap cross-plugin con e senza `scale_mode`
- rilevamento dei cicli, distinto dalla ricorsione valida

**Socket e capability**
- risoluzione ai cinque livelli, in ordine
- incompatibilità: messaggio con le alternative
- **convenzione di orientamento**: una parte di prova attaccata a ogni socket
  di un componente esce orientata come dichiarato

**Parametri**
- schema, clamp, tipi, unità
- parametri derivati con scope `self` / `parent` / `root`
- espressione maligna rifiutata (`__import__`, chiamate, subscript)
- vincoli violati: diagnosi, non eccezione

**Effetti**
- scope: model, group, part, subtree, role
- ordine deterministico e stabile
- fuori range: clampato e annotato
- una volta per responsabilità lungo la stessa discendenza
- nessun effetto stacca un pezzo, produce NaN o rompe il manifold

**Budget**
- espansione che si ferma sui triangoli
- espansione che si ferma sul tempo
- `detail_level` alto con budget basso: si ferma e lo dichiara

**Determinismo**
- stesso piano e stesso seme, due processi separati, stessa mesh

**Qualità visiva**
- `faces_per_normal >= 1.8` su ogni caso del vertical slice
- silhouette e budget triangoli

**Conservazione**
- i 5 banchi esistenti restano verdi durante tutta la migrazione

---

## 10. Ordine di lavoro proposto

| passo | cosa | perché prima | stato |
|---|---|---|---|
| 1 | `core/`: capability, socket, params, constraints, component, errors | sono i contratti; tutto il resto ci poggia | **fatto** (59 test) |
| 2 | `core/graph.py` + cicli + budget | il piano deve esistere prima del resolver | **fatto** (52 test) |
| 3 | `core/registry.py` | il resolver interroga il registry | **fatto** (69 test) |
| 4 | `core/resolver.py` con i 5 livelli e la diagnosi | è il cuore della composizione | **fatto** (85 test) |
| 5 | `core/effect.py` con i 6 stadi | dopo il resolver, prima del builder | **fatto** (61 test) |
| 6 | `build/assembler.py` + `validate.py` | produce e verifica | **fatto** (62 test) |
| 7 | **Caso A**: humanoid + frog_head + sword_legs | prova swap, capability, sostituzione | **fatto** (38 test) |
| 8 | **Caso B**: house + planet | prova che il sistema non è antropocentrico | **fatto**, stessi 38 |
| 9 | `Session` sul nuovo percorso, vecchio ancora disponibile | la UI non deve accorgersene | **fatto** |
| 10 | planner LLM che costruisce il prompt dal registry | l'LLM vede solo il vocabolario | **fatto** (45 test) |
| 11 | scenari end-to-end, dal prompt alla mesh | è l'unica prova che conti | **fatto** (31 test) |
| 12 | rimozione della pipeline storica | un solo percorso, non due | **fatto** (-7.965 righe) |
| 13 | progetti e libreria sul `CompositionGraph` | un progetto deve potersi rigenerare | **fatto** |
| 14 | fornitore LLM astratto e schema del piano | il core non nomina nessuna API | **fatto** (31 test) |
| 15 | casi d'oro permanenti e linea di partenza | l'unico criterio che conta | **fatto** (51 test) |
| 16 | API congelate | un plugin di terze parti ci si appoggia | **fatto** (44 test) |

Il vertical slice è **7 e 8**. Se quei due casi girano sullo stesso core senza
che il core sappia cosa sia una rana o un pianeta, l'architettura è universale;
se non girano, non lo è, e nessuna quantità di plugin lo cambierà.


---

## 11. Il planner, e cosa vede

    prompt
      ↓
    Session.generate
      ↓
    vocabulary(registry)      ← contratti, non codice
      ↓
    Planner.plan              ← una chiamata
      ↓
    piano JSON
      ↓
    validate_plan             ← schema, grafo, registry, parametri
      ↓
    resolve                   ← qui si scopre cosa non si incastra
      ↓  (se qualcosa non regge, e solo se una riscrittura può cambiarlo)
    repair_brief → Planner.plan   ← **una sola** correzione
      ↓
    effetti → builder → mesh

**Il vocabolario è generato dal registry**, non scritto a mano: aggiungere un
plugin cambia ciò che il planner può nominare, e il planner non cambia. Contiene
componenti (id, descrizione, `provides`, `accepts`, parametri con intervallo),
capability (chi le fornisce e chi le accetta), effetti (stadio, ambiti,
parametri), stili, tag, plugin con la loro versione. Non contiene una riga di
Python, e un test lo verifica cercando `def `, `import`, `trimesh` nel testo che
arriva al modello.

**Le descrizioni dei plugin sono dati.** Vengono da chi ha pubblicato il plugin
e finiscono nel contesto di un modello linguistico. Non si prova a riconoscere
un testo malevolo — è una gara che si perde: si toglie la **forma** con cui
potrebbe fingersi un'istruzione. Una riga sola, niente delimitatori, niente
marcatori di ruolo, lunghezza limitata; e il prompt di sistema dichiara che quel
blocco è materiale di consultazione. Le due difese servono tutte e due: la prima
toglie la forma, la seconda toglie l'autorità.

**Una generazione, al massimo una correzione.** Le diagnosi del resolver
diventano un riassunto compatto — cosa non ha funzionato, perché, e *cosa c'è al
suo posto*, che è la parte che fa la differenza. Si richiede una volta sola, e
solo se c'è qualcosa che una riscrittura possa cambiare: un budget esaurito o una
compenetrazione non si correggono cambiando dei nomi. Se la seconda risposta è
peggiore della prima, si tiene la prima.

**Nessun giudizio di qualità è affidato a un modello.** Il quality gate è fatto
di numeri — planarità sulla geometria disegnata, budget triangoli, silhouette,
giunti, compenetrazione — e sono sempre gli stessi.

---

## 12. La strada vecchia e' stata tolta

Non disattivata: tolta. 21 moduli, 7.965 righe.

```
build/builder  build/strategy  build/validation
geometry/{composition,recipe,sdf,surface,lowpoly,primitives,templates}
ai/{planner,creature,offline,prompts,variation,reference,shape_match,mesh_provider}
core/spec  core/style
```

Prima di togliere, e' stato migrato quello che serviva ancora:

| cosa serviva | dove sta adesso |
|---|---|
| `Scene` per export, LOD, libreria, animazione, UI | `build/scene.py` la costruisce da un `BuildResult` |
| `MaterialSpec` | `core/material.py`, e i materiali sono **registrabili** dai plugin |
| salvataggio di un progetto | `core/project.py` v2: salva `CompositionGraph`, plugin e versioni |
| libreria di asset | `assets/library.py` salva il piano di composizione |
| livelli di dettaglio | si **rigenerano** costruendo meno parti, invece di decimare |
| profili hardware | danno un budget di triangoli tarato sulla composizione |
| scheletro per l'animazione | legge i socket veri e il lato **dichiarato** dagli innesti |

Un test (`test_the_old_road_is_gone`) verifica che quei file non tornino e che
nessuno li importi.

**Che cosa e' sparito come funzione, e non e' stato sostituito:**

- `Session.modify(prompt)` — l'editing a voce di un modello. Si modifica il
  piano e si chiama `regenerate()`; l'editing a voce tornera' quando il planner
  sapra' riscrivere un piano esistente, che e' un problema diverso da scriverne
  uno nuovo.
- `generate_from_image` — la lettura di un'immagine di riferimento produceva un
  `GenerationPlan`. Il pulsante nella UI e' nascosto finche' non produrra' un
  piano di composizione.
- i validatori **semantici** (un pesce deve avere una coda, la coda deve stare
  dietro). Sapevano che cosa fosse un pesce, ed e' cio' che il core non deve
  sapere. Al loro posto c'e' `build/validate.py`, che misura solo quello che un
  componente **dichiara**.

---

## 13. Il fornitore LLM

```python
class LLMProvider(ABC):
    def available(self) -> bool: ...
    def complete_json(self, system, user, temperature=0.2, schema=None) -> dict
    @property
    def structured(self) -> bool          # sa vincolare la risposta a uno schema?
```

Una domanda, una risposta, nessuno stato. Il core non nomina nessuna API:
cambiare fornitore e' una riga in `core/config.py`, aggiungerne uno non tocca
ne' il planner ne' la sessione.

`schema` cambia solo **quanto ci si puo' fidare** della risposta. Tre gradini,
dal piu' forte al piu' debole: uno schema vincolante, «rispondi in JSON»,
niente. Si scende solo di quanto serve, e cio' che arriva viene validato in
tutti e tre i casi.

Se il fornitore non risponde si scende al planner locale e **lo si scrive**:
`planner = "mock_fallback"`, piu' una diagnosi. Un ripiego silenzioso e' peggio
di un errore.

---

## 14. Lo schema del piano

`core/planner/schema.py`, versionato (`1.0`) e **indipendente dai plugin**: non
contiene un solo id di componente, effetto o stile. Se ne contenesse uno,
installare un plugin obbligherebbe a rigenerare lo schema — e uno schema che si
rigenera non e' un contratto, e' una fotografia.

    schema      un piano ha una radice, i figli sono un elenco, `amount` e' un numero
    plans.py    `humanoid:body` esiste, `width` e' un suo parametro, `lanky` e' installato

La validazione vera resta in `plans.py`, perche' un piano storto non deve dare
«non conforme allo schema» ma «'creature:dragon_head' non si attacca a
'architecture:window': al suo posto puoi usare humanoid:head».

---

## 15. La correzione, e come si decide se e' servita

Una generazione, al massimo una correzione. Il confronto fra il primo piano e
quello corretto e' un **punteggio deterministico** (`PlanScore`), non il numero
di righe di errore:

| difetto | peso | perche' |
|---|---|---|
| nessun piano | 10.000 | un piano che non produce niente e' il peggio possibile |
| nodo non risolto | 1.000 | un pezzo che non entra nel modello |
| diagnosi fatale | 500 | qualcosa si e' fermato |
| innesto senza risposta | 250 | un buco visibile |
| parametro inesistente | 40 | una richiesta che non e' arrivata |
| budget superato | 20 | si e' costruito meno del previsto |

Il primo peso e' nato da un difetto vero: un piano rifiutato in blocco aveva
**meno** diagnosi di uno risolto a meta', e la correzione sembrava un
miglioramento mentre cancellava il modello.

Nessun modello linguistico entra in questo confronto, e un test verifica che il
modulo non nomini nemmeno un fornitore.

---

## 16. Prestazioni, misurate

`python tools/benchmark.py`. Su una macchina normale, senza rete:

```
caricamento plugin   16 ms      planner locale      1 ms
vocabolario           3 ms      resolver          0,2 ms
                                effetti           0,1 ms
                                builder          3-10 ms
                                qualita'          1-3 ms
                                TOTALE           6-13 ms
```

Non sono un obiettivo: sono una linea di partenza. `tests/test_performance.py`
tiene dei tetti dieci volte piu' larghi — servono ad accorgersi di un
peggioramento di un ordine di grandezza, non a difendere un numero. La prova di
scala arriva a **1000 componenti** installati e verifica che una ricerca per id
non scandisca il catalogo.

---

## 17. API congelate

Da questa fase, `tests/test_api_freeze.py` fissa campi e metodi pubblici di:

```
Capability  Mount  Requirement  Attachment  Component  Piece  Socket
ParamSpec  Constraint  EffectSpec  StyleProfile  MaterialSpec
PluginInfo  Registry  CompositionGraph  Resolver  Builder
Session  GenerationResult  Options  Planner
```

Non impedisce di cambiarle: impedisce di cambiarle **per sbaglio**. Chi
aggiunge un campo aggiorna anche quell'elenco, e quella riga di diff e' la
decisione presa.
