# Che cosa manca

Aggiornato il 15 ottobre 2026, dopo le milestone V1 (indice semantico unico),
V2 (degradazione semantica spiegabile), V3 (selettori strutturali e identita'
stabile dei nodi), V3.5 (robustezza del contratto del planner), V4 (componenti
mesh-backed dichiarati in dati), V5 (variabilita' semantica e convenzione
d'asse come contratto), V6 (authoring dei componenti) e V7 (Teach 3DGen).

Lo stato: **2070 test verdi**, un solo percorso dal prompt al modello, 23
plugin di codice piu' i plugin dati che chiunque installi o impari, 97
componenti, API congelate. Davanti al planner c'e' uno stadio di
retrieval — il carico mandato al modello dipende dalla rosa di componenti
rilevanti, non da quanti plugin sono installati — dietro c'e' una scala di
degradazione, i trait strutturali non dipendono piu' dai nomi che il planner
da' ai nodi, e adesso il planner li **usa**.

Misurato, non dichiarato: con un LLM reale le generazioni riuscite sugli otto
prompt di `PRODUCT-AUDIT.md` passano da 3 su 8 a 6 su 8 con V1, a 7 su 8 con
V2 e V3 e a 8 su 8 con V3.5 (una delle otto per ripiego dichiarato sul planner
locale, con tutti i fornitori free-tier a rate limit); i `413
payload_too_large` da 8 su 8 a zero; `jeep` da «casco» a
«vehicle_stylized:car»; «sei ruote» funziona con qualunque nome della radice e
«quattro braccia» funziona per la prima volta. Con V3.5 «una jeep con sei
ruote» **costruisce davvero sei ruote** (228 → 284 triangoli) perche' il
modello scrive `vehicle:wheel_count`, e lo fa su tre giri indipendenti. Vedi
`V1-RESULTS.md`, `V2-RESULTS.md`, `V3-RESULTS.md` e `V3.5-RESULTS.md`. Con V4 un GLB diventa un
componente usabile **senza una riga di Python**: `paladin` degrada su un
cavaliere importato senza nessun binding scritto a mano, e `wheel_count` clona
ruote procedurali su una scocca mesh-backed. Vedi `V4-RESULTS.md`. Con V5 un
componente e' una **famiglia di forme**: sei trait di proporzione relativa
colpiscono un parametro procedurale e un parametro di un GLB attraverso lo
stesso `semantic_role`, un parametro dati puo' pilotare un effetto installato
(`curvature` → `fx:bend`), squash/elongate/taper/twist esistono come effetti
normali, e la convenzione d'asse e' diventata una dichiarazione che il resolver
confronta: la chimera pesce + drago + ali non passa piu' in silenzio. Vedi
`V5-RESULTS.md`. Con V6 **un GLB diventa un plugin dati senza scrivere JSON a
mano**: si importa, si selezionano gli oggetti, si creano componenti e
composite gerarchici, si disegnano socket e capability, si dichiarano parametri
con una strategia installata, si valida con i validatori veri, si salva e si
installa — senza riavviare, e con il `SemanticIndex` che lo trova subito. E le
operazioni esistono **prima** come chiamate: `app/authoring/` non importa Qt in
nessun file, e un test costruisce un plugin intero senza aprire una finestra,
perche' e' la strada che Teach 3DGen dovra' usare. Vedi `V6-RESULTS.md`.
Con V7 **3DGen impara un concetto invece di rigenerarlo**: si decompone
«dragon» in un'ontologia con due passi di prompt, si confronta la gerarchia con
la libreria installata e ne escono i quattro stati da **evidenze nominate** (non
da una soglia su un punteggio), un giallo diventa verde con una `VariantRecipe`
senza duplicare geometria, un rosso produce una specifica tecnica che 3DGen
decide e un prompt che e' un contratto, la risposta di un modello entra in
staging — e se e' Python **non viene eseguita** finche' qualcuno non lo decide —
e cio' che si accetta si installa, reindicizza e ricalcola la copertura. Quando
ogni mandatory e' verde si emette il composite della radice e il concetto e'
`LEARNED`. La prova finale: una `Session` **normale**, con il planner locale e
nessuna rete, fa `shortlist("dragon")` e trova `dragon_pack:dragon` al primo
posto, e `generate("a cartoon dragon")` lo costruisce. Vedi `V7-RESULTS.md`.

Quello che segue e' cio' che non c'e' — scritto per essere onesto, non per
essere lungo.

---

## Debiti veri

**1. L'editing a voce non c'e' piu'.** `Session.modify("fai le ruote piu'
grandi")` girava sulla pipeline storica ed e' stato tolto con lei. Oggi si
modifica il piano e si chiama `regenerate()`. Perche' torni servono due cose:
un planner che sappia **riscrivere** un piano esistente invece di scriverne uno
nuovo, e un modo di dire all'LLM che cosa c'e' gia' (il piano corrente e' gia'
JSON, quindi e' meno lavoro di quanto sembri).

**2. La generazione da un'immagine non c'e' piu'.** Stessa ragione: leggeva una
foto e produceva un `GenerationPlan`. Il pulsante nella UI e' nascosto. Serve
riscrivere `reference.py` perche' produca un piano di composizione — misure e
colore dell'immagine diventano parametri e materiali, non piu' un template.

**3. Il planner locale ragiona per parole.** Senza rete sceglie i componenti
per corrispondenza fra le parole della richiesta e nomi, tag e descrizioni. Un
plugin che dimentica i tag e' invisibile a quel planner (non all'LLM vero), e il
ripiego peggiora in silenzio. Un test lo verifica sui plugin nostri; per quelli
di altri servirebbe un avviso al caricamento.

V1 ha reso il problema piu' netto, V2 ne ha tolto meta'. Il planner locale
sceglie dentro la rosa e a pari punteggio segue la rilevanza invece
dell'alfabeto, quindi «una jeep» non e' piu' un casco. Resta vero che senza rete
la scelta e' una corrispondenza di parole: «un albero fantasy» prende
`fantasy:wing` perche' «fantasy» colpisce il nome del plugin prima dei tag
dell'albero.

**3-bis. ~~Non c'e' degradazione semantica.~~ Fatto in V2.** `jeep`, `suv` e
`camion` arrivano a `vehicle_stylized:car` con la spiegazione
dell'approssimazione; `robot` e `sottomarino` dichiarano che non c'e' niente di
adatto invece di costruire un'omonimia. La gerarchia si ricava dai dati
installati (`subject_capabilities`), non dal catalogo: installare un componente
basta a renderlo candidato, senza scrivere un binding.

**3-ter. ~~I trait strutturali sono legati a un percorso letterale.~~ Fatto in
V3.** `prototype="car/wheel_fl"` voleva dire che lo stesso piano funzionava con
una radice chiamata `car` e moriva con `jeep`, e che `character:arm_count` non
funzionava su **nessun** corpo installato. Adesso il prototipo si sceglie con il
selettore che ogni regola dichiarava gia' (`role`, `capability`, `tags`,
`components`), il tie-breaking e' documentato in testa a
`app/core/structural.py`, e nessuna delle tre extension contiene piu' un
percorso. 4/6/8 ruote con qualunque nome della radice, 2/4/6 braccia con la
catena anatomica completa, 1/3/9 code.

**3-quater. ~~Un componente esiste solo se un modulo Python lo costruisce.~~
Fatto in V4.** Un plugin `type: "data"` dichiara i componenti in JSON accanto a
GLB/glTF e installa `Component` normali: niente import, niente percorso di
modulo, niente callback, niente expression, nessun file fuori dalla propria
cartella. Il resolver, il builder, gli effetti, il layout, il retrieval e
l'export non hanno un ramo per loro — le tre righe che sanno dell'esistenza dei
plugin dati stanno tutte in `app/core/registry.py`. Un cavaliere importato si
monta su un corpo procedurale e viceversa per capability, `paladin` degrada su
di lui senza binding, `wheel_count` gli attacca 4 o 6 ruote procedurali,
`fx:bend` ne deforma vertici e innesti con la stessa mappa, e `.my3d` lo
rigenera senza incorporare il GLB.

**4. Un ginocchio non si piega — ma solo nel plugin `humanoid` storico.** Li'
coscia, polpaccio e piede sono **fratelli** appesi ai socket della gamba, non
una catena, e l'arto si muove rigido. In `humanoid_anatomical` la catena e'
vera (`hip → thigh → knee → calf → ankle → foot`, e `shoulder → upper_arm →
elbow → forearm → wrist → hand`): verificato espandendo il grafo nel
PRODUCT-AUDIT. Resta da decidere se il plugin storico va allineato o
deprecato.

**4-bis. Il plugin `humanoid` storico non dichiara nessuna `LayoutRegion`.**
Quattro braccia su quel corpo si risolvono sui socket ordinari del resolver
invece di essere distribuite: strutturalmente corretto, visivamente mediocre. E'
la stessa decisione del punto 4 — allineare o deprecare — vista da un altro lato.
Vale anche al contrario: nove code di volpe su una regione disegnata per una coda
sola escono corrette e brutte. Correttezza strutturale e qualita' di layout sono
due giudizi distinti, e quello che manca e' il secondo.

**5. Nessuno appoggia il modello a terra, se non lo si chiede.**
`Scene.ground_offset` esiste e `to_scene(ground=True)` lo fa, ma non c'e' un
effetto `ground` nello stadio `final`: chi costruisce senza passare per la
scena ottiene il modello dove i componenti l'hanno messo.

**6. La compenetrazione si misura con scatole allineate agli assi.** Due lame
incrociate risultano sovrapposte senza toccarsi. Le soglie sono larghe apposta,
ma resta un compromesso.

**7. ~~`app/build/` non e' sotto controllo di versione.~~ Fatto prima di V5.**
Il pattern e' ancorato (`/build/`) e i sei moduli sono tracciati dal commit
`f5f0d8b`, che e' anche il checkpoint V4. Per cinque milestone l'elenco dei file
modificati era incompleto per costruzione; da V5 non lo e' piu'.

**8. Un figlio dichiarato nel piano scompare in silenzio a `detail_level 1`.**
`validate_plan` gli assegna `level 2` per default e `wanted_at(1)` e' falso:
niente nodo, niente diagnostica, `ok=True`. E' la stessa famiglia del difetto
che V3.5 ha chiuso per i trait — una richiesta persa senza referto — e si vede
con un piano a `detail_level: 1` e un figlio senza `level`. Trovato scrivendo il
benchmark di V4, non corretto.

---

## Cose che sarebbero utili, e non urgenti

- **Stili veri.** La struttura c'e' ed e' provata (un plugin puo' registrare
  `cartoon` che estende `low_poly` e cambia due numeri). Manca qualcuno che ne
  scriva uno completo, e finche' non succede non si sa quali numeri servano
  davvero.
- **Un plugin realistico.** Un test dimostra che il core lo reggerebbe: un
  componente con parametri, figli, vincoli e geometria completamente diversi che
  fornisce `head_mount`. Scriverlo per intero e' un'altra fase.
- ~~**Il vocabolario cresce con i plugin.**~~ **Fatto in V1.** Il carico segue
  la rosa: 9.991 token interi contro 1.469-3.788 sugli otto prompt, e 38.453
  contro 560-1.236 su una libreria sintetica da mille componenti.
- **Il thesaurus predefinito e' ancora nel codice.** `app/assets/semantic.py`
  contiene ~25 voci italiane di dominio. Il meccanismo per portarle fuori esiste
  ed e' gia' usato (`plugin.json` → `synonyms`, letto da `Registry.synonyms()`):
  manca spostarle nei plugin che possiedono quelle parole e lasciare vuoto il
  dizionario predefinito. Non e' stato fatto in V1 perche' cambierebbe anche la
  ricerca nella libreria degli asset, che era fuori scope.
- **La ricerca non fa stemming.** `persona` non trova `person`, `ruote` non
  trova `wheel` se non attraverso un sinonimo dichiarato. Oggi si compensa con i
  ponti nel manifest; con una libreria grande e bilingue servira' altro. Il
  punto di innesto c'e' gia': `RemoteEmbedder` e' nell'interfaccia e non e' mai
  stato provato.
- **L'indice dei componenti non viene persistito.** La persistenza e'
  implementata e testata (si attiva passando un `path`), ma `Session` la tiene
  in memoria: con 96 componenti l'indice costa 15 ms e un file in piu' nella
  home dell'utente non si ripaga. Con migliaia di componenti va acceso.
- **Il ripiego del retrieval quando non si trova niente e' un cerotto.** Sotto
  120 componenti si mostra tutta la libreria (il comportamento di prima di V1);
  sopra, si manda una fetta in ordine di id e lo si dichiara. La degradazione di
  V2 lavora sul **concetto**, non sulla rosa: quando e' il retrieval a non
  trovare niente, il ripiego resta quello.

- ~~**Un trait inventato uccide ancora un piano valido.**~~ **Fatto in V3.**
  Un `trait` o uno `structural_trait` sconosciuto diventa
  `UNKNOWN_TRAIT_SKIPPED` — avviso, non errore — viene tolto dal piano e resta
  leggibile in `skipped()`. Il test che pretendeva `graph is None` e' stato
  cambiato apposta, con il perche' scritto accanto. Il prompt «robot con quattro
  braccia» passa da 0 a 412 triangoli.

  ~~Resta vero per un **effetto**.~~ **Fatto in V3.5.** Un `params` annidato su
  un effetto **noto** si srotola, ma solo quando non c'e' niente da decidere:
  ogni chiave interna e' un parametro dichiarato da quell'effetto e nessuna
  entra in conflitto con un valore gia' presente. Allora
  `EFFECT_PARAMS_FLATTENED`, avviso, e la forma annidata e quella piatta
  convergono sullo **stesso** grafo e sulla **stessa** geometria. Una chiave
  sconosciuta, un conflitto, un `params` che non e' un oggetto e un effetto
  inesistente restano fatali: la politica ha tre categorie e si distinguono per
  quanta scelta richiedono, non per gravita'.

- ~~**Il planner non chiama i trait strutturali.**~~ **Fatto in V3.5.** E la
  diagnosi era sbagliata su un punto che cambia tutto: `instance_count` non era
  un trait inventato, era **l'alias di `std:instance_count`**, installato, e
  l'unico trait strutturale che il modello vedesse. Cinque cause misurate,
  nessuna nel motore: il prompt di sistema non nominava ne' `traits` ne'
  `structural_traits`; una `adaptation` di concept non puo' **mai** diventare un
  trait strutturale (`_supported_adaptations` alimenta solo
  `materialized_traits`); il titolo della sezione era una didascalia e non una
  chiave JSON; degli alias se ne mostrava uno su tre, buttando proprio quelli
  italiani che una richiesta usa (`braccia`, `ruote`); e sul prompt delle
  quattro braccia `character:arm_count` **non era nel vocabolario**, perche'
  nessun ponte collegava `braccia` a `braccio` e la rosa non conteneva nessun
  braccio. Corretto nel prompt, nei metadati del vocabolario e nei manifest dei
  plugin. Con un LLM reale il modello scrive `structural_traits` sui due prompt
  che chiedono un conteggio, in tre giri su tre.

- **Creare un prototipo da zero per selettore non c'e'.** Se nessuna istanza del
  pezzo cercato e' dichiarata da nessuna parte, la riscrittura si ferma con
  `STRUCTURAL_PROTOTYPE_NOT_FOUND`. Con un percorso letterale il nodo si poteva
  creare dal nulla, e quella strada esiste ancora per chi dichiara un percorso;
  per il selettore servirebbe scegliere il padre per capability, mount o
  regione. Nessuna delle tre extension installate ne ha bisogno.

- **L'identita' stabile si sposta se si cancella un fratello** con la stessa
  firma. E' derivata da (padre, ref, requisito, ordinale), quindi l'ordinale dei
  fratelli che seguivano quello cancellato cambia. Finche' non esiste una strada
  che cancella nodi — cioe' finche' non torna `Session.modify` — e' un confine
  dichiarato; dopo, servira' un contatore persistito, cioe' un cambio deliberato
  del formato del piano.

- ~~**[V4] Il vocabolario dei parametri di un componente dati e' una scala e
  nient'altro.**~~ **Fatto in V5.** Un parametro dichiara `transform` **oppure**
  `effect`, mai entrambi e mai nessuno dei due. Un `effect` nomina un
  `EffectSpec` installato e uno dei suoi knob dichiarati, e tutta
  l'implementazione e' `EffectPipeline._from_params`: da li' in poi una piega
  chiesta da `curvature = 0.9` e una piega scritta nel piano sono la stessa
  cosa, con la stessa validazione. Un valore che pilota un effetto puo' essere
  negativo (il verso di una piega e' un segno), una scala no. Un plugin dati non
  puo' nemmeno **nominare** un callable, un modulo, un'espressione o una
  matrice: dieci casi parametrizzati lo verificano.
- **[V5] Un parametro dati pilota solo knob numerici.** L'`axis` di `fx:bend`
  resta quello che l'effetto dichiara come predefinito, quindi una coda che
  cresce lungo +Z non puo' dire, dai dati, che la sua piega va calcolata lungo
  Z. Serve ammettere un valore **costante** per gli altri knob del legame, e va
  deciso se sia una terza strategia o un campo in piu' su quella esistente.
- ~~**[V4] `frame` diagnostica, non converte.**~~ **Promosso a contratto in
  V5.** Un plugin (o un singolo componente) dichiara `up`, `front` e
  `growth_axis`, e il resolver confronta le dichiarazioni di padre e figlio a
  ogni collegamento. Quattro esiti: `compatible`, `convertible` (entrambe le
  terne complete, quindi la rotazione e' una sola e la diagnostica la nomina
  insieme all'`fx:rotate` che la applicherebbe), `ambiguous` (una terna
  incompleta: la rotazione non e' determinata), `undeclared`. La chimera pesce +
  testa di drago + due ali produce **tre avvisi espliciti** dove prima non
  produceva niente, fatali con `frame_policy: strict`.

  **Continua a non convertire, per scelta.** Ruotare un figlio contro il socket
  che il padre ha dichiarato sarebbe un secondo placement system: la rotazione
  si calcola e si nomina, e chi legge decide. Dei due esiti che la milestone
  ammetteva per il drago, V5 ha scelto il secondo.
- **[V5] 18 plugin su 23 non dichiarano un frame**, quindi per loro il contratto
  non dice niente, ed e' il suo limite dichiarato. Dichiararli e' lavoro di
  libreria, e per alcuni (`space:planet`, `primitives:block`) la domanda «dov'e'
  il davanti di una sfera» non ha una risposta: un frame falso sarebbe peggio di
  nessun frame.
- **[V5] `growth_axis` non entra nel confronto**, ed e' giusto — un arto che
  cresce +X su un torso che cresce +Y e' la convenzione, non un difetto — ma
  vuol dire che un asset il cui asse di crescita contraddice il proprio socket
  `base` resta un problema solo di `verify_frame`, cioe' di authoring.
- **[V4] I materiali del glTF arrivano come colore, non come materiale.** Un
  `baseColorFactor`, i colori per vertice o una texture diventano la tinta di un
  `MaterialSpec` «imported» piu' i colori conservati sulla mesh. Niente UV,
  niente PBR, nessun sistema nuovo.
- **[V4] Un solo `mesh` per componente**: niente LOD dichiarati, niente
  varianti. `app/build/optimize.py` sa fare i LOD per decimazione e nessuno
  glieli chiede dai dati.
- **[V4] L'impronta del contenuto si ricalcola a ogni caricamento** leggendo
  tutti i file referenziati: ~2.7 ms per GLB, ~5.4 ms per componente dati
  contro ~1.4 ms per plugin di codice. Con centinaia di componenti dati va messa
  in cache (mtime + dimensione come chiave), ed e' il primo numero che peggiora.
  E' anche cio' che rende diagnosticabile un GLB cambiato a versione ferma, per
  cui non si toglie, si mette in cache.
- **[V4] Il GLB non e' incorporato in `.my3d`**, per scelta: un progetto resta
  rigenerabile solo finche' il plugin e' installato, e `changed_plugins` dice
  quando non lo e' piu' nello stesso stato. Incorporarlo e' una decisione di
  formato.
- **La soglia `MIN_CONFIDENCE = 0.08` e' tarata su 97 componenti.** Con migliaia
  va riverificata: troppo bassa produce omonimie, troppo alta rifiuta
  approssimazioni legittime.
- **La correzione unica non e' ancora dimostrata su un modello vero.** Lo
  structured output e la catena di failover ora funzionano davvero (V1 ha
  misurato 6 generazioni su 8 con provider reali), ma la riparazione non ha mai
  migliorato un piano in nessuna delle misurazioni: l'unico caso in cui e'
  partita ha dato lo stesso punteggio prima e dopo. V3.5 l'ha fatta **partire**
  su un codice nuovo — `STRUCTURAL_PROTOTYPE_NOT_FOUND`, dove prima non partiva
  affatto — e nel giro finale il prompt 3 e' tornato verde con `repaired=True`.
  Resta un caso solo: non e' ancora una dimostrazione.

- **[V5] Un trait generico con `scope: subtree` e un trait selettivo per ruolo
  si pestano i piedi.** Scrivono lo stesso canale `(nodo, parametro)` sulla
  parte selezionata, quindi `TRAIT_RULE_CONFLICT` li scarta entrambi — e' la
  politica che c'era, che rifiuta di scegliere al posto dell'autore. La forma
  che funziona per «creatura piu' grande con la testa enorme» e' `part_scale`
  con `scope: local` sulla radice piu' `head_scale`. La via d'uscita e' un
  selettore **nella richiesta** (`{"trait": "part_scale", "role": "head"}`),
  che e' un cambio dello schema del piano e della sua versione.
- **[V5] I ruoli semantici della libreria installata non sono stati
  riassegnati.** `humanoid:mouth.width` dichiara `semantic_role="girth"`, e
  `std:width` lo raggiunge per quella via invece che per la sua. Una revisione
  dei 259 ruoli dichiarati (134 `girth`, 113 `length`, 12 `ratio`) cambierebbe
  anche `std:body_mass`, quindi e' una milestone di contenuto con la sua misura.
- **[V5] `repair_brief` mescola le `alternatives` fra voci dello stesso
  codice.** Con tre `FRAME_CONVERTIBLE` su tre nodi le voci sono tre, con il
  `where` giusto, ma il testo reso puo' mostrare la mossa di un nodo accanto al
  messaggio di un altro. Riguarda tutti i codici allo stesso modo ed e' presente
  da V3.5.
- ~~**[V4] Un solo `mesh` per componente, e un composite dati non si puo'
  dichiarare.**~~ **Mezzo fatto in V6.** `mesh` e' diventato **facoltativo**: un
  componente dati senza mesh e' un contenitore, `Piece.mesh = None`, e la
  geometria la portano i figli — che e' la forma normale di un concetto
  complesso e quella che Teach 3DGen usera'. Due regole lo rendono non ambiguo:
  senza mesh **servono** children, e senza mesh **niente** `transform` (scalare
  i soli socket sposterebbe i figli senza rimpicciolirli). Restano senza LOD
  dichiarati e senza varianti di mesh: quella meta' del debito e' aperta.

- **[V6] Il gizmo dei socket si legge e non si trascina.** Nel viewport non c'e'
  picking, quindi un innesto si sposta con gli snap e con i campi numerici.
  Aggiungerlo vuol dire un ray cast contro la scena e una nozione di «maniglia
  afferrata»: codice nuovo nel viewport, non nel contratto. Dichiarato invece
  che finto con un gizmo che non si puo' prendere.
- **[V6] La selezione e' per nodo della scena, non per facce.** Un GLB che
  arriva in un pezzo unico non si puo' dividere dentro 3DGen, ed e' il caso in
  cui l'authoring non aiuta. La selezione di facce richiederebbe un editor mesh
  completo; l'auto-segmentation e' un'altra milestone.
- **[V6] Riaprire un plugin dati non recupera la selezione degli oggetti.** La
  mesh per componente si copia byte per byte, quindi non si perde niente — ma
  chi vuole ritagliare diversamente reimporta il GLB originale. Il campo
  editor-only che lo eviterebbe non e' stato aggiunto per scelta: il plugin e'
  una libreria, non uno stato di lavoro.
- **[V6] Una variant con trait o effetti non si incorpora in un composite.** Un
  `Attachment` porta `params`; trait ed effetti sono cose del **piano**.
  `embeddable` dice quale delle due si ha davanti e
  `AUTHORING_VARIANT_NOT_EMBEDDABLE` lo segnala invece di perderlo in silenzio.
  La via dichiarata e' un parametro `effect`-backed sul componente base.
- **[V6] Lo staging a freddo costa 131 ms** — emettere il plugin piu' caricare
  24 plugin — e si paga a ogni cambiamento strutturale. E' il prezzo dichiarato
  di far passare la preview dalla pipeline vera invece di simularla, e muovere
  uno slider costa 1.2 ms perche' i parametri viaggiano nel piano. Con un
  progetto da cinquanta componenti servira' riemettere solo i file cambiati,
  cioe' un'impronta **per componente** invece che per progetto — e rende piu'
  caro il debito dell'impronta di contenuto ricalcolata a ogni caricamento.
- ~~**[V6] La copertura esiste e non e' collegata a niente.**~~ **Decisa in
  V7.** `app/teach/coverage.py` confronta la gerarchia di un concetto con la
  libreria installata e produce i quattro stati da **evidenze nominate**:
  `CANDIDATE` vuole identita' **e** contesto, `PROXY` identita' senza contesto
  oppure contesto con somiglianza, `MISSING` nessuna delle due, e `VALIDATED`
  **mai** da un'evidenza — lo scrivono quattro metodi che un utente chiama. Gli
  stati restano quelli di V6, importati da `app/authoring/model.py`: due elenchi
  di quattro stringhe che devono restare uguali sono un elenco di troppo.
- **[V6] Nessun plugin autorato o imparato e' entrato nella libreria
  installata.** I plugin dati di V4, V5, V6 e V7 vivono nei test e in cartelle
  temporanee: la libreria resta 23 plugin e 97 componenti, tutti di codice. Il
  giorno in cui uno entra in `app/plugins/` sara' una milestone di contenuto con
  la sua misura — ed e' anche il modo di scoprire quale parte dello strumento e'
  davvero fastidiosa.

- **[V7] Uno schema di risposta ricorsivo non passa da tutti i backend di
  structured output.** Groq risponde `400 json_validate_failed` sullo schema di
  decomposizione, che usa `$ref: "#/$defs/node"`; Gemini ha risposto `503` e poi
  e' andato in timeout, Mistral `429`, e la catena di failover ha trovato chi
  rispondesse. La modalita' esterna funziona identica, quindi non blocca niente:
  la via dichiarata e' una **variante** dello schema appiattita a profondita'
  fissa per quei provider, non la sostituzione di quello vero, perche'
  un'ontologia non ha una profondita' nota. Misurato in `V7-RESULTS.md` §22.
- **[V7] Un record di validazione non sa quando e' scaduto.** Registra il
  plugin ma non la sua impronta, quindi un componente cambiato dopo resta un
  `prior_validation` valido. `TeachService.changed_components()` lo rileva
  **dentro** un progetto; lo store di conoscenza no, e dovrebbe.
- **[V7] Un componente generato si valida da solo, non sul padre.** Si carica,
  si costruisce, si misura e si cerca; la compatibilita' con il padre e con i
  figli la esercita il composite quando viene emesso, cioe' piu' tardi.
  Costruire un piano `padre + figlio` dentro la validazione e' il prossimo
  passo evidente.
- **[V7] La disposizione degli innesti di un composite e' una convenzione.** Si
  distribuiscono su una circonferenza guardando verso l'esterno: strutturalmente
  corretto, visivamente mediocre — ed e' la stessa distinzione del punto 4-bis
  fra correttezza strutturale e qualita' di layout. La via e' dichiarare
  `LayoutRegion` sul composite, che `AuthoringService` sa gia' fare e che
  nessuno gli chiede da qui.
- **[V7] Lo store di conoscenza e' lineare.** Sei record si cercano in niente;
  migliaia andranno indicizzati per (ruolo, nome), e la domanda vera e' se lo
  store debba diventare un `Corpus` dell'indice semantico — la risposta coerente
  con la regola 10 — invece di una tabella.
- **[V7] Il sottoprocesso di validazione costa 2.9 secondi**, contro 5.4 ms in
  processo: e' l'avvio di un interprete piu' `trimesh`. Un processo di servizio
  riusato lo ammortizzerebbe, e il motivo per cui non c'e' e' che un processo
  che resta vivo e che ha importato codice generato e' esattamente la cosa che
  §30 della milestone chiede di non avere per sbaglio.
- **[V7] `emit_composite` paga lo staging dell'authoring due volte per
  concetto** (debito di V6, ora piu' visibile): 185 ms per il composite
  intermedio, 467 per la radice. La via resta riemettere solo i file cambiati.
- **[V7] Alzare il `detail_target` dopo l'analisi non avvisa.** Funziona, e i
  nodi che diventano rilevanti partono da zero senza che nessuna diagnostica lo
  dica. E' la stessa famiglia di `TEACH_DECISION_LOST`, dal lato opposto.
- **[V7] Il `MockPlanner` trova un composite imparato per il nome, non per il
  significato.** «a cartoon dragon» arriva a `dragon_pack:dragon` perche' la
  parola combacia; «a winged fire-breathing reptile» dipende dai sinonimi che il
  manifest dichiara, e `emit_composite` ne dichiara uno solo — il nome del
  concetto. Dichiararne di piu' vuol dire chiedere all'utente quali, ed e' una
  domanda ragionevole che non e' stata fatta.

- **[V5] Il banco dei sei prompt non e' stato fatto con un modello di
  frontiera.** Quello che e' misurato e' che il trait giusto sia nel **testo
  reso** del vocabolario per ciascuno dei sei prompt e che la richiesta sia
  cablata fino alla geometria (testa ×1.74, gambe ×0.56, mani ×2.20, larghezza
  ×2.05, coda ×1.60, casa ×1.23). Che un modello vero scelga quel trait resta
  da misurare, ed e' lo stesso debito del punto successivo.

- **Il filtro di rilevanza dei trait strutturali fa la domanda sbagliata.**
  `_rilevante_structural` mostra un trait se un pezzo **della rosa** soddisfa il
  bersaglio della sua regola; ma un trait strutturale lavora sui figli
  **dichiarati** di un componente, che il retrieval non indicizza. Misurato:
  `humanoid_anatomical:body` al terzo posto della rosa — il componente su cui V3
  ha dimostrato 2/4/6 braccia — e `arm_count` nascosto, perche' nella rosa non
  c'era nessun braccio. I ponti dichiarati in V3.5 lo aggirano per i tre trait
  installati; la correzione vera e' seguire gli `Attachment` dichiarati in modo
  transitivo, ed e' codice nuovo.

  **[V5] Vale identico per i trait semantici**, e la causa si e' vista di nuovo:
  per «humanoid with huge hands» la rosa non conteneva nessuna mano — il plurale
  inglese non deriva al singolare — quindi `std:hand_scale` era nascosto e il
  modello non poteva sceglierlo. Risolto come in V3.5, con 25 ponti fra le parole
  nel manifest di `variability_extension` (la libreria passa da 16 a 39
  sinonimi): dati, non codice. La domanda sbagliata resta la stessa.

  **[V6] Il Component Lab la fa giusta, e il vocabolario no.**
  `ComponentLab.traits()` guarda il **sottoalbero risolto** del componente,
  quindi su `humanoid_anatomical:body` offre `std:head_scale`, `std:hand_scale`
  e `std:limb_length` — i tre che il filtro del vocabolario nasconde. Si puo'
  fare li' perche' il laboratorio ha il componente in mano e puo' costruirlo,
  mentre il retrieval ha solo la rosa e nessun grafo. Scoperto misurando:
  leggere gli `Attachment` dichiarati non basta, perche' `Component.children` e'
  una callable e quella di `humanoid_anatomical:torso` legge valori che il
  resolver deriva dal padre — chiamata con i soli predefiniti alza `KeyError`.
  **Il debito nel vocabolario resta aperto**, e ora si sa che la correzione vera
  costa una risoluzione, non una lettura.

- **Il retrieval mette le parti davanti agli interi.** «un robot con quattro
  braccia» da' una rosa di pezzi di braccio e nessun corpo, ed e' il motivo per
  cui un modello reale ha scelto `humanoid:leg` come radice. Serve una nozione di
  «soggetto» nel ranking: `subject_capabilities()` di V2 sa già riconoscerne uno,
  e il retrieval non lo chiama.

- **Il `MockPlanner` non scrive trait strutturali.** Senza rete la pipeline non
  esercita mai quel livello, quindi il benchmark offline non puo' dimostrare
  niente di strutturale — il prompt 4 offline resta a quattro ruote mentre con
  un LLM reale ne fa sei. Fargliene scrivere per corrispondenza lessicale
  sarebbe coerente con come scegli gli effetti, e cambierebbe la linea di base
  offline: e' una decisione, non un dettaglio.

- **Non c'e' nessun corpo robot nella libreria**, quindi il prompt 3 del
  PRODUCT-AUDIT non puo' essere un successo **visivo**. Due giri su tre con LLM
  reale hanno risposto `CONCEPT_TOO_FAR`, che per questa libreria e' la risposta
  giusta. E' contenuto, non motore.

- **`fx:bend` con `scope: "model"` perde l'effetto.** L'effetto dichiara
  `part, subtree, group, role`, il modello scrive `model` perche' e' lo scope di
  tutti gli esempi del prompt, e il risultato e' un `EFFECT_INCOMPATIBLE` non
  fatale: la casa si costruisce e non si piega. E' la stessa famiglia di difetto
  che V3.5 ha corretto per i trait — presentazione, non motore — e non e' stata
  toccata.

---

## Cose che non vanno fatte adesso

Marketplace, plugin store, registry remoto, esecuzione in cloud, sandbox dei
plugin, generazione automatica di plugin, cicli di correzione infiniti, giudizio
visivo affidato a un modello, IK completo, motore di collisione completo,
risolutore CAD, build distribuita, database.

~~Nemmeno l'authoring visuale.~~ **Fatto in V6**, nella forma che la milestone
chiedeva: non un editor 3D general purpose, ma uno strumento per autorare il
**contratto che 3DGen ha gia'**. Import GLB/glTF, selezione per nodo della
scena, componenti e composite, socket con gizmo leggibili e snap deterministici,
capability da un elenco, parametri con una strategia installata, frame, detail
level, validazione con i validatori veri, salvataggio nel formato V4/V5 e
installazione senza riavviare. Con tre cose **non** fatte per scelta e scritte
fra i debiti: il gizmo non si trascina, la selezione di facce non c'e', e
nessuna inferenza automatica di parti.

Restano fuori: auto-segmentation, riconoscimento delle parti con un modello, rig
automatico, proceduralizzazione di una mesh, FBX/USD/Blend, editor UV, sculpting.

~~E nemmeno Teach 3DGen, la decomposizione di un concetto con un modello, il
giudizio AI di idoneita' o visivo, la generazione di codice Python.~~ **Fatto in
V7**, nella forma che la milestone chiedeva: due passi di prompt per
l'ontologia, una copertura che decide da evidenze e non da una soglia, un
dossier economico per validare un candidato, una `VariantRecipe` che porta un
giallo al verde senza nuova geometria, una specifica tecnica che 3DGen decide,
un prompt che e' un contratto, uno staging da cui il Python **non esce senza
fiducia esplicita**, e un composite della radice che una `Session` normale
costruisce senza AI. Con tre cose **non** fatte per scelta e scritte fra i
debiti: nessuna sandbox Python (e nessun messaggio che finga di averne una),
nessun ciclo autonomo, e nessun componente artistico generato per riempire il
drago.

Restano fuori: marketplace, plugin store, esecuzione in cloud, job in
background, cicli autonomi infiniti, fiducia automatica del Python generato,
una sandbox vera, generazione neurale di mesh, generazione automatica di GLB da
testo, auto-segmentation, rig, animation authoring, agent swarm permanente.

E nemmeno `Session.modify` e le shape key.

Ognuna di queste, oggi, aggiungerebbe infrastruttura per un problema che non
abbiamo.
