# V6-RESULTS — Un GLB diventa conoscenza di 3DGen senza scrivere JSON

Milestone V6, chiusa il **15 ottobre 2026**. Branch `v5-semantic-variability`,
partenza dichiarata e verificata prima di toccare qualunque cosa: commit
`34f4791`, **1598 test verdi**, componenti procedurali e mesh-backed che
convivono, data plugin JSON+GLB funzionanti, retrieval e degradazione semantica
funzionanti, trait semantici e strutturali funzionanti, parametri mesh-backed
che pilotano un `EffectSpec`, contratto dei frame disponibile. UI di authoring
inesistente, Teach 3DGen inesistente.

**Esito: completa.** Suite da 1598 a **1761 test verdi** (163 nuovi, zero
rossi).

Tre cose vanno dette in testa, perche' cambiano la lettura di tutto il resto.

**1. La UI non e' il prodotto di questa milestone: il livello di servizio lo
e'.** `app/authoring/` non importa Qt in nessun file, e un test costruisce un
plugin intero — import, gerarchia, socket, parametri, validazione,
installazione — senza aprire una finestra. La finestra
(`app/ui/authoring_window.py`) e' un cliente sottile, e un test verifica per
**token** che non contenga `trimesh`, `json`, `emit_plugin`, `load_component`
ne' `Registry`. Il punto 25 della milestone chiedeva che la UI non fosse
l'unico modo di costruire un plugin: e' misurato, non dichiarato.

**2. Una sola riga del core e' cambiata, e apre il caso che mancava.** Un
componente **dati** non poteva esistere senza `mesh`, quindi un cavaliere fatto
di corpo, testa, spada e scudo andava dichiarato come una mesh monolitica
oppure non si poteva dichiarare. `Piece.mesh = None` era legittimo da sempre —
`humanoid:body` e' quello storico — e il loader lo pretendeva comunque. Da V6
`mesh` e' facoltativo, con due regole che rendono il caso non ambiguo (§3). E'
l'unico cambiamento di contratto non additivo della milestone, e §16 lo
dichiara.

**3. La preview non simula: emette e installa.** Costruire un draft vorrebbe
dire o simularlo chiamando `trimesh` a mano — che il punto 19 vieta, e che
mentirebbe appena qualcosa nella pipeline cambia — o farlo diventare un plugin
vero. V6 sceglie il secondo: `_stage()` scrive il plugin in una cartella di
lavoro e lo installa in una `Session` usa e getta, quindi **cio' che si vede e'
cio' che si salvera'**, perche' e' lo stesso JSON letto dallo stesso loader. Il
prezzo e' 131 ms una volta; muovere uno slider costa **1.2 ms**, perche' i
parametri viaggiano nel piano e non nel JSON (§13).

---

## 1. UX e flusso

Sette schede, in quest'ordine, piu' una riga che non cambia mai:

```text
1. Import  →  2. Components  →  3. Hierarchy  →  4. Sockets
           →  5. Variability →  6. Validate   →  7. Save / Install
```

L'ordine e' quello in cui le cose **diventano possibili**: non si crea un
componente senza una selezione, non si fa una gerarchia senza componenti, non
si innesta senza sapere su che cosa. Non e' un wizard e non obbliga: le schede
restano tutte raggiungibili, perche' tornare indietro a sistemare un socket
dopo aver visto la validazione e' il caso normale, non l'eccezione.

Sotto le schede c'e' sempre la stessa riga, e risponde alle quattro domande del
punto 24:

```text
componente: head   geometria: 3 oggetti: knight/Head, knight/Eye_L, knight/Eye_R
destinazione: C:/…/plugins/my_plugin   validita': ok (0 errori, 0 avvisi, 2 note)
```

Sono le quattro cose che si perdono dopo dieci minuti di lavoro, e un test le
legge tutte e quattro dalla finestra vera
(`test_the_context_bar_answers_the_four_questions`).

A destra c'e' il viewport di sempre, con il detail level e due interruttori per
i gizmo. Non e' un editor 3D general purpose, ed e' deliberato: non c'e'
selezione di facce, non c'e' sculpting, non c'e' un editor UV, non c'e' rigging.
Gli strumenti sono quelli che servono a **dichiarare il contratto che 3DGen ha
gia'**.

Il Component Lab e' una finestra a parte, raggiungibile dalla scheda
Variability (sul componente in lavorazione) e dalla finestra principale (su
qualunque componente installato).

---

## 2. Il modello di authoring, e perche' non e' un secondo modello

`app/authoring/model.py` (718 righe). Durante l'editing serve uno stato che il
plugin finale non ha: quale GLB e' aperto, quali oggetti sono selezionati, quale
componente si sta modificando, cosa e' nascosto, dove si salvera', quanto una
parte e' affidabile. Scriverlo nel plugin a ogni click sarebbe sbagliato due
volte — si ricaricherebbe il registry a ogni carattere digitato, e il plugin
conterrebbe campi che riguardano l'editor.

| Oggetto | Che cos'e' | Che cosa diventa al salvataggio |
| --- | --- | --- |
| `AuthoringProject` | il lavoro: sorgenti, componenti, materiali, variant, selezione, destinazione | `plugin.json` |
| `SourceModel` / `SceneObject` | un GLB importato e i suoi nodi (nome, triangoli, limiti, trasformazione, tinta) | **niente**: la geometria si estrae, il percorso non si salva nel plugin |
| `DraftComponent` | un componente in lavorazione | `components/<nome>.json` |
| `DraftSocket` | un innesto | un normale `Socket` |
| `DraftParam` | un parametro con la sua strategia | `params.<nome>` con `transform` o `effect` |
| `DraftChild` | un arco della gerarchia | un normale `Attachment` |
| `VariantRecipe` | una configurazione utile | resta nel progetto (§11) |

**Non e' una seconda rappresentazione permanente dei `Component`**, e le quattro
ragioni sono verificabili:

1. nessun `Draft*` ha un `build`, e nessuno entra mai nel `Registry`;
2. al salvataggio producono il formato dati V4/V5 e **spariscono**;
3. riaprire un plugin salvato ricostruisce i draft **dal JSON**
   (`open_data_plugin`), quindi non c'e' una seconda verita' da sincronizzare;
4. portano campi che il plugin non deve avere — selezione, visibilita',
   copertura, `objects`, `mesh_source` — ed e' per questo che esistono separati.
   Un test cerca ciascuno di quei campi nel JSON emesso e non lo trova.

### Il progetto e' serializzabile, e non contiene mesh

`.3dgenproj` e' JSON con `format: 1`. Pesa meno di 60 KB per il cavaliere di
prova, non contiene un byte di geometria, e riaprirlo reimporta le sorgenti dai
loro percorsi — come `.my3d` non incorpora i GLB. Una sorgente che non c'e' piu'
diventa un **avviso** `AUTHORING_FILE_MISSING` e non un'eccezione: il progetto
resta apribile e chi legge sa quale file e' sparito. Un `format` diverso e'
rifiutato invece di essere letto al contrario.

### La copertura: VALIDATED / CANDIDATE / MISSING / PROXY

Il punto 26 chiedeva di rappresentare lo stato di copertura di una parte senza
collegarlo a nessun provider, e di **trovare il livello appropriato**. Il
livello e' `DraftComponent.coverage` e `VariantRecipe.coverage`, cioe' il
progetto di authoring — non `Component`:

> Un `Component` installato non **ha** una copertura. Ci sta dentro, o non c'e'.
> La copertura e' il giudizio di chi sta costruendo un concetto, e appartiene a
> chi costruisce.

Quattro valori, quattro colori di V7: verde `VALIDATED`, giallo `CANDIDATE`,
rosso `MISSING`, blu `PROXY`. Nessun provider AI li tocca: sono campi, e un test
cerca `provider`, `LLMProvider`, `complete_json`, `Planner` e `make_provider`
nei **token** di `variant.py` e non ne trova nessuno. Un test parametrizzato sui
quattro valori verifica che nessuno dei quattro compaia nel plugin emesso e che
tutti e quattro sopravvivano nel `.3dgenproj`.

---

## 3. Il composite senza mesh: l'unica modifica al core

```json
{
  "id": "knight_pack:knight",
  "description": "A complete knight: body and head",
  "provides": ["creature"],
  "mounts": [{"capability": "torso_mount", "socket_id": "core"}],
  "sockets": [{"name": "core", "position": [0,0,0], "direction": [0,1,0],
               "up": [0,0,1], "radius": 0.25, "capabilities": ["torso_mount"]}],
  "children": [{"id": "body", "component": "knight_pack:body", "level": 1,
                "requirement": {"capability": "torso_mount"}}]
}
```

Nessun `mesh`. Due regole lo rendono non ambiguo, e sono entrambe la politica di
V4 (`V4-RESULTS.md` §6) applicata a un caso nuovo:

| regola | perche' |
| --- | --- |
| senza `mesh` **servono** `children` | un componente che non ha ne' geometria ne' figli non e' niente, e un niente dichiarato e' un errore di chi scrive. `DATA_SCHEMA_INVALID` |
| senza `mesh` **niente** `transform` | `scale_x` moltiplica una mesh; qui non ce n'e' una, e scalare i soli socket sposterebbe i figli senza rimpicciolirli. `DATA_PARAM_UNSUPPORTED` |

Un parametro `effect` resta ammesso su un composite, perche' un effetto con
ambito `subtree` deforma i figli e questo e' esattamente cio' che chiede chi
scrive un composite variabile.

Perche' e' importante al di la' dell'authoring: **un concetto complesso e'
normalmente un composite, non una mega-mesh**. Il cavaliere di prova costruisce
48 triangoli — 12 del corpo piu' 36 della testa con due occhi — e la radice non
porta geometria propria. E' la forma che Teach 3DGen usera' per decomporre un
concetto, e fino a V5 un plugin dati non poteva esprimerla.

Misurato: `detail 1` da' `[subject, subject/body]`, `detail 2` aggiunge
`subject/body/head`, e i triangoli passano da 12 a 48 senza che niente venga
ritassellato — la geometria del corpo e' **identica** ai due livelli
(`test_detail_level_is_not_mesh_lod`).

---

## 4. Il livello di servizio

`app/authoring/service.py` (1816 righe). I nomi che la milestone suggeriva
esistono, piu' quelli che servivano:

```python
svc = AuthoringService()                       # tiene una Session, nient'altro
svc.create_authoring_project("knight_pack", destination="…")
svc.import_model("knight.glb")                 # → SourceModel
svc.scene_objects(); svc.object_info(key)
svc.select([...]); svc.isolate(); svc.show_all()
svc.create_component("body", role="torso", provides=["torso_mount"])
svc.set_metadata(key, tags=(...), coverage=CANDIDATE)
svc.add_socket(key, "neck", direction=(0,1,0), radius=.15)
svc.add_mount(key, "head_mount", socket="neck")        # socket + Mount insieme
svc.snap_socket_to_face(key, "neck", "+Y"); svc.mirror_socket(key, "arm_l")
svc.add_param(key, "width", transform="scale_x", semantic_role="width")
svc.add_param(key, "curvature", effect={"type": "fx:bend", …})
svc.set_parent(child, parent, level=1, requirement={"capability": …})
svc.reorder(parent, "head", 0); svc.duplicate_reference(parent, "wing")
svc.set_frame(key, growth_axis="+Y", front="+Z", up="+Y")
svc.search_components("dragon eye"); svc.search_staged("dragon eye")
svc.planner_preview(key); svc.detail_preview(key, 2); svc.frame_report()
svc.validate()                                  # → ValidationReport
svc.build_component(key, params={…}, detail_level=3)   # → GenerationResult
svc.save_plugin(); svc.install_plugin()         # → Path, InstallResult
svc.open_data_plugin(path); svc.save_project(); svc.load_project()
svc.lab("creature:eye"); svc.draft_lab(key)     # → ComponentLab
svc.save_variant(recipe); svc.build_variant("dragon_eye")
```

Quattro decisioni di questo livello valgono la pena di essere scritte.

**1. `add_mount` esiste perche' socket e `Mount` si dichiarano insieme.** Nel
modello sono separati, e per buone ragioni: un socket e' geometria, un `Mount`
e' contratto. Ma dichiararne uno senza l'altro e' l'errore che si fa sempre — un
`Mount` su un socket che non c'e' non monta niente, e un socket senza `Mount`
non viene mai scelto dal resolver. Un composite appena creato ha questo problema
**per costruzione**, perche' nasce senza socket: il resolver dice `NO_MOUNTS` e i
figli non si attaccano. `add_mount` crea i due insieme, e
`AUTHORING_MOUNT_WITHOUT_SOCKET` segnala il caso in cui restano scollegati.

**2. Il riferimento di un arco nomina tre cose con lo stesso campo.** Il
prefisso dice quale: `draft:<key>` un componente di questo progetto,
`variant:<nome>` una ricetta, qualunque altra stringa un componente
**installato**. E' cio' che rende il punto 7 della milestone un caso normale
invece di una funzione a parte (§7).

**3. Un campo sconosciuto e' rifiutato, non ignorato.** `set_metadata(colour=…)`
alza `AUTHORING_PROJECT_INVALID`. E' la regola 22 di `PROJECT-INDEX` applicata
all'API: un'opzione ignorata in silenzio e' un contratto che divergera'.

**4. Gli errori hanno un codice stabile, e i codici del formato dati non si
traducono.** `AuthoringError` porta `AUTHORING_*`; quando il salvataggio produce
un JSON che il loader rifiuta, chi legge vede `DATA_FRAME_INVALID` o
`DATA_PARAM_UNSUPPORTED` — il codice del loader, non un alias che nasconde dove
sta il confine.

### Come fa a costruire prima di aver salvato

```text
project.fingerprint()  cambiato?
   no  → la Session di lavoro che c'e'
   si  → emit_plugin(project, cartella_temporanea) → Session(plugin_paths + …)
                                                   → catalog()
```

`fingerprint()` e' lo sha256 di cio' che finirebbe nel plugin, **escluso** lo
stato dell'editor: selezione, visibilita', componente corrente, destinazione,
copertura, note. Muovere uno slider non lo cambia, perche' i parametri viaggiano
nel **piano**. E' la ragione per cui un aggiornamento di parametro costa 1.2 ms
invece di 130 (§13).

---

## 5. Import e creazione di un componente

`app/authoring/inspect.py` (175 righe). Due vincoli dichiarati prima della prima
riga, entrambi presi da `VISION-GAP.md` §5.3:

* **niente inferenza.** Importare elenca cio' che il file dichiara — nodi, nomi,
  triangoli, limiti, trasformazione, tinta — e si ferma. Un test verifica che
  dopo un import il progetto abbia **zero** componenti: riconoscere le parti con
  un modello e' una feature separata e successiva;
* **niente esecuzione, e nessun file fuori dalla cartella del modello.** Un
  `.gltf` puo' nominare risorse esterne: passano dallo stesso lettore confinato
  di `app/core/data_plugin.py`, con la cartella del modello come radice.
  `trimesh` riceve byte e un dizionario, mai un resolver di filesystem o di
  rete (`allow_remote=False`).

Che cosa sia un glTF 2.0 valido e che cosa sia una `uri` ammissibile e' deciso in
**un** posto, e `inspect.py` importa gli helper di `data_plugin` invece di
copiarli: un secondo parser vorrebbe dire due idee di validita' che divergono
alla prima divergenza, e il formato che si salva e' quello che il loader
rilegge.

Per il GLB di prova — un cavaliere in cinque pezzi, come un artista lo
esporterebbe:

```text
knight/Body   Body   12 tri  0.500 x 1.000 x 0.300  #788296
knight/Eye_L  Eye_L  12 tri  0.080 x 0.080 x 0.060  #1e1e28
knight/Eye_R  Eye_R  12 tri  0.080 x 0.080 x 0.060  #1e1e28
knight/Head   Head   12 tri  0.340 x 0.340 x 0.340  #d2b48c
knight/Sword  Sword  12 tri  0.070 x 0.900 x 0.020  #c8c8d2
```

La chiave di un oggetto e' `<file>/<nodo>`, e non dipende dall'ordine di
importazione: due file con lo stesso nome di nodo restano distinguibili
(`knight_2/Head`), perche' i draft la nominano e una chiave che cambia non
sarebbe un'identita'.

### Selezione, e un oggetto per componente

Multi-selezione, `select_all`, `clear_selection`, `isolate`, `hide`/`show`.
Nessuna selezione di facce: richiederebbe un editor mesh completo, ed e' fuori
da V6 per scelta dichiarata.

Un oggetto appartiene **a un solo** componente, e il secondo tentativo e'
`AUTHORING_DUPLICATE` invece di una geometria condivisa che nessuno dei due
possiede davvero. `object_info(key)["component"]` dice di chi e', ed e' quello
che la riga di contesto mostra.

### Il nome di un componente e' anche un nome di file

`check_name`: minuscole, cifre, `_`, `-`. Non e' pignoleria — quel nome diventa
`plugin:nome` e `meshes/nome.glb`, quindi uno spazio o un `..` sarebbero un id e
un percorso insieme. Cinque casi parametrizzati (`Head`, `my head`,
`../escape`, `head!`, `""`) sono rifiutati dall'API, e un sesto test ne forza
**sei** dentro il modello — saltando l'API — per verificare che anche
l'emettitore si difenda da solo (§16).

---

## 6. Gerarchia

```text
knight            (composite, nessuna mesh)
└ body            level 1   requirement: torso_mount
  └ head          level 2   requirement: head_mount
```

Operazioni: `set_parent`, `unparent`, `remove_from_hierarchy`, `reorder`,
`set_child_options` (level, optional, on_request, replaces, replaces_parent,
on, own_socket, scale_mode, insert, roll, requirement, params, material, tags),
`duplicate_reference`.

Tre cose misurate, non assunte:

* **la gerarchia e' `Attachment` normali.** Il JSON emesso contiene
  `{"id": "body", "component": "knight_pack:body", "level": 1, "requirement":
  {...}}` e nient'altro: nessun campo nuovo, nessun tipo nuovo;
* **non tocca la geometria originale.** Un test confronta `object_info` prima e
  dopo `set_child_options` e `reorder`, e il dizionario e' identico. Il punto 6
  della milestone lo chiedeva esplicitamente;
* **un ciclo e' rifiutato prima di esistere.** `set_parent` aggiunge l'arco,
  cerca il ciclo, e in caso lo **toglie** prima di alzare `AUTHORING_CYCLE`: un
  test verifica che il figlio non resti a meta'.

`duplicate_reference` e' il modo di montare lo stesso componente due volte — due
occhi, due ali — e genera l'id successivo (`sword` → `sword_2`) invece di
chiedere all'utente di inventarlo.

---

## 7. Riusare la libreria installata

E' il punto 7 della milestone, ed e' un caso normale e non una funzione a parte:
`set_parent` accetta l'id di un componente **installato**.

```python
svc.set_parent("creature:dragon_head", body.key, child_id="head",
               requirement={"capability": "head_mount"})
svc.set_parent("fantasy:wing", body.key, child_id="wing_l",
               requirement={"capability": "wing_mount", "side": "l"})
```

Misurato: il corpo di drago importato con `creature:dragon_head` montata per
capability costruisce 94 triangoli, i `ref` risolti sono
`{unit_plugin:dragon_body, creature:dragon_head}`, e il JSON emesso contiene
`"component": "creature:dragon_head"` — cioe' il plugin generato **dipende**
dalla libreria installata invece di duplicarla. La ricerca che fa trovare il
pezzo da riusare e' l'indice semantico vero (§9).

Un riferimento che non e' ne' un draft, ne' una variant, ne' un componente
installato e' `AUTHORING_UNKNOWN_COMPONENT` subito, non un `COMPONENT_NOT_FOUND`
al primo build.

---

## 8. Socket, gizmo e snap

`DraftSocket` ha i campi di `Socket`, uno per uno: `name`, `position`,
`direction`, `up`, `radius`, `capabilities`, `side`, `tags`. Nessun
`MeshSocket`, e il test lo verifica leggendo il tipo: `type(socket) is Socket`.

### Il gizmo e' geometria, non un overlay

Il viewport disegna una `Scene`, cioe' mesh con un materiale. Non ha un canale
per righe e frecce, e aggiungerglielo vorrebbe dire un secondo sistema di
rendering accanto a quello che c'e'. Quindi un gizmo e' **una mesh in piu' nella
scena di preview**, con il tag `gizmo`:

| forma | che cosa dice |
| --- | --- |
| disco | dove sta il socket, e quanto e' grande — il raggio **e'** il raggio |
| freccia | il `direction`: da che parte esce il figlio |
| barretta | l'`up`: come e' orientato il figlio girando attorno all'asse |

Le misure seguono il raggio dell'innesto, perche' un gizmo di dimensione fissa
su un socket da 2 cm e uno da 2 m non si leggerebbe in nessuno dei due casi.

**I nodi di gizmo non sono il modello**, ed e' misurato: la scena di preview del
corpo ha 6 nodi in piu' (tre per ciascuno dei due socket), e la somma dei
triangoli dei nodi **senza** il tag `gizmo` e' esattamente quella di
`GenerationResult.triangles`. Non entrano nei conteggi, non si esportano, non
finiscono nel plugin.

**Limite dichiarato: il gizmo non si trascina.** Il picking nel viewport non
esiste in V6, e un gizmo che si vede ma non si afferra sarebbe una promessa non
mantenuta. Si sposta e si orienta con i campi numerici e con gli snap, e il
round-trip dei suoi dati e' verificato fino al plugin salvato
(`test_socket_gizmo_data_survives_save_and_reload`: posizione, direzione, up e
raggio tornano identici a 1e-6 dopo essere passati per il loader di produzione).

### Gli snap sono aritmetica sui limiti

`snap_to_center`, `snap_to_face(axis)`, `snap_to_extreme(axis)`,
`align_socket_direction(axis)`, `align_socket_up(axis)`, `mirror_socket`.
Nessuno guarda la topologia, nessuno indovina niente, tutti danno lo stesso
risultato ogni volta — e nessun piazzamento assistito da un modello, come la
milestone chiede.

`mirror_socket` e' quello che vale di piu' nell'uso vero: occhio sinistro e
occhio destro sono lo stesso innesto con una coordinata invertita, e scriverli
due volte a mano e' il modo di scriverne uno sbagliato. Inverte posizione,
direzione e `up`, gira il `side` (`l` ↔ `r`), e rinomina (`eye_l` → `eye_r`).
Un test verifica che sia la propria inversa.

### Una sola idea di socket valido

`DraftSocket.check()` chiama `data_plugin._socket`. Non la validazione di
`Socket`, che e' piu' indulgente **di proposito**: `orthogonal_up` **ripara** un
`up` parallelo alla direzione, perche' un componente procedurale che sbaglia di
un epsilon non deve morire. Il loader dei plugin dati invece rifiuta una terna
degenere, e chi sta disegnando un innesto deve sapere adesso cio' che
scoprirebbe al salvataggio. Un `update_socket` rifiutato non lascia il socket a
meta': si prova su una copia e si tiene solo se regge.

---

## 9. Capability, metadata e preview semantica

### Capability

`capabilities()` restituisce ogni nome conosciuto con chi lo **fornisce** e chi
lo **accetta**, letti da `Registry.capability()`. L'utente sceglie da un elenco
di 27 voci invece di ricordare una stringa, e `search_capabilities(text)` filtra.

Dichiararne una nuova e' lecito ed e' **dati**: compare nell'elenco con
`declared = False`, e la validazione dice `AUTHORING_NEW_CAPABILITY` come
**nota** — «la fornisci, e nessuno la accetta ancora» — non come errore. E' la
risposta al punto 10: si puo' creare una capability dichiarativa senza toccare
il core, perche' il core non ne ha un elenco.

### Metadata, e cio' che il planner vedra'

`role`, `tags`, `provides`, `styles`, `requires`, `description`, `synonyms`,
`material`, `mounts`, `layout_regions`, `coverage`, `notes`. I `synonyms` di un
componente diventano **ponti nel manifest**, cioe' dati che
`Registry.synonyms()` legge: e' la regola 11 di `PROJECT-INDEX`, e l'autore puo'
dire «questo cavaliere risponde anche a *paladin*» senza una riga di codice.
Misurato: dopo l'installazione `session.shortlist("a paladin").ids` contiene
`unit_plugin:knight`.

La preview «What the planner will see» non e' un riassunto scritto da noi:

```text
- unit_plugin:head "A helmeted knight head with eyes"
    e': head_mount
    tag: head
```

E' `ComponentEntry.to_text()`, la **stessa funzione** del vocabolario di
produzione, e un test lo asserisce confrontando la stringa con
`_componente(component).to_text()`. E' la regola 16 di `PROJECT-INDEX`: cio' che
non e' nel testo reso non esiste per il modello, quindi l'autore deve vedere il
testo reso e non una parafrasi.

### «Se scrivo *dragon eye*, questo componente sara' trovabile?»

Due ricerche, e la differenza conta:

| chiamata | su che cosa cerca |
| --- | --- |
| `search_components(q)` | la libreria installata — serve a **trovare il pezzo da riusare** |
| `search_staged(q)` | la libreria **piu'** i draft di adesso — serve a rispondere alla domanda dell'autore |

Entrambe passano da `Session.component_index()`, cioe' dal `SemanticIndex` di
V1: un test verifica che `search_components` dia **esattamente** lo stesso
risultato di `session.component_index().search(...)`. Nessuna ricerca separata
per l'editor.

Misurato: `unit_plugin:body` non e' in `search_components("knight body")` — non
e' installato — ed e' in `search_staged("knight body")`.

La validazione aggiunge `AUTHORING_NOT_RETRIEVABLE` (avviso) quando un
componente installato non viene trovato cercando il proprio nome, e
`AUTHORING_NO_DESCRIPTION` (nota) quando manca la descrizione, perche' la
descrizione **e'** il documento che il retrieval indicizza.

---

## 10. Variabilita'

La UI offre **solo cio' che e' installato**, e lo legge dal registry:

```text
Parameter: width
type: float      default 1.0      min 0.3   max 2.5
semantic role: width        ← dai 6 ruoli che la libreria dichiara davvero
implementation:
  ○ transform  scale_x / scale_y / scale_z / uniform_scale   ← l'elenco del loader
  ○ effect     fx:bend          knob: amount   scope: part   neutral: 0.0
               ↑ i 12 effetti installati, con i soli knob **numerici**
```

* `param_strategies()["transforms"]` e' la costante `TRANSFORMS` del loader, non
  una copia;
* `param_strategies()["effects"]` sono gli effetti installati con i knob
  numerici e gli ambiti **dichiarati**. L'`axis` di `fx:bend` non compare,
  perche' un parametro dati pilota solo numeri — e' il debito dichiarato di V5,
  e la UI non prova ad aggirarlo offrendo un knob che il loader rifiuterebbe. Un
  test lo verifica: `"axis" not in knobs`;
* `semantic_roles()` sono i ruoli che i componenti installati e le regole dei
  trait dichiarano: `girth`, `height`, `length`, `ratio`, `scale`, `width`.
  Nessun elenco nel core.

Sette casi ostili sono rifiutati con `AUTHORING_PARAM_STRATEGY` prima di
arrivare al disco: un effetto non installato, un knob che non esiste, un ambito
non dichiarato, e **quattro** chiavi che un plugin dati non puo' nemmeno nominare
(`callable`, `expression`, `module`, `matrix`). E' la stessa politica di V5 §1,
applicata all'editor perche' l'editor non deve essere la strada per aggirarla.

Misurato su una lama importata:

| `curvature` | triangoli | referto | geometria |
| --- | --- | --- | --- |
| 0.0 (neutro) | 12 | nessun `PARAM_EFFECT_REQUESTED` | la mesh come e' |
| 0.9 | 12 | `PARAM_EFFECT_REQUESTED` | vertici e limiti cambiati |

Dodici triangoli in entrambi i casi: e' una mappa di punti, non una mesh nuova.
E il neutro non chiede niente — a 0.0 l'effetto non entra in programma, che e'
esattamente cio' per cui `neutral` esiste.

Un parametro **senza** strategia non e' rifiutato mentre si scrive (scrivere il
nome e poi scegliere l'implementazione e' come si lavora) ma la validazione lo
dichiara errore e il loader lo rifiuterebbe: non si puo' salvarlo per sbaglio.

E un trait installato raggiunge il componente nuovo attraverso il
`semantic_role`, senza che nessuno scriva una regola: `std:width = 2.0` su un
corpo importato che dichiara `semantic_role: "width"` raddoppia l'estensione X e
lascia Y invariata.

---

## 11. Frame

Dichiarabile sul **plugin** (una riga, vale per tutti i suoi componenti) e sul
singolo componente, che vince sul predefinito — le due strade di V5 §7, con la
stessa precedenza, verificata caricando il plugin emesso:

```json
"frame": { "growth_axis": "+Y", "front": "+Z", "up": "+Y" }
```

Un asse non nominabile (`+W`) o un `front` parallelo a `up` sono rifiutati
**adesso**, non al caricamento.

`frame_report()` applica `compare()` a ogni arco della gerarchia e restituisce i
quattro esiti con le stesse parole che il resolver usera' sul modello vero:

```text
dragon_body/head    convertible
  frame convertibile (front: -Z contro +Z): 180.0 gradi attorno a Y
  al suo posto: fx:rotate axis=Y angle=180.0 su subtree:head
dragon_body/wing_l  convertible   (idem)
```

**V6 non auto-corregge**, come V5 non auto-correggeva: la rotazione si calcola,
si nomina, e chi legge decide. Un test verifica che dopo un `convertible` la
geometria sia ancora quella (48 triangoli) e che `FRAME_CONVERTIBLE` sia nel
referto. Un frame incompleto resta `ambiguous` e **non** porta una mossa: con
una terna incompleta la rotazione non e' determinata, e indovinarla sarebbe
inventare.

`verify_frame` gira sulla geometria vera con l'helper che esisteva
(`app/core/authoring.py`): per il corpo del cavaliere, che cresce davvero lungo
+Y, nessuna diagnostica; dichiarando `+Z` — lungo cui si estende per meno di un
terzo del lato lungo — `GROWTH_AXIS_MISMATCH`, e la geometria resta identica.

**Un frame non dichiarato e' silenzio, non un predefinito**: `verify_frame` su
un componente senza terna da' `FRAME_UNDECLARED` come **nota**, e il referto
resta `ok`. E' la regola 27 di `PROJECT-INDEX` applicata anche al disegno: il
gizmo del frame mostra una freccia solo per gli assi che il frame nomina
davvero, perche' mostrarne una inventata insegnerebbe una convenzione che
l'autore non ha scritto.

---

## 12. Materiali, e la politica di V4 intatta

`material_preview(key)` mostra tre cose perche' le decisioni sono tre, e
l'ordine e' quello di V4 §10:

```text
imported:  ['#788296']           le tinte che i nodi del GLB portavano
declared:  knight_steel          il MaterialSpec scelto
effective: #8899aa  (progetto)   cio' che si vedra', e da dove viene
```

`source` e' uno di `progetto` / `installato` / `importato` / `ripiego`. Si puo'
creare un `MaterialSpec` con i **cinque campi che esistono** (`name`,
`base_color`, `roughness`, `metallic`, `opacity`) — nessun editor PBR, nessuna
texture, nessuna UV. Misurato: il materiale dichiarato in authoring diventa
`materials/knight_steel.json`, il registry lo installa, e
`scene().by_id("subject").material.base_color` e' `#8899aa`.

---

## 13. Component Lab

`app/authoring/lab.py` (415 righe). Funziona su **qualunque** componente del
registry, e il test che tiene insieme questa sezione e' una
`@pytest.mark.parametrize("backend", ["procedural", "mesh"])` ripetuta su sei
assert: il laboratorio non sa da dove viene la geometria, perche' passa dalla
pipeline vera. Un test legge `lab.py` per **token** cercando `mesh_backed`,
`is_mesh`, `glb`, `gltf`, `trimesh`, `data_plugin`, e non trova niente.

```text
humanoid_anatomical:body | 2 params | 7 trait | 12 effetti
    body_mass  ratio  [0.55, 1.65]  ruolo girth
    height     distance [0.45, 2.6]  ruolo length
traits: std:body_mass std:hand_scale std:head_scale std:length
        std:limb_length std:part_scale std:width
structural: character:arm_count
```

### I trait compatibili seguono la composizione, risolvendola

E' la parte di cui vale la pena spiegare il perche'. Un trait su un composite
colpisce quasi sempre una **parte** e non la radice: `std:head_scale` filtra
`role in (head, face)`, e la testa di un umanoide non e' la radice — e' un
figlio che la radice dichiara. Guardare solo il componente direbbe «nessun trait
compatibile» su un umanoide intero, che e' falso e che V5 §9 ha misurato falso
(testa ×1.74 su questo stesso componente).

Quindi `subtree()` **risolve** invece di leggere gli `Attachment`, e la
differenza non e' di comodo: `Component.children` e' una callable, e quella di
`humanoid_anatomical:torso` legge valori che il resolver deriva dal padre
(`height`, `hip_width`). Chiamarla con i soli predefiniti alza `KeyError` —
misurato mentre si scriveva questo modulo — quindi l'unico modo onesto di sapere
di quali parti un componente e' fatto e' chiederlo a chi lo compone.

Il giudizio di compatibilita' riusa `TraitResolver._matches` e
`StructuralTarget.matches`, cioe' gli stessi criteri che decideranno davvero:
un secondo matcher qui vorrebbe dire offrire un trait che poi non colpisce, che
e' peggio di non offrirlo. Un test verifica che ogni trait offerto si applichi
davvero.

**Questa e' la correzione che il debito 12 di `PROJECT-INDEX` chiede** — seguire
la composizione dichiarata invece di guardare la rosa — fatta dove si puo'
fare: il laboratorio ha il componente in mano e puo' costruirlo, mentre il
retrieval ha solo la rosa e nessun grafo. **Il debito nel vocabolario resta
aperto**, e questo non lo chiude.

### Non modifica niente

Il laboratorio costruisce **piani**, che sono la cosa che il progetto considera
l'artefatto (regola 7). Un test su entrambi i backend randomizza i parametri,
applica un trait, poi chiama `reset()` e verifica che l'ingombro sia tornato
**esattamente** quello di partenza e che i `default` del `Component` non siano
cambiati. Il registry e' congelato e lo resta.

`randomize` sta dentro gli intervalli **dichiarati** e non ne inventa: un
parametro senza `min`/`max` non si tocca, perche' dargli un intervallo vorrebbe
dire scegliere al posto dell'autore. E' deterministico per seme.

`detail_levels()` misura i nodi con build vere, livello per livello: serve a
distinguere il `detail_level` dal LOD di una mesh, e per
`humanoid_anatomical:body` da' 7 / 37 / 38 nodi. Un test verifica che un L1 con
`part_scale = 2.5` abbia **meno nodi** e piu' ingombro di un L3 senza niente —
l'assert di V5 §10, qui dalla parte del laboratorio.

`Save as defaults` scrive sul **draft**, se c'e'; su un componente installato
dice di usare `Save Variant`, perche' un laboratorio che modificasse la libreria
non sarebbe un laboratorio.

---

## 14. Variant recipe

```json
{"base": "lab_plugin:blade", "name": "curved_blade",
 "params": {"curvature": 0.9},
 "coverage": "CANDIDATE", "detail_level": 2, "style": "low_poly"}
```

Il formato minimo coerente con il sistema, e non e' un formato nuovo: ogni campo
e' un pezzo di piano. `to_plan()` lo rende un piano che `Session.build` accetta,
`to_attachment()` lo rende un `Attachment` che un composite puo' contenere.

* **nessuna mesh duplicata**, e misurato: un file di variant pesa meno di 700
  byte, non contiene `mesh`, `glb`, `vertices` ne' `faces`, e salvarlo non
  scrive nessun `.glb` accanto;
* **tiene solo cio' che e' cambiato**: `save_variant` confronta con i `default`
  del componente e scarta il resto;
* **ricostruisce la stessa geometria**: un test verifica che
  `session.build(recipe.to_plan())` dia gli stessi triangoli e gli stessi limiti
  (a 1e-9) della configurazione da cui e' stata salvata.

### Riusarla in un composite, e il limite dichiarato

```python
svc.set_parent("variant:wide_body", holder.key, child_id="wide",
               requirement={"capability": "torso_mount"})
```

Il JSON emesso contiene `{"component": "unit_plugin:body", "params":
{"width": 2.0}}` — la **base** con i parametri incorporati, e la parola
«variant» non compare da nessuna parte: nel plugin installato non esiste un
terzo tipo di cosa.

**Il limite**: un `Attachment` porta `params` e non porta trait ne' effetti, che
sono cose del **piano**. Quindi una variant di soli parametri si incorpora senza
perdere niente (`embeddable = True`), e una con trait o effetti no:
`lost_in_attachment()` dice che cosa, e `validate()` emette
`AUTHORING_VARIANT_NOT_EMBEDDABLE` come avviso invece di perderlo in silenzio.
La via d'uscita, se servira', e' un parametro `effect`-backed sul componente
base: un numero che chiede una piega e' un parametro, e i parametri viaggiano.

### Il ponte verso V7

```text
giallo (CANDIDATE)  →  l'utente muove i parametri  →  Save Variant  →  verde (VALIDATED)
```

`promote()` fa il passaggio, e lo fa **l'utente**: nessun provider decide niente
in V6.

Una variant di una variant non esiste, ed e' dichiarato invece che gestito: una
catena di ricette avrebbe bisogno di una risoluzione ricorsiva dei parametri,
cioe' di un secondo sistema di composizione accanto al piano. La base e' sempre
un `Component`.

---

## 15. Validazione

`validate()` usa **i validatori veri**, in quest'ordine, che e' l'ordine del
flusso:

| passo | chi parla | esempi di codice |
| --- | --- | --- |
| progetto | l'authoring | `AUTHORING_PARAM_STRATEGY`, `AUTHORING_REF_NOT_FOUND`, `AUTHORING_MOUNT_WITHOUT_SOCKET`, `AUTHORING_DUPLICATE_NAME`, `AUTHORING_EMPTY_COMPONENT`, `AUTHORING_NEW_CAPABILITY`, `AUTHORING_NO_DESCRIPTION`, `AUTHORING_VARIANT_NOT_EMBEDDABLE` |
| schema | `data_plugin` | `DATA_SCHEMA_INVALID`, `DATA_PARAM_UNSUPPORTED`, `DATA_FRAME_INVALID`, `DATA_PATH_UNSAFE` |
| registry | `Registry.verify()` | `COMPONENT_EFFECT_NOT_FOUND`, `COMPONENT_EFFECT_KNOB_UNKNOWN`, `MATERIAL_REDECLARED`, dipendenze |
| resolver | `Resolver` | `NO_MOUNTS`, `SOCKET_INCOMPATIBLE`, `PROVIDER_INCOMPATIBLE`, `FRAME_CONVERTIBLE`, `FRAME_AMBIGUOUS` |
| geometria | `app/build/validate.py` | `GEOMETRY_REQUIREMENT`, `EMPTY_GEOMETRY`, `TRIANGLE_BUDGET`, giunti, compenetrazioni, stile |
| retrieval | il `SemanticIndex` | `AUTHORING_NOT_RETRIEVABLE` |

Tre categorie, che sono le tre severita' che `Report` ha da sempre: `error`,
`warning`, `info`. `ValidationReport.by_category()` le restituisce cosi', e la
tabella della scheda Validate e' quella.

**Non c'e' un validatore di authoring**, e le diagnostiche dei frame arrivano
dal resolver come su qualunque generazione — e' il contratto di V5, e si applica
a ogni collegamento. `frame_report()` resta la vista del pannello Frame e viene
usata nel referto **solo come ripiego** quando nessuna build e' arrivata a
risolvere: un errore a monte non deve far scomparire gli esiti dei frame, e un
esito mostrato due volte sarebbe rumore. (La prima scrittura lo faceva, e si
vedeva: `FRAME_CONVERTIBLE` compariva sia come `subject/head` sia come
`dragon_body/head`.)

«Build Component» passa dalla pipeline reale — Registry → Resolver → Traits →
Effects → Builder → Validation → Scene — perche' passa da `Session.build` su un
plugin installato per davvero. Nessuna chiamata a `trimesh` per simulare il
risultato: il punto 19 della milestone, ottenuto per costruzione invece che per
disciplina.

---

## 16. Il plugin generato, per esteso

Dal GLB del cavaliere, senza scrivere una riga di JSON a mano:

```text
knight_pack/
├ plugin.json                374 byte
├ components/
│  ├ body.json              1312     mesh-backed, un parametro, due socket
│  ├ head.json               535     mesh-backed, un socket
│  └ knight.json             817     composite: nessuna mesh, un figlio
└ meshes/
   ├ body.glb               1236     solo il nodo Body
   └ head.glb               1760     Head piu' i due occhi, non la spada
```

```json
{
  "id": "knight_pack", "version": "1.0.0", "type": "data",
  "name": "knight pack",
  "components": ["components/body.json", "components/head.json",
                 "components/knight.json"],
  "materials": [],
  "frame": {"growth_axis": "+Y", "front": "+Z", "up": "+Y"},
  "synonyms": {"paladin": ["knight"]}
}
```

```json
{
  "id": "knight_pack:body",
  "description": "A boxy knight body",
  "mesh": "../meshes/body.glb",
  "role": "torso",
  "tags": ["knight", "humanoid"],
  "provides": ["torso_mount"],
  "mounts": [{"capability": "head_mount", "socket_id": "neck"}],
  "sockets": [
    {"name": "base", "position": [0,0,0], "direction": [0,-1,0],
     "up": [0,0,1], "radius": 0.2},
    {"name": "neck", "position": [0,1,0], "direction": [0,1,0],
     "up": [0,0,1], "radius": 0.15, "capabilities": ["head_mount"]}
  ],
  "params": {"width": {"default": 1.0, "min": 0.3, "max": 2.5,
                       "type": "float", "transform": "scale_x",
                       "semantic_role": "width"}},
  "children": [{"id": "head", "component": "knight_pack:head", "level": 2,
                "requirement": {"capability": "head_mount"}}]
}
```

Tre proprieta' misurate di questo output:

* **nessun Python**: `list(path.rglob("*.py"))` e' vuoto, e il manifest non
  nomina `effects`, `styles`, `traits`, `archetypes`, `profiles` ne' `bindings`
  — le chiavi che in un plugin di codice nominano file Python. Nessuna
  definizione contiene `derived`, `callable`, `module`, `expression`,
  `entry_point` ne' `build`;
* **il riferimento alla mesh e' relativo**, quindi il plugin si puo' spostare:
  un test lo copia in un'altra cartella e lo ricarica;
* **solo la geometria necessaria**: `body.glb` ha 12 triangoli e `head.glb` ne
  ha 36, non i 60 del file d'origine, e le trasformazioni dei nodi sono
  conservate (la testa resta fra y = 1.03 e y = 1.37, non ricentrata).

Un componente rinominato non lascia il proprio vecchio JSON nella cartella: le
tre sottocartelle che l'emettitore possiede si riscrivono da zero, perche' un
file orfano e' un plugin che un domani si ricarica diverso.

---

## 17. Installare senza riavviare

`Session.reload_plugins(*paths)` e' il metodo nuovo, e il motivo per cui e' su
`Session` e non nell'authoring e' la regola 8 di `PROJECT-INDEX`: UI, CLI e test
passano da `Session`. Non scrive in un registry congelato — ne costruisce un
altro — e invalida quello che deve:

| cosa | perche' |
| --- | --- |
| `registry` | il vocabolario, ricaricato dalle stesse cartelle **piu'** quelle nuove |
| `_vocabolari` | la cache per stile: un vocabolario calcolato su prima nasconderebbe il componente appena installato |
| `_indice` | `component_index()` saprebbe accorgersene da solo (`is_current`), ma lasciarlo vivo vorrebbe dire pagare un confronto di firme per scoprire cio' che qui si sa con certezza |

Le cartelle nuove si **aggiungono**: chi installa un plugin non vuole perdere la
libreria che aveva, e un test lo verifica (23 plugin → 24, e `humanoid:body` e'
ancora li').

`install_plugin()` misura quattro cose, e non ne assume nessuna:

```text
C:/…/out/knight_pack | 3 componenti installati | 3/3 trovabili
                     | indice invalidato | ok
build knight: ok=True, 48 triangoli
```

| misura | come |
| --- | --- |
| installato | `registry.component(id)` non e' `None` per ciascuno |
| indice | l'indice di **prima** non e' piu' `is_current` sul registry nuovo |
| trovabile | una ricerca semantica per il nome del componente lo restituisce |
| costruibile | la radice passa da `Session.build` con `check=True` |

E dopo l'installazione, dalla stessa sessione, senza riavviare: il planner lo
vede (`vocabulary(prompt="a knight")` contiene `saga:knight`), il retrieval lo
trova, `paladin` ci arriva attraverso il ponte dichiarato in authoring, il
modello si costruisce e si esporta in `.glb` con l'esportatore che c'era.

---

## 18. Round-trip

Il test `test_an_existing_data_plugin_reopens_and_rebuilds_identically` fa il
giro che la milestone chiede:

```text
GLB → authoring → Save Plugin → chiudi → open_data_plugin → build
```

Cio' che si conserva, con la sua tolleranza:

| cosa | verifica |
| --- | --- |
| geometria | stessi triangoli (48), e il GLB risalvato e' **byte per byte** identico |
| trasformazioni | conservate nei vertici all'import, quindi conservate nella copia |
| socket | posizione, direzione, up e raggio a 1e-6 dopo il loader di produzione |
| gerarchia | `knight → body → head`, con livelli e `requirement` |
| parametri | strategia, intervalli, ruolo semantico |
| materiali | il `MaterialSpec` dichiarato, reinstallato e risolto |
| frame | plugin e componente, con la precedenza giusta |
| metadata | role, tags, provides, requires, description, synonyms |

### Che cosa **non** torna, e perche' e' dichiarato

Due cose, ed e' la risposta al punto 23 («se richiede metadata editor-only,
documenta il limite e non allargare V6»):

1. **la selezione degli oggetti.** La mesh di un componente salvato e' gia' un
   file per componente, quindi «quali nodi del GLB originale erano questi» non
   e' scritto da nessuna parte. Si e' scelto di **non** aggiungere un campo
   editor-only al formato: il draft tiene il GLB come `mesh_source` e al
   salvataggio lo copia byte per byte — niente riestrazione, niente perdita,
   `objects == ()`. Chi vuole ritagliare diversamente reimporta il GLB
   originale;
2. **la copertura.** E' il giudizio di chi costruiva, non un dato della
   libreria, e il plugin non la contiene per scelta (§2).

Non si aprono plugin di **codice**: un manifest senza `type: "data"` e'
rifiutato con `AUTHORING_PROJECT_INVALID` e il messaggio dice «un plugin di
codice si modifica a mano». Modificare Python automaticamente e' un percorso
diverso, con una fiducia diversa, e appartiene a Teach 3DGen.

Il round-trip del **progetto** di authoring e' separato e piu' stretto:
`project.to_dict()` e' identico prima e dopo il salvataggio, e il progetto
riaperto ricostruisce gli stessi 48 triangoli.

---

## 19. Prestazioni

`python tools/authoring_benchmark.py 7`, stessa macchina, nessuna rete, mediana
di 7 ripetizioni. Il target della milestone non e' «veloce», e' **interattivo**:
la colonna dice dove quel giudizio si applica, e la soglia dichiarata e' 100 ms.

| passo | mediana | peggiore | interattivo |
| --- | --- | --- | --- |
| import GLB (5 oggetti, 60 triangoli) | 3.39 ms | 4.12 ms | si |
| **staging a freddo (emit + registry)** | **131.52 ms** | 131.52 ms | — |
| preview rebuild (radice, detail 3) | 2.67 ms | 119.17 ms¹ | si |
| preview rebuild + quality gate | 3.66 ms | 4.80 ms | si |
| **slider update (un parametro)** | **1.17 ms** | 1.50 ms | si |
| Component Lab: una build | 3.21 ms | 4.23 ms | si |
| Component Lab: trait compatibili | 0.10 ms | 1.85 ms | si |
| detail level preview (un livello) | 2.57 ms | 4.15 ms | si |
| semantic search preview | 3.39 ms | 17.55 ms | si |
| planner preview (testo reso) | 0.17 ms | 0.35 ms | si |
| frame report (due archi) | 0.05 ms | 41.23 ms | si |
| validation (tutti i validatori) | 13.76 ms | 15.26 ms | — |
| save plugin (3 JSON + 2 GLB) | 10.26 ms | 11.37 ms | — |
| install: reload del registry | 56.93 ms | 60.27 ms | — |
| semantic reindex (100 componenti) | 17.02 ms | 17.70 ms | — |
| install and test (end to end) | 92.44 ms | 103.45 ms | — |
| salva progetto authoring | 0.57 ms | 0.80 ms | si |
| riapri progetto authoring | 4.73 ms | 7.45 ms | — |

¹ il peggiore della preview e' il riscaldamento del primo giro: la mediana e' la
misura.

Lettura onesta:

* **la riga che conta e' «slider update»: 1.17 ms.** E' la giustificazione
  dell'architettura di §4 — i parametri viaggiano nel piano, quindi muovere uno
  slider non riscrive il plugin e non ricarica il registry. Se l'impronta avesse
  incluso i parametri, quella riga sarebbe stata 130 ms e la UI sarebbe stata
  inutilizzabile;
* **lo staging a freddo costa 131 ms, una volta.** E' il prezzo dichiarato di
  far passare la preview dalla pipeline vera invece di simularla, e si paga alla
  prima build dopo un cambiamento strutturale (un socket spostato, un figlio
  agganciato). Dei 131 ms, ~57 sono il caricamento di 23 plugin — che e' il
  numero di V4 e non una regressione di V6;
* **la validazione completa e' 13.8 ms**, cioe' la si puo' premere spesso;
* **«install and test» e' 92 ms** per salvare tre JSON, due GLB, ricaricare 24
  plugin, reindicizzare 100 componenti e costruire la radice. Non e' istantaneo
  ed e' un gesto raro;
* **la preview a freddo non e' la preview**: dopo lo staging, ricostruire la
  radice a detail 3 costa 2.67 ms;
* il `frame report` e la `planner preview` non si misurano: confrontano stringhe.

I numeri di V5 non sono cambiati: nessuna modifica tocca il percorso di
generazione.

---

## 20. File modificati

Nuovi:

| File | Righe | Che cosa |
| --- | --- | --- |
| `app/authoring/__init__.py` | 42 | la faccia del pacchetto |
| `app/authoring/errors.py` | 42 | `AuthoringError` e i codici stabili |
| `app/authoring/model.py` | 718 | `AuthoringProject`, i `Draft*`, la copertura, la serializzazione |
| `app/authoring/inspect.py` | 175 | import e ispezione di un GLB, estrazione, export |
| `app/authoring/gizmo.py` | 240 | gizmo leggibili e snap deterministici |
| `app/authoring/emit.py` | 239 | progetto → plugin dati V4/V5 su disco |
| `app/authoring/lab.py` | 415 | `ComponentLab`, `ParamKnob`, `LabResult` |
| `app/authoring/variant.py` | 182 | `VariantRecipe` |
| `app/authoring/service.py` | 1816 | le operazioni, cioe' il contratto che V7 chiamera' |
| `app/ui/authoring_window.py` | 1627 | `AuthoringWindow` (7 schede) e `ComponentLabDialog` |
| `tests/authoring_fixtures.py` | 61 | il cavaliere in cinque pezzi, GLB veri |
| `tests/test_authoring.py` | 1446 | 112 test |
| `tests/test_component_lab.py` | 342 | 26 test |
| `tests/test_authoring_ui.py` | 459 | 25 test |
| `tools/authoring_benchmark.py` | 211 | le misure del §19 |
| `V6-RESULTS.md` | — | questo documento |

Modificati:

| File | Che cosa |
| --- | --- |
| `app/core/data_plugin.py` | `mesh` facoltativo (§3): le due regole del composite, `_params(has_mesh=…)`, `build` che restituisce `Piece(mesh=None)` |
| `app/core/session.py` | `Session.reload_plugins()` (§17) |
| `app/ui/main_window.py` | due azioni in barra: «Authoring» e «Component Lab», sulla **stessa** `Session` |
| `tests/test_api_freeze.py` | `reload_plugins` fra i metodi congelati di `Session` (additivo, §21) |

Il core non sa che l'authoring esiste, e si legge:

```bash
$ grep -rn "app.authoring\|app\.ui" app/core/ app/build/ app/geometry/ --include=*.py
$                                        # nessuna riga
```

E l'invariante di V4/V5 e' intatto con il livello nuovo sopra:

```bash
$ grep -rn "mesh_backed\|is_mesh\|kind == \"data\"" app/build/ app/core/ \
      --include=*.py | grep -v data_plugin.py | grep -v registry.py
$                                        # nessuna riga
```

---

## 21. Test

**1761 passed** (`python -m pytest -q`), da 1598. I 163 nuovi:

| file | quanti | che cosa |
| --- | --- | --- |
| `tests/test_authoring.py` | 112 | import e ispezione (nessuna inferenza, chiavi stabili, formati rifiutati, GLB troncato, sorgente mai modificata), selezione e creazione (un oggetto per componente, sei nomi rifiutati), composite senza mesh (48 triangoli, nessun `mesh` nel JSON, le due regole del loader), gerarchia (archi normali, opzioni, ordine, duplicato, ciclo rifiutato, geometria intatta), socket (tipo `Socket`, terna degenere, round-trip del gizmo fino al plugin, cinque snap, mirror e la sua inversa), capability (provides/accepts, una nuova e' dati, `add_mount`), metadata (arrivano al componente installato, un campo sconosciuto e' rifiutato, la copertura nei quattro valori non raggiunge il plugin e sopravvive nel progetto), preview semantica (l'indice vero, «sara' trovabile?», il testo reso del planner), variabilita' (transform misurato ×4, effect-backed con il neutro, sette legami ostili, solo le strategie installate, un parametro senza strategia, i ruoli della libreria, un trait installato che arriva), frame (plugin e componente, assi rifiutati, convertibile con la mossa, ambiguo senza mossa, `verify_frame`, non dichiarato = silenzio), materiali (le tre righe, il dichiarato che vince), detail level (quali nodi, e non e' LOD), validazione (tre severita', riferimento mancante, incompatibilita' dal resolver, mount senza socket, trovabilita'), salvataggio (il layout V4, lo schema, il percorso relativo, solo la geometria necessaria, le trasformazioni, nessun file orfano), installazione (senza riavvio, indice e vocabolario invalidati, trovabile, costruibile, la libreria resta), composizione mista, variant, progetto di authoring, plugin esistente riaperto, sicurezza (nessun Python eseguito, sei nomi forzati nel modello che non escono dalla cartella, due `uri` di glTF), e i due end-to-end |
| `tests/test_component_lab.py` | 26 | gli stessi sei assert su procedurale **e** mesh-backed, nessun ramo nel file letto per token, i trait compatibili che seguono la composizione risolta, i trait strutturali per selettore, un trait offerto che si applica davvero, gli effetti compatibili e uno applicato, i livelli di dettaglio misurati, variabilita' separata dal dettaglio, le variant (solo cio' che e' cambiato, la stessa geometria, il file minuscolo, il nome rifiutato, giallo→verde senza provider, nessuna variant di variant) |
| `tests/test_authoring_ui.py` | 25 | il flusso dichiarato nelle sette schede, la riga di contesto con le quattro risposte, la tabella degli oggetti, la selezione che arriva al servizio, la creazione dal form, un'operazione rifiutata che diventa una riga di stato e non un traceback, l'albero della gerarchia, l'aggancio dal form, gli snap dal pannello socket, solo le strategie installate (e `axis` assente), un parametro effect-backed dal form, il testo reso del planner, la ricerca vera, la preview dei livelli, la tabella dei frame con la mossa, la tabella di validazione, la build dalla finestra, i gizmo che non sono il modello, salva e installa, il dialogo del laboratorio (slider, etichette, reset), la variant salvata nel progetto, `Save as defaults` sul draft e non sulla libreria, e **la finestra che non contiene logica di authoring**, letta per token |

I 31 punti della milestone, e dove sono:

| # | richiesta | dove |
| --- | --- | --- |
| 1 | progetto di authoring separato dal plugin | `app/authoring/model.py`, §2; `test_the_authoring_project_round_trips_without_carrying_a_mesh` |
| 2 | import GLB | §5; `test_importing_a_glb_lists_its_objects_without_inferring_anything` |
| 3 | selezione di scena | §5; `test_selection_is_multiple_and_isolation_hides_the_rest` |
| 4 | create component from selection | §5; `test_a_component_from_a_selection_owns_exactly_that_geometry` |
| 5 | composite senza mesh | §3; `test_a_composite_component_has_no_mesh_and_still_builds` |
| 6 | gerarchia visuale | §6; `test_the_hierarchy_is_a_tree_of_ordinary_attachments`, `test_the_hierarchy_tree_mirrors_the_service` |
| 7 | riusare componenti esistenti | §7; `test_a_hierarchy_can_mix_imported_geometry_with_installed_components` |
| 8 | socket editor con gizmo | §8; `test_the_gizmo_is_readable_geometry_and_is_not_the_model` |
| 9 | snap helpers | §8; `test_snap_helpers_are_deterministic_arithmetic_on_the_bounds` (+5) |
| 10 | capability editor | §9; `test_capabilities_are_offered_with_who_provides_and_who_accepts` |
| 11 | semantic metadata + preview del planner | §9; `test_the_planner_preview_is_the_production_rendering` |
| 12 | semantic retrieval preview | §9; `test_the_search_preview_uses_the_real_semantic_index` |
| 13 | variability editor | §10; `test_only_installed_strategies_are_offered` |
| 14 | live parameter lab | §13; `test_moving_a_parameter_changes_the_geometry_on_both_backends` |
| 15 | frame editor | §11; `test_a_disagreeing_frame_is_named_with_its_move_and_never_converted` |
| 16 | material preview | §12; `test_the_material_preview_shows_imported_declared_and_effective` |
| 17 | detail-level preview | §3, §13; `test_detail_level_preview_shows_which_children_really_expand` |
| 18 | validation panel | §15; `test_validation_uses_the_real_validators_and_three_severities` |
| 19 | build/test dalla pipeline reale | §15; `test_the_generated_plugin_builds_through_the_whole_pipeline` |
| 20 | save plugin | §16; `test_the_saved_plugin_has_the_v4_layout` |
| 21 | install/test immediato | §17; `test_installing_adds_the_components_without_a_restart` |
| 22 | round-trip | §18; `test_an_existing_data_plugin_reopens_and_rebuilds_identically` |
| 23 | aprire un plugin esistente | §18, con i due limiti dichiarati |
| 24 | UX minima | §1; `test_the_context_bar_answers_the_four_questions` |
| 25 | livello programmatico separato dalla UI | §4; `test_the_same_plugin_can_be_built_entirely_without_a_user_interface`, `test_the_window_holds_no_authoring_logic` |
| 26 | stato di copertura | §2; `test_coverage_is_project_state_and_never_reaches_the_plugin` (4 casi) |
| 27 | Component Lab | §13; 12 test parametrizzati sui due backend |
| 28 | variant recipe | §14; `test_a_variant_recipe_is_a_configuration_and_never_a_mesh` |
| 29 | sicurezza | §16; `test_authoring_never_executes_python_from_a_model_or_a_plugin` + 9 |
| 30 | prestazioni | §19; `tools/authoring_benchmark.py` |
| 31 | test obbligatori | questa tabella, piu' i due end-to-end |
| 32 | niente fuori scope | §23 |

---

## 22. Regressioni e contratti cambiati

**Zero test rossi**, e nessun test esistente indebolito. Due cambiamenti
dichiarati.

1. **`mesh` e' facoltativo in una definizione di componente dati** (§3). E'
   l'unico cambiamento **non additivo** della milestone, ed e' un
   allargamento: ogni definizione che era valida prima lo e' ancora, e
   `tests/test_data_plugin.py` passa senza una modifica. Cio' che era un
   errore (`mesh` assente) ora e' un caso ammesso, con due nuove condizioni di
   rifiuto che prima non potevano verificarsi: nessun figlio, e un `transform`
   senza mesh.
2. **`Session.reload_plugins`** e' un metodo nuovo (§17), quindi
   `tests/test_api_freeze.py` e' stato aggiornato: quella riga di diff **e'** la
   decisione, come dice il file stesso. Additivo: chi non lo chiama vede il
   comportamento di prima, cioe' un registry caricato una volta e congelato.

### Un difetto trovato e corretto, nella UI

`ComponentLabDialog` aggiornava i numeri accanto agli slider solo dentro
`on_slider`, quindi dopo `Reset` o `Randomize` le etichette restavano al valore
di prima mentre la geometria era cambiata. Trovato da
`test_the_component_lab_dialog_reflects_the_lab`, corretto spostando la
sincronizzazione in `rebuild()` — che e' il posto dove si sa che qualcosa e'
cambiato.

### Due cose scoperte scrivendo, e documentate dove servono

* **`Component.children` e' una callable che puo' alzare `KeyError`** con i soli
  valori predefiniti, perche' legge valori che il resolver deriva dal padre
  (`humanoid_anatomical:torso` vuole `height` e `hip_width`). Non e' un difetto:
  e' la ragione per cui `ComponentLab.subtree()` **risolve** invece di leggere
  gli attachment (§13). Scritto accanto al codice.
* **Un composite nasce senza innesti**, quindi il resolver dice `NO_MOUNTS` e i
  figli non si attaccano. E' il contratto che c'era, e la risposta e'
  `add_mount` (§4) piu' una diagnostica che lo nomina, non un socket inventato
  automaticamente.

### Difetti preesistenti non toccati

* `MATERIAL_REDECLARED` su `tree_stylized`: invariato, resta in ogni report del
  registry — e adesso compare anche nel referto di validazione dell'authoring,
  perche' quel referto include quello del registry;
* `repair_brief` che mescola le `alternatives` fra voci dello stesso codice
  (debito 26): invariato;
* un figlio dichiarato nel piano che scompare in silenzio a `detail_level 1`
  (debito 21): invariato;
* l'impronta di contenuto ricalcolata a ogni caricamento (debito 20): adesso si
  paga anche a ogni staging, e con un plugin grande sara' la prima cosa da
  mettere in cache.

---

## 23. Definition of Done

| # | Criterio | Esito |
| --- | --- | --- |
| 1 | suite verde | ✅ **1761 passed** (erano 1598) |
| 2 | un GLB diventa un data plugin dalla UI senza editare JSON | ✅ §16, e la finestra non contiene logica di authoring |
| 3 | componenti e composite gerarchici | ✅ §3, §6: radice senza mesh, 48 triangoli dai figli |
| 4 | sockets/capability authorabili visualmente | ✅ §8, §9: gizmo leggibili, snap, elenco delle 27 capability |
| 5 | params / semantic role / effect binding authorabili | ✅ §10: solo le strategie installate, sette legami ostili rifiutati |
| 6 | Component Lab su procedurale e mesh-backed | ✅ §13: 12 test parametrizzati sui due backend |
| 7 | una configurazione si salva come variant senza duplicare la geometria | ✅ §14: < 700 byte, nessun `.glb` |
| 8 | il plugin generato si installa e il SemanticIndex lo trova, senza restart | ✅ §17: 3/3 trovabili, indice invalidato |
| 9 | il flusso programmatico esiste separato dalla UI | ✅ §4: `app/authoring/` non importa Qt, e un test costruisce tutto senza finestre |
| 10 | nessun Python eseguito | ✅ §16: `sources == ()`, `sys.path` intatto, i `.py` restano sul disco |
| 11 | V7 non implementata | ✅ §24 |

Fuori scope e **non iniziati**, come chiesto: AI concept decomposition, giudizio
AI di idoneita' o visivo, prompt di generazione di codice, generazione di Python,
integrazione di provider per l'authoring, ciclo ricorsivo di Teach,
`Session.modify`, editing di facce arbitrarie, sculpting, editor UV, rigging,
auto-segmentation, marketplace.

---

## 24. Debiti verso V7

* **Il gizmo non si trascina.** Il picking nel viewport non esiste: un socket si
  sposta con gli snap e con i campi numerici. Aggiungerlo vuol dire un ray cast
  contro la scena e una nozione di «maniglia afferrata», cioe' codice nuovo nel
  viewport — non nel contratto.
* **La selezione e' per nodo della scena, non per facce.** Un GLB che arriva in
  un pezzo unico non si puo' dividere dentro 3DGen. E' il caso in cui
  l'authoring non aiuta, ed e' dichiarato: la selezione di facce richiederebbe
  un editor mesh, e l'auto-segmentation e' un'altra milestone.
* **Riaprire un plugin non recupera la selezione degli oggetti** (§18). Il GLB
  per componente si copia byte per byte, quindi non si perde niente; ma chi
  vuole ritagliare diversamente reimporta il file originale. Il campo
  editor-only che lo eviterebbe non e' stato aggiunto per scelta.
* **Una variant con trait o effetti non si incorpora in un composite** (§14).
  Diagnosticato, non risolto. La via dichiarata e' un parametro `effect`-backed
  sul componente base.
* **Non c'e' una variant di una variant** (§14), e non c'e' una libreria di
  variant condivisa: vivono nel progetto di authoring e in un file JSON. Se V7
  ne avra' bisogno come cittadine di prima classe, la domanda e' se diventino
  componenti installabili — e la risposta onesta oggi e' che un composite
  meshless con un figlio ci va vicino, ma avrebbe bisogno di socket che solo la
  base conosce.
* **Lo staging costa 131 ms a freddo** (§19), e con un progetto di cinquanta
  componenti crescera' con il numero di GLB da riscrivere. La strada e'
  riemettere solo i file cambiati, che vuol dire un'impronta **per componente**
  invece che per progetto.
* **L'impronta di contenuto del registry si ricalcola a ogni staging** (debito
  20 di V4, ora piu' caro): ~2.7 ms per GLB, pagati a ogni cambiamento
  strutturale. La cache su mtime + dimensione e' la prima ottimizzazione che
  servira'.
* **Il filtro di rilevanza del vocabolario fa ancora la domanda di V3** (debito
  12). Il Component Lab la fa giusta, perche' risolve la composizione (§13), ma
  il retrieval ha solo la rosa: la correzione vera resta seguire gli
  `Attachment` dichiarati dentro `app/core/planner/vocabulary.py`.
* **La copertura esiste e non e' collegata a niente**, ed e' deliberato: V6 la
  rappresenta, V7 la decidera'. Oggi la imposta l'utente, e nessuna parte del
  sistema la legge per fare qualcosa.
* **Nessun componente di prova e' stato aggiunto alla libreria installata.** I
  plugin dati di V6 nascono nei test e nelle cartelle temporanee, come quelli di
  V4 e V5: la libreria resta 23 plugin e 97 componenti, tutti di codice. Il
  giorno in cui un plugin autorato con questo strumento entra in
  `app/plugins/`, sara' una milestone di contenuto con la sua misura.
* **I debiti di V5 restano tutti**: il conflitto fra un trait generico con
  `scope: subtree` e uno selettivo, un parametro dati che pilota solo knob
  numerici, i 259 ruoli semantici non riassegnati, 18 plugin su 23 senza frame,
  il frame che non converte, il banco dei sei prompt senza un modello di
  frontiera. E quelli di V3/V3.5 e V4: il retrieval che mette le parti davanti
  agli interi, il `MockPlanner` che non scrive trait strutturali, `fx:bend` con
  `scope: "model"` che si perde, il prototipo strutturale che non si crea dal
  nulla, i materiali glTF come colore, un solo `mesh` per componente, il GLB non
  incorporato in `.my3d`.

---

## 25. Riprodurre le misure

```bash
python -m pytest -q                                   # 1761 passed
python -m pytest -q tests/test_authoring.py           # i 112 del servizio
python -m pytest -q tests/test_component_lab.py       # i 26 del laboratorio
python -m pytest -q tests/test_authoring_ui.py        # i 25 della finestra
python tools/authoring_benchmark.py 7                 # la tabella del §19
```

I contratti, letti dal codice invece che da questo documento:

```bash
grep -rn "app.authoring\|app\.ui" app/core/ app/build/ app/geometry/ --include=*.py
grep -rn "mesh_backed\|is_mesh\|kind == \"data\"" app/build/ app/core/ --include=*.py \
  | grep -v data_plugin.py | grep -v registry.py
grep -rn "PySide6\|QtWidgets" app/authoring/
```

Un plugin costruito senza aprire una finestra, scritto su disco da ispezionare a
mano:

```bash
python -c "
import sys, tempfile; sys.path[:0] = ['.']
from pathlib import Path
from tests.authoring_fixtures import write_knight_glb
from tests.test_authoring import knight_project
from app.authoring import AuthoringService
tmp = Path(tempfile.mkdtemp())
svc = AuthoringService()
svc.create_authoring_project('knight_pack', destination=str(tmp / 'out'))
svc.import_model(write_knight_glb(tmp / 'source'))
knight_project(svc)
print(svc.validate().describe())
print(svc.save_plugin())
svc.close()"
```

E la finestra, per guardarla:

```bash
python -c "
from PySide6.QtWidgets import QApplication
from app.ui.viewport import configure_opengl
configure_opengl(); app = QApplication([])
from app.ui.authoring_window import AuthoringWindow
w = AuthoringWindow(); w.show(); app.exec()"
```
