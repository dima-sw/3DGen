# V5-RESULTS — La stessa testa, sei teste diverse; e il drago dice che guarda dalla parte sbagliata

Milestone V5, chiusa il **14 ottobre 2026**. Branch `v5-semantic-variability`,
partenza dichiarata e verificata: V4 completa, **1506 test verdi**, data plugin
JSON+GLB funzionanti, `Component` indipendente dal backend geometrico,
retrieval e degradazione semantica funzionanti, trait strutturali funzionanti,
effetti funzionanti, composizione mista procedurale/mesh funzionante.

**Esito: completa.** Suite da 1506 a **1598 test verdi** (92 nuovi, zero rossi).

Tre cose vanno dette in testa.

**1. Il checkpoint V4 esiste.** Prima di toccare qualunque cosa, `.gitignore:11`
era gia' `/build/` (ancorato) ma i sei moduli di `app/build/` non stavano in
nessun commit: `git check-ignore -v app/build/scene.py` non riportava niente e
`git ls-files app/build/` era vuoto. Il commit `f5f0d8b` su `v1-semantic-index`
cattura tutto il working tree da V3 a V4 piu' quei sei file, con la suite a
1506 verdi misurata prima. Da adesso l'elenco dei file modificati di una
milestone e' completo, che per cinque milestone non lo era (debito 22 di
`PROJECT-INDEX`, chiuso).

**2. Due campi nuovi nel core, e nessuna gerarchia nuova.** `Component` guadagna
`frame` e `param_effects`; `PluginInfo` guadagna `frame`; `Options` guadagna
`frame_policy`; `ResolvedLink` guadagna `frame`. Non esistono `VariableComponent`,
`DeformableParam`, `FrameResolver`. I trait, gli effetti e i ruoli semantici
nuovi sono **contenuto di plugin**, e il grep che lo dimostra e' nel §13.

**3. V5 ha trovato e corretto un difetto preesistente che riguardava proprio il
contratto che doveva verificare.** Per le deformazioni **locali** il builder
passava `bounds=None`, quindi `fx:bend` normalizzava la posizione lungo l'asse
una volta sui 24 vertici e una volta sui 3 socket: due mappe diverse per
geometria e innesti, cioe' esattamente la desincronizzazione che `EffectSpec.
deform` esiste per rendere impossibile. Si vedeva solo su un pezzo i cui socket
non coprono l'intervallo dei vertici — e il probe di V5 e' uno di quelli.
Dettagli e misura nel §12.

---

## 1. Il formato dei parametri variabili

**Un parametro di un componente dati dichiara esattamente una strategia.** Due
sono ammesse, zero e due sono rifiutate:

| strategia | che cosa significa | valori |
| --- | --- | --- |
| `transform` | una scala positiva per asse: `scale_x`, `scale_y`, `scale_z`, `uniform_scale`. La mesh si moltiplica, i socket con lei. **E' quella di V4, invariata.** | solo positivi |
| `effect` | il valore pilota un **effetto installato** attraverso la `EffectPipeline` esistente | anche negativi |

```json
"params": {
  "width":     {"default": 1.0, "min": 0.2, "max": 3.0,
                "transform": "scale_x", "semantic_role": "width"},
  "curvature": {"default": 0.0, "min": -1.0, "max": 1.0,
                "semantic_role": "curvature",
                "effect": {"type": "fx:bend", "parameter": "amount",
                           "scope": "part", "neutral": 0.0}}
}
```

Le regole, e perche':

* **nessuna delle due dichiarata → rifiutato** (`DATA_PARAM_UNSUPPORTED`). E' la
  politica di V4 e resta: fingere che un `ParamSpec` qualunque funzioni su una
  mesh importata e' il difetto da non introdurre.
* **entrambe dichiarate → rifiutato.** Non esiste un ordine fra una scala e una
  deformazione che non sia arbitrario, e scegliere al posto dell'autore
  sarebbe peggio che rifiutare.
* **una scala deve essere positiva; un valore che pilota un effetto no.** Il
  verso di una piega e' un segno (`curvature: -0.5` curva dall'altra parte),
  mentre un fattore di scala negativo specchierebbe la mesh. Il contratto del
  valore e' quello dell'effetto, non quello di una scala.
* `neutral` e' il valore per cui **non si chiede niente**. Senza, ogni testa con
  `curvature` a zero porterebbe in giro una piega da zero gradi, e ogni modello
  avrebbe un effetto in programma che non fa nulla. Vuoto significa «chiedi
  sempre», e la scelta e' dell'autore.
* il tipo resta `float`, `ratio` o `int`: un knob numerico pilota un knob
  numerico. Un `enum` dell'effetto (l'`axis` di `fx:bend`) non si pilota da un
  parametro dati — lo decide la dichiarazione dell'effetto con i suoi
  predefiniti.

### Che cosa un plugin dati **non** puo' dichiarare

Quattro chiavi e tre tipi, e niente altro: `type`, `parameter`, `scope`,
`neutral` — tre stringhe e un numero. Dieci casi parametrizzati verificano che
non si possa nemmeno **nominare** altro:

```text
{"type": "fx:bend", "callable":   "mod:fn"}      → DATA_SCHEMA_INVALID
{"type": "fx:bend", "expression": "1+1"}         → DATA_SCHEMA_INVALID
{"type": "fx:bend", "module":     "os"}          → DATA_SCHEMA_INVALID
{"type": "fx:bend", "matrix":     [[1,0,0]]}     → DATA_SCHEMA_INVALID
{"type": "fx:bend", "scope":      "ovunque"}     → DATA_PARAM_UNSUPPORTED
{"type": "fx:bend", "neutral":    "zero"}        → DATA_SCHEMA_INVALID
{"type": "fx:bend", "parameter":  ""}            → DATA_SCHEMA_INVALID
{"type": ""} / {"type": 7} / {}                  → DATA_SCHEMA_INVALID
```

E' la regola 22 di `PROJECT-INDEX` applicata a una chiave nuova: una
dichiarazione che il loader non capisce viene **rifiutata, non ignorata**.
I tre test di V4 che verificano che nessun `.py` di un plugin dati venga
importato, eseguito o aperto continuano a passare senza modifiche: non c'e' una
seconda strada.

### Dove l'esistenza dell'effetto viene verificata, e perche' non al caricamento

`Registry.verify()`, cioe' a caricamento finito, come le dipendenze fra plugin
e per la stessa ragione: un componente puo' nominare `fx:bend` e il plugin `fx`
arrivare dopo in ordine alfabetico. Quattro controlli, tutti **errori** e non
avvisi, perche' un knob che il planner vedrebbe fra quelli disponibili e che
non fa niente non e' un campo ignorabile:

| codice | quando |
| --- | --- |
| `COMPONENT_EFFECT_NOT_FOUND` | l'effetto nominato non e' installato |
| `COMPONENT_EFFECT_PARAM_UNKNOWN` | il parametro pilota non e' un parametro del componente |
| `COMPONENT_EFFECT_KNOB_UNKNOWN` | l'effetto non dichiara quel knob (ne' `amount`) |
| `COMPONENT_EFFECT_SCOPE_UNSUPPORTED` | l'effetto non dichiara quell'ambito |

Il controllo non sa se sta guardando un componente di codice o di dati, e non
deve saperlo.

---

## 2. Semantic role dei parametri

`ParamSpec.semantic_role` **esisteva dal primo giorno** e `TraitMatch.param_roles`
e `ParamPatch.semantic_role` sapevano gia' cercarlo: V5 non ha aggiunto il
meccanismo, ha aggiunto il **vocabolario** e lo ha reso visibile al planner.

I ruoli che i trait di V5 conoscono — e che vivono nei dati, non nel core:

| ruolo | significato | chi lo dichiara oggi |
| --- | --- | --- |
| `length` | una lunghezza lungo l'asse di crescita | 113 parametri dei 97 componenti installati |
| `girth` | uno spessore nella sezione | 134 parametri dei 97 componenti installati |
| `width` | una larghezza dichiarata come tale | i componenti che la dichiarano (tipicamente dati) |
| `height` | un'altezza dichiarata come tale | idem |
| `scale` | un fattore di scala complessivo | idem |
| `curvature` | quanto una parte e' curva | il probe e la coda dei fixture |

Nessuno di questi nomi sta nel core. Il grep lo dice:

```bash
$ grep -rn "squash\|elongate\|taper\|twist\|head_scale\|hand_scale\|part_scale" \
      app/core/*.py app/core/planner/*.py | grep -v app/core/frame.py
$                                  # nessuna riga
```

Sono stringhe che i componenti scrivono e che i trait cercano. Un trait generico
dice «qualunque parametro con ruolo `width`» e non sa che in un plugin si chiama
`width`, in un altro `cheek_width` e in un terzo `largo`.

**Nessun ruolo esistente e' stato riassegnato.** `humanoid:mouth.width` dichiara
`semantic_role="girth"` da sempre, ed e' discutibile, ma cambiarlo cambierebbe
il comportamento di `std:body_mass` su quel pezzo: una riassegnazione di ruoli
nella libreria installata e' una decisione separata, e sta fra i debiti.

### Il planner li vede

Regola 16 di `PROJECT-INDEX`: cio' che non e' nel **testo reso** non esiste per
il modello. `ParamEntry.role` esisteva nel JSON e **non** nel testo; adesso c'e',
insieme all'effetto che il knob pilota:

```text
- procedural_probe:head "a procedural probe head declaring width, height and length"
    params: curve: float [-1, 1] ruolo curvature -> fx:bend; height: distance [0.02, 4] ruolo height; ...
```

Due token per parametro, e l'implementazione dell'effetto non entra: un test
verifica che la voce del componente **non** nomini `local`, `preserve`, `along`,
`deform` ne' `socket_policy`. Il modello deve capire che muovendo quel numero la
forma cambia, non come la deformazione e' scritta.

---

## 3. Effect-backed params: una traduzione, non un motore

`ParamEffect` sta in `app/core/vocabulary.py` accanto a `ParamRule`, ed e' il suo
verso opposto: `ParamRule` dice come un effetto cambia un parametro,
`ParamEffect` dice come un parametro chiede un effetto. Cinque campi, tutti dati.

**Tutta l'implementazione e' una traduzione**, in `EffectPipeline._from_params`
(57 righe in `app/core/effect.py`, commenti compresi):

```text
nodo.values["curvature"] = 0.9
   → EffectRequest(type="fx:bend", scope="part:subject", amount=0.9)
   → _validate  → _resolve_conflicts  → _ordine  → il builder
```

Da li' in poi una piega chiesta da un parametro e una piega scritta nel piano
sono **la stessa cosa**, e passano dalla stessa validazione: effetto inesistente
(`EFFECT_NOT_FOUND`), ambito non dichiarato (`EFFECT_INCOMPATIBLE`), valore
fuori intervallo (`EFFECT_OUT_OF_RANGE`), conflitto fra effetti
(`EFFECT_CONFLICT`). Non e' stata copiata una riga di `EffectSpec`.

Quattro decisioni che valgono la pena di essere scritte:

1. **Dove.** Nella pipeline degli effetti e non nel resolver, perche' i trait
   semantici girano **fra** i due: un trait che cambia `curvature` deve
   cambiare la piega, e se la richiesta nascesse nel resolver il trait
   arriverebbe troppo tardi. Ordine reale: resolver → trait → effetti.
2. **`composition.effects` non viene scritto.** La pipeline puo' girare due
   volte sulla stessa composizione, e un elenco che cresce a ogni giro darebbe
   due pieghe dove ne era stata chiesta una. La lista si costruisce e si butta.
3. **Il piano vince sulla dichiarazione**, come per i parametri e per i figli: se
   qualcuno ha chiesto `fx:bend` su quel nodo, il legame non ne aggiunge un
   secondo e lo dice (`PARAM_EFFECT_SUPERSEDED`, nota). Misurato: con il piano
   che chiede `amount=-0.4` e il parametro che chiederebbe `0.9`, gli effetti in
   programma sono **uno** e vale `-0.4`.
4. **La richiesta e' leggibile.** `PARAM_EFFECT_REQUESTED` dice «`curvature` =
   0.9 chiede `fx:bend.amount`, dichiarato da `mesh_variable:tail`»: un modello
   che cambia forma senza che niente lo spieghi e' la stessa famiglia di difetto
   che V3.5 ha chiuso per i trait.

### Misurato (punto 7 della milestone)

`mesh_variable:tail` e' un GLB vero (una scatola di 12 triangoli che cresce
lungo +X) con `curvature` legato a `fx:bend.amount`:

| `curvature` | limiti del modello | triangoli |
| --- | --- | --- |
| 0.0 | `[0, 0, -0.15] … [1.0, 0.3, 0.15]` | 12 |
| 0.9 | `[0, 0, -0.15] … [0.305, 1.161, 0.15]` | 12 |

* **la mesh si deforma**: i vertici cambiano, il conteggio no — e' una mappa di
  punti, non una mesh nuova;
* **i socket si deformano con lei**: il fixture mette il socket `corner`
  *esattamente* su un vertice (`(1.0, 0.15, 0.15)`), e dopo la piega quel
  vertice e quel socket coincidono ancora a `1e-9`. Se le due mappe fossero
  diverse si separerebbero, e un figlio si attaccherebbe nel vuoto;
* **la mesh sorgente non cambia**: la terza build con `curvature: 0.0` torna
  identica alla prima, cioe' la deformazione non si accumula sul GLB caricato
  una volta sola;
* **ricostruzione deterministica**: due build con `0.8` danno gli stessi
  vertici bit per bit.

### Non e' una cosa dei plugin dati

`procedural_probe:head` e' un componente di **codice** che dichiara
`param_effects=(ParamEffect(param="curve", type="fx:bend", ...),)` e costruisce
con il kernel poligonale. Funziona allo stesso modo. Il legame appartiene al
contratto `Component`, non al loader.

---

## 4. I quattro effetti che mancavano

`app/plugins/effects/effects/forma.py` (238 righe), nuovo file **nel plugin**:

| id | che cosa fa | stadio | ambiti | parametri |
| --- | --- | --- | --- | --- |
| `fx:squash` | piu' basso lungo un asse, piu' largo negli altri due | `local` | part, subtree, group, role | `axis` {X,Y,Z}; amount 0…1 |
| `fx:elongate` | piu' lungo lungo un asse, piu' stretto negli altri due | `local` | idem | `axis`; amount 0…1 |
| `fx:taper` | restringe la sezione verso un'estremita' | `local` | idem | `axis`, `end` {tip,base}; amount 0…1 |
| `fx:twist` | torce la sezione man mano che si sale lungo un asse | `local` | idem | `axis`, `angle` −360…360; amount 0…1 |

Gli ambiti sono **esattamente quelli di `fx:bend`**, e `model` non c'e' per la
stessa ragione: una deformazione dello stadio `local` si applica pezzo per
pezzo, con il riferimento del pezzo, quindi «tutto il modello» non e' una misura
che possa usare — lo stadio che ha i limiti del modello e' `global`, e li' vive
`perspective_exaggeration`. Dichiarare `model` farebbe schiacciare ogni parte
attorno alla propria base, che non e' cio' che la richiesta direbbe.

Tutti e quattro:

* **dichiarano `deform` e non `apply`**, quindi il builder muove vertici e socket
  con la **stessa funzione**: la sincronizzazione non e' una convenzione da
  rispettare, e' impossibile romperla. Verificato sui quattro, piu' `fx:bend`,
  con il socket-su-vertice del §3;
* **dichiarano l'ambito, i parametri e gli intervalli**: un test verifica che
  ogni parametro abbia o `choices` o `min`+`max`, e che `amount` abbia entrambi;
* **rispettano il low poly**: nessun vertice, nessuna faccia, nessuna
  suddivisione in piu'. `taper` e `twist` non sono affini (il fattore dipende
  dalla posizione normalizzata) ma le facce restano piane perche' sono
  triangoli, e tre punti sono sempre complanari;
* **non sono nel core**: `grep squash|elongate|taper|twist` su
  `app/core/effect.py`, `vocabulary.py`, `traits.py`, `resolver.py` non trova
  niente, ed e' un test.

`squash` ed `elongate` si dichiarano **in conflitto** fra loro (sono l'uno
l'opposto dell'altro, come `lanky` e `chunky`), quindi chiederli insieme li
scarta entrambi con `EFFECT_CONFLICT` invece di applicarne uno a caso.

Non sono doppioni di `fx:lanky`/`fx:chunky`: quelli sono dello stadio
`proportion` e cambiano i **parametri** di cio' che si costruira', quindi
funzionano solo su un componente che sappia ricostruirsi — e la' sono la scelta
migliore, perche' una gamba piu' lunga e' una gamba piu' lunga e non una gamba
stirata. Questi quattro muovono i vertici di cio' che **e' stato** costruito, ed
e' l'unico modo di far variare una mesh importata, che ha un solo stato.

Misurato sul probe (estensioni, `amount = 0.9`):

| effetto | asse nominato | sezione | triangoli |
| --- | --- | --- | --- |
| `fx:squash` (Y) | 0.400 → 0.184 | 0.300 → 0.423 | 12 → 12 |
| `fx:elongate` (Y) | 0.400 → 0.688 | 0.300 → 0.219 | 12 → 12 |
| `fx:taper` (Y, tip) | invariato | larghezza in cima < 50% di quella in basso | 12 → 12 |
| `fx:twist` (Y, 90°) | invariato | la base resta ferma (t = 0 → angolo 0) | 12 → 12 |

---

## 5. I trait aggiunti

`app/plugins/variability_extension/` (nuovo plugin, 179 righe di dichiarazioni),
sei `TraitSpec` e **19 `TraitRule`** (5 + 2 + 1 + 5 + 5 + 1), tutte generate da
una funzione sola perche' sono la stessa regola con un bersaglio diverso:

| trait | alias | bersaglio delle regole | misure toccate |
| --- | --- | --- | --- |
| `std:part_scale` | part_scale, scale, size | qualunque nodo che l'ambito raggiunge | length, girth, width, height, scale |
| `std:width` | width, wide, largo | idem | width, girth |
| `std:length` | length, long, lungo | idem | length |
| `std:head_scale` | head_scale, head_size | ruoli `head`, `face` | tutte e cinque |
| `std:hand_scale` | hand_scale, hand_size | ruolo `hand` | tutte e cinque |
| `std:limb_length` | limb_length, leg_length, arm_length | ruoli `arm`, `leg`, `limb`, `foot` | length |

Il valore e' un **fattore** (`ParamSpec(1.0, ratio, 0.15…4.0)`) e l'espressione e'
`value * trait`: «due volte piu' grande» ha senso su una testa alta 24
centimetri e su una casa alta sei metri, «piu' venti centimetri» no. Il
`ParamSpec` del parametro continua a decidere il tetto — un trait puo' spingere,
non sfondare.

Ogni patch dichiara `semantic_role` e **nessuna** dichiara `param`: un test lo
verifica su tutte e 19.

### Perche' tre selettivi, e non solo i tre generici

La milestone chiedeva di valutarlo. La risposta e' misurata, e sta in una
diagnostica:

```text
traits: [{"trait": "std:part_scale", "value": 2.0, "on": "head"}]
   → TRAIT_TARGET_NOT_FOUND
```

`on` **indirizza un nodo**, e la testa di un umanoide non e' un nodo del piano:
e' un figlio che il componente dichiara da se', quindi il suo id e' il percorso
`subject/torso/neck/head`, che il planner non ha scritto e non puo' indovinare.
Con `on: "subject/torso/neck/head"` funziona, e con quel percorso il piano
dipende da come quel plugin ha chiamato le proprie parti: e' la fragilita' che
V3 ha tolto ai trait strutturali, ritrovata nei trait semantici.

Un trait **selettivo per ruolo** non ha la domanda: `{"trait": "head_scale",
"value": 2.4}` con l'ambito predefinito (tutto il sottoalbero) e la regola che
filtra `role in (head, face)`. Un test lo verifica sostituendo l'id della
radice con `subject`, `pupazzo`, `guy_01`, `x`: quattro nomi, **una sola
misura**.

Tre e non trenta: sono i tre ruoli che una richiesta cartoon nomina quasi
sempre. Per un `std:ear_scale` la risposta e' `part_scale` con un `on`, non un
settimo trait.

### Il limite dichiarato: part_scale(subtree) + un trait selettivo

Due regole diverse che scrivono lo stesso canale `(nodo, parametro)` si
scartano **entrambe** con `TRAIT_RULE_CONFLICT`. E' la politica che c'era, ed e'
giusta — tenerne una vorrebbe dire scegliere al posto dell'autore — ma vuol dire
che `part_scale` con `scope: subtree` **piu'** `head_scale` perde entrambi sulla
testa, e lo dichiara. La forma che funziona per «creatura piu' grande con la
testa enorme» e' `part_scale` con `scope: local` sulla radice piu'
`head_scale`: canali disgiunti, nessun conflitto. Scritto qui perche' e' una
cosa che si scopre scrivendo un piano, non leggendo il codice.

### Ponti fra le parole

Il manifest del plugin dichiara **25 sinonimi** (la libreria passa da 16 a 39),
e sono dati, non codice: i plurali inglesi che il retrieval non sa derivare
(`hands` → `hand`, `legs` → `leg`, `heads` → `head`, `arms`, `tails`), le forme
italiane (`testa`, `mani`, `gambe`, `larga`, `lunga`, `corte`) e i comparativi
(`bigger`, `wider`, `longer`, `shorter`, `slender`). Senza il ponte
`hands` → `hand`, la rosa di «humanoid with huge hands» non conteneva **nessuna
mano**, il filtro di rilevanza nascondeva `std:hand_scale` e il modello non
poteva sceglierlo: e' lo stesso meccanismo e la stessa causa che V3.5 ha
misurato per «quattro braccia». `Registry.synonyms()` legge ogni manifest, e
questo non ha richiesto una riga di codice.

---

## 6. Procedurale e mesh-backed: la stessa richiesta

E' il punto 8 della milestone, ed e' il test che tiene insieme tutta V5.

Due componenti che non hanno **niente** in comune tranne un ruolo semantico:

* `procedural_probe:head` — plugin di **codice**, geometria dal kernel
  poligonale (`app/geometry/kernel.py:block`), parametri `width`/`height`/
  `length`/`curve` con ruoli `width`/`height`/`length`/`curvature`;
* `mesh_variable:head` e `mesh_variable:tail` — plugin di **dati**, geometria da
  GLB, parametri `width`/`height`/`size` (transform) e `length`/`curvature`.

Quattro casi parametrizzati, ciascuno su entrambi i backend:

| trait | parametro | procedurale | mesh-backed |
| --- | --- | --- | --- |
| `std:width` | `width` | geometria cambiata | geometria cambiata |
| `std:part_scale` | `width` | geometria cambiata | geometria cambiata |
| `std:length` | `length` | geometria cambiata | geometria cambiata |
| `std:part_scale` | `length` | geometria cambiata | geometria cambiata |

In tutti e otto i casi il canale applicato e' `subject.<parametro>`, e in nessuno
la richiesta nomina il componente, il backend o il percorso. Misura esatta su
`mesh_variable:head` con `std:width = 2.0`: estensione X `0.30 → 0.60`,
estensione Y invariata — la scala e' quella dichiarata dal parametro, non una
scala del modello.

E un piano solo che li tocca entrambi: `mesh_variable:host` (GLB) con un figlio
`procedural_probe:head` montato per capability, `std:width = 1.8` con
`scope: subtree` → la larghezza del figlio procedurale cresce dentro un albero
la cui radice e' una mesh importata.

### Nessun ramo, e la prova per grep

```bash
$ grep -rn "mesh_backed\|is_mesh\|kind == \"data\"" app/build/ app/core/ \
      --include=*.py | grep -v data_plugin.py | grep -v registry.py
$                                        # nessuna riga
```

Invariato da V4, con il livello semantico nuovo sopra. E un test legge
direttamente `app/core/traits.py` e verifica che le parole `mesh`, `glb`,
`gltf`, `mesh_backed`, `data_plugin` non compaiano: non e' un test di stile,
perche' un `if mesh_backed:` nel `TraitResolver` farebbe fallire il punto 6
della milestone anche con tutti i numeri giusti.

**I componenti procedurali non sono stati retrocessi.** Tutti e sei i trait sono
misurati sulla libreria procedurale installata (§9), `ParamEffect` funziona su un
componente di codice, e i quattro effetti nuovi sono misurati sul probe
procedurale.

---

## 7. Il frame diventa un contratto

### Che cosa si confronta, e che cosa no

E' la decisione centrale del modulo, e senza di lei il contratto sarebbe
rumore. Tre assi, due significati:

* **`growth_axis` e' locale**: da dove la parte si estende partendo dalla sua
  base. Un arto che cresce `+X` su un torso che cresce `+Y` **non e'
  un'incoerenza**, e' la convenzione scritta in `app/core/authoring.py`. Il
  socket del padre porta `direction` e `up`, e il placement engine usa quelli:
  la rotazione del figlio e' gia' decisa, e V5 non la tocca. Se `compare()`
  guardasse `growth_axis`, ogni arto di ogni umanoide produrrebbe una
  diagnostica — e una diagnostica che compare sempre non si legge piu'.
* **`up` e `front` sono del soggetto**: quale asse locale guarda in alto e quale
  in avanti quando il componente sta dritto. Queste il socket **non** le
  conciliava: il frame di innesto allinea `direction` con `-direction`, non la
  nozione di «in alto» di due autori diversi. Se un plugin costruisce con il
  davanti verso `+Z` e un altro verso `-Z`, i due pezzi si montano senza un
  errore e il risultato guarda dalla parte sbagliata.

Quindi `compare()` guarda **solo** `up` e `front`, e `growth_axis` resta la
diagnostica geometrica di `verify_frame` che era. Un test lo fissa.

### Quattro esiti

| esito | quando | che cosa produce |
| --- | --- | --- |
| `compatible` | concordano su cio' che entrambi dichiarano | niente |
| `convertible` | non concordano, **entrambe** le terne sono complete | avviso con la rotazione e la mossa |
| `ambiguous` | non concordano, una terna e' incompleta | avviso: la rotazione non e' determinata |
| `undeclared` | non c'e' niente da confrontare | niente |

`convertible` e' una categoria utile e non un'opinione: fra due terne
ortonormali destrorse la rotazione che mappa l'una sull'altra e' **una sola**
(`other.basis() @ self.basis().T`), e un test verifica che quella matrice porti
davvero `front` su `front` e `up` su `up`. `ambiguous` e' diverso perche' con
una terna incompleta la rotazione attorno all'asse noto resta libera, e
indovinarla sarebbe inventare.

`undeclared` **non e' un difetto**: e' il limite dichiarato del contratto. La
milestone chiede di non accettare piu' in silenzio un orientamento assurdo
«quando i metadata permettono di rilevarlo», e per i 18 plugin che non
dichiarano niente il sistema non sa e dice di non sapere.

### Dove si dichiara: nel manifest, non in ogni pezzo

```json
"frame": { "up": "+Y", "front": "+Z" }
```

`PluginInfo.frame` vale per tutti i componenti del plugin che non dichiarano una
terna propria (`Registry.register_component`). E' la promozione che
`VISION-GAP` §8 chiedeva: `humanoid_anatomical` scriveva la stessa cosa in
`metadata` come prosa italiana — vera, e non confrontabile da nessuno. Una riga
per plugin invece di una per componente, perche' **una convenzione appartiene
all'autore del plugin**. Risultato: **53 componenti su 97** hanno una terna
dichiarata, con cinque righe di JSON.

Un componente che dichiara la propria vince sul predefinito del plugin (test),
e un asse illeggibile nel manifest rifiuta il plugin con `INVALID_MANIFEST`
invece di essere ignorato. Un componente **dati** passa dallo stesso
`FrameSpec`: la validazione che V4 teneva in `data_plugin.py` e' stata spostata
in `app/core/frame.py`, cosi' un asse valido e' definito in un posto solo.

### Niente conversione, e perche'

Applicare la rotazione vorrebbe dire decidere la posa di un figlio **contro** il
socket che il padre ha dichiarato, cioe' un secondo placement system accanto a
quello che c'e'. V5 non lo fa. La rotazione si **calcola** e si **nomina**:
`FrameSpec.axis_and_angle_to()` da' asse e gradi, `FrameSpec.move()` scrive la
richiesta di effetto nella forma che il piano accetta, e la diagnostica la porta
fra le `alternatives`. E' la scelta di V3.5 per i brief di riparazione: dire la
mossa, non farla.

La politica del progetto sta in `Options.frame_policy`, due valori:

| politica | esito |
| --- | --- |
| `diagnose` (predefinito) | avviso, il modello si costruisce |
| `strict` | errore: il referto non e' ok, e la correzione unica parte |

Non e' una decisione del piano perche' non riguarda un modello: riguarda quanto
severo vuole essere **questo progetto** con gli asset che installa. Si salva in
`.my3d` solo quando non e' il predefinito, si rilegge, e un valore sconosciuto
torna a `diagnose`. Disponibile anche da CLI: `--frame-policy strict`.

`FRAME_CONVERTIBLE` e' entrato in `CORREGGIBILI` (`app/core/planner/repair.py`),
perche' con `strict` il brief porta **la mossa** — `fx:rotate` con asse e gradi
gia' calcolati — ed e' un difetto che una riscrittura del piano puo' davvero
risolvere. `FRAME_AMBIGUOUS` resta fuori, deliberatamente: la correzione non sta
nel piano ma nel componente, perche' e' l'autore dell'asset che deve dichiarare
`up` e `front`.

---

## 8. Il banco del drago

Il caso storico di `VISION-GAP`: `fish:fish_body` + `creature:dragon_head` +
due `fantasy:wing`, tre plugin diversi, montati per capability.

Le terne dichiarate sono **misurate, non supposte**. Il corpo del pesce cresce
`+Y` (il suo plugin lo documenta: «cosi' una figura con un corpo di pesce resta
in piedi») e il suo socket `dorso` — il **dorso**, la schiena — sta a `+Z` e
guarda `+Z`. Per questo plugin il davanti del soggetto e' quindi `-Z`. La testa
di drago costruisce il muso lungo `+Z` (`snout_depth`, `axis=2`), e l'ala e' una
lamina nel piano XY: per entrambe il davanti e' `+Z`, come per `humanoid` e
`humanoid_anatomical`, che e' anche la convenzione dei nomi di direzione in
`app/plugins/effects/effects/posa.py` (`front: (0,0,1)`).

Prima di V5: nessun referto. Dopo:

```text
FRAME_CONVERTIBLE  subject/head    avviso
  'fish:fish_body' e 'creature:dragon_head' non concordano sull'orientamento
  perche': convenzioni dichiarate: 'fish:fish_body' front -Z, up +Y,
           'creature:dragon_head' front +Z, up +Y; frame convertibile
           (front: -Z contro +Z): 180.0 gradi attorno a Y
  al suo posto: fx:rotate axis=Y angle=180.0 su subtree:head

FRAME_CONVERTIBLE  subject/wing_l  (idem)
FRAME_CONVERTIBLE  subject/wing_r  (idem)
```

Tre avvisi su tre innesti discordanti, e **nessuno** sulla coda, che e' un figlio
dichiarato dal corpo e viene dallo stesso plugin: `compatible`. Ogni
`ResolvedLink` porta l'esito (`link.frame`), quindi il referto non e' l'unico
posto dove la cosa e' leggibile.

Con `frame_policy: strict` gli stessi tre diventano fatali, `report.ok` e'
falso, `repair_brief()` ha tre voci e porta `fx:rotate` — e con `diagnose` il
brief e' vuoto, perche' un avviso e' una cosa che il sistema ha gia' deciso di
tollerare.

**La mossa suggerita funziona davvero**, e un test lo misura: aggiungendo al
piano `{"type": "fx:rotate", "scope": "subtree:head", "params": {"axis": "Y",
"angle": 180.0}}` il modello si costruisce, i triangoli sono gli stessi (e' una
posa, non geometria nuova) e i vertici della testa sono cambiati.

Quindi, rispetto al punto 12 della milestone: **non e' la composizione a essere
stata raddrizzata, e' il sistema a non accettarla piu' in silenzio** — con la
diagnostica esplicita, la rotazione esatta e l'effetto installato che la
applica, e con una politica di progetto che la rende fatale. Dei due esiti che
la milestone ammetteva, V5 sceglie il secondo, deliberatamente: il primo
avrebbe richiesto un secondo placement system.

---

## 9. Le sei richieste

`python tools/variability_benchmark.py 7`. Il planner e' quello locale e il piano
che esprime la richiesta e' scritto a mano: questa parte misura il **motore**, e
la colonna «intento» misura separatamente che il trait giusto sia nel
vocabolario che il modello vedrebbe per quel prompt — la lezione di V3.5, dove
il livello funzionava e nessuno lo chiamava.

Nessuna riga si accontenta di `ok=True`.

| # | richiesta | intento: trait offerto per quel prompt | applicato | geometria | visivo (la misura che la richiesta nominava) |
| --- | --- | --- | --- | --- | --- |
| 1 | `humanoid with a huge head` | `std:head_scale` ✅ nel testo reso | 19 canali | 1142 → 1142 triangoli, limiti cambiati | testa (max estensione) **0.244 → 0.424**, ×1.74 |
| 2 | `humanoid with short legs` | `std:limb_length` ✅ | 40 canali | 1142 → 1142, limiti cambiati | gambe **1.638 → 0.922**, ×0.56 |
| 3 | `humanoid with huge hands` | `std:hand_scale` ✅ | 12 canali | 1142 → 1142, limiti cambiati | mani **0.280 → 0.617**, ×2.20 |
| 4 | `very wide cartoon creature` | `std:width` ✅ | 20 canali | 412 → 412, limiti cambiati | larghezza X **0.697 → 1.430**, ×2.05 |
| 5 | `long curved tail` | `std:length` ✅ + `fx:bend` | 1 canale + 1 effetto | 38 → 38, limiti cambiati | estensione max **0.323 → 0.516**, ×1.60 |
| 6 | `tall slender slightly curved house` | `std:length` + `std:width` ✅ + `fx:bend` | 8 canali | 32 → 32, limiti cambiati | altezza Y **6.575 → 8.102**, ×1.23 |

E le diagnostiche visive che c'erano (`app/build/visual.py:analyse`), sulla scena
vera, prima → dopo:

| # | riempimento (solidita' media) | proporzioni (x, y, z normalizzate) |
| --- | --- | --- |
| 1 | 0.550 → 0.586 | `0.531, 1.000, 0.236` → `0.484, 1.000, 0.252` |
| 2 | 0.550 → 0.674 | `0.531, 1.000, 0.236` → `0.588, 1.000, 0.204` |
| 3 | 0.550 → 0.585 | `0.531, 1.000, 0.236` → `0.645, 1.000, 0.236` |
| 4 | 0.681 → 0.724 | `0.310, 0.775, 1.000` → `0.616, 0.955, 1.000` |
| 5 | 0.709 → 0.743 | `0.681, 1.000, 0.206` → `0.595, 1.000, 0.129` |
| 6 | 0.906 → 0.757 | `0.908, 0.938, 1.000` → `0.640, 1.000, 0.821` |

Si leggono: la testa enorme e le mani grandi allargano la silhouette senza
cambiare l'altezza (y resta l'asse lungo); le gambe corte la rendono piu'
compatta (riempimento 0.55 → 0.67, x 0.53 → 0.59); la creatura larga raddoppia
in x; la coda lunga e curva si assottiglia in z; **la casa diventa alta e
stretta** e y passa da 0.938 a essere l'asse piu' lungo. Nessuno di questi
numeri e' un giudizio: sono due misure confrontabili.

Il banco cartoon della milestone — testa enorme, gambe corte, mani grandi — e'
esprimibile in **un piano solo**:

```json
"traits": [{"trait": "head_scale", "value": 2.4},
           {"trait": "limb_length", "value": 0.55},
           {"trait": "hand_scale", "value": 2.0}]
```

I tre non si pestano i piedi (`traits.conflicts == []`), nessuno nomina un
percorso di nodo, nessuno conosce l'id della radice, il referto e' ok e le tre
misure si muovono tutte nel verso giusto: testa ×>1.5, gambe ×<0.8, mani ×>1.3.

**Quello che questa sezione non dimostra** e' che un modello di frontiera scelga
davvero quel trait: il debito 8 di `TODO` resta aperto, e questo benchmark lo
restringe a «il modello lo vede e la richiesta e' cablata fino alla geometria».

---

## 10. Variabilita' e `detail_level` restano separate

Punto 13 della milestone, verificato e non assunto. `detail_level` decide
**quali** componenti esistono, i trait decidono **come sono fatti** quelli che
esistono. Per i livelli 1, 2 e 3, con `std:part_scale = 2.5`:

| livello | nodi senza trait | nodi con trait | triangoli | altezza |
| --- | --- | --- | --- | --- |
| 1 | invariati | **gli stessi** | **gli stessi** | cresciuta |
| 2 | invariati | gli stessi | gli stessi | cresciuta |
| 3 | invariati | gli stessi | gli stessi | cresciuta |

E l'assert che la milestone chiedeva per esteso: un L1 con `part_scale = 2.5` ha
**meno nodi** di un L3 senza niente. Un modello gigante non diventa dettagliato.

---

## 11. Prestazioni

`python tools/variability_benchmark.py 7`, stessa macchina, nessuna rete,
mediana di 7 ripetizioni.

| passo | mediana | peggiore |
| --- | --- | --- |
| riferimento: build di un componente mesh-backed, niente altro | 1.204 ms | 110.101 ms¹ |
| parametro `transform` (scala su mesh) | 1.039 ms | 1.364 ms |
| parametro effect-backed (`fx:bend` da `curvature`) | 1.541 ms | 1.634 ms |
| trait semantico su componente mesh-backed | 1.125 ms | 1.176 ms |
| trait semantico su componente procedurale | 2.309 ms | 2.953 ms |
| trait semantico su albero misto (mesh + procedurale) | 3.738 ms | 3.923 ms |
| riferimento: `humanoid_anatomical:body` intero (37 nodi) senza trait | 97.262 ms | 101.327 ms |
| `std:part_scale` sullo stesso albero (113 canali applicati) | 102.365 ms | 111.392 ms |
| validazione dei frame: la chimera, 3 innesti discordanti, `diagnose` | 20.914 ms | 23.731 ms |
| la stessa, politica `strict` | 20.457 ms | 23.185 ms |
| `compare()` da solo, 10 000 confronti | 33.522 ms | 59.159 ms |

¹ il peggiore della prima riga e' il riscaldamento del primo giro (import di
`trimesh`, costruzione dell'indice): la mediana e' la misura.

Lettura onesta:

* **un parametro effect-backed costa 0.5 ms in piu'** di una scala, cioe' il
  costo di una `EffectRequest` validata e di una mappa di punti su 12 vertici.
* **un trait semantico costa meno su una mesh importata che su un componente
  procedurale** (1.1 ms contro 2.3 ms) perche' la mesh non si ricostruisce: e'
  la stessa asimmetria che V4 aveva misurato sulla build.
* **il livello dei trait su un albero vero costa ~5 ms su 97**, cioe' il 5%, per
  113 canali applicati su 37 nodi: ~0.045 ms per canale. Resta nell'ordine dei
  millisecondi, che e' cio' che la milestone chiedeva.
* **la validazione dei frame non si misura**: `compare()` costa **0.0034 ms**, e
  i due numeri della chimera (`diagnose` 20.9, `strict` 20.5) differiscono meno
  del rumore. Era prevedibile — confronta due stringhe — e vale la pena averlo
  misurato proprio perche' e' il genere di controllo che si teme di aggiungere.
* i 97 ms di `humanoid_anatomical` **non** sono i 6–13 ms della linea di base di
  `PROJECT-INDEX`: quello e' un modello di 2 nodi, questo di 37 nodi e 1142
  triangoli. Non e' una regressione di V5, e il riferimento senza trait lo dice.

---

## 12. Il difetto preesistente che V5 ha trovato

Il builder applicava le deformazioni **locali** con `bounds=None`
(`app/build/assembler.py:311`). Gli effetti che normalizzano la posizione lungo
un asse — `fx:bend`, e ora `fx:taper` e `fx:twist` — ricavano l'intervallo dai
punti che ricevono quando `ctx.bounds` e' vuoto. Ma il builder chiama la mappa
**due volte**: una sui vertici e una sui socket. Due insiemi di punti, due
intervalli, **due mappe diverse**.

Misurato sul probe, dove i socket stanno tutti a x = 0 e i vertici in
`[-0.15, 0.15]`:

```text
prima:  fx:bend amount=0.9  → i vertici si piegano, il socket `tip` non si muove
        (intervallo lungo X dei soli socket = 0, quindi t = 0 per tutti)
dopo:   il vertice che coincideva con il socket `corner` ci coincide ancora
```

Era esattamente la desincronizzazione che `EffectSpec.deform` esiste per rendere
impossibile, e che `app/core/vocabulary.py:163-168` dichiara impossibile per
costruzione: il contratto e' giusto, l'implementazione lo rompeva passando due
riferimenti diversi alle due chiamate.

La correzione e' una riga: per gli effetti locali si passano i limiti **del
pezzo**. **La geometria non cambia** — per i vertici quelli sono gli stessi
numeri che `_estremi` ricavava da loro — e cambiano solo i socket, che ora
seguono. Verificato su tutti e cinque gli effetti di deformazione, con un socket
messo *esattamente* su un vertice:

| effetto | vertice e socket coincidono dopo |
| --- | --- |
| `fx:bend` | ✅ (prima: no) |
| `fx:squash` | ✅ |
| `fx:elongate` | ✅ |
| `fx:taper` | ✅ |
| `fx:twist` | ✅ |

Non e' un difetto di V4 e non e' stato introdotto qui: V4 lo aveva mancato
perche' il suo fixture usava un pezzo in cui i due intervalli coincidevano per
caso. Zero test esistenti sono cambiati per questa correzione.

---

## 13. Validation

Nessun quality system nuovo. Dopo le deformazioni, verificato sui quattro
effetti nuovi e su tutti i trait:

* **i socket restano coerenti**: §12, e il socket-su-vertice del §3;
* **nessun NaN/inf**: `np.all(np.isfinite(...))` su vertici, posizioni e versi
  dei socket; un verso di norma nulla farebbe fallire `SOCKET_WITHOUT_DIRECTION`;
* **la topologia resta triangolare**: `mesh.faces.shape[1] == 3`, e il conteggio
  delle facce e' identico a quello della mesh *come costruita*
  (`BuiltNode.designed`);
* **i controlli di giunzione girano**: `app/build/validate.py:validate` sui
  quattro effetti non produce nessuna diagnostica fatale, e i sei banchi del §9
  hanno `report.ok` vero con `check=True`;
* **le diagnostiche visive esistenti girano**: `analyse()` sulle sei scene,
  tabella nel §9.

---

## 14. File modificati

Nuovi:

| File | Righe | Che cosa |
| --- | --- | --- |
| `app/core/frame.py` | 310 | `FrameSpec`, `FrameComparison`, `compare`, le due politiche, la rotazione e la mossa |
| `app/plugins/effects/effects/forma.py` | 238 | `squash`, `elongate`, `taper`, `twist` |
| `app/plugins/variability_extension/` | 179 + manifest | sei `TraitSpec`, 19 `TraitRule`, 25 sinonimi |
| `tests/plugins/variabilita/procedural_probe/` | 60 + manifest | il componente procedurale che dichiara i ruoli di V5 e un `ParamEffect` |
| `tests/test_semantic_variability.py` | 775 | 65 test |
| `tests/test_frame_contract.py` | 398 | 27 test |
| `tools/variability_benchmark.py` | 298 | le misure dei §9 e §11 |
| `V5-RESULTS.md` | — | questo documento |

Modificati:

| File | Che cosa |
| --- | --- |
| `app/core/vocabulary.py` | `ParamEffect` (+52 righe), accanto a `ParamRule` |
| `app/core/component.py` | `Component.frame`, `Component.param_effects` |
| `app/core/effect.py` | `EffectPipeline._from_params`: la traduzione parametro → `EffectRequest` |
| `app/core/resolver.py` | `Resolver._frame`: il confronto a ogni collegamento, e `frame_policy` |
| `app/core/resolved.py` | `ResolvedLink.frame`, `ResolvedComposition.frame_policy` |
| `app/core/registry.py` | `PluginInfo.frame`, il frame del plugin come predefinito, `_verify_param_effects` |
| `app/core/data_plugin.py` | la strategia `effect` sui params, `_binding`, `frame` dal contratto comune |
| `app/core/session.py` | `Options.frame_policy`, round-trip, passaggio al resolver |
| `app/core/planner/vocabulary.py` | `ParamEntry.effect`, il ruolo semantico nel testo reso |
| `app/core/planner/repair.py` | `FRAME_CONVERTIBLE` fra i `CORREGGIBILI`, con il perche' accanto |
| `app/build/assembler.py` | i limiti del pezzo alle deformazioni locali (§12) |
| `cli.py` | `--frame-policy` |
| `app/plugins/{humanoid,humanoid_anatomical,creature,fantasy,fish}/plugin.json` | una riga `frame` ciascuno |
| `app/plugins/effects/plugin.json` | `forma.py` fra gli effetti |
| `tests/data_plugin_fixtures.py` | `write_variable_plugin`: i knob semantici e il socket-su-vertice |
| `tests/test_api_freeze.py` | `Component.frame`, `Component.param_effects`, `Options.frame_policy`, `PluginInfo.frame` (additivi, §16) |

Nessun tipo nuovo fuori da `FrameSpec`/`FrameComparison`/`ParamEffect`, che sono
tre dataclass di dati. Nessun file nuovo nel core oltre a `frame.py`.

---

## 15. Test

**1598 passed** (`python -m pytest -q`), da 1506. I 92 nuovi:

| file | quanti | che cosa |
| --- | --- | --- |
| `tests/test_semantic_variability.py` | 65 | il formato dei params (le due strategie, dieci rifiuti di sicurezza, i valori negativi), i quattro controlli del registry, il parametro effect-backed (mesh e socket sulla stessa mappa, sorgente intatta, determinismo, il piano che vince, su dati **e** su codice), lo stesso trait su procedurale e mesh in quattro combinazioni, i sei trait sulla libreria installata, il banco cartoon, l'invarianza all'id della radice, la separazione da `detail_level`, i quattro effetti nuovi (ambiti, intervalli, conflitto, assi, socket, validita' geometrica, assenza dal core), e che cosa il planner vede nel testo reso |
| `tests/test_frame_contract.py` | 27 | il contratto da solo (assi nominati, terne rifiutate, base ortonormale destrorsa, i quattro esiti in sette casi, la rotazione che mappa davvero, `growth_axis` che non e' mai un disaccordo), la dichiarazione (manifest, componente che vince, manifest storto, componente dati), il confronto durante la risoluzione (composizione coerente muta, frame non dichiarato muto, l'esito su ogni arco), il banco del drago, le due politiche e il round-trip, e l'ambiguo distinto dal convertibile |

I 20 punti della milestone, e dove sono:

| # | richiesta | test |
| --- | --- | --- |
| 1 | nessun secondo motore di deformazione | `test_the_new_effects_are_not_in_the_core`, `test_the_trait_resolver_has_no_branch_for_mesh_backed_components` |
| 2 | params mesh-backed → transform o effect | `test_a_parameter_declares_a_transform_or_an_effect_but_not_both` (+10 rifiuti) |
| 3 | semantic role dei parametri | `test_a_semantic_role_is_declarable_on_both_strategies`, `test_the_vocabulary_shows_semantic_roles_in_the_rendered_text` |
| 4 | i trait mancanti | `test_every_new_trait_is_installed_with_rules_and_a_purpose` (6 casi), `test_no_alias_of_the_new_traits_is_ambiguous` |
| 5 | gli effetti mancanti | `test_the_new_effects_are_ordinary_installed_effects` (4 casi) + 5 test di comportamento |
| 6 | mesh-backed + semantic trait | `test_a_semantic_trait_reaches_a_mesh_backed_component` |
| 7 | mesh-backed + effect-backed param | `test_an_effect_backed_parameter_deforms_mesh_and_sockets_by_the_same_map`, `..._source_mesh_is_never_touched_and_the_result_is_deterministic` |
| 8 | procedurale e mesh, stesso ruolo | `test_the_same_trait_hits_procedural_and_mesh_through_the_same_role` (4 casi × 2 backend), `test_one_plan_changes_a_procedural_and_a_mesh_part_at_once` |
| 9–10 | frame come contratto, e semantica | `tests/test_frame_contract.py` §1–§3 |
| 11 | auto-alignment prudente | nessuna conversione applicata: `test_the_dragon_chimera_no_longer_passes_in_silence` costruisce, `..._suggested_move_is_a_real_installed_effect` la nomina |
| 12 | banco drago | `test_the_dragon_chimera_no_longer_passes_in_silence`, `test_strict_policy_refuses_what_diagnose_only_reports` |
| 13 | variabilita' ≠ detail_level | `test_detail_level_and_variability_stay_separate` |
| 14 | vocabolario del planner | tre test su `to_text()`, piu' `test_the_payload_does_not_explode_with_the_new_vocabulary` |
| 15 | i sei prompt | `tools/variability_benchmark.py` (§9) + `test_the_cartoon_benchmark_is_expressible_in_one_plan` |
| 16 | sicurezza dello schema dati | `test_an_effect_binding_can_only_name_things` (10 casi) + i tre test di V4 sull'assenza di esecuzione |
| 17 | validation | `test_the_new_effects_keep_the_geometry_measurable`, `test_the_new_effects_move_sockets_with_the_vertices` |
| 18 | prestazioni | `tools/variability_benchmark.py` (§11) |
| 19 | niente di fuori scope | §17 |
| 20 | output | questo documento, `PROJECT-INDEX.md`, `TODO.md` |

---

## 16. Regressioni e contratti cambiati

**Zero test rossi**, e nessun test esistente indebolito. Quattro cambiamenti
dichiarati, tutti additivi:

1. **`Component.frame` e `Component.param_effects`** sono campi nuovi; un
   componente che non li dichiara si comporta come prima.
   `tests/test_api_freeze.py` aggiornato: quella riga di diff **e'** la
   decisione, come dice il file stesso.
2. **`Options.frame_policy`** e' un campo nuovo con il predefinito `diagnose`,
   cioe' il comportamento di prima (nessuna diagnostica dove non c'erano
   dichiarazioni). Entra in `to_dict()` solo quando non e' il predefinito, e un
   `.my3d` salvato prima non lo ha.
3. **`PluginInfo.frame`** e' un campo nuovo, e `frame` e' una chiave accettata
   anche nei manifest dei plugin **dati** (prima l'elenco chiuso la rifiutava).
4. **`ResolvedLink.frame`** e `ResolvedComposition.frame_policy` sono campi
   nuovi con un predefinito che vuol dire «non dichiarato».

Cinque manifest di plugin installati hanno una riga in piu' (`frame`). Non e'
un cambio di contratto: e' contenuto di libreria, ed e' la dichiarazione che
rende la chimera diagnosticabile. Da sola produce **tre avvisi nuovi** su una
composizione che prima era muta — ed e' lo scopo.

### Difetti preesistenti trovati

* **La desincronizzazione dei socket sulle deformazioni locali** — corretta qui,
  §12, perche' riguardava direttamente il contratto che V5 doveva verificare.
* **`repair_brief` dedup per `(codice, dove)` e tiene le `alternatives`
  dell'ultima voce letta per quel codice**: con tre `FRAME_CONVERTIBLE` su tre
  nodi, il testo reso puo' mostrare la mossa di `wing_r` accanto al messaggio
  della testa. Le tre voci sono comunque tre, con il `where` giusto. Riguarda
  tutti i codici allo stesso modo ed e' presente da V3.5: non corretto qui.
* **`MATERIAL_REDECLARED`** su `tree_stylized`: invariato, resta rumore in ogni
  report del registry.
* **Un figlio dichiarato nel piano scompare in silenzio a `detail_level 1`**
  (debito 21 di V4): invariato, non toccato.

---

## 17. Definition of Done

| # | Criterio | Esito |
| --- | --- | --- |
| 1 | suite completa verde | ✅ **1598 passed** (erano 1506) |
| 2 | un parametro mesh-backed pilota un `EffectSpec` installato | ✅ `curvature` → `fx:bend`, §3 |
| 3 | i trait semantici modificano componenti mesh-backed | ✅ `std:width` su un GLB, X ×2, §6 |
| 4 | lo stesso trait su procedurale e mesh via `semantic_role` | ✅ 4 casi × 2 backend, §6 |
| 5 | width/length/scale esprimibili semanticamente | ✅ piu' height, piu' tre selettivi per ruolo, §5 |
| 6 | squash/elongate/taper/twist esistono e passano dalla pipeline | ✅ in `app/plugins/effects/`, §4 |
| 7 | socket e mesh restano sincronizzati | ✅ socket-su-vertice su 5 effetti, e un difetto preesistente corretto, §12 |
| 8 | frame convention dichiarata e verificabile | ✅ `app/core/frame.py`, 53 componenti su 97 la dichiarano, §7 |
| 9 | composizioni cross-plugin incoerenti non passano piu' in silenzio | ✅ tre avvisi sulla chimera, fatali con `strict`, §8 |
| 10 | nessuna conoscenza di dominio nel core | ✅ due grep vuoti, §2 e §6 |
| 11 | i plugin data-only restano senza esecuzione di codice | ✅ 10 rifiuti nuovi, i tre test di V4 invariati, §1 |
| 12 | V6/V7 non iniziate | ✅ §18 |

Fuori scope e non iniziati, come chiesto: UI di importazione o di authoring,
selezione di mesh/facce, component editor, Teach 3DGen, generazione di codice o
di gerarchie con l'AI, `Session.modify`, marketplace, auto-segmentation, rig,
shape key, generazione neurale di mesh.

---

## 18. Debiti verso V6 e V7

* **Il conflitto fra un trait generico con `scope: subtree` e un trait
  selettivo** (§5) e' dichiarato e diagnosticato, non risolto. La via che non
  vuole scegliere al posto dell'autore e' un selettore **nella richiesta**
  (`{"trait": "part_scale", "value": 2, "role": "head"}`), che e' un cambio
  dello schema del piano e della sua versione: una decisione, non un dettaglio.
* **Un parametro dati pilota solo knob numerici.** L'`axis` di `fx:bend` resta
  quello che l'effetto dichiara come predefinito: una coda che cresce lungo +Z
  non puo' dichiarare, dai dati, che la sua piega va calcolata lungo Z. Serve
  ammettere un valore **costante** per gli altri knob del legame, e va deciso se
  sia una terza strategia o un campo in piu' su quella esistente.
* **I ruoli semantici della libreria installata non sono stati riassegnati.**
  `humanoid:mouth.width` dichiara `girth`, e `std:width` lo raggiunge per quella
  via invece che per la sua. Una revisione dei 259 `semantic_role` dichiarati dai componenti installati
  (134 `girth`, 113 `length`, 12 `ratio`)
  cambierebbe anche `std:body_mass`, quindi e' una milestone di contenuto con la
  sua misura.
* **18 plugin su 23 non dichiarano un frame**, quindi per loro il contratto non
  dice niente. Dichiararli e' lavoro di libreria, e per alcuni (`space:planet`,
  `primitives:block`) la domanda «dov'e' il davanti di una sfera» non ha una
  risposta — e un frame falso sarebbe peggio di nessun frame.
* **`frame` non converte**, per scelta. Se un giorno servisse, la strada
  dichiarata e' che il **piano** porti l'`fx:rotate` che la diagnostica
  suggerisce — possibilmente scritto dalla correzione unica, che ora ha il
  codice fra i `CORREGGIBILI` — non che il builder ruoti un figlio contro il
  socket del padre.
* **`growth_axis` non entra nel confronto**, ed e' giusto, ma vuol dire che un
  asset il cui asse di crescita contraddice il proprio `base` socket resta un
  problema solo di `verify_frame`, cioe' di authoring.
* **Il benchmark dei sei prompt non e' stato fatto con un modello di frontiera**
  (debito 8 di `TODO`): quello che e' misurato e' che il trait giusto e' nel
  testo reso per ciascun prompt e che la richiesta e' cablata fino alla
  geometria. Che il modello lo scelga va misurato con una chiave vera.
* **Il filtro di rilevanza dei trait fa ancora la domanda di V3** (debito 12):
  mostra un trait quando un pezzo **della rosa** soddisfa il bersaglio della sua
  regola, e i ponti fra le parole del §5 lo aggirano per i sei trait nuovi come
  quelli di V3.5 lo aggiravano per i tre strutturali. La correzione vera resta
  seguire gli `Attachment` dichiarati in modo transitivo.
* **`repair_brief` mescola le `alternatives` fra voci dello stesso codice**
  (§16): si vede per la prima volta con tre `FRAME_CONVERTIBLE`, riguarda tutti
  i codici, e correggerlo e' un cambio di quel modulo.
* **I debiti di V4 restano tutti**: l'impronta di contenuto ricalcolata a ogni
  caricamento, l'indice non persistito, il GLB non incorporato in `.my3d`, i
  materiali glTF come colore e non come materiale, un solo `mesh` per
  componente. E quelli di V3/V3.5: il retrieval che mette le parti davanti agli
  interi, il `MockPlanner` che non scrive trait strutturali, `fx:bend` con
  `scope: "model"` che si perde, il prototipo strutturale che non si crea dal
  nulla.

---

## 19. Riprodurre le misure

```bash
python -m pytest -q                                        # 1598 passed
python -m pytest -q tests/test_semantic_variability.py     # i 65 della variabilita'
python -m pytest -q tests/test_frame_contract.py           # i 27 del frame
python tools/variability_benchmark.py 7                    # le tabelle dei §9 e §11
```

Il contratto, letto dal codice invece che da questo documento:

```bash
grep -rn "mesh_backed\|is_mesh\|kind == \"data\"" app/build/ app/core/ --include=*.py \
  | grep -v data_plugin.py | grep -v registry.py
grep -rn "squash\|elongate\|taper\|twist\|head_scale\|hand_scale\|part_scale" \
  app/core/*.py app/core/planner/*.py | grep -v app/core/frame.py
```

Che cosa il planner vede davvero, per un prompt:

```bash
python -c "
from app.core.session import Session
v = Session().vocabulary('low_poly', prompt='a humanoid with a huge head')
print([t.id for t in v.traits])
print([c.to_text() for c in v.components if c.id.endswith(':head')][0])"
```

Il plugin dati con i knob semantici, scritto su disco da ispezionare a mano:

```bash
python -c "
import sys, tempfile; sys.path[:0] = ['.']
from pathlib import Path
from tests.data_plugin_fixtures import write_variable_plugin
print(write_variable_plugin(Path(tempfile.mkdtemp())))"
```
