"""Dal prompt a una rosa di componenti: lo stadio che manca prima del planner.

Il vocabolario completo cresce con la libreria installata, e il contesto di un
modello no. Con 97 componenti il carico supera gia' il limite del fornitore
primario; con mille non entrerebbe da nessuna parte. Qui si sceglie **che cosa
mostrare**, non che cosa costruire: il planner continua a scegliere, ma fra i
pezzi che hanno a che fare con la richiesta.

Il motore di ricerca non e' nuovo. E' lo stesso di `app/assets/semantic.py`,
che indicizza gli asset salvati: TF-IDF locale, embedder remoto opzionale,
persistenza e fingerprint. Qui cambia solo il **corpus** — componenti invece di
asset — e il documento che li descrive.

## Il documento di un componente e' gia' scritto nella libreria

Nessuna conoscenza di dominio entra nel core. Il testo cercabile si ricava solo
da cio' che il componente **dichiara**: id, nome, descrizione, tag, ruolo,
capability fornite, capability accettate, plugin, stili. Se una volpe si trova
cercando "animale" e' perche' qualcuno ha scritto `animal` fra i suoi tag, non
perche' il core sappia che cos'e' una volpe.

## Perche' la rosa non e' solo "i primi N"

Una richiesta come «un pesce con corpo umanoide» nomina due famiglie. Prendere
i primi N risultati di una sola interrogazione darebbe solo la piu' forte, e il
planner non potrebbe comporre cio' che non vede. Quindi si interroga una volta
per la frase intera e una volta per ogni parola che conta, e si **alterna** fra
le liste: nessun gruppo riempie la rosa da solo.

Alla rosa si aggiunge poi la sua **chiusura**: per ogni capability che un
componente scelto accetta, chi la fornisce entra anche se la richiesta non lo
nominava. E' cio' che rende la composizione possibile — una testa non si attacca
a un corpo che il planner non ha davanti.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Sequence

from app.assets.semantic import THESAURUS, Corpus, SemanticIndex, TfidfEmbedder, tokenize
from app.core.logging_setup import get

log = get("core.planner.retrieval")

INDEX_FILE = ".component-index.json"

# Quanti componenti mostrare al planner. Non e' un limite di qualita': e' il
# budget di contesto, ed e' l'unico numero che separa una libreria da mille
# pezzi da un carico che nessun fornitore accetta.
SHORTLIST = 28
PER_GROUP = 8             # quanti ne prende ogni interrogazione prima di alternare
PER_PLUGIN = 10           # quanti ne puo' mettere un solo plugin
CLOSURE = 10              # quanti pezzi si aggiungono per rendere componibile la rosa
PER_CAPABILITY = 2        # quanti fornitori per ogni capability accettata
THRESHOLD = 0.02          # sotto questo punteggio non e' una somiglianza, e' rumore
MAX_GROUPS = 8            # oltre questo una frase non e' una richiesta, e' un tema

# Quando non si trova niente, mostrare tutto e' la risposta onesta: e' cio' che
# il planner vedeva prima di V1, e nascondere la libreria a chi non ha avuto un
# riscontro sarebbe peggio che mostrargliela. Ma «tutto» ha un limite: oltre
# questa soglia nessun fornitore accetterebbe il carico, e si manda una fetta
# dichiarata invece di una richiesta che fallisce.
#
# DEBITO: la risposta giusta a «non ho trovato niente» non e' una fetta, e' la
# degradazione semantica — risalire da 'jeep' a 'vehicle'. E' V2.
FALLBACK_MAX = 120


@dataclass(frozen=True)
class ComponentDoc:
    """Un componente come lo vede l'indice: un id, un testo, una versione.

    Lo `stamp` e' l'identita' versionata: cambia se cambia il plugin, se cambia
    la sua versione o se cambia una qualunque parte semanticamente rilevante del
    componente. E' cio' che fa ricostruire l'indice da solo.
    """

    id: str
    document: str
    stamp: str


@dataclass
class Hit:
    """Un componente trovato, con il perche'."""

    id: str
    score: float
    group: str = ""           # l'interrogazione che lo ha portato
    reason: str = "query"     # "query" oppure "closure:<capability>"

    def to_dict(self) -> dict:
        return {"id": self.id, "score": round(self.score, 4),
                "group": self.group, "reason": self.reason}


@dataclass
class Shortlist:
    """La rosa, e la traccia di come e' stata scelta."""

    components: tuple[Any, ...] = ()
    hits: tuple[Hit, ...] = ()
    groups: tuple[str, ...] = ()
    seconds: float = 0.0
    total: int = 0                 # quanti componenti esistevano
    fallback: str = ""             # se vuota, perche'

    @property
    def ids(self) -> list[str]:
        return [c.id for c in self.components]

    def to_dict(self) -> dict:
        return {"ids": self.ids, "groups": list(self.groups),
                "hits": [h.to_dict() for h in self.hits],
                "seconds": round(self.seconds, 4),
                "total": self.total, "selected": len(self.components),
                "fallback": self.fallback}

    def __len__(self) -> int:
        return len(self.components)


# --------------------------------------------------------------------------- #
# Il documento di un componente
# --------------------------------------------------------------------------- #
def _words(value: str) -> str:
    """`fox_stylized:tail_tip` diventa parole cercabili, non un identificatore."""
    return str(value or "").replace(":", " ").replace("_", " ").replace("-", " ")


def document_for(component, registry=None) -> str:
    """Il testo cercabile di un componente: solo cio' che dichiara.

    L'id e il nome pesano doppio, come il nome di un asset nell'altro corpus:
    chi cerca "volpe" sta quasi sempre cercando il pezzo che si chiama cosi'.
    """
    nome = component.id.partition(":")[2]
    pezzi = [_words(nome), _words(nome), _words(component.id),
             str(component.description or ""),
             str(component.role or ""), _words(component.role or ""),
             " ".join(sorted(component.tags)),
             " ".join(sorted(_words(t) for t in component.tags)),
             " ".join(sorted(c.name for c in component.provides)),
             " ".join(sorted(_words(c.name) for c in component.provides)),
             " ".join(sorted(m.capability for m in component.mounts)),
             " ".join(sorted(_words(m.capability) for m in component.mounts)),
             " ".join(sorted(t for m in component.mounts for t in m.tags)),
             component.plugin, _words(component.plugin),
             " ".join(sorted(component.styles))]
    if registry is not None:
        info = registry.plugin(component.plugin)
        if info is not None:
            # il plugin e' il contesto dichiarato del componente: il suo nome e
            # i suoi tag descrivono il pezzo quanto i tag del pezzo stesso
            pezzi.append(str(info.name or ""))
            pezzi.append(" ".join(sorted(info.tags)))
    return " ".join(p for p in pezzi if p)


def stamp_for(component, registry=None) -> str:
    """Identita' versionata. Se cambia una virgola del documento, cambia."""
    versione = ""
    contenuto = ""
    if registry is not None:
        info = registry.plugin(component.plugin)
        versione = getattr(info, "version", "") if info is not None else ""
        contenuto = getattr(info, "fingerprint", "") if info is not None else ""
    impronta = hashlib.sha1(
        document_for(component, registry).encode("utf-8")).hexdigest()[:12]
    return "%s@%s#%s%s" % (component.id, versione, impronta,
                            ":" + contenuto if contenuto else "")


COMPONENTS = Corpus(name="components",
                    document=lambda doc: doc.document,
                    stamp=lambda doc: doc.stamp,
                    key=lambda doc: doc.id)


def documents(registry) -> list[ComponentDoc]:
    """Il corpus: un documento per componente installato, in ordine stabile."""
    return [ComponentDoc(id=c.id, document=document_for(c, registry),
                         stamp=stamp_for(c, registry))
            for c in sorted(registry.components(), key=lambda c: c.id)]


def registry_signature(registry) -> str:
    """I plugin installati e le loro versioni.

    Serve accanto al fingerprint dei componenti: un plugin che porta solo trait
    non cambia nessun documento, ma cambia il vocabolario. Due controlli
    separati perche' sono due cose diverse, non per prudenza.
    """
    return "|".join("%s@%s%s" % (p.id, p.version,
                                "#" + p.fingerprint if p.fingerprint else "")
                    for p in sorted(registry.plugins(), key=lambda p: p.id))


# --------------------------------------------------------------------------- #
# L'indice
# --------------------------------------------------------------------------- #
@dataclass
class ComponentIndex:
    """L'indice dei componenti installati, con la sua ragione di esistere.

    Tiene insieme l'indice semantico e la firma del registry da cui proviene:
    `is_current` risponde a entrambe le domande, perche' un indice giusto sul
    corpus sbagliato e' un indice sbagliato.
    """

    index: SemanticIndex
    signature: str = ""
    docs: tuple[ComponentDoc, ...] = ()

    def is_current(self, registry) -> bool:
        if self.signature != registry_signature(registry):
            return False
        return self.index.is_current(documents(registry))

    def search(self, query: str, limit: int = 10,
               threshold: float = THRESHOLD) -> list[tuple[str, float]]:
        return self.index.search(query, limit=limit, threshold=threshold)


def thesaurus_for(registry) -> dict[str, tuple[str, ...]]:
    """I ponti predefiniti piu' quelli dichiarati dai plugin installati.

    Il dizionario di base vive in `app/assets/semantic.py` ed e' li' da prima:
    non viene toccato, e chi non passa niente continua a vedere quello. Cio' che
    un plugin dichiara nel proprio manifest si somma — sapere che una jeep e'
    un'automobile e' conoscenza della libreria, non del core.
    """
    fuori = {k: tuple(v) for k, v in THESAURUS.items()}
    for parola, equivalenti in registry.synonyms().items():
        fuori[parola] = tuple(sorted(set(fuori.get(parola, ())) | set(equivalenti)))
    return fuori


def build_index(registry, embedder=None, path=None) -> ComponentIndex:
    """Costruisce l'indice. Da disco se e' ancora valido, altrimenti da capo."""
    docs = documents(registry)
    firma = registry_signature(registry)

    if path is not None:
        cached = SemanticIndex.load(path, embedder, corpus=COMPONENTS)
        if cached is not None and cached.is_current(docs):
            return ComponentIndex(index=cached, signature=firma, docs=tuple(docs))

    if embedder is None:
        embedder = TfidfEmbedder(thesaurus=thesaurus_for(registry))
    index = SemanticIndex(embedder=embedder, corpus=COMPONENTS)
    index.build(docs)
    if path is not None:
        index.save(path)
    return ComponentIndex(index=index, signature=firma, docs=tuple(docs))


# --------------------------------------------------------------------------- #
# La rosa
# --------------------------------------------------------------------------- #
def query_groups(prompt: str, limit: int = MAX_GROUPS) -> list[str]:
    """La frase intera, poi le parole che contano. In quest'ordine, sempre.

    La frase intera per prima perche' e' l'unica interrogazione che conserva il
    contesto; le parole singole dopo perche' sono l'unico modo di non perdere
    la seconda famiglia nominata da una richiesta.
    """
    testo = str(prompt or "").strip()
    if not testo:
        return []
    gruppi = [testo]
    visti: set[str] = set()
    for parola in tokenize(testo):
        if parola in visti:
            continue
        visti.add(parola)
        gruppi.append(parola)
        if len(gruppi) >= limit:
            break
    return gruppi


def _alterna(liste: Sequence[Sequence[Hit]]) -> list[Hit]:
    """Un giro per lista, finche' ce n'e'. Deterministico, e senza pesi.

    Alternare invece di ordinare per punteggio e' la scelta che tiene insieme
    due famiglie: il primo `humanoid` entra prima del quinto `fish`, anche se
    vale meno.
    """
    fuori: list[Hit] = []
    profondita = max((len(l) for l in liste), default=0)
    for i in range(profondita):
        for lista in liste:
            if i < len(lista):
                fuori.append(lista[i])
    return fuori


def _chiusura(scelti: list, registry, style: str, presi: set[str],
              budget: int = CLOSURE) -> list[Hit]:
    """Chi fornisce cio' che gli scelti accettano. Senza, la rosa non si compone."""
    aggiunti: list[Hit] = []
    capacita: list[str] = []
    for componente in scelti:
        for mount in componente.mounts:
            if mount.capability and mount.capability not in capacita:
                capacita.append(mount.capability)

    for capability in capacita:
        if len(aggiunti) >= budget:
            break
        fornitori = [c for c in registry.providers(capability=capability,
                                                   style=style)
                     if c.provides_capability(capability)]
        fornitori.sort(key=lambda c: c.id)
        quanti = 0
        for componente in fornitori:
            if quanti >= PER_CAPABILITY or len(aggiunti) >= budget:
                break
            if componente.id in presi:
                continue
            presi.add(componente.id)
            aggiunti.append(Hit(id=componente.id, score=0.0,
                                reason="closure:%s" % capability))
            quanti += 1
    return aggiunti


def _tutto(disponibili, gruppi, totale, inizio, motivo, limit):
    """La risposta a «non ho trovato niente»: la libreria, se ci sta.

    Oltre `FALLBACK_MAX` la libreria non entra in nessun prompt, e allora si
    dichiara la fetta invece di far fallire la richiesta per dimensione. La
    fetta e' in ordine di id: arbitraria, ma ripetibile e detta.
    """
    import time

    ordinati = sorted(disponibili, key=lambda c: c.id)
    if totale > FALLBACK_MAX:
        ordinati = ordinati[:limit]
        motivo = "%s; libreria troppo grande per mostrarla tutta (%d pezzi), "                  "mostrati i primi %d in ordine di id" % (motivo, totale, limit)
    return Shortlist(components=tuple(ordinati), groups=tuple(gruppi),
                     seconds=time.perf_counter() - inizio, total=totale,
                     fallback=motivo)


def shortlist(registry, prompt: str, *, index: ComponentIndex | None = None,
              style: str = "", limit: int = SHORTLIST,
              per_group: int = PER_GROUP, per_plugin: int = PER_PLUGIN,
              closure: int = CLOSURE, embedder=None, path=None) -> Shortlist:
    """La rosa di componenti per una richiesta. Deterministica a parita' di indice."""
    import time

    inizio = time.perf_counter()
    disponibili = [c for c in registry.components() if c.supports_style(style)]
    totale = len(disponibili)
    ammessi = {c.id: c for c in disponibili}

    gruppi = query_groups(prompt)
    if not gruppi:
        # nessuna richiesta, nessuna rosa: chi non chiede niente vede tutto,
        # ed e' il comportamento di prima di V1
        return _tutto(disponibili, (), totale, inizio, "prompt vuoto", limit)

    if index is None:
        index = build_index(registry, embedder=embedder, path=path)

    liste: list[list[Hit]] = []
    for gruppo in gruppi:
        trovati = [Hit(id=cid, score=score, group=gruppo)
                   for cid, score in index.search(gruppo, limit=per_group * 3)
                   if cid in ammessi]
        liste.append(trovati[:per_group])

    presi: set[str] = set()
    per_plugin_count: dict[str, int] = {}
    scelti: list = []
    hits: list[Hit] = []
    rimandati: list[Hit] = []

    for hit in _alterna(liste):
        if hit.id in presi or len(scelti) >= limit:
            continue
        componente = ammessi[hit.id]
        quanti = per_plugin_count.get(componente.plugin, 0)
        if quanti >= per_plugin:
            rimandati.append(hit)       # non scartato: solo dopo gli altri
            continue
        presi.add(hit.id)
        per_plugin_count[componente.plugin] = quanti + 1
        scelti.append(componente)
        hits.append(hit)

    # la quota per plugin limita chi domina, non chi resta solo: se dopo il
    # giro c'e' ancora spazio, i rimandati rientrano nell'ordine in cui erano
    for hit in rimandati:
        if hit.id in presi or len(scelti) >= limit:
            continue
        presi.add(hit.id)
        scelti.append(ammessi[hit.id])
        hits.append(hit)

    if not scelti:
        log.info("nessun componente rilevante per '%s'", prompt[:60])
        return _tutto(disponibili, gruppi, totale, inizio,
                      "nessun risultato sopra la soglia", limit)

    for hit in _chiusura(list(scelti), registry, style, presi, budget=closure):
        componente = ammessi.get(hit.id)
        if componente is None:
            continue
        scelti.append(componente)
        hits.append(hit)

    # L'ordine e' quello della scelta — prima i piu' rilevanti, poi la
    # chiusura — e non l'alfabetico. Un planner che a pari merito prende il
    # primo deve trovarsi davanti l'auto, non il casco: ordinare per id
    # trasformava la rosa in una lotteria sul nome del componente.
    ordinati = scelti
    secondi = time.perf_counter() - inizio
    log.info("rosa: %d/%d componenti in %.1f ms per '%s'",
             len(ordinati), totale, secondi * 1000, prompt[:60])
    return Shortlist(components=tuple(ordinati), hits=tuple(hits),
                     groups=tuple(gruppi), seconds=secondi, total=totale)


def estimate_tokens(text: str) -> int:
    """Stima grossolana, e dichiarata tale: quattro caratteri per token.

    Serve a sapere se un carico sta sotto un limite, non a fatturarlo. Il
    numero vero lo conosce solo il tokenizzatore del fornitore, e cambia da
    fornitore a fornitore.
    """
    return (len(str(text or "")) + 3) // 4
