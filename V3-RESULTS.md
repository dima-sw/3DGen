# V3-RESULTS — Selettori strutturali e identità stabile dei nodi

Milestone V3 di `VISION-GAP.md`, implementata il **14 ottobre 2026**.
Branch `v1-semantic-index`, partenza `193734b` (V2).

**Esito: completa.** I dieci criteri della Definition of Done sono soddisfatti e
misurati. I trait strutturali non dipendono più dagli id che il planner scrive:
lo stesso piano con radice `car`, `jeep`, `jeep1` o `auto_01` produce sei ruote
in tutti e quattro i casi, e `character:arm_count` costruisce 2 / 4 / 6 braccia
**con la catena anatomica completa** su `humanoid_anatomical:body` — un plugin
che in V2 non aveva mai funzionato. Nessuna delle tre extension installate
contiene più un percorso letterale. Suite da 1287 a **1343 test verdi**.

---

## 1. Decisioni architetturali

### 1.1 Il selettore esisteva già: non è stato aggiunto niente

La correzione non ha richiesto un secondo tipo di selettore, e la ragione è
scritta nei dati: **ogni regola ne dichiarava già uno**.

```python
# prima
ARM_COUNT_RULE = StructuralTraitRule(
    trait="character:arm_count",
    prototype="corpo/torso/arm_l",            # ← percorso letterale
    component="humanoid_anatomical:arm",
    target=StructuralTarget(role="arm", tags=("arm",)))   # ← e anche un selettore

# dopo
ARM_COUNT_RULE = StructuralTraitRule(
    trait="character:arm_count",
    component="humanoid_anatomical:arm",
    target=StructuralTarget(role="arm", tags=("arm",)))
```

Il campo `target` serviva a contare i fratelli compatibili; il campo `prototype`
a trovare quello da clonare. Sono la stessa domanda — *che cosa sto ripetendo* —
e adesso hanno una sola risposta. **Un selettore per regola.** La modifica alle
tre extension è di una riga ciascuna: una riga togliata.

`StructuralTraitRule.prototype` resta, e resta un percorso, ma è **facoltativo**.
Due casi lo usano ancora, e nessuno dei due è una supposizione sulla forma del
piano:

* `std:instance_count`, dove è la richiesta stessa a puntare un nodo preciso;
* una regola che dovesse clonare qualcosa di diverso da ciò che conta.

### 1.2 Il tie-breaking, documentato perché è un contratto

Scegliere *un* prototipo fra più candidati è la parte che può diventare magia se
non è scritta. È a gradini, come la scala di V2, e per la stessa ragione: una
somma pesata ha dei numeri da tarare e nessuno sa dire perché valgano quelli.

```python
return (not esatto, not ruolo, not capability, -tag,
        not self._parent_region_accepts(node, resolved),
        node.depth, node.path)
```

1. **component exact match** — la regola nomina questo componente
2. **role** — il ruolo dichiarato è quello richiesto
3. **capability** — il nodo fornisce la capability richiesta
4. **tags** — sovrapposizione con i tag richiesti, decrescente
5. **layout region** — il padre dichiara una `LayoutRegion` che lo accetta
6. **depth** — il meno profondo: la testa di un gruppo ripetuto, non un anello
   in mezzo a una catena
7. **path** — ordine stabile, così un pari merito non galleggia

Due passate: prima i candidati che soddisfano il selettore **intero**, e solo se
non ce n'è nessuno quelli che ne soddisfano almeno un facet — con
`STRUCTURAL_PROTOTYPE_PARTIAL_MATCH` a dirlo. I facet 2–4 sono costanti nella
prima passata per costruzione (tutti i candidati hanno superato lo stesso
selettore) e discriminano nella seconda.

I facet 5 e 6 sono quelli che risolvono il caso difficile. Nell'anatomia a
catena quattro componenti diversi dichiarano `role="arm"`:

```text
corpo/torso/shoulder_l                              depth=2  role=arm
corpo/torso/shoulder_l/upper_arm                    depth=3  role=arm
corpo/torso/shoulder_l/upper_arm/elbow              depth=4  role=arm
corpo/torso/shoulder_l/upper_arm/elbow/forearm      depth=5  role=arm
```

Si sceglie la spalla, e **non per il suo nome**: perché suo padre — il torso — è
il solo a dichiarare una `LayoutRegion` con `allows_role="arm"`, ed è la meno
profonda. Clonare la spalla rigenera l'intera catena, perché i figli di un clone
li dichiara il componente, non il piano. Clonare il gomito avrebbe prodotto un
conteggio giusto e un braccio sbagliato.

Niente di tutto questo conosce le parole braccio, ruota o coda: tutti e sette i
facet leggono dati che il componente ha dichiarato.

### 1.3 `on` da indirizzo ad ambito

`StructuralTraitRequest.on` non è più il prototipo: è il **sottoalbero dentro cui
cercarlo**. Quando nomina un nodo che esiste, restringe la ricerca; quando nomina
qualcosa che la risoluzione ha sostituito, si ignora invece di fallire.

È una differenza che si misura. `corpo/torso/arm_l` esiste a detail 1 e a
detail 2 no, perché `shoulder_l` lo `replaces`:

| `on` | detail | V2 | V3 |
| --- | --- | --- | --- |
| `corpo/torso/arm_l` | 1 | 4 braccia | 4 braccia |
| `corpo/torso/arm_l` | 2 | `parent prototype non disponibile` | 4 braccia |

Restringere una ricerca e dipendere da un percorso sono due cose diverse: la
prima degrada, la seconda rompe.

### 1.4 Dove vanno le copie: dai contratti, non dalle stringhe

Trovare il prototipo non basta — bisogna sapere dove mettere i cloni. Non lo
decide nessun percorso:

* il clone eredita la **parent relation** del prototipo;
* eredita una copia profonda del suo `Attachment`, quindi il `Requirement`
  (capability, lato, tag) e `own_socket`: la compatibilità di socket è preservata
  per costruzione;
* `LayoutEngine` distribuisce il gruppo attraverso la `LayoutRegion` e la
  `LayoutPolicy` che il padre dichiara.

Il trait strutturale decide **quante** parti servono; il layout decide **dove**
disporle. La separazione è rimasta intatta, ed è la ragione per cui si possono
chiedere sei ruote a un componente auto che non conosce il numero sei.

Un dettaglio che sarebbe stato facile perdere: `_materialize_path` materializza
non solo la catena del prototipo ma **l'intera serie di fratelli dichiarata dal
padre**. È il motivo per cui dieci ruote escono 5 sinistra / 5 destra — i cloni
ciclano su `wheel_fl/fr/rl/rr` e ne ereditano i lati. La selezione per selettore
finisce dentro quello stesso meccanismo invece di sostituirlo.

### 1.5 L'identità stabile è **derivata**, non un campo nuovo

La milestone chiedeva di verificare se bastasse ricavarla. Basta, e c'è anche un
vincolo che lo rendeva l'unica strada pulita.

Il vincolo, misurato leggendo il codice: `project.load` **non** chiama
`CompositionGraph.from_dict`. Ricostruisce ogni versione con `Session.build`,
quindi passa da `validate_plan`. Un campo `identity` esportato in `to_dict()`
sarebbe stato scartato alla riapertura come `NODE_UNKNOWN_KEY` — a meno di
allargare lo schema esposto all'LLM, cioè di dare al planner un'altra manopola
da sbagliare.

```python
identity = sha1(identita_del_padre | ref | firma_dell_attacco | ordinale)[:12]
```

* la **firma dell'attacco** è il requisito: capability, socket, lato, tag
  ordinati;
* l'**ordinale** conta i fratelli con la stessa coppia (ref, firma) nell'ordine
  di inserimento;
* la radice deriva dal solo `ref`.

Le proprietà richieste, una per una:

| Requisito | Come è soddisfatto |
| --- | --- |
| generata dal sistema, non dall'LLM | è una funzione pura: non c'è un campo da riempire |
| sopravvive a serialization | si **ricalcola** — un `.my3d` anteriore a V3 la ottiene senza cambiare formato |
| stabile se cambiano parametri o effetti | non entrano nel calcolo |
| cambia solo se il nodo è sostituito/eliminato | usa `ref`, non `resolved_ref`: uno `swap` **non** la cambia |
| distingue i cloni strutturali | ordinali diversi |
| indipendente dall'id del piano | l'id non entra nel calcolo |

`own_socket` è stato **escluso** dalla firma, e non per eleganza: il formato del
piano non lo scrive, quindi un'identità che lo contenesse cambierebbe a ogni
salva-e-riapri. Un'identità che non sopravvive al round-trip non è un'identità.
Il round-trip ha però fatto emergere un difetto vero: `to_dict()` non esportava
i **tag del requisito**, che sono ciò che distingue una ruota davanti da una
dietro (`wheel_mount` + lato `l` + tag `front` contro `rear`). Lo schema li
dichiarava già sotto `at`; adesso ci passano davvero, in entrambe le direzioni.

I due nomi restano entrambi, e la differenza è documentata in testa a
`app/core/graph.py`:

```text
planner node id        node.id          lo scrive chi scrive il piano
stable node identity   identity(id)     la deriva il sistema
```

Limite dichiarato, non nascosto: cancellare un fratello con la stessa firma
sposta gli ordinali di quelli che lo seguivano. Finché non esiste una strada che
cancella nodi — cioè finché non arriva `Session.modify` — è un confine noto.
Qualunque schema alternativo avrebbe dovuto persistere un contatore, e un
contatore persistito è esattamente il campo che il vincolo del §1.5 vietava.

### 1.6 La provenienza dei cloni riusa ciò che c'era

Tre meccanismi esistevano già e sono stati arricchiti invece di affiancati:
`Operation` nel registro del grafo, `StructuralTraitResolution.applied` e
`.created`. Dato che `graph.operations` non viene serializzato, una sola lista a
livello di radice porta la provenienza nel file di progetto:
`CompositionGraph.structural_provenance`.

Misurata, su `character:arm_count = 4`:

```text
{'trait': 'character:arm_count',
 'rule': 'multi_arm_extension:arm_count',
 'component': 'humanoid_anatomical:shoulder',
 'prototype': '56f53c3cf18f',          # identità stabile, non un percorso
 'identity': 'b7f62b1864a2',
 'clone_index': 3, 'clone_count': 4}
```

È la forma esatta che la milestone descriveva al §5: origine, prototipo, indice
del clone. Il prototipo è indicato per **identità** e non per percorso, perché un
percorso cambia se qualcuno rinomina un nodo — che è il difetto che questa
milestone esisteva per togliere.

È dichiaratamente **diagnostica**: si esporta, si rilegge, e
`structural_provenance_from_dict` butta ogni voce la cui identità non
corrisponde a nessun nodo vero. Nessuna voce può creare, spostare o rinominare
niente. Un blob allucinato non ha niente da iniettare.

### 1.7 Un elemento facoltativo sconosciuto non distrugge una struttura valida

La regola è generale e scritta in testa a `app/core/planner/plans.py`, non un
caso speciale per `instance_count`:

> Ciò che si può ignorare in sicurezza si ignora e si dichiara; ciò che rende il
> piano ambiguo o incostruibile resta fatale.

Un `trait` o uno `structural_trait` **sconosciuto** diventa
`UNKNOWN_TRAIT_SKIPPED`, severità avviso, e viene tolto dal piano: la richiesta
non si inventa, si dichiara persa. Un codice solo per i due casi, perché la
politica è una sola.

```text
UNKNOWN_TRAIT_SKIPPED
trait sconosciuto, ignorato: trait = 'instance_count'
   perche': un elemento facoltativo sconosciuto non invalida il resto del piano
   alternative: botany:leafiness, std:body_mass
```

Restano **fatali**, deliberatamente, e c'è un test parametrico per ognuno:

| Caso | Codice | Perché non si può ignorare |
| --- | --- | --- |
| radice inesistente | `COMPONENT_NOT_FOUND` | non c'è niente da costruire |
| attacco essenziale impossibile | `SOCKET_INCOMPATIBLE` | il resolver lo dice, non lo nasconde |
| elenco o oggetto malformato | `TRAITS_NOT_A_LIST`, `TRAIT_NOT_AN_OBJECT` | è lo schema |
| trait senza id o senza valore | `TRAIT_NO_ID`, `TRAIT_NO_VALUE` | non si sa nemmeno cosa chiedesse |
| nome registrato due volte | `TRAIT_AMBIGUOUS` | ignorarlo sarebbe **scegliere** al posto di chi ha scritto il piano |
| trait noto, op o scope invalidi | `TRAIT_*_UNSUPPORTED` | la richiesta è leggibile e sbagliata |
| effetto inesistente | `EFFECT_NOT_FOUND` | vedi sotto |

La distinzione fra «non esiste» e «non si sa quale» è la meno ovvia delle sette,
ed è quella che impedisce alla politica di diventare un'indulgenza generica.

**Perché gli effetti restano fatali.** Un effetto è scritto *su un nodo* e dice
come quel nodo deve venire: ignorarlo cambia la geometria in silenzio, non la
lascia incompleta. La milestone limita la politica ai due generi di trait, e
tre test esistenti (`test_core_effects.py:119`, `test_planner_core.py:297`,
`test_plugins.py:328`) codificano il contratto attuale. Allargarla sarebbe una
decisione diversa, da prendere apposta. È registrata al §9, con la forma esatta.

**Non fatale non vuol dire invisibile.** `GenerationResult.skipped()` riporta i
trait persi leggendoli dal referto — nessun campo nuovo — quindi compaiono anche
in `to_dict()`. Una richiesta persa in silenzio sarebbe stato lo stesso difetto
spostato di un metro.

---

## 2. File modificati

| File | Che cosa |
| --- | --- |
| `app/core/structural.py` | selezione del prototipo per selettore (`_locate`, `_discover`, `_rank`, `_parent_region_accepts`, `_explore`); `on` come ambito; `StructuralTarget.facets/empty/describe`; `EnsureCountOperation.on`; provenienza dei cloni; `UNKNOWN_TRAIT_SKIPPED` |
| `app/core/graph.py` | `identity()`, `identities()`, `by_identity()`, `structural_provenance`, `structural_provenance_from_dict`, `_signature`, `_digest`; i tag del requisito in `to_dict`/`from_dict`; la sezione «Due identità per nodo» |
| `app/core/planner/plans.py` | politica dei trait facoltativi sconosciuti, `structural_provenance` fra le chiavi di radice, la regola documentata in testa al file |
| `app/core/session.py` | `GenerationResult.skipped()` riporta i trait ignorati |
| `app/plugins/multi_arm_extension/structural/arms.py` | `prototype` rimosso |
| `app/plugins/multi_wheel_extension/structural/wheels.py` | `prototype` rimosso |
| `app/plugins/multi_tail_extension/structural/tails.py` | `prototype` rimosso |
| `tests/test_api_freeze.py` | elenco congelato aggiornato (additivo) |
| `tests/test_traits.py` | **un cambio di contratto deliberato**, §6 |
| `tests/test_structural_identity.py` | **nuovo**, 56 test |

Nessun file nuovo nel core: la selezione vive dove viveva la risoluzione del
prototipo, e l'identità dove vivono già `path()` e `resolved_ref()`. Nessun
secondo selector type: `StructuralTarget` era già quello giusto.

`V3-PLAN.md` è la nota di progetto scritta prima di toccare il codice, con i
fatti misurati dal tree e il perché di ogni decisione. Resta nel repository
perché due delle tre decisioni difficili sono venute da lì.

---

## 3. Comportamento prima e dopo

| Caso | V2 | V3 |
| --- | --- | --- |
| `wheel_count = 6`, radice `car` | ✅ 6 ruote | ✅ 6 ruote |
| `wheel_count = 6`, radice `jeep` | ❌ `parent prototype non disponibile: 'car'`, 0 tris | ✅ 6 ruote, 284 tris |
| `wheel_count = 6`, radice `jeep1` / `auto_01` | ❌ idem | ✅ 6 ruote, 284 tris |
| `arm_count` su qualunque corpo | ❌ `parent prototype non disponibile: 'corpo/torso'` | ✅ 2 / 4 / 6 braccia |
| `arm_count` a detail 2 | ❌ mai funzionato | ✅ catena completa per ogni braccio |
| `on` che nomina un nodo sostituito | ❌ fatale | ✅ si ignora, si cerca nell'albero |
| trait inventato dal planner | ❌ `graph is None`, 0 tris | ✅ avviso, piano vivo, richiesta dichiarata persa |
| id del piano rinominati | ❌ cambiava l'esito | ✅ struttura identica |
| riconoscere un nodo già creato | — | `by_identity()` |
| spiegare un clone | percorso del prototipo | trait, regola, prototipo per identità, indice/totale |

### 3.1 Ruote: 4 / 6 / 8 con qualunque nome della radice

Detail 2, seme 7. Nessuna regola contiene nessuno di questi nomi — c'è un test
che lo verifica leggendo il registro.

| radice | `wheel_count` | ok | ruote | lati | placements | triangoli |
| --- | ---: | --- | ---: | --- | ---: | ---: |
| `car` | 6 | ✅ | 6 | 3 l / 3 r | 6 | 284 |
| `jeep` | 6 | ✅ | 6 | 3 l / 3 r | 6 | 284 |
| `jeep1` | 6 | ✅ | 6 | 3 l / 3 r | 6 | 284 |
| `auto_01` | 6 | ✅ | 6 | 3 l / 3 r | 6 | 284 |
| `jeep` | 4 | ✅ | 4 | 2 l / 2 r | 4 | 228 |
| `jeep` | 8 | ✅ | 8 | 4 l / 4 r | 8 | 340 |

### 3.2 Braccia: 2 / 4 / 6 sull'humanoid anatomico

Radice chiamata `robot_01`, detail 2.

| `arm_count` | ok | spalle | nodi `role="arm"` | placements | triangoli |
| ---: | --- | ---: | ---: | ---: | ---: |
| 2 | ✅ | 2 | 8 | 2 | 1290 |
| 4 | ✅ | 4 | 16 | 4 | 1578 |
| 6 | ✅ | 6 | 24 | 6 | 1866 |

I nodi `role="arm"` sono quattro per braccio — `shoulder`, `upper_arm`, `elbow`,
`forearm` — ed è il numero che dimostra che le braccia nuove sono **catene** e
non nodi singoli. Il test verifica la catena per esteso, non il conteggio:

```text
shoulder -> upper_arm -> elbow -> forearm -> wrist -> hand
```

per ognuna delle braccia, con i lati che restano bilanciati. Un clone che avesse
prodotto un solo nodo avrebbe passato un conteggio e non sarebbe stato un
braccio.

Le gambe restano due in tutti e tre i casi: chiedere braccia non moltiplica
altro.

### 3.3 Code

Radice `kitsune`, detail 2. `multi_tail_extension` nomina `fox_stylized:tail`.

| `tail_count` | ok | code | placements | triangoli |
| ---: | --- | ---: | ---: | ---: |
| 1 | ✅ | 1 | 1 | 412 |
| 3 | ✅ | 3 | 3 | 572 |
| 9 | ✅ | 9 | 9 | 1052 |

Il caso interessante è un altro: la stessa regola, applicata a `fish:fish_body`,
trova `fish:tail` e produce tre code di pesce. Il selettore non è un alias del
componente della regola — un plugin che dichiara `role="tail"` partecipa senza
che nessuno scriva niente da nessuna parte. È la stessa proprietà che V2 aveva
dato alla degradazione semantica, e c'è un test dedicato.

**Correttezza strutturale e qualità visiva, distinte.** `fan_policy` distribuisce
nove code su una regione dichiarata per una, e il risultato è geometricamente
corretto e artisticamente discutibile: angoli da −70° a +70° su una base pensata
per una coda sola. La milestone chiedeva di separare i due giudizi, ed è
registrato come debito al §9 — non è un difetto del meccanismo, è un asset che
non è stato disegnato per nove code.

Lo stesso vale, in modo più netto, per il plugin `humanoid` storico: non dichiara
nessuna `LayoutRegion`, quindi quattro braccia si risolvono sui socket ordinari
del resolver e il layout non ha niente da distribuire. Non è un fallimento — è un
componente che non ha chiesto di essere distribuito. Pretendere delle placement
lì vorrebbe dire pretendere che ogni componente dichiari una regione, che è il
contrario del contratto. Il test lo asserisce esplicitamente.

### 3.4 Rename invariance

Il test che impedisce il ritorno dei percorsi letterali: si costruisce un piano,
si rinominano **tutti** gli id dei nodi con valori arbitrari (`a`, `zzz_99`,
`Il_Mio_Oggetto`, `x`), si applica lo stesso structural trait e si confronta la
struttura semantica risultante — componente, ruolo, lato, capability e profondità
di ogni nodo, più placements e triangoli. L'id del nodo, che è la cosa che non
deve contare, non entra nel confronto.

Verde su quattro combinazioni: ruote a detail 1, braccia a detail 1 e a detail 2,
code. In più, le **identità stabili** sono le stesse insieme sotto tutti e quattro
i nomi di radice — che è la stessa proprietà vista dall'altro lato.

---

## 4. Performance

25 ripetizioni per caso, mediane, pipeline locale senza rete.

| Caso | nodi | riscrittura | layout | `identities()` | `resolve` senza trait |
| --- | ---: | ---: | ---: | ---: | ---: |
| ruote 6 | 8 | 1,19 ms | 0,28 ms | 0,042 ms | 0,57 ms |
| ruote 8 | 10 | 1,57 ms | 0,30 ms | 0,050 ms | 0,64 ms |
| braccia 4, detail 1 | 9 | 1,52 ms | 0,50 ms | 0,049 ms | 0,93 ms |
| braccia 6, detail 2 | 14 | 5,14 ms | 0,77 ms | 0,075 ms | 4,00 ms |
| code 9 | 16 | 2,73 ms | 0,69 ms | 0,075 ms | 0,75 ms |

`identities()` su 200 nodi — il tetto di `validate_plan` — costa **0,61 ms**.

Due cose da dire.

**L'identità è gratis.** 0,04–0,08 ms sui grafi veri, contro una pipeline locale
che sta fra 6 e 13 ms. Non c'è niente da ottimizzare e non è stato ottimizzato
niente: la memoizzazione è un dizionario calcolato in un passo dalla radice alle
foglie, perché l'identità di un nodo contiene quella del padre e calcolarle una
per volta vorrebbe dire risalire la catena ogni volta.

**La riscrittura costa una risoluzione, e ne costava due.** La selezione per
selettore deve guardare l'albero *risolto*, perché il prototipo di solito non sta
nel piano: lo dichiara il componente attraverso `children`. La prima versione
risolveva due volte — una per scegliere, una per materializzare — e si vedeva:

| Caso | due risoluzioni | una risoluzione |
| --- | ---: | ---: |
| ruote 6 | 1,87 ms | **1,19 ms** |
| braccia 6, detail 2 | 9,47 ms | **5,14 ms** |

Passare l'albero già risolto da `_discover` a `_materialize_path` è una riga di
plumbing e toglie il 40%. Non è ottimizzazione prematura: è la rimozione di una
chiamata duplicata introdotta dalla modifica stessa. Il resto — una risoluzione
di esplorazione più la materializzazione — è il pavimento: senza risolvere non
c'è niente da selezionare.

Resta nell'ordine dei millisecondi, che era il criterio.

---

## 5. Test

**56 test nuovi** in `tests/test_structural_identity.py`; suite completa
**1343 passed** (erano 1287).

| Area | Test |
| --- | --- |
| prototipi per selettore | 17 — nessun percorso nelle tre extension, nessun nome di nodo nelle regole, 6 ruote sotto 4 radici, 4/6/8 ruote, 2/4/6 braccia, catena anatomica per esteso, code, determinismo, testa del gruppo ripetuto, ruoli non correlati intatti, percorso letterale ancora valido, `on` come ambito |
| rename invariance | 5 — quattro combinazioni piano/trait/detail più le identità |
| identità stabile | 6 — derivata e non scritta dal piano, indifferente a parametri ed effetti, sopravvive a uno swap, cambia con il requisito, cloni distinti, riconoscimento di un nodo già creato, contratto dell'attacco del clone |
| provenienza dei cloni | 2 — origine/prototipo/indice, e una voce inventata che non entra |
| serializzazione | 4 — round-trip via `from_dict` **e** via `validate_plan`, progetto `.my3d` vero, progetto anteriore a V3 |
| trait sconosciuti | 11 — radice salva, structural trait salvo, resolver, 7 casi che restano fatali, trait ambiguo, visibilità in `skipped()` |
| composizione cross-plugin | 3 — chimera umanoide + testa di rana + 4 braccia, selettore che attraversa i plugin, regola di terze parti senza percorso |

Il test che vale più degli altri è `test_structural_result_is_invariant_to_planner_node_ids`:
finché passa, un prototipo legato a un percorso letterale non può rientrare senza
farlo cadere.

### 5.1 Il cambio di contratto, dichiarato

`tests/test_traits.py` pretendeva, dal tempo in cui i trait sono stati scritti:

```python
graph, report = validate_plan(bad, catalog)
assert graph is None
assert "TRAIT_NOT_FOUND" in report.codes()
```

Adesso pretende il contrario:

```python
assert graph is not None, report.describe()
assert "UNKNOWN_TRAIT_SKIPPED" in report.codes()
assert report.ok                       # avviso, non errore
assert graph.traits == []              # ignorato, non inventato
```

**Perché il vecchio contratto era incompatibile con la robustezza del planner.**
Un piano è scritto da un modello linguistico, e un modello linguistico inventa
campi facoltativi: `instance_count` al posto di un trait installato. Il vecchio
contratto diceva che un campo facoltativo inventato vale quanto una radice
inesistente, e non è vero — una radice inesistente non si può costruire, un trait
inventato sì, ignorandolo. È esattamente il difetto di forma che V2 aveva già
tolto al ramo `concept` (V2-RESULTS §1.4), e il prompt 3 del `PRODUCT-AUDIT`
restituiva zero geometria per quella ragione e per nessun'altra.

Non è stato indebolito nulla: il test ha più asserzioni di prima (quattro invece
di due), e i casi che restano fatali sono coperti da un test parametrico nuovo di
sette righe — compreso quello che la politica poteva mangiarsi per sbaglio, il
trait **ambiguo**. `tests/test_api_freeze.py` è aggiornato in modo additivo, che è
il meccanismo che quel file documenta.

Tre test nuovi hanno fallito scrivendoli, e tutti e tre hanno trovato qualcosa di
vero:

1. il round-trip dell'identità — `to_dict()` perdeva i tag del requisito (§1.5);
2. la chimera cross-plugin — `swap` più `on` aggiunge un nodo *sotto* il nodo
   indirizzato, non lo sostituisce, quindi la prova va scritta con la catena
   esplicita (ed è la forma che `tests/test_scenari.py` usava già);
3. la regola di terze parti — un `Attachment` di livello 2 non si espande a
   detail 1, quindi il prototipo non c'era da scoprire. In V2 il caso passava
   perché il percorso letterale faceva **creare** il nodo da zero.

Il terzo è anche un limite reale, ed è registrato al §9.

---

## 6. Definition of Done

| # | Criterio | Esito |
| --- | --- | --- |
| 1 | suite intera verde | ✅ 1343 passed |
| 2 | i trait strutturali non dipendono dai planner node id | ✅ rename invariance su 4 combinazioni |
| 3 | nessun prototype path letterale nelle tre extension | ✅ verificato da un test che legge il registro |
| 4 | 2/4/6 braccia sull'humanoid anatomico | ✅ con la catena verificata, non il conteggio |
| 5 | 4/6/8 ruote con qualunque nome della radice | ✅ `car` / `jeep` / `jeep1` / `auto_01` |
| 6 | l'identità stabile sopravvive a riscrittura e serializzazione | ✅ round-trip dict e `.my3d` vero |
| 7 | i trait opzionali sconosciuti non distruggono una radice valida | ✅ con `UNKNOWN_TRAIT_SKIPPED` e 7 casi ancora fatali |
| 8 | la composizione cross-plugin continua a funzionare | ✅ 3 test, parti non correlate intatte |
| 9 | nessuna conoscenza di dominio nel core | ✅ i 7 facet leggono dati dichiarati |
| 10 | PRODUCT-AUDIT non peggiora sotto 7/8 | ✅ 7/8 con LLM reale e 0 × 413, 8/8 offline (§8) |

---

## 7. Regressioni

Nessuna rossa. Due cose da dire comunque.

1. **`to_dict()` esporta un campo in più** (`at.tags`) e, quando c'è stata una
   riscrittura, `structural_provenance`. I progetti anteriori a V3 si aprono
   senza differenze — c'è un test — e i piani scritti prima restano validi: i
   tag erano già dichiarati dallo schema sotto `at`, semplicemente non venivano
   scritti. Un piano riaperto adesso conserva la differenza fra una ruota davanti
   e una dietro, che prima perdeva.
2. **La riscrittura strutturale costa una risoluzione in più** rispetto a V2,
   perché la selezione per selettore deve guardare l'albero risolto. 1,2–5,1 ms
   contro una pipeline locale di 6–13 ms. Era il prezzo della milestone e sta nel
   budget che la milestone dichiarava.

---

## 8. Gli 8 prompt del PRODUCT-AUDIT

### 8.1 Offline (MockPlanner), 8/8 e identico a V2

| # | Prompt | V2 | V3 | Radice scelta |
| --- | --- | ---: | ---: | --- |
| 1 | volpe | 412 | 412 | `fox_stylized:fox` |
| 2 | umanoide | 264 | 264 | `humanoid_anatomical:head` |
| 3 | robot 4 braccia | 32 | 32 | `architecture:house` |
| 4 | jeep 6 ruote | 228 | 228 | `vehicle_stylized:car` |
| 5 | pesce+umano | 414 | 414 | `humanoid_anatomical:body` |
| 6 | casa | 32 | 32 | `architecture:house` |
| 7 | drago | 82 | 82 | `creature:dragon_head` |
| 8 | albero | 50 | 50 | `fantasy:wing` |

Triangolo per triangolo lo stesso risultato: V3 non cambia come si sceglie, solo
cosa si può fare con ciò che è stato scelto. Il 3 e l'8 restano semanticamente
sbagliati per la ragione di V2 — il planner locale ragiona per parole — e nessuno
dei due passa dai trait strutturali, perché il `MockPlanner` non ne scrive.

### 8.2 Con LLM reale

Un giro, 14 ottobre 2026, catena predefinita (`groq` primario).

| # | Prompt | V2 | V3 | provider | failover |
| --- | --- | --- | --- | --- | ---: |
| 1 | volpe | ✅ 412, 2,2 s | ✅ 412, 3,3 s | groq | 0 |
| 2 | umanoide | ✅ 80, 20,8 s | ✅ 20, 61,4 s | nvidia_nim | 4 |
| 3 | robot 4 braccia | ❌ 0 | ✅ **412**, 3,2 s | groq | 0 |
| 4 | jeep 6 ruote | ✅ 228, 42,0 s | ✅ 228, **19,3 s** | cloudflare | 3 |
| 5 | pesce+umano | ✅ 198, 19,7 s | ✅ 118, 131,5 s | groq | 0 |
| 6 | casa | ✅ 32, 30,5 s | ❌ 0 | nvidia_nim | 4 |
| 7 | drago | ✅ 256, 37,5 s | ✅ 256, **6,4 s** | groq | 0 |
| 8 | albero | ✅ 400, 2,6 s | ✅ 400, 20,5 s | cloudflare | 3 |

```text
generazioni riuscite    7/8  →  7/8
413 payload_too_large   0/8  →  0/8
failover totali           6  →  14
mediana                20,3s →  19,9s
```

Il bersaglio della milestone (`>= 7/8`, zero 413) è raggiunto. Il prompt che era
rosso adesso è verde, e ne è diventato rosso un altro: va spiegato, non nascosto.

### 8.3 Il prompt 3, che V3 ha sbloccato

Il modello ha scritto **lo stesso piano di V2**, con lo stesso trait inventato:

```json
{"concept": {"requested": "robot with four arms",
             "archetypes": ["registered:archetype_metadata:quadruped"],
             "adaptations": [{"trait": "instance_count", "value": 4}]},
 "root": {"id": "fox", "ref": "fox_stylized:fox"},
 "traits": [{"trait": "std:body_mass", "value": 0.58},
            {"trait": "instance_count", "value": 4}],
 "structural_traits": []}
```

V2: `trait non disponibile: 'instance_count'` → `graph is None` → 0 triangoli.

V3: il trait viene ignorato, dichiarato, e il resto del piano vive.

```text
diagnostica:  UNKNOWN_TRAIT_SKIPPED  trait sconosciuto, ignorato:
                                     trait = 'instance_count'   [traits[1]]
skipped():    UNKNOWN_TRAIT_SKIPPED: trait sconosciuto, ignorato:
                                     trait = 'instance_count'
risultato:    412 triangoli, 3,2 s, groq, failover 0
```

**I tre generi di successo, distinti come chiedeva la milestone:**

| | esito | perché |
| --- | --- | --- |
| **semantic success** | ✅ | il concetto si risolve, l'id allucinato si normalizza, il trait buono (`std:body_mass`) si applica, quello inventato si dichiara perso |
| **structural success** | ➖ non esercitato | il modello ha messo «quattro braccia» in `adaptations`, e ha lasciato `structural_traits` **vuoto**. La richiesta strutturale non è arrivata al livello strutturale |
| **visual success** | ❌ | è una volpe. La libreria non contiene nessun corpo robot `low_poly` — `robot:head` è dichiarato per lo stile realistico |

Il terzo è un problema di **contenuto**, non di algoritmo, e la milestone lo
diceva: «Non è necessario che produca un robot bello se il catalogo non possiede
un corpo robot low-poly. È necessario che degradi onestamente e che una richiesta
strutturale valida non dipenda dagli id.» Entrambe le condizioni sono
soddisfatte, e sono verificabili separatamente: la richiesta strutturale valida
non dipende più dagli id (§3.1, §3.4), e la degradazione è onesta e leggibile.

Il secondo merita una riga in più, perché è il limite vero che questo giro ha
mostrato: **il planner non sa ancora che «quattro braccia» è uno
`structural_trait`.** V3 ha reso quel livello funzionante e indipendente dai
nomi; convincere il modello a usarlo è un problema di vocabolario e di prompt,
non di meccanismo. È registrato al §9.

### 8.4 Il prompt 6, che è diventato rosso — e non è V3

```text
l'effetto 'fx:bend' non ha un parametro 'params'   [house1]
   perche': un nome inventato sembra una richiesta e non lo e'
   alternative: along, axis
```

Il modello ha annidato i parametri dell'effetto in un oggetto `params` che lo
schema non prevede:

```json
"effects": [{"type": "fx:bend", "amount": 0.2,
             "params": {"along": "Y", "axis": "Z"}}]
```

`fx:bend` **esiste**: non è un elemento sconosciuto, è un parametro inventato su
un elemento noto — la categoria che il §1.7 tiene deliberatamente fatale, in V2
come in V3.

È **dipendente dal fornitore**, e lo si misura rieseguendo solo quel prompt tre
volte:

| giro | provider | esito | codice fatale |
| ---: | --- | --- | --- |
| 1 | groq | ✅ 80 triangoli, 4,4 s | nessuno |
| 2 | cloudflare | ❌ 0 | `EFFECT_PARAM_NOT_FOUND` |
| 3 | cloudflare | ❌ 0 | `EFFECT_PARAM_NOT_FOUND` |

Il primario lo scrive giusto; i modelli di ripiego annidano. Nel giro di V2 la
casa aveva pescato un fornitore che lo scriveva giusto, in questo no — i failover
totali sono saliti da 6 a 14 per i limiti di frequenza dei piani gratuiti
(`groq` 8 000 token al minuto, quota giornaliera di `gemini` esaurita). Come in
V2: **un singolo giro di otto richieste su fornitori free-tier non è un campione
da cui dedurre una regressione**, e qui c'è anche la riprova diretta.

Resta però una cosa vera che questo giro ha fatto emergere, e che non è
varianza: un `params` annidato è un errore di **forma** che si potrebbe srotolare
in modo deterministico, come V2 srotola un prefisso inventato dentro un id
(`normalize_reference`). Non è stato fatto qui perché sarebbe stata la terza
decisione sulla stessa politica dentro una milestone che ne prevedeva una. §9.

---

## 9. Debiti rimasti a V4

* **Il planner non usa `structural_traits`.** V3 ha reso quel livello corretto e
  indipendente dai nomi, e il modello continua a esprimere «quattro braccia»
  come `adaptations`. Serve lavoro sul vocabolario mostrato e sul prompt, non sul
  meccanismo. È il debito con il rapporto valore/costo più alto adesso: il
  livello funziona e nessuno lo chiama.
* **Un parametro annidato su un effetto noto uccide un piano valido** (prompt 6,
  §8.4). La correzione ha la forma di `normalize_reference` di V2: srotolare un
  `params` annidato è deterministico e dichiarabile. Richiede di decidere se la
  politica del §1.7 si estende dagli elementi *sconosciuti* alle forme
  *sbagliate ma interpretabili*, che è una decisione diversa.
* **Gli effetti inventati restano fatali** (§1.7). La forma esatta della modifica
  è la stessa dei trait; tre test esistenti codificano il contratto attuale e
  andrebbero cambiati apposta, non di sfuggita.
* **Creare un prototipo da zero per selettore non è implementato.** Se nessuna
  istanza del pezzo cercato è dichiarata da nessuna parte, la riscrittura si
  ferma con `STRUCTURAL_PROTOTYPE_NOT_FOUND`. In V2 il percorso letterale
  permetteva di **creare** il nodo da zero (`op.component` più `_ensure_parent`),
  e quella strada esiste ancora per le regole che dichiarano un percorso. Per il
  selettore servirebbe scegliere il padre per capability/mount/region, che è
  codice nuovo per un caso che nessuna delle tre extension ha. Il limite è
  visibile in un test: una regola di terze parti su un `Attachment` di livello 2
  va esercitata a `detail_level=2`, perché a detail 1 il prototipo non è ancora
  dichiarato.
* **L'ordinale dell'identità si sposta se si cancella un fratello** con la stessa
  firma (§1.5). Finché non esiste una strada che cancella nodi è un confine, non
  un difetto; con `Session.modify` va affrontato, e la risposta sarà
  probabilmente un contatore persistito — cioè un cambio deliberato del formato
  del piano, non una derivazione.
* **Nove code su una regione pensata per una** restano corrette e brutte (§3.3).
  È qualità di layout, non correttezza strutturale, e si risolve con una regione
  dichiarata meglio dal plugin: contenuto, non motore.
* **`humanoid` storico non dichiara nessuna `LayoutRegion`.** Le braccia in più
  si risolvono sui socket ordinari del resolver. Allineare o deprecare quel
  plugin è la decisione già aperta nel `TODO.md`.
* **I facet 2–4 del tie-breaking sono inerti nella passata stretta.**
  Discriminano solo in quella parziale. Non è un difetto — sono documentati e
  testati — ma significa che oggi la scelta fra candidati che soddisfano tutto il
  selettore si decide su region, profondità e ordine. Con una libreria più grande
  vale rimisurare se basta.

---

## 10. Riprodurre le misure

```bash
python -m pytest -q                                   # 1343 passed
python -m pytest -q tests/test_structural_identity.py # i 56 test di V3
python tools/structural_layout_benchmark.py           # 9 code, 6 braccia, 10 ruote
python audit-images/run_audit.py offline audit-images/v3
python audit-images/run_audit.py llm audit-images/v3  # richiede rete
```

Artefatti in `audit-images/` (non versionati):

```text
v3/metrics_llm.json       gli 8 prompt con LLM reale
v3/metrics_offline.json   gli 8 prompt offline
v3_performance.json       riscrittura, layout, identità
v3/*.png                  3 angolazioni per generazione riuscita
```

Il confronto è con `audit-images/v2/`.
