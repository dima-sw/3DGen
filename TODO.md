# 3DGen — stato e piano di lavoro

Questo file è la fonte di verità del progetto: cosa è **davvero** fatto, cosa
viene dopo e con quale criterio si considera finito. Va aggiornato alla fine di
ogni sessione di lavoro, prima di chiudere.

Ultimo aggiornamento: **9 settembre 2026** — 694 test verdi, nessuno rosso.
**Tutti e cinque i banchi di prova passano**: il sistema compone oggetti che
nessun template prevede, senza generazione AI di mesh.

---

## Il problema che ha cambiato tutto (risolto il 9 settembre 2026)

Fino a ieri il sistema faceva questo:

```
"crea un pesce"                                 -> un cubo
"un pesce con il corpo di una persona"          -> un cubo
"una creatura con ali e testa di squalo"        -> un cubo
```

Non era un difetto di rifinitura: era il limite dell'architettura. Un generatore
parametrico per ogni oggetto possibile non esiste, e non si puo' scrivere.

Oggi le stesse richieste producono creature composte da parti, fuse in un corpo
unico, senza che esista alcun template "pesce", "lupo" o "drago".

![ibrido](output/bench_ibrido.png)

La risposta non e' stata "allora la mesh la fa l'AI". L'AI e' il **direttore**:
descrive quali parti e come stanno insieme; la geometria resta procedurale,
locale e deterministica. Il costo AI di una generazione e' una chiamata sola.

## Regole che non si negoziano

1. **L'LLM non esegue mai codice.** Produce solo JSON validato con Pydantic;
   i parametri fuori schema si scartano, quelli fuori scala si clampano.
2. **Una milestone alla volta**, con i suoi test, prima di passare alla successiva.
3. **Niente dipendenze nuove** senza una ragione scritta qui accanto alla voce.
4. **Il fallback non si tocca**: se AI e rete spariscono, l'app deve continuare a
   produrre un modello.
5. **UI, AI e geometria restano separate.** La UI parla solo con `Session`.
6. **Il backend geometrico resta sostituibile.** Oggi trimesh; Blender solo se
   serve qualcosa che trimesh non fa, e comunque dietro la stessa interfaccia.
7. **Niente engine proprietario** finché il workflow non è validato dall'uso.
8. **Ciò che l'utente chiede non viene mai alterato** da varianti o euristiche.
9. **L'assenza di un template, di un asset o di un generatore specializzato non
   deve mai impedire l'esecuzione della richiesta.** Il sistema ricade sempre
   sulla strategia generativa più generale disponibile. Non esiste "non so farlo".
10. **Il costo in chiamate AI di una generazione è costante e limitato.**
    Il raffinamento è deterministico: la geometria non si corregge chiedendo
    all'LLM in un ciclo. Vedi *Perché il ciclo di validazione non è un ciclo AI*.

---

## L'architettura verso cui andiamo

```
                        PROMPT
                          |
                          v
                  COMPRENSIONE (LLM)              <- 1 chiamata
                          |
                          v
                  PIANO DI COMPOSIZIONE
              (parti, attacchi, fusione, vincoli)
                          |
        +-----------------+------------------+---------------------+
        v                 v                  v                     v
   TEMPLATE          CATALOGO PARTI      LIBRERIA ASSET       AI MESH (API)
   parametrico       + fusione SDF       (riuso)              ultima risorsa
        |                 |                  |                     |
        +-----------------+------------------+---------------------+
                          v
                    COMPOSIZIONE
              (socket, scala, simmetria)
                          |
                          v
                  VALIDAZIONE SEMANTICA          <- codice, non AI
                          |
                +---------+---------+
                v                   v
             PASSA            NON PASSA -> riparazione deterministica,
                |                          al massimo 1 chiamata AI
                v
                     MESH FINALE
```

Cinque livelli, come da discussione: **concetto → struttura → forma → dettaglio
→ superficie**. L'LLM lavora ai primi due, il codice agli altri tre.

### Perché il ciclo di validazione non è un ciclo AI

Un LLM non può giudicare una mesh se non gliela mostri: servirebbe renderizzare
e inviare immagini a ogni iterazione. Lento, costoso, e con esiti instabili.

I controlli che servono sono invece esprimibili come **regole geometriche**:
la coda sta dietro, la simmetria è bilaterale, le pinne sono almeno due, il
rapporto testa/corpo è nell'intervallo, le parti si toccano davvero, la
silhouette non degenera in un ovale. Sono verificabili in codice, in millisecondi,
sempre allo stesso modo.

L'LLM viene chiamato **una volta** per pianificare. Se la validazione fallisce,
riceve un rapporto strutturato degli errori e ha **una sola** possibilità di
correggere il piano. Poi si applica una riparazione deterministica. Budget finito,
per costruzione.

### Perché "generatore aperto" non significa "generato dall'AI"

Nella proposta iniziale il ramo UNKNOWN andava direttamente a un generatore AI di
mesh. Lo cambio: il generatore aperto è il **compositore SDF di parti**. È un
linguaggio di forme generale — qualunque cosa organica si descrive come un
insieme di volumi fusi — e resta procedurale, locale, gratuito e veloce.

La generazione AI di mesh resta in roadmap, ma come **quarta** strategia, per ciò
che nemmeno il compositore riesce a esprimere. Ordine delle strategie:

```
1. template parametrico specializzato   (jeep, casa, sedia: precisi e velocissimi)
2. composizione di parti + fusione SDF  (tutto il resto: creature, ibridi, inventati)
3. asset dalla libreria                 (riuso di ciò che esiste gia')
4. generazione AI di mesh via API       (ultima risorsa, quando le altre non bastano)
```

Il `GeneratorManager` sceglie, e può mescolarle nello stesso oggetto: torso umano
parametrico + testa di pesce composta + giunti dalla libreria.

### La grammatica di forme: perché non serviranno mille parti

Il rischio del catalogo di parti è di riprodurre fra un anno lo stesso problema
di oggi, solo con 500 generatori invece di 9. Si evita se una parte non è una
forma fissa ma **un volume più le operazioni che lo trasformano**.

```
corpo di pesce   = ellissoide + taper
tentacolo        = capsula affusolata + bend + twist
quattro zampe    = capsula + mirror + repeat
casco            = sfera + shell + difference
```

Il vocabolario è chiuso e piccolo — sei volumi, undici operazioni, tre
combinatori — ma le combinazioni sono illimitate. È questo, non il numero di
parti, a rendere il sistema aperto.

**Una parte non è una mesh: è una ricetta.**

```
PARTE = PARAMETRI + SOCKET + OPERAZIONI + VINCOLI
```

Le ricette sono **dati**, non codice: stanno in file, si aggiungono senza
toccare il motore, e l'LLM può scriverne di nuove al volo per ciò che non
esiste ancora. Il catalogo iniziale serve solo a dare qualità agli oggetti
comuni, non a definire il confine di ciò che si può creare.

Le operazioni vivono **sul dominio del campo di distanza**, non sulle mesh:
lì piegare, torcere e rastremare sono deformazioni della coordinata di
interrogazione, cioè tre righe di numpy senza problemi di topologia. Le stesse
operazioni su mesh triangolate richiedono tessellazione fitta e producono
autointersezioni.

### Il pezzo che mancava nella proposta: i socket

Un piano fatto di `{"name": "head", "type": "fish_head"}` non dice **dove** va la
testa. Senza questa informazione le parti si incollano a caso.

Ogni parte dichiara quindi dei **socket**: punti di attacco con posizione,
direzione e raggio.

```
torso_umano:  collo(0, 1.45, 0, su, r=0.09)   spalla_l   spalla_r   anca_l   anca_r
testa_pesce:  base(-0.3, 0, 0, indietro, r=0.11)
coda_pesce:   base(0.5, 0, 0, avanti, r=0.14)
```

Comporre significa allineare `collo` con `base`, adattare la scala perché i raggi
combacino, e fondere il giunto. È questo che distingue "un corpo unico" da
"tre pezzi sovrapposti".

---

## Fatto

### Fase 1 — Infrastruttura
- [x] Struttura del progetto, logging con buffer consultabile dalla UI
- [x] Configurazione esterna al codice (`.env`), nessuna chiave hardcoded
- [x] Registro provider LLM guidato dai dati (`app/core/config.py`)
- [x] `truststore` per gli antivirus che intercettano l'HTTPS

### Fase 2 — Geometria
- [x] 11 primitive, tutte watertight (`app/geometry/primitives.py`)
- [x] Ear clipping proprio per profili concavi, senza dipendenze esterne
- [x] Trasformazioni scala → rotazione → traslazione
- [x] 9 generatori parametrici: `vehicle` (8 sottotipi), `house`, `humanoid`,
      `weapon` (5 tipi), `chair`, `table`, `tree`, `rock`, `primitive`

### Fase 3 — Pipeline e contratto AI
- [x] `GenerationPlan` come unica sorgente di verità (`app/core/spec.py`)
- [x] Scene graph con ID stabili e tag (`app/core/scene.py`)
- [x] Builder con recupero d'errore per componente (`app/build/builder.py`)
- [x] Validazione pre-export e export GLB/OBJ/STL/PLY + piano JSON riproducibile

### Fase 4 — Interfaccia desktop
- [x] Viewport OpenGL 3.3 proprio (moderngl + QOpenGLWidget), orbita/pan/zoom
- [x] Finestra con chat, albero della scena, parametri editabili, qualità, versioni, log
- [x] Rete e geometria in `QThread`: la UI non si blocca mai
- [x] Renderer offscreen per anteprime e test senza aprire finestre

### Fase 5 — LLM
- [x] Catena di failover su 9 provider, degrado fino alle regole locali
- [x] Planner a regole italiano/inglese, funzionante offline
- [x] Editing incrementale con comandi strutturati (`set_param`, `scale_param`, …)
- [x] Cronologia con annulla/ripeti e salto a qualunque versione

### Fase 6 — Varianti
- [x] Profilo di variazione per parametro (`variation_profile.py`)
- [x] Blocco di ciò che l'utente ha chiesto, incluse le modifiche esplicite
- [x] Snapshot pre-variante: i disturbi non si accumulano
- [x] Riproducibilità a parità di seed, `--seed` e `--variants` da CLI, F5 nella UI

### Fase 7 — Libreria di asset
- [x] Formato su disco autosufficiente: `asset.json` + `model.glb` + `preview.png`
- [x] Il **piano** salvato insieme alla mesh: un asset ricaricato resta parametrico
- [x] `AssetLibrary`: salva, elenca, cerca, carica, rinomina, cancella
- [x] Tag automatici, inclusi i sinonimi dei template ("albero" trova "pino")
- [x] Pannello Libreria nella UI + comandi CLI
- [x] Il filesystem è la fonte di verità: cartelle o metadati rotti non fermano l'elenco

### Fase 8 — Grammatica di forme (8 settembre 2026)
- [x] `app/geometry/sdf.py`: 6 volumi, 11 operazioni, 3 combinatori, tutti
      componibili in albero (`Union`, `Mirror`, `Repeat`, `Taper`, `Bend`, `Twist`, …)
- [x] Fusione morbida con coefficiente **per giunto**: alto fra corpo e testa,
      basso per le appendici che devono restare distinte
- [x] `app/geometry/surface.py`: campo → mesh watertight, risoluzione scelta
      (anteprima / normale / alta) e tetto sul numero di celle
- [x] **Valutazione a banda stretta**: ogni figlio calcolato solo dentro la
      propria scatola. 5,1× più veloce, e con le scatole strette la griglia
      passa da 4,9 M celle a 286 k
- [x] 47 test, inclusa la verifica che la banda stretta coincida con il calcolo
      ingenuo vicino alla superficie e non sottostimi mai

**Risultato misurato sul pesce**: dal prototipo a mano a griglia piena
(4,4 s) alla pipeline vera: **0,04 s in anteprima**, 0,10 s a risoluzione
normale, 32.000 facce in alta. Il collo di bottiglia dichiarato nella fase 2
è già risolto.

**Nota che costa cara se dimenticata:** i campi della grammatica sono distanze
vere, in metri. I coefficienti di fusione hanno quindi un significato fisico e
i valori tarati sul prototipo (che usava un campo compresso) non si trasferiscono.
Fondere due parti che non si toccano non le unisce: le lascia staccate. Il
validatore semantico dovrà controllare la connessione, non fidarsi del blend.

### Fase 9 — Composizione di parti (9 settembre 2026)
- [x] `app/geometry/recipe.py`: le parti sono **ricette dichiarative** in JSON,
      con parametri, socket, albero di operazioni e vincoli. Dati, non codice
- [x] Interprete di espressioni ristretto: solo aritmetica sui parametri della
      ricetta, nessuna chiamata. Vale anche per le ricette scritte dall'LLM
- [x] **9 ricette generiche** coprono tutto: `body`, `torso`, `head`, `limb`,
      `blade`, `extremity`, `eye`, `plate`, `segment`. Non una per animale
- [x] Socket con posizione, direzione, **dorso** e raggio; disposizioni
      `single`, `pair`, `radial`, `row` per zampe, tentacoli, ali
- [x] `app/geometry/composition.py`: allineamento delle terne, adattamento di
      scala sui raggi, innesto forzato nel padre perche' la fusione abbia materia
- [x] La superficie si estrae **una volta sola** dal campo fuso e viene poi
      ripartita fra le parti: corpo unico, ma ogni parte tiene identita',
      materiale e tag. E' cosi' che una testa di pesce sta su un torso umano
- [x] `app/ai/creature.py`: archetipi e specie come **preset di parametri**;
      aggiungere una specie costa una riga di dizionario
- [x] Parser semantico italiano/inglese: innesti ("con il corpo di X",
      "testa di Y"), conteggi ("quattro braccia", "sei tentacoli"), taglia
- [x] `GenerationPlan` esteso: da lista piatta a **grafo** di parti con attacchi
- [x] Veicolo parametrico anche nel numero di assi: 4, 6 o 8 ruote senza
      scrivere un generatore nuovo

### Fase 10 — Vincoli semantici e riparazione (9 settembre 2026)
- [x] `app/build/validation.py`: regole per classe (pesce, quadrupede, uccello,
      umanoide, serpente) dichiarate come dati
- [x] Otto controlli geometrici: parti mancanti, conteggi minimi, **connessione
      reale**, coda posteriore, simmetria bilaterale, allungamento, proporzione
      della testa, parti degeneri
- [x] Errori **strutturati** (`code`, `severity`, `part`, `expected`, `actual`)
- [x] Riparazione deterministica: riconnette, riporta la coda dietro, riduce una
      testa sproporzionata, elimina le parti degeneri
- [x] Budget finito: valida, ripara, rivalida. Nessun ciclo aperto, nessuna
      chiamata a modelli nel percorso di correzione (regola 10)

### Fase 11 — Gestore delle strategie (9 settembre 2026)
- [x] `app/build/strategy.py`: un solo punto decide template / composizione /
      libreria / AI mesh, nell'ordine della roadmap
- [x] Ripiego automatico alla strategia successiva quando una fallisce
- [x] Ultima risorsa sempre disponibile: nessuna richiesta resta senza risposta
- [x] La scena registra **quale strategia** l'ha prodotta e tutti i tentativi

### Fase 12 — Materiali e texture (9 settembre 2026)
- [x] `app/materials/texture.py`: nove texture procedurali (metallo graffiato,
      gomma, legno, squame, pelo, intonaco, pelle, vetro, calcestruzzo). Nessun
      file immagine nel repository: si calcolano da un seme
- [x] Rumore frattale che si chiude su se stesso, quindi piastrellabile senza
      cuciture visibili
- [x] `app/materials/library.py`: le **finiture** sono dati (`finishes.json`),
      separate dai materiali. Il materiale dice il colore, la finitura la grana
- [x] Ripiego per parola chiave: "tire_front" trova la gomma senza doverlo elencare
- [x] `app/geometry/uv.py`: proiezione a scatola per faccia, in metri, per le
      mesh estratte dai campi, che non hanno una parametrizzazione naturale
- [x] Export GLB con mappe PBR complete: colore base, metallico/rugosita'
      impacchettati come vuole glTF, e normali dalla mappa di altezza
- [x] Anteprima e viewport interattivo: campionamento **triplanare** nello
      shader dalla posizione di mondo, senza UV nei vertici
- [x] Intensita' per finitura: la vernice ha una grana appena accennata, la
      corteccia quasi solo grana
- [x] Interruttore Texture nella barra strumenti, `--no-textures` nella CLI

**Trovato lungo la strada:** su Windows `con.glb`, `aux.glb`, `nul.glb` non sono
file ma **dispositivi**. Esportare su AUX blocca il processo. L'esportatore ora
riconosce i nomi riservati e salva con un suffisso, invece di piantarsi.

### Fase 13 — Ricerca semantica (9 settembre 2026)
- [x] `app/assets/semantic.py`: interfaccia `Embedder` con due realizzazioni
- [x] **Locale**: TF-IDF sul corpus della libreria piu' un dizionario di
      sinonimi italiano/inglese. Nessuna rete, nessuna chiave, nessuna
      dipendenza nuova: e' il percorso predefinito
- [x] **Remota**: embedding da endpoint compatibile OpenAI, quando c'e'.
      Se fallisce si ricade sul TF-IDF, e da li' sulla ricerca testuale
- [x] Indice su disco che si ricostruisce da solo quando la libreria cambia;
      salva anche vocabolario e idf, senza i quali i vettori sarebbero inutili
- [x] Collegata a UI e CLI

**Criterio raggiunto**: "un pneumatico da fuoristrada" trova la jeep, "un
arbusto sempreverde" il pino, "un'arma da taglio" la spada, "abitazione" la casa.
**Limite dichiarato**: le parafrasi lontane ("dove mi siedo") restano fuori
portata di TF-IDF; e' il lavoro degli embedding veri.

### Fase 14 — Formato progetto `.my3d` (9 settembre 2026)
- [x] Archivio zip con metadati, cronologia completa e anteprima
- [x] Dentro ci sono i **piani**, non le mesh: un progetto con quattro versioni
      pesa 3 KB invece di decine di megabyte
- [x] Salva/apri da UI e CLI, con cursore e undo/redo ricostruiti
- [x] Numero di versione del formato e migrazione: un progetto salvato da una
      versione futura non fa esplodere l'applicazione
- [x] Una versione illeggibile viene saltata, non fa perdere il resto

### Fase 15 — Ottimizzazione e "game ready" (9 settembre 2026)
- [x] **LOD per rigenerazione**: un sistema procedurale non deve decimare, puo'
      ricostruire lo stesso piano a dettaglio inferiore. Mesh pulite, non
      residui di semplificazione
- [x] Decimazione per raggruppamento di vertici come ripiego, per le mesh che
      non si possono rigenerare. Poche righe di numpy, nessuna dipendenza:
      `fast_simplification` sarebbe servito solo per l'errore quadrico
- [x] Fusione per materiale, mesh di collisione convessa entro 256 facce
- [x] La collisione viene riportata a **contenere** il modello dopo la
      decimazione: un volume piu' piccolo lascerebbe compenetrare gli oggetti
- [x] Preset Unity, Unreal, Godot, generico, con budget di triangoli applicato
- [x] `--game-ready` da CLI: scrive LOD e collisione pronti per l'import

### Fase 16 — Generazione AI di mesh (9 settembre 2026)
- [x] `app/ai/mesh_provider.py`: interfaccia `MeshGenerator`, richiesta con
      vincoli, servizio con ordine di tentativi e ripieghi
- [x] Pulizia obbligatoria di cio' che arriva: vertici doppi, facce degeneri,
      normali, decimazione al budget, scala e appoggio a terra
- [x] Filtro di qualita': una mesh troppo povera o in pezzi non entra in scena
- [x] Quarta strategia collegata al gestore, dopo template, composizione e libreria
- [x] Fornitore locale finto per sviluppare e provare tutto il percorso

**Blocco esterno dichiarato**: il fornitore vero (Hunyuan3D, TripoSR) richiede
una chiave HuggingFace e un modello attivo. Senza, `available()` e' falso e il
gestore passa oltre senza che l'utente se ne accorga.

### Fase 17 — Prompt compositivo per l'LLM (9 settembre 2026)
- [x] Il prompt di sistema contiene entrambe le strade — template e
      assemblaggio — e il catalogo completo delle ricette. L'LLM sceglie
- [x] I socket sono elencati con i **nomi veri**: scrivere "leg_front[]"
      faceva inventare "leg_front_0" al posto di "leg_front_l"
- [x] Ricerca dei socket tollerante ai suffissi plausibili
- [x] Ricette, socket e parametri inventati vengono scartati, non fanno fallire
- [x] **Una sola** chiamata di correzione, e solo se la riparazione
      deterministica non basta. Una correzione che non migliora viene scartata
- [x] Nuovo controllo di **fedelta' alla richiesta**: se l'utente ha chiesto
      due ali e il piano non ne ha, l'assemblaggio viene ricostruito
      dall'archetipo, che la richiesta la legge per intero
- [x] Nuovo controllo di **proporzione delle appendici**: un drago di sette
      metri con zampe di cinque centimetri e' un errore, non uno stile

### Fase 18 — Immagine di riferimento (9 settembre 2026)
- [x] `app/ai/reference.py`: misura locale di una foto — sagoma, proporzioni,
      simmetria, colori dominanti. Nessuna rete, nessuna chiave
- [x] Sfondo **multiplo**: cielo e asfalto sono due sfondi diversi. Con un
      colore medio solo, la striscia d'asfalto entrava nella sagoma e l'auto
      risultava larga quanto l'inquadratura
- [x] Apertura morfologica e macchia connessa piu' grande: via le righe di
      confine fra i due sfondi e i frammenti isolati
- [x] Descrizione con un modello vision, quando la catena ne ha uno che accetta
      immagini. Se manca, o rifiuta, si prosegue con le sole misure
- [x] Due viste: il fianco da' la lunghezza, il fronte la larghezza. Con una
      vista sola il rapporto trasversale resta dichiaratamente ignoto
- [x] `app/ai/shape_match.py`: **riconoscimento per sagoma** contro il catalogo
      procedurale. Ogni template viene costruito ai valori predefiniti,
      proiettato di lato e ridotto a un profilo di larghezze a 24 altezze.
      Un'auto e' larga sotto e stretta in cabina, un albero e' l'opposto
- [x] Rasterizzazione a scanline scritta a mano: `mesh.projected()` di trimesh
      richiede `shapely`, che non e' installato e non vale una dipendenza nuova
- [x] Quando i primi due candidati sono vicini non si sceglie: un'ipotesi
      sbagliata sarebbe peggio di nessuna ipotesi
- [x] Precedenza dichiarata: parole dell'utente > modello vision > sagoma
- [x] Colore e proporzioni misurati vengono **bloccati**: le varianti
      successive continuano ad assomigliare al riferimento
- [x] `Session.generate_from_image`, `--image` / `--front` da CLI, pulsante
      "Genera da un'immagine..." nella UI

**Criterio raggiunto**, nella forma piu' dura: dalla sola foto di un'auto
rossa — nessun modello vision, nessuna parola dell'utente — esce un veicolo
rosso lungo 4,6 m e alto 1,7 m, cioe' le proporzioni della foto.
**Limite dichiarato**: la sagoma sa dire "somiglia a un veicolo", non "e' una
utilitaria a tre porte". Per quello serve il modello vision.

### Fase 19 — Scheletro e animazione (9 settembre 2026)
- [x] `app/anim/skeleton.py`: lo scheletro **non si costruisce, si legge**. Il
      grafo delle parti e' gia' una gerarchia e ogni socket di attacco e' gia'
      il punto attorno a cui la parte deve ruotare
- [x] Assi del corpo ricavati dalla posizione della testa, non dai nomi:
      longitudinale, laterale, verticale
- [x] Sfasamenti dell'andatura in diagonale — anteriore destra con posteriore
      sinistra — che su un bipede degenerano nel semplice alternarsi
- [x] `app/anim/clip.py`: riposo, camminata, battito d'ali. Rotazioni sui
      giunti, **nessuno skinning**: i modelli sono fatti di pezzi rigidi
- [x] Le rotazioni usano gli assi del **corpo**, non quelli del singolo socket:
      due gambe simmetriche hanno terne specchiate, e con quelle un passo
      alterno sarebbe diventato un passo simultaneo
- [x] Ampiezze decrescenti lungo l'arto: l'anca fa il passo, il piede rifinisce
- [x] Si esportano solo le animazioni che il modello puo' fare: un pesce non
      cammina, un cavallo non batte le ali
- [x] `app/anim/pose.py`: cinematica diretta, per verificare e per l'anteprima
- [x] `app/anim/gltf.py`: glTF binario animato **composto a mano**
- [x] Riproduzione nella UI (scheda Animazione) e `--animate` da CLI

**Perche' il glTF a mano:** trimesh esporta glTF ma non scrive animazioni — non
ha `animations` ne' `samplers` nello scrittore, e non c'e' un parametro per
aggiungerle. Le alternative erano `pygltflib` (una dipendenza per una manciata
di dizionari) o comporre il JSON. Serve solo la parte con nodi, accessori e
canali di rotazione, quindi si compone.

**Verifica strutturale:** riaprendo il file animato senza animarlo si
riottengono i limiti del modello di partenza a meno di 1e-5 m. La catena delle
traslazioni dei nodi ridA' esattamente i pivot originali.

**Limite dichiarato, non aggirato:** il corpo di un assemblaggio e' una
superficie fusa e continua. Ruotando una coscia la cucitura all'anca si apre,
perche' i triangoli attorno al giunto appartengono a parti che si muovono in
modo diverso. Le ampiezze sono tenute contenute proprio per questo. Nasconderlo
del tutto richiederebbe pesi di skinning, cioe' esattamente la cosa che qui non
si vuole.

### Fase 20 — Distribuzione (9 settembre 2026)
- [x] `app/core/hardware.py`: core, memoria e scheda rilevati senza dipendenze
      nuove — `GlobalMemoryStatusEx` via `ctypes`, `os.cpu_count()`,
      `nvidia-smi` e in subordine una query WMI
- [x] Un valore non rilevato resta `None`, non diventa zero: con la memoria
      ignota si sceglie il profilo prudente, non quello ottimista
- [x] Tre profili (basso, medio, alto) che **scalano** la risoluzione dello
      stile invece di sostituirla: lo stile e' una scelta dell'utente, il
      profilo dice solo quanto quella macchina puo' spingere
- [x] Il criterio e' CPU e RAM, non la GPU: la generazione e' marching cubes e
      numpy, cioe' lavoro di processore. La scheda conta per l'anteprima
- [x] `--quality`, `--hardware` e `GEN3D_QUALITY` per forzare
- [x] `app/core/recovery.py`: salvataggio periodico e recupero dopo crash. Un
      progetto contiene i piani e non le mesh, quindi pesa meno di un kilobyte
      per versione: salvare spesso non si sente
- [x] Scrittura su file provvisorio e rinomina: se il programma muore *durante*
      il salvataggio automatico, il recupero precedente resta intatto
- [x] Nessun timer: si salva subito dopo un'azione dell'utente, che e' l'unico
      momento in cui c'e' qualcosa di nuovo da salvare. Cosi' UI, CLI e test
      usano lo stesso meccanismo senza thread da spegnere
- [x] All'avvio si **propone** il recupero, non lo si impone. Un recupero
      rifiutato non viene cancellato subito: resta finche' non lo sostituiscono
      sessioni piu' recenti
- [x] `packaging/build.py`: cartella `dist/3DGen` (432 MB) e zip (183 MB),
      costruiti e **provati**: l'eseguibile parte e resta su
- [x] Installato, i dati dell'utente escono dalla cartella del programma e
      vanno in `%LOCALAPPDATA%\3DGen`: in Programmi non si puo' scrivere
- [x] `packaging/3dgen.iss` per Inno Setup, con disinstallazione che **non**
      tocca libreria e progetti dell'utente

**Perche' una cartella e non un file unico:** PySide6, trimesh, scikit-image e
numpy fanno un eseguibile monolitico che si scompatta in una cartella
temporanea a ogni avvio, con secondi di attesa. La cartella parte subito, e
dentro l'installer la differenza sparisce.

**Blocco esterno dichiarato:** l'installer `.exe` vero richiede Inno Setup
(`iscc.exe`), che su questa macchina non e' installato. Lo script `.iss` e'
scritto secondo la documentazione di Inno Setup 6 ma **non e' mai stato
compilato**, e va provato prima di distribuirlo. `build.py` lo usa da solo non
appena `iscc` e' presente.

### Verifica finale end-to-end (9 settembre 2026)

Provando la catena intera con l'LLM vero sono emersi due difetti, corretti:

- [x] **`--animate` sovrascriveva se stesso.** Con `--out grifone.glb` il glTF
      animato veniva scritto su quel nome, e subito dopo l'export normale ci
      scriveva sopra la versione statica. Ora l'animato e' `<nome>_animato.glb`
- [x] **Gli assemblaggi non erano appoggiati a terra.** Le parti si compongono
      attorno all'origine del corpo, quindi le zampe finivano sotto lo zero e il
      controllo di qualita' lo segnalava su *ogni* creatura. Ora la scena viene
      alzata e lo spostamento e' registrato in `Scene.ground_offset`: si spostano
      le mesh, non le pose, perche' le pose condividono gli oggetti con la
      composizione e i campi SDF su cui lavorano i validatori non si spostano con
      loro. Lo scheletro somma l'offset, cosi' i giunti restano dentro le parti

---

## I cinque banchi di prova

Sono la definizione operativa di cosa il software deve saper fare, e sono
**eseguibili**: `tests/test_benchmarks.py`. Quelli non ancora raggiunti sono
`xfail(strict=True)`, quindi il giorno in cui iniziano a passare la suite lo
segnala invece di restare zitta.

| # | Richiesta | Cosa dimostra | Stato |
|---|---|---|---|
| 1 | "crea una jeep" | usa il generatore parametrico | **verde** |
| 2 | "jeep con sei ruote, cassone, cabina aperta" | estende senza scrivere un generatore nuovo | **verde** |
| 3 | "crea un pesce" | composizione senza template dedicato | **verde** |
| 4 | "un pesce con corpo di persona e quattro braccia" | ibrido fra categorie | **verde** |
| 5 | "corpo di lupo, sei tentacoli, ali da pipistrello, corazza" | apertura totale | **verde** |

Più un test che deve restare verde per sempre: **nessuna richiesta, nemmeno
priva di senso, resta senza risposta** (regola 9).

Il banco 4 è quello decisivo: se funziona senza generazione AI di mesh,
l'architettura ha superato i template.

---

## Da fare, in ordine

**Vuoto.** Tutta la roadmap compositiva e' chiusa: fasi 1-20 nella sezione
"Fatto", cinque banchi di prova verdi, 692 test.

Il debito tecnico noto e i limiti dichiarati sono in fondo a questo file. Non
sono voci di roadmap: sono cose che si sanno e si sono decise, non dimenticate.

## Escluso di proposito

| Cosa | Perché no |
|---|---|
| Un generatore parametrico per ogni categoria di oggetto | Non scala: è il problema che la composizione risolve |
| AI che genera la mesh finale da zero come strategia primaria | Lenta, costosa, incontrollabile; resta come quarta strategia |
| Ciclo di validazione con l'LLM che giudica la mesh | Richiede rendering e vision a ogni giro; sostituito da vincoli in codice |
| Text-to-3D locale (Shap-E e simili) | Su 6 GB di VRAM produce blob inutilizzabili |
| `bpy` come modulo pip | Non esiste per Python 3.13; il Blender installato è il 2.93 |
| Blender come dipendenza obbligatoria | trimesh + manifold3d coprono il fabbisogno |
| Engine di rendering proprietario | Il viewport attuale basta |
| Marketplace di asset | Prodotto diverso, non tecnologia |
| Provider LLM a pagamento nella catena | OpenAI e DeepSeek configurati ma fuori dal failover |

---

## Debito tecnico noto

Elenco onesto di ciò che si sa e non si è risolto. Nessuna di queste voci
impedisce a una funzione di funzionare; tutte renderebbero il codice migliore.

- [ ] `app/ai/offline.py` è cresciuto molto: separare le tabelle dalla logica
- [ ] Il blocco dei parametri espliciti nel percorso LLM è approssimato: lock su
      tutto ciò che il modello restituisce
- [ ] Nessun test automatico sulla UI oltre allo smoke (`tests/_smoke_gui.py`).
      Le tre schede aggiunte (immagine, animazione, recupero) sono provate
      attraverso `Session`, non attraverso i widget
- [ ] La chiave Mistral in `.env` viene rifiutata con 401: da rigenerare o togliere
- [ ] I generatori non condividono un modo comune di dichiarare le proporzioni;
      `apply_hints` deve conoscere i nomi `length`/`width`/`height` per sapere
      dove mettere le misure prese da una foto
- [ ] La sagoma di riferimento si confronta solo con i **template**, non con gli
      archetipi compositivi: una foto di drago non può ancora dare un drago
- [ ] L'anteprima dell'animazione ricarica l'intera scena a ogni fotogramma
      (`Viewport.set_scene`). Su modelli molto densi si sente: servirebbe
      aggiornare le sole matrici dei nodi
- [ ] `packaging/3dgen.iss` non è mai stato compilato: manca Inno Setup
