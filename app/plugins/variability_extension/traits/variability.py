"""Il vocabolario delle proporzioni relative: sei trait, nessuno specifico.

`body_mass_extension` e `tree_leafiness_extension` dimostravano il meccanismo;
mancava il vocabolario che serve davvero a una richiesta cartoon. Questi sei
trait sono quel vocabolario, e sono **contenuto di libreria**: nessuna riga del
core e' stata scritta per loro, e `TraitRule` li risolve con il meccanismo di
V1.

## Tre generici e tre selettivi, e la differenza non e' estetica

    std:part_scale   scala tutte le misure di cio' che il bersaglio nomina
    std:width        allarga
    std:length       allunga

I tre generici non filtrano per ruolo: colpiscono qualunque nodo l'ambito della
richiesta raggiunga. Si indirizzano con `on` e `scope`, cioe' nominando un
nodo del piano.

    std:head_scale   la stessa scala, ma solo sui nodi che dichiarano ruolo
    std:hand_scale   `head`/`face`, `hand`, oppure gli arti
    std:limb_length

I tre selettivi esistono perche' `on` indirizza un nodo e questa libreria ha
imparato in V3 che indirizzare e' fragile: la testa di un umanoide e' un figlio
**dichiarato dal componente**, non dal piano, quindi il suo id e' un percorso
(`subject/head`) che il planner non ha scritto e non puo' indovinare. Un trait
che seleziona per ruolo non ha questo problema: la richiesta resta
`{"trait": "head_scale", "value": 2.2}`, l'ambito predefinito e' tutto il
sottoalbero, e la regola trova la testa dove sia. E' la stessa lezione dei
trait strutturali, applicata ai trait semantici — selezionare, non indirizzare.

Non sono trenta trait specifici: sono tre ruoli, e sono quelli che una richiesta
cartoon nomina quasi sempre («testa enorme, gambe corte, mani grandi»). Se
domani servisse `std:ear_scale` la risposta e' `part_scale` con un `on`, non un
settimo trait.

## Il bersaglio e' un ruolo semantico di parametro, mai un nome

Ogni patch dichiara `semantic_role`, non `param`: questa libreria chiama
`length` una lunghezza in un plugin e `lung` in un altro, e un trait che
nominasse un parametro funzionerebbe su un componente e non sul successivo.
Chi scrive il componente — in Python **o in JSON** — dichiara che quel numero e'
una larghezza, e il trait parla quel linguaggio. E' per questo che gli stessi
sei trait raggiungono un componente procedurale e una mesh importata senza
sapere quale dei due stanno toccando: non c'e' nessun `if mesh_backed`, e non
puo' essercene uno, perche' il trait non vede il backend geometrico.

## I ruoli semantici che questi trait conoscono

    length      una lunghezza, lungo l'asse di crescita
    girth       uno spessore, nella sezione
    width       una larghezza dichiarata come tale
    height      un'altezza dichiarata come tale
    scale       un fattore di scala complessivo

`length` e `girth` sono quelli che i 97 componenti installati dichiarano gia'
(104 parametri `girth`, 63 `length`). `width`, `height` e `scale` sono per chi
li dichiara — tipicamente un componente dati, dove una scala per asse *e'* il
parametro. Nessuno di questi nomi sta nel core: sono stringhe che i componenti
scrivono e che i trait cercano, e la convenzione vive qui e in `PLUGIN-AUTORI`.

## Perche' un moltiplicatore e non un delta

Perche' «due volte piu' grande» e' una frase che ha senso su una testa alta 24
centimetri e su una casa alta sei metri, mentre «piu' venti centimetri» ne ha
senso su una sola delle due. Il valore del trait e' un fattore: 1.0 e' «come
l'autore l'ha fatto», e il `ParamSpec` del parametro continua a decidere il
tetto — un trait puo' spingere, non sfondare.
"""
from app.core.params import RATIO, ParamSpec
from app.core.traits import ParamPatch, TraitMatch, TraitRule, TraitSpec

# I ruoli semantici che una scala complessiva deve toccare, in ordine stabile.
MISURE = ("length", "girth", "width", "height", "scale")

# Le larghezze: una `width` dichiarata come tale, e `girth`, che in questa
# libreria *e'* la misura della sezione. Sono due ruoli diversi e due regole
# diverse, perche' un componente puo' dichiarare l'uno, l'altro o entrambi.
LARGHEZZE = ("width", "girth")

# I ruoli dei componenti su cui i tre trait selettivi lavorano. Stanno qui e
# non nel core: sono nomi che i plugin installati hanno scelto.
TESTE = ("head", "face")
MANI = ("hand",)
ARTI = ("arm", "leg", "limb", "foot")


def _scala(trait: str, prefix: str, roles: tuple[str, ...] = (),
           measures: tuple[str, ...] = MISURE) -> tuple[TraitRule, ...]:
    """Una regola per ogni misura: moltiplica il valore per il fattore chiesto.

    Una regola per misura e non una sola con cinque patch, cosi' la diagnostica
    di conflitto (`TRAIT_RULE_CONFLICT`) nomina la misura in questione invece
    di un'unica regola che tocca tutto.
    """
    return tuple(
        TraitRule(id="%s_%s" % (prefix, measure), trait=trait,
                  match=TraitMatch(roles=roles, param_roles=(measure,)),
                  patches=(ParamPatch(semantic_role=measure,
                                      expression="value * trait"),),
                  description="scala il ruolo semantico '%s'" % measure)
        for measure in measures)


FATTORE = ParamSpec(1.0, RATIO, min=0.15, max=4.0,
                    description="fattore di scala: 1.0 e' la misura dichiarata "
                                "dall'autore del componente")


# --------------------------------------------------------------------------- #
# I tre generici
# --------------------------------------------------------------------------- #
PART_SCALE = TraitSpec(
    id="std:part_scale",
    aliases=("part_scale", "scale", "size"),
    description="how big the addressed part is, relative to how it was authored",
    purpose="scale every declared measure of the part the request addresses",
    value=FATTORE, scopes=("local", "subtree"), operations=("set", "add"),
    owner="std", version="1.0.0",
)

WIDTH = TraitSpec(
    id="std:width",
    aliases=("width", "wide", "largo"),
    description="how wide the addressed part is, relative to how it was authored",
    purpose="scale the cross-section measures of the part the request addresses",
    value=FATTORE, scopes=("local", "subtree"), operations=("set", "add"),
    owner="std", version="1.0.0",
)

LENGTH = TraitSpec(
    id="std:length",
    aliases=("length", "long", "lungo"),
    description="how long the addressed part is, relative to how it was authored",
    purpose="scale the length measures of the part the request addresses",
    value=FATTORE, scopes=("local", "subtree"), operations=("set", "add"),
    owner="std", version="1.0.0",
)

PART_SCALE_RULES = _scala("std:part_scale", "part_scale")
WIDTH_RULES = _scala("std:width", "width", measures=LARGHEZZE)
LENGTH_RULES = _scala("std:length", "length", measures=("length",))


# --------------------------------------------------------------------------- #
# I tre selettivi: stesse regole, un ruolo davanti
# --------------------------------------------------------------------------- #
HEAD_SCALE = TraitSpec(
    id="std:head_scale",
    aliases=("head_scale", "head_size"),
    description="how big the head is relative to the rest of the subject",
    purpose="scale the parts that declare a head or face role, wherever they are",
    value=FATTORE, scopes=("local", "subtree"), operations=("set", "add"),
    owner="std", version="1.0.0",
)

HAND_SCALE = TraitSpec(
    id="std:hand_scale",
    aliases=("hand_scale", "hand_size"),
    description="how big the hands are relative to the rest of the subject",
    purpose="scale the parts that declare a hand role, wherever they are",
    value=FATTORE, scopes=("local", "subtree"), operations=("set", "add"),
    owner="std", version="1.0.0",
)

LIMB_LENGTH = TraitSpec(
    id="std:limb_length",
    aliases=("limb_length", "leg_length", "arm_length"),
    description="how long the limbs are relative to the rest of the subject",
    purpose="scale the length of the parts that declare a limb role, "
            "including every segment of a chained limb",
    value=FATTORE, scopes=("local", "subtree"), operations=("set", "add"),
    owner="std", version="1.0.0",
)

HEAD_SCALE_RULES = _scala("std:head_scale", "head_scale", roles=TESTE)
HAND_SCALE_RULES = _scala("std:hand_scale", "hand_scale", roles=MANI)
LIMB_LENGTH_RULES = _scala("std:limb_length", "limb_length", roles=ARTI,
                           measures=("length",))
