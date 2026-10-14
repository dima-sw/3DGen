# Che cosa manca

Aggiornato il 14 ottobre 2026, dopo le milestone V1 (indice semantico unico) e
V2 (degradazione semantica spiegabile).

Lo stato: **1287 test verdi**, un solo percorso dal prompt al modello, 22
plugin, 97 componenti, API congelate. Davanti al planner c'e' uno stadio di
retrieval — il carico mandato al modello dipende dalla rosa di componenti
rilevanti, non da quanti plugin sono installati — e dietro c'e' una scala di
degradazione: quando il concetto chiesto non esiste si usa il piu' vicino che
c'e', e lo si dice.

Misurato, non dichiarato: con un LLM reale le generazioni riuscite sugli otto
prompt di `PRODUCT-AUDIT.md` passano da 3 su 8 a 6 su 8 con V1 e a 7 su 8 con
V2; i `413 payload_too_large` da 8 su 8 a zero; `jeep` da «casco» a
«vehicle_stylized:car». Vedi `V1-RESULTS.md` e `V2-RESULTS.md`.

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

**4. Un ginocchio non si piega — ma solo nel plugin `humanoid` storico.** Li'
coscia, polpaccio e piede sono **fratelli** appesi ai socket della gamba, non
una catena, e l'arto si muove rigido. In `humanoid_anatomical` la catena e'
vera (`hip → thigh → knee → calf → ankle → foot`, e `shoulder → upper_arm →
elbow → forearm → wrist → hand`): verificato espandendo il grafo nel
PRODUCT-AUDIT. Resta da decidere se il plugin storico va allineato o
deprecato.

**5. Nessuno appoggia il modello a terra, se non lo si chiede.**
`Scene.ground_offset` esiste e `to_scene(ground=True)` lo fa, ma non c'e' un
effetto `ground` nello stadio `final`: chi costruisce senza passare per la
scena ottiene il modello dove i componenti l'hanno messo.

**6. La compenetrazione si misura con scatole allineate agli assi.** Due lame
incrociate risultano sovrapposte senza toccarsi. Le soglie sono larghe apposta,
ma resta un compromesso.

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

- **Un trait inventato uccide ancora un piano valido.** E' l'ultimo dei due
  fallimenti con LLM reale: il modello scrive
  `adaptations: [{"trait": "instance_count"}]`, `validate_plan` lo rifiuta come
  errore fatale e il piano muore anche quando la radice e' buona. E' la stessa
  forma del difetto che V2 ha tolto al ramo `concept`, ma e' una decisione
  diversa: `tests/test_traits.py:299` pretende oggi `graph is None` per un trait
  sconosciuto. Cambiarlo vuol dire cambiare quel test apposta, non di sfuggita.
  Vale uguale per uno `structural_trait` o un `effect` inventato.

- **La soglia `MIN_CONFIDENCE = 0.08` e' tarata su 97 componenti.** Con migliaia
  va riverificata: troppo bassa produce omonimie, troppo alta rifiuta
  approssimazioni legittime.
- **La correzione unica non e' ancora dimostrata su un modello vero.** Lo
  structured output e la catena di failover ora funzionano davvero (V1 ha
  misurato 6 generazioni su 8 con provider reali), ma la riparazione non ha mai
  migliorato un piano in nessuna delle misurazioni: l'unico caso in cui e'
  partita ha dato lo stesso punteggio prima e dopo.

---

## Cose che non vanno fatte adesso

Marketplace, plugin store, registry remoto, esecuzione in cloud, sandbox dei
plugin, generazione automatica di plugin, cicli di correzione infiniti, giudizio
visivo affidato a un modello, IK completo, motore di collisione completo,
risolutore CAD, build distribuita, database.

Ognuna di queste, oggi, aggiungerebbe infrastruttura per un problema che non
abbiamo.
