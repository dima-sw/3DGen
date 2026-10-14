# 3DGen - Structural Traits, Layout Regions, and Adaptation Planning

Specifica architetturale. Stato: design only. Nessuna implementazione runtime.

Obiettivo:

> a structural trait decides what must exist; a graph rewrite creates valid
> semantic instances; a layout policy decides how those instances occupy an
> allowed region; the backend computes exact placement.

E:

> strange is allowed; invalid is not.

Questa proposta continua la V1 dei Semantic Traits senza trasformarla in un
motore di struttura. Il core non deve imparare cosa siano fox, tail, car,
wheel, human, arm, dragon, horn, lantern o cannon. Deve conoscere solo intenti
strutturali, rewrite data-only, istanze, mount, regioni, policy di layout, fit,
validazione e provenienza.

---

## STRUCT-A. Current architecture reuse

Il codice corrente ha gia' i contratti giusti per evitare una pipeline parallela
domain-specific:

| Esistente | Riuso strutturale/layout |
|---|---|
| `CompositionGraph` | rappresenta cosa l'utente vuole; e' serializzabile e targettabile |
| `CompositionGraph.path()` / `on:` | precedente per indirizzare parti dichiarate da componenti |
| `Component.children()` | espansione dichiarativa dei figli di un componente |
| `Attachment` | descrive quale componente aggiungere e con quale requisito |
| `Component.provides` / `mounts` | contratto semantico non geometrico tra parti |
| `Mount.capacity` | precedente minimale per capienza dichiarata |
| `Resolver` | risolve componenti, parametri, children e link senza geometria |
| `TraitResolver` | risolve intenti deformazionali su `ResolvedComposition` |
| `Piece.sockets` / `Socket` / `Placement` | frame geometrici reali prodotti dal build |
| `Builder` | calcola placement finale usando socket veri e scala uniforme |
| `BuildResult.bounds` / validation | misura e diagnostica dopo la costruzione |
| `Report` | canale per problemi, conflitti e fallback leggibili |
| `Registry` / planner vocabulary | indice deterministico esponibile ai planner |

Osservazione fondamentale dal codice:

- i children dichiarati dai componenti diventano visibili nel `Resolver`;
- i parametri sono risolti nel `Resolver`;
- i Semantic Traits V1 modificano valori/effects dopo il `Resolver`;
- i socket veri, i bounds e le trasformazioni esistono nel `Builder`;
- la validation trova giunti, compenetrazioni AABB, bounds e requisiti dopo il build.

Quindi il nuovo layer non deve sostituire il Resolver e non deve usare il
TraitResolver V1 come scorciatoia. Deve inserirsi in due punti distinti:

```text
CompositionGraph
-> StructuralTraitResolver / GraphRewritePlan
-> expanded CompositionGraph
-> Resolver
-> TraitResolver
-> Layout planning
-> EffectPipeline
-> Builder
-> Validate
```

Per la V1 futura il layout puo' essere un pass esplicito prima del build finale,
con misure derivate da envelope dichiarati o da una misura locale controllata.

---

## STRUCT-B. Semantic vs Structural Traits

Un Semantic Trait modifica qualcosa che esiste gia'. Esempi: `body_mass`,
`leafiness` come volume della chioma, `muscularity`, `damage` su una parte
presente. La sua pipeline naturale e':

```text
ResolvedComposition -> TraitResolver -> ParamPatch / EffectRequest
```

Un Structural Trait modifica cosa esiste. Esempi: `tail_count`, `wheel_count`,
`arm_count`, `horn_count`, `branch_count`. Puo' aggiungere, rimuovere,
duplicare, sostituire o garantire quantita'. Questo non puo' essere V1
`TraitResolver`, perche' quel resolver lavora su nodi gia' risolti e produce
patch/effect, non nuovi nodi del grafo.

Separazione concettuale:

```text
Composition: what exists.
Layout: where repeated or related things go.
Effects: how an existing subtree is transformed.
Style: what visual language it follows.
```

Esempio:

- "9 tails" e' struttura;
- "fan them behind the body" e' layout;
- "outer tails bend upward" e' effect;
- "chunky fantasy" e' style.

Questi concetti non devono collassare nello stesso JSON.

---

## STRUCT-C. Structural Trait data model

Il modello dati dovrebbe essere parallelo ai Semantic Traits, ma separato:

```json
{
  "trait": "std:instance_count",
  "value": 9,
  "on": "fox/body/tail",
  "scope": "local",
  "mode": "exact",
  "target": {
    "role": "tail",
    "capability": "limb_mount",
    "tags": ["tail"]
  }
}
```

Campi concettuali minimi:

- `trait`: id namespaced, per esempio `std:instance_count`;
- `value`: valore validato da `ParamSpec` o equivalente;
- `on`: target path o prototype path;
- `scope`: per V1 solo `local` o `children`;
- `mode`: `exact` o `best_effort`, inizialmente opzionale con default `exact`
  quando il prompt contiene un numero esplicito;
- `target`: vincolo semantico opzionale per trovare istanze compatibili.

Un `StructuralTraitSpec` dichiara tipo valore, range, scope ammessi e finalita'.
Un `StructuralTraitRule` registrato da un plugin traduce request strutturali in
un `GraphRewritePlan`. La rule non muta il grafo direttamente.

---

## STRUCT-D. `instance_count` vs domain-specific count traits

Il concetto universale non e' davvero `tail_count`; e':

> ensure N instances of this semantic child.

`std:instance_count` dovrebbe essere il trait standard minimo. Il target puo'
essere un prototype path (`fox/body/tail`) oppure una query semantica limitata
(`role=tail`, `tags=tail`, `provides=tail_mount` se esiste un capability
generico).

I trait domain-specific restano utili come faccia linguistica e come
compatibilita' plugin:

```text
fantasy:tail_count=9 -> std:instance_count target=tail count=9
vehicle:wheel_count=10 -> std:instance_count target=wheel count=10
creature:horn_count=20 -> std:instance_count target=horn count=20
```

Regola di standardizzazione:

- standardizzare solo meccanismi generici (`std:instance_count`,
  eventualmente `std:replace_family`);
- lasciare a plugin/extension i nomi del dominio;
- promuovere a standard solo quando piu' domini condividono lo stesso contratto
  senza lessico specifico.

---

## STRUCT-E. GraphRewritePlan

Il rewrite plan e' data-only, validabile, deterministico e serializzabile.
Subset consigliato per la prima runtime:

```json
{
  "operations": [
    {
      "op": "ensure_count",
      "prototype": "fox/body/tail",
      "count": 9,
      "group": "tails",
      "mode": "exact"
    }
  ]
}
```

Operazioni valutate:

- `ensure_count`: necessario per 9 tails, 10 wheels, 6 arms. V1 indispensabile.
- `clone`: utile come primitive interna, ma V1 puo' esporre solo
  `ensure_count` e implementare cloning semanticamente.
- `remove`: utile per "senza ruote" o conflitti futuri; non serve al primo set.
- `replace`: gia' esiste `swap`; una versione strutturale puo' arrivare dopo.
- `attach`: gia' esiste `CompositionGraph.attach`; non serve come op nuova V1.

Subset minimo raccomandato: solo `ensure_count`, con semantica formalizzata.
Il backend produce gli id, non il planner.

---

## STRUCT-F. Prototype/clone semantics

Quando si chiedono 9 code, le altre 8 non devono copiare mesh. Devono duplicare
una descrizione di nodo e lasciare al Resolver/Builder il lavoro normale.

Fonti prototipo, in ordine:

1. Existing child as prototype: clona semanticamente `fox/body/tail`, inclusi
   ref, attachment, params espliciti, material, tags e effects locali.
2. Registry component ref: se non esiste ancora un child, una rule puo'
   indicare `fox_stylized:tail` o un ref equivalente.
3. Capability-compatible selection: il resolver sceglie un componente che
   soddisfa role/capability/tags dichiarati, con lo stesso meccanismo di
   registry gia' usato.

V1 dovrebbe preferire il prototipo esistente, perche' riusa i component children
attuali e non duplica la logica di selezione del Resolver. Se il prototipo nasce
da un child dichiarato dal componente e non dal graph iniziale, il processo
corretto e' una pre-resolve leggera o una rule che sa indicare il componente di
default. Non si deve costruire mesh per clonare.

---

## STRUCT-G. IDs/path semantics

L'attuale `CompositionGraph.path()` usa `/` e `node(key)` risolve id o path
esatto. Non c'e' sintassi bracket. Quindi la forma piu' compatibile e':

```text
tail
tail_2
tail_3
...
tail_9
```

Non usare `tail[0]`, perche' introdurrebbe una nuova grammatica nei path e nei
target `on:`. La policy di id:

- conserva l'id del prototipo come prima istanza quando esiste;
- crea suffissi `_2`, `_3`, ... in ordine crescente;
- se un id e' gia' occupato, continua con il primo suffisso libero e registra
  mapping in provenance;
- non dipende dall'ordine del filesystem;
- rimane serializzabile e targettabile: `fox/body/tail_5`.

Gli id creati diventano target normali per override, Semantic Traits ed effects:
`tail_5 longer`, `body_mass on tail_3`, `bend part:tail_9`.

---

## STRUCT-H. Structural resolution pipeline position

Il punto corretto e' prima del `Resolver` principale:

```text
Planner
-> CompositionGraph with structural trait requests
-> StructuralTraitResolver
-> GraphRewritePlan
-> expanded CompositionGraph
-> Resolver
-> Semantic TraitResolver
-> Layout planning
-> EffectPipeline
-> Builder
-> Validate
```

Ragione:

- il Resolver deve vedere il grafo espanso per risolvere parametri, children e
  occupazione dei mount in modo uniforme;
- i Semantic Traits devono poter colpire anche i nodi creati;
- i socket non esistono ancora, quindi la fase strutturale non puo' decidere
  coordinate;
- layout dipende da parametri e Semantic Traits, quindi viene dopo il
  TraitResolver;
- Effects locali devono seguire il layout base o, dove gia' accade, muovere i
  socket insieme alla mesh senza contraddire il placement.

Caso delicato: i children automatici diventano visibili solo nel Resolver. Per
`ensure_count` su un child automatico esistono due strategie:

1. V1: la Structural Extension deve indicare un prototype/ref sufficiente prima
   del Resolver.
2. V2: pre-resolve dichiarativo che espande solo children metadata senza build,
   poi applica rewrite, poi Resolver completo.

La V1 dovrebbe usare la prima strada per ridurre rischio.

---

## STRUCT-I. Layout architecture

Il layout non decide cosa esiste. Riceve un grafo risolto ed espanso e produce
un `LayoutPlan` data-only:

```json
{
  "placements": [
    {
      "node": "fox/body/tail_3",
      "region": "rear_tail_region",
      "policy": "fan",
      "frame_index": 2,
      "scale": 1.0
    }
  ],
  "problems": []
}
```

Il piano contiene riferimenti a regioni e policy registrate, non coordinate LLM.
Il backend genera attachment frames deterministici e li collega al meccanismo
esistente di socket/placement. Il modo piu' elegante e':

```text
LayoutRegion -> LayoutPolicy -> generated attachment frames -> normal socket attachment
```

Il Builder puo' restare il posto in cui la posa finale diventa matrice. Il
LayoutEngine prepara parent frame virtuali o socket virtuali validati, poi il
Builder li usa come usa i socket reali.

---

## STRUCT-J. Socket vs LayoutRegion

Socket:

- punto/frame preciso;
- buono per one head, one sword, one nest, one wheel in known position;
- nasce dal `Piece.build`;
- ha position, direction, up, radius, capabilities, side, tags.

LayoutRegion:

- dominio nel quale N child possono essere organizzati;
- buono per spikes along a back, wheels along vehicle sides, tails around rear
  pelvis, windows across facade, fruit across crown;
- descrive frame locale, span/area, asse preferito, child capability ammessa,
  capacity, policy default, spacing e range scala;
- puo' generare socket virtuali.

Una region non deve sostituire i socket. Deve essere concetto separato che puo'
referenziare uno o piu' socket reali come anchor. Esempio: `rear_tail_region`
puo' usare il socket `tail_socket` come centro e generare 9 frame fan.

---

## STRUCT-K. LayoutPolicy model

Una `LayoutPolicy` e' una funzione deterministica registrata:

```text
policy(region, child_envelopes, count, constraints, seed) -> frames | problem
```

Input minimo:

- `region`: frame locale, span/area, normal/up, side/symmetry, capacity;
- `children`: envelope, own_socket, scale limits, tags/role;
- `count`;
- `constraints`: min spacing, orientation, ground contact, symmetry;
- `style_hints`: solo preferenze tra policy dichiarate, non coordinate;
- `seed`: per varianti deterministiche quando ammesso.

Output:

- frame virtuali ordinati;
- scale uniforme per instance, entro bounds;
- diagnostica fit;
- provenance.

Le policy possono essere registrabili come plugin objects: data schema piu'
implementazione backend deterministica. Il planner puo' scegliere solo policy
registrate e consentite dalla region.

---

## STRUCT-L. Deterministic policies

Policy candidate:

- `fan`: copre code, corna posteriori, spine decorative. Parametri minimi:
  `spread_angle`, `elevation`, `depth_offset`, `center_bias`. Per 9 code con
  spread 140 produce angoli deterministici: -70, -52.5, -35, -17.5, 0, 17.5,
  35, 52.5, 70. Puo' alternare elevazione/depth per evitare coplanarita'.
- `linear`: copre ruote lungo un lato, finestre, lanterne su una trave. Usa
  span, count, min spacing, alignment e scale range.
- `paired`: non e' sempre una policy geometrica autonoma. Per 10 ruote, due
  regioni `left_side` e `right_side` con `linear` possono bastare. `paired`
  serve quando il vincolo di simmetria deve accoppiare due regioni e fallire se
  una non puo' rispettare l'altra.
- `radial`: copre rami attorno a tronco, corna a corona, cannoni su torretta.
  Usa asse, radius/elevation band e count.
- `stagger`: copre fallback quando una linea non entra o quando lo stile
  consente alternanza. Meglio come modifier applicabile a `linear`/`radial`,
  ma puo' essere policy V2.

V1 futura consigliata:

- `fan`;
- `linear`;
- simmetria a due regioni;
- `radial` solo se serve per tree/six-arm benchmark;
- `stagger` rinviato a V2 o usato solo come Adaptation operation.

---

## STRUCT-M. Bounds/envelope strategy

Il layout ha bisogno di sapere se qualcosa entra prima del placement finale.
Le opzioni:

Metadata envelope:

- pro: cheap, disponibile prima del build;
- contro: duplica la verita' geometrica e puo' divergere.

Local geometry measurement:

- pro: misura la mesh reale prodotta dal componente;
- contro: introduce ordine/build complexity, specialmente con children.

Raccomandazione: usare una strategia ibrida.

1. Aggiungere in futuro un contratto opzionale `layout_envelope(params)` o
   `preferred_bounds` per componenti semplici e per planning cheap.
2. Permettere al LayoutEngine di costruire child leaf/local in coordinate locali
   per misurare bounds quando serve accuratezza.
3. Non costruire l'intero modello due volte in V1. Misurare solo prototipi o
   children ripetuti, memoizzando per `(component, params, style, detail)`.

La validation esistente resta post-build e non diventa un solver.

---

## STRUCT-N. Fit model

Il LayoutEngine deve restituire:

```text
SUCCESS
```

oppure:

```text
LAYOUT_PROBLEM
```

Taxonomy minima:

- `insufficient_span`: non c'e' spazio lungo l'asse principale;
- `overlap`: envelope si sovrappongono oltre tolleranza;
- `capacity_exceeded`: region o mount non accetta count;
- `scale_below_minimum`: scale-to-fit richiederebbe scala sotto il minimo;
- `no_compatible_region`: nessuna region accetta quel child;
- `symmetry_conflict`: i lati non possono mantenere coppie/simmetria;
- `invalid_attachment`: frame/socket/own_socket non validi.

Il fit e' basato su envelope, spacing e occupancy. Non e' un collision solver
generale.

---

## STRUCT-O. Scale-to-fit

`scale_to_fit` e' una capacita' del layout, non un permesso globale.

Una region dichiara:

```json
{
  "min_scale": 0.75,
  "max_scale": 1.1,
  "allow_scale_to_fit": true
}
```

Il backend puo' ridurre uniformemente i child fino al minimo. Se per far entrare
10 ruote servirebbe `scale=0.61` e il minimo e' `0.75`, il risultato e'
`scale_below_minimum`, non una ruota minuscola. I limiti appartengono al
contratto della region/plugin.

---

## STRUCT-P. LayoutProblem

`LayoutProblem` e' un oggetto strutturato e piccolo:

```json
{
  "code": "insufficient_span",
  "parent": "car/body",
  "child_role": "wheel",
  "requested": 10,
  "placed": 6,
  "remaining": 4,
  "region": "side_wheel_regions",
  "required_span": 3.4,
  "available_span": 2.6,
  "min_scale": 0.75,
  "attempts": [
    {"policy": "linear", "result": "insufficient_span"},
    {"policy": "linear", "scale": 0.75, "result": "scale_below_minimum"}
  ]
}
```

Questo e' l'unico input legittimo per un futuro Adaptation Planner. Non contiene
mesh, sorgenti Python o vocabolario globale.

---

## STRUCT-Q. Adaptation Planner contract

L'Adaptation Planner e' un secondo uso opzionale dell'LLM. Non e' un visual
judge e non decide coordinate. Riceve solo:

- subject role/tags;
- child role/tags;
- requested count e mode;
- bounds/envelopes rilevanti;
- problema di fit;
- regioni disponibili dichiarate;
- policy consentite;
- range scala;
- param parent pubblici modificabili;
- style hints compatti.

Output JSON piccolo:

```json
{
  "operations": [
    {
      "op": "use_alternate_region",
      "region": "upper_side",
      "policy": "stagger",
      "count": 4,
      "scale": 0.75
    }
  ]
}
```

Il backend valida ogni campo: strategy, region, param, component, count, scale,
policy e compatibilita'. Unknown significa invalid plan.

---

## STRUCT-R. Allowed operations

Operazioni ammesse per Adaptation V2:

- `retry_policy`: stessa region, policy diversa dichiarata;
- `scale_to_fit`: scala entro min/max;
- `use_alternate_region`: sposta una quota in region dichiarata;
- `split_across_regions`: divide count tra region compatibili;
- `patch_parent_param`: modifica un `ParamSpec` pubblico dichiarato come
  layout-adaptable, per esempio `body_length`;
- `relax_mode_to_best_effort`: solo se l'intento originale lo consente.

Operazioni vietate:

- coordinate XYZ libere;
- rotation Euler libera;
- patch mesh;
- eseguire Python;
- inventare socket o region;
- inventare parametri;
- ignorare capacity, scale constraints o symmetry;
- bypassare ParamSpec.

Se in futuro servono offset, usare valori normalizzati bounded:
`offset_along_region: -1..1`, `rotation_bias: -15..15`, dentro frame dichiarati.

---

## STRUCT-S. LLM call budget

Policy esistente:

```text
Composition generation + max 1 repair
```

Futuro:

```text
Adaptation generation: 0 or 1
Adaptation repair: max 1, and only schema/validation repair
```

Nessun loop generate/render/judge. Nessun "make it prettier". Se il piano
adattato non fitta, si produce fallback deterministico o errore strutturato.

Per V1 runtime raccomandata: nessun Adaptation Planner. Solo structural rewrite
e layout deterministico. Questo riduce la superficie di failure e permette di
testare prima i contratti.

---

## STRUCT-T. Failure/fallback behavior

Modalita':

- `exact`: se l'utente ha chiesto un numero esplicito, default a exact. Se non
  si possono piazzare tutte le istanze, fallire con diagnostic strutturato.
- `best_effort`: se il linguaggio e' vago ("many wheels", "lots of horns"), il
  planner puo' chiedere best effort. Il backend puo' mantenere il massimo valido
  e deve dichiarare `placed/requested`.

Se Adaptation Planner timeout, provider unavailable, output invalid, operazione
non consentita o fit ancora fallito:

- `exact`: fail generation with `LAYOUT_PROBLEM`;
- `best_effort`: keep maximum valid instances with diagnostic.

Mai restituire 6 ruote come se fossero 10.

---

## STRUCT-U. Provenance

La provenance deve essere leggibile e serializzabile:

```text
structural trait fantasy:tail_count=9
matched rule: kitsune_extension:tail_count
normalized trait: std:instance_count target=tail count=9 mode=exact
prototype: fox/body/tail
existing: 1
created: tail_2 ... tail_9
layout: rear_tail_region
policy: fan spread=140
adaptation: not required
final: 9/9 placed
```

Per fit/adaptation:

```text
structural trait vehicle:wheel_count=10
linear layout failed: insufficient_span
scale_to_fit failed: minimum=0.75 required=0.61
adaptation planner selected: alternate_region + stagger
validated operations: upper_side count=4 scale=0.75
final: 10/10 placed
```

La provenance non e' decorativa: serve per debug, save/load, UI e test.

---

## STRUCT-V. Save/load

Per `.my3d` salvare tutti questi livelli:

1. structural intent originale;
2. expanded CompositionGraph;
3. GraphRewritePlan validato;
4. LayoutPlan validato;
5. AdaptationPlan validato, se usato;
6. provenance.

Reload deve ottenere lo stesso modello senza chiamare LLM. Se un Adaptation
Planner ha scelto `stagger + upper_side`, quella scelta validata viene congelata
nel file. Il sistema puo' rigenerare deterministicamente solo se versione,
registry e contratti sono compatibili; altrimenti usa il piano salvato o segnala
incompatibilita'.

Tradeoff:

- salvare solo intent e rigenerare e' compatto ma fragile;
- salvare solo expanded graph perde perche' si e' arrivati li';
- salvare layout/adaptation rende il file piu' grande ma riproducibile.

Raccomandazione: salvare intent + piani validati + graph espanso.

---

## STRUCT-W. Nine-tail fox end-to-end

Prompt:

```text
una volpe a 9 code
```

Planner:

```json
{
  "root": {"id": "fox", "ref": "fox_stylized:fox"},
  "traits": [
    {
      "trait": "fantasy:tail_count",
      "value": 9,
      "on": "fox/body/tail",
      "scope": "local"
    }
  ]
}
```

Structural Extension:

```text
fantasy:tail_count -> std:instance_count target=tail count=9
```

GraphRewritePlan:

```json
{
  "operations": [
    {
      "op": "ensure_count",
      "prototype": "fox/body/tail",
      "count": 9,
      "group": "tails",
      "mode": "exact"
    }
  ]
}
```

Expanded graph:

```text
fox/body/tail
fox/body/tail_2
...
fox/body/tail_9
```

Layout:

- parent/plugin declares `rear_tail_region`;
- region allows child tags/capability compatible with tail;
- default policy `fan`;
- backend produces 9 virtual frames at deterministic angles over 140 degrees,
  with slight elevation/depth alternation if declared;
- normal Resolver/Effects/Builder continue.

Who knows "tail":

- planner/extension/plugin vocabulary can expose tail as tag/role/prototype;
- core sees only `std:instance_count`, compatible target, region and policy.

---

## STRUCT-X. Ten-wheel car end-to-end

Prompt:

```text
un'auto a 10 ruote
```

Structural:

```text
vehicle:wheel_count=10 -> std:instance_count target=wheel count=10
```

Scenario A: all fit.

- existing 4 wheel instances count toward requested total;
- `ensure_count` creates 6 more;
- left/right wheel regions each receive 5 instances;
- two `linear` layouts preserve side symmetry;
- final 10/10 placed.

Scenario B: scale-to-fit works.

- linear spacing at scale 1.0 fails with `insufficient_span`;
- region allows `min_scale=0.75`;
- backend computes scale 0.82;
- final 10/10 placed with provenance `scale_to_fit`.

Scenario C: deterministic fit fails.

- scale required would be 0.61, below min 0.75;
- LayoutProblem includes available alternate regions, e.g. `upper_side` or
  `rear`, only if plugin declared them;
- future Adaptation Planner may choose:

```json
{
  "operations": [
    {"op": "split_across_regions", "region": "side", "count": 6, "policy": "linear"},
    {"op": "use_alternate_region", "region": "upper_side", "count": 4,
     "policy": "stagger", "scale": 0.75}
  ]
}
```

This is strange but valid if the plugin declared those affordances. If not,
`exact` fails with diagnostic.

---

## STRUCT-Y. Six-arm humanoid end-to-end

Prompt:

```text
umano con sei braccia
```

Problem:

- traditional left/right shoulder sockets accept one arm each;
- simply attaching three arms to the same socket creates overlap and crowded
  mounts;
- this is layout, not anatomy or IK.

Design:

- torso declares left/right upper torso arm regions, or one bilateral shoulder
  region;
- `std:instance_count target=arm count=6 mode=exact`;
- existing two arms count toward total;
- four arms are cloned semantically from arm prototypes;
- layout uses paired bilateral region: 3 per side;
- each side can use fan/radial small-angle frames around shoulder/upper torso;
- no IK; arms are repeated subtrees with valid attachment frames;
- effects after layout may bend or exaggerate arms.

Core sees repeated compatible limb instances and a region/policy. Plugin owns
whether those regions exist.

---

## STRUCT-Z. Tree branch example

Prompt:

```text
tree with 8 major branches
```

Tree already has semantic branching, so `std:instance_count` on a branch
prototype is sufficient:

```text
prototype: tree/trunk/branch_l
count: 8
target tags: branch, major
```

Layout:

- trunk exposes `major_branch_region`;
- policy `radial` or `staggered_radial`;
- count 8 around trunk with vertical/elevation bands;
- style may prefer irregular ordering, but placement remains deterministic.

This is the right organic benchmark for layout because it tests repeated
semantic children without requiring a general procedural tree solver.

---

## STRUCT-AA. Extension model

Third-party Structural Trait Extension:

- registers `StructuralTraitSpec`;
- registers `StructuralTraitRule`;
- translates trait request into `GraphRewritePlan`;
- never mutates graph directly;
- can depend on public roles/tags/capabilities/prototype paths.

Third-party LayoutPolicy:

- registers policy id, schema, constraints and deterministic implementation;
- declares which inputs are allowed;
- returns frames or `LayoutProblem`;
- cannot call LLM or run arbitrary code as part of data validation.

Third-party Component/LayoutAffordance:

```json
{
  "regions": [
    {
      "id": "rear_tail_region",
      "anchor_socket": "tail_socket",
      "allows": {"tags": ["tail"]},
      "default_policy": "fan",
      "allowed_policies": ["fan"],
      "capacity": 12,
      "min_spacing": 0.08,
      "min_scale": 0.8,
      "max_scale": 1.1
    }
  ],
  "adaptation": {
    "allow_parent_resize": false,
    "allowed_parent_params": []
  }
}
```

Keep the contract small. New laws should be installable, but not by expanding
core domain knowledge.

---

## STRUCT-AB. Conflict semantics

No hidden last-wins.

Conflicts:

- `ensure_count tails=9` and `ensure_count tails=3` on same channel;
- `ensure_count tails=9` and `remove tails`;
- two rules create same deterministic id;
- layout policies claim same exclusive region slots;
- `exact` request exceeds declared hard capacity.

Use channels analogous to Semantic Traits:

```text
(target_family, structural_property)
(parent_region, child_group)
(node_id, rewrite_op)
```

If multiple rules write the same channel and are not declared composable, report
`STRUCTURAL_RULE_CONFLICT` and skip that channel. Additive requests can compose
only when a rule explicitly defines merge semantics, e.g. max count for
`best_effort` or exact equality for two identical counts.

---

## STRUCT-AC. Interaction with Semantic Traits

Order:

```text
Structural expansion -> Resolver -> Semantic TraitResolver -> Layout
```

Reasons:

- structural clones must be targettable by Semantic Traits;
- Semantic Traits may change dimensions (`tail_volume`, `body_mass`,
  `leafiness`) needed by layout;
- explicit structural intent should override detail gating.

Detail-level precedence:

- explicit structural user intent opens the required parts even if normal
  detail level would omit them;
- automatic plugin children still follow detail unless they are prototypes or
  targets of explicit structure.

Explicit children:

- compatible existing instances count toward `ensure_count`;
- if graph already authored 3 tails and request is 9, create 6 more, not 9.

Local overrides:

- generated paths are normal targets: `tail_5` can be longer, bent or styled
  through existing override/trait/effect mechanisms.

---

## STRUCT-AD. Interaction with Effects

Layout produces base attachment frames. Effects transform existing geometry or
subtrees. They should not both own the same decision.

Correct split:

```text
9 tails -> fan layout -> outer tails bend upward effect
```

The Builder already applies local effects before children placement so sockets
move with deformed geometry. Layout must respect that by either:

- running after Semantic Traits but before local effects are applied, while
  effects remain responsible for post-layout deformation; or
- using measured local geometry before effects and letting effects move sockets
  as today.

No layout policy should secretly implement `bend`.

---

## STRUCT-AE. Interaction with Styles

Style can influence availability and preference, not geometry math by itself.

Examples:

- `chaotic_fantasy` may prefer `stagger` over perfect symmetry if region allows
  both;
- `low_poly` may prefer fewer, stronger branches or wider spacing;
- `toy_vehicle` may allow upper-side wheels if component declares that region.

Style does not invent regions, free coordinates or bypass fit.

---

## STRUCT-AF. Backward compatibility

Additive requirements:

- graph without structural traits behaves exactly as today;
- plugins without LayoutRegion continue to use socket placement;
- existing `TraitResolver` remains deformational;
- existing `.my3d` files load without layout/adaptation fields;
- existing `Component`, `Attachment`, `Piece`, `Socket` remain valid contracts.

Any API addition should be optional and gated by feature presence.

---

## STRUCT-AG. Minimal implementation recommendation

Recommend:

```text
V1 = deterministic Structural + Layout
V2 = LLM Adaptation
```

V1 smallest useful runtime:

Structural:

- `StructuralTraitSpec`;
- `StructuralTraitRequest`;
- `GraphRewriteRule`;
- `GraphRewritePlan`;
- only `ensure_count`;
- deterministic id generation;
- provenance.

Layout:

- `LayoutRegion`;
- `LayoutPolicy`;
- `LayoutPlan`;
- `fan`;
- `linear`;
- symmetric two-region assignment;
- optionally `radial` if tree/six-arm needs it.

Fit:

- region span;
- child envelope/bounds;
- min spacing;
- bounded scale-to-fit.

No Adaptation Planner in V1. Demonstrate:

- 9 tails -> fan;
- 10 wheels -> linear left/right with scale-to-fit;
- 6 arms -> bilateral region/fan without IK.

V2:

- `LayoutProblem`;
- Adaptation Planner input/output schemas;
- allowed operations;
- frozen adaptation results in save/load.

This staged plan is better than implementing everything together because it
tests the hardest deterministic contracts before adding a second LLM boundary.

---

## STRUCT-AH. Risks

- graph explosion: counts can create too many nodes; require budgets and max
  count per trait/region.
- invalid count: zero, negative, fractional or huge values need coercion and
  diagnostics.
- layout recursion: structural expansion must not repeatedly clone clones
  forever; plans apply once per request/provenance id.
- duplicated semantics: avoid both `tail_count` and `instance_count` owning the
  same behavior; domain traits normalize to generic ops.
- circular parameter/layout dependencies: layout may read semantic params, but
  parent adaptation must be a separate bounded operation.
- LLM overreach: Adaptation Planner can choose only registered policies,
  declared regions and public params.
- save/load nondeterminism: freeze expanded graph and validated layout/adaption
  plans.
- collision complexity: use envelope/spacing/occupancy only; do not build a
  general CAD solver.
- plugin contracts becoming too large: keep LayoutRegion and affordances
  minimal; add fields only when a benchmark proves the need.

---

## STRUCT-AI. Files changed

Only documentation:

```text
STRUCTURAL-TRAITS-AND-LAYOUT.md
```

