"""Il composition graph: la descrizione di **cosa** vogliamo costruire.

Non di come. Il graph non sa costruire niente, non sa cosa e' disponibile, non
sa collegare. Sa soltanto dire: questo componente, con questi parametri, appeso
a quest'altro, piu' questa sostituzione e questi effetti.

    graph      COSA vogliamo
    registry   COSA e' disponibile          (passo 3)
    resolver   COME collegare le due cose   (passo 4)
    builder    COME costruire la geometria  (passo 6)

Mescolare questi ruoli e' il modo piu' rapido di ottenere un sistema che
funziona solo per i casi gia' visti.

## Un solo tipo di nodo

`CompositionNode`, e basta. Un torso, una ruota, un pianeta, un piercing sono
tutti la stessa cosa: un riferimento a un componente piu' come sta appeso. Non
esistono `DecorationNode` o `AnimalNode`, e non devono esistere.

## Tre operazioni, tenute distinte

    add_child   aggiunge una parte **strutturale**: e' cio' che l'oggetto e'
    attach      aggiunge un componente **senza sostituire**: cio' che porta
    swap        **sostituisce** cio' da cui un nodo viene costruito

Confonderle in una sola API sembra elegante e non lo e': "aggiungi una maschera
alla testa" e "sostituisci la testa con una di drago" sono intenzioni diverse, e
il grafo deve poterle raccontare separatamente — anche a chi legge una diagnosi.

## La sostituzione non e' distruttiva — ma non raddoppia niente

Uno swap si **registra**, non riscrive il nodo. Il grafo iniziale resta
leggibile: si vede che l'intenzione era "un umanoide" e che la testa e' stata
scambiata. `resolved_ref()` dice da cosa un nodo verra' effettivamente
costruito; `ref` dice da cosa doveva essere costruito. Servono entrambe, per il
debug e per la correzione di un piano.

Detto questo, la tracciabilita' vive **solo nel piano**. Un nodo ha un solo
provider effettivo, sempre:

    piano        Humanoid.Head  +  swap -> Dragon.Head     due informazioni
    risolto      Dragon.Head                               un componente
    geometria    una testa                                 una mesh

`Humanoid.Head` e `Dragon.Head` non esistono mai insieme come geometria: il
componente originale, dopo lo swap, non viene piu' costruito ne' interrogato
per i socket. Uno swap **non aggiunge un nodo** — `len(graph)` non cambia — e
`providers()` restituisce esattamente una voce per nodo. Quello che sopravvive
del componente di partenza e' il suo nome in `node.ref` e la coppia `from`/`to`
nel registro delle operazioni: materiale per chi legge una diagnosi, non per
chi costruisce.

Chi vuole *entrambe* le teste non fa uno swap: aggiunge un secondo nodo con
`attach`. Sono due intenzioni diverse, e restano due chiamate diverse.

## Ricorsione si', ciclo no

Ripetere un componente e' legittimo — un ramo che porta un ramo che porta una
foglia — a patto che **qualcosa cambi**: parametri diversi, livello che scende,
budget che si consuma. Ripetere lo stesso componente con gli stessi parametri
non e' ricorsione, e' un ciclo travestito, e non finirebbe mai.

## Due identita' per nodo, e non sono la stessa cosa

    planner node id        `node.id`          chi scrive il piano
    stable node identity   `identity(id)`     il sistema

L'**id del piano** e' un nome libero: lo scrive un modello linguistico o una
persona, serve a indirizzare (`on`, `swap`, `target`, le diagnosi) e vale solo
dentro quel piano. `car`, `jeep`, `jeep1`, `fantasy_tree_01` sono tutti id
legittimi per la stessa cosa, e questo e' voluto: obbligare il planner a
indovinare un nome preciso vorrebbe dire legare il significato a una stringa.

Per questo un id del piano **non puo' essere l'identita' semantica di un nodo**.
Una riscrittura strutturale che riconosce "lo stesso braccio", un clone che non
deve rompere i riferimenti, una futura modifica incrementale che preserva "la
stessa testa": tutte hanno bisogno di qualcosa che il planner non possa
scegliere.

`identity(id)` e' quel qualcosa, e viene **derivata** invece di essere scritta:

    sha1( identita' del padre | ref | firma dell'attacco | ordinale )

La firma dell'attacco e' `own_socket` piu' il requisito (capability, socket,
lato, tag ordinati); l'ordinale conta i fratelli con la stessa coppia
(ref, firma) nell'ordine di inserimento. La radice deriva dal solo `ref`.

Conseguenze, che sono i requisiti:

* la genera il sistema, non il modello: e' una funzione pura, non un campo che
  qualcuno possa riempire;
* sopravvive a serialization e deserialization perche' si **ricalcola** — un
  `.my3d` scritto prima di questa versione la ottiene senza cambiare formato;
* non cambia quando cambiano parametri o effetti: non entrano nel calcolo;
* usa `ref`, non `resolved_ref`, quindi uno `swap` **non** la cambia: e' lo
  stesso nodo costruito da un altro componente;
* non cambia se si rinomina l'id del piano;
* due cloni strutturali hanno identita' diverse, perche' hanno ordinali diversi.

Limite dichiarato: cancellare un fratello con la stessa firma sposta gli
ordinali di quelli che lo seguivano. Finche' non esiste una strada che cancella
nodi (la modifica incrementale), e' un confine noto, non un difetto nascosto.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha1
from typing import Any, Iterator

from app.core.component import Attachment
from app.core.errors import Report
from app.core.socket import DEFAULT_INSERT

# --------------------------------------------------------------------------- #
# Provenienza di un valore
# --------------------------------------------------------------------------- #
# Non un sistema di ereditarieta': solo la memoria di **da dove viene** un
# numero. Serve piu' avanti agli effetti, per non applicare due volte cio' che
# qualcuno ha gia' deciso — il difetto che aveva sfasciato il "chibi".
FROM_DEFAULT = "default"      # valore predefinito del componente
FROM_DERIVED = "derived"      # calcolato da un'espressione
FROM_OVERRIDE = "override"    # deciso nel piano, da utente o LLM
FROM_EFFECT = "effect"        # modificato da un effetto
FROM_TRAIT = "trait"          # modificato da un Trait semantico

SEPARATOR = "/"


class GraphError(ValueError):
    """Un uso dell'API che non ha senso. Gli errori del **piano** non sollevano:
    finiscono in un `Report`."""


@dataclass
class EffectRequest:
    """Un effetto chiesto dal piano.

    Il graph non lo interpreta: lo registra. Che cosa significhi `lanky`, quali
    intervalli abbia e in che ordine si applichi lo decide il sistema degli
    effetti (passo 5). Qui e' solo un'intenzione dichiarata.
    """

    type: str
    scope: str = "model"                 # model | group:tag | part:id | subtree:id | role:x
    params: dict[str, Any] = field(default_factory=dict)
    amount: float = 1.0

    def describe(self) -> str:
        return "%s su %s (%.2f)" % (self.type, self.scope, self.amount)


@dataclass
class Operation:
    """Una modifica al piano, registrata.

    Tracciare le operazioni costa una riga e serve due volte: a spiegare a
    qualcuno perche' il modello e' venuto cosi', e a far correggere un piano
    senza doverlo ricostruire da zero.
    """

    kind: str                            # add_child | attach | swap | override | effect
    target: str
    detail: dict[str, Any] = field(default_factory=dict)

    def describe(self) -> str:
        extra = " ".join("%s=%s" % kv for kv in sorted(self.detail.items()))
        return "%s %s%s" % (self.kind, self.target, " " + extra if extra else "")


@dataclass
class CompositionNode:
    """Un nodo: un componente, come sta appeso, e cosa gli e' stato cambiato."""

    id: str
    ref: str                                       # "plugin:componente"
    attachment: Attachment | None = None           # None per la radice
    overrides: dict[str, Any] = field(default_factory=dict)
    effects: list[EffectRequest] = field(default_factory=list)
    tags: frozenset[str] = field(default_factory=frozenset)
    requested: bool = False                        # chiesto esplicitamente

    def __post_init__(self) -> None:
        self.tags = frozenset(self.tags)

    @property
    def plugin(self) -> str:
        return self.ref.partition(":")[0]

    def describe(self) -> str:
        return "%s <- %s%s" % (self.id, self.ref,
                               " (chiesto)" if self.requested else "")


# --------------------------------------------------------------------------- #
# Il grafo
# --------------------------------------------------------------------------- #
@dataclass
class CompositionGraph:
    """Cosa vogliamo costruire, in forma dichiarativa e indirizzabile."""

    style: str = "low_poly"
    detail_level: int = 2
    seed: int = 0
    version: str = "1.0"

    root_id: str = ""
    nodes: dict[str, CompositionNode] = field(default_factory=dict)
    parents: dict[str, str] = field(default_factory=dict)
    order: dict[str, list[str]] = field(default_factory=dict)   # figli, ordinati
    swaps: dict[str, str] = field(default_factory=dict)         # nodo -> nuovo ref
    operations: list[Operation] = field(default_factory=list)
    traits: list[Any] = field(default_factory=list)
    structural_traits: list[Any] = field(default_factory=list)
    graph_rewrite_plan: Any = None
    layout_plan: Any = None
    structural_resolution: Any = None
    concept_resolution: Any = None
    # Da dove vengono i nodi nati da una riscrittura strutturale. Solo
    # diagnostica: si esporta, si rilegge, e una voce che non corrisponde a
    # nessun nodo vero viene buttata invece di essere creduta.
    structural_provenance: list[dict[str, Any]] = field(default_factory=list)

    # ------------------------------------------------------------ costruzione #
    def set_root(self, id: str, ref: str, **params) -> CompositionNode:
        if self.root_id:
            raise GraphError("la radice e' gia' '%s'" % self.root_id)
        nodo = self._new(id, ref, None, params)
        self.root_id = id
        self.operations.append(Operation("add_child", id, {"ref": ref, "root": True}))
        return nodo

    def add_child(self, id: str, ref: str, parent: str = "", *,
                  requirement=None, own_socket: str = "base", level: int = 2,
                  scale_mode: str = "none", insert: float = 0.35, roll: float = 0.0,
                  **params) -> CompositionNode:
        """Una parte **strutturale**: cio' di cui l'oggetto e' fatto."""
        attacco = Attachment(id=id, component=ref, requirement=requirement,
                             own_socket=own_socket, level=level,
                             scale_mode=scale_mode, insert=insert, roll=roll)
        nodo = self._link(id, ref, parent, attacco, params)
        self.operations.append(Operation("add_child", self.path(id), {"ref": ref}))
        return nodo

    def attach(self, id: str, ref: str, to: str = "", *, requirement=None,
               own_socket: str = "base", on_request: bool = True,
               optional: bool = True, level: int = 2, scale_mode: str = "socket",
               insert: float = 0.35, roll: float = 0.0, on: str = "",
               **params) -> CompositionNode:
        """Un componente **aggiunto**, che non sostituisce niente.

        E' quello che altrove si chiamerebbe "decorazione". Qui non ha un tipo
        proprio: e' un componente con un attacco facoltativo e su richiesta.
        `scale_mode="socket"` perche' cio' che si applica a qualcosa quasi
        sempre viene da un altro vocabolario e deve adattarsi all'innesto.

        `on` indirizza una parte che **non e' nel piano**: `on="testa/naso"`
        vuol dire il naso che la testa dichiara per conto proprio. Il piano non
        deve rimetterlo — rimetterlo vorrebbe dire sostituirlo, e riscriverne i
        parametri a mano. Nel grafo il nodo resta appeso al contenitore piu'
        profondo che il percorso nomina e che esiste gia'; e' il resolver, che
        vede anche le parti dichiarate, a spostarlo sul bersaglio vero.
        """
        attacco = Attachment(id=id, component=ref, requirement=requirement,
                             own_socket=own_socket, level=level,
                             optional=optional, on_request=on_request,
                             scale_mode=scale_mode, insert=insert, roll=roll,
                             on=on)
        nodo = self._link(id, ref, to or (self._ancora(on) if on else ""),
                          attacco, params)
        nodo.requested = on_request
        self.operations.append(Operation(
            "attach", self.path(id),
            {"ref": ref, "on_request": on_request, **({"on": on} if on else {})}))
        return nodo

    def swap(self, target: str, ref: str, *, scale_mode: str = "none",
             **params) -> CompositionNode:
        """**Sostituisce** cio' da cui un nodo viene costruito.

        Non riscrive il nodo: registra la sostituzione. Il piano resta leggibile
        e `ref` continua a dire quale era l'intenzione di partenza.

        `scale_mode` predefinito `"none"`, al contrario di `attach`. Un pezzo
        che **sostituisce** un altro porta misure gia' sensate: una spada al
        posto di una gamba e' lunga quanto una spada. Portarla al raggio
        dell'innesto la scalerebbe finche' la sua sezione non riempie l'anca —
        che per un pezzo lungo e sottile vuol dire moltiplicarne la lunghezza
        per sette. Chi vuole l'adattamento lo chiede; chi aggiunge una
        decorazione lo ha gia' per predefinito, perche' li' serve davvero.
        """
        nodo = self.node(target)
        if nodo is None:
            raise GraphError("nessun nodo da sostituire: '%s'" % target)
        self.swaps[nodo.id] = ref
        if nodo.attachment is not None:
            nodo.attachment.scale_mode = scale_mode
            # i parametri del vecchio componente parlano un'altra lingua
            nodo.attachment.params = {}
        nodo.overrides = dict(params) if params else {}
        self.operations.append(Operation("swap", self.path(nodo.id),
                                         {"from": nodo.ref, "to": ref}))
        return nodo

    def override(self, target: str, **params) -> CompositionNode:
        """Cambia un parametro senza cambiare il componente.

        Distinto dallo swap di proposito: `Head.width = 0.5` non e'
        `Head -> DragonHead`, e un piano che confonde le due cose e' un piano
        che non si riesce a correggere.
        """
        nodo = self._require(target)
        nodo.overrides.update(params)
        self.operations.append(Operation("override", self.path(nodo.id), dict(params)))
        return nodo

    def effect(self, type: str, scope: str = "model", target: str = "",
               amount: float = 1.0, **params) -> EffectRequest:
        """Registra un effetto. Il graph non lo interpreta."""
        richiesta = EffectRequest(type=type, scope=scope, params=dict(params),
                                  amount=amount)
        nodo = self._require(target) if target else self._require(self.root_id)
        nodo.effects.append(richiesta)
        self.operations.append(Operation("effect", self.path(nodo.id),
                                         {"type": type, "scope": scope}))
        return richiesta

    # ------------------------------------------------------------- lettura #
    def node(self, key: str) -> CompositionNode | None:
        """Un nodo per id o per percorso. Entrambi sono indirizzi validi."""
        if key in self.nodes:
            return self.nodes[key]
        if SEPARATOR in key:
            return self.nodes.get(key.rsplit(SEPARATOR, 1)[-1]) \
                if self._path_matches(key) else None
        return None

    def path(self, id: str) -> str:
        """Percorso stabile dalla radice: `testa/naso/piercing`."""
        pezzi, corrente = [], id
        visti = set()
        while corrente and corrente not in visti:
            visti.add(corrente)
            pezzi.append(corrente)
            corrente = self.parents.get(corrente, "")
        return SEPARATOR.join(reversed(pezzi))

    def children(self, id: str) -> list[CompositionNode]:
        return [self.nodes[c] for c in self.order.get(id, []) if c in self.nodes]

    def parent(self, id: str) -> CompositionNode | None:
        return self.nodes.get(self.parents.get(id, ""))

    def ancestors(self, id: str) -> list[CompositionNode]:
        """La catena dei contenitori. Regge anche un grafo rotto.

        Deve reggerlo: la validazione la usa proprio mentre sta cercando cio'
        che e' rotto. Un padre che non esiste interrompe la catena, non la fa
        cadere — il difetto viene poi riferito come `PARENT_MISSING`.
        """
        fuori, corrente, visti = [], self.parents.get(id, ""), {id}
        while corrente and corrente not in visti and corrente in self.nodes:
            visti.add(corrente)
            fuori.append(self.nodes[corrente])
            corrente = self.parents.get(corrente, "")
        return fuori

    def resolved_ref(self, id: str) -> str:
        """Da cosa il nodo verra' davvero costruito, sostituzioni comprese.

        **Uno solo.** Il componente sostituito resta scritto in `node.ref` per
        chi legge il piano, ma non viene costruito: la geometria di un nodo
        viene da un provider e basta.
        """
        return self.swaps.get(id, self.nodes[id].ref if id in self.nodes else "")

    # ---------------------------------------------------------- identita' #
    def identity(self, id: str) -> str:
        """L'identita' stabile del nodo: derivata, non scritta da nessuno.

        Vedi la sezione "Due identita' per nodo" in testa al file per il perche'
        e per i limiti. Qui basta sapere che e' una funzione pura della
        struttura: stesso albero, stessa identita', su qualunque macchina e
        dopo qualunque salvataggio.
        """
        if id not in self.nodes:
            return ""
        return self.identities().get(id, "")

    def identities(self) -> dict[str, str]:
        """Tutte le identita' stabili, id del piano -> identita'.

        Si calcola in un passo dalla radice verso le foglie, perche' l'identita'
        di un nodo contiene quella del padre: calcolarle una per volta vorrebbe
        dire risalire la catena ogni volta.
        """
        fuori: dict[str, str] = {}
        if not self.root_id or self.root_id not in self.nodes:
            return fuori
        radice = self.nodes[self.root_id]
        fuori[radice.id] = _digest("", radice.ref, "", 0)
        coda = [radice.id]
        while coda:
            padre = coda.pop(0)
            visti: dict[tuple[str, str], int] = {}
            for figlio in self.children(padre):
                firma = _signature(figlio.attachment)
                chiave = (figlio.ref, firma)
                ordinale = visti.get(chiave, 0)
                visti[chiave] = ordinale + 1
                fuori[figlio.id] = _digest(fuori.get(padre, ""), figlio.ref,
                                           firma, ordinale)
                coda.append(figlio.id)
        return fuori

    def by_identity(self, identity: str) -> CompositionNode | None:
        """Il nodo con quell'identita' stabile, se c'e' ancora.

        E' la domanda che fa una riscrittura — «questo nodo esiste gia'?» — e
        quella che fara' la modifica incrementale: «lo stesso braccio di prima».
        """
        if not identity:
            return None
        for id, valore in self.identities().items():
            if valore == identity:
                return self.nodes.get(id)
        return None

    def providers(self) -> dict[str, str]:
        """Il piano risolto: un nodo, un componente effettivo.

        E' la vista che il builder deve usare. Se qui comparissero due voci per
        lo stesso nodo, verrebbero costruite due mesh dove ne serviva una — il
        motivo per cui `swaps` e' una mappa `nodo -> ref` e non una lista di
        aggiunte.
        """
        return {id: self.resolved_ref(id) for id in self.nodes}

    def swapped(self) -> dict[str, tuple[str, str]]:
        """Le sostituzioni in chiaro: nodo -> (da, a). Solo per la diagnostica."""
        return {id: (self.nodes[id].ref, ref) for id, ref in self.swaps.items()
                if id in self.nodes}

    def walk(self, start: str = "") -> Iterator[CompositionNode]:
        """Visita in profondita', in ordine di inserimento. Deterministica."""
        radice = start or self.root_id
        if not radice or radice not in self.nodes:
            return
        pila = [radice]
        visti: set[str] = set()
        while pila:
            corrente = pila.pop()
            if corrente in visti:
                continue
            visti.add(corrente)
            yield self.nodes[corrente]
            pila.extend(reversed(self.order.get(corrente, [])))

    def subtree(self, id: str) -> list[CompositionNode]:
        return list(self.walk(id))

    def wanted(self, node: CompositionNode) -> bool:
        """Questo nodo compare, con il dettaglio chiesto?

        Un attacco esplicito entra **anche** sotto il livello: chi domanda «una
        testa semplice con un piercing» non vuole che tutto l'albero diventi
        dettagliato per avere il piercing.
        """
        if node.attachment is None:
            return True
        return node.attachment.wanted_at(self.detail_level, node.requested)

    def __len__(self) -> int:
        return len(self.nodes)

    def describe(self) -> str:
        righe = []
        for nodo in self.walk():
            profondita = self.path(nodo.id).count(SEPARATOR)
            marchio = "" if self.resolved_ref(nodo.id) == nodo.ref \
                else "  ->  %s" % self.resolved_ref(nodo.id)
            righe.append("%s%s%s" % ("  " * profondita, nodo.describe(), marchio))
        return "\n".join(righe)

    # ---------------------------------------------------------- validazione #
    def validate(self, report: Report | None = None) -> Report:
        """Validita' **strutturale**. Non compatibilita': quella e' del resolver.

        Qui si risponde a «questo grafo ha senso come grafo?», non a «questi
        pezzi possono stare insieme?». Tenerle separate significa che un errore
        di struttura non viene mascherato da un errore di compatibilita'.
        """
        # `or` non basta: un `Report` vuoto e' falso, e le diagnosi
        # finirebbero in un referto diverso da quello di chi lo ha passato.
        report = report if report is not None else Report()

        if not self.root_id:
            report.add("GRAPH_NO_ROOT", "il piano non ha una radice")
            return report
        if self.root_id not in self.nodes:
            report.add("GRAPH_NO_ROOT", "la radice '%s' non esiste" % self.root_id)
            return report

        for nodo in self.nodes.values():
            if not self.resolved_ref(nodo.id):
                report.add("NODE_NO_REF", "il nodo '%s' non dice cosa costruire"
                           % nodo.id, where=self.path(nodo.id))
            elif ":" not in self.resolved_ref(nodo.id):
                report.warn("REF_NOT_QUALIFIED",
                            "riferimento senza plugin: '%s'" % self.resolved_ref(nodo.id),
                            where=self.path(nodo.id),
                            why="un riferimento qualificato e' 'plugin:componente'")

            padre = self.parents.get(nodo.id)
            if nodo.id != self.root_id:
                if not padre:
                    report.add("NODE_ORPHAN", "'%s' non e' appeso a niente" % nodo.id,
                               where=nodo.id)
                elif padre not in self.nodes:
                    report.add("PARENT_MISSING",
                               "'%s' e' appeso a '%s', che non esiste"
                               % (nodo.id, padre), where=nodo.id,
                               alternatives=sorted(self.nodes)[:6])

        for bersaglio in self.swaps:
            if bersaglio not in self.nodes:
                report.add("SWAP_TARGET_MISSING",
                           "sostituzione su un nodo inesistente: '%s'" % bersaglio,
                           alternatives=sorted(self.nodes)[:6])

        self._check_cycles(report)
        self._check_progress(report)

        raggiungibili = {n.id for n in self.walk()}
        for perso in sorted(set(self.nodes) - raggiungibili):
            report.warn("NODE_UNREACHABLE",
                        "'%s' non e' raggiungibile dalla radice" % perso, where=perso)
        return report

    def _check_cycles(self, report: Report) -> None:
        """Un nodo non puo' essere antenato di se stesso."""
        for id in self.nodes:
            visti, corrente = set(), self.parents.get(id, "")
            while corrente:
                if corrente == id:
                    report.add("GRAPH_CYCLE",
                               "ciclo nella catena dei padri a '%s'" % id, where=id,
                               why="un nodo non puo' contenere se stesso")
                    break
                if corrente in visti:
                    break
                visti.add(corrente)
                corrente = self.parents.get(corrente, "")

    def _check_progress(self, report: Report) -> None:
        """Ricorsione si', ripetizione immobile no.

        Un ramo che contiene un ramo va benissimo, **se qualcosa cambia**: i
        parametri, o il livello. Lo stesso componente con gli stessi parametri
        dentro se stesso non e' ricorsione, e' un ciclo che non si accorge di
        esserlo.
        """
        for nodo in self.nodes.values():
            proprio = self.resolved_ref(nodo.id)
            for antenato in self.ancestors(nodo.id):
                if self.resolved_ref(antenato.id) != proprio:
                    continue
                if antenato.overrides != nodo.overrides:
                    continue                       # qualcosa cambia: e' ricorsione
                report.warn(
                    "RECURSION_WITHOUT_PROGRESS",
                    "'%s' ripete '%s' senza cambiare niente" % (nodo.id, proprio),
                    where=self.path(nodo.id),
                    why="stesso componente e stessi parametri di '%s'" % antenato.id)
                break

    # ---------------------------------------------------------- serializzazione #
    def to_dict(self) -> dict:
        def esporta(nodo: CompositionNode) -> dict:
            fuori: dict[str, Any] = {"id": nodo.id, "ref": nodo.ref}
            if nodo.id in self.swaps:
                fuori["swap"] = self.swaps[nodo.id]
            if nodo.overrides:
                fuori["params"] = dict(nodo.overrides)
            if nodo.effects:
                fuori["effects"] = [{"type": e.type, "scope": e.scope,
                                     "amount": e.amount, **e.params}
                                    for e in nodo.effects]
            attacco = nodo.attachment
            if attacco is not None:
                collegamento: dict[str, Any] = {}
                richiesta = attacco.requirement
                if richiesta is not None and (richiesta.capability or richiesta.socket_id):
                    # I `tags` del requisito escono con gli altri tre campi:
                    # sono cio' che distingue una ruota davanti da una dietro, e
                    # senza di loro un piano riaperto perdeva quella differenza.
                    # Lo schema li dichiarava gia' sotto `at`.
                    collegamento["at"] = {k: v for k, v in
                                          (("socket", richiesta.socket_id),
                                           ("capability", richiesta.capability),
                                           ("side", richiesta.side),
                                           ("tags", sorted(richiesta.tags))) if v}
                if attacco.on:
                    collegamento["on"] = attacco.on
                if attacco.on_request:
                    collegamento["on_request"] = True
                if attacco.optional:
                    collegamento["optional"] = True
                if attacco.scale_mode != "none":
                    collegamento["scale_mode"] = attacco.scale_mode
                if attacco.level != 2:
                    collegamento["level"] = attacco.level
                # `insert` e `roll` sono dichiarabili dal piano e lo schema li
                # accetta: senza riscriverli, un progetto riaperto montava i
                # pezzi a una profondita' diversa da quella chiesta e la
                # geometria cambiava senza che niente lo dicesse. Si scrivono
                # solo quando non sono il valore predefinito, quindi un file
                # salvato prima di questa riga si rilegge come prima.
                if abs(attacco.insert - DEFAULT_INSERT) > 1e-12:
                    collegamento["insert"] = attacco.insert
                if attacco.roll:
                    collegamento["roll"] = attacco.roll
                fuori.update(collegamento)
            figli = [esporta(c) for c in self.children(nodo.id)]
            if figli:
                fuori["children"] = figli
            return fuori

        fuori = {"version": self.version, "style": self.style,
                "detail_level": self.detail_level, "seed": self.seed,
                "root": esporta(self.nodes[self.root_id]) if self.root_id else {}}
        if self.traits:
            fuori["traits"] = [t.__dict__.copy() for t in self.traits]
        if self.structural_traits:
            richieste = []
            for trait in self.structural_traits:
                item = trait.__dict__.copy()
                target = item.get("target")
                if hasattr(target, "key"):
                    item["target"] = {
                        "role": target.role,
                        "capability": target.capability,
                        "tags": list(target.tags),
                        "components": list(target.components),
                    }
                richieste.append(item)
            fuori["structural_traits"] = richieste
        if self.structural_provenance:
            fuori["structural_provenance"] = [dict(v) for v in
                                              self.structural_provenance]
        if self.graph_rewrite_plan is not None:
            fuori["graph_rewrite_plan"] = self.graph_rewrite_plan.to_dict()
        if self.layout_plan is not None:
            fuori["layout_plan"] = self.layout_plan.to_dict()
        if self.concept_resolution is not None:
            fuori["concept_resolution"] = (self.concept_resolution.to_dict()
                                            if hasattr(self.concept_resolution, "to_dict")
                                            else dict(self.concept_resolution))
        return fuori

    @classmethod
    def from_dict(cls, data: dict) -> "CompositionGraph":
        from app.core.capability import Requirement

        grafo = cls(style=data.get("style", "low_poly"),
                    detail_level=int(data.get("detail_level", 2)),
                    seed=int(data.get("seed", 0)),
                    version=str(data.get("version", "1.0")))
        from app.core.traits import trait_requests_from_dict
        from app.core.structural import structural_trait_requests_from_dict
        from app.core.archetypes import ConceptResolutionPlan

        grafo.traits = trait_requests_from_dict(data.get("traits") or [])
        grafo.structural_traits = structural_trait_requests_from_dict(
            data.get("structural_traits") or [])
        grafo.concept_resolution = ConceptResolutionPlan.from_dict(
            data.get("concept_resolution"))

        def importa(voce: dict, padre: str) -> None:
            id, ref = voce["id"], voce.get("ref", "")
            dove = voce.get("at") or {}
            richiesta = Requirement(capability=dove.get("capability", ""),
                                    socket_id=dove.get("socket", ""),
                                    side=dove.get("side", ""),
                                    tags=frozenset(dove.get("tags") or ()))
            params = dict(voce.get("params") or {})
            if not padre:
                grafo.set_root(id, ref, **params)
            elif voce.get("on_request") or voce.get("optional") or voce.get("on"):
                dove = voce.get("on", "")
                grafo.attach(id, ref, "" if dove else padre, requirement=richiesta,
                             on_request=bool(voce.get("on_request", True)),
                             optional=bool(voce.get("optional", True)),
                             level=int(voce.get("level", 2)), on=dove,
                             scale_mode=voce.get("scale_mode", "socket"),
                             insert=float(voce.get("insert", DEFAULT_INSERT)),
                             roll=float(voce.get("roll", 0.0)), **params)
            else:
                grafo.add_child(id, ref, padre, requirement=richiesta,
                                level=int(voce.get("level", 2)),
                                scale_mode=voce.get("scale_mode", "none"),
                                insert=float(voce.get("insert", DEFAULT_INSERT)),
                                roll=float(voce.get("roll", 0.0)), **params)
            if voce.get("swap"):
                grafo.swap(id, voce["swap"])
            for effetto in voce.get("effects") or []:
                extra = {k: v for k, v in effetto.items()
                         if k not in ("type", "scope", "amount")}
                grafo.effect(effetto["type"], effetto.get("scope", "model"),
                             target=id, amount=float(effetto.get("amount", 1.0)),
                             **extra)
            for figlio in voce.get("children") or []:
                importa(figlio, id)

        if data.get("root"):
            importa(data["root"], "")
        grafo.structural_provenance = structural_provenance_from_dict(
            data.get("structural_provenance"), grafo)
        return grafo

    # ------------------------------------------------------------- interno #
    def _new(self, id: str, ref: str, attachment, params: dict) -> CompositionNode:
        if id in self.nodes:
            raise GraphError("id gia' usato: '%s'" % id)
        nodo = CompositionNode(id=id, ref=ref, attachment=attachment,
                               overrides=dict(params or {}))
        self.nodes[id] = nodo
        self.order.setdefault(id, [])
        return nodo

    def _link(self, id: str, ref: str, parent: str,
              attachment, params: dict) -> CompositionNode:
        padre = parent or self.root_id
        if not padre:
            raise GraphError("non c'e' una radice a cui appendere '%s'" % id)
        bersaglio = self.node(padre)
        if bersaglio is None:
            raise GraphError("padre inesistente: '%s'" % padre)
        nodo = self._new(id, ref, attachment, params)
        self.parents[id] = bersaglio.id
        self.order.setdefault(bersaglio.id, []).append(id)
        return nodo

    def _require(self, key: str) -> CompositionNode:
        nodo = self.node(key)
        if nodo is None:
            raise GraphError("nodo inesistente: '%s'" % key)
        return nodo

    def _ancora(self, on: str) -> str:
        """Il nodo del piano piu' profondo che il percorso nomina.

        `"testa/naso"` con solo la testa nel piano da' la testa: il naso non
        c'e' ancora e nascera' dall'espansione della testa. Il grafo non lo
        sa costruire e non deve provarci — gli basta appendere il nodo a
        qualcosa di reale, cosi' resta un grafo valido; lo spostamento sul
        bersaglio definitivo e' del resolver.
        """
        pezzi = [p for p in on.split(SEPARATOR) if p]
        for i in range(len(pezzi), 0, -1):
            nodo = self.node(SEPARATOR.join(pezzi[:i]))
            if nodo is not None:
                return nodo.id
        return self.root_id

    def _path_matches(self, path: str) -> bool:
        pezzi = path.split(SEPARATOR)
        return self.path(pezzi[-1]) == path


# --------------------------------------------------------------------------- #
# Identita' stabile: le due funzioni pure su cui si regge
# --------------------------------------------------------------------------- #
PROVENANCE_KEYS = ("trait", "rule", "component", "prototype", "identity",
                   "clone_index", "clone_count")


def structural_provenance_from_dict(items: Any,
                                    graph: "CompositionGraph" | None = None
                                    ) -> list[dict[str, Any]]:
    """Rilegge la provenienza dei cloni, senza fidarsene.

    E' l'unico pezzo di V3 che arriva da un file e non da un calcolo, quindi si
    tiene soltanto cio' che si puo' ancora verificare: una voce la cui identita'
    non corrisponde a nessun nodo del grafo descrive un nodo che non c'e' piu',
    e tenerla vorrebbe dire spiegare una cosa inesistente. Nessuna voce puo'
    creare, spostare o rinominare niente: e' diagnostica.
    """
    valide = graph.identities().values() if graph is not None else None
    fuori: list[dict[str, Any]] = []
    for voce in items or ():
        if not isinstance(voce, dict):
            continue
        identita = str(voce.get("identity") or "")
        if valide is not None and identita not in valide:
            continue
        pulita: dict[str, Any] = {}
        for chiave in PROVENANCE_KEYS:
            if chiave not in voce:
                continue
            valore = voce[chiave]
            pulita[chiave] = int(valore) if chiave in ("clone_index",
                                                       "clone_count") \
                and isinstance(valore, (int, float)) and not isinstance(valore, bool) \
                else str(valore)
        if pulita:
            fuori.append(pulita)
    return fuori


def _signature(attachment: Attachment | None) -> str:
    """Come un nodo sta appeso, in una stringa.

    Entra nell'identita' perche' distingue due nodi che nominano lo stesso
    componente in due posti diversi — una ruota davanti e una dietro, che
    differiscono per i tag `front`/`rear` del requisito — senza dipendere
    dall'id che qualcuno ha scelto.

    E' il **requisito**, e soltanto quello: capability, socket, lato, tag. Non
    i parametri e non gli effetti, perche' cambiare la larghezza di un braccio
    non lo rende un altro braccio. E non `own_socket`, per una ragione piu'
    prosaica e piu' vincolante: il formato del piano non lo scrive, quindi un
    `own_socket` dentro l'identita' la farebbe cambiare a ogni salva-e-riapri.
    Un'identita' che non sopravvive al round-trip non e' un'identita'.
    """
    if attachment is None:
        return ""
    richiesta = getattr(attachment, "requirement", None)
    if richiesta is None:
        return "|||"
    return "|".join([
        str(getattr(richiesta, "capability", "") or ""),
        str(getattr(richiesta, "socket_id", "") or ""),
        str(getattr(richiesta, "side", "") or ""),
        ",".join(sorted(str(t) for t in getattr(richiesta, "tags", ()) or ())),
    ])


def _digest(parent: str, ref: str, signature: str, ordinal: int) -> str:
    """L'identita' vera e propria. Corta perche' finisce in una diagnosi."""
    grezzo = "\x00".join([parent, str(ref or ""), signature, str(int(ordinal))])
    return sha1(grezzo.encode("utf-8")).hexdigest()[:12]
