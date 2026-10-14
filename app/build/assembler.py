"""Il builder: dove finisce ogni vertice.

    registry     cosa esiste
    graph        cosa voglio
    resolver     quali componenti uso, collegati come
    effetti      cosa cambio
    builder      la geometria vera                       <- questo file

E' il primo punto in cui il piano diventa una mesh. Il builder percorre il
grafo risolto, chiede a ogni componente il proprio `Piece`, controlla che i
socket promessi esistano davvero, posa i figli nei socket dei padri, applica le
deformazioni gia' validate dalla pipeline degli effetti e riferisce.

## Non sa cosa sta costruendo

Non c'e' un `build_humanoid`, non c'e' un `if plugin == ...`. Il builder lavora
solo su `Component`, `Piece`, `Socket`, `ResolvedNode`, `ResolvedLink` e
`PlannedEffect`. Un umanoide con la testa di rana e una casa su un pianeta
passano dallo stesso codice, ed e' l'unico modo di sapere che l'architettura
non e' specifica per un dominio.

## Dove nasce un socket

Un socket **vero** — posizione, verso, raggio — esiste solo dentro il `Piece`.
Il resolver aveva le dichiarazioni (`Component.mounts`) e ha deciso *chi si
collega a chi*; qui si controlla che quelle promesse fossero vere e si decide
*dove esattamente*. E' la meta' che mancava, ed e' anche il momento in cui una
dichiarazione sbagliata viene finalmente riferita.

## Ogni pezzo tiene la sua mesh

Niente fusione automatica. Nel low poly una testa, un torso e un braccio sono
tre oggetti con tre materiali e tre destini possibili — animazione, esportazione,
sostituzione. Fonderli sarebbe una decisione irreversibile presa nel posto
sbagliato: chi vuole un'unica mesh la chiede.

## Nome del file

Si chiamera' `builder.py` quando il vecchio percorso SDF sara' andato via; oggi
quel nome e' occupato da chi serve i plugin non ancora migrati, e prendersi il
nome adesso vorrebbe dire spegnere meta' della suite in un colpo solo.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator

import numpy as np
import trimesh

from app.core.budget import TRIANGLES, Budget, unlimited
from app.core.capability import Requirement, best_match
from app.core.component import BuildContext, Component, Piece
from app.core.effect import EffectContext, EffectedComposition, PlannedEffect
from app.core.errors import Report
from app.core.resolved import ResolvedComposition, ResolvedNode
from app.core.socket import (SCALE_MODE_FIT_REPLACED, Placement, Socket,
                             attach)
from app.core.vocabulary import (STAGE_FINAL, STAGE_GLOBAL, STAGE_LOCAL,
                                 STAGE_STYLE)

# Gli stadi che il builder esegue. `structural` e `proportion` sono gia' stati
# applicati — il primo al grafo, il secondo ai parametri — e rifarli qui
# vorrebbe dire applicarli due volte.
STADI_LOCALI = (STAGE_LOCAL,)
STADI_GLOBALI = (STAGE_GLOBAL, STAGE_STYLE, STAGE_FINAL)

# Quanto puo' distare un giunto prima di essere un pezzo staccato, in frazione
# della misura del modello. Il posizionamento e' esatto per costruzione: questo
# serve a intercettare una deformazione che ha spostato la geometria lasciando
# indietro il socket.
GIUNTO_MASSIMO = 0.02


@dataclass
class BuiltNode:
    """Un componente costruito: la sua mesh, dove sta, cosa offre.

    `piece.mesh` e' la geometria nel sistema locale e `placement` la posa: la
    coppia serve a chi anima, che ha bisogno di una trasformazione e non di
    vertici gia' spostati. `mesh` e' la stessa geometria nel sistema del
    modello, ed e' quella che si esporta.
    """

    id: str
    node: ResolvedNode
    piece: Piece
    placement: Placement = field(default_factory=Placement)
    mesh: trimesh.Trimesh | None = None          # nel sistema del modello
    sockets: dict[str, Socket] = field(default_factory=dict)   # locali
    parent: str = ""
    material: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    deformed: bool = False                       # un effetto ne ha mosso i vertici
    # La mesh **come il componente l'ha costruita**, prima di qualunque effetto.
    # Serve al giudizio di stile: una piega rende non complanari quadrilateri
    # che erano piatti, e misurare li' direbbe "campionata" di una forma
    # disegnata benissimo. Lo stile giudica come e' stata costruita, non che
    # cosa le e' stato fatto dopo. Non costa niente: e' un riferimento, e le
    # deformazioni restituiscono sempre una mesh nuova.
    designed: trimesh.Trimesh | None = None
    # I socket nel sistema del modello, quando una deformazione globale li ha
    # spostati. Da quel momento `placement` non basta piu' a ricavarli: una
    # deformazione non e' una trasformazione rigida, e comporla con la posa
    # darebbe una posizione che non esiste.
    world_sockets: dict[str, Socket] = field(default_factory=dict)

    @property
    def component(self) -> Component:
        return self.node.component

    @property
    def ref(self) -> str:
        return self.node.ref

    @property
    def role(self) -> str:
        return self.node.component.role

    @property
    def triangles(self) -> int:
        return 0 if self.mesh is None else len(self.mesh.faces)

    @property
    def vertices(self) -> int:
        return 0 if self.mesh is None else len(self.mesh.vertices)

    @property
    def parent_socket(self) -> str:
        """Il nome dell'innesto del padre a cui questo pezzo e' appeso.

        Sta nel collegamento risolto, ma chi guarda un modello costruito — lo
        scheletro, un ispettore, l'interfaccia — ha in mano il nodo costruito e
        non il piano. Due righe qui evitano che ognuno rifaccia la stessa
        catena di attributi.
        """
        return self.node.link.parent_socket if self.node.link is not None else ""

    @property
    def tags(self) -> tuple[str, ...]:
        """Le etichette del nodo e del componente, insieme e ordinate."""
        return tuple(sorted(self.node.tags | self.node.component.tags))

    def socket_world(self, name: str) -> Socket | None:
        if name in self.world_sockets:
            return self.world_sockets[name]
        locale = self.sockets.get(name)
        return None if locale is None else self.placement.socket_world(locale)

    def describe(self) -> str:
        forma = "senza geometria" if self.mesh is None \
            else "%d triangoli" % self.triangles
        return "%s: %s (%s)" % (self.id, self.ref, forma)


@dataclass
class BuildResult:
    """Il modello costruito, e tutto cio' che serve per farne qualcosa."""

    composition: ResolvedComposition
    nodes: dict[str, BuiltNode] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)
    effects: list[PlannedEffect] = field(default_factory=list)
    report: Report = field(default_factory=Report)
    skipped: list[str] = field(default_factory=list)

    # ------------------------------------------------------------- lettura #
    @property
    def ok(self) -> bool:
        return self.report.ok

    @property
    def style(self) -> str:
        return self.composition.style

    def node(self, id: str) -> BuiltNode | None:
        return self.nodes.get(id)

    def walk(self) -> Iterator[BuiltNode]:
        for id in self.order:
            if id in self.nodes:
                yield self.nodes[id]

    def geometry(self) -> list[BuiltNode]:
        return [n for n in self.walk() if n.mesh is not None]

    def meshes(self) -> list[trimesh.Trimesh]:
        return [n.mesh for n in self.geometry()]

    @property
    def triangles(self) -> int:
        return sum(n.triangles for n in self.walk())

    @property
    def vertices(self) -> int:
        return sum(n.vertices for n in self.walk())

    @property
    def bounds(self) -> np.ndarray | None:
        # una mesh senza vertici non ha limiti: chiederglieli darebbe numeri
        # inventati, e il modello vuoto e' un caso vero, non un incidente
        pezzi = [n.mesh.bounds for n in self.geometry() if len(n.mesh.vertices)]
        if not pezzi:
            return None
        return np.array([np.min([b[0] for b in pezzi], axis=0),
                         np.max([b[1] for b in pezzi], axis=0)])

    @property
    def size(self) -> np.ndarray:
        limiti = self.bounds
        return np.zeros(3) if limiti is None else limiti[1] - limiti[0]

    def combined(self) -> trimesh.Trimesh | None:
        """Tutti i pezzi in una mesh sola. Su richiesta, mai d'ufficio."""
        pezzi = self.meshes()
        if not pezzi:
            return None
        return trimesh.util.concatenate(pezzi)

    def scene(self) -> trimesh.Scene:
        """Una scena con un nodo per componente, con i nomi del grafo."""
        scena = trimesh.Scene()
        for costruito in self.geometry():
            scena.add_geometry(costruito.mesh, node_name=costruito.id,
                               geom_name="%s|%s" % (costruito.id, costruito.ref))
        return scena

    def materials(self) -> dict[str, str]:
        return {n.id: n.material for n in self.walk() if n.material}

    def describe(self) -> str:
        righe = ["%s%s" % ("  " * n.node.depth, n.describe()) for n in self.walk()]
        if self.skipped:
            righe.append("saltati: %s" % ", ".join(self.skipped))
        righe.append("totale: %d triangoli, %d vertici" % (self.triangles,
                                                           self.vertices))
        return "\n".join(righe)


# --------------------------------------------------------------------------- #
# Il builder
# --------------------------------------------------------------------------- #
class Builder:
    """Percorre il grafo risolto e produce geometria. Non sa cosa sia."""

    def __init__(self, *, budget: Budget | None = None,
                 strict_sockets: bool = False) -> None:
        self.budget = budget if budget is not None else unlimited()
        self.strict_sockets = strict_sockets

    # ------------------------------------------------------------------ run #
    def run(self, source: ResolvedComposition | EffectedComposition,
            report: Report | None = None) -> BuildResult:
        composizione, effetti = _sciogli(source)
        if report is None:
            report = composizione.report if composizione.report is not None else Report()
        out = BuildResult(composition=composizione, report=report,
                          effects=[e for e in effetti
                                   if e.stage in STADI_LOCALI + STADI_GLOBALI])

        locali = self._per_nodo(out.effects)
        saltati: set[str] = set()

        for nodo in composizione.walk():
            padre = nodo.link.parent if nodo.link else ""
            if padre and (padre in saltati or padre not in out.nodes):
                # senza il padre non c'e' un socket in cui posarsi
                saltati.add(nodo.id)
                continue
            costruito = self._nodo(nodo, out, locali.get(nodo.id, ()))
            if costruito is None:
                saltati.add(nodo.id)
                continue
            out.nodes[nodo.id] = costruito
            out.order.append(nodo.id)

        out.skipped = sorted(saltati)
        self._globali(out)
        self.budget.report_to(report, composizione.detail_level)
        return out

    # ------------------------------------------------------------- un nodo #
    def _nodo(self, nodo: ResolvedNode, out: BuildResult,
              effetti: Iterable[PlannedEffect]) -> BuiltNode | None:
        pezzo = self._costruisci(nodo, out)
        if pezzo is None:
            return None

        sockets = dict(pezzo.sockets)
        sockets.update(self._layout_sockets(nodo, out))
        self._verifica_socket(nodo, sockets, out)

        costruito = BuiltNode(id=nodo.id, node=nodo, piece=pezzo, sockets=sockets,
                              parent=nodo.link.parent if nodo.link else "",
                              material=nodo.material or pezzo.material or nodo.component.material,
                              metadata={"plugin": nodo.component.plugin,
                                        "component": nodo.component.id,
                                        "path": nodo.path,
                                        "role": nodo.component.role,
                                        "requested": nodo.requested_ref,
                                        "from_plan": nodo.from_plan,
                                        "undeclared_sockets":
                                            self._non_dichiarati(nodo, sockets)})

        costruito.designed = pezzo.mesh

        # le deformazioni locali vengono **prima** della posa dei figli: un
        # figlio va messo dove il socket sta davvero, non dove stava prima che
        # la parte venisse piegata
        for effetto in effetti:
            self._deforma(costruito, effetto, out, locale=True)

        posa = self._posa(nodo, costruito, out)
        if posa is None:
            return None
        costruito.placement = posa

        if nodo.builds_geometry and pezzo.mesh is not None:
            costruito.mesh = _trasforma(pezzo.mesh, posa)
            if not self._paga(costruito, out):
                return None
        return costruito

    def _costruisci(self, nodo: ResolvedNode, out: BuildResult) -> Piece | None:
        ctx = BuildContext(style=out.composition.style,
                           detail_level=out.composition.detail_level,
                           depth=nodo.depth, seed=out.composition.seed,
                           budget=self.budget, path=nodo.path, report=out.report,
                           node=nodo, composition=out.composition,
                           parent_piece=self._pezzo_del_padre(nodo, out))
        try:
            pezzo = nodo.component.build(dict(nodo.values), ctx)
        except Exception as exc:                            # noqa: BLE001
            self._fallito(nodo, "%s: %s" % (type(exc).__name__, exc), out)
            return None
        if pezzo is None:
            self._fallito(nodo, "non ha restituito niente", out)
            return None
        return pezzo

    @staticmethod
    def _layout_sockets(nodo: ResolvedNode, out: BuildResult) -> dict[str, Socket]:
        piano = getattr(out.composition, "layout_plan", None)
        if piano is None:
            return {}
        sockets: dict[str, Socket] = {}
        for placement in piano.by_parent().get(nodo.id, ()):
            if placement.frame is None:
                continue
            sockets[placement.socket] = placement.frame.to_socket(
                capabilities=(), side="", tags=("layout", placement.region))
        return sockets

    def _fallito(self, nodo: ResolvedNode, motivo: str, out: BuildResult) -> None:
        """Un pezzo che non si costruisce: quanto e' grave dipende dall'attacco.

        Un cappello facoltativo che non viene su lascia una testa perfettamente
        valida. Un braccio strutturale che non viene su lascia un modello
        sbagliato, e va detto come errore.
        """
        facoltativo = nodo.link is not None and \
            nodo.component is not None and self._facoltativo(nodo, out)
        messaggio = "'%s' non si e' costruito: %s" % (nodo.ref, motivo)
        if facoltativo:
            out.report.warn("COMPONENT_BUILD_FAILED", messaggio, where=nodo.path,
                            why="facoltativo: il modello resta valido senza")
        else:
            out.report.add("COMPONENT_BUILD_FAILED", messaggio, where=nodo.path,
                           why="fa parte di cio' che l'oggetto e'")

    @staticmethod
    def _facoltativo(nodo: ResolvedNode, out: BuildResult) -> bool:
        piano = out.composition.graph.node(nodo.id)
        attacco = piano.attachment if piano is not None else None
        return bool(attacco is not None and not attacco.structural)

    @staticmethod
    def _pezzo_del_padre(nodo: ResolvedNode, out: BuildResult) -> Piece | None:
        if nodo.link is None:
            return None
        padre = out.nodes.get(nodo.link.parent)
        return padre.piece if padre is not None else None

    # ------------------------------------------------------- socket dichiarati #
    def _verifica_socket(self, nodo: ResolvedNode, sockets: dict[str, Socket],
                         out: BuildResult) -> None:
        """La promessa contro il fatto.

        `Component.mounts` e' una dichiarazione scritta a freddo; `Piece.sockets`
        e' cio' che la costruzione ha davvero prodotto. Fin qui nessuno poteva
        confrontarle: il resolver non aveva il pezzo. Adesso si', e una
        dichiarazione falsa va detta — altrimenti si scopre quando un figlio
        finisce nel posto sbagliato.
        """
        mancanti = [m.socket_id for m in nodo.component.mounts
                    if m.socket_id and m.socket_id not in sockets]
        if not mancanti:
            return
        messaggio = "'%s' dichiara innesti che non costruisce: %s" \
            % (nodo.ref, ", ".join(sorted(mancanti)))
        perche = "costruiti: %s" % (", ".join(sorted(sockets)) or "nessuno")
        if self.strict_sockets:
            out.report.add("DECLARED_SOCKET_MISSING", messaggio, where=nodo.path,
                           why=perche, alternatives=sorted(sockets)[:6])
        else:
            out.report.warn("DECLARED_SOCKET_MISSING", messaggio, where=nodo.path,
                            why=perche, alternatives=sorted(sockets)[:6])

    @staticmethod
    def _non_dichiarati(nodo: ResolvedNode, sockets: dict[str, Socket]) -> list[str]:
        """Socket prodotti e non dichiarati. Non sono un errore.

        Un plugin puo' generarli in base ai parametri — quattro zampe o sei, a
        seconda del numero chiesto — e obbligarlo a dichiararli tutti a freddo
        vorrebbe dire vietare quel genere di componenti. Si annotano e basta.
        """
        dichiarati = {m.socket_id for m in nodo.component.mounts if m.socket_id}
        return sorted(set(sockets) - dichiarati)

    # ------------------------------------------------------------------ posa #
    def _posa(self, nodo: ResolvedNode, costruito: BuiltNode,
              out: BuildResult) -> Placement | None:
        if nodo.link is None:
            return Placement()

        padre = out.nodes.get(nodo.link.parent)
        if padre is None:
            return None

        innesto = self._socket_del_padre(nodo, padre, out)
        if innesto is None:
            return None
        proprio = self._socket_proprio(nodo, costruito, out)

        modo = nodo.link.scale_mode
        scala = float(getattr(nodo.link, "layout_scale", 1.0) or 1.0)
        if modo == SCALE_MODE_FIT_REPLACED:
            # la scala si calcola qui, dove la geometria esiste: quanto e' lungo
            # questo pezzo contro quanto era lungo quello che sostituisce
            modo = "none"
            scala *= self._fattore(costruito, proprio, nodo.link.target_size, out)

        return attach(padre.placement, innesto, proprio, scale_mode=modo,
                      scale=scala, insert=nodo.link.insert, roll=nodo.link.roll)

    @staticmethod
    def _fattore(costruito: BuiltNode, proprio: Socket, bersaglio: float,
                 out: BuildResult) -> float:
        """Quanto scalare per stare grande come il pezzo sostituito."""
        mesh = costruito.piece.mesh
        if bersaglio <= 0.0 or mesh is None or len(mesh.vertices) == 0:
            return 1.0
        crescita = -proprio.direction
        proiezione = np.asarray(mesh.vertices, dtype=float) @ crescita
        lunghezza = float(proiezione.max() - proiezione.min())
        if lunghezza < 1e-9:
            return 1.0
        fattore = bersaglio / lunghezza
        out.report.note("SCALED_TO_REPLACED",
                        "'%s' portato a %.3f come cio' che sostituisce (x%.2f)"
                        % (costruito.ref, bersaglio, fattore),
                        where=costruito.node.path)
        return fattore

    def _socket_del_padre(self, nodo: ResolvedNode, padre: BuiltNode,
                          out: BuildResult) -> Socket | None:
        """L'innesto vero, cercato prima per nome e poi per capability.

        La ricerca per capability usa la stessa scala del resolver: `Mount` e
        `Socket` rispondono alle stesse domande apposta, cosi' la decisione
        presa a freddo e quella presa a caldo non possono divergere.
        """
        atteso = nodo.link.parent_socket
        if atteso and atteso in padre.sockets:
            return padre.sockets[atteso]

        requisito = Requirement(capability=nodo.link.capability,
                                socket_id=atteso, side=nodo.link.side,
                                allow_fallback=True)
        trovato, punteggio = best_match(requisito, padre.sockets.values())
        if trovato is not None and punteggio > 0:
            if atteso:
                out.report.note("PARENT_SOCKET_RENAMED",
                                "'%s' non ha '%s': si usa '%s'"
                                % (padre.ref, atteso, trovato.name),
                                where=nodo.path,
                                why="stessa capability, nome diverso")
            return trovato

        facoltativo = self._facoltativo(nodo, out)
        messaggio = "'%s' non offre un innesto per %s" \
            % (padre.ref, nodo.link.capability or atteso or "questo attacco")
        perche = "socket costruiti: %s" % (", ".join(sorted(padre.sockets))
                                           or "nessuno")
        if facoltativo:
            out.report.warn("PARENT_SOCKET_NOT_FOUND", messaggio, where=nodo.path,
                            why=perche)
        else:
            out.report.add("PARENT_SOCKET_NOT_FOUND", messaggio, where=nodo.path,
                           why=perche, alternatives=sorted(padre.sockets)[:6])
        return None

    def _socket_proprio(self, nodo: ResolvedNode, costruito: BuiltNode,
                        out: BuildResult) -> Socket:
        """Il socket con cui il figlio si posa. Se manca, non si cade.

        Il ripiego e' la base della convenzione — origine, verso -X — perche' e'
        cio' che un componente che rispetta il contratto ha comunque. Vale come
        diagnosi, non come silenzio: un pezzo posato su un socket inventato si
        vede subito.
        """
        nome = nodo.link.own_socket
        if nome in costruito.sockets:
            return costruito.sockets[nome]

        out.report.warn("OWN_SOCKET_NOT_FOUND",
                        "'%s' non ha il socket '%s' con cui doveva posarsi"
                        % (nodo.ref, nome), where=nodo.path,
                        why="socket costruiti: %s" % (", ".join(
                            sorted(costruito.sockets)) or "nessuno"),
                        alternatives=sorted(costruito.sockets)[:6])
        return Socket(name=nome, position=np.zeros(3),
                      direction=np.array([-1.0, 0.0, 0.0]),
                      radius=_raggio(costruito.piece))

    # --------------------------------------------------------------- effetti #
    @staticmethod
    def _per_nodo(effetti: Iterable[PlannedEffect]) -> dict[str, list[PlannedEffect]]:
        """Gli effetti locali, gia' ordinati, indicizzati per bersaglio.

        Lo scope e' stato risolto dalla pipeline: qui non si cerca piu' niente,
        si applica. Rifare la risoluzione vorrebbe dire due posti in cui puo'
        rispondere diversamente.
        """
        fuori: dict[str, list[PlannedEffect]] = {}
        for effetto in effetti:
            if effetto.stage not in STADI_LOCALI:
                continue
            for id in effetto.targets:
                fuori.setdefault(id, []).append(effetto)
        return fuori

    def _deforma(self, costruito: BuiltNode, effetto: PlannedEffect,
                 out: BuildResult, locale: bool, bounds=None,
                 ancoraggio=None) -> None:
        """Applica una deformazione a un pezzo, **socket compresi**.

        E' il punto in cui questo progetto ha gia' sbagliato una volta: se si
        piega la mesh e si lasciano i socket dove stavano, i figli si attaccano
        nel vuoto. Con una mappa di punti il problema non esiste — la stessa
        funzione muove i vertici e i socket, e non possono separarsi.
        """
        pezzo = costruito.piece if locale else None
        mesh = pezzo.mesh if locale else costruito.mesh
        perno, estremo = ancoraggio or (None, None)
        ctx = EffectContext(amount=effetto.amount, params=effetto.params,
                            node=costruito.node, composition=out.composition,
                            bounds=bounds, report=out.report,
                            pivot=perno, reach=estremo)
        try:
            if mesh is not None:
                nuova = effetto.spec.transform(mesh, ctx)
                if nuova is not None:
                    if locale:
                        pezzo.mesh = nuova
                    else:
                        costruito.mesh = nuova
            if effetto.spec.moves_points:
                self._muovi_socket(costruito, effetto, ctx, locale)
            costruito.deformed = True
        except Exception as exc:                            # noqa: BLE001
            out.report.warn("EFFECT_APPLICATION_FAILED",
                            "'%s' non si e' potuto applicare: %s"
                            % (effetto.id, exc), where=costruito.node.path,
                            why="il pezzo resta come era")

    @staticmethod
    def _muovi_socket(costruito: BuiltNode, effetto: PlannedEffect,
                      ctx: EffectContext, locale: bool) -> None:
        """Porta i socket dove la stessa mappa ha portato i vertici.

        Il verso si ricava mandando anche un punto poco piu' avanti e uno poco
        piu' in alto: e' l'unico modo di sapere come una deformazione qualunque
        ha girato un innesto, e non richiede che l'effetto racconti niente di
        se'.
        """
        partenza = costruito.sockets if locale else             (costruito.world_sockets or {n: costruito.placement.socket_world(s)
                                         for n, s in costruito.sockets.items()})
        if not partenza:
            return
        nomi = sorted(partenza)
        passo = _passo(costruito)

        posizioni = np.array([partenza[n].position for n in nomi], dtype=float)
        avanti = posizioni + np.array([partenza[n].direction for n in nomi]) * passo
        alto = posizioni + np.array([partenza[n].up for n in nomi]) * passo

        mosse = effetto.spec.map_points(posizioni, ctx)
        mosse_avanti = effetto.spec.map_points(avanti, ctx)
        mosse_alto = effetto.spec.map_points(alto, ctx)

        destinazione = costruito.sockets if locale else costruito.world_sockets
        for indice, nome in enumerate(nomi):
            vecchio = partenza[nome]
            destinazione[nome] = Socket(
                name=vecchio.name, position=mosse[indice],
                direction=mosse_avanti[indice] - mosse[indice],
                up=mosse_alto[indice] - mosse[indice],
                radius=vecchio.radius, capabilities=vecchio.capabilities,
                side=vecchio.side, tags=vecchio.tags)

    def _globali(self, out: BuildResult) -> None:
        """Le deformazioni del modello intero, dopo che tutto e' assemblato.

        Il riferimento e' la misura **del modello**, non del singolo pezzo:
        un'esagerazione prospettica calcolata sui limiti di una mano
        deformerebbe la mano invece del corpo.
        """
        globali = [e for e in out.effects if e.stage in STADI_GLOBALI]
        if not globali:
            return
        for effetto in globali:
            limiti = out.bounds
            if limiti is None:
                continue
            ancoraggi = self._ancoraggi(effetto, out)
            for id in effetto.targets:
                costruito = out.nodes.get(id)
                if costruito is None:
                    continue
                # anche un contenitore senza geometria va deformato: i suoi
                # socket sono il riferimento dei figli, e se restano indietro
                # il modello risulta staccato dove non lo e'
                self._deforma(costruito, effetto, out, locale=False, bounds=limiti,
                              ancoraggio=ancoraggi.get(id))

    @staticmethod
    def _ancoraggi(effetto: PlannedEffect, out: BuildResult) -> dict:
        """Per ogni pezzo colpito, dove il suo gruppo e' appeso e fin dove arriva.

        Un effetto puo' colpire piu' gruppi staccati: `role:arm` prende tutti e
        due i braccia. Ruotarli attorno a un perno solo — quello del primo —
        farebbe volare via il secondo, e sarebbe una di quelle cose che si
        vedono solo guardando il modello. Quindi i bersagli si raccolgono in
        **sottoalberi massimi**: chi ha il padre fra i bersagli sta nel gruppo
        del padre, chi non ce l'ha apre un gruppo nuovo e porta il perno.

        Il perno e' l'innesto da cui il gruppo pende — la spalla, non
        l'origine. Se il gruppo non pende da niente (e' la radice) si usa il
        centro dei suoi limiti: e' l'unica risposta onesta, e una rotazione
        attorno al proprio centro e' comunque cio' che si vuole li'.
        """
        bersagli = [id for id in out.order
                    if id in effetto.targets and id in out.nodes]
        if not bersagli:
            return {}
        insieme = set(bersagli)

        capogruppo: dict[str, str] = {}
        for id in bersagli:
            padre = out.nodes[id].parent
            capogruppo[id] = capogruppo.get(padre, id) if padre in insieme else id

        membri: dict[str, list[str]] = {}
        for id in bersagli:
            membri.setdefault(capogruppo[id], []).append(id)

        fuori: dict[str, tuple] = {}
        for capo, gruppo in membri.items():
            punti = [np.asarray(out.nodes[i].mesh.vertices, dtype=float)
                     for i in gruppo
                     if out.nodes[i].mesh is not None
                     and len(out.nodes[i].mesh.vertices)]
            tutti = np.vstack(punti) if punti else None
            perno = _perno(out.nodes[capo], out)
            if perno is None:
                perno = (tutti.min(axis=0) + tutti.max(axis=0)) * 0.5 \
                    if tutti is not None else np.zeros(3)
            if tutti is None:
                estremo = perno
            else:
                distanze = np.linalg.norm(tutti - perno, axis=1)
                estremo = tutti[int(np.argmax(distanze))]
            for id in gruppo:
                fuori[id] = (np.asarray(perno, dtype=float),
                             np.asarray(estremo, dtype=float))
        return fuori

    # ------------------------------------------------------------- budget #
    def _paga(self, costruito: BuiltNode, out: BuildResult) -> bool:
        """I triangoli sono l'unico budget che solo la geometria conosce.

        Superarlo non autorizza a rompere una mesh: si riferisce, e da li' in
        poi si lascia fuori cio' che era dichiarato facoltativo. Il modello
        resta quello che e', con meno cose sopra.
        """
        quanti = costruito.triangles
        if self.budget.spend(TRIANGLES, quanti, where=costruito.node.path):
            return True
        if self._facoltativo(costruito.node, out):
            out.report.note("BUDGET_EXCEEDED",
                            "'%s' lasciato fuori: %d triangoli di troppo"
                            % (costruito.ref, quanti), where=costruito.node.path,
                            why="facoltativo, e il budget e' finito")
            return False
        return True


# --------------------------------------------------------------------------- #
# Utilita'
# --------------------------------------------------------------------------- #
def _sciogli(source) -> tuple[ResolvedComposition, list[PlannedEffect]]:
    """Accetta una composizione risolta o una con gli effetti gia' passati."""
    if isinstance(source, EffectedComposition):
        return source.composition, list(source.planned)
    return source, []


def _trasforma(mesh: trimesh.Trimesh, posa: Placement) -> trimesh.Trimesh:
    fuori = mesh.copy()
    fuori.apply_transform(posa.matrix())
    return fuori


def _perno(costruito: BuiltNode, out: BuildResult):
    """La posizione, nel modello, dell'innesto da cui un pezzo pende.

    Si guarda il socket del **padre**, non quello proprio: e' il padre a dire
    dove il figlio e' agganciato, e dopo una deformazione e' il suo socket
    aggiornato a dire la verita'.
    """
    collegamento = costruito.node.link
    if collegamento is None:
        return None
    padre = out.nodes.get(collegamento.parent)
    if padre is None:
        return None
    nome = collegamento.parent_socket
    innesto = padre.socket_world(nome) if nome else None
    if innesto is None:
        for altro in sorted(padre.sockets):
            innesto = padre.socket_world(altro)
            break
    return None if innesto is None else np.asarray(innesto.position, dtype=float)


def _passo(costruito: BuiltNode) -> float:
    """Quanto lontano mandare il punto che serve a ricavare un verso."""
    mesh = costruito.piece.mesh
    if mesh is None or len(mesh.vertices) == 0:
        return 1e-4
    return max(float(np.max(mesh.bounds[1] - mesh.bounds[0])) * 1e-3, 1e-6)


def _raggio(pezzo: Piece) -> float:
    if pezzo.mesh is None or len(pezzo.mesh.vertices) == 0:
        return 0.1
    misura = pezzo.mesh.bounds[1] - pezzo.mesh.bounds[0]
    return max(float(np.min(misura)) * 0.5, 1e-3)


def build(source: ResolvedComposition | EffectedComposition, *,
          budget: Budget | None = None, strict_sockets: bool = False,
          report: Report | None = None) -> BuildResult:
    """Da un piano risolto (con o senza effetti) alla geometria."""
    return Builder(budget=budget, strict_sockets=strict_sockets).run(source, report)
