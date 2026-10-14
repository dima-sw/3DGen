# VISION-GAP — 3DGen rispetto alla visione di prodotto

Analisi del working tree al **14 ottobre 2026**, a valle di `PRODUCT-AUDIT.md`.
Nessuna implementazione, nessun refactoring, nessun test toccato, nessun commit.

Principio usato per giudicare ogni voce, come richiesto:

> La libreria contiene la conoscenza 3D.
> L'LLM compone quella conoscenza.
> Il core non conosce il dominio.

---

## Verdetto in testa

**Il sistema può evolvere naturalmente nella direzione descritta.** Le fondamenta
sono giuste e verificate: il contratto `Component` è già agnostico rispetto al
backend geometrico, la ricorsione è già una proprietà dei componenti, il core è
davvero privo di dominio, e un motore di retrieval completo esiste già nel
repository.

Due eccezioni, entrambe nel livello aggiunto più di recente:

1. **I trait strutturali sono una direzione sbagliata**, non solo un'implementazione
   difettosa. Legano un comportamento semantico a un percorso di nodi letterale.
2. **Archetypes / profiles / bindings sono un secondo catalogo parallelo**, da
   mantenere a mano, che duplica conoscenza che i componenti già dichiarano. Ma
   l'**algoritmo** che contengono è esattamente quello che la visione chiede: va
   riusato, non buttato.

Un terzo punto non è una divergenza ma un'assenza: **la pipeline di retrieval non
esiste** fra il prompt e il planner, mentre il motore per costruirla è già scritto
e funzionante in `app/assets/semantic.py`, puntato però sul corpus sbagliato.

---

## Quadro riassuntivo

| Sottosistema | Stato | In una riga |
| --- | --- | --- |
| Plugin Registry | **ALIGNED** | vocabolario installabile, dispatch per tipo, zero dominio nel core |
| Component | **ALIGNED** | `build → Piece`: il contratto è già indipendente dal backend |
| recursive attachments / `detail_level` | **ALIGNED** | ricorsione dei componenti verificata; profondità guidata dal livello |
| capabilities | **ALIGNED** | `provides`/`accepts` + punteggio di innesto; è il contratto portante |
| Resolver | **PARTIAL** | risolve e compone; **non degrada** semanticamente |
| ConceptResolver | **PARTIAL** | l'algoritmo di degradazione è giusto; è alimentato e cablato male |
| archetypes | **PARTIAL / OVERENGINEERED** | la gerarchia serve; il catalogo separato a mano no |
| profiles | **OVERENGINEERED** | 1 profilo installato; è un bundle di default che i trait già sanno esprimere |
| bindings | **DIVERGENT** | tabella concept→componente scritta a mano: non scala con la libreria |
| semantic traits | **ALIGNED** | è esattamente «parametri pubblici con significato semantico» |
| structural traits | **DIVERGENT** | prototipo = percorso letterale; rotto e concettualmente sbagliato |
| LayoutEngine | **ALIGNED** | le regioni sono dichiarate dal componente, le policy sono generiche |
| EffectPipeline | **ALIGNED** | sei stadi, ordine contrattuale, effetti ignari del dominio |
| planner vocabulary | **PARTIAL** | faccia pubblica corretta, ma **nessun filtro per richiesta** |
| semantic asset index | **PARTIAL** | motore di retrieval completo, puntato sugli asset salvati invece che sui componenti |
| Builder | **ALIGNED** | esegue il piano; non sa da dove venga la geometria |
| procedural geometry kernel | **ALIGNED** | è un plugin di fatto, non un presupposto del core |
| mesh-backed components | **MISSING** (ma non bloccato) | nessun ostacolo architetturale; manca il loader e la dichiarazione dati |
| project `.my3d` | **PARTIAL** | salva piani e versioni dei plugin; **non salva** la spiegazione dell'approssimazione |
| Session | **PARTIAL** | porta unica corretta; `build()` e `generate()` hanno capacità diverse |
| UI | **PARTIAL** | buon client della sessione; nessun accesso al vocabolario, nessun authoring |

---

## 1. Fondamenta: ciò che è già allineato

### Plugin Registry — ALIGNED

`Registry.load_plugin` legge un manifesto, importa i moduli dichiarati e registra
per **tipo di oggetto**, non per categoria:

```python
if isinstance(item, Component):            self.register_component(...)
elif isinstance(item, EffectSpec):         self.register_effect(...)
elif isinstance(item, TraitSpec):          self.register_trait(...)
elif isinstance(item, ArchetypeSpec):      self.register_archetype(...)
```

Un plugin nuovo non tocca il core: verificato nel `PRODUCT-AUDIT`, due soli
riscontri testuali di nomi di dominio in `app/core`, `app/build`, `app/geometry`,
`app/ui`, e nessuno dei due è codice.

Un solo vincolo da registrare per il futuro: **i plugin sono moduli Python
importati**. Un artista che installa una libreria sta eseguendo codice di terzi nel
proprio processo. Per la visione «l'artista espande la libreria senza scrivere
codice» questo è un punto da affrontare, ed è anche una ragione in più per il
formato dati di cui al §5.

### Component — ALIGNED, e più allineato di quanto il progetto sappia

```python
@dataclass
class Component:
    id: str
    build: Callable[[dict, BuildContext], Piece]
    children: Callable[[dict, BuildContext], list[Attachment]] | None = None
    params: dict[str, ParamSpec]
    provides: tuple[Capability, ...]
    mounts: tuple[Mount, ...]
    ...

@dataclass
class Piece:
    mesh: trimesh.Trimesh | None = None
    sockets: dict[str, Socket] = ...
    material: str = ""
```

Il contratto verso core, resolver e planner è **già** quello che la visione chiede:
capabilities, accepts/provides, sockets, parameters, materials, children, bounds,
style compatibility. `build` restituisce un `Piece`; che il mesh venga da
`profile_sweep()` o da un GLB caricato da disco il resolver non lo sa e non lo può
sapere. **Non serve nessuna astrazione nuova per i componenti mesh-backed.**

`Piece.mesh` può essere `None` — un componente che esiste solo per contenerne altri
è già previsto, ed è il caso `humanoid:body`.

### Ricorsione e `detail_level` — ALIGNED

`children` è una **callable**, non una lista: l'albero dei sotto-componenti è
calcolato al momento, in funzione di `BuildContext` (stile, livello, budget, seme).
È la ricorsione come proprietà del componente, esattamente come nella visione.

`Attachment.wanted_at(detail_level, requested)` decide la profondità di espansione,
e `on_request=True` permette di chiedere una sotto-parte **senza** alzare il livello
di tutto l'albero. La visione chiede che un componente complesso possa essere usato
direttamente senza espanderlo: è ciò che fa `detail_level = 1`.

Misurato nel `PRODUCT-AUDIT`, stesso piano a livelli diversi:

| Modello | L1 | L2 | L3 |
| --- | --- | --- | --- |
| `humanoid_anatomical:body` | 564 tris / 7 nodi | 1142 / 37 | 1938 / 38 |
| `humanoid:body` (legacy) | 80 / 2 | 80 / 2 | **76** / 4 |

Il caso legacy è la prova pulita: a L3 i nodi crescono e i triangoli **calano**,
perché `replaces_parent` sostituisce il torso intero con bacino + petto. È
complessità semantica, non tassellazione.

Due limiti minori: **L4 e L5 sono vuoti** (nessun componente dichiara attachment
oltre il livello 3, mentre lo schema accetta fino a 5), e la profondità dell'albero
`humanoid_anatomical` arriva a 6 livelli (`shoulder → upper_arm → elbow → forearm →
wrist → hand`) senza che `MAX_PROFONDITA = 4` del `MockPlanner` lo preveda — il
vincolo riguarda i piani scritti dal planner, non l'espansione, ma vale la pena
saperlo.

### capabilities — ALIGNED

È il contratto portante e funziona. `Requirement.score(socket)` classifica con
cinque gradini espliciti (`EXACT_ID 5`, `CAPABILITY_AND_SIDE 4`,
`CAPABILITY_AND_TAGS 3`, `CAPABILITY 2`, `FALLBACK 1`, `INCOMPATIBLE -1`). Una
`humanoid:head` si monta su qualunque cosa esponga un innesto compatibile, e il core
non sa che cos'è una testa.

Verificato: `weapon:sword` dichiara `limb_mount` e prende il posto di una gamba;
`creature:dragon_head` si è montata su `fish:fish_body`.

Un limite reale emerso dall'audit, che **non** è un problema di capability ma di
contratto mancante: le convenzioni d'asse. `humanoid_anatomical` dichiara nel
manifesto «torso e testa crescono lungo +Y; arti lungo +X; fronte verso +Z», ma è
testo libero in `metadata`. `app/core/authoring.py` ha `growth_axis` e
`verify_frame`, e sono **helper per gli autori, non controlli imposti**. Il risultato
è il drago dell'audit, in piedi sulla coda.

### LayoutEngine — ALIGNED

`LayoutRegion` è dichiarata dal componente (`Component.layout_regions`, che può
essere anche una callable); `LayoutPolicy` è generica (`fan`, `linear`). Il motore
sintetizza i socket quando molti fratelli devono dividersi una superficie, invece di
costringere il plugin a cablarli. È il modo giusto di far scalare «sei ruote» senza
che il componente auto conosca il numero sei.

Prova: le sei ruote del `PRODUCT-AUDIT` sono state posizionate dal layout, non
dichiarate. Difetto estetico noto (distribuzione asimmetrica), ma il meccanismo è
quello giusto.

### EffectPipeline — ALIGNED

Sei stadi in ordine contrattuale (`structural`, `proportion`, `local`, `global`,
`style`, `final`), con la distinzione corretta fra «cambio **cosa** si costruirà»
(`proportion`, sui parametri) e «cambio **ciò che è stato** costruito» (i tre stadi
geometrici). `EffectSpec.applies_to` elenca capability o tag, quindi
`effects_for(capability)` risponde senza che il core sappia cosa sia un umanoide.

La visione elenca `elongate, squash, bend, twist, taper, chunky, lanky, exaggerate`.
Installati oggi: `lanky`, `chunky`, `bend`, `perspective_exaggeration`, `rotate`,
`align`, `offset`, `mirror`. Mancano `twist`, `taper`, `squash`, `elongate` —
**contenuto mancante, non architettura mancante**: si aggiungono in
`app/plugins/effects/` senza toccare nulla.

`EffectSpec.deform` muove vertici e socket con la stessa funzione, il che rende
impossibile per costruzione la desincronizzazione fra geometria e punti di innesto.
Scelta eccellente, documentata in `app/core/vocabulary.py:163-168`.

### Builder e geometry kernel — ALIGNED

Il `Builder` esegue il piano risolto: chiama `component.build(valori, ctx)`, riceve
un `Piece`, lo posa via socket. Non importa un solo simbolo da
`app/geometry/kernel.py`. Il kernel procedurale (`ring`, `sweep`, `profile_sweep`,
`grow`, `block`) è **di fatto già una libreria di plugin**, non un presupposto del
motore: lo usano i componenti, non il core.

Questo è il singolo fatto che rende la direzione mesh-backed realistica.

### semantic traits — ALIGNED

È letteralmente la sezione «Variabilità» della visione, già implementata:

```python
BODY_MASS = TraitSpec(id="std:body_mass", aliases=("body_mass",),
                      value=ParamSpec(0.5, RATIO, min=0.0, max=1.0),
                      scopes=("local", "subtree"), operations=("set", "add"))

HUMANOID_TORSO_GIRTH = TraitRule(
    trait="std:body_mass",
    match=TraitMatch(roles=("torso",), tags=("humanoid",), param_roles=("girth",)),
    patches=(ParamPatch(semantic_role="girth",
                        expression="value * (1.0 + (trait - 0.5) * 0.42)"),))
```

Il bersaglio è `role` + `tags` + `param_roles`, mai un percorso. Il trait non sa che
cosa sia un umanoide, sa che esiste un parametro con ruolo semantico `girth`.

Verificato funzionante: `botany:leafiness` cambia l'ingombro della chioma da
`[2.72, 2.86, 1.38]` a `[4.24, 3.14, 2.51]` fra valore 0,0 e 1,0.

**Questo è il modello da imitare per tutto il resto.** Il confronto con i trait
strutturali (§3) è istruttivo: stessa idea, un bersaglio dichiarativo contro un
percorso letterale, e solo uno dei due funziona.

Manca il vocabolario delle proporzioni relative — `head_scale`, `limb_length`,
`hand_scale` — che è esattamente ciò che serve per «testa enorme, gambe corte, mani
grandi». È contenuto, non architettura.

---

## 2. Matching e fallback: il cuore del divario

La visione chiede cinque gradini:

```text
1. exact semantic/component match
2. compatible specialized match
3. semantic ancestor/category match
4. composition di componenti compatibili
5. generic fallback
```

Oggi esistono **due percorsi separati**, nessuno dei quali li copre tutti.

### 2.1 Il percorso normale (`root`): nessuna degradazione

`Resolver._trova` risolve un riferimento in tre tempi:

1. nome nel plugin di casa;
2. nome ovunque (`registry.named`);
3. **come capability** — «mettici qualcosa che fornisce questo».

Il terzo gradino è buono e già allineato allo spirito. Ma se nessuno dei tre dà
risultato:

```python
out.report.add("COMPONENT_NOT_FOUND", "nessun componente '%s'" % ref,
               why="ne' un nome, ne' una capability fornita da qualcuno",
               alternatives=[c.id for c in self.registry.search(ref)][:6])
return None
```

Fine. Nessuna risalita semantica, nessuna composizione alternativa, nessun ripiego:
**errore fatale**. `jeep` non diventa mai `vehicle`.

Peggio, le `alternatives` suggerite vengono da `Registry.search`, che è dichiarata
così nel proprio docstring:

> «Ricerca testuale elementare su id, nome, descrizione e tag. Volutamente stupida:
> nessun NLP, nessun embedding. Il punteggio è il numero di parole che compaiono.»

È onesta su se stessa, ed è l'unico meccanismo «semantico» del percorso normale. È
anche il meccanismo che il `MockPlanner` usa per scegliere, ed è la ragione per cui
«jeep cartoon con sei ruote» ha prodotto `accessories:helmet`: condivisione di
parole, zero relazione semantica. **È esattamente il comportamento che la visione
vieta.**

### 2.2 Il percorso `concept`: l'algoritmo giusto, isolato

`ConceptResolver.resolve` implementa i gradini 1–3 della visione, e li spiega:

```python
direct = self.registry.component(requested)          # 1. exact
if direct is not None: ... match = "direct implementation"

def _binding_match(self, binding, expanded, requested) -> str:
    if supported & set(requested):                   # 1. exact binding
        return "exact"
    if supported & set(self._ancestors_of(expanded)):
        return "ancestor/body-plan proxy"            # 3. ancestor
    if any(requested_set & set(self._archetype_ancestors(aid)) ...):
        return "descendant/specialization implementation"   # 2. specialized
    return ""
```

`_expand_archetypes` risale la catena `parents` con rilevamento dei cicli, e
`ConceptCoverage` registra per ogni adattamento richiesto se è `supported`,
`unsupported` o `ignored`. La spiegazione dell'approssimazione — ciò che la visione
chiede esplicitamente — **esiste già come struttura dati**.

Quattro problemi, in ordine di gravità:

1. **È alimentato da un catalogo a mano.** 9 archetipi, 1 profilo, 3 binding, contro
   97 componenti installati. I tre binding sono uno per ciascun plugin benchmark.
   La copertura semantica coincide con i benchmark.
2. **I gradini 4 e 5 non esistono.** Nessuna composizione di componenti compatibili,
   nessun fallback generico. Se il binding non c'è, si muore.
3. **Il fallimento è fatale.** `CONCEPT_UNKNOWN` è severità `error`: 4 dei 5
   fallimenti con LLM reale dell'audit passano da lì. Non c'è degradazione verso il
   ramo `root`.
4. **È raggiungibile solo da `Session.generate`.** `_risolvi_concept` materializza il
   concept in un `root` prima di `validate_plan`; un piano `concept` passato a
   `Session.build` viene respinto con `un piano concept deve essere materializzato
   dal backend` (`app/core/planner/plans.py:79`). Verificato: il piano manuale
   `m01b_fox_concept`, scritto correttamente, fallisce.

### 2.3 Risposta alla domanda: è un secondo catalogo parallelo?

**Sì, ed è il punto da correggere — ma l'algoritmo va tenuto.**

Cosa duplica. Un `ArchetypeSpec` dichiara `required_capabilities`,
`preferred_capabilities`, `preferred_roles`. Un `Component` dichiara già `provides`,
`mounts`, `role`, `tags`. L'archetipo `quadruped` dice `preferred_capabilities =
("limb_mount",)`; `fox_stylized:fox` dichiara `provides = animal` e
`tags = {animal, fox, quadruped, low_poly, stylized}`. **La relazione
fox → quadruped → animal è già scritta due volte**: una nei tag e nelle capability
del componente, una nel catalogo degli archetipi. Il binding `fox_quadruped` è una
terza scrittura della stessa cosa.

Il costo è che la precisione **non cresce con la libreria**: installare 500
componenti senza scrivere a mano 500 binding non migliora il matching di un grammo.
Questo contraddice direttamente il requisito «la precisione del risultato deve
crescere con la qualità e la dimensione della libreria installata».

Cosa invece ha valore reale, e non va perso:

* la **risalita della gerarchia** con rilevamento dei cicli (`_expand_archetypes`);
* la **classificazione del match** in exact / ancestor-proxy / descendant-specialization;
* la **copertura degli adattamenti** (`ConceptCoverage`: supported / unsupported /
  ignored), che è l'unica struttura del repository capace di dire «questa è
  un'approssimazione, ed ecco cosa ho dovuto cambiare»;
* `_preflight`, che verifica che l'implementazione scelta regga davvero gli
  adattamenti richiesti prima di sceglierla.

Giudizio operativo, senza rimuovere niente: **`ArchetypeSpec` PARTIAL/OVERENGINEERED,
`ProfileSpec` OVERENGINEERED, `ImplementationBinding` DIVERGENT, l'algoritmo di
`ConceptResolver` da promuovere a cittadino di prima classe del percorso normale.**

La direzione naturale è invertire l'alimentazione: la gerarchia semantica va
**derivata** da ciò che i componenti dichiarano (capability fornite, tag, `role`),
con gli `ArchetypeSpec` che restano come **override facoltativo** per i casi che la
derivazione sbaglia — non come requisito perché un concetto esista. Un plugin che
installa 200 componenti deve diventare ricercabile senza che nessuno scriva 200
binding.

`ProfileSpec` in particolare: un solo profilo installato (`compact_quadruped`), e
ciò che fa — un bundle di valori di trait predefiniti — è già esprimibile come lista
di `traits` nel piano. Finché resta uno, è complessità senza ritorno.

---

## 3. structural traits — DIVERGENT

L'unico sottosistema di cui questo documento propone un cambio di **direzione**, non
di qualità.

```python
ARM_COUNT_RULE = StructuralTraitRule(
    trait="character:arm_count",
    prototype="corpo/torso/arm_l",            # ← percorso letterale di nodi
    component="humanoid_anatomical:arm",
    target=StructuralTarget(role="arm", tags=("arm",)))
```

Prova misurata nel `PRODUCT-AUDIT`:

```text
root id = car   → ok True,  524 tris, 28 nodi, 6 ruote
root id = jeep  → ok False, 0 tris,   0 nodi,  "parent prototype non disponibile: 'car'"
```

e `character:arm_count` non funziona su **nessun** corpo installato
(`parent prototype non disponibile: 'corpo/torso'`).

Perché è una divergenza e non un bug: il percorso letterale impone al piano una
forma precisa, cioè l'opposto del principio «il core non conosce il dominio e il
piano è libero». Un LLM che chiama la radice `jeep1` o `fantasy_tree_01` — cosa che
fa, come documentato — rompe il meccanismo. Il comportamento corretto è selezionare
il prototipo come fanno i trait semantici: per `role`, `capability`, `tags`.

L'ironia utile: `StructuralTarget` **già** supporta `role`, `capability`, `tags`,
`components`, ed è usato per il campo `target`. La stessa classe, sullo stesso
oggetto, sarebbe il selettore giusto anche per `prototype`. Non serve inventare
niente: serve smettere di usare una stringa di percorso dove c'è già un selettore.

---

## 4. Libreria grande: il retrieval che manca, e il motore che c'è già

### 4.1 Lo stato

`build_vocabulary(registry, *, style="low_poly", detail_level=2)` — **non riceve il
prompt**. Nessun filtro per richiesta. L'unico taglio è un troncamento cieco
`[:MAX_CONCEPT_SHORTLIST]` su archetipi, profili e binding, in ordine di registry,
non di rilevanza.

Costo misurato: **39 964 caratteri, ~8 200 token**, contro il limite di 8 000 del
provider primario. **413 su 8 richieste su 8.** Con 97 componenti. La visione parla
di migliaia.

### 4.2 Il motore esiste già, puntato altrove

`app/assets/semantic.py` contiene un sistema di retrieval completo e funzionante:

* `Embedder` astratto con due implementazioni, `TfidfEmbedder` e `RemoteEmbedder`
  (quindi gli embeddings «in futuro» della visione sono già previsti come
  sostituzione, non come riscrittura);
* `SemanticIndex` con `build`, `search(query, limit, threshold)`, persistenza su
  disco, `fingerprint` per l'invalidazione automatica, `signature` dell'embedder per
  rifiutare un indice costruito con un altro motore;
* un thesaurus e una tokenizzazione con stopword bilingui.

L'unico punto legato agli asset è una funzione di tre righe:

```python
@staticmethod
def document_for(record) -> str:
    return " ".join([record.name, record.name, record.prompt,
                     record.root_ref.replace(":", " "), record.category,
                     " ".join(record.tags)])
```

Indicizzare `Component` invece di `AssetRecord` significa scrivere un
`document_for(component)` che concatena id, nome, descrizione, tag, capability
fornite e accettate, `role`. Tutto il resto — ricerca, soglia, persistenza,
invalidazione — è già scritto e già testato.

**Questo è il singolo pezzo di leva più alto dell'intero sistema**: trasforma il
problema «il vocabolario non entra nel prompt» e il problema «la degradazione
semantica non esiste» in due usi dello stesso indice.

Una nota di igiene: il `THESAURUS` in `app/assets/semantic.py` è un dizionario
italiano di dominio («corazza», «verde» → «militare»). Non è nel core, ma è
conoscenza di dominio cablata nel codice dell'applicazione. Secondo il principio,
appartiene a un plugin o a un file dati, non a un modulo Python di `app/`.

---

## 5. mesh-backed components — MISSING, ma la strada è libera

### 5.1 Nessun ostacolo architetturale

Il contratto è già rispettato. Un componente mesh-backed è una `build` che carica un
file invece di chiamare `profile_sweep`:

```python
def build(valori, ctx) -> Piece:
    return Piece(mesh=trimesh.load("head.glb"), sockets={...}, material="skin")
```

Il resolver, il builder, gli effetti, il layout e il planner non cambiano di una
riga. La visione chiede che il resolver non sappia da dove viene la geometria:
**non lo sa già oggi**.

### 5.2 Ciò che manca davvero

Non è l'astrazione, sono quattro cose concrete:

1. **Una dichiarazione dati.** Oggi un componente esiste solo se un modulo Python lo
   costruisce e il registry lo raccoglie per `isinstance`. Un artista che non scrive
   codice ha bisogno di dichiarare un componente in JSON accanto al GLB — id,
   capability, socket (posizione, direzione, up, raggio), parametri, materiali,
   figli — e di un loader che produca il `Component` equivalente. Il formato
   esiste già implicitamente: è la firma di `app/core/socket.py:socket(...)` e di
   `ParamSpec`.
2. **Il significato dei parametri su una mesh fissa.** Un componente procedurale
   ricostruisce la geometria quando `head.width` cambia. Una mesh importata no: i
   parametri diventano trasformazioni (scala non uniforme, deformazioni di stadio
   `local`). È una differenza **reale** fra i due backend, e va dichiarata — per
   esempio un componente che espone i propri parametri come «rebuild» oppure
   «deform». Fingere che siano identici produrrebbe aspettative sbagliate.
3. **Il cancello di qualità.** `app/build/validate.py` verifica `manifold`,
   `watertight`, `connected`, `no_degenerate` sui componenti che li dichiarano in
   `requires`, e misura `faces_per_normal` contro la soglia 1,55 dello stile
   `low_poly`. Una mesh d'artista può fallire entrambi legittimamente. Il meccanismo
   di esenzione esiste già (`FACCETTATO in componente.requires`), ma la politica per
   i componenti importati va decisa, non ereditata per caso.
4. **La sicurezza del percorso di import.** Importare un GLB non deve voler dire
   eseguire codice. Un componente dichiarato in dati, caricato da un loader del core,
   è anche la risposta al fatto che oggi installare un plugin significa importare un
   modulo Python di terze parti.

### 5.3 Quello che la visione dice di non fare, e che il codice per ora non fa

«NON assumere che una mesh importata debba essere trasformata in geometria
procedurale.» Oggi non c'è nessun codice che lo assuma, perché non c'è nessun codice
di import. La raccomandazione va però registrata come vincolo di progetto prima di
scrivere la prima riga: l'inferenza automatica di parti, socket e parametri da una
mesh è una feature **separata e successiva**, non il modo di far entrare un GLB nel
sistema.

---

## 6. Gli altri sottosistemi

### planner vocabulary — PARTIAL

La `Vocabulary` è la faccia pubblica del registry, si aggiorna da sola quando
cambiano i plugin, e `sanitize()` è un confine di sicurezza reale: le descrizioni di
terze parti diventano una riga quotata, senza delimitatori né marcatori di ruolo,
tagliata a 160 caratteri. Un plugin non può iniettare istruzioni nel planner. Questo
è allineato e va protetto da qualunque modifica futura.

Il divario è solo l'assenza di filtro per richiesta (§4).

### semantic asset index — PARTIAL

Vedi §4.2. Motore giusto, corpus sbagliato.

### project `.my3d` — PARTIAL

Salva ciò che conta: `graph.to_dict()`, le opzioni, i nomi e le **versioni** dei
plugin installati, la storia delle versioni. Un progetto resta leggero e
rigenerabile, e il sistema può spiegare perché una rigenerazione differisce.

Divario rispetto alla visione: `_versione()` in `app/core/project.py` salva
`graph`, `options`, `prompt`, `label`, `seconds` — **non** `concept_resolution`. La
spiegazione dell'approssimazione («richiesto jeep, usato vehicle, adattamenti:
scocca più massiccia, ruote più grandi») viene calcolata e poi persa al salvataggio.
Se la degradazione semantica diventa il comportamento normale, la sua spiegazione
deve sopravvivere al progetto, perché è parte di ciò che l'utente ha accettato.

### Session — PARTIAL

La porta unica esiste davvero: UI, CLI e test passano tutti da `Session`, e non c'è
un secondo motore di generazione. Storia delle versioni, undo/redo, provenienza del
provider, ripiego mai silenzioso (`planner = "mock_fallback"`): tutto allineato.

Due divari:

* **`build()` e `generate()` non hanno le stesse capacità.** `_risolvi_concept` è
  chiamato solo da `generate`, quindi un piano `concept` costruito direttamente viene
  respinto. Chi scrive un piano a mano — un test, un tool, una futura funzione di
  modifica — non ha accesso alla stessa pipeline.
* **`GenerationResult.explain()`** elenca le scelte di componente e di innesto, ma
  **non** l'approssimazione semantica: `concept_resolution` è un campo a parte che
  `explain()` non legge. La visione chiede che la degradazione sia spiegata nel
  risultato.

Infine, già rilevato nell'audit e rilevante anche qui: `result.scene()` ha
`registry=None` per default e restituisce un modello **grigio**. La libreria contiene
anche la conoscenza dei materiali: perderla nella chiamata ovvia dell'API è una
perdita di conoscenza della libreria, non un dettaglio di rendering.

### UI — PARTIAL

Buon client sottile della sessione: non scavalca planner, registry, resolver o
builder. Ha scena, parametri, qualità, versioni, animazione, libreria, log.

Divari rispetto alla visione:

* **Nessun accesso al vocabolario.** La scheda «Libreria» mostra gli **asset
  salvati**, non i componenti installati. Non c'è modo di sfogliare ciò che i plugin
  forniscono, che è la conoscenza su cui tutto il sistema si regge.
* **Nessun authoring.** Niente import di mesh, niente definizione di socket o
  capability: la visione §«importazione di modelli come componenti» non ha oggi
  nessun punto d'ingresso nell'interfaccia.
* **Due pulsanti morti**, già documentati nell'audit: «Modifica il modello attuale»
  (`setVisible(False)`, nessun handler) e «Genera da un'immagine» (handler con un
  `return` in testa).

---

## 7. Divergenze fra la roadmap del PRODUCT-AUDIT e questa visione

| Milestone dell'audit | Esito del confronto |
| --- | --- |
| **M1** «filtrare il vocabolario per capability e tag» | **Sottodimensionata.** Un filtro euristico risolve il 413 ma non dà la degradazione semantica. La visione chiede uno **stadio di retrieval**, e il motore esiste già: stessa fatica, due problemi risolti. |
| **M2** «trait strutturali per selettore» | **Confermata e rafforzata.** Da bug-fix diventa correzione di direzione. |
| **M3** «colori, coerenza post-effetto» | **Confermata.** Il `registry=None` è anche una perdita di conoscenza della libreria. |
| **M4** «conversazione» | **Confermata, con un prerequisito nuovo**: identità stabile dei nodi. Se il planner rinomina i nodi a ogni turno, né la modifica incrementale né i trait strutturali per selettore funzionano in modo prevedibile. |
| **M5** «scrivere robot, drago, jeep a mano in Python» | **Divergente.** Contraddice «la precisione cresce con la libreria»: non si scala a migliaia di componenti scrivendone uno per volta in Python. La risposta della visione è duplice — degradazione semantica (non serve una jeep per rispondere «jeep») e import di mesh (l'artista espande la libreria senza codice). Gli asset autoriali restano utili come benchmark di qualità, non come strategia di copertura. |
| — | **Mancanti del tutto nell'audit**: componenti mesh-backed, authoring nella UI, convenzioni d'asse come contratto verificato, persistenza della spiegazione dell'approssimazione. |

---

## 8. Roadmap minima verso la visione

Cinque passi, ordinati per impatto. Nessuno introduce un'astrazione nuova dove ne
esiste già una adatta; ognuno dichiara che cosa **riusa**.

### V1 — Un solo indice semantico, due usi

**Obiettivo.** La libreria diventa cercabile; il prompt non la trascina più tutta nel
contesto.

**Riusa.** `SemanticIndex`, `Embedder`, `TfidfEmbedder`, `RemoteEmbedder`,
persistenza e `fingerprint` — tutto già in `app/assets/semantic.py`.

**Cosa cambia.** Un `document_for(component)` accanto a quello degli asset; l'indice
costruito sul registry e invalidato quando cambiano i plugin; `build_vocabulary`
accetta una shortlist. Il thesaurus di dominio esce dal codice applicativo.

**Difficoltà.** Media-bassa: è un secondo corpus per un motore esistente.

**Completo quando.** Payload sotto i 5 000 token con 97 componenti e sotto gli 8 000
con 1 000 componenti sintetici; nessun 413 sul provider primario; gli 8 prompt
dell'audit mantengono o migliorano il loro esito.

### V2 — Degradazione semantica spiegabile, sul percorso normale

**Obiettivo.** `jeep` → `vehicle` con adattamenti, mai `accessories:helmet`. Il
fallimento diventa un'approssimazione dichiarata.

**Riusa.** L'algoritmo di `ConceptResolver`: `_expand_archetypes`, `_binding_match`,
`ConceptCoverage`, `_preflight`. La gerarchia smette di essere un catalogo da
scrivere a mano e viene derivata da capability, tag e `role` dei componenti, con
`ArchetypeSpec` degradato a **override facoltativo**. `ImplementationBinding` resta
per i casi in cui un autore vuole forzare una scelta, non come requisito di
esistenza.

**Cosa cambia.** `Resolver._trova`, invece di restituire `None` con `registry.search`
fra le alternative, interroga l'indice di V1 e risale la gerarchia; i gradini 4
(composizione) e 5 (fallback generico) vengono aggiunti; `CONCEPT_UNKNOWN` da
`error` diventa `warning` con ripiego sul ramo `root`; `explain()` include il
percorso di degradazione e gli adattamenti; `_versione()` lo salva nel `.my3d`.

**Dipende da.** V1.

**Completo quando.** «jeep con sei ruote» dà un veicolo con una spiegazione
esplicita di approssimazione; nessun prompt dell'audit restituisce zero triangoli;
`Session.build` e `Session.generate` accettano gli stessi piani.

### V3 — Selettori al posto dei percorsi, e identità stabile dei nodi

**Obiettivo.** «Quattro braccia», «sei ruote», «tre code» funzionano su qualunque
piano, con qualunque nome di nodo.

**Riusa.** `StructuralTarget`, già capace di selezionare per `role`, `capability`,
`tags`, `components` — e già usato per il campo `target` della stessa regola.

**Cosa cambia.** `StructuralTraitRule.prototype` da percorso a selettore; le tre
regole esistenti aggiornate; un'identità dei nodi che sopravviva alla riscrittura di
un piano (prerequisito della modifica incrementale).

**Dipende da.** Nulla. Può procedere in parallelo a V1/V2.

**Completo quando.** Lo stesso piano con radice `car`, `jeep`, `jeep1`, `auto_01`
produce sei ruote in tutti e quattro i casi; un umanoide con
`character:arm_count = 4` costruisce quattro braccia.

### V4 — Componenti mesh-backed dichiarati in dati

**Obiettivo.** Un artista aggiunge componenti alla libreria senza scrivere codice,
e il resolver non nota la differenza.

**Riusa.** `Component`, `Piece`, `Socket`, `ParamSpec`, `Attachment`: il contratto è
già agnostico. Nessuna astrazione nuova.

**Cosa cambia.** Un formato dati per dichiarare un componente (GLB + JSON con
capability, socket, parametri, materiali, figli) e un loader nel registry accanto a
quello dei moduli Python; una politica esplicita per i parametri «rebuild» contro
«deform»; una politica di validazione per le mesh importate; nessuna inferenza
automatica, che resta una feature separata.

**Dipende da.** V2 (una libreria che cresce senza degradazione semantica non serve a
niente) e V1 (una libreria che cresce senza retrieval non entra nel prompt).

**Completo quando.** Un GLB diventa un componente usabile in un piano, montabile per
capability su un componente procedurale esistente, senza una riga di Python
dell'artista e senza modifiche al core.

### V5 — Il vocabolario della variabilità, e la convenzione come contratto

**Obiettivo.** Component + parameters + effects coprono una grande famiglia di
varianti, e le chimere fra plugin escono orientate giuste.

**Riusa.** `TraitSpec` / `TraitRule` / `ParamPatch` — il meccanismo semantico che già
funziona; `app/core/authoring.py` (`growth_axis`, `verify_frame`), oggi helper
facoltativi.

**Cosa cambia.** Trait di proporzione relativa (`head_scale`, `limb_length`,
`hand_scale`); gli effetti mancanti della visione (`twist`, `taper`, `squash`,
`elongate`) in `app/plugins/effects/`; la convenzione d'asse promossa da `metadata`
testuale a dichiarazione verificata dal resolver.

**Dipende da.** Nulla di architetturale; conviene dopo V3 per non scrivere due volte
le regole.

**Completo quando.** «Umanoide cartoon con testa enorme, gambe corte e mani grandi»
produce quelle tre proporzioni; il drago non è più in piedi sulla coda.

---

## 9. Risposta diretta alla domanda posta

> Il sistema attuale può evolvere naturalmente in questa direzione, o alcune
> astrazioni recenti stanno creando complessità non necessaria?

**Entrambe le cose, e in proporzioni favorevoli.**

Le astrazioni portanti — `Component` con `build → Piece`, capabilities,
`Attachment` ricorsivo con `detail_level`, `EffectSpec` a stadi, `LayoutRegion`,
`TraitSpec` — sono quelle giuste, e sono esattamente ciò che la visione descrive. Il
contratto backend-agnostico per i componenti mesh-backed **esiste già**, senza che
nessuno lo abbia progettato per quello: è la conseguenza di aver tenuto il core
ignorante. Il motore di retrieval che la visione chiede **esiste già**, scritto per
un altro corpus.

Le astrazioni recenti hanno creato complessità non necessaria in due punti precisi, e
in modi diversi:

* **structural traits**: direzione sbagliata. Un percorso letterale dove esisteva
  già un selettore. Da correggere, non da ampliare.
* **archetypes / profiles / bindings**: idea giusta, forma sbagliata. Un catalogo
  parallelo da mantenere a mano che non scala con la libreria, costruito attorno a
  un algoritmo di degradazione che invece è quello corretto e che oggi non è
  raggiungibile dal percorso normale. Da riusare, non da rimuovere — e da alimentare
  dai componenti invece che da un file scritto a mano.

Nessuno dei due richiede un refactoring generale. Il primo è un cambio di tipo di un
campo; il secondo è un cambio di sorgente dei dati e un punto di aggancio diverso.

Il principio regge come criterio: **la libreria contiene la conoscenza 3D** — e oggi
la contiene davvero, nei componenti, nelle capability, nei tag, nei ruoli e nei
materiali. Il difetto del sistema attuale non è dove sta la conoscenza, è che
**nessuno la interroga**: il percorso normale la cerca con un conteggio di parole, e
il percorso semantico la cerca in una tabella scritta a mano che la duplica.
