# 3DGen - Archetypes + Profiles

Specifica architetturale. **Design only**: questo documento non introduce
runtime, nuovi plugin, benchmark eseguibili o modifiche ai contratti Python.

Stato: proposta per una futura V1.

## Tesi

3DGen deve poter rappresentare un concetto che non possiede come
implementazione diretta, ma soltanto quando il concetto puo' essere ricondotto
a un body-plan e a un vocabolario realmente installati.

```text
requested concept
    -> semantic/archetype interpretation
    -> closest representable generative basis
    -> validated adaptations
    -> ordinary CompositionGraph
    -> existing resolver, traits, layout, effects and builder
```

Un Archetype guida la generazione; non crea geometria e non decide se una
variante sia biologicamente o fisicamente "corretta". Un Profile e' un bundle
riutilizzabile di preferenze. I Traits restano il canale per esprimere le
differenze. I Components restano proprietari della geometria.

La regola piu' importante e':

> semantic similarity is not implementation compatibility.

## ARCH-A. Why this layer belongs in 3DGen

La pipeline attuale risponde molto bene quando il prompt corrisponde a un
component/plugin installato. Questo lascia pero' un vuoto tra il vocabolario
concreto e le richieste naturali dell'utente:

```text
"crea una lince"
"crea un'aquila"
"crea un dune buggy"
"crea un bonsai"
```

Non serve una mesh dedicata per ogni sostantivo. Serve un livello che sappia:

1. descrivere una famiglia generativa utile;
2. collegare una richiesta a quella famiglia;
3. scegliere una base costruibile;
4. trasformare le differenze in normali Trait/StructuralTrait/Style e
   preferenze di componenti;
5. rendere visibili copertura, limiti e provenienza.

Questa responsabilita' appartiene a 3DGen perche' attraversa registry,
planner, resolver, CompositionGraph, save/load e provenance. Non appartiene a
un singolo plugin e non deve essere incorporata in una tassonomia biologica.

L'obiettivo non e' riconoscere il mondo. E' aumentare la superficie dei
concetti rappresentabili con il vocabolario gia' disponibile.

## ARCH-B. Terminology

| Concetto | Responsabilita' | Non e' |
|---|---|---|
| **Plugin** | Unita' di distribuzione/installazione. Consegna manifest e moduli. | Una categoria semantica o una classe base. |
| **Component** | Implementazione costruibile con geometria, parametri, ruolo, capability, mount e socket. | Un sinonimo di Archetype. |
| **Archetype** | Famiglia semantica/body-plan con aspettative e compatibilita'. | Un package, una mesh o una tassonomia completa. |
| **Profile** | Bundle nominato di preferenze per uno o piu' Archetype. | Un nuovo linguaggio di mesh manipulation o uno Style. |
| **Trait** | Intenzione semantica applicabile e propagabile, materializzata con il contratto dei Traits. | Un parametro locale o una modifica arbitraria alla mesh. |
| **Structural Trait** | Intenzione che puo' cambiare cardinalita' o struttura tramite i rewrite gia' previsti. | Coordinate o logica privata dell'Archetype. |
| **Style** | Espressione visiva, per esempio `low_poly` o `toy`. | Identita' semantica o anatomia del soggetto. |
| **Capability** | Capacita' dichiarata da un Component, usata per validare implementazioni e innesti. | Prova che un componente sia semanticamente identico al concetto richiesto. |

La distinzione Plugin/Archetype e' obbligatoria:

```text
plugin biology_core = distribuzione
animal, quadruped, felid, bird, raptor = concetti semantici forniti
```

Un plugin puo' quindi fornire soltanto metadata, senza una sola mesh.

## ARCH-C. Archetype data model

La V1 proposta e' data-only e volutamente piccola. In forma concettuale:

```text
ArchetypeSpec
    id: namespaced stable id
    aliases: tuple[str, ...]
    description: short semantic description
    parents: tuple[ArchetypeId, ...]
    tags: tuple[str, ...]

    required_roles: tuple[str, ...]
    preferred_roles: tuple[str, ...]
    required_capabilities: tuple[str, ...]
    preferred_capabilities: tuple[str, ...]

    default_traits: tuple[TraitRequestData, ...]
    structural_expectations: tuple[StructuralExpectationData, ...]
    component_preferences: tuple[ComponentPreferenceData, ...]
    layout_preferences: tuple[LayoutPreferenceData, ...]

    owner: plugin id
    version: string
```

`ArchetypeSpec` non elenca automaticamente i Components che lo
implementano. La relazione semantica e la relazione con una concreta
implementation sono due contratti distinti; la seconda e' descritta da un
`ImplementationBinding` registrato separatamente. Questo evita che un tag o
il nome di un plugin diventi una falsa prova di identita'.

Non tutti i campi devono essere compilati. In particolare:

- `required_*` descrive il minimo che una candidate implementation deve
  saper rappresentare;
- `preferred_*` migliora il ranking ma non invalida un candidato;
- `default_traits` e' un insieme di richieste normali, non una copia della
  logica del Trait resolver;
- `structural_expectations` contiene richieste/default strutturali con la
  stessa validazione dei Structural Traits;
- `component_preferences` nomina ruoli, capability o famiglie, non mesh e non
  id obbligatori di un plugin specifico;
- `layout_preferences` puo' indicare una policy o una relazione semantica,
  ma non coordinate, offset o algoritmi di placement;
- `tags` e `aliases` servono per retrieval e matching, non sono prove di
  compatibilita' da sole.

### Forma delle aspettative

Le aspettative che descrivono cio' che e' tipico devono avere una natura
esplicita. Per esempio:

```text
structural_expectations:
  - trait: std:instance_count
    target: { role: limb }
    value: 4
    mode: best_effort
    kind: typical
```

Una aspettativa `typical` puo' essere materializzata come default e poi
sovrascritta. Non deve trasformarsi automaticamente in un vincolo hard.

Una capability o un ruolo `required`, invece, serve a dire che il candidato
non e' rappresentabile senza quella superficie minima. Non dice che tutte le
varianti del soggetto devono avere esattamente quella forma.

### Requisiti e alternative

Per evitare una grammatica nuova nella V1, la semantica segue il modello gia'
usato da `TraitMatch`:

- categorie diverse sono requisiti cumulativi;
- valori alternativi dentro una categoria sono alternative;
- i tags richiesti sono un sottoinsieme;
- la cardinalita' tipica appartiene a un default strutturale, non a una
  lista di quattro ruoli duplicati obbligatori.

Questo permette a `quadruped` di preferire quattro arti senza impedire a un
utente di chiedere esplicitamente sei arti.

## ARCH-D. Profile data model

Un Profile e' una configurazione nominata e riusabile. Non deve creare
Component e non deve contenere operazioni di mesh.

```text
ProfileSpec
    id: namespaced stable id
    aliases: tuple[str, ...]
    description: short semantic description
    archetypes: tuple[ArchetypeId, ...]
    includes: tuple[ProfileId, ...]

    default_traits: tuple[TraitRequestData, ...]
    structural_defaults: tuple[StructuralTraitRequestData, ...]
    param_role_preferences: tuple[ParamRolePreferenceData, ...]
    component_preferences: tuple[ComponentPreferenceData, ...]
    style_preferences: tuple[StylePreferenceData, ...]

    owner: plugin id
    version: string
```

`archetypes` indica a quali famiglie il profilo e' applicabile. Puo' contenere
piu' Archetype per un profilo ibrido, ma un profilo non introduce una seconda
gerarchia di classi.

`includes` e' una composizione di bundle, non ereditarieta' OOP. E' opzionale,
deve essere aciclica e viene risolta con la stessa diagnostica dei conflitti.
Serve, per esempio, a comporre `cat_like` con `winter_variant` senza copiare
il primo profilo.

Esempio concettuale:

```text
ProfileSpec(id="animal:domestic_cat", archetypes=("animal:felid",))
    default_traits:
      body_mass = 0.45
      tail_length = 0.70
      leg_length = 0.55
    component_preferences:
      head role=felid_head, tail role=tail, paw role=paw
```

Il profilo non contiene `low_poly`, `realistic` o una ricetta di rendering.
Una preferenza di Style puo' esistere soltanto come soft tie-breaker o
compatibilita' dichiarata; non cambia l'identita' semantica del soggetto.

## ARCH-E. Multiple parents/composition

Gli Archetypes sono dati semantici e possono avere piu' parents:

```text
bat
    parents: mammal, winged_creature

griffin
    parents: raptor, quadruped
```

Questo e' preferibile a una catena `LivingThing -> Mammal -> ...` perche'
descrive assi indipendenti. `winged`, `aquatic`, `bipedal` e `armored` possono
essere Archetypes leggeri, o tags/capabilities se non aggiungono aspettative
di generazione. Non e' necessario introdurre `AspectSpec` nella V1.

### Merge deterministico

Il grafo degli Archetypes deve essere un DAG. Il Registry deve rifiutare o
isolare una dichiarazione con ciclo, parent mancante o id ambiguo.

La merge policy proposta e':

1. deduplicare dichiarazioni identiche;
2. raccogliere gli ancestors in ordine deterministico, indipendente
   dall'ordine di import dei moduli;
3. trattare i defaults ereditati allo stesso livello come concorrenti;
4. se due valori concorrenti differiscono, produrre un conflitto esplicito;
5. consentire al nodo figlio di redeclarare esplicitamente un default, con
   provenance visibile;
6. non usare mai un `last import wins` nascosto;
7. usare l'id stabile come ultimo tie-breaker soltanto per l'ordine di
   presentazione, mai per scegliere un valore semanticamente conflittuale.

Un conflitto irrisolto puo' lasciare il concept risolvibile solo in modalita'
diagnostica, ma non deve produrre silenziosamente una forma scelta a caso.

### Composizione senza tassonomia

Una richiesta come `winged wolf` puo' risolversi come:

```text
canid/quadruped + winged_creature
```

Non occorre creare `winged_wolf` se la combinazione non aggiunge una regola
generativa riusabile.

## ARCH-F. Typical vs required

Questa distinzione deve attraversare tutto il modello.

| Tipo | Effetto | Esempio |
|---|---|---|
| Required | Scarta un candidato che non puo' rappresentare il minimo richiesto. | Un body-plan senza torso per un Archetype che lo richiede. |
| Preferred | Aumenta il punteggio spiegabile. | Una capability `paw_mount` per un felid. |
| Typical/default | Genera una richiesta iniziale sovrascrivibile. | Quattro arti, due ali, coda corta. |
| Explicit user intent | Viene applicato dopo i defaults e li sovrascrive. | Sei arti o quattro ali. |

Un Archetype guida cio' che e' tipico; non fa il poliziotto della realta'.
Pertanto `felid` non deve dichiarare `leg_count = 4` come invalidazione globale.
Un `StructuralTraitRequest` esplicito `leg_count = 6` deve poter vincere, se
esiste un implementation vocabulary compatibile.

I requisiti hard servono alla compatibilita' e alla sicurezza della pipeline,
non alla normalita' biologica.

## ARCH-G. Archetype resolution

La Concept Resolution e' un pass concettuale che produce un oggetto
validabile, non una nuova fase di geometria.

```text
1. canonicalize requested concept;
2. check direct local concept resolution when possible;
3. check exact registered profile and aliases;
4. check exact registered archetype and aliases;
5. when necessary, let the Composition Planner map the concept using the
   compact global Archetype index;
6. validate the proposed Archetype/Profile ids and adaptation vocabulary;
7. discover concrete candidates through registered ImplementationBindings;
8. filter hard requirements;
9. preflight adaptation coverage for every remaining candidate, without
   changing parameters or building geometry;
10. rank deterministically and select the concrete root in the backend;
11. expand and merge Profiles;
12. materialize ordinary requests for Composition Planner/Graph;
13. attach provenance and coverage.
```

Il pass di coverage precedente alla scelta del root e' una verifica di
contratto. Per ogni candidato il backend guarda, senza costruire nulla:

```text
Trait id registered?
matching TraitRule for candidate role/capabilities?
StructuralTrait rule and target available?
public param-role/component preference available?
required role/capability covered by binding?
```

Il risultato e' una matrice `supported / unsupported / conflicting` per
candidato. Solo dopo questa matrice il backend sceglie il root. La
materializzazione successiva applica le richieste gia' validate e non puo'
retroattivamente cambiare il candidato. Cosi' implementation selection e
adaptation coverage non formano una dipendenza circolare.

La fallback ladder e':

```text
exact implementation
    -> exact profile
    -> exact archetype
    -> ancestor/composed archetype
    -> compatible sibling implementation
    -> generic body-plan implementation
    -> cannot represent
```

Un fallback semantico e un fallback implementativo sono campi distinti:

```text
semantic concept: felid
implementation proxy: fox_stylized:body
```

Il secondo non autorizza il sistema a dire che `fox` e' sinonimo di `felid`.
Dice soltanto che quel Component espone una superficie compatibile per la
costruzione richiesta.

### Oggetto concettuale

La V1 dovrebbe fissare un `ConceptResolutionPlan` serializzabile:

```text
ConceptResolutionPlan
    requested_concept
    direct_implementation
    archetypes
    profiles
    selected_root_implementation
    component_preferences
    adaptations
    coverage
    unsupported
    diagnostics
    provenance
```

Il nome dell'implementazione selezionata non deve essere assunto valido solo
perche' lo ha proposto l'LLM: nella V1 la selezione concreta appartiene al
backend e passa dal Registry e dal resolver.

## ARCH-H. Candidate implementation ranking

Il ranking e' deterministico e data-driven, non un modello ML. Prima si
eliminano i candidati che falliscono requisiti hard. Poi si ordinano con una
chiave spiegabile, per esempio:

```text
1. a registered binding exists for the concrete root
2. all hard roles/capabilities satisfied
3. exact Archetype binding before ancestor/body-plan proxy
4. required adaptation coverage
5. preferred roles/capabilities satisfied
6. Trait coverage
7. Structural Trait coverage
8. component family completeness
9. Profile compatibility
10. Style compatibility, only as a tie-breaker
11. stable binding/component id
```

Il primo criterio non e' il nome del plugin, il suo namespace o un tag. Un
binding esplicito e la compatibilita' verificabile sono necessari. In
particolare:

```text
plugin name contains "cat" -> not evidence of felid
tag "fox"                -> not evidence of felid
```

Tags e descrizioni possono contribuire al retrieval e a un soft score, ma non
possono promuovere un candidato oltre un binding mancante o un requisito hard
fallito.

Il risultato deve includere i contributi al ranking:

```text
generic_quadruped:body
  hard requirements: pass
  role coverage: 5/5
  preferred capabilities: 4/6
  trait coverage: 6/8
  structural coverage: 2/2
  unsupported: ear_tuft, fur_thickness
  reason: highest validated coverage among compatible roots
```

Il backend conserva anche la natura del match:

```text
binding: generic_quadruped:body -> animal:quadruped
semantic request: animal:felid
match: ancestor/body-plan proxy
```

Questo significa che il Component e' compatibile con il body-plan, non che
la sua identita' semantica diventi `felid`.

Non e' necessario esporre un numero percentuale nella API pubblica. Se un
numero viene mostrato, e' una metrica di coverage delle richieste, non un
beauty score del modello.

### Un root o una famiglia di componenti?

La V1 dovrebbe scegliere prima un root/body-plan implementation. Le preferenze
di famiglia restano nel piano e il Composition Planner/resolver puo' scegliere
componenti di altri plugin quando ruoli, mounts e capabilities lo consentono.

Questo conserva la composizione cross-plugin senza trasformare Archetype
Resolution in un secondo planner completo. Una futura V2 puo' fare ranking di
famiglie complete, se i benchmark dimostrano che il root non basta.

## ARCH-I. Coverage model

La coverage risponde a "quanto del concept posso esprimere con contratti
installati?", non a "quanto e' bello il risultato?".

Ogni richiesta adattiva viene classificata per canale:

```text
role               supported | unsupported | conflicting
capability         supported | unsupported | conflicting
semantic_trait     supported | unsupported | conflicting
structural_trait   supported | unsupported | conflicting
component_family   supported | unavailable | conflicting
style              compatible | unavailable | conflicting
```

Una voce supportata deve indicare il contratto che la supporta:

```text
paw_size -> TraitSpec std:paw_size -> rule fox_stylized:body
wing_count -> StructuralTraitSpec std:instance_count -> rule bird:wing
```

Le voci non supportate restano nel piano e nel report. Non vengono convertite
in parametri inventati e non vengono eliminate per rendere il piano piu'
ottimistico.

## ARCH-J. Unknown concept handling

Il comportamento dipende dalla conoscenza disponibile:

```text
concept registered locally       -> deterministic resolution
concept unknown, described        -> LLM may map to known vocabulary
concept unknown, undescribed      -> unknown concept / request clarification
concept mapped but unsupported    -> honest incomplete resolution
```

Per `florbax` senza descrizione, 3DGen non deve inventare un animale. Per
`florbax, un felino con sei orecchie e due code`, l'LLM puo' proporre
`felid + ear_count=6 + tail_count=2`, ma il backend applica soltanto Traits,
Structural Traits e component capabilities registrati.

Ogni mapping sconosciuto e' un'ipotesi con authority inferiore ai metadata
installati. Non diventa conoscenza permanente del core.

## ARCH-K. LLM semantic mapping

L'LLM e' un semantic mapper, non un modellatore e non un'autorita' sulla
geometria disponibile.

Input minimo:

```text
requested concept and prompt
compact archetype/profile shortlist
registered Traits and Structural Traits
component roles/capabilities
compatible Styles
```

Output possibile:

```json
{
  "requested_concept": "lynx",
  "archetypes": ["animal:felid"],
  "profiles": ["animal:cat_like"],
  "adaptations": [
    {"trait": "std:tail_length", "value": 0.45},
    {"trait": "std:paw_size", "value": 1.15},
    {"trait": "std:leg_length", "value": 1.10}
  ],
  "unsupported_candidates": ["ear_tuft"]
}
```

L'output normale del planner contiene semantic intent, non una scelta concreta
di mesh:

```text
LLM owns:
  requested concept interpretation
  Archetype proposal
  Profile proposal
  semantic adaptation intent

Backend owns:
  ImplementationBinding discovery
  hard compatibility validation
  preflight adaptation coverage
  deterministic ranking
  final root Component selection
```

Un campo opzionale `implementation_hint` puo' essere conservato come
informazione diagnostica, ma e' soltanto un soft candidate hint. Non puo'
selezionare `fox_stylized:fox`, non salta il binding e non cambia il ranking.

Il backend deve rifiutare o riparare ogni id non registrato. `ear_super_lynx_factor`
non e' un adaptation valido se non esiste un Trait o un parametro semanticamente
compatibile nel vocabolario.

Authority order:

```text
installed explicit metadata
    > registered aliases and profiles
    > validated deterministic compatibility
    > LLM semantic approximation
```

L'LLM puo' dire che una lince ha zampe grandi; il backend decide se `paw_size`
e' un contratto installato e applicabile al candidato scelto.

## ARCH-L. Single planner vs separate concept planner

### Opzione A: un Composition Planner che fa tutto

Il planner riceve prompt, shortlist di Archetypes/Profiles e vocabolario dei
contratti e produce un piano completo.

Vantaggi:

- una sola chiamata LLM;
- meno serializzazione tra fasi;
- il planner vede insieme semantica e composizione;
- si preserva il budget gia' ottimizzato del payload.

Rischi:

- responsabilita' piu' dense in uno schema;
- diagnostica concettuale meno isolata;
- maggiore rischio che il planner confonda candidato semantico e Component.

### Opzione B: Concept Planner separato

Una prima fase produce `ConceptResolutionPlan`; una seconda produce il normale
CompositionPlan.

Vantaggi:

- confini e provenance molto chiari;
- repair concettuale indipendente;
- piu' facile cache/save/load del mapping.

Rischi:

- seconda chiamata LLM o payload duplicato;
- errori composti tra due piani;
- latenza e costo maggiori;
- il primo planner puo' scegliere una semantica che il secondo non sa
  costruire.

### Raccomandazione V1

Separare **logicamente** il concetto come `ConceptResolutionPlan`, ma non
introdurre un secondo planner LLM. Il Composition Planner riceve una shortlist
compatta e puo' emettere nello stesso JSON sia la risoluzione concettuale sia
le normali richieste di composizione.

Il backend esegue poi due pass deterministici:

```text
validate concept resolution
materialize profile defaults
validate ordinary CompositionPlan
```

Si conserva una sola chiamata normale e al massimo la stessa repair call gia'
prevista per un piano non valido. Un Concept Planner separato resta una
possibile V2 se i benchmark mostrano che la responsabilita' unificata riduce
affidabilita' o debuggabilita'.

## ARCH-M. Planner vocabulary

Il planner non deve ricevere l'ontologia intera. La V1 separa due livelli:

```text
COMPACT GLOBAL CONCEPT INDEX -> tiny, all registered Archetypes
DETAILED LOCAL SHORTLIST     -> bounded, only relevant requirements/profiles
CONTRACT VOCABULARY           -> existing compact Traits/StructuralTraits/Styles
```

Il compact index e' l'unico indice globale inviato al planner. Contiene per
ogni Archetype soltanto:

```text
canonical id
essential aliases
one very short semantic description
```

Non serve overlap lessicale tra `lynx` e `felid` perche' `animal:felid` possa
entrare nel prompt: l'LLM vede il piccolo catalogo dei concetti installati e
puo' proporre il mapping semantico.

La detailed shortlist viene costruita dal backend dopo la proposta, o da un
retrieval locale quando esiste un match, e contiene soltanto gli elementi
necessari a validare la scelta:

```text
canonical Archetype id reference
required/preferred roles and capabilities
relevant Profiles
relevant ImplementationBindings
relevant Trait/StructuralTrait/Style contract ids
```

Le descrizioni non vengono duplicate: la shortlist referenzia il testo
canonico del global index e aggiunge solo i requisiti operativi.

Per ogni elemento vengono inviati soltanto:

```text
ARCHETYPE
  id
  aliases
  short description

DETAILED ARCHETYPE REFERENCE
  id reference
  bounded direct parents
  key required/preferred capabilities

PROFILE
  id
  archetypes
  aliases
  short semantic description

CONTRACTS
  registered Trait ids and short descriptions
  registered Structural Trait ids and short descriptions
  component roles/capabilities
  compatible Style ids
```

Non vengono espansi tutti gli ancestors, tutte le regole dei Traits o ogni
parametro locale. Il Registry resta authority; il payload e' una vista
data-only per il planner. I Traits e gli Structural Traits restano il
vocabolario compatto gia' esistente e non vengono duplicati dentro ogni
Archetype/Profile.

### Retrieval V1

Il retrieval locale puo' usare:

1. normalizzazione e tokenizzazione dei prompt;
2. match su id e aliases;
3. match su tags e parole della description;
4. preferenza per exact match e namespace rilevanti;
5. limite deterministico al numero di risultati;
6. stable sort per id.

Embeddings, web search e retrieval semantico vettoriale sono fuori dalla V1.
Non sono necessari per dimostrare il contratto e introdurrebbero nuove fonti
di non-determinismo.

### Registry troppo grande

Quando il compact index non entra piu' nel budget, la strategia futura deve
conservare lo stesso contratto a strati:

1. generare shards o summary groups deterministici per dominio/tag/namespace;
2. inviare prima solo gli identificatori e i summary dei gruppi;
3. espandere nel prompt soltanto i gruppi selezionati;
4. usare un retrieval locale offline, eventualmente con un indice semantico
   opzionale in una fase successiva;
5. mantenere il backend authority e un limite esplicito al numero di
   candidate.

Non introdurre nella V1 un secondo LLM per navigare l'indice. Se in futuro si
usera' embeddings, il risultato dovra' essere una shortlist riproducibile e
validata dal Registry, non una nuova fonte di verita'.

## ARCH-N. Profile materialization

Il Profile si materializza subito dopo la resolution, prima del Composition
Graph finale:

```text
ConceptResolution
    -> merge Archetype defaults
    -> merge Profile bundles
    -> validate adaptation requests
    -> ordinary TraitRequest/StructuralTraitRequest/style/component hints
    -> CompositionPlan
    -> existing resolver and builder
```

Dopo questo punto il resto della pipeline non deve conoscere la semantica
speciale dei Profiles. Deve vedere normali richieste con provenance.

Un Profile puo' produrre:

- `TraitRequest` per body mass, proportions o altre intenzioni semantiche;
- `StructuralTraitRequest` per count/default strutturali;
- preferenze di role/capability/component per la selezione;
- preferenze Style soltanto come canale dichiarato e soft;
- param-role preferences, mai patch arbitrarie verso nomi non pubblici.

Se esiste un Trait adatto, il Profile deve usare quello invece di duplicarne la
logica in un parametro speciale. Se non esiste un Trait, la V1 puo' esprimere
una preferenza di ruolo/parametro soltanto se il parametro e' gia' parte del
contratto pubblico di un Component candidato. Altrimenti la richiesta e'
unsupported.

## ARCH-O. Precedence

La precedenza globale proposta e':

```text
Component defaults
    < Archetype defaults
    < Profile defaults
    < LLM concept adaptations
    < explicit user Traits
    < explicit user Structural Traits
    < explicit user params/effects/style
```

Il simbolo `<` significa "ha meno autorita' di".

Questa regola va applicata per canale, non con un unico dizionario last-wins.
Un valore esplicito dell'utente vince sempre un default inferito. Un
adattamento LLM non e' equivalente a un'intenzione esplicita dell'utente.

Se l'utente chiede `lynx` e poi `tail_length = 0.9`, il secondo valore vince
il default `short tail` del mapping. La provenienza deve conservarsi:
`user` sostituisce `llm_adaptation`, che sostituiva `profile`.

## ARCH-P. Conflict semantics

I conflitti sono per canale:

```text
semantic trait default
structural trait default
component preference
style preference
archetype requirement
profile applicability
```

Regole:

1. dichiarazioni identiche vengono deduplicate;
2. defaults concorrenti diversi producono un diagnostic;
3. nessun import order o file order decide in silenzio;
4. una dichiarazione piu' specifica ed esplicita puo' override ereditato;
5. un valore esplicito dell'utente risolve il conflitto a suo favore;
6. se due richieste esplicite dell'utente sono incompatibili, il conflitto
   resta visibile e non viene risolto arbitrariamente;
7. ogni output conserva source, authority, channel e decision.

Esempio:

```text
Profile A: tail_length = short
Profile B: tail_length = long

result: PROFILE_CONFLICT(tail_length)
resolution: requires explicit user value or a named higher-precedence layer
```

Un `includes` di Profile non e' un modo per nascondere conflitti. Una terza
parte puo' comporre un profilo esistente, ma non modificarlo in-place.

## ARCH-Q. Provenance

La provenance deve essere leggibile senza ricostruire la storia del planner:

```text
requested concept: lynx
direct implementation: none
selected archetypes: animal:animal, animal:quadruped, animal:felid
selected profiles: animal:cat_like
selected root: generic_quadruped:body

adaptations:
  tail_length: down, source=llm, validated_by=std:tail_length
  paw_size: up, source=llm, validated_by=std:paw_size
  leg_length: up, source=llm, validated_by=std:leg_length

unsupported:
  ear_tuft, reason=no registered Trait/component vocabulary

reason:
  highest validated implementation coverage
```

Campi minimi raccomandati:

```text
requested
authority path
candidate list and ranking reasons
selected archetypes/profiles
selected implementation(s)
materialized requests
supported/unsupported/conflicting adaptations
registry/plugin versions
```

La provenance non deve chiamare "felid" un Component fox-like solo perche'
quel Component e' stato scelto come proxy.

## ARCH-R. Save/load

Un progetto o risultato che ha usato fallback semantico deve salvare la
decisione validata:

```json
{
  "concept_resolution": {
    "version": "1.0",
    "requested": "lynx",
    "archetypes": ["animal:felid"],
    "profiles": ["animal:cat_like"],
    "implementation": "generic_quadruped:body",
    "adaptations": [],
    "coverage": {},
    "unsupported": [],
    "provenance": {}
  }
}
```

Il contenuto reale sara' definito dall'implementazione futura, ma il contratto
deve includere almeno richiesta, risoluzione, implementazione, adaptation plan
validato e provenance.

In reload:

```text
load saved ConceptResolutionPlan
validate ids and versions
reuse the saved plan
do not call the LLM again
```

Se un plugin non e' piu' installato o una capability e' cambiata, il loader
deve produrre una diagnosi riproducibile. Non deve fare un nuovo mapping
silenzioso verso un soggetto diverso.

## ARCH-S. Relation with Semantic Traits

I Profiles sono bundle di TraitRequest, non un nuovo Trait resolver.

```text
Profile: lynx_like
    -> std:tail_length = 0.45
    -> std:paw_size = 1.15
    -> std:leg_length = 1.10
    -> existing TraitResolver
```

Le regole che traducono un Trait in param patches o effects restano registrate
da plugin/extension e restano responsabili della compatibilita' locale.

Un Profile non puo' accedere a campi privati, vertici, funzioni `build` o
nomi di parametri non dichiarati. Se una preferenza non ha un Trait globale,
puo' diventare un hint di componente; non puo' creare una scorciatoia privata.

## ARCH-T. Relation with Structural Traits

Gli Archetypes possono dichiarare il tipico, per esempio due ali o quattro
arti, come StructuralTraitRequest di default. La logica resta quella esistente:

```text
Archetype/Profile default
    -> StructuralTraitRequest
    -> GraphRewritePlan
    -> expanded CompositionGraph
    -> LayoutEngine
```

Archetype Resolver non implementa `ensure_count`, non clona nodi e non decide
il layout. Un Structural Trait esplicito dell'utente, per esempio quattro ali,
vince il default tipico di due ali, se il rewrite rule e' disponibile.

Questo mantiene la distinzione tra:

```text
semantic expectation = what is typical
structural rewrite    = how the graph changes
layout policy         = where instances are placed
```

## ARCH-U. Relation with Layout

Un Archetype puo' preferire una policy registrata, per esempio bilateral per
una coppia di ali, ma non puo' esprimere coordinate, offset o compensazioni
visuali.

```text
raptor profile -> preferred layout policy: bilateral
LayoutEngine   -> validates region and places wing instances
```

La policy viene scelta solo se la regione del Component la consente. Se non
esiste, il report deve dire `layout preference unavailable`; il resolver non
deve inventare placement.

## ARCH-V. Relation with Effects/Styles

### Effects

Un'adattamento come "gambe piu' lunghe" deve preferire un Trait che produca
patch/effects tramite regole registrate. Un Profile non deve chiamare
direttamente un effect builder e non deve ordinare effetti arbitrari.

### Styles

```text
profile = lynx_like
style = low_poly
```

descrive la stessa identita' con due assi distinti:

```text
Profile -> cosa e' tipicamente il soggetto
Style   -> come viene espresso visivamente
```

Lo Style puo' essere un tie-breaker tra implementation equivalenti, ma non
puo' trasformare un vehicle in un animal o cambiare il significato del
Profile. Un Profile non deve contenere alternative come `realistic` o
`cartoon` quando queste appartengono allo Style system.

## ARCH-W. Third-party extension model

Il manifest esistente puo' essere esteso additivamente:

```json
{
  "id": "biology_core",
  "version": "1.0.0",
  "components": [],
  "effects": [],
  "styles": [],
  "traits": [],
  "archetypes": ["archetypes/animals.py"],
  "profiles": []
}
```

Un normale plugin puo' quindi contenere:

```text
only archetypes
only profiles
components + profiles
traits + archetypes
all of the above
```

Il modulo dichiara `ArchetypeSpec` e `ProfileSpec` data-only. Il Registry li
qualifica con il namespace del plugin, li valida e li espone nel vocabulary.
Nessuna modifica al core deve essere necessaria per installare:

```text
fantasy_creatures:griffin
fantasy_creatures:wyvern
fantasy_creatures:ice_griffin
```

Un Profile terzo puo' puntare a un Archetype di un altro plugin:

```text
fantasy:dire_wolf
    archetypes: [animal:canid, animal:quadruped]
    includes: [animal:wolf_like]
    default_traits: ...
```

Questo non copia il plugin originale e non modifica il Profile originale.

Il loader deve isolare errori di un plugin e segnalare almeno:

- id non namespaced o duplicato;
- parent/archetype/profile mancante;
- ciclo nel grafo;
- campo sconosciuto o tipo invalido;
- Trait/StructuralTrait/Style non registrato;
- conflitto non risolvibile.

L'ordine di import non puo' essere un meccanismo di precedenza.

## ARCH-X. Lynx no-plugin end-to-end

Scenario:

```text
prompt: "crea una lince low-poly"
direct lynx implementation: none
installed metadata: animal, quadruped, felid, cat_like
installed implementations: generic quadruped body, head, ears, tail, paws
```

Flusso:

```text
prompt
  -> requested concept = lynx, style = low_poly
  -> no direct implementation
  -> registered felid/animal/quadruped shortlist
  -> selected archetype = animal:felid
  -> selected profile = animal:cat_like
  -> selected root = generic_quadruped:body
  -> materialized adaptations
  -> existing Traits/StructuralTraits
  -> CompositionGraph
  -> existing resolver/layout/effects/builder
```

Adattamenti possibili, solo se supportati:

```text
tail_length down
paw_size up
leg_length up
head_width up
ear_size up
```

`ear_tuft` e `fur_thickness` vengono riportati come unsupported se non esiste
un Trait, una capability o un Component compatibile. Il risultato puo' essere
un approximation valida, ma non deve presentarsi come una lince esatta.

## ARCH-Y. Lynx with no lynx metadata at all

Scenario piu' severo:

```text
no lynx plugin
no lynx profile
no lynx archetype
```

Se il prompt contiene soltanto `lynx`, l'LLM puo' usare conoscenza generale per
proporre:

```text
base semantic family: felid
base profile: cat_like, if registered
adaptations: short tail, large paws, longer legs, broad head, large ears
```

Il backend accetta soltanto la parte validabile contro il registry. Se anche
`felid` e `cat_like` non sono registrati ma esiste un body-plan quadrupede,
puo' restare un mapping verso `generic_quadruped` con coverage inferiore. Se
non esiste nessun contratto sufficiente, lo stato e' `cannot represent`.

Authority e provenance devono distinguere chiaramente:

```text
inferred by LLM: lynx approximately felid
validated locally: generic quadruped supports selected traits
unsupported: ear tuft
```

Nessuna mesh `lynx.py` viene introdotta per chiudere il benchmark.

## ARCH-Z. Eagle no-plugin end-to-end

Un'aquila verifica che il modello non sia specializzato sui quadrupedi:

```text
requested: eagle
candidate semantics: bird + raptor + winged
possible roles: torso, head, beak, wing, talon
```

Il resolver puo' selezionare un root bird/raptor, oppure una body-plan
implementation compatibile con le capability disponibili, e poi lasciare al
Composition Planner la sostituzione di testa, ali, becco o artigli tra
plugin.

Il default tipico `wing_count = 2` deve diventare una richiesta strutturale
normale, non una regola privata dell'Archetype. Se il repository non dispone di
Component bird/wing/beak/talon e di regole sufficienti, il benchmark deve
fallire onestamente con coverage e unsupported dettagliati. L'architettura non
deve inventare una geometria d'uccello per soddisfare il nome.

## ARCH-AA. Dune buggy no-plugin end-to-end

Caso non biologico:

```text
requested: dune buggy
direct implementation: none
semantic basis: vehicle + wheeled_vehicle + car_like
```

La selezione puo' partire da un Component vehicle/car-like e applicare, solo
se il vocabolario lo permette:

```text
wheel_size up
ground_clearance up
body_length down
open_cabin component preference
```

Le ruote devono restare una responsabilita' del component/structural/layout
contract; l'Archetype non decide coordinate e non patcha la mesh. Un profilo
`buggy_like` e' utile se riusabile, ma non e' obbligatorio per risolvere il
concept quando il mapping LLM e' validabile.

Questo caso dimostra che Archetypes non sono una tassonomia zoologica: lo
stesso meccanismo vale per un body-plan meccanico.

## ARCH-AB. Bonsai example

```text
requested: bonsai
base archetype: tree
profile: bonsai_like, if registered
```

Adattamenti candidati:

```text
height down
relative crown width up
relative trunk girth up
branch spread up or down
leafiness as existing Semantic Trait
```

Il Profile esprime queste differenze con TraitRequest, structural defaults e
component preferences. Non scrive una nuova variante di `tree_stylized` e non
imposta direttamente il numero di vertici o la posizione dei rami.

Se `height`, `trunk_girth` o `branch_spread` non sono contratti installati,
restano unsupported. Il sistema puo' comunque usare la parte rappresentabile
del profilo, con provenance e coverage.

## ARCH-AC. Fantasy hybrid example

Un autore puo' dichiarare:

```text
fantasy:griffin
    parents: [animal:raptor, animal:quadruped]
    preferred_roles: [beak, wing, talon]
    preferred_capabilities: [wing_mount, paw_mount]
```

La composizione puo' scegliere:

```text
quadruped body
raptor head/beak
wing components
talon components
```

Il Structural Trait `wing_count` o `std:instance_count` puo' chiedere il
numero di ali; LayoutEngine resta responsabile della loro disposizione.

Un `cat-eagle` puo' essere rappresentato come `felid + raptor/winged` senza
creare un Archetype enciclopedico per ogni ibrido. Se i due body-plan hanno
requisiti incompatibili, il resolver espone il conflitto invece di inventare
una gerarchia di ereditarieta'.

## ARCH-AD. Minimal runtime V1 recommendation

La minima V1 futura dovrebbe includere soltanto:

1. `ArchetypeSpec` e `ProfileSpec` data-only;
2. manifest opzionale `archetypes`/`profiles`;
3. registry index, aliases, DAG validation e cycle diagnostics;
4. exact/alias deterministic resolution;
5. profile includes aciclici con merge e conflict diagnostics;
6. `ConceptResolutionPlan` serializzabile;
7. profile materialization verso Trait/StructuralTrait requests, style e
   component hints gia' esistenti;
8. candidate ranking deterministico con coverage spiegabile;
9. compact planner vocabulary e lexical shortlist;
10. provenance e save/load senza nuova chiamata LLM;
11. un solo Composition Planner call, con al massimo la repair call gia'
    prevista.

Da lasciare fuori:

```text
embeddings
ML ranking
marketplace ontology
automatic web knowledge
arbitrary mesh adaptation
second LLM service obbligatorio
AspectSpec
taxonomy completa
```

La V1 e' riuscita se un plugin vecchio continua a funzionare senza metadata
nuovi e se un concetto nuovo viene accettato soltanto nella parte validata.

## ARCH-AE. Benchmark roadmap

### 1. Lynx without lynx plugin

Benchmark principale:

```text
recognized as felid-like
base implementation selected
short-tail adaptation
paw/leg/head/ear adaptations where supported
unsupported features reported honestly
valid low-poly build
saved resolution reloads without LLM
```

Non si crea `lynx.py`.

### 2. Dune buggy without buggy plugin

Verifica:

```text
vehicle/car-like fallback
larger wheels and higher clearance only when supported
cross-domain semantic mapping
no biological assumptions in core
```

### 3. Eagle without eagle plugin

Verifica:

```text
bird/raptor body-plan
wing/beak/talon capability selection
structural wing defaults
honest incomplete result when bird vocabulary is absent
```

### 4. Bonsai without bonsai plugin

Verifica il riuso di Traits, structural defaults e component preferences su un
dominio vegetale.

### 5. Third-party extensions

Verifica che un plugin esterno aggiunga `fantasy:griffin` e `fantasy:dire_wolf`
senza modificare core o plugin originali, e che gli errori di metadata non
alterino l'ordine di risoluzione degli altri plugin.

## ARCH-AF. Risks

### Taxonomy explosion

Se ogni sostantivo diventa un Archetype, il sistema ricrea Wikipedia. Criterio:
creare un Archetype solo quando cambia generation, composition, selection,
trait adaptation, structural expectation o layout preference.

### Overconstraint

Confondere il tipico con il necessario impedisce sei braccia, quattro ali o
un gatto alato. I defaults sono overrideable; i required sono soltanto
compatibility minima.

### Bad semantic fallback

Un proxy implementativo non e' una verita' semantica. Il piano deve conservare
separati concept, archetype e selected implementation.

### LLM hallucinated adaptations

Ogni adaptation passa dal registry. Id, Trait, Structural Trait, capability e
Style non registrati vengono rifiutati o riportati come unsupported.

### Profile conflicts

Niente hidden last-wins. I conflitti per canale restano diagnosticabili e un
override esplicito deve essere necessario.

### Vocabulary payload growth

Usare retrieval locale e shortlist compatte. Il planner vede descrizioni e
capabilities essenziali, non una ontologia espansa di migliaia di elementi.

### Misleading nearest implementation

Il ranking deve esporre coverage e motivi. "Nearest" significa migliore base
validata, non identita' del concept.

### Biological taxonomy leaking into generic core

Il core conosce spec e graph, non che cosa sia una lince, un'aquila o un
buggy. Questa conoscenza arriva da metadata o dal mapping LLM validato.

### Duplicated Trait semantics

Un Profile deve produrre TraitRequest, non una seconda implementazione delle
regole di `body_mass`, `tail_length` o `leafiness`.

### Archetype graph cycles

Registry validation obbligatoria; un ciclo non puo' essere risolto tramite
ricorsione implicita o import order.

### Version drift on reload

Il plan salvato deve avere versioni e provenance. Se i contratti installati
non sono piu' compatibili, il reload diagnostica il problema invece di
chiamare automaticamente l'LLM.

## ARCH-HARDEN-A. Unknown concept discovery

La lexical shortlist locale da sola non risolve il caso in cui `lynx` non
condivida alcun token con gli Archetypes installati. La V1 usa quindi due
viste, con responsabilita' diverse:

```text
compact global concept index
    -> rende visibili tutti gli Archetypes candidabili al mapping semantico

detailed local shortlist
    -> rende validabili solo requirements, Profiles, bindings e contratti
       rilevanti
```

Il global index non deve contenere ogni dettaglio. Ogni entry e' soltanto:

```text
canonical Archetype id
essential aliases
very short semantic description
```

Il planner puo' quindi vedere `animal:felid` anche se il prompt contiene solo
`lynx` e non c'e' overlap lessicale. Dopo la proposta, il backend costruisce
la detailed shortlist e valida ogni riferimento contro il Registry.

La V1 non introduce embeddings, web search o un secondo LLM. La lexical
retrieval resta utile per i casi facili e per costruire la shortlist, ma non e'
piu' il solo ingresso al mapping sconosciuto.

## ARCH-HARDEN-B. Compact global index

Il payload concettuale ha tre livelli misurabili:

```text
GLOBAL INDEX:       N Archetypes x (id, aliases essenziali, descrizione breve)
DETAILED SHORTLIST: K Archetypes/Profiles/Bindings, con K bounded dal budget
CONTRACT VOCAB:     M id compatti di Traits, Structural Traits e Styles
```

`N` e' il numero totale degli Archetypes registrati; l'entry globale e' la
stessa descrizione canonica usata nel Registry e non viene ripetuta nella
shortlist. `K` e' una configurazione di budget, non un numero implicito scelto
dall'LLM. `M` riusa il formato compatto gia' adottato dal planner e contiene
solo contratti rilevanti.

La sequenza e':

```text
all Archetype ids in compact global index
    -> LLM semantic proposal
    -> backend resolves ids and parent graph
    -> detailed shortlist for validation
    -> backend discovers implementations
```

Quando il Registry cresce oltre il budget, la V1 futura puo' creare shard e
summary groups deterministici. Il planner vedra' prima i gruppi e il backend
espandera' soltanto quelli richiesti. In seguito si potranno valutare
embeddings locali o un indice semantico offline, ma la loro uscita dovra'
essere sempre una shortlist validata dal Registry. Non si deve trasformare il
compact index in una nuova ontologia duplicata o in una catena di chiamate LLM.

## ARCH-HARDEN-C. Implementation binding

La minima dichiarazione raccomandata e' un oggetto data-only separato dal
Component:

```text
ImplementationBinding
    id: stable namespaced binding id
    implementation: concrete root Component id
    supported_archetypes: tuple[ArchetypeId, ...]
    roles: tuple[str, ...]
    capabilities: tuple[str, ...]
    owner: plugin id
    version: string
```

Esempio:

```text
ImplementationBinding(
    id="fox_stylized:quadruped_root",
    implementation="fox_stylized:fox",
    supported_archetypes=("animal:quadruped",),
    roles=("torso", "head", "limb", "tail"),
    capabilities=("head_mount", "limb_mount", "tail_mount")
)
```

Questo binding dichiara che `fox_stylized:fox` puo' essere usato come
implementation di un body-plan quadrupede. Non dichiara `animal:felid` e non
trasforma il fox in una verita' semantica sulla lince.

Il binding puo' essere esportato da un normale modulo data-only elencato in un
campo manifest opzionale, per esempio `bindings`. Questo e' un'estensione
additiva del plugin manifest, non un nuovo tipo di package. Un autore terzo
puo' aggiungere un binding per un Component esistente senza modificare il core
o il plugin originale, purche' il Registry autorizzi e validi quel riferimento.

Per una richiesta `animal:felid`, il backend puo' usare il binding quadrupede
come proxy se il grafo degli Archetypes dimostra che quadrupede e' un
body-plan ancestor compatibile e la coverage supera i requisiti hard. Nel
result devono restare separati:

```text
semantic truth:            animal:felid
binding truth:             fox_stylized:quadruped_root
implementation proxy:     fox_stylized:fox
match kind:                ancestor/body-plan proxy
```

Tags, descrizioni e nomi dei plugin non sostituiscono il binding. Il binding
non deve contenere mesh, coordinate, codice di build o una copia della logica
dei Traits.

## ARCH-HARDEN-D. LLM/backend authority boundary

Il confine diventa esplicito:

```text
LLM:
  requested semantic interpretation
  Archetype proposal
  Profile proposal
  semantic adaptation intent

BACKEND:
  concrete candidate discovery through bindings
  hard requirement validation
  preflight adaptation coverage
  deterministic ranking
  final root Component selection
```

Il planner dovrebbe quindi produrre:

```text
felid
quadruped
cat_like
short tail
large ears
large paws
```

e non scegliere direttamente `fox_stylized:fox`. Un eventuale
`implementation_hint` puo' essere conservato come soft hint diagnostico, ma:

- deve riferirsi a un Component esistente;
- non bypassa `ImplementationBinding`;
- non cambia i requisiti hard;
- non vince il ranking per il solo fatto di essere stato proposto dall'LLM;
- non viene usato in reload al posto del piano validato.

La selezione concreta appartiene al backend anche quando il planner e' una
singola chiamata che emette sia semantic intent sia il CompositionPlan.

## ARCH-HARDEN-E. Candidate ranking

Il ranking aggiornato e' una sequenza di filtri e score spiegabili:

```text
1. binding registrato per il root Component
2. required roles/capabilities coperti
3. exact Archetype binding
4. ancestor/body-plan proxy binding
5. adaptation coverage preflight
6. preferred roles/capabilities
7. Trait coverage
8. Structural Trait coverage
9. component family completeness
10. Profile compatibility
11. Style compatibility as soft tie-breaker
12. stable binding id and Component id
```

Un candidato senza binding non diventa valido perche' il plugin si chiama
`cat`, perche' un tag dice `fox` o perche' il Component ha una descrizione
simile. Tags e nomi possono aiutare il retrieval e un soft score, ma non
possono sostituire una compatibilita' dichiarata e verificabile.

Prima del ranking il backend calcola, per ogni candidato rimasto:

```text
requested adaptation
    -> registered contract?
    -> matching rule for candidate role/capability?
    -> binding coverage?
    -> supported / unsupported / conflicting
```

Il calcolo e' statico sui contratti Registry: non modifica il grafo, non
risolve parametri finali e non costruisce mesh. In questo modo la coverage puo'
contribuire al ranking senza creare una dipendenza circolare tra candidate
selection e adaptation materialization.

## ARCH-HARDEN-F. Resolution ordering

Il flusso end-to-end aggiornato e':

```text
requested concept
    -> exact local concept resolution, if possible
    -> LLM semantic mapping only when necessary
    -> validated Archetype/Profile intent
    -> backend ImplementationBinding discovery
    -> hard requirement filtering
    -> deterministic adaptation coverage preflight
    -> deterministic coverage ranking
    -> concrete root selected by backend
    -> Profile/adaptation materialization
    -> normal CompositionPlan
    -> existing 3DGen pipeline
```

"Exact local concept resolution" include un Component direct, un alias,
un Profile o un Archetype registrato. In questi casi l'LLM non serve per
inventare una semantica gia' installata. L'LLM entra soltanto quando il
concept non e' risolvibile esattamente dal metadata locale.

La coverage preflight non applica adattamenti. Interroga solo:

```text
TraitSpec / TraitRule metadata
StructuralTraitSpec / StructuralTraitRule metadata
public component roles and param roles
ImplementationBinding roles/capabilities
```

Quindi il backend puo' confrontare i candidati prima di fissare il root. Dopo
la scelta, la materializzazione e' una trasformazione monotona del piano
validato: non puo' introdurre un nuovo Component e non puo' riaprire la
selezione.

## ARCH-HARDEN-G. Lynx severe case

I benchmark lynx devono registrare quattro insiemi distinti:

```text
requested semantic differences
installed adaptation vocabulary
supported adaptations for selected candidate
unsupported adaptations and reasons
```

### Felid metadata installed

Scenario:

```text
no lynx plugin
felid/quadruped metadata installed
one or more quadruped ImplementationBindings installed
```

Il backend risolve `felid`, raccoglie i binding di body-plan compatibili,
scarta quelli che falliscono i requisiti e sceglie il root con il ranking. Il
prompt puo' chiedere coda piu' corta, zampe piu' grandi, orecchie piu' grandi
e gambe piu' lunghe. Per ciascuna differenza il report deve mostrare se esiste
un contratto gia' installato e se una regola e' applicabile al candidato.

Una feature tipica come ciuffi sulle orecchie puo' restare unsupported. Questo
non rende il benchmark fallito: il benchmark e' riuscito se il root e' valido,
le differenze supportate sono materializzate attraverso contratti esistenti,
le differenze non supportate sono dichiarate e il build resta valido.

### Zero lynx metadata

Scenario:

```text
no lynx plugin
no lynx profile
no lynx archetype
```

L'LLM vede il compact global index e puo' proporre `felid`, `quadruped` e un
Profile gia' presente, se esiste. Se `felid` non e' installato, puo' proporre
un body-plan disponibile soltanto quando la semantica e' supportata dal prompt
e la coverage e' validabile. Il backend seleziona comunque il root tramite
binding; l'LLM non puo' nominare un Component come autorita'.

Il benchmark non introduce nuovi Trait teorici. L'insieme
`installed adaptation vocabulary` e' lo snapshot dei Trait, Structural Traits,
ruoli, param-role e component capability gia' registrati. Le differenze
richieste sono testo semantico; diventano supported solo quando uno di quei
contratti le copre. Tutto il resto va in `unsupported`, con motivo leggibile.

Una approximation parziale ma validata e' un successo; una geometria inventata
o un parametro non registrato non lo e'.

## ARCH-HARDEN-H. Planner payload

La quantificazione concettuale resta:

```text
GLOBAL CONCEPT INDEX:
  N entries
  3 small fields per entry: canonical id, essential aliases, short description

DETAILED SHORTLIST:
  K entries, K bounded by configured planner budget
  requirements, Profiles, bindings and relevant contract references only

TRAITS/STRUCTURAL TRAITS/STYLES:
  existing compact vocabulary
  ids and short descriptions, no duplicated rule bodies
```

Il global index serve alla discovery semantica e non porta parametri, mesh,
regole o tutte le relazioni espanse. La detailed shortlist serve alla
validazione operativa e non ripete la descrizione canonica. Il planner payload
non cresce moltiplicando lo stesso testo per ogni Profile o binding.

Il limite `K` e il budget dei contratti devono essere misurati e configurabili
dal backend. Se `N` eccede il budget globale, si passa agli shard/summary
groups descritti in ARCH-HARDEN-B; non si tronca in modo casuale e non si
nascondono i concetti rari solo perche' hanno poco overlap lessicale.

## ARCH-HARDEN-I. Minimal runtime V1 changes after hardening

Quando verra' il momento di implementare, l'hardening aggiunge soltanto questi
punti al piano V1 precedente:

1. `ImplementationBinding` data-only e raccolta Registry;
2. validazione di binding, Component root e Archetype supportati;
3. compact global Archetype index separato dalla detailed shortlist;
4. backend preflight per coverage delle adaptations;
5. ranking che usa binding e body-plan distance, non nomi o tags come verita';
6. schema planner con semantic intent e `implementation_hint` opzionale,
   sempre non autorevole;
7. provenance che separa semantic truth, binding match e concrete proxy;
8. benchmark lynx basato soltanto sul vocabulary realmente installato.

Non sono richiesti un secondo LLM, embeddings, web search, nuovi Trait teorici,
nuove mesh o un nuovo package type. Il resto della pipeline rimane quello
esistente: dopo la selezione backend, il piano diventa un normale
CompositionGraph.

## ARCH-AG. Files changed

Questa fase design-only crea soltanto:

```text
ARCHETYPES-AND-PROFILES.md
```

Non richiede modifiche a:

```text
app/core
app/plugins
tests
manifest esistenti
Structural/Layout
```

## Final principles

```text
Do not build taxonomy for taxonomy's sake.
Do not create lynx.py to pass a benchmark.
Do not let Archetypes generate geometry.
Do not let Profiles bypass Traits or Components.
Do not let the LLM invent unsupported parameters.
Do not confuse semantic similarity with implementation compatibility.
Keep normality separate from validity.
Persist validated fallback decisions.
Let explicit user intent beat inferred defaults.
```

Il modello desiderato resta:

```text
requested concept
    -> semantic/archetype understanding
    -> closest representable generative basis
    -> validated adaptation using installed vocabulary
    -> ordinary 3DGen CompositionGraph
    -> existing pipeline
```

> Archetypes guide what something is typically like.
>
> Profiles describe reusable configurations of that archetype.
>
> Traits express semantic differences.
>
> Components still own geometry.
>
> Explicit user intent always beats inferred defaults.
