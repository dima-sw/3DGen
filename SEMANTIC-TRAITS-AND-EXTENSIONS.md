# 3DGen - Semantic Traits + Third-Party Extensions

Specifica architetturale. Stato: design, nessuna implementazione runtime del
trait system.

Obiettivo:

> semantic intent can flow through a heterogeneous CompositionGraph while each
> compatible component retains ownership of how that intent becomes geometry.

E:

> third-party authors can add new laws without copying or modifying the
> original plugin.

---

## 1. Riutilizzo dell'architettura attuale

Il sistema non deve nascere come pipeline parallela agli Effects. Il codice
attuale ha gia' quasi tutti i pezzi pubblici necessari:

| Esistente | Riuso per i Traits |
|---|---|
| `Component.role` | compatibilita' semantica grossa: `torso`, `arm`, `head`, `tree_crown` |
| `Component.tags` | compatibilita' descrittiva e cross-plugin: `fox`, `foliage`, `humanoid` |
| `Component.provides` / `mounts` | capacita' e struttura senza nominare id concreti |
| `ParamSpec.semantic_role` | canale pubblico minimo per parametri come `length`, `girth` |
| `ParamSpec.coerce` e `resolve_params` | validazione finale dei valori prodotti |
| `EffectSpec`, `ParamRule`, `EffectRequest` | formato gia' adatto a trasformazioni semantiche su parametri o mesh |
| `Scope` (`model`, `subtree`, `part`, `role`, `group`) | modello di targeting da riusare |
| `CompositionGraph.path()` e `on:` | precedente per indirizzare sottoparti dichiarate da altri componenti |
| `ResolvedNode.sources` | provenance dei valori; va estesa con `trait` |
| `Report` | diagnostica non fatale per unsupported e conflitti |
| `Registry` | indice deterministico di cose dichiarate dai plugin |
| `Vocabulary` | faccia pubblica data-only del registry per il planner |

Il punto importante: un Trait non e' un Effect rinominato. Un Trait e' intento
utente; una Extension puo' tradurlo in param patch o effect request usando le
API gia' esistenti.

---

## 2. Terminologia

### Param

Valore concreto, locale e implementativo di un `Component`.

Esempi:

```text
length
width
girth
head_size
tail_volume
crown_width
```

Un Param vive nel contratto pubblico del componente che lo dichiara. E'
validato dal suo `ParamSpec`. Anche quando ha un nome semantico, resta un
meccanismo implementativo.

Nota: l'attuale `humanoid_anatomical:body` ha un parametro `body_mass`.
Quello oggi e' un Param locale, non un Trait globale. Il futuro Trait
`body_mass` non deve dipendere dal fatto che quel Param esista.

### Trait

Intento semantico applicabile a uno scope del grafo.

Esempi:

```text
body_mass
muscularity
age
leafiness
damage
season
```

Un Trait non sa come e' costruita la mesh e non deve nominare vertici, funzioni
`build`, campi privati o geometria interna. Il Trait dice "che intenzione scorre
nel grafo"; le Extension dicono come interpretarla localmente.

### Extension

Contributo registrabile da un autore terzo che insegna come uno o piu' Trait si
traducono per componenti compatibili.

Una Extension non e' un nuovo tipo di pacchetto. E' un normale plugin 3DGen che
puo' non dichiarare componenti e registrare solo trait specs, trait rules,
effects, materiali o metadata.

---

## 3. Principio centrale

La catena desiderata e':

```text
USER INTENT
  -> TRAIT
  -> TRAIT RESOLUTION
  -> COMPATIBLE EXTENSION RULES
  -> PUBLIC PARAM / EFFECT PATCHES
  -> EXISTING BUILD PIPELINE
```

Il core puo' conoscere:

```text
Trait identity
Trait value type/range
scope
inheritance
compatibility matching
resolution
validation
conflict detection
provenance
```

Il core non deve conoscere:

```text
what fat means
what old means
what muscular means
what autumn means
what damaged means geometrically
```

Quel significato appartiene alle Extension installate.

---

## 4. Data model proposto

Questa e' la forma concettuale minima. I nomi sono indicativi.

```python
TraitSpec(
    id="std:body_mass",
    aliases=("body_mass",),
    description="perceived mass/fullness of an organic body",
    value=ParamSpec(0.5, RATIO, min=0.0, max=1.0),
    scopes=("local", "subtree"),
    operations=("set", "add"),
    owner="std",
    version="1.0.0",
)
```

```python
TraitRequest(
    trait="body_mass",
    value=0.7,
    op="set",
    on="root",
    scope="subtree",
)
```

```python
TraitRule(
    id="human_body_mass:torso_width",
    trait="std:body_mass",
    match=TraitMatch(
        roles=("torso",),
        tags=("humanoid",),
        param_roles=("girth",),
    ),
    patches=(
        ParamPatch(
            param="girth",
            expression="value * (1 + trait * 0.28)",
            channel="torso_mass",
        ),
    ),
)
```

```python
TraitResolution(
    applied=[...],
    unsupported=[...],
    conflicts=[...],
    diagnostics=Report(...),
)
```

La forma dati non deve diventare un DSL grande. Le espressioni dei patch devono
riusare l'espression evaluator gia' usato da `ParamRule`, con variabili
limitate:

```text
value        valore corrente del parametro
trait        valore risolto del trait sul nodo
default      valore default del parametro
min/max      limiti dichiarati se disponibili
```

Niente accesso a mesh, build context, filesystem, import o funzioni arbitrarie.

---

## 5. Trait ownership e naming

Il rischio da evitare:

```text
authorA:mass
authorB:mass
```

sembrano uguali ma significano cose diverse.

Regola proposta:

1. L'identita' canonica di un Trait e' sempre namespaced: `namespace:name`.
2. I nomi nudi (`body_mass`) sono alias, non identita' canoniche.
3. Un alias nudo e' accettato solo se:
   - appartiene a un Trait standard stabilizzato, oppure
   - e' univoco nel registry installato.
4. Se due Trait registrano lo stesso alias non standard, il planner non lo vede
   come nome nudo e un piano che lo usa riceve `TRAIT_AMBIGUOUS`.

Esempio:

```text
std:body_mass      alias body_mass
acme:toon_mass     alias toon_mass
botany:leafiness   alias leafiness
```

`std:` non deve essere grande all'inizio. Puo' contenere solo Traits il cui
contratto semantico e' stato stabilizzato. Prima di allora un plugin puo'
registrare `human_body:body_mass` o simili.

---

## 6. Scope e inheritance

V1 deve restare minimale:

```text
local       vale solo sul nodo target
subtree     vale sul target e su tutti i discendenti
```

`root/global` non serve come scope separato: `on="root", scope="subtree"` copre
il caso globale. `descendants-only` puo' essere aggiunto in futuro se un caso
reale lo chiede, ma non e' necessario per `body_mass`.

Risoluzione concettuale:

```text
root body_mass = 0.7            scope=subtree
root/torso/abdomen += 0.3       scope=local

root       0.7
torso      0.7
abdomen    1.0
arms       0.7
legs       0.7
```

Ordine deterministico:

1. Validare tutte le `TraitRequest` contro `TraitSpec`.
2. Ordinare per profondita' del target, poi per indice esplicito nel piano.
3. Propagare `subtree` dal target ai discendenti risolti.
4. Applicare `local` solo al nodo target.

Il piano array conserva un ordine esplicito, ma non deve diventare "last writer
wins" nascosto. Per lo stesso `trait + target + scope`, due `set` concorrenti
nello stesso livello sono un conflitto, non una scelta implicita.

---

## 7. Operazioni e merge semantics

Set minimo per V1:

```text
set
add
```

`multiply` e combinatori piu' complessi restano fuori dalla prima
implementazione.

Semantica:

| op | significato |
|---|---|
| `set` | imposta il valore risolto per quel target/scope |
| `add` | aggiunge un delta al valore ereditato |

Regole:

- `set` richiede un valore dentro il dominio del Trait.
- `add` produce un valore finale che viene ricondotto nel dominio del Trait.
- due `set` locali per lo stesso Trait e nodo sono `TRAIT_VALUE_CONFLICT`;
- `add` senza valore ereditato parte dal default del `TraitSpec`;
- il risultato finale e' sempre validato dal `TraitSpec.value`.

---

## 8. Precedenza

Precedenza proposta:

```text
component default
-> inherited traits
-> local trait requests
-> explicit user param override
-> explicit user effects
```

Conseguenza:

```text
body_mass = 0.8
```

puo' allargare un braccio compatibile.

Ma:

```text
arm.width = explicit user value
```

vince su cio' che `body_mass` avrebbe prodotto per `width`.

Nel codice futuro questo richiede una nuova provenance:

```text
FROM_TRAIT = "trait"
```

Un param patch da Trait puo' modificare un parametro solo se la sua sorgente non
e' `FROM_OVERRIDE`. Se trova `FROM_OVERRIDE`, produce una nota:

```text
TRAIT_PATCH_SKIPPED_BY_OVERRIDE
```

Gli Effects espliciti restano intenzioni dell'utente e devono venire dopo i
Trait: un utente puo' chiedere corpo massiccio e poi piegare/ruotare una parte.

---

## 9. Extension registration

Un plugin normale puo' dichiarare sorgenti di trait:

```json
{
  "id": "human_body_mass",
  "version": "0.1.0",
  "components": [],
  "effects": [],
  "styles": [],
  "traits": ["traits/body_mass.py"]
}
```

Questa e' una estensione del manifest, non un nuovo ecosistema. La stessa
meccanica di `components`, `effects`, `styles`, `materials` carica moduli Python
e raccoglie oggetti dichiarativi.

Ogni Trait Extension dichiara:

```text
trait name/id
accepted value type/range
compatible semantic roles/tags/capabilities/param roles
rules
produced param patches and/or effect requests
optional requirements
version compatibility
```

Forma minima:

```python
BODY_MASS = TraitSpec(...)

TORSO_RULE = TraitRule(
    id="human_body_mass:torso",
    trait="std:body_mass",
    match=TraitMatch(roles=("torso",), tags=("humanoid",)),
    patches=(
        ParamPatch(param_role="girth",
                   expression="value * (1 + trait * 0.30)",
                   channel="torso_mass"),
    ),
)
```

Una Extension puo' registrare solo rules per un Trait gia' noto, oppure portare
anche il `TraitSpec` se il Trait non e' ancora standard.

---

## 10. Compatibility matching

Il modello principale non deve essere:

```text
humanoid:torso
humanoid:left_arm
humanoid:right_arm
```

Il matching deve preferire contratti generali:

```text
Component.role
Component.tags
Component.provides / mounts
ParamSpec.semantic_role
EffectSpec id/scope
StyleProfile id
```

Ordine di matching consigliato:

1. Trait id compatibile.
2. Stile compatibile se la regola lo dichiara.
3. Component role/tags/capabilities.
4. Param semantic role o param name pubblico.
5. Specific component id solo come opt-in/fallback.

Esempio:

```text
role=torso + param_role=girth
```

puo' colpire:

```text
humanoid:torso
humanoid_anatomical:ribcage
thirdparty:orc_torso
future:cartoon_torso
```

se questi dichiarano ruoli/tag/parametri compatibili.

Nota sui ruoli attuali: `ParamSpec.semantic_role` oggi e' volutamente largo
(`length`, `girth`, `ratio`). Per Traits ricchi puo' non bastare. La V1 puo'
partire da `Component.role + tags + ParamSpec.semantic_role`; una V2 puo'
aggiungere canali piu' espliciti come `trait_channels` se l'esperienza reale lo
richiede.

---

## 11. Encapsulation boundary

Una Extension puo' agire solo tramite API pubbliche:

```text
TraitSpec
TraitRule
TraitMatch
ParamPatch su ParamSpec pubblici
EffectRequest verso EffectSpec registrati
Component.role/tags/provides/mounts/styles
ResolvedNode.values/sources tramite il trait resolver
Report diagnostics
```

Una Extension non deve:

```text
modificare mesh.vertices di componenti altrui
chiamare o sostituire build() di un altro plugin
patchare classi o moduli di altri plugin
leggere campi privati/helper interni
dipendere da nomi locali non dichiarati come contratto
```

Principio:

> extensions add laws through public contracts; they do not patch foreign
> implementation internals.

Un plugin Python installato e' comunque codice Python. Questa specifica non
costruisce sandboxing. Definisce pero' cosa e' comportamento supportato e cosa
e' monkey patching fuori contratto.

---

## 12. Param patch vs Effect

Una Trait rule puo' produrre due tipi di output.

### ParamPatch

Usare quando il Trait cambia cosa viene costruito.

Esempi:

```text
body_mass -> torso girth/width/depth
muscularity -> arm girth, shoulder width
age proportions -> head_size/limb length
leafiness deformational -> crown_width/crown_height
```

Il patch passa sempre da `ParamSpec.coerce`. Non puo' generare `width = -4`.

### EffectRequest

Usare quando il Trait e' meglio come trasformazione dichiarata o superficie gia'
esistente.

Esempi:

```text
damage -> registered dent/chip/bend effects
wind -> bend su rami o bandiere
pose-like lean -> existing final/local effects
```

Non duplicare gli Effects: se un plugin ha gia' un effetto `bend`, una Extension
puo' produrre una richiesta a quell'effetto invece di ricreare una deformazione.

---

## 13. Multiple extensions e conflitti

Problema:

```text
Extension A: body_mass -> torso.width
Extension B: body_mass -> torso.width
```

Non deve esistere hidden last-wins.

Policy V1:

1. Ogni output ha un channel deterministico:
   - param patch: `(node_id, param_name)`
   - effect request: `(node_id, effect_id, scope)`
2. Due regole che producono output sullo stesso channel sono in conflitto.
3. I patch conflittuali su quel channel vengono saltati entrambi.
4. I patch disgiunti restano applicabili.
5. Il report contiene `TRAIT_RULE_CONFLICT`.

Quindi:

```text
A: body_mass -> torso.width
B: body_mass -> torso.width
```

produce conflitto su `torso.width`.

Ma:

```text
A: body_mass -> torso.width
C: body_mass -> torso.depth
```

e' composable: canali diversi.

Estensioni future possibili, non V1:

```text
explicit user-selected extension set
mutually exclusive handler groups
priority only inside an explicitly selected family
declared numeric combine policy
```

La V1 deve essere comprensibile: disjoint compose, same channel conflicts.

---

## 14. Range e validation

Validazione a tre livelli:

1. `TraitSpec.value` valida il valore del Trait.
2. `TraitRule` valida che la regola abbia un target compatibile.
3. Il target finale usa `ParamSpec.coerce` o la validazione dell'EffectSpec.

Il normale parameter validation resta l'autorita' finale. Il Trait resolver non
duplica la validazione geometrica e non decide se una forma e' bella.

Diagnostiche:

```text
TRAIT_NOT_FOUND
TRAIT_VALUE_OUT_OF_RANGE
TRAIT_TARGET_NOT_FOUND
TRAIT_UNSUPPORTED
TRAIT_RULE_CONFLICT
TRAIT_PATCH_CLAMPED
TRAIT_PATCH_SKIPPED_BY_OVERRIDE
TRAIT_EFFECT_NOT_FOUND
```

`TRAIT_UNSUPPORTED` non e' errore di default. Un componente robotico o un
componente senza regole compatibili resta invariato e viene annotato.

Strict mode puo' esistere in futuro:

```text
strict_traits=True -> unsupported richiesto diventa errore
```

Non e' necessario per V1.

---

## 15. Planner e vocabulary

L'LLM deve vedere solo Traits realmente registrati/disponibili.

Il vocabolario compatto dei Trait deve includere:

```text
trait id or stable alias
description
value type/range/choices
supported ops
scope support
semantic purpose
```

Non deve includere:

```text
implementation rules dettagliate
param patch expressions
component internals
Python code
private extension metadata
```

Esempio testo compatto:

```text
## TRAITS (usa questi id, e nessun altro)
- body_mass ratio [0,1] ops=set,add scopes=local,subtree purpose="organic fullness/mass"
- leafiness ratio [0,1] ops=set,add scopes=local,subtree purpose="foliage amount where supported"
- season enum {spring,summer,autumn,winter} ops=set scopes=subtree purpose="seasonal appearance"
```

Il planner non deve inventare `mega_fatness_mode`: se non e' nel vocabolario,
non e' valido.

---

## 16. Plan JSON proposal

Estensione additiva minima:

```json
{
  "version": "1.1",
  "style": "low_poly",
  "detail_level": 3,
  "seed": 123,
  "traits": [
    {
      "trait": "body_mass",
      "value": 0.7,
      "on": "root",
      "scope": "subtree"
    },
    {
      "trait": "body_mass",
      "op": "add",
      "value": 0.3,
      "on": "root/torso/abdomen",
      "scope": "local"
    }
  ],
  "root": {
    "id": "root",
    "ref": "humanoid:body",
    "params": { "height": 1.8 }
  }
}
```

Default:

```text
op = set
scope = subtree
on = root
```

Compatibilita':

- piani senza `traits` si comportano esattamente come oggi;
- `.my3d` v2 puo' continuare a salvare il `graph` se `CompositionGraph.to_dict`
  include in futuro `traits`;
- lo schema planner deve passare a `1.1` perche' oggi `additionalProperties`
  rifiuta `traits`;
- il formato zip `.my3d` non richiede per forza un major bump se il wrapper
  resta uguale, ma il loader deve registrare plugin/trait versions nei metadata
  come gia' fa per i plugin.

---

## 17. Pipeline insertion point

Pipeline attuale:

```text
CompositionGraph
-> Resolver
-> ResolvedComposition
-> EffectPipeline
-> EffectedComposition
-> Builder
-> Validate
```

Pipeline proposta per deformational/semantic Traits:

```text
CompositionGraph
-> Resolver
-> ResolvedComposition
-> TraitResolver
-> TraitPatchedComposition
-> EffectPipeline
-> EffectedComposition
-> Builder
-> Validate
```

Perche' dopo il Resolver:

- il Resolver sa quali componenti esistono davvero nel subtree;
- i componenti dichiarati internamente (`children`) sono visibili;
- `on:` e detail corridors sono gia' risolti;
- i parametri hanno default/override/derived e provenance.

Perche' prima degli Effects:

- i Trait deformational spesso cambiano parametri, cioe' "cosa si costruisce";
- gli Effects espliciti dell'utente devono poter vincere come intenzione piu'
  locale;
- gli Effects geometrici hanno senso dopo che i parametri sono stabiliti.

Interazione con gli stadi esistenti:

| Stage esistente | Relazione con Traits |
|---|---|
| structural | fuori da V1; usato solo dai futuri Structural Traits |
| proportion | principale target dei param patch Trait |
| local/global/style/final | target via EffectRequest se una rule lo richiede |

Non serve inventare un nuovo stage Effect. Serve un pass prima della
EffectPipeline che traduce Trait in patch pubblici.

---

## 18. Provenance e debugging

La risoluzione deve essere leggibile.

Esempio:

```text
trait body_mass=0.7
target=root
scope=subtree

matched:
  root/torso -> human_body_mass:torso -> girth, flat
  root/arm_l -> human_body_mass:limb -> girth
  root/arm_r -> human_body_mass:limb -> girth
  root/head -> human_body_mass:face -> cheek_width

unsupported:
  root/robot_arm -> no compatible rule

skipped:
  root/arm_l.width -> explicit user override

conflicts:
  root/torso.width -> extA and extB both patch same channel
```

Provenance sul valore:

```text
source = trait
origin = std:body_mass
rule = human_body_mass:torso
previous = 0.21
expression = value * (1 + trait * 0.30)
```

La diagnostica deve essere disponibile sia nel `Report` sia in una struttura
serializzabile accanto al risultato, come gia' avviene per plan/resolved/effects.

---

## 19. Backward compatibility

Regole:

1. Un progetto senza `traits` produce lo stesso risultato di oggi.
2. I plugin esistenti non devono registrare nulla per continuare a funzionare.
3. I Param esistenti restano Param, anche se hanno nomi semanticamente ricchi.
4. `EffectSpec` e `ParamSpec` continuano a essere validatori finali.
5. Plugin che non supportano un Trait restano invariati.
6. Il planner vede Traits solo se registrati.

Le API pubbliche sono congelate da `tests/test_api_freeze.py`; qualunque nuova
classe pubblica o campo pubblico deve aggiornare quel test in modo esplicito.

---

## 20. Body mass example

### Root + abdomen override

Input:

```json
"traits": [
  { "trait": "body_mass", "value": 0.7, "on": "root", "scope": "subtree" },
  { "trait": "body_mass", "op": "add", "value": 0.3,
    "on": "root/torso/abdomen", "scope": "local" }
]
```

Resolved trait values:

```text
root                 0.7
root/torso           0.7
root/torso/abdomen   1.0
root/arm_l           0.7
root/arm_r           0.7
root/leg_l           0.7
root/leg_r           0.7
```

Possible extension rules:

```text
torso_mass
  match role=torso
  patch public girth/depth params

limb_girth
  match role=arm|leg|limb and param_role=girth
  patch girth/radius params

cheek_volume
  match role=head|face and tags face/head
  patch cheek_width/head_width/head_depth if public
```

None of these rules lives in the core.

### Mixed plugin graph

Graph:

```text
character
|-- humanoid:torso
|-- fox_stylized:head
|-- humanoid:arm
`-- robot:arm
```

Apply:

```text
body_mass = 0.8
scope = subtree
```

Desired behavior:

```text
humanoid torso
  compatible -> transformed

fox head
  compatible only if installed extension supports role=head/tags=fox/head

human arm
  compatible -> transformed

robot arm
  unsupported -> unchanged + diagnostic
```

Unsupported is not an error by default.

### Existing humanoid_anatomical note

`humanoid_anatomical:body` already has a Param named `body_mass`. That can be
used by a future Extension as one possible public parameter target, but it must
not define the global Trait by itself. Other humanoid plugins without that Param
must still be supportable through Extension rules.

---

## 21. Tree example: season e leafiness

`leafiness` is ambiguous and the architecture must not depend on the name alone.

Deformational meaning:

```text
tree
leafiness = 0.3

existing crown volume down
existing foliage lobe scale down
material saturation down
```

This is V1-compatible: it can be ParamPatch on public crown params such as
`crown_width`, `crown_height`, or an EffectRequest to a registered foliage
deformation.

Structural meaning:

```text
number of leaf clusters down
remove secondary crown lobes
add fallen leaves
```

This is not V1. It changes what exists in the graph.

`season` can be mixed:

```text
season = autumn
  param/effect: leaf material shifts, crown tint changes

season = winter
  structural future: remove/replace foliage components, add snow caps
```

The future `tree_season_extension` should therefore declare separate rules:

```text
season_color_rule        deformational/effect/material-oriented
leafiness_volume_rule    deformational param patch
leafiness_cluster_rule   structural, disabled until structural traits exist
```

---

## 22. Structural Trait boundary

Deformational/Semantic Trait:

```text
body_mass
muscularity
lean
age proportions
leafiness as crown volume
damage as dents/chips on existing parts
```

Changes existing components through public params/effects.

Structural Trait:

```text
wheel_count
tail_count
branch_count
horn_count
leaf_cluster_count
```

Changes what exists.

Structural Traits must not enter the first TraitResolver. Future path:

```text
Trait
-> CompositionGraph rewrite/expansion
-> Resolver
-> Layout
-> possibly Adaptation Planner
```

If mixed into V1, the Trait system will become a second graph builder. Avoid.

---

## 23. Future LayoutPlan relation

Example:

```text
wheel_count = 10
-> graph expansion
-> normal layout attempts
-> unplaced wheels
-> LayoutProblem
-> LLM Adaptation Planner
-> validated strategy
```

This belongs to a later architectural layer:

```text
StructuralTraitResolver
-> GraphRewritePlan
-> CompositionGraph
-> Resolver
-> LayoutPlan
-> Adaptation Planner if layout fails
```

The V1 deformational TraitResolver should know nothing about wheel placement,
tail distribution, branch packing or collision-driven adaptation.

---

## 24. Determinism

Same:

```text
graph
trait requests
installed extensions
registry versions
style
seed
```

must produce the same patches and diagnostics.

Required deterministic ordering:

```text
traits: plan order, after validation
nodes: ResolvedComposition.order
rules: sorted by canonical rule id
patch conflict grouping: sorted channel keys
diagnostics: stable Report ordering
```

Filesystem import order must not affect rule selection. The registry already
sorts discovered plugins and registered objects; the Trait registry should
follow the same pattern.

---

## 25. Security and trust boundary

Supported public API:

```text
TraitSpec/TraitRule declarations
Component/ParamSpec/EffectSpec public fields
Registry trait/effect/component queries
Report diagnostics
safe expression evaluator
```

Unsupported behavior:

```text
monkey patching another plugin
patching build functions
editing meshes owned by another component
depending on private module globals
using import side effects as registration order
using environment variables to alter rule semantics invisibly
```

No sandbox is proposed in this phase. The design still matters because it tells
third-party authors where the stable surface is.

---

## 26. Future reference extension: body_mass_extension

Not implemented now.

First benchmark extension should support:

```text
humanoid
humanoid_anatomical
fox_stylized head where meaningful
```

and ignore:

```text
robot
incompatible mechanical parts
components without matching public contracts
```

Expected assertions for the future benchmark:

```text
root body_mass propagates through subtree
local abdomen add overrides inherited value
humanoid torso and limbs patch public params
fox head only changes if fox-compatible rule installed
robot remains unchanged with diagnostic
explicit user param override wins
same-channel conflict is reported and skipped
```

---

## 27. Future reference extension: tree_season_extension

Not implemented now.

Purpose: prove the design is not humanoid-specific.

Traits:

```text
season
leafiness
```

V1-compatible rules:

```text
leafiness -> crown_width/crown_height param patches
season=autumn -> registered material/effect patch if public
season=winter -> reduce foliage volume only, not remove components
```

Non-V1 rules:

```text
leaf cluster count
fallen leaves
branch count
snow object insertion
```

Those wait for Structural Traits.

---

## 28. Minimal V1 implementation proposal

The smallest useful implementation:

1. Add public dataclasses:
   - `TraitSpec`
   - `TraitRule`
   - `TraitMatch`
   - `ParamPatch`
   - `TraitRequest`
   - `TraitResolution`
2. Extend plugin manifest with `"traits": ["..."]`.
3. Extend `Registry` with trait specs/rules:
   - `register_trait`
   - `register_trait_rule`
   - `traits`
   - `trait`
   - `trait_rules`
4. Extend `CompositionGraph` with `traits: list[TraitRequest]`.
5. Extend planner schema/validation with top-level `traits`.
6. Extend `Vocabulary` with Trait entries.
7. Implement `TraitResolver` after `resolve()` and before `apply_effects()`.
8. Add `FROM_TRAIT`.
9. Add provenance and diagnostics.
10. Add tests for:
    - inheritance/local add;
    - unsupported diagnostic;
    - explicit param override wins;
    - same-channel conflict;
    - disjoint extension composition;
    - planner sees registered traits only;
    - `.my3d` roundtrip with no traits and with traits.

Do not implement Structural Traits in V1.

---

## 29. Risks

| Risk | Mitigation |
|---|---|
| semantic collisions | canonical namespaced Trait ids, aliases only when stable or unique |
| extension conflicts | disjoint channels compose, same channel conflicts; no hidden last-wins |
| too-generic traits | require TraitSpec description/range and extension-specific matching |
| breaking encapsulation | only public params/effects/contracts; no mesh/internal patches |
| planner vocabulary explosion | show Trait specs, not rules; compact text only |
| duplicate Effects system | TraitResolver outputs ParamPatch/EffectRequest and reuses EffectPipeline |
| unsupported mistaken as failure | unsupported is diagnostic, not error, unless future strict mode |
| derived params overwritten incorrectly | add `FROM_TRAIT` and rederive rules mirroring EffectPipeline |
| current `semantic_role` too coarse | combine with component role/tags first; add channels later only if needed |
| structural traits sneaking into V1 | explicit boundary: no graph rewrite in V1 |

---

## 30. Final decision

Semantic Traits should be an additive layer over the existing registry,
resolver, params and effects systems.

The future V1 is not "more parameters". It is:

```text
registered semantic intent
-> deterministic inheritance
-> third-party compatible rules
-> public param/effect patches
-> existing build pipeline
```

That keeps ownership where it belongs:

```text
the user/plugin owns the intent
the Extension owns the mapping law
the Component owns geometry
the core owns deterministic resolution and validation
```
