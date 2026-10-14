# Che cosa manca

Aggiornato il 14 ottobre 2026, dopo le milestone V1 (indice semantico unico),
V2 (degradazione semantica spiegabile), V3 (selettori strutturali e identita'
stabile dei nodi), V3.5 (robustezza del contratto del planner) e V4 (componenti
mesh-backed dichiarati in dati).

Lo stato: **1506 test verdi**, un solo percorso dal prompt al modello, 22
plugin di codice piu' i plugin dati che chiunque installi, 97 componenti, API
congelate. Davanti al planner c'e' uno stadio di
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
ruote procedurali su una scocca mesh-backed. Vedi `V4-RESULTS.md`.

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

**7. `app/build/` non e' sotto controllo di versione.** `.gitignore:11` contiene
`build/`, che combacia anche con `app/build/`: `assembler.py`, `validate.py`,
`scene.py`, `exporter.py`, `optimize.py`, `visual.py` non stanno in nessun
commit (`git check-ignore -v app/build/scene.py`). Finche' il pattern non e'
ancorato (`/build/`), l'elenco dei file modificati di **ogni** milestone e'
incompleto per costruzione — V4 ne ha cambiati tre. Correggerlo aggiunge sei
file al repository: e' una decisione, non una pulizia.

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

- **[V4] Il vocabolario dei parametri di un componente dati e' una scala e
  nient'altro.** `scale_x`, `scale_y`, `scale_z`, `uniform_scale`: coprono «piu'
  grande» e «piu' largo», non «piu' curvo». La strada dichiarata e' mappare un
  parametro su un **effetto installato** — lo stesso meccanismo che `TraitRule`
  usa per i parametri pubblici — non inventare una seconda deformazione nel
  loader. Un `transform` sconosciuto e un parametro senza `transform` sono
  rifiutati apposta: fingere che qualunque `ParamSpec` funzioni su una mesh
  importata era il difetto da non introdurre.
- **[V4] `frame` diagnostica, non converte.** Una mesh che contraddice il
  proprio `growth_axis` prende `GROWTH_AXIS_MISMATCH` e resta com'e'. Il drago
  in piedi sulla coda di `VISION-GAP.md` e' ancora in piedi sulla coda, e
  promuovere la convenzione a contratto verificato dal resolver resta V5.
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

- **Il filtro di rilevanza dei trait strutturali fa la domanda sbagliata.**
  `_rilevante_structural` mostra un trait se un pezzo **della rosa** soddisfa il
  bersaglio della sua regola; ma un trait strutturale lavora sui figli
  **dichiarati** di un componente, che il retrieval non indicizza. Misurato:
  `humanoid_anatomical:body` al terzo posto della rosa — il componente su cui V3
  ha dimostrato 2/4/6 braccia — e `arm_count` nascosto, perche' nella rosa non
  c'era nessun braccio. I ponti dichiarati in V3.5 lo aggirano per i tre trait
  installati; la correzione vera e' seguire gli `Attachment` dichiarati in modo
  transitivo, ed e' codice nuovo.

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

Nemmeno l'authoring visuale: UI di importazione, selezione di facce o parti,
creazione visuale dei socket, auto-segmentation, riconoscimento delle parti con
un modello, rig automatico, proceduralizzazione di una mesh, FBX/USD/Blend.
V4 ha portato il **contratto** di un componente mesh-backed, non gli strumenti
per autorarlo: oggi un artista scrive il JSON a mano, e va bene cosi' finche'
non si sa quale parte del JSON e' davvero fastidiosa.

Ognuna di queste, oggi, aggiungerebbe infrastruttura per un problema che non
abbiamo.
