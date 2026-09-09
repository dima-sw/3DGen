# 3DGen — cambio di rotta: architettura a plugin, stile cartoon low-poly

Documento di lavoro. Contiene: cosa ho capito della nuova direzione, che cosa
ne penso davvero, che cosa del codice attuale sopravvive e che cosa va rifatto,
lo stato reale del repo adesso, e il nuovo TODO in ordine con i criteri per
dire "fatto".

Ultimo aggiornamento: **9 settembre 2026**. Stato: **762 test verdi, nessuno
rosso**. Chiusi item 0, 1, 1.5 (kernel poligonale) e la prima meta' del 2
(parti ricorsive e `detail_level`). Il plugin umanoide esiste e costruisce
(§ 4ter).

---

## 1. Cosa ho capito

La catena diventa:

```
UTENTE
  ↓
LLM  →  JSON di piano   (sceglie plugin, parti, parametri, effetti)
  ↓
PLUGIN RESOLVER         (quale plugin, quale etichetta di stile)
  ↓
PART GRAPH              (parti gerarchiche, socket, detail_level)
  ↓
PARAMETRIZZAZIONE       (valori validati contro lo schema del plugin)
  ↓
EFFECT PIPELINE         (allunga, piega, torci, esagera)
  ↓
GEOMETRIA PROCEDURALE   →  LOW POLY  →  MATERIALI  →  MODELLO
```

Le quattro idee portanti, come le ho lette:

1. **Un solo stile: cartoon + low poly.** Non un'opzione fra quattro. È il
   linguaggio estetico del prodotto.
2. **Plugin** = un vocabolario 3D specializzato e installabile (umanoide,
   veicolo, arma, arma a distanza, edificio, creatura…). Se manca qualcosa, si
   installa un plugin, non si tocca il core.
3. **Parti gerarchiche.** Un plugin contiene parti; una parte contiene altre
   parti; la profondità a cui ci si ferma è il `detail_level`. Non è "più parti
   = più dettaglio", è un **LOD semantico**.
4. **Effetti.** L'AI non inventa geometria. Genera l'oggetto proceduralmente
   con parametri validi, poi dichiara *effetti* ("slanciata", "storta") che
   sono deformazioni dichiarate e limitate dal plugin.

E il punto che tiene su tutto:

```
LLM = generatore/modificatore di JSON
LLM ≠ modellatore 3D
```

Questo non cambia rispetto a prima. È l'unica cosa che nel progetto attuale
non è mai stata in discussione, ed è giusto che resti.

---

## 2. Giudizio onesto

### Dove la direzione è giusta, e molto

**Cartoon + low poly come unico stile è la decisione più importante di tutte,
più dei plugin.** Elimina l'asse su cui non si può vincere ("è abbastanza
realistico?") e trasforma in *prodotto* il lavoro che serve comunque:
silhouette leggibile, pochi triangoli, piani scelti. In questa sessione ho
appena costruito esattamente i pezzi che servono a quello stile — profili di
sezione, decimazione a errore quadrico, flat shading. Con lo stile unico
diventano il motore, non un'opzione.

Ha anche una conseguenza pratica che vale la pena dire: **semplifica il
codice**. `STYLE_RESOLUTION`, `STYLE_SMOOTH`, `STYLE_BUDGET`, i quattro rami
di stile nei generatori e il parametro `style` nel piano si riducono a un
profilo solo più un `detail_level`. Meno superficie, meno test, meno modi di
sbagliare.

**Separare "cosa so costruire" da "cosa costruire" è corretto**, e in parte è
già così: le ricette sono JSON dati, non codice; c'è un catalogo; c'è uno
strato di composizione. Il plugin è la scatola che mancava attorno a queste
cose.

**Gli effetti come stadio a valle è giusto**, e c'è già l'infrastruttura:
`app/geometry/sdf.py` implementa `elongate, taper, bend, twist, round, shell,
mirror, repeat` come deformazioni della coordinata di interrogazione. "Casa
slanciata" = `elongate` sull'asse verticale. Non c'è niente da inventare, c'è
da **esporlo come vocabolario dichiarato** invece che tenerlo dentro le
ricette.

### Dove non sono d'accordo, o dove il rischio è più grosso di come suona

**a) Il sistema di plugin è imballaggio, non capacità. Va messo in fondo, non
davanti.**

Questa è la mia obiezione principale. Un plugin, come è descritto, è:
ricette + schema parametri + archetipo + effetti ammessi + vincoli. Nel repo
attuale esistono già tutte e cinque le cose, sparse in `app/geometry/parts/`,
`app/geometry/templates/`, `app/ai/creature.py`, `app/build/validation.py`.
Raggrupparle in cartelle con un manifesto è **una riorganizzazione**, ed è
un miglioramento reale di ordine ed estensibilità — ma non produce un solo
modello più bello.

Il rischio concreto è passare tre settimane su caricatore di plugin, formato
del manifesto, versioni, dipendenze fra plugin, sandbox — e ritrovarsi con gli
stessi modelli di adesso. **I modelli sono il prodotto; il plugin system è
idraulica.** Nel TODO qui sotto l'ho messo dopo la qualità, non prima.

**b) `detail_level` è l'idea nuova che vale davvero, più dei plugin.**

Ed è anche la più difficile, per una ragione che va detta subito: i livelli
devono **sostituire**, non solo aggiungere. Se al livello 2 il torso diventa
petto+addome+bacino, il torso del livello 1 non deve restare lì sotto: sparisce
e viene rimpiazzato da tre parti che occupano lo stesso volume. Altrimenti si
ottiene geometria doppia, compenetrata, e un conto di triangoli che esplode.

Vuol dire che una parte deve poter dichiarare la propria **espansione**:

```
Torso (livello 1)
  espansione → [Chest, Abdomen, Pelvis]  con i socket riportati sui figli
```

e il costruttore sceglie a che profondità fermarsi. Questo è vero lavoro di
progettazione, non configurazione.

**c) Il livello di composizione sopra i plugin non è un dettaglio: è il
banco di prova che il progetto ha già superato e non deve perdere.**

Oggi funziona: "un pesce con il corpo di una persona e quattro braccia" e
"corpo di lupo, sei tentacoli, ali da pipistrello, corazza" producono modelli
strutturalmente corretti (banchi 4 e 5 in `tests/test_benchmarks.py`). Sono
verdi. **Qualunque disegno di plugin che non sappia esprimere "testa di drago
su torso umanoide" è un passo indietro rispetto a stasera.** Lo metto come
vincolo duro, non come desiderata.

**d) Gli effetti hanno bisogno di uno stadio dichiarato, non solo di un
intervallo.**

ChatGPT dice giustamente che l'AI non deve poter scrivere `bend: 999999`. Il
contratto dei parametri esiste già (`ParamDef` con `min/max/choices`), va
riusato. Ma manca una cosa: **su cosa** agisce l'effetto. Piegare un torso non
è piegare tutto l'umanoide; allungare una casa non è allungare il suo camino.
Un effetto deve dichiarare l'ambito:

```
scope: "model" | "group:<tag>" | "part:<id>"
```

Senza questo, "slanciata" applicata al modello intero allunga anche le finestre
e le porte, e viene una casa di gomma.

**e) Una trappola che nessuno ha nominato: cartoon e proporzioni anatomiche
litigano.**

In questa sessione ho costruito validatori che rifiutano proporzioni assurde
(`check_appendage_proportions`, `APPENDAGE_RATIO`). Il cartoon **vive di
esagerazione**: testa enorme, mani grosse, gambe corte. Se i validatori restano
tarati sull'anatomia, combatteranno la direzione artistica e la riporteranno
verso il realismo — cioè faranno esattamente il danno che devono prevenire.

Serve che gli intervalli di proporzione siano **dati dello stile**, non
costanti nel codice: un profilo `cartoon` con testa fino al 45% del corpo, e i
validatori che leggono da lì. Non è tanto lavoro, ma se ci si dimentica se ne
accorge tardi e male.

**f) Cose che taglierei adesso**

- **Marketplace, plugin di terze parti, sandbox, versioni.** Non ora. Un
  plugin è una cartella che il progetto carica all'avvio. Basta.
- **"Realistic Humanoid" come variante di plugin.** Avete appena dichiarato
  che lo stile è uno solo: non costruite l'asse che avete escluso.
- **Il parametro `style` nel piano.** Se lo stile è uno, va via. Resta
  `detail_level`. (Le etichette di stile *dei plugin* sono un'altra cosa e
  servono: due plugin umanoide diversi, non due stili di render.)

**g) Una conseguenza scomoda, per onestà**

Con lo stile unico cartoon, il lavoro della **fase 18 (immagine di
riferimento)** perde parecchio valore: misurare le proporzioni di una foto per
riprodurle serve poco se poi lo stile le esagera per scelta. Resta utile
l'estrazione del **colore**; il riconoscimento per sagoma (`shape_match.py`) va
ripensato o messo in naftalina. Non la butterei, ma smetterei di considerarla
una funzione di punta.

### Verdetto

Sì, ci andrei. Con questo ordine, che è diverso da quello suggerito:

```
1. stile unico cartoon low-poly     (semplifica e migliora subito)
2. parti gerarchiche + detail_level (è qui il valore nuovo)
3. effetti dichiarati               (è qui la resa sui prompt liberi)
4. plugin come confezione           (è qui l'estensibilità, ed è l'ultima)
```

Il prototipo attuale non va buttato. Va **spostato sotto**: SDF, socket,
composizione, decimazione, validazione e benchmark diventano il core su cui i
plugin poggiano.

---

## 3. Che cosa sopravvive e che cosa cambia

### Sopravvive quasi tutto il motore (non riscrivere)

| File | Ruolo nel nuovo assetto |
|---|---|
| `app/geometry/sdf.py` | Volumi + **operazioni = vocabolario degli effetti** |
| `app/geometry/recipe.py` | Formato delle parti, socket, valutatore di espressioni |
| `app/geometry/composition.py` | Innesto per socket, fusione, ripartizione per proprietario |
| `app/geometry/lowpoly.py` | Decimazione a errore quadrico: **è il motore dello stile** |
| `app/geometry/surface.py` | Marching cubes, risoluzione dettata dalla parte più sottile |
| `app/build/validation.py` | Vincoli deterministici (con § 2e: intervalli come dati) |
| `app/build/visual.py` | Metriche di sagoma — diventa il quality gate dello stile |
| `app/anim/` | Scheletro dal grafo delle parti, animazione rigida, glTF |
| `app/core/session.py` | Unica API per UI e CLI: **non cambia** |
| `tests/test_benchmarks.py` | I cinque banchi: **non si toccano, non si indeboliscono** |

### Cambia

| Cosa | Da | A |
|---|---|---|
| Organizzazione ricette | `app/geometry/parts/*.json` piatte | `plugins/<nome>/parts/*.json` |
| Archetipi | `app/ai/creature.py`, `templates/humanoid_body.py` | `plugins/<nome>/archetype.py` |
| Registro template | `app/geometry/templates/__init__.py` | registro plugin |
| Stile | `style` a 4 valori nel piano | tolto; resta `detail_level` |
| Deformazioni | dentro le ricette | `effects: [...]` nel piano, con ambito |
| Proporzioni ammesse | costanti in `validation.py` | dati del profilo di stile |
| Schema del piano | `GenerationPlan` | `+ plugin, detail_level, effects`; `- style` |

### Va progettato ex novo

- **Manifesto di plugin** (`plugin.json`): nome, categoria, etichetta di stile,
  versione, parti esposte, effetti ammessi con intervalli, vincoli.
- **Espansione gerarchica delle parti** e risoluzione del `detail_level`.
- **Pipeline degli effetti** con ambito (`model` / `group:<tag>` / `part:<id>`).
- **Composizione fra plugin** (testa di drago su torso umanoide).

---

## 4. Stato reale del repo

Test: **727 verdi, nessuno rosso.**

### Item 0 — i cinque test rossi: chiuso

Nessuno e' stato indebolito; in tre casi su cinque il test aveva ragione e ho
corretto l'implementazione.

| Test | Che cosa ho fatto |
|---|---|
| `test_style_detection` | La funzione che verificava non esiste piu': sostituito con `test_density_detection`, piu' `test_there_is_only_one_style` e `test_density_only_changes_the_triangle_count` |
| tre test di `shape_match` | Il peso della proporzione era troppo basso. **Tarato su sette casi noti**: fra 0,25 e 0,70 li classifica tutti giusti, il margine sul piu' debole passa da 0,06 a 0,20. Preso 0,45, il mezzo dell'intervallo verificato — non ho allargato la soglia |
| `test_lods_are_regenerated_when_possible` | La scala dei LOD era agganciata allo stile e partiva sempre dal dettaglio massimo. Ora scende **di densita', relativa al piano** |
| `test_lods_fall_back_to_decimation_without_a_plan` | La catena non era monotona (1668, 140, 398): la decimazione ripartiva ogni volta dall'originale. Ora si decima **il livello precedente**, quindi ogni gradino e' per costruzione piu' leggero |

### Item 1 — stile unico cartoon low-poly: chiuso

- **`app/core/style.py`**: un posto solo per budget triangoli, risoluzione,
  lisciatura, arrotondamenti, rapporto di fusione, intervalli di proporzione,
  esagerazione, materiali. Chi deve sapere "come deve venire" chiede qui.
- **`style` non esiste piu' nel piano.** Al suo posto `density` (0,3-2,4), che
  e' un'altra cosa: **non cambia l'aspetto, solo quanti triangoli servono** a
  ottenerlo. Toccati 17 file di codice e 10 di test.
- **Gli intervalli di proporzione sono dati dello stile**, non costanti nel
  validatore. Era il rischio nominato al § 2e, ed era reale: con i numeri
  anatomici i controlli avrebbero riportato il cartoon verso il realismo.
- **Esagerazione cartoon applicata**: testa x1,28, occhi x1,45, mani x1,30,
  piedi x1,25, arti x0,90, torace x1,08. Vale per l'umanoide e per le creature.
- **Testa dimensionata sul corpo**, non da tabella assoluta: era il difetto piu'
  visibile del banco 4 (un cranio di pesce da mezzo metro su un torso umano).
- **Piedi e mani orientati**: un piede punta in avanti e sporge dietro la
  caviglia, una mano continua l'avambraccio (`pitch`, `heel`, `toe`).
- **Materiali piatti di serie**; le texture restano, ma si chiedono.
- CLI: `--style` -> `--density`, `--no-textures` -> `--textures`.
  UI: via la tendina degli stili, resta "Dettaglio" (leggero/normale/fitto).

### Due difetti che i test hanno preso al volo

Vale la pena registrarli, perche' dicono che la rete tiene:

1. Accorciando le gambe per il cartoon, l'umanoide non era piu' alto quanto
   chiesto (1,80 -> 1,57). `test_a_humanoid_is_as_tall_as_requested` e' caduto
   subito. Corretta la resa; **e ho sbagliato la prima correzione**, misurando
   il fattore senza azzerarlo prima — il test e' caduto di nuovo. Ora la
   procedura per rimisurarlo e' scritta accanto alla costante.
2. Un pesce con il corpo a palla non veniva piu' segnalato, perche'
   l'allungamento si misurava sull'ingombro di **tutto** il modello e la coda
   lunga lo salvava. Ora si misura sul corpo, che e' dove sta il difetto.

### I cinque modelli di riferimento, adesso

| | triangoli | riempimento | parti |
|---|---|---|---|
| pesce | 3.998 | 0,85 | 9 |
| lupo | 4.000 | 0,76 | 17 |
| drago | 4.000 | 0,57 | 19 |
| ibrido (banco 4) | 4.000 | 0,68 | 23 |
| umanoide | 4.000 | 0,73 | 20 |

Riempimento = quanto il modello occupa il proprio guscio convesso; 1,00 e' una
patata, una sfera vale 1,00. Immagini in `output/qualita/v2_*.png`.

Tempo di generazione: 0,56-1,70 s a modello.

### Che cosa resta valido dal lavoro precedente

`Profile` (sezioni controllate), `app/geometry/lowpoly.py` (decimazione a
errore quadrico, 1,2 s), estrazione separata delle lamine, fusione
proporzionata allo spessore, ricette `body`/`head`/`limb`/`torso`/`blade`,
umanoide come assemblaggio, `app/build/visual.py` con 20 test, animazione,
distribuzione.

## 4bis. Il difetto vero: geometria campionata invece che costruita

Item 0 e 1 hanno migliorato le proporzioni, i profili e i materiali, ma il
risultato **restava molle**. La causa non era la taratura: era la pipeline.

### La misura

Torso dell'umanoide, costruito con la pipeline attuale
(`SDF -> smooth_min -> marching cubes -> decimazione`):

```
493 facce, 296 direzioni di normale distinte
gruppo di facce complanari piu' grande: 7
angolo diedro mediano: 6,8 gradi     spigoli oltre 25 gradi: 5%
```

Nessuna superficie piatta. Nessuno spigolo. E' **una bolla liscia campionata a
493 triangoli** — non un low poly disegnato, un low poly *campionato*.

E non e' colpa della decimazione: la decimazione a errore quadrico sceglie i
piani meglio del caso, ma li sceglie **su una bolla**. Semplificare bene una
forma sbagliata da' una forma sbagliata con meno triangoli.

### La causa

Il marching cubes non puo' produrre topologia intenzionale. Ogni vertice sta
dove la griglia ha incrociato l'isosuperficie; nessuno spigolo e' una decisione
di forma. Qualunque taratura di risoluzione, budget o lisciatura resta dentro
questo limite.

### La misura che lo dice in un numero

**Facce per direzione di normale distinta.**

| | facce | normali | facce/normale | spigoli duri |
|---|---|---|---|---|
| torso costruito per regola | 56 | 26 | **2,15** | 50% |
| torso campionato (attuale) | 420 | 401 | **1,05** | 21% |

Vicino a 1 significa che ogni triangolo guarda per conto suo: bolla. Vicino o
sopra 2 significa quadrilateri piani, cioe' facce vere. E' il criterio che
mancava, ed e' calcolabile in una riga.

### La soluzione: `app/geometry/kernel.py`

Una parte diventa **una regola che emette poligoni**:

```python
anelli = [ring(6, x=0.0, r=0.14), ring(6, x=0.5, r=0.18), ring(6, x=1.0, r=0.11)]
mesh = sweep(anelli)          # cuce, chiude, orienta
```

Conseguenze, tutte nella direzione giusta:

- **Facce piatte e spigoli per costruzione.** Niente da decimare.
- **Conteggio noto in partenza**: `(stazioni-1) x lati x 2` triangoli. Un torso
  sono 56 facce, non 420 da ridurre.
- **Topologia stabile**: la stessa parte ha sempre gli stessi vertici. Serve
  alle animazioni e ai livelli di dettaglio.
- **Nessuna griglia**: sparisce il problema delle lamine piu' sottili di una
  cella, l'innalzamento di risoluzione, il budget, la decimazione.

Un dettaglio che si e' rivelato decisivo: gli anelli vanno costruiti
**circolari** e la sezione ellittica va applicata dopo, come scala non uniforme.
Con anelli gia' ellittici i quadrilateri del fianco non sono piani e si torna a
78 normali su 108 facce — di nuovo una bolla. Una trasformazione affine manda
piani in piani, quindi fatta dopo lascia tutto piatto: 26 normali su 56 facce.

### Che cosa si perde, e perche' va bene

Si perde la **fusione morbida in un corpo unico**. E' un guadagno, non una
perdita, per tre motivi:

1. Nel cartoon low poly i personaggi sono **fatti di pezzi**, e si vede: e' il
   linguaggio, non un difetto.
2. Sparisce il limite dichiarato dell'animazione — la cucitura che si apriva
   ruotando una coscia. Le parti sono gia' separate: ruotarle e' esatto.
3. Sparisce tutta la macchineria che serviva a tenere insieme la fusione:
   risoluzione dettata dalla parte piu' sottile, estrazione separata delle
   lamine, fusione proporzionata allo spessore, budget, decimazione.

L'SDF **non si butta**: resta per le sottrazioni booleane (l'incavo di una coda
biforcuta, una finestra in un muro) e come opzione organica futura. Ma non e'
piu' il modo normale di fare una parte.

### E rende piu' semplici i due item successivi

- **Effetti** (item 3): su vertici espliciti `elongate`, `bend`, `twist` sono
  trasformazioni dirette ed esatte. L'allungamento e' affine, quindi **non
  rompe la planarita'**. Sull'SDF erano deformazioni del campo da ricampionare.
- **`detail_level`** (item 2): piu' dettaglio = piu' anelli, piu' lati, piu'
  sotto-parti. Il conteggio resta prevedibile a ogni livello.

---

## 4ter. Il plugin umanoide: parti ricorsive, effetti, 708 triangoli

### Il kernel

`app/geometry/kernel.py`. Una parte e' una regola che emette anelli di vertici;
il kernel li cuce in quadrilateri. `ring`, `sweep`, `grow` (cresce dalla base,
che e' la forma naturale di cio' che si attacca), `block` (scatola smussabile),
`faces_per_normal` (il criterio).

Il dettaglio decisivo: gli anelli si costruiscono **circolari** e la sezione
ellittica arriva dopo, come scala non uniforme. Con anelli gia' ellittici i
quadrilateri del fianco non sono piani — 78 normali su 108 facce, di nuovo una
bolla. Una trasformazione affine manda piani in piani: 26 su 56.

### La struttura ricorsiva

`app/plugins/base.py` definisce tre cose e basta:

- **`PartRule`**: parametri con intervallo, una funzione che emette poligoni e
  socket, i figli, gli slot, e un **ruolo** semantico.
- **`Child`**: un figlio strutturale, con il livello da cui compare e se
  **sostituisce** il genitore.
- **`Slot`**: un posto dove puo' andare un dettaglio, con che tipi ci stanno.

La distinzione fra figli e slot non e' formale: i figli sono cio' che la parte
**e'** e vanno con il `detail_level`; gli slot sono cio' che la parte **ha** e
vanno con quello che l'utente chiede.

### Livelli, misurati

| livello | pezzi | triangoli | facce/normale | contenuto |
|---|---|---|---|---|
| 1 | 6 | 408 | 2,34 | torso, testa, 2 braccia, 2 gambe |
| 2 | 17 | 560 | 2,48 | +petto/addome/bacino, collo, omero/avambraccio/mano, coscia/polpaccio/piede |
| 3 | 24 | 708 | 2,36 | +occhi, orecchie, naso, bocca, capelli |

Il torso al livello 2 **non c'e' piu'**: e' stato sostituito, non riempito.
C'e' un test che lo verifica, ed e' la cosa piu' facile da sbagliare.

Confronto con la pipeline che si e' lasciata: 4.000 triangoli a 1,05 facce per
normale. Ora 708 a 2,36. Sei volte meno triangoli, e sono facce vere.

### Le proporzioni sono esatte per costruzione

Le regole lavorano in **frazioni di uno** e il modello finito viene scalato
all'altezza chiesta. Sparisce `HEIGHT_YIELD`, il fattore di resa che andava
rimisurato a ogni ritocco — e che avevo gia' sbagliato una volta. Un test
verifica l'altezza a tre scale, tre livelli e cinque effetti: sempre esatta.

### Gli effetti

Profili di proporzione per **ruolo**, non scale uniformi:

| effetto | cosa fa |
|---|---|
| `spilungone` | arti +42/45%, giro -30%, torace -24%, testa -8% |
| `tozzo` | arti -34/42% ma piu' grossi del 40%, torace +45% |
| `chibi` | testa x1,95, arti dimezzati, piedi e mani grossi |
| `eroico` | torace +22%, braccia +25% di giro, testa -6% |

**Un errore che vale la pena raccontare.** La prima versione applicava
l'effetto a ogni livello: accorciava il braccio del 45%, e poi accorciava di
nuovo l'omero *dentro* un braccio gia' corto. I pezzi non arrivavano piu' dove
il genitore li aspettava e il chibi si e' aperto in una pila di scatole
staccate. La regola giusta: **una volta sola per ruolo**, al primo antenato che
lo porta. Per questo omero e avambraccio condividono il ruolo `arm`. C'e' un
test che lo blocca, e un altro che verifica che nessun effetto stacchi un pezzo.

### Un difetto vero trovato per strada

`ProceduralStubGenerator` usava `hash()` sulle stringhe per il proprio seme.
`hash()` sulle stringhe e' **randomizzato a ogni processo**: il generatore
produceva una forma diversa a ogni esecuzione, e il test che lo dichiarava
deterministico passava lo stesso, perche' confrontava due chiamate dentro lo
stesso processo. Ora il seme e' un CRC32 del testo, stabile ovunque, e un test
lo inchioda al valore.

### Che cosa non c'e' ancora

Detto chiaro, perche' il plugin **non e' finito**:

- gli **slot sono dichiarati ma vuoti**: non esistono ancora cappelli,
  mascherine, caschi da metterci dentro;
- **manca il livello 4** (dita, dettagli fini);
- il plugin **non e' collegato a `Session`**: si costruisce da codice, non
  ancora da un prompt;
- **la vecchia pipeline SDF e' ancora tutta li'**, in parallelo. Niente e'
  stato tolto;
- **solo umanoide**: veicolo, arma, edificio, creatura non ci sono;
- il **viso e' rozzo**: occhi e bocca sono blocchetti, manca un piano del volto.

---

## 5. Nuovo TODO, in ordine

### 0. Chiudere i cinque test rossi — **FATTO**
- [x] Aggiornato l'atteso di `test_style_detection` (poi sostituito del tutto)
- [x] Ricalibrato `shape_match`: peso della proporzione tarato su sette casi
- [x] Scala dei LOD sulla densita', e catena garantita decrescente

---

### 1. Stile unico: cartoon low-poly — **FATTO**
- [x] `app/core/style.py`: un posto solo per tutto cio' che decide l'aspetto
- [x] `style` via dal piano, sostituito da `density`
- [x] Intervalli di proporzione come dati dello stile
- [x] Esagerazione cartoon applicata a umanoide e creature
- [x] Materiali piatti di serie

**Criterio raggiunto:** i cinque modelli sono dello stesso linguaggio
geometrico, fra 3.998 e 4.000 triangoli (limite 6.000), `tests/test_visual.py`
verde. Restano da rifinire la testa dell'ibrido, ancora grande, e il viso
dell'umanoide, che e' una calotta con due occhi.

---

### 1.5 Kernel poligonale — **FATTO**

- [x] `app/geometry/kernel.py`: `ring`, `sweep`, `grow`, `block`,
      `faces_per_normal`
- [x] Anelli circolari piu' scala affine, per non perdere la planarita'
- [x] Le parti dell'umanoide sono regole che emettono poligoni
- [x] `faces_per_normal >= 1.8` come criterio, in `tests/test_plugins.py`

**Criterio raggiunto** sull'umanoide: 708 triangoli a 2,36 facce per normale,
contro 4.000 a 1,05. Resta da portare sul kernel il resto del catalogo
(creature, veicoli, armi) e da togliere la macchineria della fusione, che oggi
convive in parallelo.

### 2. Parti gerarchiche e `detail_level` — **META' FATTO**

Fatto: espansione che **sostituisce**, livelli 1-3, conteggio prevedibile,
altezza esatta a ogni livello, slot dichiarati.
Resta: livello 4, riempire gli slot (cappelli, mascherine), collegare a
`Session`.

#### Traccia originale
- [ ] Una parte può dichiarare la propria **espansione** in sotto-parti, con i
      socket riportati sui figli
- [ ] L'espansione **sostituisce** il genitore, non si somma (§ 2b)
- [ ] `detail_level` 1–4 nel piano; il costruttore si ferma alla profondità
      chiesta
- [ ] Livelli dell'umanoide: 1 torso/testa/arti · 2 petto-addome-bacino,
      braccio-avambraccio-mano · 3 dita, orecchie, occhi, ginocchia · 4
      piastre, bottoni, dettagli meccanici
- [ ] Il conto dei triangoli deve crescere in modo controllato, non esplodere

**Fatto quando:** lo stesso piano a `detail_level` 1 e 3 dà due modelli con la
stessa silhouette e dettaglio diverso, e il livello 3 non ha geometria doppia.

*Nota:* sul kernel poligonale questo diventa "piu' anelli, piu' lati, piu'
sotto-parti", con il conteggio noto a ogni livello.

---

### 3. Pipeline degli effetti
- [ ] `effects: [{type, scope, axis, amount}]` nel piano
- [ ] Ambito dichiarato: `model` / `group:<tag>` / `part:<id>` (§ 2d)
- [ ] Vocabolario iniziale su ciò che esiste già in `sdf.py`: `elongate`,
      `bend`, `twist`, `taper`, `round`, più `exaggerate` (cartoon)
- [ ] Ogni effetto ha intervallo dichiarato dal plugin; fuori intervallo si
      clampa e si annota, non si sbaglia in silenzio
- [ ] L'ordine di applicazione è dichiarato e stabile

**Fatto quando:** "una casa slanciata", "una casa storta", "un robot tozzo"
producono lo stesso oggetto base con deformazioni diverse, e nessun effetto
riesce a produrre geometria non valida.

---

### 4. Plugin come confezione
- [ ] `plugins/<nome>/`: `plugin.json` + `parts/*.json` + `archetype.py`
- [ ] Manifesto: nome, categoria, **etichetta di stile**, versione, parti,
      effetti ammessi, vincoli
- [ ] Registro che scopre i plugin all'avvio; il core non li conosce per nome
- [ ] Migrare l'esistente: `humanoid`, `vehicle`, `weapon`, `building`,
      `nature`, `furniture`, `creature`
- [ ] Nuovi: `ranged_weapon` (era assente)
- [ ] Il prompt di sistema si costruisce dai plugin installati

**Fatto quando:** aggiungere una categoria è aggiungere una cartella, senza
toccare un file del core; e togliendo una cartella il resto continua a
funzionare.

---

### 5. Composizione fra plugin — il vincolo duro
- [ ] Lo strato di composizione sta **sopra** i plugin, non dentro
- [ ] Una parte di un plugin si attacca al socket di un altro plugin se i
      `kind` dei socket sono compatibili
- [ ] I cinque banchi restano verdi, in particolare il 4 e il 5

**Fatto quando:** "robot con corpo umanoide, ali da pipistrello e testa di
drago" attinge a tre plugin e produce un modello coerente.

---

### 6. Ripulire ciò che lo stile unico rende inutile
- [ ] Ridimensionare `app/ai/reference.py` e `shape_match.py` (§ 2g): tenere
      il colore, ripensare la sagoma
- [ ] Rivedere texture procedurali e finiture: nel cartoon servono meno
- [ ] Aggiornare `TODO.md`, `README.md` e i banchi

---

## 6. Regole che restano, e le nuove

Restano (dal mandato precedente):

1. L'AI dirige, la procedura modella. Mai "prompt → AI → mesh finale".
2. Budget AI costante: una chiamata per generazione, al massimo una correzione.
3. Nessun ciclo con l'LLM che giudica il risultato.
4. La UI parla solo con `Session`.
5. Nessuna richiesta resta senza risposta.
6. I benchmark non si indeboliscono, non si cancellano, non si riscrivono per
   farli passare.
7. Dipendenze nuove: documentare perché serve, cosa risolve, perché non basta
   ciò che c'è.

Nuove:

8. **Uno stile solo.** Cartoon low-poly. Chi vuole aggiungere un asse di stile
   deve prima dimostrare che serve.
9. **Un plugin non può rompere la composizione.** Se una parte non è
   componibile con parti di altri plugin, è un template chiuso travestito.
10. **L'AI non scrive numeri liberi.** Ogni valore passa dallo schema del
    plugin, che lo valida e lo clampa.
11. **Il quality gate visivo vale come i test.** Un modello che passa i
    controlli strutturali ma è un blob non è finito.

---

## 7. Rischi, detti chiaramente

| Rischio | Perché è reale | Come lo tengo basso |
|---|---|---|
| Costruire idraulica invece di modelli | I plugin sono la parte divertente da progettare e la meno utile all'utente | Plugin come item 4, non 1 |
| Plugin rigidi = template chiusi | È esattamente il problema da cui il progetto è uscito a fatica | Regola 9 + banchi 4 e 5 verdi come condizione |
| `detail_level` che raddoppia la geometria | Se l'espansione somma invece di sostituire | Test sul conteggio triangoli fra livelli |
| Validatori anatomici contro stile cartoon | Le due cose vogliono numeri opposti | Intervalli come dati dello stile (item 1) |
| Perdere ciò che già funziona | Ci sono 727 test e 5 banchi verdi | Il kernel affianca l'SDF prima di sostituirlo; i banchi restano il criterio |
| Ottimizzare il modo di semplificare una forma sbagliata | È già successo: profili, decimazione a errore quadrico e taratura hanno migliorato una bolla, lasciandola bolla | `faces_per_normal` come criterio, misurato a ogni modello |
| Effetti senza ambito | "Slanciata" allunga anche le maniglie delle porte | `scope` obbligatorio (item 3) |
