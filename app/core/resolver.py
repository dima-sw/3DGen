"""Il resolver: come realizzo quello che voglio con quello che esiste.

    registry    cosa esiste
    graph       cosa voglio
    resolver    come realizzo il secondo con il primo      <- questo file
    builder     dove finisce ogni vertice

Il resolver non costruisce mesh, non applica effetti, non parla con nessun
modello linguistico. Decide **quali componenti si usano e come si collegano**,
e lo scrive in un `ResolvedComposition`.

## Provides e mounts non sono la stessa cosa

E' la distinzione su cui gira tutto il collegamento:

    il padre  ACCETTA   `head_mount`      (`Component.mounts`)
    il figlio FORNISCE  `head_mount`      (`Component.provides`)

Si cerca **nel padre** un innesto che soddisfi il requisito dell'attacco, e si
verifica **nel figlio** che sappia riempirlo. Invertire le due parti sembra
indifferente e non lo e': un torso che "fornisce head_mount" vorrebbe dire che
il torso *e'* una testa.

## Cosa il resolver non puo' sapere

Un socket vero ha una posizione, un verso e un raggio, e nasce dentro `build`.
Qui esistono solo le **dichiarazioni** (`Component.mounts`). Quindi il resolver
risponde a *chi si collega a chi*, e lascia al builder *dove esattamente, come,
con che scala*. Dove servisse una coordinata, la risposta giusta e' spostare la
domanda al builder, non inventare un numero.

## Niente magia

Se un componente non esiste, non si inventa: si riferisce, con le alternative
piu' vicine. Se due candidati sono equivalenti, non si tira a sorte: si dice
che sono due. Un piano approssimativo va corretto da chi l'ha scritto — un
umano o un modello — e per correggerlo bisogna sapere cos'e' mancato.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from app.core.budget import EXPANSIONS, NODES, Budget, standard
from app.core.capability import (CAPABILITY, FALLBACK, INCOMPATIBLE,
                                 Requirement)
from app.core.component import Attachment, BuildContext, Component
from app.core.constraints import check as check_constraints
from app.core.errors import Report
from app.core.frame import (FRAME_CONVERTIBLE, POLICIES, POLICY_DIAGNOSE,
                            POLICY_STRICT, FrameComparison, compare)
from app.core.graph import (FROM_DEFAULT, FROM_DERIVED, FROM_OVERRIDE,
                            CompositionGraph, CompositionNode)
from app.core.params import numeric
from app.core.params import resolve as resolve_params
from app.core.registry import Registry
from app.core.socket import SCALE_MODE_FIT_REPLACED
from app.core.resolved import (SEPARATOR, ResolvedComposition, ResolvedLink,
                               ResolvedNode, ResolvedValue)

# Quanto pesa ogni criterio nella scelta fra piu' candidati. Sono pesi, non
# soglie: servono a mettere in fila i candidati in modo ripetibile, non a
# decidere chi e' "meglio" in assoluto. Distanziati perche' un criterio non
# possa essere pareggiato dalla somma di quelli sotto.
PESO_CAPABILITY = 16      # fornisce cio' che l'attacco chiede
PESO_LATO = 8             # ha un innesto sul lato giusto
PESO_STILE = 4            # dichiara lo stile chiesto (non solo "non lo esclude")
PESO_TAG = 1              # per ogni tag chiesto che possiede


@dataclass
class _Candidato:
    component: Component
    score: int

    @property
    def id(self) -> str:
        return self.component.id


# --------------------------------------------------------------------------- #
# Punto di ingresso
# --------------------------------------------------------------------------- #
def _lunghezza(componente, valori: dict) -> float:
    """La misura che il componente dichiara essere la propria lunghezza.

    Se non ne dichiara nessuna si prende la piu' grande fra le distanze: e' un
    ripiego, ma resta una misura che l'autore del componente ha scritto.
    """
    lunghezze = [float(valori[n]) for n, s in componente.params.items()
                 if getattr(s, "semantic_role", "") == "length"
                 and isinstance(valori.get(n), (int, float))]
    if lunghezze:
        return max(lunghezze)
    distanze = [float(valori[n]) for n, s in componente.params.items()
                if getattr(s, "type", "") == "distance"
                and isinstance(valori.get(n), (int, float))]
    return max(distanze) if distanze else 0.0


def resolve(graph: CompositionGraph, registry: Registry, *,
            style: str = "", budget: Budget | None = None,
            frame_policy: str = POLICY_DIAGNOSE,
            report: Report | None = None) -> ResolvedComposition:
    """Da un piano e un vocabolario, il piano risolto."""
    return Resolver(registry, style=style, budget=budget,
                    frame_policy=frame_policy).run(graph, report=report)


class Resolver:
    """La macchina. Separata dalla funzione perche' porta stato: budget,
    contesto, nodi gia' risolti. Uno per generazione."""

    def __init__(self, registry: Registry, *, style: str = "",
                 budget: Budget | None = None,
                 frame_policy: str = POLICY_DIAGNOSE) -> None:
        self.registry = registry
        self.style = style
        # La politica del progetto sulle convenzioni d'asse. `diagnose` dice che
        # due asset non concordano e costruisce comunque; `strict` non fa
        # passare una chimera disorientata. Non esiste una politica che
        # converta: ruotare un figlio contro il socket che il padre ha
        # dichiarato sarebbe un secondo placement system.
        self.frame_policy = frame_policy if frame_policy in POLICIES else POLICY_DIAGNOSE
        # Senza un budget si usa quello **standard**, mai `unlimited()`. Una
        # ricorsione valida non e' una ricorsione che finisce: un componente
        # che si annida riducendo un parametro resta legittimo a ogni passo e
        # non arriva mai in fondo. Chi vuole davvero nessun tetto lo dice.
        self.budget = budget if budget is not None else standard()
        # gli attacchi che indirizzano una parte dichiarata (`on`): non si
        # possono risolvere mentre si cammina, perche' il bersaglio nasce
        # dall'espansione di un componente che forse non e' ancora arrivata.
        self._rinviati: list[CompositionNode] = []
        self._corridoi: set[tuple[str, str]] = set()

    # ------------------------------------------------------------------ run #
    def run(self, graph: CompositionGraph,
            report: Report | None = None) -> ResolvedComposition:
        # `or` non basta: un `Report` vuoto e' falso, e le diagnosi
        # finirebbero in un referto diverso da quello di chi lo ha passato.
        report = report if report is not None else Report()
        stile = self.style or graph.style
        out = ResolvedComposition(graph=graph, registry=self.registry, style=stile,
                                  detail_level=graph.detail_level, seed=graph.seed,
                                  budget=self.budget, report=report,
                                  frame_policy=self.frame_policy)

        # 1. il grafo deve stare in piedi come grafo, prima di guardare i pezzi
        strutturale = graph.validate()
        report.extend(strutturale)
        if not strutturale.ok:
            report.add("GRAPH_INVALID", "il piano non e' risolvibile",
                       why="prima vanno corretti i difetti di struttura")
            return out

        # 2. cosa il piano ha chiesto esplicitamente: apre la strada anche
        #    sotto il livello di dettaglio, per se' e per i propri contenitori
        forzati = self._forzati(graph)

        # 3. i percorsi indirizzati con `on` aprono le parti dichiarate che
        #    nominano, anche sotto il livello di dettaglio: chiedere un piercing
        #    sul naso non deve rendere dettagliato tutto il resto della figura
        self._rinviati = []
        self._corridoi = self._percorsi_indirizzati(graph)

        radice = graph.nodes[graph.root_id]
        self._risolvi_ramo(radice, None, out, forzati)
        self._appendi_rinviati(out, forzati)
        out.root = graph.root_id if graph.root_id in out.nodes else ""
        self.budget.report_to(report, graph.detail_level)
        return out

    # ------------------------------------------------------- nodi del piano #
    def _forzati(self, graph: CompositionGraph) -> set[str]:
        """Chi entra comunque: i nodi chiesti, e tutti i loro contenitori.

        Chiedere «una testa semplice, ma con un piercing sul naso» non deve
        alzare il dettaglio di tutto l'albero. Deve aprire un corridoio: il
        piercing, il naso che lo porta, la testa che porta il naso.
        """
        fuori: set[str] = set()
        for nodo in graph.nodes.values():
            if not nodo.requested:
                continue
            fuori.add(nodo.id)
            fuori.update(a.id for a in graph.ancestors(nodo.id))
        return fuori

    def _percorsi_indirizzati(self, graph: CompositionGraph) -> set[tuple[str, str]]:
        """I corridoi che i percorsi `on` aprono, come coppie (dove, cosa).

        `"testa/naso"` diventa `("", "testa")` e `("testa", "naso")`: mentre si
        espande un nodo il cui percorso finisce per `testa`, il figlio
        dichiarato `naso` va costruito anche se il livello di dettaglio non lo
        prevedeva. E' lo stesso principio dei nodi chiesti — aprire un
        corridoio, non alzare il dettaglio di tutto l'albero — applicato a una
        parte che il piano non nomina come nodo proprio.
        """
        coppie: set[tuple[str, str]] = set()
        for nodo in graph.nodes.values():
            dove = nodo.attachment.on if nodo.attachment else ""
            pezzi = [p for p in dove.split(SEPARATOR) if p]
            for i, segmento in enumerate(pezzi):
                coppie.add((SEPARATOR.join(pezzi[:i]), segmento))
        return coppie

    def _indirizzato(self, percorso: str, id: str) -> bool:
        """Questo figlio dichiarato e' nominato da un `on`, sotto questo nodo?"""
        for prefisso, segmento in self._corridoi:
            if segmento != id:
                continue
            if not prefisso or percorso == prefisso \
                    or percorso.endswith(SEPARATOR + prefisso):
                return True
        return False

    def _appendi_rinviati(self, out: ResolvedComposition,
                          forzati: set[str]) -> None:
        """Gli attacchi con `on`, ora che le parti dichiarate esistono.

        Si ripassa finche' qualcosa si attacca: un rinviato puo' essere il
        bersaglio di un altro rinviato — un piercing sul naso, e una gemma sul
        piercing — e un solo giro lascerebbe fuori il secondo. Il ciclo finisce
        perche' ogni giro o consuma un rinviato o non ne consuma nessuno.
        """
        rimasti = list(self._rinviati)
        while rimasti:
            fermi = []
            for nodo in rimasti:
                bersaglio = self._bersaglio(nodo, out, riferisci=False)
                if bersaglio is None:
                    fermi.append(nodo)
                    continue
                self._risolvi_ramo(nodo, bersaglio, out, forzati,
                                   "%s%s%s" % (bersaglio.path, SEPARATOR, nodo.id),
                                   rinviabile=False)
            if len(fermi) == len(rimasti):
                for nodo in fermi:
                    self._bersaglio(nodo, out, riferisci=True)
                return
            rimasti = fermi

    def _bersaglio(self, nodo: CompositionNode, out: ResolvedComposition,
                   riferisci: bool) -> ResolvedNode | None:
        """Il nodo risolto che un percorso `on` indirizza. Uno solo, o niente.

        Il confronto e' sulla **coda** del percorso: `"testa/naso"` trova
        `corpo/testa/naso` senza obbligare chi scrive il piano a ripetere la
        radice. Se ne trova due non ne sceglie uno: due nasi sono due posti
        diversi, e indovinare qui vorrebbe dire mettere l'orecchino sul naso
        sbagliato senza dirlo a nessuno.
        """
        dove = nodo.attachment.on if nodo.attachment else ""
        coda = SEPARATOR + dove
        trovati = sorted((n for n in out.nodes.values()
                          if n.path == dove or n.path.endswith(coda)),
                         key=lambda n: (n.depth, n.path))
        if len(trovati) == 1:
            return trovati[0]
        if not riferisci:
            return None
        if not trovati:
            out.report.add(
                "ON_TARGET_MISSING",
                "'%s' non trova la parte '%s'" % (nodo.ref, dove), where=nodo.id,
                why="nessun nodo con quel percorso: la parte non e' prevista, "
                    "oppure il livello di dettaglio non la costruisce",
                alternatives=sorted(n.path for n in out.nodes.values())[:8])
        else:
            out.report.add(
                "ON_TARGET_AMBIGUOUS",
                "'%s' indirizza '%s', e ce ne sono %d"
                % (nodo.ref, dove, len(trovati)), where=nodo.id,
                why="qualificare il percorso a partire da un nodo che ne ha uno solo",
                alternatives=[n.path for n in trovati][:8])
        out.unresolved.append(nodo.id)
        return None

    def _risolvi_ramo(self, nodo: CompositionNode, padre: ResolvedNode | None,
                      out: ResolvedComposition, forzati: set[str],
                      percorso: str = "", rinviabile: bool = True) -> None:
        """Un nodo del piano, i suoi figli del piano, i figli del componente."""
        graph = out.graph
        attacco = nodo.attachment
        if rinviabile and attacco is not None and attacco.deferred:
            # il bersaglio e' una parte dichiarata: forse non esiste ancora
            self._rinviati.append(nodo)
            return
        if not graph.wanted(nodo) and nodo.id not in forzati:
            return
        percorso = percorso or graph.path(nodo.id)
        if not self._paga(NODES, out, percorso):
            return

        risolto = self._risolvi_nodo(nodo, padre, out, percorso)
        if risolto is None:
            out.unresolved.append(nodo.id)
            return
        self._aggiungi(risolto, padre, out)

        # i figli del piano vengono prima: sono la volonta' esplicita
        figli_del_piano = [c for c in graph.children(nodo.id)]
        for figlio in figli_del_piano:
            self._risolvi_ramo(figlio, risolto, out, forzati,
                               "%s%s%s" % (risolto.path, SEPARATOR, figlio.id))

        # poi quelli che il componente dichiara da se', saltando quelli di cui
        # il piano si e' gia' occupato
        self._espandi(risolto, out, esclusi=self._gia_nel_piano(figli_del_piano, out))

    def _gia_nel_piano(self, figli, out: ResolvedComposition) -> set[str]:
        """Cosa il piano ha gia' messo, in una forma confrontabile.

        Serve perche' il piano **vince** sulla dichiarazione: se il piano ha
        gia' messo un torso, il componente non deve aggiungerne un secondo
        perche' lo dichiara fra i propri figli. Il confronto va fatto sia sul
        nome dell'attacco sia sul componente risolto: `torso`, `humanoid:torso`
        e un `humanoid:torso` sostituito con un corpo di pesce sono lo stesso
        posto occupato, scritto in tre modi.
        """
        graph = out.graph
        presi: set[str] = set()
        for figlio in figli:
            presi.add(figlio.id)
            presi.add(figlio.ref)
            presi.add(graph.resolved_ref(figlio.id))
            risolto = out.nodes.get(figlio.id)
            if risolto is not None:
                presi.add(risolto.ref)
                presi.add(risolto.requested_ref)
        return {p for p in presi if p}

    def _risolvi_nodo(self, nodo: CompositionNode, padre: ResolvedNode | None,
                      out: ResolvedComposition,
                      percorso: str = "") -> ResolvedNode | None:
        graph = out.graph
        chiesto, effettivo = nodo.ref, graph.resolved_ref(nodo.id)
        percorso = percorso or graph.path(nodo.id)
        attacco = nodo.attachment

        componente = self._trova(effettivo, out, percorso,
                                 requirement=attacco.requirement if attacco else None,
                                 origine="sostituzione" if nodo.id in graph.swaps else "")
        if componente is None:
            return None

        risolto = ResolvedNode(
            id=nodo.id, component=componente, path=percorso,
            depth=percorso.count(SEPARATOR),
            requested_ref=chiesto, tags=nodo.tags,
            effects=list(nodo.effects), from_plan=True,
            material=attacco.material if attacco is not None else "",
            swapped_from=chiesto if nodo.id in graph.swaps else "")

        if padre is not None and attacco is not None:
            risolto.link = self._collega(attacco, padre, risolto, out)
            if risolto.link is None:
                return None
        self._parametri(risolto, padre, out, nodo.overrides)
        for effetto in nodo.effects:
            out.effects.append((nodo.id, effetto))
        return risolto

    # -------------------------------------------- espansione dei componenti #
    def _espandi(self, nodo: ResolvedNode, out: ResolvedComposition,
                 esclusi: Iterable[str] = ()) -> None:
        """I figli che il componente dichiara da se'.

        Non c'e' una profondita' massima: si scende finche' il dettaglio lo
        prevede, il budget lo consente e qualcosa cambia a ogni giro. Un limite
        semantico fisso taglierebbe alberi legittimi e non fermerebbe quelli
        che non finiscono.
        """
        componente = nodo.component
        if componente.children is None:
            return
        if not self._paga(EXPANSIONS, out, nodo.path):
            return

        ctx = BuildContext(style=out.style, detail_level=out.detail_level,
                           depth=nodo.depth, seed=out.seed, budget=self.budget,
                           path=nodo.path, report=out.report)
        try:
            dichiarati = list(componente.children(nodo.values, ctx) or ())
        except Exception as exc:                          # noqa: BLE001
            out.report.add("EXPANSION_FAILED",
                           "'%s' non sa elencare i propri figli: %s"
                           % (componente.id, exc), where=nodo.path)
            return

        fuori = set(esclusi)
        voluti = [a for a in dichiarati
                  if (a.wanted_at(out.detail_level, False)
                      or self._indirizzato(nodo.path, a.id))
                  and not self._occupato(a, componente.plugin, fuori)]
        # un fratello sostituito esce dall'espansione: al suo posto c'e' l'altro
        sostituiti = {a.replaces for a in voluti if a.replaces}
        voluti = [a for a in voluti if a.id not in sostituiti]

        if any(a.replaces_parent for a in voluti):
            # i figli prendono il posto della geometria del padre, non si
            # aggiungono a essa: altrimenti resterebbero tutte e due
            nodo.builds_geometry = False

        for attacco in voluti:
            self._risolvi_dichiarato(attacco, nodo, out)

    def _occupato(self, attacco: Attachment, home: str, esclusi: set[str]) -> bool:
        """Questo figlio dichiarato lo ha gia' messo il piano?"""
        if attacco.id in esclusi or attacco.component in esclusi:
            return True
        componente = self._quale(attacco.component, home)
        return componente is not None and componente.id in esclusi

    def _quale(self, ref: str, home: str = ""):
        """Il componente di un riferimento, in silenzio. Senza diagnosi.

        Serve dove la risposta e' solo per decidere qualcosa internamente: dire
        «non trovato» qui riempirebbe il referto di errori su componenti che non
        stavamo per usare comunque.
        """
        if ":" in ref:
            return self.registry.component(ref)
        if home:
            proprio = self.registry.component("%s:%s" % (home, ref))
            if proprio is not None:
                return proprio
        candidati = self.registry.named(ref)
        return candidati[0] if len(candidati) == 1 else None

    def _risolvi_dichiarato(self, attacco: Attachment, padre: ResolvedNode,
                            out: ResolvedComposition) -> None:
        percorso = "%s%s%s" % (padre.path, SEPARATOR, attacco.id)
        if not self._paga(NODES, out, percorso):
            return

        componente = self._trova(attacco.component, out, percorso,
                                 requirement=attacco.requirement,
                                 home=padre.component.plugin)
        if componente is None:
            out.unresolved.append(percorso)
            return

        id = self._id_libero("%s%s%s" % (padre.id, SEPARATOR, attacco.id), out)
        risolto = ResolvedNode(id=id, component=componente, path=percorso,
                               depth=padre.depth + 1, requested_ref=attacco.component,
                               tags=attacco.tags, from_plan=False,
                               material=attacco.material)

        # i parametri prima del collegamento: la ripetizione si riconosce sui
        # valori risolti, non sugli scostamenti dichiarati. Confrontare un
        # override con dei valori completi non troverebbe mai niente.
        self._parametri(risolto, padre, out, attacco.params)
        if self._ripetizione(risolto, padre, out, percorso):
            return

        risolto.link = self._collega(attacco, padre, risolto, out)
        if risolto.link is None:
            out.unresolved.append(percorso)
            return
        self._aggiungi(risolto, padre, out)
        self._espandi(risolto, out)

    def _ripetizione(self, figlio: ResolvedNode, padre: ResolvedNode,
                     out: ResolvedComposition, percorso: str) -> bool:
        """Lo stesso componente con gli stessi parametri dentro se stesso.

        Un ramo che porta un ramo va bene finche' **qualcosa cambia**. Se non
        cambia niente, non e' ricorsione: e' un ciclo che non si e' accorto di
        esserlo, e senza questo controllo si fermerebbe solo il budget — cioe'
        dopo aver sprecato tutto.
        """
        firma = self._firma(figlio)
        corrente = padre
        while corrente is not None:
            if self._firma(corrente) == firma:
                out.report.note("RECURSION_WITHOUT_PROGRESS",
                                "'%s' si ripete identico" % figlio.ref,
                                where=percorso,
                                why="stesso componente e stessi parametri di '%s'"
                                    % corrente.id)
                return True
            corrente = out.nodes.get(corrente.link.parent) if corrente.link else None
        return False

    @staticmethod
    def _firma(nodo: ResolvedNode) -> tuple[str, str]:
        return nodo.ref, repr(sorted(nodo.values.items()))

    # ------------------------------------------------- scelta del componente #
    def _trova(self, ref: str, out: ResolvedComposition, dove: str,
               requirement: Requirement | None = None,
               origine: str = "", home: str = "") -> Component | None:
        """Da un riferimento a un componente. Uno, o nessuno con una spiegazione.

        Un riferimento nudo si legge in tre tempi: prima come nome nel plugin di
        casa (un plugin non deve qualificare i riferimenti a se stesso), poi
        come nome ovunque, infine come **capability** — «mettici qualcosa che
        fornisce questo». L'ultimo caso e' quello che serve a un piano scritto
        senza sapere quali plugin sono installati.
        """
        if not ref:
            out.report.add("COMPONENT_NOT_FOUND", "riferimento vuoto", where=dove)
            return None

        plugin, _, nome = ref.partition(":")
        if nome:
            componente = self.registry.component(ref)
            if componente is None:
                if not self._namespace(plugin):
                    out.report.add(
                        "PLUGIN_NOT_FOUND", "plugin non installato: '%s'" % plugin,
                        where=dove, why="richiesto da '%s'%s" % (ref, self._per(origine)),
                        alternatives=self._namespaces()[:6])
                else:
                    out.report.add(
                        "COMPONENT_NOT_FOUND",
                        "'%s' non esiste nel plugin '%s'" % (nome, plugin),
                        where=dove, why="richiesto da '%s'%s" % (ref, self._per(origine)),
                        alternatives=[c.id for c in
                                      self.registry.components(plugin=plugin)][:6]
                        or [c.id for c in self.registry.named(nome)][:6])
                return None
            return self._compatibile(componente, out, dove)

        # 1. il plugin di casa: un plugin si riferisce ai propri pezzi per nome
        if home:
            proprio = self.registry.component("%s:%s" % (home, ref))
            if proprio is not None:
                return self._compatibile(proprio, out, dove)

        # 2. per nome, ovunque. Sceglierne uno a caso qui vorrebbe dire che lo
        #    stesso piano, con un plugin in piu' installato, darebbe un modello
        #    diverso.
        candidati = self.registry.named(ref)
        if candidati:
            scelti = self._classifica(candidati, requirement, out.style)
            if len(scelti) == 1:
                return self._compatibile(scelti[0].component, out, dove)
            out.report.add(
                "AMBIGUOUS_COMPONENT",
                "'%s' non basta a scegliere: %d candidati" % (ref, len(scelti)),
                where=dove,
                why="qualificare il riferimento come 'plugin:%s'" % ref,
                alternatives=[c.id for c in scelti])
            return None

        # 3. come capability: «mettici qualcosa che fornisce questo». Solo chi
        #    la **fornisce**: chi la accetta e' un contenitore, non un candidato.
        fornitori = [c for c in self.registry.providers(capability=ref,
                                                        style=out.style)
                     if c.provides_capability(ref)]
        if fornitori:
            scelti = self._classifica(fornitori, requirement, out.style)
            if len(scelti) == 1:
                return self._compatibile(scelti[0].component, out, dove)
            out.report.add(
                "AMBIGUOUS_PROVIDER",
                "piu' componenti forniscono '%s': %d" % (ref, len(scelti)),
                where=dove,
                why="indicare quale, o restringere con lato, tag o stile",
                alternatives=[c.id for c in scelti])
            return None

        out.report.add("COMPONENT_NOT_FOUND", "nessun componente '%s'" % ref,
                       where=dove,
                       why="ne' un nome, ne' una capability fornita da qualcuno",
                       alternatives=[c.id for c in self.registry.search(ref)][:6])
        return None

    def _classifica(self, candidati: list[Component],
                    requirement: Requirement | None,
                    style: str) -> list[_Candidato]:
        """I candidati a pari merito in cima. Deterministico, e senza fantasia.

        Non e' un giudizio di qualita': e' un ordine ripetibile. Se in cima ce
        ne resta piu' di uno, la risposta giusta e' dirlo, non tirare a sorte.
        """
        R = requirement or Requirement()
        valutati: list[_Candidato] = []
        for componente in sorted(candidati, key=lambda c: c.id):
            punti = 0
            if R.capability and componente.provides_capability(R.capability):
                punti += PESO_CAPABILITY
            if R.side and componente.accepts(R.capability, R.side):
                punti += PESO_LATO
            if style and style in componente.styles:
                punti += PESO_STILE
            punti += PESO_TAG * len(R.tags & componente.tags)
            valutati.append(_Candidato(componente, punti))

        massimo = max(c.score for c in valutati)
        return [c for c in valutati if c.score == massimo]

    def _compatibile(self, componente: Component, out: ResolvedComposition,
                     dove: str) -> Component | None:
        """Lo stile non si converte: o il componente lo parla, o si cambia pezzo."""
        if componente.supports_style(out.style):
            return componente
        alternative = [c.id for c in self.registry.components(style=out.style)
                       if any(componente.provides_capability(p.name)
                              for p in c.provides)]
        out.report.add("STYLE_INCOMPATIBLE",
                       "'%s' non e' fatto per lo stile '%s'"
                       % (componente.id, out.style), where=dove,
                       why="dichiara %s" % ", ".join(sorted(componente.styles)),
                       alternatives=alternative[:6])
        return None

    def _namespace(self, plugin: str) -> bool:
        """Il namespace esiste se ci vive qualcosa.

        Non basta chiedere al registry se il plugin e' installato: un componente
        registrato a mano — nei test, o da un plugin incorporato — ha un
        namespace valido senza avere un manifest. Confondere le due cose farebbe
        dire "plugin non installato" a chi ha solo sbagliato il nome del pezzo.
        """
        if self.registry.plugin(plugin) is not None:
            return True
        return any(c.plugin == plugin for c in self.registry.components())

    def _namespaces(self) -> list[str]:
        nomi = {p.id for p in self.registry.plugins()}
        nomi |= {c.plugin for c in self.registry.components()}
        return sorted(nomi)

    @staticmethod
    def _per(origine: str) -> str:
        return " (%s)" % origine if origine else ""

    # ------------------------------------------------------- collegamento #
    def _collega(self, attacco: Attachment, padre: ResolvedNode,
                 figlio: ResolvedNode, out: ResolvedComposition) -> ResolvedLink | None:
        """Trova nel padre l'innesto giusto, e verifica che il figlio lo riempia.

        Due domande separate, in quest'ordine:

            1. il padre ha un posto che soddisfa il requisito?   (`mounts`)
            2. il figlio sa stare in quel posto?                 (`provides`)
        """
        requisito = attacco.requirement or Requirement()
        innesti = padre.component.mounts
        if not innesti:
            out.report.add(
                "NO_MOUNTS", "'%s' non dichiara nessun innesto" % padre.ref,
                where=figlio.path,
                why="'%s' chiedeva %s" % (figlio.ref, requisito.describe()),
                alternatives=[c.id for c in self.registry.socket_providers(
                    requisito.capability)][:6])
            return None

        scelto, punteggio = self._innesto(requisito, innesti, figlio.component,
                                          padre.occupied)
        if scelto is None:
            vicini = [str(m) for m in innesti if requisito.score(m) > INCOMPATIBLE]
            out.report.add(
                "SOCKET_INCOMPATIBLE",
                "'%s' non ha un innesto per %s" % (padre.ref, requisito.describe()),
                where=figlio.path,
                why="offre: %s%s" % (", ".join(sorted(str(m) for m in innesti)),
                                     "" if not vicini else
                                     "; ci andrebbe vicino %s, ma il ripiego non e' "
                                     "dichiarato" % ", ".join(sorted(vicini))),
                alternatives=[c.id for c in self.registry.socket_providers(
                    requisito.capability, requisito.side)][:6])
            return None

        if scelto.capability and not figlio.component.provides_capability(scelto.capability):
            out.report.add(
                "PROVIDER_INCOMPATIBLE",
                "'%s' non fornisce '%s'" % (figlio.ref, scelto.capability),
                where=figlio.path,
                why="l'innesto '%s' di '%s' accetta '%s'; il componente fornisce: %s"
                    % (scelto.name or "?", padre.ref, scelto.capability,
                       ", ".join(sorted(p.name for p in figlio.component.provides))
                       or "niente"),
                alternatives=[c.id for c in self.registry.providers(
                    capability=scelto.capability, style=out.style)][:6])
            return None

        chiave = self._chiave(scelto)
        preso = padre.occupied.get(chiave, 0)
        if scelto.capacity and preso >= scelto.capacity:
            # si attacca lo stesso: un pezzo compenetrato e' un difetto visibile
            # e correggibile, un pezzo mancante e' un modello sbagliato e basta.
            out.report.warn(
                "MOUNT_CROWDED",
                "l'innesto '%s' di '%s' porta gia' %d componenti"
                % (chiave, padre.ref, preso), where=figlio.path,
                why="'%s' non ha altri innesti liberi per %s"
                    % (padre.ref, requisito.describe()))
        padre.occupied[chiave] = preso + 1

        if punteggio == FALLBACK and (requisito.capability or requisito.socket_id):
            out.report.note(
                "MOUNT_FALLBACK",
                "'%s' si attacca per ripiego a '%s'" % (figlio.ref, chiave),
                where=figlio.path,
                why="nessun innesto soddisfa %s" % requisito.describe())

        confronto = self._frame(padre, figlio, out)

        return ResolvedLink(
            parent=padre.id, parent_socket=scelto.socket_id,
            capability=scelto.capability, side=scelto.side or requisito.side,
            own_socket=attacco.own_socket, score=punteggio, requirement=requisito,
            scale_mode=attacco.scale_mode, insert=attacco.insert, roll=attacco.roll,
            frame=confronto.result,
            target_size=self._taglia_sostituita(figlio, padre, attacco, out))

    def _frame(self, padre: ResolvedNode, figlio: ResolvedNode,
               out: ResolvedComposition) -> FrameComparison:
        """I due asset concordano su dove sia il sopra e dove il davanti?

        E' il controllo che V4 non faceva: `frame` era una diagnostica di
        authoring su un pezzo solo, e due plugin con convenzioni diverse si
        montavano in silenzio. Qui si confrontano **solo** le dichiarazioni, e
        non si corregge niente: `app/core/frame.py` spiega perche'.

        Un frame non dichiarato non produce nessuna diagnostica. Non e' una
        svista: l'unica alternativa sarebbe pretendere la terna da tutti i
        componenti installati, cioe' rendere obbligatoria una dichiarazione che
        22 plugin non hanno, e il contratto dice quello che i dati permettono
        di dire.
        """
        confronto = compare(padre.component, figlio.component)
        if not confronto.detectable:
            return confronto
        mossa = confronto.move(scope="subtree:%s" % figlio.id)
        dettaglio = ("convenzioni dichiarate: '%s' %s, '%s' %s"
                     % (padre.ref, confronto.parent.describe(),
                        figlio.ref, confronto.child.describe()))
        if confronto.result == FRAME_CONVERTIBLE:
            codice, perche = "FRAME_CONVERTIBLE", "%s; %s" % (dettaglio,
                                                              confronto.describe())
            alternative = ["fx:rotate axis=%s angle=%s su %s"
                           % (mossa["params"]["axis"], mossa["params"]["angle"],
                              mossa["scope"])]
        else:
            codice, perche = "FRAME_AMBIGUOUS", "%s; %s" % (dettaglio,
                                                            confronto.describe())
            alternative = ["dichiarare up e front su entrambi i componenti"]
        if self.frame_policy == POLICY_STRICT:
            out.report.add(codice, "'%s' e '%s' non concordano sull'orientamento"
                           % (padre.ref, figlio.ref), where=figlio.path,
                           why=perche, alternatives=alternative)
        else:
            out.report.warn(codice, "'%s' e '%s' non concordano sull'orientamento"
                            % (padre.ref, figlio.ref), where=figlio.path,
                            why=perche, alternatives=alternative)
        return confronto

    def _taglia_sostituita(self, figlio: ResolvedNode, padre: ResolvedNode,
                           attacco: Attachment, out: ResolvedComposition) -> float:
        """Quanto era grande il pezzo che questo sta prendendo il posto di.

        Si misura sui **parametri** del componente sostituito, non sulla sua
        geometria: costruirlo solo per misurarlo vorrebbe dire costruire due
        volte ogni sostituzione, e i numeri dichiarati bastano — un componente
        che dichiara quale suo parametro e' una lunghezza sta gia' dicendo
        quanto e' lungo.
        """
        if attacco.scale_mode != SCALE_MODE_FIT_REPLACED or not figlio.swapped_from:
            return 0.0
        sostituito = self.registry.component(figlio.swapped_from)
        if sostituito is None:
            out.report.warn(
                "FIT_TARGET_UNKNOWN",
                "'%s' non si sa quanto fosse grande" % figlio.swapped_from,
                where=figlio.path,
                why="senza il componente sostituito la scala resta quella propria")
            return 0.0
        ambiti = {"parent": numeric(padre.values)}
        radice = out.nodes.get(out.graph.root_id)
        if radice is not None:
            ambiti["root"] = numeric(radice.values)
        valori = resolve_params(sostituito.params, {}, scopes=ambiti)
        return _lunghezza(sostituito, valori)

    @staticmethod
    def _chiave(innesto) -> str:
        return innesto.socket_id or "%s:%s" % (innesto.capability, innesto.side)

    @classmethod
    def _innesto(cls, requisito: Requirement, innesti, figlio: Component,
                 occupati: dict[str, int] | None = None):
        """L'innesto migliore, e a parita' quello che il figlio sa riempire.

        La scala di punteggio e' quella dello STEP 1 — socket esatto, capability
        e lato, capability e tag, capability, ripiego — e la stessa funzione
        misurera' i socket veri quando il builder li avra' in mano: `Mount`
        risponde alle stesse domande di un `Socket` apposta.

        Il secondo criterio conta piu' di quanto sembri. Con un requisito
        generico («attaccalo dove ci sta») due innesti prendono lo stesso
        punteggio, e sceglierli in ordine alfabetico manderebbe una testa nel
        posto di un braccio. Preferire quello che il figlio **sa fornire**
        risolve il pareggio con l'unica informazione pertinente.

        Un innesto libero viene prima di uno gia' occupato, anche se occupato
        aveva un punteggio migliore: un braccio nel posto giusto insieme a un
        altro braccio non e' meglio di un braccio nel posto secondo. Su un corpo
        di pesce con due pinne, il terzo arto lo si vede subito.

        Prima si **filtra**, poi si ordina. Un innesto incompatibile non entra
        nella graduatoria: non esiste un punteggio abbastanza alto da renderlo
        una scelta. Ordinare tutto e prendere il massimo darebbe la risposta
        giusta quasi sempre e quella sbagliata quando conta.

        Fra i compatibili, l'ordine dei criteri:

            1. libero               due pezzi nello stesso posto sono due pezzi
                                    compenetrati, e non si vede finche' non si
                                    guarda il modello
            2. punteggio            la scala dei cinque livelli
            3. tag in comune        distingue due innesti con lo stesso lato:
                                    `spalla_l` e `anca_l` sono entrambi arti a
                                    sinistra, e senza i tag il braccio finirebbe
                                    dove va la gamba
            4. il figlio lo sa riempire
            5. il nome, per non lasciare niente al caso
        """
        occupati = occupati or {}
        valutati = []
        for innesto in innesti:
            compatibile, valore = cls._giudizio(requisito, innesto, figlio)
            if not compatibile:
                continue
            preso = occupati.get(cls._chiave(innesto), 0)
            libero = 0 if (innesto.capacity and preso >= innesto.capacity) else 1
            affinita = len(requisito.tags & innesto.tags)
            adatto = 1 if figlio.provides_capability(innesto.capability) else 0
            valutati.append((-libero, -valore, -affinita, -adatto,
                             innesto.socket_id, innesto.capability, innesto))
        if not valutati:
            return None, INCOMPATIBLE
        valutati.sort(key=lambda t: t[:6])
        primo = valutati[0]
        return primo[6], -primo[1]

    @staticmethod
    def _giudizio(requisito: Requirement, innesto, figlio: Component):
        """(compatibile, punteggio). Due domande diverse, tenute separate.

        La compatibilita' e' un si' o un no e viene prima; il punteggio dice
        soltanto quanto e' buona una corrispondenza gia' ammessa.

        Il caso delicato e' il `FALLBACK`, che nasce da due situazioni diverse
        e va trattato in due modi diversi:

        - **il requisito non chiede niente.** Se il figlio fornisce cio' che
          l'innesto accetta, la corrispondenza c'e' davvero: l'ha dichiarata il
          figlio invece del requisito, e vale quanto una corrispondenza per
          capability. Se non la fornisce, non e' un attacco, e' una casualita'.
        - **il lato e' sbagliato.** Qui serve un permesso esplicito, da chi
          chiede o da chi offre. Altrimenti una spada finirebbe sulla pinna
          destra solo perche' quella sinistra era occupata.
        """
        punteggio = requisito.score(innesto)
        if punteggio >= CAPABILITY:
            return True, punteggio
        if punteggio <= INCOMPATIBLE:
            return False, punteggio

        senza_richiesta = not (requisito.capability or requisito.socket_id)
        if senza_richiesta and innesto.capability \
                and figlio.provides_capability(innesto.capability):
            return True, CAPABILITY
        if requisito.allow_fallback or innesto.allow_fallback:
            return True, FALLBACK
        return False, FALLBACK

    # --------------------------------------------------------- parametri #
    def _parametri(self, nodo: ResolvedNode, padre: ResolvedNode | None,
                   out: ResolvedComposition, overrides: dict | None) -> None:
        """Valori validi, e la memoria di chi li ha decisi.

        L'ordine e' quello del contratto: predefiniti del componente, poi cio'
        che il piano impone, poi le espressioni derivate — che possono leggere
        `self`, `parent` e `root` e quindi vanno per ultime.
        """
        schema = nodo.component.params
        ambiti = {}
        if padre is not None:
            ambiti["parent"] = numeric(padre.values)
        radice = out.nodes.get(out.graph.root_id)
        if radice is not None:
            ambiti["root"] = numeric(radice.values)
        elif padre is None:
            ambiti["root"] = {}

        chiesti = dict(overrides or {})
        valori = resolve_params(schema, chiesti, scopes=ambiti, report=out.report,
                                where=nodo.path)
        valori = check_constraints(nodo.component.constraints, valori, schema,
                                   scopes=ambiti, report=out.report, where=nodo.path)

        nodo.values = valori
        for nome, valore in valori.items():
            spec = schema.get(nome)
            if spec is not None and spec.is_derived:
                nodo.sources[nome] = ResolvedValue(valore, FROM_DERIVED,
                                                   expression=spec.derived)
            elif nome in chiesti:
                nodo.sources[nome] = ResolvedValue(valore, FROM_OVERRIDE,
                                                   origin=nodo.id)
            else:
                nodo.sources[nome] = ResolvedValue(valore, FROM_DEFAULT)

    # ------------------------------------------------------------ utilita' #
    def _paga(self, tipo: str, out: ResolvedComposition, dove: str) -> bool:
        """Il budget dice quando smettere. Il dettaglio dice quanto vorremmo."""
        if self.budget.spend(tipo, 1, where=dove):
            return True
        return False

    @staticmethod
    def _aggiungi(nodo: ResolvedNode, padre: ResolvedNode | None,
                  out: ResolvedComposition) -> None:
        out.nodes[nodo.id] = nodo
        out.order.append(nodo.id)
        if padre is not None:
            padre.children.append(nodo.id)

    @staticmethod
    def _id_libero(proposto: str, out: ResolvedComposition) -> str:
        if proposto not in out.nodes:
            return proposto
        n = 2
        while "%s#%d" % (proposto, n) in out.nodes:
            n += 1
        return "%s#%d" % (proposto, n)
