# V4-RESULTS — Un GLB diventa un componente senza una riga di Python

Milestone V4, chiusa il **14 ottobre 2026**. Branch `v1-semantic-index`,
partenza dichiarata: V3.5 completa, 1381 test verdi.

**Esito: completa.** Un plugin fatto di soli JSON e GLB installa `Component`
normali nel `Registry`; resolver, planner, trait semantici, trait strutturali,
layout, effetti, builder, quality gate, scena ed export non hanno un ramo per
loro. Suite da 1381 a **1506 test verdi** (125 nuovi, zero rossi).

Due cose vanno dette in testa, perche' cambiano la lettura di tutto il resto.

**1. La milestone non partiva da zero.** Lo stato atteso diceva «V4 non e'
ancora iniziata»; il working tree conteneva gia' `app/core/data_plugin.py`
(481 righe), `tests/data_plugin_fixtures.py`, `tests/test_data_plugin_integration.py`
e le modifiche a `registry.py`, `resolver.py`, `resolved.py`, `scene.py`,
`retrieval.py`, `session.py` che le servono. Alla prima esecuzione: **1395
passed, 10 failed**, tutti e dieci nel file di integrazione nuovo. Questa
milestone ha quindi *finito* V4, non l'ha scritta da capo: §10 separa cio' che
c'era da cio' che e' stato aggiunto qui, perche' la differenza conta per chi
legge il diff.

**2. `app/build/` non e' sotto controllo di versione.** `.gitignore:11`
contiene `build/`, che su Windows come su POSIX combacia anche con
`app/build/`: `assembler.py`, `validate.py`, `scene.py`, `exporter.py`,
`optimize.py`, `visual.py` non sono tracciati da nessun commit
(`git check-ignore -v app/build/scene.py` lo dice). Tre di quei file sono
stati modificati per V4 e `git status` non li mostra. **Non e' un difetto di
V4 e non e' stato cambiato qui**, perche' correggere il pattern aggiungerebbe
sei file al repository: e' una decisione, non un dettaglio di pulizia. Fino a
quel momento, l'elenco dei file modificati di qualunque milestone e'
incompleto per costruzione.

---

## 1. Il contratto esistente, verificato prima di scrivere

La milestone chiedeva di dimostrare che `Component → Piece → Builder` basta, e
che Builder e Resolver non richiedono il kernel geometrico. Misurato sul
working tree, non dedotto:

```bash
$ grep -rn "app.geometry" app/build/assembler.py app/core/resolver.py \
      app/core/effect.py app/core/layout.py app/core/structural.py app/core/session.py
$                                        # nessuna riga: nessun import
```

Il builder chiama una funzione e riceve un oggetto:

```python
app/build/assembler.py:332:   pezzo = nodo.component.build(dict(nodo.values), ctx)
```

`Piece` e' l'unica cosa che attraversa quel confine
(`app/build/assembler.py:17`: «solo su `Component`, `Piece`, `Socket`,
`ResolvedNode`, `ResolvedLink`»). Il kernel poligonale
(`app/geometry/kernel.py`) e' importato soltanto dai plugin, mai dal motore:
e' questo che rende un componente mesh-backed una `build` qualunque.

Conseguenza registrata e verificata a fine milestone:

```bash
$ grep -rn "mesh_backed\|is_mesh\|kind == \"data\"" app/build/ app/core/ \
      --include=*.py | grep -v data_plugin.py | grep -v registry.py
$                                        # nessuna riga
```

Le **tre** righe che sanno dell'esistenza dei plugin dati stanno tutte in
`app/core/registry.py` (542, 680, 716), cioe' nel punto che legge i manifest.
Nessuna nel builder, nel resolver, negli effetti, nel layout, nella scena o
nell'export.

### Nessuna gerarchia nuova

Non esistono `MeshComponent`, `ProceduralComponent`, `ImportedComponent`,
`MeshSocket`. Il loader restituisce `Component`, `Piece`, `Socket`,
`ParamSpec`, `Attachment`, `Capability`, `Requirement`, `Mount`,
`LayoutRegion`, `MaterialSpec` — le classi che c'erano. Un test lo dice
leggendo i tipi:

```python
assert type(component) is Component          # tests/test_data_plugin.py
assert type(piece.socket("tip")) is Socket
assert type(regions[0]) is LayoutRegion
```

---

## 2. Il formato dati: la decisione

**Il formato e' la traduzione in JSON dei campi che i modelli esistenti
dichiarano gia', piu' due sole aggiunte.** Nessun campo e' stato inventato per
comodita' di authoring, e nessun modello e' stato duplicato.

| Chiave del JSON | Dove finisce |
| --- | --- |
| `id`, `role`, `tags`, `description`, `styles`, `requires`, `material` | campi omonimi di `Component` |
| `name` | **non** un campo nuovo: `Component.name` resta derivato dall'id, e il nome d'arte entra in `description` (quindi nell'indice semantico) |
| `provides` | `tuple[Capability, ...]` |
| `mounts` | `tuple[Mount, ...]` (`capability`, `socket_id`, `side`, `tags`, `capacity`, `description`, `allow_fallback`) |
| `sockets` | `Socket(name, position, direction, up, radius, capabilities, side, tags)` |
| `params` | `ParamSpec`, **piu'** `transform` (l'aggiunta, §6) |
| `children` | `Attachment` per intero (`level`, `optional`, `on_request`, `replaces`, `replaces_parent`, `on`, `scale_mode`, `insert`, `roll`, `requirement`, `params`, `material`, `tags`) |
| `layout_regions` | `LayoutRegion` |
| `mesh` | **l'aggiunta**: il percorso del GLB, relativo al file componente |
| `frame` | `growth_axis` / `front` / `up`, i tre assi che `app/core/authoring.py` sa gia' verificare |

Le due aggiunte sono `mesh` (senza la quale non c'e' niente da caricare) e
`params[*].transform` (senza la quale un parametro su una mesh fissa non ha un
significato dichiarato, §6). `frame` non e' un'aggiunta al modello: e' la
dichiarazione di cio' che `verify_frame` chiede come argomento.

Niente formato universale di authoring: non c'e' un campo per le texture, per i
LOD, per i gruppi di facce, per lo scheletro, per le varianti. Una chiave non
prevista non viene ignorata, viene **rifiutata** (`DATA_SCHEMA_INVALID`), cosi'
un domani che aggiunge un campo non legge in silenzio i file di oggi al
contrario.

### Il manifest

`plugin.json` guadagna `type: "data"`. Un manifest dati accetta soltanto
`id`, `version`, `type`, `name`, `description`, `author`, `license`,
`homepage`, `tags`, `dependencies`, `capabilities`, `metadata`, `synonyms`,
`components`, `materials`. Le chiavi che nei plugin di codice nominano **file
Python** (`effects`, `styles`, `traits`, `archetypes`, `profiles`, `bindings`,
e `components` quando contiene `.py`) sono rifiutate con `INVALID_MANIFEST`:
non esiste una forma di manifest dati che possa nominare un modulo.

---

## 3. Esempio completo di plugin

Questo e' il plugin dati che i test installano davvero
(`tests/data_plugin_fixtures.py` lo scrive su disco; i GLB sono veri, 976–1008
byte ciascuno, prodotti da `trimesh`, non mock):

```text
mesh_fixture/
├ plugin.json
├ components/
│  ├ knight.json      radice: un cavaliere intero
│  ├ body.json        lo stesso corpo, senza figli, montabile da altri
│  ├ head.json        testa con un figlio ricorsivo
│  └ crest.json       cimiero, livello 3
├ meshes/
│  ├ body.glb
│  ├ head.glb
│  └ crest.glb
└ materials/
   └ material_0.json
```

```json
{
  "id": "mesh_fixture",
  "version": "1.0.0",
  "name": "Mesh fixture",
  "description": "Small low-poly test assets, supplied entirely as data",
  "type": "data",
  "components": ["components/knight.json", "components/body.json",
                 "components/head.json", "components/crest.json"],
  "materials": ["materials/material_0.json"],
  "synonyms": {"knight": ["paladin", "cavaliere"]}
}
```

```json
{
  "id": "mesh_fixture:head",
  "description": "A helmeted head",
  "mesh": "../meshes/head.glb",
  "role": "head",
  "tags": ["head", "humanoid"],
  "provides": ["head_mount"],
  "mounts": [{"capability": "crest_mount", "socket_id": "crest"}],
  "sockets": [
    {"name": "base",  "position": [0, 0, 0],   "direction": [0, -1, 0],
     "up": [0, 0, 1], "radius": 0.1},
    {"name": "crest", "position": [0, 0.4, 0], "direction": [0, 1, 0],
     "up": [0, 0, 1], "radius": 0.1, "capabilities": ["crest_mount"]}
  ],
  "params": {"width": {"default": 1.0, "min": 0.2, "max": 3.0,
                       "transform": "scale_x"}},
  "children": [{"id": "crest", "component": "mesh_fixture:crest", "level": 3,
                "insert": 0.0, "requirement": {"capability": "crest_mount"}}],
  "material": "fixture_metal",
  "requires": ["connected", "watertight"],
  "frame": {"growth_axis": "+Y", "front": "+Z", "up": "+Y"}
}
```

```json
{"name": "fixture_metal", "base_color": "#cf7934",
 "roughness": 0.8, "metallic": 0.15}
```

Nessun file `.py` nella cartella. Nessuna chiave che ne nomini uno.

---

## 4. Sicurezza: un plugin dati non esegue niente

### Non c'e' nessun percorso di import

Un plugin `type: "data"` non passa da `importlib`: `PluginInfo.sources` resta
vuoto e il ramo che importa moduli non viene raggiunto. Tre test lo verificano
dal lato dell'effetto, non della fiducia:

```python
# un .py nella cartella, con un side effect che si vedrebbe
(folder / "boom.py").write_text("raise SystemExit('eseguito')\n")
(folder / "components/boom.py").write_text("import os; os.remove(__file__)\n")
data["metadata"] = {"build": "boom.py", "entry_point": "boom:build"}

registry = load([folder])
assert registry.report.ok                       # il plugin si installa
assert registry.plugin("unit").sources == ()
assert not [n for n in set(sys.modules) - before if "boom" in n]
assert all(not str(p).endswith(".py") for p in letti)   # nessun .py aperto
assert (folder / "components/boom.py").is_file()        # niente e' girato
```

e, separatamente: `sys.path` non viene toccato
(`test_the_loader_imports_no_plugin_module_and_touches_no_sys_path`), e
`components: [..., "components/extra.py"]` fa rifiutare il manifest. Non c'e'
sandbox: non serve, perche' non c'e' esecuzione. Il `metadata` di un manifest
dati e' testo come prima — passa da `sanitize()` prima di raggiungere il
planner, come per qualunque plugin.

### Niente expression

`ParamSpec.derived` e' l'unico posto dove il core valuta un'espressione
(`app/core/params.py:evaluate`, AST whitelist). Il loader **non accetta**
`derived`: `{"derived": "parent.height"}` e' `DATA_SCHEMA_INVALID`. I `params`
di un `children` accettano solo letterali (numero, stringa, booleano, lista di
numeri): `{"n": {"expr": "1+1"}}` e' rifiutato.

### Percorsi confinati

`safe_path(root, relative, base)` risolve una risorsa **dentro** la cartella
del plugin e rifiuta tutto il resto. `..` e' permesso solo finche' il risultato
resta dentro — `../meshes/head.glb` da `components/` e' il caso normale e
funziona; uscire non funziona. I controlli: nessun percorso assoluto POSIX
**ne'** Windows (su qualunque piattaforma, via `PureWindowsPath`), nessun
drive, nessun UNC, nessun `:`, nessun byte nullo, e `resolve()` prima del
confronto, quindi un symlink o una junction che punta fuori viene visto come
fuori. Dieci casi ostili sono parametrizzati:

```text
../../secret.glb   ../../../secret.glb   /etc/passwd   C:/Windows/win.ini
\\server\share\mesh.glb   components/../../../secret.glb
meshes/../../../secret.glb   mesh\x00.glb   file:///secret.glb   ..\..\secret.glb
→ DATA_PATH_UNSAFE
```

Vale anche **dentro** il glTF: un `.gltf` con risorse esterne viene
preletto da un lettore confinato, le sue `uri` passano dallo stesso
`safe_path`, e `trimesh` riceve soltanto byte piu' un dizionario — mai un
resolver di filesystem o di rete (`allow_remote=False`). Un `uri` con schema,
host, query o frammento e' rifiutato; un `data:` non-base64 e' rifiutato.

```python
{"buffers": [{"uri": "../../secret.bin"}]}             → DATA_PATH_UNSAFE
{"buffers": [{"uri": "https://example.invalid/x.bin"}]} → DATA_PATH_UNSAFE
```

### Atomicita'

Un plugin dati con due definizioni, una rotta, non installa l'altra: si
raccoglie tutto prima di registrare qualcosa, e un id non proprio
(`humanoid:head` dichiarato da `unit`) lo fa scartare con
`COMPONENT_ID_MISMATCH` senza intaccare il componente vero.

---

## 5. Mesh loading

Obbligatorio e unico: **GLB e glTF 2.0**. `.obj` passato come `mesh` e'
`DATA_MESH_FORMAT` con il messaggio che nomina cio' che e' supportato. FBX,
USD, Blender non sono stati toccati.

Il GLB viene letto **una volta sola** al caricamento del plugin e copiato a
ogni build, quindi una build non puo' modificare la sorgente di un'altra
(`test_the_source_mesh_is_loaded_once_and_never_mutated_by_a_build`).

Comportamento dichiarato, caso per caso:

| Caso | Esito |
| --- | --- |
| mesh singola | `Piece.mesh` con gli stessi triangoli e gli stessi limiti |
| scena con piu' nodi | ogni primitiva e' **bakeata con la trasformazione del proprio nodo** e concatenata; l'ordine e' quello alfabetico dei nodi, quindi deterministico |
| transform dei nodi | conservate: una scatola traslata di +1 lungo Y resta a 1.0–1.2 |
| geometria non triangolare | `DATA_MESH_INVALID` |
| primitiva vuota | `DATA_MESH_EMPTY` (prima della pipeline, non dopo) |
| scena senza triangoli | `DATA_MESH_EMPTY` |
| file assente | `DATA_FILE_MISSING` |
| header GLB storto, lunghezza incoerente, JSON chunk non valido, `asset.version` != 2.0 | `DATA_MESH_INVALID` |
| vertici NaN/inf | rifiutato al caricamento (`DATA_JSON_INVALID` o `DATA_MESH_INVALID`, dipende da dove il NaN finisce nel file) |

La scelta esplicita su un GLB multi-nodo: **una mesh coerente, senza perdere le
trasformazioni**. Si concatenano vertici e facce con `trimesh.util.append_faces`
e si costruisce un `Trimesh` a mano, invece di usare la concatenazione delle
visual: quella inventa un materiale predefinito quando i pezzi non ne hanno
uno, e un materiale inventato e' esattamente la conoscenza che la libreria non
voleva perdere. Le componenti separate restano separate
(`mesh.body_count == 2`), perche' incollarle sarebbe una correzione magica:
se il componente dichiara `connected`, e' il quality gate a dirlo.

---

## 6. Params: una politica, non una finzione

**Sono ammessi soltanto parametri con un comportamento deterministico
dichiarato, e l'unico vocabolario dichiarabile oggi e' la scala positiva per
asse.** Un parametro dati *deve* dichiarare `transform`, con uno di quattro
valori: `scale_x`, `scale_y`, `scale_z`, `uniform_scale`.

```json
"params": {"width": {"default": 1.0, "min": 0.2, "max": 3.0,
                     "transform": "scale_x"}}
```

Non c'e' `rebuild`, non c'e' `deform`, non c'e' mappatura automatica verso gli
effetti. Un `transform` sconosciuto (`rebuild`, `bend`) e' rifiutato con
`DATA_PARAM_UNSUPPORTED`, e cosi' un parametro **senza** `transform`: fingere
che un `ParamSpec` qualunque di un componente procedurale funzioni su una mesh
importata e' il difetto che la milestone chiedeva di non introdurre, e il modo
di non introdurlo e' rifiutare la dichiarazione, non assorbirla.

Il tipo deve essere `float`, `ratio` o `int` — una scala non ha senso su un
`enum` — e il valore deve essere positivo, dentro `min`/`max`, anche a build
time: `build({"width": -2.0})` solleva invece di specchiare la mesh.

**I socket si scalano con la geometria, e il raggio e' quello del disco.** Un
raggio e' uno scalare, ma rappresenta l'area del disco d'innesto: sotto una
scala affine si usa il raggio del cerchio equivalente, cioe'
`r * sqrt(det(S) * |direction / S|)`. Misurato su un innesto che guarda +X:

| `transform` = 2.0 | mesh | posizione | raggio |
| --- | --- | --- | --- |
| `scale_x` | ×(2,1,1) | ×(2,1,1) | ×1.00 — il disco sta nel piano YZ, e non e' stato scalato |
| `scale_y` | ×(1,2,1) | ×(1,2,1) | ×1.41 |
| `scale_z` | ×(1,1,2) | ×(1,1,2) | ×1.41 |
| `uniform_scale` | ×2 | ×2 | ×2.00 |

Niente proceduralizzazione, niente shape key, niente rig: non sono stati
scritti.

---

## 7. Socket dichiarati nei dati

Un socket e' un `Socket`, con gli stessi concetti e nessun tipo nuovo:
`name`, `position`, `direction`, `up`, `radius`, `capabilities`, `side`,
`tags`. Rifiutati: `direction` o `up` nulli o paralleli
(`DATA_FRAME_INVALID` — un frame degenere non ha un orientamento), un vettore
che non ha tre coordinate, un raggio non positivo, un `side` fuori da
`l/r/center/top/bottom/front/back`, un nome vuoto, due socket con lo stesso
nome.

**Il test piu' importante della milestone**, nelle due direzioni, sullo stesso
assert:

```python
@pytest.mark.parametrize("direction", ["mesh_head", "mesh_body"])
def test_capabilities_mount_mesh_and_procedural_parts_in_both_directions(...):
```

* `humanoid:body` (procedurale) + `mesh_fixture:head` (GLB) su `head_mount`;
* `mesh_fixture:body` (GLB) + `humanoid:head` (procedurale) su `head_mount`.

In entrambi i casi il collegamento e' risolto per **capability** (non per id,
non per percorso), e la verifica e' geometrica: il socket `base` del figlio
coincide in posizione con il socket del padre e guarda nel verso opposto.

```python
assert head.node.link.capability == "head_mount"
assert np.allclose(own.position, socket.position)
assert np.allclose(own.direction, -socket.direction)
```

---

## 8. Convenzione degli assi

Un componente dati puo' dichiarare `frame: {growth_axis, front, up}` e il
loader usa gli helper che esistevano (`ASSI`, `verify_frame` di
`app/core/authoring.py`). La politica e' quella chiesta: **diagnostica chiara,
nessuna correzione**.

Una scatola larga 2.0 lungo X che dichiara di crescere lungo +Y produce
`GROWTH_AXIS_MISMATCH` nel report del build e in
`Piece.metadata["frame_diagnostics"]`, e la geometria **resta quella**:

```python
assert "GROWTH_AXIS_MISMATCH" in report.codes()
assert np.isclose(piece.mesh.extents[0], 2.0)        # nessuna rotazione magica
assert piece.metadata["frame"]["growth_axis"] == "+Y"
```

Un asse non nominabile (`up`, `+W`) o un `front` parallelo a `up` sono
rifiutati al caricamento (`DATA_FRAME_INVALID`). Nessun sistema di conversione
di coordinate e' stato scritto.

---

## 9. Children ricorsivi e `detail_level`

I `children` di un componente dati sono `Attachment` normali, e li governa il
meccanismo che c'era:

```text
detail 1 → {subject}
detail 2 → {subject, subject/head}
detail 3 → {subject, subject/head, subject/head/crest}
```

con 12 triangoli per nodo, quindi 12 / 24 / 36. A livello 3 il nipote e'
figlio del figlio (`resolved.node("subject/head/crest").link.parent ==
"subject/head"`), cioe' la ricorsione e' vera e non appiattita. La gerarchia e'
scritta a mano nei fixture, come chiesto: nessuna UI la costruisce.

Ogni build riceve una **copia** dei propri `Attachment`
(`copy.deepcopy`), quindi una riscrittura strutturale non puo' sporcare la
dichiarazione del componente per le build successive.

---

## 10. Materiali

La politica, nell'ordine:

```text
1. materiale nominato nei dati del componente      → vince
2. nessun nome, ma la mesh porta colori             → i colori si conservano
3. ne' l'uno ne' l'altro                            → materiale di ripiego
```

Implementata dove si decide il materiale di un nodo
(`app/build/assembler.py:295`: `nodo.material or pezzo.material or
nodo.component.material`) e dove la scena legge il colore
(`app/build/scene.py:_materiale_visivo` + `SceneNode.preserve_visual`): un
`SceneNode` che conserva i colori importati esporta la mesh **con i suoi**,
mentre `material` resta la tinta rappresentativa per le viste a tinta unica.
Nessun sistema PBR nuovo: `MaterialSpec` ha gli stessi cinque campi di prima.

Il bug storico del registry non e' stato reintrodotto, ed e' coperto da un
assert:

```python
result = session.build(plan_for())
assert result.scene().by_id("subject").material.base_color == "#cf7934"
```

`GenerationResult.scene()` senza argomenti non torna piu' grigia: il risultato
conserva la libreria che ha costruito i suoi materiali
(`session.py:_costruisci` → `risultato._registry`), quindi `scene()` risolve i
nomi anche chiamata fuori dalla `Session`. Un colore hex storto in un file
materiale resta la degradazione deliberata di `MaterialSpec` (diventa grigio);
`roughness: 5.0` e `roughness: "molto"` sono rifiutati.

---

## 11. Validation

Nessun secondo validatore. I componenti dati passano da
`app/build/validate.py` come tutti, e la politica deriva dagli stessi
`requires`: `watertight`, `manifold`, `connected`, `no_degenerate`, `faceted`.

Il punto che la milestone chiedeva di non sbagliare: **una mesh d'artista
legittima non viene rifiutata per un requisito che non ha dichiarato**. Lo
stesso GLB bucato, due componenti:

```python
relaxed = component_of(tmp_path, geometry=open_box)                     # requires = {}
strict  = component_of(tmp_path, geometry=open_box, requires=["watertight"])
```

Il primo si costruisce, il secondo prende `GEOMETRY_REQUIREMENT` con il
`why` che dice «dichiarato in Component.requires». Vuoto, NaN/inf e
degenerazioni totali restano rifiutati **al caricamento**, perche' una mesh che
non si puo' misurare non e' una scelta artistica. Il budget di triangoli e la
conformita' di stile sono quelli di prima, e il cavaliere dei fixture dichiara
`connected` e `watertight` e li rispetta.

---

## 12. Registry e discovery

`Registry.load_directory` scopre le due specie nello stesso giro, e la
differenza vive in `PluginInfo`: `kind` (`"code"` / `"data"`),
`data_components`, `data_materials`, `fingerprint`. Il resto del sistema
chiede componenti, non specie.

Retrocompatibilita': i 22 plugin esistenti non sono stati convertiti e non
sono stati toccati in questa milestone (le modifiche ai tre `multi_*_extension`
nel working tree sono di V3.5). Un manifest senza `type` e' `code`, come prima.

`fingerprint` e' lo `sha256` dei **contenuti referenziati** — manifest, JSON dei
componenti, JSON dei materiali, GLB e risorse esterne — con i percorsi relativi
alla cartella del plugin, quindi copiare un plugin altrove non cambia la sua
identita' di contenuto, mentre cambiare un GLB la cambia.

---

## 13. Retrieval semantico

Un componente dati entra nell'indice di V1 da solo, con `document_for()` che
legge i metadati dichiarati — id, nome, descrizione, ruolo, tag, `provides`,
le capability dei `mounts` e i loro tag, stili, nome e tag del plugin — e con i
`synonyms` del manifest che alimentano il thesaurus dal lato della **query**
(`Registry.synonyms()`), non del documento. Nessuno dei due percorsi ha avuto
bisogno di una riga per i plugin dati. Misurato:

```text
prima  : "mesh_fixture:knight" in search("knight")   → False
load_plugin(folder)
         index.is_current(registry)                   → False   (invalidato)
dopo   : search("knight")                             → ['mesh_fixture:knight']
         session.shortlist("knight").ids              → ['mesh_fixture:knight',
                                                         'accessories:helmet', ...]
         vocabulary(prompt="knight").components       → contiene mesh_fixture:knight
```

Nessun binding, nessun archetipo, nessuna riga di codice: **installare
contenuto aumenta la conoscenza di 3DGen**. L'impronta di contenuto entra in
`stamp_for` / `registry_signature`, quindi anche una modifica a versione ferma
invalida l'indice (tre casi testati: versione, descrizione, GLB).

Rimuovere il plugin fa il percorso inverso, e la verifica e' simmetrica:
l'indice si invalida, il componente esce dai risultati, **e il ponte fra le
parole esce con lui** (`"knight" not in registry.synonyms()`), quindi
`paladin` non trova piu' nulla.

---

## 14. Degradazione semantica

Fixture: `paladin` non e' installato; `mesh_fixture:knight` lo e', e il
manifest del plugin dichiara `synonyms: {"knight": ["paladin", "cavaliere"]}`.
Nessuna modifica al `ConceptResolver`, nessun binding, nessun archetipo:

```text
richiesto: 'paladin'
implementazione esatta: non installata
scelto per approssimazione: mesh_fixture:knight
tipo di corrispondenza: semantic subject proxy      (MATCH_SUBJECT, confidenza 0.32)
```

e il piano `{"concept": {"requested": "paladin"}}` costruisce davvero il
cavaliere mesh-backed, con `degradation()` non vuota. La scala di V2 arriva al
componente importato per la via normale — rung 4, `subject_capabilities()` —
perche' il GLB fornisce una capability che nessuno accetta, cioe' e' un
soggetto intero. Il test lo afferma dopo aver verificato che non esistono
binding ne' archetipi che nominino il plugin.

---

## 15. Composizione mista

Oltre al test a due direzioni del §7:

* `mesh_fixture:knight` con figli dati, a tre livelli di dettaglio (§9);
* `humanoid:body` + `mesh_fixture:head` esportato in quattro formati (§18);
* `mesh_vehicle:body` (GLB) con ruote **procedurali**
  (`vehicle_stylized:wheel`) e il trait strutturale installato (§16).

In nessuno di questi casi il piano dice che un componente e' importato: dice
`ref`, `at`, `on`, come sempre.

---

## 16. Trait strutturale su un prototipo mesh-backed

La prova che V3 non distingue le due specie: un corpo veicolo mesh-backed, due
ruote procedurali dichiarate come `children` nei dati, due `layout_regions`
dichiarate nei dati, e il trait installato `vehicle:wheel_count` di
`multi_wheel_extension`.

```python
plan["structural_traits"] = [{"trait": "vehicle:wheel_count", "value": count,
                              "mode": "exact"}]
```

| `wheel_count` | ruote costruite | posizioni distinte | `layout.placements` |
| --- | --- | --- | --- |
| 4 | 4 | 4 | 4 |
| 6 | 6 | 6 | 6 |

Il prototipo e' **selezionato** dal `target` della regola (`role: wheel`), non
indirizzato: la radice si chiama `subject` e il trait non la nomina. Le ruote
clonate sono `vehicle_stylized:wheel` — un componente di un **altro** plugin,
procedurale — e il layout le distribuisce nelle regioni dichiarate in JSON.
`result.structural.applied` non e' vuoto, cioe' la richiesta e' stata
applicata, non saltata.

---

## 17. Effetti

`fx:bend` con `scope: "part"` su un corpo mesh-backed, nessun percorso
speciale, stessa `EffectPipeline`. La verifica e' quella che conta — vertici e
socket deformati **dalla stessa mappa**:

```python
index = np.flatnonzero(np.all(np.isclose(before.mesh.vertices,
                                         before.sockets["corner"].position), axis=1))
assert len(index) == 1
assert np.allclose(after.mesh.vertices[index[0]], after.sockets["corner"].position)
```

Il socket `corner` e' stato messo nel fixture esattamente su un vertice della
scatola: se geometria e innesti si desincronizzassero, quel vertice e quel
socket si separerebbero. Anche il `direction` del socket `head` cambia, e una
build successiva dalla sorgente torna identica (nessuna deformazione
accumulata sulla mesh caricata una volta).

---

## 18. Export

Scena mista (`humanoid:body` procedurale + `mesh_fixture:head` da GLB),
esportata con l'`exporter` esistente, senza nuovi esportatori:

| formato | esito |
| --- | --- |
| `.glb` | triangoli conservati, limiti identici alla scena (`atol=1e-6`) |
| `.obj` | idem |
| `.stl` | idem |
| `.ply` | idem |

```python
loaded = trimesh.load(destination, force="scene")
assert sum(len(m.faces) for m in loaded.geometry.values()) == result.triangles
assert np.allclose(loaded.bounds, result.scene().bounds(), atol=1e-6)
```

---

## 19. Progetto `.my3d`

Il formato continua a salvare piani, identita' e versioni dei plugin, **e non
la mesh**:

```python
with zipfile.ZipFile(saved) as archive:
    assert not any(n.endswith((".glb", ".gltf", ".bin")) for n in archive.namelist())
    assert json.loads(archive.read("project.json"))["plugins"]["mesh_fixture"] == "1.0.0"
```

Alla riapertura con il plugin installato, il modello e' lo **stesso**: stesso
piano serializzato, stesso conteggio di triangoli, stessi vertici e stesse
facce, e i materiali del componente dati di nuovo al loro posto. Nessun GLB
incorporato.

Questo round-trip ha trovato un difetto **preesistente** del formato, non di
V4: `CompositionGraph.to_dict()` non scriveva `insert` e `roll`, che lo schema
del piano accetta e che `validate_plan` legge da sempre. Un piano con
`insert: 0.0` riaperto tornava a 0.35, cioe' la testa entrava nel torso di
0.035 unita' e la geometria cambiava **senza che niente lo dicesse** — con
`current_plan.to_dict()` identico prima e dopo, perche' il campo mancava in
entrambi. Ora si scrivono quando non sono il valore predefinito, e si rileggono
(`graph.py`): un file salvato prima non ha quelle chiavi e si rilegge
esattamente come prima.

Plugin mancante e plugin cambiato riusano i meccanismi diagnostici, con una
sola aggiunta simmetrica a `missing_plugins`:

| caso | dove si legge |
| --- | --- |
| plugin assente | `session.missing_plugins` → `["mesh_fixture@1.0.0"]`, le altre versioni si aprono |
| versione cambiata | `PLUGIN_VERSION_CHANGED` fra le `result.diagnostics`, e `session.changed_plugins` |
| contenuto cambiato a versione ferma | `PLUGIN_CONTENT_CHANGED`, dall'impronta del §12 |

`ProjectInfo.fingerprints` e' additivo: un progetto salvato prima non lo ha, e
`changed_plugins()` confronta soltanto cio' che trova. Le diagnostiche stanno
sul **risultato ricostruito**, non accanto ad esso, perche' chi riapre un
progetto legge `result.diagnostics` come dopo una generazione qualunque.

---

## 20. Prestazioni

`python tools/data_plugin_benchmark.py 7`, stessa macchina, nessuna rete,
mediana di 7 ripetizioni (plugin dati scritto in una cartella temporanea dalle
fixture dei test):

| passo | mediana | peggiore |
| --- | --- | --- |
| scoperta: solo codice (22 plugin, 97 componenti) | 30.94 ms | 32.12 ms |
| scoperta: codice + dati (23 plugin, 101 componenti) | 54.41 ms | 57.62 ms |
| scoperta: il solo plugin dati (4 componenti, 3 GLB) | 21.51 ms | 21.94 ms |
| caricamento GLB: 1 componente | 2.78 ms | 3.33 ms |
| indice semantico: 97 componenti | 15.21 ms | 15.23 ms |
| indice semantico: 101 (+ dati) | 15.05 ms | 15.54 ms |

| composizione (radice + figlio) | build del figlio | totale locale | triangoli |
| --- | --- | --- | --- |
| procedurale (`humanoid:body` + `humanoid:head`) | 3.47 ms | 9.23 ms | 160 |
| mesh-backed (`mesh_fixture:body` + `:head`) | 0.26 ms | 5.14 ms | 24 |
| misto (`humanoid:body` + `mesh_fixture:head`) | 0.25 ms | 7.55 ms | 92 |

Lettura onesta dei numeri:

* **La build di un componente mesh-backed e' piu' economica** (0.26 ms contro
  3.47 ms): una copia piu' una scala contro una generazione di geometria. Non
  era il punto, ma e' il numero.
* **Il costo si sposta sull'installazione**: ~5.4 ms per componente dati contro
  ~1.4 ms per plugin di codice, e la meta' di quel tempo e' l'impronta
  `sha256`, che si paga una volta per registry e che e' cio' che rende
  diagnosticabile un GLB cambiato. Con quattro componenti il registry passa da
  31 a 54 ms: visibile, non sproporzionato. Con una libreria grande di plugin
  dati andra' riverificato, ed e' scritto fra i debiti.
* **L'indice semantico non si accorge della differenza** (15.2 → 15.1 ms, cioe'
  rumore): i documenti si costruiscono dai metadati dichiarati, non dalla
  geometria.
* Il totale locale non e' confrontabile fra le righe (sono modelli diversi, con
  conteggi di triangoli diversi): serve a dire che nessuno dei tre e' fuori
  scala rispetto ai 6–13 ms della linea di base.

---

## 21. Test

**1506 passed** (`python -m pytest -q`), da 1381. I 125 nuovi:

| file | quanti | che cosa |
| --- | --- | --- |
| `tests/test_data_plugin.py` | 101 | il confine: manifest, schema JSON, confinamento dei percorsi, caricamento GLB, socket, frame, params, materiali, children, layout region, politica di validazione, zero esecuzione di Python |
| `tests/test_data_plugin_integration.py` | 24 | la pipeline: GLB → Registry → Component → Piece → Builder → Scene → Export, composizione mista nelle due direzioni, detail_level, retrieval, degradazione, trait strutturale, effetto, `.my3d`, rimozione, cambio di versione/contenuto |

I 22 punti richiesti dalla milestone, e dove sono:

| # | richiesta | test |
| --- | --- | --- |
| 1 | manifest data-only valido | `test_a_data_manifest_installs_components_without_declaring_python` |
| 2 | JSON component valido | `test_a_valid_definition_becomes_the_existing_models` (+ 11 casi malformati) |
| 3 | path traversal bloccato | `test_path_traversal_and_absolute_paths_are_blocked` (10 casi), `..._gltf_uri_cannot_leave_the_plugin_or_reach_the_network` |
| 4 | GLB missing | `test_a_missing_mesh_file_is_reported_as_missing` |
| 5 | GLB invalido | `test_an_invalid_glb_is_refused_without_a_traceback` (4 casi), `..._unsupported_mesh_format_names_what_is_supported` |
| 6 | mesh singola | `test_a_single_mesh_keeps_its_triangles_and_bounds` |
| 7 | GLB multi-node | `test_a_multi_node_glb_merges_every_primitive_with_its_transform` |
| 8 | socket da dati | `test_sockets_are_ordinary_sockets_with_the_declared_frame` (+ 6 casi rifiutati) |
| 9 | params trasformativi | `test_a_transform_parameter_scales_mesh_and_sockets_together` (4 casi) + 9 rifiuti |
| 10 | materials | quattro test di politica + `test_a_malformed_material_is_refused` |
| 11 | children/detail_level | `test_recursive_data_children_use_existing_attachment_detail_levels` (3 livelli), `test_children_are_ordinary_attachments_with_their_own_detail_level` |
| 12 | mesh + procedural composition | `test_capabilities_mount_mesh_and_procedural_parts_in_both_directions` (2 direzioni) |
| 13 | semantic retrieval | `test_installing_data_adds_semantic_knowledge_and_rebuilds_the_session_index` |
| 14 | semantic degradation | `test_unknown_paladin_degrades_to_data_knight_without_binding_or_archetype` |
| 15 | structural trait | `test_existing_wheel_count_and_layout_work_on_a_data_body` (4 e 6) |
| 16 | effect | `test_existing_bend_deforms_data_vertices_and_sockets_by_the_same_map` |
| 17 | validation | `test_requires_is_the_only_policy_for_imported_geometry`, `..._non_finite_vertices_are_refused_before_the_pipeline_sees_them` |
| 18 | export | `test_mixed_scene_exports_through_existing_exporters` (4 formati) |
| 19 | `.my3d` round-trip | `test_my3d_round_trip_regenerates_mixed_geometry_without_embedding_mesh` |
| 20 | plugin removal | `test_removing_a_data_plugin_invalidates_retrieval_and_loses_its_synonyms` |
| 21 | version/fingerprint change | `test_data_version_or_content_change_invalidates_semantic_fingerprint` (3 casi), `test_my3d_reports_data_version_or_asset_change` (2 casi) |
| 22 | zero Python execution | `test_a_data_plugin_never_imports_or_executes_its_own_python`, `..._touches_no_sys_path`, `..._cannot_declare_python_sources_at_all` |

### La fixture e' un GLB vero

`tests/data_plugin_fixtures.py` scrive cartelle che contengono **soltanto** JSON
e GLB, esportati da `trimesh` su disco (976–1008 byte), e i test le caricano
dal filesystem attraverso `Registry.load_directory`. `trimesh.load` non e' mai
mockato: `(folder / "meshes/head.glb").read_bytes()[:4] == b"glTF"` e' un
assert del primo test. Il modulo delle fixture e' strumento di test, non codice
di plugin: le cartelle che produce si caricano senza di esso.

---

## 22. File modificati

Quello che **c'era gia'** nel working tree all'inizio della milestone
(riportato per leggibilita' del diff, non rivendicato qui):

| File | Che cosa |
| --- | --- |
| `app/core/data_plugin.py` | **nuovo**, 481 righe: il loader dei plugin dati |
| `app/core/registry.py` | `kind`, `data_components`, `data_materials`, `fingerprint`; il ramo dati di `_carica` e `_read_manifest` |
| `app/core/resolved.py`, `app/core/resolver.py` | `ResolvedNode.material`: l'attacco puo' sostituire il materiale anche quando nasce dall'espansione |
| `app/core/scene.py`, `app/build/scene.py` | `SceneNode.preserve_visual`, `_materiale_visivo` |
| `app/core/session.py` | `risultato._registry`, cosi' `scene()` senza argomenti non perde i materiali |
| `app/core/planner/retrieval.py` | l'impronta di contenuto in `stamp_for` e `registry_signature` |
| `app/build/assembler.py` | la catena `nodo.material or pezzo.material or component.material` |
| `tests/data_plugin_fixtures.py` | **nuovo**: i due plugin dati di test |
| `tests/test_data_plugin_integration.py` | **nuovo**, 24 test (10 rossi all'inizio) |

Quello che **questa milestone** ha aggiunto o cambiato:

| File | Che cosa |
| --- | --- |
| `tests/test_data_plugin.py` | **nuovo**, 101 test: il confine del loader |
| `tools/data_plugin_benchmark.py` | **nuovo**: le misure del §20 |
| `app/core/data_plugin.py` | `_region` + `layout_regions` fra le chiavi del componente (con id unici e ancoraggio esistente); `DATA_JSON_INVALID` per un numero JSON non finito |
| `app/core/graph.py` | `insert` e `roll` nella serializzazione e nella rilettura del piano (§19) |
| `app/core/project.py` | `ProjectInfo.fingerprints`, `changed_plugins()`, `fingerprints_of()`, `PLUGIN_VERSION_CHANGED` / `PLUGIN_CONTENT_CHANGED` sui risultati ricostruiti |
| `app/core/session.py` | `Session.changed_plugins` |
| `tests/data_plugin_fixtures.py` | le regioni di layout del veicolo rese costruibili (span 2.18, `min_spacing` 0.06, `capacity` 8, `allow_scale_to_fit`) |
| `tests/test_data_plugin_integration.py` | quattro usi sbagliati dell'API corretti: gli id dei nodi espansi sono percorsi (`subject/head`), il padre si legge da `link.parent`, la radice da `resolved.root` |
| `tests/test_api_freeze.py` | `changed_plugins` fra i campi congelati di `Session` (additivo, §23) |
| `V4-RESULTS.md`, `PROJECT-INDEX.md`, `TODO.md` | questo documento e i due indici |

Nessun file nuovo nel core oltre a quelli elencati. Nessun tipo nuovo in tutta
la milestone.

---

## 23. Regressioni e contratti cambiati

**Zero test rossi**, e nessun test esistente indebolito. Tre cambiamenti
dichiarati, tutti additivi:

1. **`Session.changed_plugins`** e' un campo nuovo, quindi
   `tests/test_api_freeze.py` e' stato aggiornato: quella riga di diff **e'** la
   decisione, come dice il file stesso.
2. **`CompositionGraph.to_dict()` ora scrive `insert` e `roll`** quando non sono
   i valori predefiniti. Non e' una scelta estetica: senza, il round-trip di un
   progetto cambia la geometria in silenzio (§19). Un `.my3d` salvato prima non
   ha quelle chiavi, e `from_dict` usa gli stessi valori predefiniti di sempre.
3. **`ProjectInfo` ha un campo in piu'** (`fingerprints`). `migrate()` filtra sui
   campi noti, quindi i progetti vecchi si leggono, e `FORMAT_VERSION` resta 2
   perche' nessun file diventa illeggibile in nessuna delle due direzioni.

I dieci test rossi iniziali erano del file di integrazione, non del motore:
sei venivano da usi sbagliati dell'API nel test stesso (id dei nodi, `parent`,
`root_id`, `changed_plugins`), due da numeri di layout non costruibili nella
fixture, e due da difetti veri — `layout_regions` che il loader non leggeva e
`insert` che la serializzazione perdeva.

### Difetti preesistenti trovati, e non corretti qui

* **`app/build/` e' git-ignored** (`.gitignore:11`, `build/`). Cambiarlo
  aggiunge sei file al repository: e' una decisione del proprietario, non una
  pulizia.
* **Un figlio dichiarato nel piano scompare in silenzio a `detail_level 1`.**
  `validate_plan` gli da' `level 2` per default e `wanted_at(1)` e' falso:
  niente nodo, niente diagnostica, `ok=True`. Si vede subito scrivendo un piano
  con `detail_level: 1` e un figlio senza `level`. E' la stessa famiglia del
  difetto che V3.5 ha chiuso per i trait: una richiesta persa senza referto.
* **`MATERIAL_REDECLARED` sui plugin installati**: `tree_stylized` ridichiara
  `wood` con un colore diverso e vince la prima dichiarazione. E' un avviso
  (`report.ok` resta vero), ed e' rumore in ogni report del registry.

---

## 24. Definition of Done

| # | Criterio | Esito |
| --- | --- | --- |
| 1 | suite completa verde | ✅ 1506 passed (erano 1381) |
| 2 | un plugin fornisce un Component GLB senza Python | ✅ `mesh_fixture`: solo JSON e GLB, `sources == ()` |
| 3 | Registry/Resolver/Builder senza percorso speciale a valle | ✅ zero riscontri di branching fuori da loader e registry (§1) |
| 4 | il plugin dati non esegue codice | ✅ tre test, verificati sugli effetti: nessun modulo importato, `sys.path` intatto, i `.py` restano sul disco |
| 5 | path traversal bloccato | ✅ 10 casi + le `uri` dentro il glTF, `DATA_PATH_UNSAFE` |
| 6 | socket e capability fra procedurale e mesh-backed | ✅ nelle due direzioni, verificate geometricamente (§7) |
| 7 | detail_level/children | ✅ 1/2/3 → 12/24/36 triangoli, nipote figlio del figlio |
| 8 | il SemanticIndex lo scopre da solo | ✅ prima assente, dopo primo in `shortlist("knight")` |
| 9 | la degradazione lo sceglie senza binding manuale | ✅ `paladin` → `mesh_fixture:knight`, `MATCH_SUBJECT`, nessun binding ne' archetipo |
| 10 | trait strutturali ed effetti anche su di esso | ✅ 4/6 ruote procedurali su un corpo GLB; `fx:bend` con vertici e socket sulla stessa mappa |
| 11 | export misto | ✅ glb, obj, stl, ply |
| 12 | `.my3d` rigenera tramite il plugin | ✅ stessi vertici e facce, nessun GLB nell'archivio |
| 13 | nessuna conoscenza di dominio nel core | ✅ il formato nomina capability, ruoli e tag; «knight», «paladin» e «cavaliere» stanno nel manifest del plugin |
| 14 | nessuna UI di authoring | ✅ nessun file di UI toccato; le gerarchie sono scritte a mano nei fixture |

Fuori scope e non iniziati, come chiesto: UI di importazione, selezione di
facce, creazione visuale di socket, auto-segmentation, riconoscimento di parti,
rig automatico, proceduralizzazione, `Session.modify`, marketplace, plugin
remoti, sandbox Python, FBX/USD/Blend, categorie artistiche nuove.

---

## 25. Debiti verso V5 e l'authoring

* **Il vocabolario dei parametri e' una scala e nient'altro.** `scale_*` e
  `uniform_scale` coprono «piu' grande» e «piu' largo», non «piu' curvo». La
  strada dichiarata e' mappare un parametro su un **effetto installato** (lo
  stesso meccanismo che `TraitRule` usa per i parametri pubblici), non
  inventare una seconda deformazione nel loader. Finche' non esiste, un
  componente dati non ha un knob semantico proprio.
* **Un trait semantico non raggiunge un componente dati** se non attraverso
  `role`, `tags` e `param_roles`: i `semantic_role` si possono dichiarare, ma il
  parametro che toccano e' sempre una scala. «testa enorme» su una mesh
  importata e' V5 (§5 di `VISION-GAP.md`).
* **Il `fingerprint` si ricalcola a ogni caricamento** leggendo tutti i file
  referenziati: ~2.7 ms per GLB. Con centinaia di componenti dati va messo in
  cache (mtime + dimensione come chiave), ed e' il primo numero che peggiora.
* **Nessuna persistenza dell'indice** (debito di V1, ora piu' rilevante): una
  libreria d'artista grande e' esattamente il caso in cui i 15 ms diventano
  significativi.
* **Il GLB non e' incorporato in `.my3d`**, per scelta di questa milestone: un
  progetto resta rigenerabile solo finche' il plugin e' installato, e
  `changed_plugins` dice quando non lo e' piu' nello stesso stato. Incorporarlo
  e' una decisione di formato, non un'ottimizzazione.
* **Nessuna conversione di coordinate**: `frame` diagnostica, non corregge. Il
  drago in piedi sulla coda di `VISION-GAP.md` resta in piedi sulla coda, e
  promuovere la convenzione a contratto verificato dal resolver e' V5.
* **I materiali del glTF arrivano come colore, non come materiale.** Un
  `baseColorFactor`, i colori per vertice o una texture diventano la tinta di un
  `MaterialSpec` «imported» piu' i colori conservati sulla mesh. Texture, UV e
  PBR veri non sono stati toccati.
* **Un solo `mesh` per componente**: niente LOD dichiarati, niente varianti.
  `app/build/optimize.py` sa fare i LOD per decimazione e nessuno glieli chiede
  dai dati.
* **I debiti di V3 e V3.5 restano tutti**: il filtro di rilevanza dei trait
  strutturali guarda la rosa e non i figli dichiarati, il retrieval classifica
  le parti sopra gli interi, il `MockPlanner` non scrive trait strutturali,
  `fx:bend` con `scope: "model"` si perde, creare un prototipo da zero per
  selettore non c'e', l'ordinale dell'identita' si sposta cancellando un
  fratello.

---

## 26. Riprodurre le misure

```bash
python -m pytest -q                                      # 1506 passed
python -m pytest -q tests/test_data_plugin.py            # i 101 del confine
python -m pytest -q tests/test_data_plugin_integration.py  # i 24 della pipeline
python tools/data_plugin_benchmark.py 7                  # la tabella del §20
```

Il contratto, letto dal codice invece che da questo documento:

```bash
grep -rn "app.geometry" app/build/assembler.py app/core/resolver.py
grep -rn "mesh_backed\|kind == \"data\"" app/build/ app/core/ --include=*.py \
  | grep -v data_plugin.py | grep -v registry.py
```

Un plugin dati scritto su disco, da ispezionare a mano:

```bash
python -c "
import sys, tempfile; sys.path[:0] = ['.', 'tests']
from pathlib import Path
from data_plugin_fixtures import write_knight_plugin
print(write_knight_plugin(Path(tempfile.mkdtemp())))"
```
