"""La copertura: quali parti la libreria sa gia' fare, e con quanta certezza.

E' il motore di §9-§12 della milestone, e tre vincoli lo definiscono prima di
qualunque dettaglio.

**1. Non c'e' un secondo motore di ricerca.** I candidati arrivano dal
`SemanticIndex` di V1 attraverso `ComponentIndex.search` — lo stesso oggetto che
la `Session` usa per la rosa del planner — piu' i fornitori di una capability
letti dal `Registry`. Nessun indice nuovo, nessun corpus nuovo, nessun punteggio
calcolato qui dentro (regola 10 di `PROJECT-INDEX`).

**2. La copertura non e' una soglia su un punteggio.** §11 lo chiede
esplicitamente, e la ragione e' che un punteggio di retrieval misura la
somiglianza di due **documenti di testo**: dice che `humanoid:leg` assomiglia
alla parola «leg», non che una gamba umanoide sia una gamba di drago. Quindi
ogni candidato porta **evidenze nominate**, e l'insieme dei nomi — non la loro
somma — decide lo stato. Il punteggio partecipa: ordina i candidati fra loro ed
e' una delle evidenze, la piu' debole.

**3. Nessuna parola di dominio.** Qui non compare «drago», «occhio», «zampa» o
qualunque altro soggetto o parte: le evidenze si leggono dai dati dichiarati
(ruolo, tag, capability, parametri, frame, stili) e dalle parole che **il
concetto porta con se'**. Un test fa il grep.

## Le tre famiglie di evidenza, e i quattro stati

    identita'   `prior_validation`, `role`, `name`
                «questo pezzo **e'** la parte richiesta»
    contesto    `family`, `capability`, `subject`
                «questo pezzo appartiene a **questo** oggetto»
    somiglianza `retrieval` sopra la soglia dell'indice
                «qualcosa nei due testi si somiglia»

        CANDIDATE   identita' **e** contesto
        PROXY       identita' senza contesto, oppure contesto con somiglianza
        MISSING     ne' l'una ne' l'altro
        VALIDATED   mai da un'evidenza: solo da una soluzione confermata

Le due righe centrali sono la risposta alla domanda che §10 pone con due
esempi. Un occhio umanoide su una testa di drago ha identita' (`name: eye`) **e**
contesto (`capability: face_mount`, che la testa scelta accetta davvero):
e' un occhio, ed e' montabile li' — `CANDIDATE`, da verificare. Una gamba
umanoide per una zampa di drago ha identita' (`role: leg`) e **nessun**
contesto: niente la lega a questo soggetto — `PROXY`, un'approssimazione
consapevole. E una cosa che sta nel socket giusto ma non e' la parte richiesta
(contesto senza identita') e' un proxy soltanto se almeno i testi si
somigliano; altrimenti «ci sta» non e' una ragione, e il nodo e' `MISSING`.

## L'ordine di calcolo e' dall'alto in basso, e non e' un dettaglio

L'evidenza `capability` di un figlio guarda che cosa il **padre** accetta.
Quindi i padri si calcolano prima dei figli (`TeachNode.walk()` lo garantisce),
e il «padre» e' la sua soluzione se c'e', altrimenti i suoi candidati. Un nodo
la cui copertura dipendesse da quella dei figli richiederebbe due passate: non
e' il caso, e la ragione e' che la domanda «questo pezzo ci sta?» si fa verso
l'alto.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from app.core.frame import FRAME_COMPATIBLE, compare
from app.core.planner.retrieval import THRESHOLD
from app.teach.model import (CANDIDATE, COVERAGE, MISSING, PROXY, VALIDATED,
                             Candidate, Evidence, TeachNode, TeachProject, slug)

# --------------------------------------------------------------------------- #
# I nomi delle evidenze
# --------------------------------------------------------------------------- #
PRIOR_VALIDATION = "prior_validation"
ROLE = "role"
NAME = "name"
SUBJECT = "subject"
CAPABILITY = "capability"
FAMILY = "family"
CHILDREN = "children"
PARAMS = "params"
SEMANTIC_ROLES = "semantic_roles"
VARIABILITY = "variability"
STYLE = "style"
FRAME = "frame"
RETRIEVAL = "retrieval"

IDENTITY = (PRIOR_VALIDATION, ROLE, NAME)
CONTEXT = (FAMILY, CAPABILITY, SUBJECT)

# I pesi ordinano i candidati fra loro; non decidono lo stato. Sono qui e non
# sparsi nel codice perche' un peso nascosto in una funzione e' un numero che
# nessuno rivede.
WEIGHTS = {
    PRIOR_VALIDATION: 6.0, ROLE: 4.0, NAME: 3.0, SUBJECT: 2.0,
    CAPABILITY: 1.5, FAMILY: 1.5, CHILDREN: 1.0, PARAMS: 0.4,
    SEMANTIC_ROLES: 0.3, VARIABILITY: 0.3, STYLE: 0.2, FRAME: 0.2,
}

MAX_CANDIDATES = 6        # quanti se ne mostrano per nodo
PER_QUERY = 6             # quanti ne porta ciascuna interrogazione
POOL_PER_CAPABILITY = 6   # quanti fornitori per una capability che il padre accetta
_RANK = {CANDIDATE: 0, PROXY: 1, MISSING: 2}


@dataclass
class CoverageReport:
    """Che cosa e' cambiato in un ricalcolo. Si legge, non si indovina."""

    changed: dict = field(default_factory=dict)      # node -> (prima, dopo)
    candidates: dict = field(default_factory=dict)   # node -> quanti
    rejected: dict = field(default_factory=dict)     # node -> quanti scartati
    dropped: tuple = ()                              # soluzioni non piu' installate
    seconds: float = 0.0

    @property
    def any_change(self) -> bool:
        return bool(self.changed)

    def describe(self) -> str:
        righe = ["copertura ricalcolata in %.1f ms" % (self.seconds * 1000.0)]
        for node, (before, after) in sorted(self.changed.items()):
            righe.append("  %s: %s -> %s" % (node, before, after))
        for ref in self.dropped:
            righe.append("  soluzione non piu' installata: %s" % ref)
        return "\n".join(righe)


# --------------------------------------------------------------------------- #
# Le parole di un nodo
# --------------------------------------------------------------------------- #
def _words(text: str) -> frozenset[str]:
    return frozenset(w for w in slug(text, "").split("_") if w)


def variants(word: str) -> tuple[str, ...]:
    """La parola, e la sua forma senza il plurale inglese piu' ovvio.

    Sta qui e non nel retrieval di proposito: `TODO` dichiara da V1 che la
    ricerca non fa stemming, e la correzione vera e' un embedder che lo faccia
    o un ponte dichiarato in un manifest (regola 11). Questo e' soltanto
    **un'interrogazione in piu'** dal lato della domanda, dove interrogazioni
    multiple sono gia' la norma (`query_groups`): «wings» non trova niente,
    «wing» trova `fantasy:wing`, e chiedere entrambe non cambia il motore.
    """
    base = slug(word, "")
    if not base:
        return ()
    out = [base]
    for suffix, cut in (("ies", 3), ("es", 2), ("s", 1)):
        if base.endswith(suffix) and len(base) > cut + 2:
            stem = base[:-cut] + ("y" if suffix == "ies" else "")
            if stem and stem not in out:
                out.append(stem)
            break
    return tuple(out)


def part_queries(project: TeachProject, node: TeachNode) -> list[str]:
    """Le interrogazioni che parlano **della parte**: nome, ruolo, descrizione.

    Sono quelle che possono valere come somiglianza, e la distinzione non e'
    pedanteria: misurata, e' la differenza fra una copertura leggibile e una in
    cui tutto e' blu. Cercare «dragon horn» trova `creature:dragon_head` con un
    punteggio alto — perche' la parola «dragon» pesa in entrambi i documenti —
    e una testa di drago non e' un corno. Se quel punteggio contasse come
    somiglianza, **ogni** parte di un drago avrebbe la testa di drago come
    proxy, e nessun nodo risulterebbe mai `MISSING`.

    Quindi la somiglianza si misura solo su cio' che nomina la parte, e
    l'interrogazione col nome del concetto resta per **trovare** i candidati e
    per ordinarli (`node_queries`).
    """
    del project
    out: list[str] = []
    for word in (node.name, node.role):
        for form in variants(word):
            if form not in out:
                out.append(form)
    description = " ".join(str(node.description or "").split())[:160]
    if description:
        out.append(description)
    return out


def node_queries(project: TeachProject, node: TeachNode) -> list[str]:
    """Tutte le interrogazioni con cui si cercano i candidati di un nodo.

    Quelle della parte (`part_queries`) piu' il concetto insieme al nome. Sono
    interrogazioni **diverse** sullo stesso indice, come `shortlist` ne fa piu'
    di una per un prompt: l'unione dei risultati, con il punteggio massimo per
    componente.
    """
    out = part_queries(project, node)
    combined = ("%s %s" % (project.concept, node.name)).strip()
    if combined and combined not in out:
        out.append(combined)
    return out


# --------------------------------------------------------------------------- #
# Le evidenze di un candidato
# --------------------------------------------------------------------------- #
def component_words(registry, component) -> frozenset[str]:
    """Le parole che un componente **dichiara**: tag, ruolo, id, plugin.

    La descrizione non entra: e' testo libero, e la userebbe per dire di
    appartenere a qualunque cosa. I tag sono dati tassonomici, e sono il posto
    in cui un plugin dichiara a che famiglia appartiene un pezzo.
    """
    out = set()
    for tag in component.tags:
        out.add(str(tag).lower())
        out |= _words(str(tag))
    out |= _words(component.role)
    out |= _words(component.name)
    info = registry.plugin(component.plugin)
    if info is not None:
        out |= _words(info.name or "")
        for tag in info.tags:
            out.add(str(tag).lower())
            out |= _words(str(tag))
    out |= _words(component.plugin)
    return frozenset(w for w in out if w)


def family_words(project: TeachProject, node: TeachNode) -> frozenset[str]:
    """Le parole del **contesto**, cioe' del concetto e degli antenati.

    Non quelle del nodo: se ci fossero, `family` direbbe la stessa cosa di
    `name` e la distinzione fra `CANDIDATE` e `PROXY` collasserebbe. Quello che
    questa evidenza chiede e' «questo pezzo nomina l'oggetto di cui stiamo
    parlando», non «nomina la parte».
    """
    words = set(project.concept_words())
    prefix = node.id
    for other in project.nodes():
        if prefix.startswith(other.id + ".") and other.id != node.id:
            words |= _words(other.name) | _words(other.role)
    return frozenset(words - _words(node.name) - _words(node.role))


def _hosts(project: TeachProject, node: TeachNode,
           registry) -> tuple[frozenset[str], str]:
    """Le capability che il padre di questo nodo accetta, e chi lo dice.

    La soluzione del padre se c'e' (una risposta certa), altrimenti
    l'unione dei suoi candidati (una risposta possibile). Per la radice non
    c'e' padre: il contesto di una radice e' `subject`, non `capability`.
    """
    parent = project.parent_of(node.id)
    if parent is None:
        return frozenset(), ""
    state = project.state(parent.id)
    if state.solution is not None and state.solution.ref:
        refs = [state.solution.ref]
    else:
        refs = [c.component_id for c in state.candidates]
    caps: set[str] = set()
    for ref in refs:
        component = registry.component(ref)
        if component is None:
            continue
        caps |= {m.capability for m in component.mounts if m.capability}
    return frozenset(caps), ", ".join(refs[:3])


def _match_node(component):
    class _Node:
        __slots__ = ("component", "tags")

        def __init__(self) -> None:
            self.component = component
            self.tags = frozenset()

    return _Node()


def _variability(registry, component, style: str) -> int:
    """Quanti trait installati accettano questo componente.

    Riusa `TraitResolver._matches`, come fa `ComponentLab.traits()`: un secondo
    giudizio di compatibilita' qui vorrebbe dire promettere una variabilita'
    che poi non si applica.
    """
    from app.core.traits import TraitResolver

    found = set()
    probe = _match_node(component)
    for rule in registry.trait_rules():
        if rule.trait in found:
            continue
        if TraitResolver._matches(rule.match, probe, style):
            found.add(rule.trait)
    return len(found)


def _children_fit(registry, component, project: TeachProject,
                  node: TeachNode) -> tuple[int, int]:
    """Quanti figli mandatory del nodo potrebbero stare su questo componente.

    Per ogni figlio si cerca un componente installato che **sia** quel figlio
    (stesso `role`, o il nome fra i tag) e si guarda se fornisce una capability
    che il candidato accetta. E' una domanda sulla libreria, non sul figlio:
    non serve che la copertura del figlio sia stata calcolata, e infatti a
    questo punto non lo e'.
    """
    wanted = [c for c in node.children if c.mandatory and project.relevant(c)]
    if not wanted:
        return 0, 0
    accepted = {m.capability for m in component.mounts if m.capability}
    if not accepted:
        return 0, len(wanted)
    fit = 0
    for child in wanted:
        role = slug(child.role, "")
        names = set(variants(child.name))
        for other in registry.components():
            if other.id == component.id:
                continue
            same = (role and slug(other.role, "") == role) or bool(
                names & {str(t).lower() for t in other.tags})
            if not same:
                continue
            if accepted & {c.name for c in other.provides}:
                fit += 1
                break
    return fit, len(wanted)


def evidence_for(project: TeachProject, node: TeachNode, component, *,
                 registry, score: float, hosts: frozenset[str],
                 host_names: str, subjects: frozenset[str], knowledge=None,
                 style: str = "low_poly",
                 part_score: float | None = None) -> tuple[Evidence, ...]:
    """Tutte le evidenze di un candidato, nominate. Nessuna somma, nessuna soglia."""
    out: list[Evidence] = []

    record = None
    if knowledge is not None:
        record = knowledge.record_for(component.id, role=node.role, name=node.name)
    if record is not None:
        out.append(Evidence(PRIOR_VALIDATION, record.describe(),
                            WEIGHTS[PRIOR_VALIDATION]))

    node_role = slug(node.role, "")
    if node_role and slug(component.role, "") == node_role:
        out.append(Evidence(ROLE, "role %r dichiarato" % component.role,
                            WEIGHTS[ROLE]))

    declared = component_words(registry, component)
    own = set()
    for word in (node.name, node.role):
        own |= set(variants(word))
    hit = sorted(own & declared)
    if hit:
        out.append(Evidence(NAME, "nome/tag: %s" % ", ".join(hit), WEIGHTS[NAME]))

    if node is project.root or project.parent_of(node.id) is None:
        provided = {c.name for c in component.provides}
        shared = sorted(provided & subjects)
        if shared:
            out.append(Evidence(SUBJECT, "soggetto intero: %s" % ", ".join(shared),
                                WEIGHTS[SUBJECT]))

    provided = {c.name for c in component.provides}
    usable = sorted(provided & hosts)
    if usable:
        out.append(Evidence(CAPABILITY,
                            "%s, che %s accetta" % (", ".join(usable), host_names),
                            WEIGHTS[CAPABILITY]))

    family = sorted(family_words(project, node) & declared)
    if family:
        out.append(Evidence(FAMILY, "parole del concetto: %s" % ", ".join(family),
                            WEIGHTS[FAMILY]))

    fit, wanted = _children_fit(registry, component, project, node)
    if fit:
        out.append(Evidence(CHILDREN, "puo' ospitare %d figli su %d" % (fit, wanted),
                            WEIGHTS[CHILDREN]))

    free = [s for s in component.params.values() if not s.derived]
    if free:
        out.append(Evidence(PARAMS, "%d parametri pubblici" % len(free),
                            WEIGHTS[PARAMS]))
    roles = sorted({getattr(s, "semantic_role", "") for s in component.params.values()
                    if getattr(s, "semantic_role", "")})
    if roles:
        out.append(Evidence(SEMANTIC_ROLES, ", ".join(roles),
                            WEIGHTS[SEMANTIC_ROLES]))
    traits = _variability(registry, component, style)
    if traits:
        out.append(Evidence(VARIABILITY, "%d trait installati lo raggiungono"
                            % traits, WEIGHTS[VARIABILITY]))

    if component.supports_style(style):
        out.append(Evidence(STYLE, "compatibile con %s" % style, WEIGHTS[STYLE]))

    parent = project.parent_of(node.id)
    if parent is not None:
        parent_state = project.state(parent.id)
        parent_ref = ""
        if parent_state.solution is not None:
            parent_ref = parent_state.solution.ref
        elif parent_state.candidates:
            parent_ref = parent_state.candidates[0].component_id
        parent_component = registry.component(parent_ref) if parent_ref else None
        if parent_component is not None:
            outcome = compare(parent_component.frame, component.frame)
            if outcome.result == FRAME_COMPATIBLE:
                out.append(Evidence(FRAME, outcome.describe(), WEIGHTS[FRAME]))

    # La somiglianza si misura sulle interrogazioni **della parte**: vedi
    # `part_queries` per il perche'. Il punteggio complessivo resta quello che
    # ordina i candidati fra loro.
    measured = score if part_score is None else part_score
    if measured >= THRESHOLD:
        out.append(Evidence(RETRIEVAL, "punteggio %.3f sulla parte" % measured,
                            float(score)))
    return tuple(out)


def verdict_for(evidence) -> str:
    """Lo stato che **questo** candidato da solo giustifica.

    Mai `VALIDATED`: una soluzione confermata non e' un candidato, e nessuna
    quantita' di evidenza equivale a una conferma (§14).
    """
    kinds = {e.kind for e in evidence}
    identity = bool(kinds & set(IDENTITY))
    context = bool(kinds & set(CONTEXT))
    similar = RETRIEVAL in kinds
    if identity and context:
        return CANDIDATE
    if identity or (context and similar):
        return PROXY
    return MISSING


def reason_for(candidate: Candidate) -> str:
    """Una riga che dice perche' quel candidato e' in quello stato."""
    kinds = candidate.kinds
    identity = sorted(kinds & set(IDENTITY))
    context = sorted(kinds & set(CONTEXT))
    if candidate.verdict == CANDIDATE:
        return ("e' la parte richiesta (%s) e appartiene a questo contesto (%s): "
                "da verificare nel contesto" % (", ".join(identity),
                                                ", ".join(context)))
    if candidate.verdict == PROXY and identity and not context:
        return ("e' la parte richiesta (%s) ma niente la lega a questo oggetto: "
                "approssimazione consapevole" % ", ".join(identity))
    if candidate.verdict == PROXY:
        return ("sta in questo contesto (%s) e i testi si somigliano, ma non "
                "dichiara di essere questa parte" % ", ".join(context))
    return "nessuna evidenza sufficiente"


# --------------------------------------------------------------------------- #
# Il calcolo
# --------------------------------------------------------------------------- #
def candidates_for(project: TeachProject, node: TeachNode, *, registry,
                   index, knowledge=None, style: str = "low_poly",
                   limit: int = MAX_CANDIDATES) -> tuple[list[Candidate], int]:
    """I candidati di un nodo, ordinati, piu' quanti ne sono stati scartati.

    Il `registry` si passa, non si pesca da nessuna parte: era appoggiato sul
    progetto per la durata del calcolo, e un parametro nascosto e' un parametro
    che chi chiama la funzione da fuori - un tool, un banco - non sa di dover
    mettere, e scopre con un `AttributeError`.
    """
    from app.core.archetypes import subject_capabilities

    subjects = subject_capabilities(registry)
    hosts, host_names = _hosts(project, node, registry)
    is_root = project.parent_of(node.id) is None
    scores: dict[str, float] = {}
    part_scores: dict[str, float] = {}
    own = part_queries(project, node)
    for query in node_queries(project, node):
        for cid, score in index.search(query, limit=PER_QUERY):
            if score > scores.get(cid, 0.0):
                scores[cid] = float(score)
            if query in own and score > part_scores.get(cid, 0.0):
                part_scores[cid] = float(score)

    pool = set(scores)
    # I fornitori di cio' che il padre accetta: e' il modo in cui una parte
    # senza nome riconoscibile entra comunque nell'elenco. Si limitano, perche'
    # `face_mount` ha dodici fornitori e dodici candidati non sono un elenco.
    for capability in sorted(hosts):
        # `Registry.providers` restituisce chi la **fornisce** e chi la
        # **accetta**, per buone ragioni sue; qui interessa solo il primo
        # gruppo, perche' la domanda e' «chi puo' stare in quel socket».
        providers = sorted((c for c in registry.providers(capability)
                            if c.provides_capability(capability)),
                           key=lambda c: (-scores.get(c.id, 0.0), c.id))
        pool |= {c.id for c in providers[:POOL_PER_CAPABILITY]}
    if knowledge is not None:
        pool |= {r.component for r in knowledge.records_for(role=node.role,
                                                            name=node.name)}
    state = project.state(node.id)
    if state.solution is not None and state.solution.ref:
        pool.add(state.solution.ref)

    found: list[Candidate] = []
    rejected = 0
    for cid in sorted(pool):
        component = registry.component(cid)
        if component is None:
            continue
        # La radice di un concetto e' un oggetto **intero**, e un pezzo non lo
        # e'. Un candidato per la radice deve quindi fornire una capability che
        # nessuno accetta — cioe' deve essere un soggetto secondo
        # `subject_capabilities()` di V2. Senza questo filtro una testa di
        # drago risulta il miglior candidato per un drago, e il guasto non si
        # ferma li': i figli leggono l'evidenza `capability` da cio' che il
        # padre accetta, quindi una radice sbagliata sposta ogni figlio.
        #
        # E' il debito 13 di `PROJECT-INDEX` — «il retrieval mette le parti
        # davanti agli interi, e `subject_capabilities()` sa gia' riconoscere
        # un soggetto» — chiuso **qui**, dove c'e' un concetto di cui si sa che
        # e' un oggetto intero. Nel vocabolario resta aperto.
        provided = {c.name for c in component.provides}
        if is_root and not (provided & subjects):
            rejected += 1
            continue
        # E un nodo che **non** e' la radice e' una parte, quindi deve potersi
        # montare: un componente che non fornisce nessuna capability non e'
        # montabile da nessuno. `humanoid:body` e' il caso vero — e' la radice
        # del proprio plugin e `provides` e' vuoto — e proporlo come zampa di
        # un drago vorrebbe dire portare chi costruisce fino al composite per
        # poi dirgli li' che non si attacca. Meglio non proporlo.
        if not is_root and not provided:
            rejected += 1
            continue
        evidence = evidence_for(project, node, component, registry=registry,
                                score=scores.get(cid, 0.0), hosts=hosts,
                                host_names=host_names or "il padre",
                                subjects=subjects, knowledge=knowledge,
                                style=style,
                                part_score=part_scores.get(cid, 0.0))
        verdict = verdict_for(evidence)
        if verdict == MISSING:
            rejected += 1
            continue
        candidate = Candidate(component_id=cid, score=scores.get(cid, 0.0),
                              verdict=verdict, evidence=evidence)
        candidate.reason = reason_for(candidate)
        found.append(candidate)
    found.sort(key=lambda c: (_RANK.get(c.verdict, 9), -round(c.weight, 6),
                              -round(c.score, 6), c.component_id))
    return found[:max(1, int(limit))], rejected


def analyse(project: TeachProject, registry, index, *, knowledge=None,
            limit: int = MAX_CANDIDATES) -> CoverageReport:
    """Ricalcola candidati e copertura di tutta la gerarchia. Dall'alto in basso.

    Che cosa **non** sovrascrive, e perche':

        una soluzione confermata     resta `VALIDATED`, e i candidati si
                                     aggiornano comunque: una scelta fatta non
                                     si disfa perche' e' arrivato un plugin
        uno stato bloccato           l'utente ha deciso (§43), e un ricalcolo
                                     che cancella una decisione non e' un
                                     ricalcolo
        una soluzione sparita        decade: se il componente non e' piu'
                                     installato la copertura torna a essere
                                     quella delle evidenze, e il referto lo dice
    """
    inizio = time.perf_counter()
    report = CoverageReport()
    if project.root is None:
        report.seconds = time.perf_counter() - inizio
        return report
    dropped: list[str] = []
    for node in project.root.walk():
        state = project.state(node.id)
        before = state.coverage
        if state.solution is not None and state.solution.ref:
            if registry.component(state.solution.ref) is None:
                dropped.append(state.solution.ref)
                state.solution = None
                state.locked = False
        found, rejected = candidates_for(project, node, registry=registry,
                                         index=index, knowledge=knowledge,
                                         style=project.style, limit=limit)
        state.candidates = tuple(found)
        report.candidates[node.id] = len(found)
        report.rejected[node.id] = rejected
        if state.solution is not None:
            state.coverage = VALIDATED
        elif state.locked:
            pass                         # la decisione dell'utente resta
        else:
            best = state.best
            state.coverage = best.verdict if best is not None else MISSING
        if state.coverage != before:
            report.changed[node.id] = (before, state.coverage)
    report.dropped = tuple(dropped)
    report.seconds = time.perf_counter() - inizio
    return report


def summary(project: TeachProject) -> dict:
    """I numeri di §42, piu' il conteggio dei candidati. Per una barra, o un test."""
    progress = project.progress()
    data = progress.to_dict()
    data["nodes"] = len(project.nodes())
    data["with_candidates"] = sum(1 for n in project.nodes()
                                  if project.state(n.id).candidates)
    data["completion"] = project.completion
    return data


def tree_text(project: TeachProject) -> str:
    """L'albero con i quattro colori, come §40 lo disegna. Per il terminale."""
    marks = {VALIDATED: "GREEN ", CANDIDATE: "YELLOW", PROXY: "BLUE  ",
             MISSING: "RED   "}
    righe = []
    for row in project.tree():
        state = project.state(row["id"])
        solution = ""
        if state.solution is not None:
            solution = "  " + state.solution.ref
        elif state.candidates:
            solution = "  " + state.candidates[0].component_id
        righe.append("%s %s%s%s%s" % (
            marks.get(row["coverage"], "?"), "  " * row["depth"], row["name"],
            "" if row["count"] == 1 else " x%d" % row["count"], solution))
    progress = project.progress()
    righe.append("%.0f%% mandatory (peso), %.0f%% per nodi"
                 % (progress.mandatory_percent, progress.mandatory_node_percent))
    return "\n".join(righe)


def ensure_state(project: TeachProject, node_id: str) -> Any:
    """Lo stato di un nodo che deve esistere. Alza se il nodo non c'e'."""
    project.require_node(node_id)
    return project.state(node_id)


__all__ = ["CANDIDATE", "CAPABILITY", "CHILDREN", "CONTEXT", "COVERAGE",
           "CoverageReport", "FAMILY", "FRAME", "IDENTITY", "MAX_CANDIDATES",
           "MISSING", "NAME", "PARAMS", "PRIOR_VALIDATION", "PROXY",
           "RETRIEVAL", "ROLE", "SEMANTIC_ROLES", "STYLE", "SUBJECT",
           "VALIDATED", "VARIABILITY", "WEIGHTS", "analyse", "candidates_for",
           "component_words", "ensure_state", "evidence_for", "family_words",
           "node_queries", "part_queries", "reason_for", "summary", "tree_text",
           "variants", "verdict_for"]
