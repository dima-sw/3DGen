# 3DGen — generatore 3D controllato dall'AI

Descrivi un oggetto a parole, ottieni un modello 3D, modificalo parlandoci, esportalo.

```
python main.py                                    interfaccia desktop
python cli.py "una jeep militare verde"           da riga di comando
python cli.py "una jeep" --variants 5 --png       cinque varianti diverse
python cli.py "una jeep" --seed 12345             riproduce una variante esatta
python cli.py "una sedia" --save "Sedia buona"    salva nella libreria
python cli.py --library                           elenca la libreria
python cli.py --find albero                       cerca nella libreria
python cli.py --load <id>                         ricarica un asset salvato
python cli.py --providers                         stato dei provider AI
python -m pytest -q                               186 test
```

![anteprima](output/gui.png)

---

## Cosa fa oggi

```
prompt  ->  LLM  ->  JSON validato  ->  generatore parametrico  ->  scene graph  ->  GLB
                            |                                            |
                     regole locali                                   viewport
                    (se l'LLM manca)                                 OpenGL
```

- **9 generatori parametrici**: veicoli (berlina, SUV, fuoristrada, pickup, van, camion,
  sportiva, bus), casa, umanoide/robot, spada/ascia/mazza/lancia, sedia, tavolo,
  albero, roccia, solidi di base.
- **Editing incrementale**: "fai le ruote più grandi", "fallo nero e togli il tetto".
  Tocca solo ciò che serve, il resto resta identico.
- **Varianti**: lo stesso prompt non restituisce due volte lo stesso oggetto, ma
  rispetta sempre ciò che hai chiesto esplicitamente.
- **Libreria di asset**: salvi un oggetto e lo ritrovi dopo aver chiuso l'app,
  ancora parametrico e modificabile a voce.
- **Cronologia** con annulla/ripeti e salto a qualunque versione.
- **Viewport 3D** proprio (OpenGL 3.3 via moderngl), orbita/pan/zoom.
- **Export** GLB, OBJ, STL, PLY + il piano JSON che lo ha generato (riproducibile).
- **Controllo qualità** prima dell'export: mesh chiuse, volumi non degeneri, budget
  poligoni, appoggio a terra, dimensioni plausibili.
- **Funziona senza AI**: se non c'è rete né chiavi, un planner a regole in italiano
  e inglese produce comunque un modello sensato.
- **Composizione di parti**: quando nessun template basta ("un pesce con il corpo di
  una persona e quattro braccia"), il modello viene costruito componendo parti
  generiche su socket e fondendole in un corpo unico e continuo.
- **Immagine di riferimento**: da una foto si ricavano colore e proporzioni, e —
  confrontando la sagoma con il catalogo — anche di che tipo di oggetto si tratta,
  senza alcun modello vision.
- **Animazione delle parti rigide**: dal grafo delle parti si legge uno scheletro,
  e ogni parte ruota attorno al socket che la tiene. Riposo, camminata, battito
  d'ali, in un glTF animato che qualunque motore legge.
- **Qualità automatica**: risoluzione e texture scelte in base alla macchina, con
  `--quality` per forzare.
- **Recupero dopo un crash**: la sessione viene salvata da sola ogni pochi minuti e
  riproposta al riavvio.

### Da una foto

```bash
python cli.py --image auto.jpg --front fronte.jpg --out auto.glb
```

L'analisi locale misura la sagoma (proporzioni, simmetria, colori dominanti) e la
confronta con i profili dei template: un'auto è larga in basso e stretta
nell'abitacolo, un albero è l'opposto. Da una foto di un'auto rossa esce un veicolo
rosso con le proporzioni giuste **senza modello vision e senza una parola scritta**.
Se in catena c'è un modello che accetta immagini, la sua descrizione ha la
precedenza; le parole dell'utente hanno la precedenza su tutto.

### Animazione

```bash
python cli.py "un drago con quattro zampe, due ali e una lunga coda" --animate --out drago.glb
```

Le rotazioni stanno sui giunti, non sui vertici: nessuno skinning, nessun peso, un
glTF che si apre ovunque. Il limite è dichiarato e non nascosto: il corpo è una
superficie fusa, quindi sulle andature ampie la cucitura all'anca si vede.

## Varianti: lo stesso prompt non dà due volte lo stesso oggetto

![varianti](output/varianti.png)

Quattro "una jeep": colori, proporzioni, altezza da terra e accessori diversi.
Ogni generazione riceve un seed nuovo; il pulsante **Un'altra variante (F5)**
ne produce un'altra in 0,05 s, senza spendere una chiamata all'AI.

La regola che tiene insieme il sistema è: **ciò che hai chiesto non cambia mai.**

```
"un fuoristrada rosso a due porte"
   ├─ fuoristrada, rosso, due porte  ->  bloccati, identici in ogni variante
   └─ tutto il resto                 ->  varia
```

Ogni parametro dichiara quanto può variare (`app/geometry/templates/variation_profile.py`).
Vale zero per tutto ciò che definisce *cosa* è l'oggetto — tipo di carrozzeria,
numero di porte, tipo di arma, numero di piani — e cresce per ciò che è solo
questione di gusto: proporzioni, spessori, portapacchi, cuscini, inclinazioni.
Anche una modifica esplicita diventa un vincolo: dopo "fai le ruote più grandi",
nessuna variante successiva le rimpicciolisce.

Il disturbo è additivo e non si accumula: ogni variante riparte dai valori
originali, così la decima non è più lontana dalla richiesta della seconda.
E a parità di seed il risultato è identico, quindi una variante che piace si
riproduce con `--seed`. Il seed è sempre visibile nella barra di stato.

Sul percorso LLM la varietà arriva anche dall'alto: temperatura più alta e un
numero di variante nel prompt, così il modello stesso propone soluzioni diverse
a parità di richiesta. Le modifiche invece restano a temperatura bassa: devono
essere precise, non creative.

## Libreria di asset

![libreria](output/gui_libreria.png)

Ogni asset è una cartella autosufficiente:

```
library/<id>/
    asset.json     metadati + il piano di generazione
    model.glb      la mesh già cotta, per Blender, Unity, Unreal, web
    preview.png    anteprima per la griglia
```

La scelta che conta è **conservare il piano oltre alla mesh**: ricaricando un asset
non ottieni un blocco morto ma un modello ancora parametrico. Puoi continuare a
modificarlo a voce ("fai le ruote più grandi") e generarne altre varianti, e le tue
richieste originali restano protette — un fuoristrada salvato come rosso resta rosso
in ogni variante futura.

I tag nascono da soli: dal piano, dai materiali, dalle parole del prompt e dai
sinonimi che ogni template già dichiara. Per questo cercando **"albero"** trovi un
asset salvato come **"pino"**, e cercando "arma" trovi la spada. La ricerca pesa di
più le parole che hai scritto tu rispetto ai sinonimi, così chi ha davvero detto
"palma" viene prima di tutti gli altri alberi.

Il filesystem è la fonte di verità: se cancelli una cartella a mano o un
`asset.json` si corrompe, l'elenco continua a funzionare saltando quell'asset.

## Perché non è un "text-to-3D"

Le due roadmap di partenza proponevano di fondare il progetto su un modello
text-to-3D (Shap-E in locale). Su una GTX 1660 Ti da 6 GB quella strada produce
blob a bassa risoluzione: un'app che "funziona" ma non serve. Anche `bpy` come
modulo pip non è installabile su Python 3.13.

Qui l'AI fa il **progettista**, non il modellatore: sceglie il generatore giusto e
ne compila i parametri. La geometria la costruiscono algoritmi deterministici.
Risultato: una Jeep riconoscibile in 0,1 s di calcolo locale invece di 3 minuti di
inferenza per una forma indistinta.

La generazione AI di mesh resta prevista, ma come **livello aggiuntivo** per le parti
che il procedurale non copre (vedi *Prossimi passi*), non come fondamenta.

## Il contratto AI → geometria

L'LLM non scrive mai codice e non inventa campi. Riceve il catalogo dei template con
i parametri ammessi e deve restituire solo questo:

```json
{
  "object_type": "jeep militare",
  "template": "vehicle",
  "style": "realistic",
  "params": { "body_style": "offroad", "wheel_radius": 0.46, "has_roof": false },
  "materials": [ { "name": "body", "base_color": "#4a5533", "roughness": 0.75 } ]
}
```

Il JSON viene validato con Pydantic, i parametri sconosciuti scartati e quelli fuori
scala riportati nei limiti dichiarati dal template. Le modifiche seguono la stessa
regola: comandi strutturati (`set_param`, `scale_param`, `set_material`), mai codice.

## Provider AI e costi

Il piano JSON è piccolo (~400 token): i piani gratuiti bastano ampiamente.
I provider vengono provati **in cascata**, il primo che risponde vince:

```
Groq > Gemini > Mistral > OpenRouter > Cohere > HuggingFace > Ollama > regole locali
```

Se uno è a limite di frequenza, senza credito o irraggiungibile, si passa al
successivo senza che l'utente se ne accorga. L'ordine si cambia in `.env` con
`GEN3D_LLM_CHAIN`. `ollama` gira in locale, senza rete e senza chiavi.

Copia `.env.example` in `.env` e inserisci le chiavi. **Le chiavi vere non vanno mai
in `.env.example`**: non è ignorato da git.

### Antivirus con scansione HTTPS

Avast, Kaspersky, ESET e simili sostituiscono i certificati TLS con una propria root
CA. I browser la accettano, Python no, e ogni chiamata API fallisce con
`CERTIFICATE_VERIFY_FAILED`. Il progetto usa `truststore` per far leggere a Python lo
store certificati di Windows: la verifica resta attiva, semplicemente usa le CA che
il sistema già considera valide.

## Struttura

```
app/
  core/       config e registro provider, spec (contratto dati), scene graph,
              sessione con cronologia, logging
  ai/         provider LLM con failover, prompt di sistema, planner, editor,
              varianti, planner a regole (offline)
  geometry/   primitive (trimesh + ear clipping proprio) e template parametrici
  build/      da piano a scena, validazione, export
  anim/       scheletro dal grafo delle parti, animazioni rigide, glTF animato
  assets/     libreria di asset e ricerca per significato
  materials/  texture procedurali e finiture
  ui/         viewport OpenGL, finestra, worker asincroni, renderer offscreen
packaging/    build PyInstaller e script Inno Setup
tests/        692 test: geometria, template sotto stress, planner, varianti,
              composizione, validazione, animazione, distribuzione, benchmark
```

Punti fermi dell'architettura:

- **UI, AI e geometria non si conoscono.** La UI parla solo con `Session`.
- **Il backend geometrico è sostituibile.** Oggi è trimesh (`app/geometry/primitives.py`
  + `app/build/builder.py`); per passare a Blender basta reimplementare quelle due
  superfici, senza toccare AI né UI.
- **Niente blocca l'interfaccia.** Rete e geometria girano in `QThread`.
- **Un componente che fallisce non affonda la scena**: viene saltato e registrato
  nei warning, il resto del modello si genera lo stesso.

## Test

I test di geometria costruiscono ogni template con **tutti i parametri al minimo e al
massimo**, in tutti e quattro gli stili, e verificano che le mesh restino chiuse.
È così che è emerso il caso reale delle ruote raddoppiate: i passaruota sfondavano la
fiancata e il profilo si auto-intersecava. Ora la linea di cintura si alza da sola e
gli archi sono vincolati a non toccarsi né uscire dal corpo.

Sulle varianti i test verificano tre cose: che venticinque seed diversi diano tutti
mesh chiuse e parametri dentro i limiti, che una richiesta esplicita sopravviva a
dodici generazioni, e che il profilo di variazione non nomini parametri che non
esistono più — così non può restare indietro quando un template cambia.

## Distribuzione

```bash
python packaging/build.py --check     # dice cosa manca
python packaging/build.py             # dist/3DGen/ + 3DGen-windows.zip
```

Produce una cartella eseguibile (432 MB) e uno zip (183 MB). **Non** produce
l'installer `.exe`: per quello serve Inno Setup, che non è installato qui; lo script
`packaging/3dgen.iss` è pronto e `build.py` lo usa da solo appena `iscc` c'è.

Una volta installato, output, libreria e progetti vanno in `%LOCALAPPDATA%\3DGen`:
la cartella del programma non è scrivibile e non deve esserlo.

## Prossimi passi

La roadmap è chiusa: venti fasi, cinque banchi di prova verdi. Quello che resta è
scritto in **[TODO.md](TODO.md)** sotto **Debito tecnico noto** e **Escluso di
proposito** — la prima lista dice cosa si sa di poter migliorare, la seconda cosa è
stato deciso di non fare e perché, per non rimettere in discussione decisioni già
prese.
