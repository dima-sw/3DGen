# Scrivere un plugin per 3DGen

Il minimo che serve per aggiungere un vocabolario di forme. Non c'è un SDK da
installare e non serve leggere il core: un plugin è una cartella con un
manifest e dei file Python che dichiarano dei componenti.

Il core non saprà mai che cosa hai costruito. Saprà che il tuo componente
**fornisce** certe capability e ne **accetta** altre, e questo gli basta per
metterlo insieme a componenti che non hai scritto tu.

---

## 1. La cartella

```
mio_plugin/
    plugin.json
    components/
        forme.py
```

`plugin.json`:

```json
{
  "id": "mio_plugin",
  "version": "1.0.0",
  "name": "Il mio plugin",
  "description": "Che cosa porta, in una riga.",
  "author": "…", "license": "MIT",
  "tags": ["qualcosa"],

  "components": ["components/forme.py"],
  "effects": [], "styles": [],

  "capabilities": [
    { "name": "una_capability_mia", "description": "che cosa vuol dire" }
  ],
  "dependencies": [],
  "metadata": {}
}
```

`components`, `effects` e `styles` sono **file**, non elenchi di nomi: il
manifest dice dove guardare, non cosa c'è dentro. Aggiungere un componente non
ti obbliga a tenere allineate due descrizioni.

Poi:

```python
registry.load_directory("percorso/della/cartella/che/contiene/i/plugin")
```

Se il tuo plugin è rotto, viene scartato con una diagnosi e gli altri si
caricano lo stesso.

---

## 1-bis. Chi garantisce cosa

Questa è la divisione che rende possibile tutto il resto, e conviene averla
chiara prima di scrivere una riga.

| il **core** garantisce | il **plugin** decide |
|---|---|
| i contratti (`Component`, `Attachment`, `Socket`, `Capability`) | la geometria |
| la composizione e la ricorsione | i parametri e i loro intervalli |
| la risoluzione degli innesti | i vincoli |
| il quadro della validazione | la topologia e il livello di dettaglio |
| gli effetti e il loro ordine | i materiali |
| il ciclo di vita del build | con quali stili è compatibile |

**La qualità di un componente appartiene al plugin.** Il core non sa cosa sia
una testa fatta bene: sa misurare ciò che il tuo componente **dichiara** —
`requires={"watertight"}` viene controllato, `faces_per_normal` viene misurato
se lo stile lo chiede, un giunto viene misurato se hai dichiarato un innesto.
Ciò che non dichiari non viene né preteso né garantito.

La conseguenza pratica: `humanoid_lowpoly` e `humanoid_realistic` possono
convivere, fornire la stessa capability ed essere scelti dallo stile chiesto,
senza che il core cambi di una riga.

---

## 2. Un componente

Un modulo dichiara i suoi oggetti a livello di modulo. Nessuna funzione
`register()`, nessun decoratore: il registry raccoglie quello che trova.

```python
from app.core.authoring import base_socket
from app.core.capability import Capability, mount
from app.core.component import Component, Piece
from app.core.params import DISTANCE, RATIO, ParamSpec
from app.core.socket import socket
from app.geometry.kernel import grow


def _costruisci(v, ctx) -> Piece:
    lunghezza, raggio = v["length"], v["radius"]
    mesh = grow([(0.0, raggio), (0.6, raggio * 1.1), (1.0, raggio * 0.4)],
                sides=6, length=lunghezza, axis=0)
    return Piece(mesh=mesh, material="metal", tags=("cosa",), sockets={
        "base": base_socket(raggio, axis="+X"),
        "punta": socket("punta", (lunghezza, 0, 0), (1, 0, 0), up=(0, 1, 0),
                        radius=raggio * 0.4, provides="anchor"),
    })


COSA = Component(
    id="cosa",                       # diventa "mio_plugin:cosa"
    build=_costruisci,
    description="una cosa affusolata",
    params={"length": ParamSpec(0.5, DISTANCE, min=0.01, max=5.0,
                                semantic_role="length"),
            "radius": ParamSpec(0.06, DISTANCE, min=0.005, max=1.0,
                                semantic_role="girth")},
    provides=(Capability("limb_mount"),),           # che cosa **è**
    mounts=(mount("anchor", socket_id="punta"),),   # che cosa **accetta**
    role="cosa", material="metal", tags=frozenset({"mio"}))
```

Scrivi l'`id` nudo: il registry lo qualifica in `mio_plugin:cosa`. Scrivere
l'id di un altro plugin è rifiutato.

---

## 3. Le sei cose da dichiarare

### `params` — che cosa si può regolare

```python
ParamSpec(default, DISTANCE, min=…, max=…, semantic_role="length",
          derived="root.height * 0.3", description="…")
```

- Il valore finisce **sempre** dentro `min..max`: chi usa il componente non può
  portarlo fuori, nemmeno con un effetto.
- `semantic_role` (`length`, `girth`) è come gli effetti ti trovano. Un effetto
  che allunga cerca i parametri dichiarati lunghezze, **non** quelli che si
  chiamano `length`: se il tuo si chiama `blade_length`, dichiaralo e funziona.
- `derived` è un'espressione con `self`, `parent`, `root`: aritmetica sicura,
  niente codice. Serve a far scalare le misure con chi ti contiene.

### `provides` — che cosa il componente **è**

Le capability che sa soddisfare. Una testa di drago fornisce `head_mount`: non
perché sia una testa, ma perché può stare dove ne va una.

### `mounts` — che cosa il componente **accetta**

```python
mount("limb_mount", socket_id="spalla_l", side="l", tags=("alto",),
      capacity=1, allow_fallback=False)
```

È una dichiarazione a freddo, e il registry la indicizza senza costruire
niente. Ma **deve dire la verità**: il builder confronta ogni `socket_id`
dichiarato con i socket che `build` produce davvero, e riferisce se manca.

- `capacity`: 1 = uno solo, N = al massimo N, 0 = quanti se ne vuole.
- `allow_fallback`: se accetti anche chi non ti soddisfa del tutto. Per
  difetto no — vedi il §6.

### `sockets` — dove esattamente

Solo `build` li può creare: hanno posizione, verso e raggio, che esistono solo
quando esiste la geometria.

### `children` — di che cosa il componente è fatto

```python
def _figli(v, ctx):
    return [Attachment(id="pezzo", component="altro", level=3,
                       replaces_parent=True,
                       requirement=Requirement(capability="segment"),
                       params={"length": v["length"] * 0.5})]
```

- `level`: da quale `detail_level` compare.
- `optional=True, on_request=True`: un accessorio — compare solo se chiesto.
- `replaces_parent=True`: quando compaiono i figli, **la tua geometria non si
  costruisce**. È come un braccio che a un certo livello diventa omero più
  avambraccio, e non deve restare anche il braccio intero sotto.

### `on` — attaccarsi a una parte che dichiara qualcun altro

Un piano può appendere qualcosa a una parte che **non ha nominato**, perché a
nominarla è stato un altro componente:

```json
{ "ref": "accessories:piercing", "on": "testa/naso" }
```

Il naso è un figlio che `humanoid:head` dichiara da sé. Senza `on`, il piano
dovrebbe rimetterlo — e allora sarebbe *il suo* naso a vincere, con tutti i
parametri da riscrivere a mano. Con `on`, il sistema trova il nodo che esiste
già e ci attacca la decorazione: **una sola nose, un solo piercing**, anche a
`detail_level = 1`.

Il percorso apre un corridoio: le parti che nomina vengono costruite anche se il
livello di dettaglio non le prevedeva, e **solo quelle**. Chiedere un piercing
sul naso non fa comparire occhi, bocca e orecchie.

Se il percorso non porta da nessuna parte si ottiene `ON_TARGET_MISSING` con
l'elenco dei percorsi che esistono; se ne trova due, `ON_TARGET_AMBIGUOUS` —
perché due nasi sono due posti diversi, e indovinare vorrebbe dire mettere
l'orecchino su quello sbagliato senza dirlo a nessuno.

### `requires` — che cosa la tua geometria promette

`{"connected"}`, `{"watertight"}`, `{"manifold"}`, `{"no_degenerate"}`,
`{"faceted"}`. **Solo quello che dichiari viene controllato**: una lamina aperta
è aperta apposta, e nessuno ti obbliga a chiuderla. `faceted` dice «la mia
geometria ha legittimamente una normale per faccia» ed esenta dal criterio low
poly: serve a una sfera, non serve a una cassa.

---

## 4. La convenzione, e come verificarla

```
la parte cresce da 0 verso un asse dichiarato   (+X per gli arti, +Y per ciò che sta in piedi)
il socket `base` sta all'origine e guarda **indietro**, verso -asse
ogni altro socket guarda **fuori**: è il verso in cui esce chi si attacca
```

Il figlio si posa in modo che il verso **opposto** al proprio socket coincida
con il `direction` del socket del padre. Se `base` guardasse in avanti, il pezzo
si costruirebbe all'incontrario — e il modello *sembrerebbe* costruito, che è il
modo peggiore di essere sbagliato.

Non fidarti della regola scritta: misurala.

```python
from app.core.authoring import verify_frame, describe_frame

pezzo = COSA.build(resolve(COSA.params), BuildContext())
print(describe_frame(pezzo, "+X"))
print(verify_frame(pezzo, "+X", name="mio_plugin:cosa").describe() or "ok")
```

`verify_frame` guarda la geometria vera e ti dice se cresce dove hai dichiarato,
se la base è all'origine e se ogni socket ha un verso. È un aiuto per te mentre
scrivi: il core non lo chiama mai da solo.

---

## 5. Un effetto

```python
from app.core.vocabulary import (EffectSpec, ParamRule, STAGE_PROPORTION,
                                 SCOPE_MODEL, PRESERVE_SOCKETS)

ALLUNGA = EffectSpec(
    id="allunga", stage=STAGE_PROPORTION, scopes=(SCOPE_MODEL,),
    amount=ParamSpec(0.5, RATIO, min=0.0, max=1.0),
    changes=(ParamRule(semantic_role="length",
                       expression="value * (1 + amount * 0.4)"),),
    conflicts=frozenset({"accorcia"}))
```

Sei stadi, in quest'ordine: `structural`, `proportion`, `local`, `global`,
`style`, `final`. La distinzione che conta è fra il secondo e gli altri: una
**proporzione** cambia *cosa si costruisce*, una **deformazione** cambia *ciò
che è costruito*.

Per una deformazione geometrica dichiara una **mappa di punti**, non una
trasformazione di mesh:

```python
def piega(punti, ctx):
    ...
    return nuovi_punti

BEND = EffectSpec(id="piega", stage=STAGE_LOCAL, scopes=(SCOPE_PART,),
                  deform=piega, socket_policy=PRESERVE_SOCKETS)
```

Con `deform` il builder muove i vertici **e i socket** con la stessa funzione:
la coerenza non è una convenzione da rispettare, è impossibile romperla. Con
`apply(mesh, ctx)` invece te ne occupi tu.

---

### La posa: `rotate`, `align`, `offset`, `mirror`

Sono effetti dello stadio `final` e stanno nel plugin `fx`. Servono a un caso
che nessun plugin può risolvere da solo: due vocabolari compatibili che
producono una posa assurda. Un corpo di pesce ha le pinne pettorali di lato, e
un braccio umano innestato lì esce orizzontale — non è un difetto né del pesce
né del braccio.

```python
g.effect("align", scope="subtree:braccio_l", direction="down")
g.effect("rotate", scope="role:arm", axis="Z", angle=-40)
```

Il builder passa alla deformazione due punti che solo lui può conoscere:
`ctx.pivot`, l'innesto da cui il gruppo pende, e `ctx.reach`, il suo punto più
lontano. Con quelli, «orienta le braccia verso il basso» è una rotazione sola, e
vale per un braccio umano, per una coda o per un'antenna.

Due cose da sapere:

- **l'ambito decide cosa si muove.** `subtree:` prende il gruppo con tutto ciò
  che porta; `role:` prende solo i pezzi che dichiarano quel ruolo, e se una
  mano ne dichiara un altro resta dov'era. Per una posa, `subtree:` è quasi
  sempre la risposta.
- **non c'è cinematica.** Un gruppo si muove rigido: nessun gomito si piega, e
  nessuno tiene conto di dove arriva la mano.

---

## 6. Le cose che il sistema rifiuta, e perché

| diagnosi | vuol dire |
|---|---|
| `COMPONENT_NOT_FOUND` | il riferimento non esiste. Arriva con i nomi più vicini. |
| `AMBIGUOUS_COMPONENT` | un nome nudo che due plugin usano. Qualifica il riferimento. |
| `PROVIDER_INCOMPATIBLE` | il tuo pezzo non **fornisce** ciò che l'innesto **accetta**. |
| `SOCKET_INCOMPATIBLE` | nessun innesto soddisfa il requisito. Un ripiego va **dichiarato**, non dedotto. |
| `DECLARED_SOCKET_MISSING` | hai dichiarato un `socket_id` che `build` non produce. |
| `STYLE_INCOMPATIBLE` | il componente è per un altro stile. Non viene convertito: si cambia pezzo. |
| `MOUNT_CROWDED` | quell'innesto è pieno. Si attacca lo stesso, e si dice. |
| `PART_SUBMERGED` | il pezzo entra dentro chi lo tiene molto più di quanto l'attacco prevedesse. |
| `ON_TARGET_MISSING` | il percorso di un `on` non esiste. Arriva con i percorsi veri. |
| `PARAM_NOT_FOUND` | un piano ha chiesto un parametro che il componente non ha. |
| `EFFECT_PARAM_NOT_FOUND` | idem, per un parametro di un effetto. |

Niente di tutto questo solleva un'eccezione: sono diagnosi, e il modello viene
costruito per quanto si può. Un pezzo che non si attacca è un pezzo mancante con
una spiegazione, non una generazione fallita.

---

## 7. Uno stile

```python
from app.core.vocabulary import StyleProfile

MIO_STILE = StyleProfile(
    id="mio_stile",
    params={"faces_per_normal_min": 1.8, "triangle_budget": 3200,
            "max_submersion": 0.75, "max_overlap": 0.60})
```

I `params` sono liberi: il core garantisce identità e ricerca, il significato
dei numeri appartiene a chi li legge. Un criterio che non dichiari non ti viene
applicato — se il tuo stile non parla di `faces_per_normal`, nessuno misurerà la
planarità dei tuoi quadrilateri.

Uno stile può partire da un altro e cambiargli due numeri:

```python
CARTOON = StyleProfile(id="cartoon", extends="low_poly",
                       params={"faces_per_normal_min": 1.2})
```

La catena si risolve quando si **legge** un valore, non quando si registra il
profilo: il plugin che porta lo stile di partenza può arrivare dopo il tuo, e
l'ordine di caricamento non è garantito. Un `extends` che non trova niente non è
un errore — il tuo profilo vale per i numeri che dichiara.

Un componente può dichiarare `styles={"cartoon"}` per esistere solo lì. Chi non
dichiara niente vale per tutti gli stili: gli stili si dichiarano per
**escluderne** qualcuno, non per essere usabili.

---

## 8. Il giro completo

```python
from app.core.registry import load
from app.core.graph import CompositionGraph
from app.core.capability import Requirement
from app.core.resolver import resolve
from app.core.effect import apply_effects
from app.build.assembler import build
from app.build.validate import validate

registry = load(["app/plugins", "il/mio/percorso"])
registry.freeze()

g = CompositionGraph(detail_level=2)
g.set_root("radice", "mio_plugin:cosa")
g.add_child("pezzo", "altro_plugin:qualcosa", "radice",
            requirement=Requirement(capability="anchor"))
g.effect("lanky", scope="model", amount=0.6)

risultato = build(apply_effects(resolve(g, registry), registry))
validate(risultato, style=registry.style("low_poly"))

print(risultato.describe())
print(risultato.report.describe() or "nessuna diagnosi")
risultato.scene().export("modello.glb")
```

Nessuno dei passaggi sa che cosa sia il tuo componente. È il punto.

---

## 9. Il giro completo, dalla frase

La stessa cosa passando dalla porta unica, con il planner:

```python
from app.core.session import Options, Session

sessione = Session(plugin_paths=("app/plugins", "il/mio/percorso"))
risultato = sessione.generate("una cosa affusolata con un anello in punta")

print(risultato.describe())
print("\n".join(risultato.explain()))      # perché è stato scelto ciò che c'è
risultato.scene().export("modello.glb")
```

`Session.plan(prompt)` si ferma al piano; `Session.build(piano)` costruisce un
piano già pronto — grafo o JSON. Sono lo stesso giro spezzato, non tre strade.

---

## 10. Come il tuo plugin appare al planner

Prima di chiamare il modello, il sistema costruisce un **vocabolario** dal
registry: id, descrizione, `provides`, `accepts`, parametri con intervallo, tag,
effetti, stili. Il tuo codice non ci arriva mai — solo il contratto.

Tre conseguenze pratiche per te:

1. **Il nome e i tag contano più della descrizione.** Sono quello che una
   persona scrive nel prompt. Un componente con `tags={"casa", "edificio"}` si
   trova con «una casa»; uno che lo dice solo nella descrizione, molto meno.
2. **L'intervallo di un parametro è un contratto verso il planner.** Un modello
   sceglie *dentro* `min..max`; se il tuo `min` è irrealistico, il modello
   produrrà piani irrealistici e nessuno saprà perché.
3. **La tua `description` è un dato, e viene trattata come tale.** Prima di
   entrare nel contesto viene ridotta a una riga sola fra virgolette, senza
   delimitatori e senza marcatori di ruolo, e tagliata a 160 caratteri. Non è
   sfiducia verso di te: è che un plugin installato da qualcun altro non deve
   poter dare ordini al planner di chi lo installa. Scrivi una frase breve e
   descrittiva, non istruzioni.

Il piano che il planner produce è **JSON**, e usa solo ciò che il vocabolario
elenca. Non produce geometria, non produce Python, e non inventa componenti: se
il tuo pezzo non è nel registry, per il planner non esiste.
