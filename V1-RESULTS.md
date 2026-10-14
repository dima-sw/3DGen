# V1-RESULTS — Un solo indice semantico, due usi

Milestone V1 di `VISION-GAP.md`, implementata il **14 ottobre 2026**.
Branch `v1-semantic-index`, checkpoint di partenza `3141e04` su `main`.

**Esito: completa.** Tutti e cinque i criteri di chiusura sono soddisfatti e
misurati. Il risultato principale: con un LLM reale le generazioni riuscite
passano da **3 su 8 a 6 su 8**, la mediana di attesa da **27,9 s a 14,5 s**, e i
`413 payload_too_large` da **8 su 8 a zero**.

---

## 1. Che cosa è cambiato

La pipeline aveva un buco fra il prompt e il planner: non c'era nessuno stadio
che decidesse *che cosa mostrare*. Il vocabolario intero partiva verso il
modello a ogni richiesta, e cresceva con la libreria installata.

```text
prima   prompt → build_vocabulary(TUTTO il registry) → LLM planner
dopo    prompt → SemanticIndex dei componenti → rosa → build_vocabulary(rosa) → LLM planner
```

Nessun motore di ricerca nuovo. Quello in `app/assets/semantic.py` — TF-IDF
locale, `RemoteEmbedder` opzionale, persistenza, fingerprint, signature — è
stato **generalizzato a due corpora** invece che duplicato:

```python
@dataclass(frozen=True)
class Corpus:
    name: str
    document: Callable[[Any], str]   # il testo da cercare
    stamp: Callable[[Any], str]      # identita' versionata, per il fingerprint
    key: Callable[[Any], str]        # l'id restituito da search
```

`ASSETS` descrive gli asset salvati (comportamento invariato), `COMPONENTS` i
componenti installati. Un indice salvato dichiara il proprio corpus e viene
rifiutato se riletto come l'altro — stessa regola che già valeva per l'embedder.

### Il documento di un componente

Si ricava **solo da ciò che il componente dichiara**: id, nome, descrizione,
ruolo, tag, capability fornite, capability accettate (con i loro tag), plugin,
stili. Gli identificatori diventano parole (`fox_stylized:tail_tip` →
`tail tip`), e id e nome pesano doppio, come il nome di un asset nell'altro
corpus.

Nessuna conoscenza di dominio entra nel core: se una volpe si trova cercando
«animale» è perché qualcuno ha scritto `animal` fra i suoi tag.

### Il thesaurus è diventato dato della libreria

`THESAURUS` in `app/assets/semantic.py` conteneva conoscenza di dominio nel
codice. **Il comportamento non è stato toccato** — resta il dizionario
predefinito per chi non ne passa uno — ma ora:

* `expand()` e `TfidfEmbedder` accettano un thesaurus come parametro;
* un plugin può dichiarare i propri ponti fra parole nel manifest, come dati:

```json
"synonyms": {
  "jeep": ["car", "vehicle", "auto", "veicolo", "fuoristrada", "suv"]
}
```

* `Registry.synonyms()` unisce quelli di tutti i plugin installati (due plugin
  che dichiarano la stessa parola si sommano, nessuno vince);
* `retrieval.thesaurus_for(registry)` fonde predefiniti e dichiarati.

È il meccanismo che risolve il caso `jeep` senza che il core sappia che cos'è
una jeep: lo sa il plugin dei veicoli, che è il posto giusto.

### La rosa

Deterministica, senza LLM, senza pesi arbitrari:

1. **gruppi di interrogazione** — la frase intera, poi ogni parola che conta
   (stopword escluse), in ordine di apparizione, al massimo 8;
2. una ricerca per gruppo, 8 risultati ciascuno;
3. **alternanza** fra le liste — un giro per lista — così nessun gruppo riempie
   la rosa da solo. È ciò che tiene insieme `fish` e `humanoid` nella stessa
   richiesta;
4. **quota per plugin** (10) perché un plugin da 26 componenti non monopolizzi
   il contesto; chi resta fuori per quota rientra se avanza spazio;
5. **chiusura** — per ogni capability che un componente scelto accetta, fino a 2
   fornitori entrano anche se la richiesta non li nominava. Senza, il planner
   non potrebbe comporre ciò che non vede.

Limite 28 componenti. A parità di indice, due esecuzioni danno la stessa rosa:
verificato confrontando id e token di due misurazioni separate.

### Il vocabolario segue la rosa

Filtrare i componenti non sarebbe servito a niente se il resto fosse rimasto
intero. `build_vocabulary(..., components=rosa)` restringe anche:

* **capability** — solo quelle fornite o accettate dalla rosa, e i loro elenchi
  `providers`/`mounts` filtrati agli id della rosa (altrimenti una capability
  si riporterebbe dentro tutta la libreria appena esclusa);
* **effetti** — quelli senza `applies_to` (valgono su tutto) più quelli che
  dichiarano una capability o un tag presente nella rosa;
* **trait semantici e strutturali** — quelli con almeno una regola che può
  toccare la rosa (per ruolo, tag o componente), e quelli senza regole;
* **plugin** e **tag** — solo quelli dei componenti selezionati.

`sanitize()` non è stato toccato: la rosa cambia *quali* componenti si vedono,
non *come* si raccontano. Due test lo verificano esplicitamente.

---

## 2. File toccati

| File | Che cosa |
| --- | --- |
| `app/assets/semantic.py` | `Corpus`, indice guidato dal corpus, thesaurus iniettabile, corpus nella persistenza. +90 / −24 |
| `app/core/planner/retrieval.py` | **nuovo**, 427 righe: documento del componente, fingerprint, indice, rosa |
| `app/core/planner/vocabulary.py` | `build_vocabulary(components=...)` e filtro coerente di capability, effetti, trait, plugin, tag |
| `app/core/registry.py` | `PluginInfo.synonyms`, lettura dal manifest, `Registry.synonyms()` |
| `app/core/session.py` | `component_index()`, `shortlist()`, `vocabulary(prompt=, shortlist=)`, `GenerationResult.shortlist` e `retrieval()` |
| `app/plugins/vehicle_stylized/plugin.json` | dichiara i propri sinonimi (dati, nessun codice) |
| `tests/test_api_freeze.py` | elenco congelato aggiornato per i campi e metodi aggiunti |
| `tests/test_retrieval.py` | **nuovo**, 469 righe, 41 test |
| `.gitignore` | esclude `audit-images/` e `.tmp-tests/` |

Nessun test esistente indebolito: le cinque righe cambiate in
`test_api_freeze.py` sono aggiunte all'elenco congelato, che è il modo previsto
dal file stesso per registrare una decisione.

---

## 3. Misure

### 3.1 Dimensione del vocabolario, prima e dopo

Libreria attuale: **96 componenti in stile `low_poly`** (97 installati, uno solo
realistico). Vocabolario completo: **39 964 caratteri, ~9 991 token**.

| # | Prompt | Rosa | Caratteri | Token | Riduzione | Retrieval |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | Una volpe cartoon low-poly | 18/96 | 13 894 | ~3 474 | −65% | 1,4 ms |
| 2 | Umanoide testa enorme, gambe corte, mani grandi | 24/96 | 13 919 | ~3 480 | −65% | 1,6 ms |
| 3 | Un robot con quattro braccia | 5/96 | 5 873 | ~1 469 | −85% | 0,7 ms |
| 4 | Una jeep cartoon con sei ruote | 17/96 | 10 286 | ~2 572 | −74% | 0,8 ms |
| 5 | Un pesce con corpo umanoide | 29/96 | 15 149 | ~3 788 | −62% | 1,3 ms |
| 6 | Una casa alta, slanciata e curva | 12/96 | 9 270 | ~2 318 | −77% | 1,1 ms |
| 7 | Un drago con ali, corna e coda | 14/96 | 11 009 | ~2 753 | −72% | 1,3 ms |
| 8 | Un albero fantasy, chioma asimmetrica | 20/96 | 13 582 | ~3 396 | −66% | 1,5 ms |

**Massimo 3 788 token, obiettivo < 5 000: raggiunto su tutti e 8.**

Costruzione dell'indice: **15 ms** per 96 componenti, una volta per sessione.
Retrieval: **0,7–1,6 ms**. La stima è dichiaratamente grossolana (4 caratteri
per token); il carico reale misurato sul fornitore per il prompt 1 è
**21 866 byte**, contro gli 8 211 token che Groq rifiutava prima.

Dati completi in `audit-images/v1_vocabulary.json`.

### 3.2 Retrieval, revisione manuale degli 8 prompt

I primi risultati per interrogazione, con punteggio:

```text
01 volpe        fox_stylized:fox 0.254 | poi rumore a 0.05-0.06 (vehicle, tree)
02 umanoide     humanoid:body 0.223, humanoid:head 0.190, humanoid:ear 0.186
03 robot        architecture:house 0.040  ← nessun robot low_poly esiste
04 jeep         vehicle_stylized:wheel 0.627, :car 0.575, :body 0.351, :fender 0.325
05 pesce+umano  fish:fish_body 0.547, humanoid:body 0.561, humanoid_anatomical:body 0.300
06 casa         architecture:house 0.519, :door 0.154, :window 0.153, :roof 0.137
07 drago        creature:dragon_head 0.168, fish:tail 0.265, nature:bird 0.097
08 albero       nature:tree 0.563, nature:foliage 0.508, tree_stylized:tree 0.254
```

**Il criterio sulla jeep è soddisfatto.** Tutti e undici i risultati *da
interrogazione* sono componenti `vehicle_stylized:`. `accessories:helmet` compare
ancora nella rosa, ma solo per **chiusura** su `gear_mount` — una capability che
l'auto accetta davvero — con punteggio 0,0 e in fondo:

```text
vehicle_stylized:car            0.575   query
vehicle_stylized:wheel          0.627   query
...  (altri 9 vehicle_stylized, tutti query)
vehicle_stylized:hood_panel     0.0     closure:vehicle_mount
accessories:helmet              0.0     closure:gear_mount
```

Prima di V1 il pianificatore locale sceglieva `accessories:helmet` **come
radice** per «jeep». Ora i veicoli sono strettamente più prominenti.

Il prompt 5 è la verifica del multi-concetto: la rosa contiene `fish` **e**
entrambi gli umanoidi, cioè le due famiglie nominate.

### 3.3 Gli 8 prompt con LLM reale

Stessa catena di provider, stesso script, stessa macchina.

| # | Prompt | Baseline | V1 |
| --- | --- | --- | --- |
| 1 | volpe | ❌ 0 tris, 3,2 s | ✅ **412 tris**, 3,0 s, groq, failover 0 |
| 2 | umanoide | ❌ 0 tris, 68,0 s | ✅ **264 tris**, 170,0 s, catena esaurita |
| 3 | robot 4 braccia | ❌ 0 tris, 2,7 s | ❌ 0 tris, 2,5 s, groq |
| 4 | jeep 6 ruote | ✅ 56 tris, 147,4 s | ✅ **228 tris**, 48,8 s, cloudflare |
| 5 | pesce+umano | ✅ 198 tris, 34,8 s | ✅ **412 tris**, 2,5 s, groq, failover 0 |
| 6 | casa | ❌ 0 tris, 20,9 s | ✅ **32 tris**, 13,5 s, gemini |
| 7 | drago | ❌ 0 tris, 2,6 s | ❌ 0 tris, 15,6 s, cloudflare |
| 8 | albero | ✅ 400 tris, 74,3 s | ✅ 400 tris, 32,5 s, gemini |

```text
generazioni riuscite    3/8  →  6/8
mediana                27,9s →  14,5s
failover totali           22 →  17
413 payload_too_large    8/8 →  0/8
```

Gli esiti dei provider nel run V1, contati dal log:

```text
8  rate_limited        (quota per minuto, non dimensione)
5  invalid_json        (un provider che non rispetta lo schema)
2  quota_exhausted
2  connection_error
1  server_error
0  payload_too_large   ← il bersaglio di V1
```

**Groq, il fornitore primario, ora serve davvero**: prompt 1, 3 e 5 rispondono
al primo tentativo in 2,5–3,0 s. Prima rifiutava ogni singola richiesta.

Il prompt 2 ha esaurito la catena (failover 9, 170 s) per **limiti di frequenza**
accumulati eseguendo otto richieste di fila, non per dimensione; è finito su
`planner = mock_fallback`, registrato esplicitamente come sempre.

Dati completi in `audit-images/v1/metrics_llm.json`.

### 3.4 Gli 8 prompt offline (MockPlanner)

| # | Baseline | V1 |
| --- | --- | --- |
| 1 volpe | ✅ 412 | ✅ 412 |
| 2 umanoide | ✅ 330 | ✅ 264 |
| 3 robot | ✅ 168 | ✅ 12 |
| 4 jeep | ✅ 56 | ✅ 56 |
| 5 pesce+umano | ✅ 1292 | ✅ 414 |
| 6 casa | ✅ 32 | ✅ 32 |
| 7 drago | ✅ 82 | ✅ 82 |
| 8 albero | ✅ 50 | ✅ 50 |

**8/8 prima, 8/8 dopo: nessuna regressione nel numero di generazioni riuscite.**

Due composizioni cambiano, e vanno dette:

* **5 migliora davvero.** Prima: 40 nodi con catene di arti duplicate appese a
  radici scollegate, 1292 triangoli di geometria sovrapposta. Ora:
  `humanoid_anatomical:body` + `fish:fish_body` + `fish:tail` + `fish:fin`, 414
  triangoli. È la composizione che il prompt chiedeva.
* **3 peggiora.** Prima: quattro pezzi di braccio sconnessi. Ora: una porta.
  Entrambi sono sbagliati — nella libreria non esiste **nessun** robot in stile
  `low_poly` — ma il confronto è onesto solo dicendo che il secondo è più
  povero del primo. Il pianificatore locale sceglie per corrispondenza di
  parole dentro ciò che vede, e ora vede cinque componenti invece di 96.

### 3.5 La prova sui 1 000 componenti

Registry sintetico, 12 famiglie, nessuna rete, nessun LLM
(`tests/test_retrieval.py::_libreria_sintetica`).

```text
1000 componenti | indice costruito in 0,10 s
vocabolario completo: 153 811 caratteri, ~38 453 token
```

| Prompt | Rosa | Token | Famiglie trovate |
| --- | ---: | ---: | --- |
| un animal a quattro zampe | 10/1000 | ~571 | fauna, minerali |
| una house con un tetto | 10/1000 | ~575 | edifici, minerali |
| un vehicle con wheel | 10/1000 | ~560 | minerali, veicoli |
| un fish e un humanoid | 18/1000 | ~907 | acquatici, **gente**, minerali |
| zzzqwerty (nessun riscontro) | 28/1000 | ~1 236 | ripiego dichiarato |

**Da ~38 453 token a 560–1 236: il carico dipende dalla rosa, non dalla
libreria.** Obiettivo < 8 000: raggiunto con un margine di sei volte.

`minerali` compare quasi ovunque perché nella libreria sintetica ogni componente
accetta `solid` e la chiusura ne porta i fornitori: è la chiusura che funziona,
non rumore.

Dati in `audit-images/v1_thousand.json`.

---

## 4. Test

**41 test nuovi** in `tests/test_retrieval.py`, suite completa **1254 passed**
(erano 1213).

| Area | Test |
| --- | --- |
| documento del componente | 3 — si ricava dal dichiarato, gli id diventano parole, un componente nudo ha comunque un documento |
| indicizzazione | 2 — tutti i componenti indicizzati, un corpus non si legge come l'altro |
| fingerprint / invalidazione | 6 — componente nuovo, descrizione cambiata, versione di plugin cambiata, plugin senza componenti, stamp, salva e rileggi |
| ricerca | 4 — per nome, per tag, determinismo, nessun riscontro |
| sinonimi dei plugin | 3 — arrivano al thesaurus, «jeep» trova i veicoli, il core non ne ha di suoi |
| rosa | 11 — più piccola della libreria, deterministica, due famiglie, quota per plugin, chiusura, prompt vuoto, nessun riscontro, stile, gruppi |
| vocabolario ristretto | 6 — segue la rosa, molto più piccolo, non perde altri componenti, capability filtrate, contratti completi, senza rosa è intero |
| sicurezza | 3 — `sanitize` invariata, descrizione malevola sanificata anche con la rosa, documento come dato |
| mille componenti | 3 — indicizzati, il prompt non cresce, due famiglie convivono |

Tre di questi test hanno trovato difetti veri durante la scrittura, tutti
corretti prima della chiusura (sezione 6).

---

## 5. Criteri di chiusura

| Criterio | Esito |
| --- | --- |
| 1. tutta la suite verde | ✅ 1254 passed in 61 s |
| 2. nessun provider fallisce per vocabolario troppo grande | ✅ 0 `payload_too_large` su 8 prompt (erano 8/8) |
| 3. il vocabolario scala con la rosa, non con la libreria | ✅ 1 000 componenti → 560–1 236 token contro 38 453 |
| 4. query multi-concetto conservano più categorie | ✅ `fish` + `humanoid` con 96 e con 1 000 componenti |
| 5. risultati riproducibili | ✅ due esecuzioni, stessi id e stessi token |

Obiettivi numerici: **payload < 5 000 token su tutti e 8** (massimo 3 788) e
**< 8 000 token con 1 000 componenti** (massimo 1 236).

---

## 6. Problemi scoperti

Tre trovati dai test nuovi e corretti dentro V1, uno strutturale lasciato a V2.

**1. Il ripiego mostrava tutta la libreria.** Quando nessun componente supera la
soglia, la risposta era «mostro tutto» — onesta con 96 componenti, letale con
1 000: il test sintetico è fallito con 33 931 token. Ora il ripiego mostra tutto
solo sotto `FALLBACK_MAX = 120` componenti; sopra, manda una fetta in ordine di
id e **lo dichiara** nel campo `fallback`. È un cerotto: la risposta giusta a
«non ho trovato niente» è la degradazione semantica, cioè V2.

**2. L'indice riletto da disco espandeva le interrogazioni in modo diverso.** Il
thesaurus non veniva salvato nello stato dell'embedder, quindi un indice
costruito con i sinonimi di un plugin e riletto dopo proiettava le query in uno
spazio diverso da quello dei documenti. Ora è nello `state()`.

**3. «jeep» non trovava niente.** Il thesaurus predefinito mappava
`jeep → fuoristrada, offroad, suv`, parole che non esistono in nessun
componente. È il problema che ha motivato i sinonimi dichiarati dal plugin.

**4. Rumore a punteggio basso (non corretto, accettato).** La parola `fantasy`
in «albero fantasy» fa salire `fantasy:wing` (0,415) sopra
`tree_stylized:tree` (0,254), perché il nome e i tag del plugin fanno parte del
documento e `fantasy` è un termine raro. Non è un errore — l'utente ha detto
«fantasy» e il plugin esiste — e l'albero è comunque nella rosa. Resta da
osservare se con una libreria vera diventa un problema.

---

## 7. Debiti registrati

* **Il thesaurus predefinito è ancora nel codice.** `app/assets/semantic.py`
  contiene ~25 voci italiane di dominio. Il meccanismo per spostarle fuori ora
  esiste ed è usato (`plugin.json` → `synonyms`), ma svuotare il dizionario
  predefinito cambierebbe il comportamento della ricerca nella libreria degli
  asset, che non è in scope V1. Il passo successivo è portarle nei plugin che
  possiedono quelle parole e lasciare il dizionario vuoto.
* **Nessuno stemming.** `persona` non trova `person`, `ruote` non trova `wheel`
  se non via sinonimi. Oggi si compensa dichiarando i ponti; con una libreria
  grande e multilingue servirà qualcosa di meglio. Il punto di innesto esiste
  già: `RemoteEmbedder` è nell'interfaccia e non è mai stato provato.
* **L'indice dei componenti vive in memoria per sessione.** La persistenza è
  implementata, testata e passa per `path`, ma `Session` non la usa: con 96
  componenti costruire l'indice costa 15 ms e un file in più nella home
  dell'utente non si ripaga. Con migliaia di componenti si attiva passando un
  percorso.
* **Il pianificatore locale peggiora su ciò che la rosa esclude** (prompt 3).
  Finché la rosa è giusta è un miglioramento; quando la rosa è vuota perché la
  libreria non ha il soggetto, il ripiego è più povero di prima.

---

## 8. Che cosa resta a V2

I due fallimenti rimasti con LLM reale sono **entrambi** il ramo `concept`, cioè
esattamente ciò che `VISION-GAP.md` assegna a V2:

```text
03 robot   concept.adaptations = [{"trait": "instance_count", "value": 4}]
           → trait non disponibile: 'instance_count'
           (il piano conteneva anche un root valido, ignorato: il concept lo uccide)

07 drago   concept.archetypes = ["registered:archetype_metadata:animal"]
           → Archetype non disponibile  →  concept non registrato  →  0 triangoli
```

Il prefisso `registered:` è la stessa allucinazione del PRODUCT-AUDIT, e costa
ancora l'intera generazione. V1 non doveva risolverlo e non lo risolve.

V2 ha ora ciò che le serviva da V1: **candidati corretti su cui degradare**. La
rosa per «jeep» contiene gli undici componenti `vehicle_stylized`, quindi
`jeep → vehicle` ha dove atterrare. Restano da fare, come da `VISION-GAP.md`:

1. normalizzare gli id di archetipo e profilo (togliere prefissi inventati,
   confrontare per alias);
2. rendere `CONCEPT_UNKNOWN` un `warning` con ripiego sul ramo `root`, invece di
   un errore fatale;
3. risalire la gerarchia semantica nel percorso normale — oggi
   `Resolver._trova` fallisce e suggerisce alternative da `Registry.search`, che
   è un conteggio di parole;
4. derivare la gerarchia da capability, tag e `role` dei componenti invece che
   dal catalogo scritto a mano;
5. aggiungere i gradini 4 (composizione) e 5 (fallback generico);
6. riportare la degradazione in `explain()` e salvarla nel `.my3d`.

---

## 9. Riprodurre le misure

```bash
python -m pytest -q tests/test_retrieval.py
python audit-images/v1_measure.py audit-images/v1_vocabulary.json
python audit-images/run_audit.py offline audit-images/v1
python audit-images/run_audit.py llm audit-images/v1 groq      # richiede rete
```

Gli artefatti di misura stanno in `audit-images/` (fuori dal controllo di
versione, come gli output dell'audit):

```text
v1_vocabulary.json    dimensioni e retrieval per gli 8 prompt
v1_thousand.json      la prova sui 1 000 componenti
v1/metrics_llm.json   gli 8 prompt con LLM reale
v1/metrics_offline.json  gli 8 prompt offline
v1/*.png              24 immagini, 3 angolazioni per generazione riuscita
```

Il confronto è con `audit-images/metrics_llm.json` e
`audit-images/metrics_offline.json`, prodotti dal PRODUCT-AUDIT sullo stesso
script prima di V1.
