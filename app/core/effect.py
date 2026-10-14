"""Gli effetti: cosa cambia rispetto a quello che i componenti direbbero da soli.

    registry     cosa esiste
    graph        cosa voglio
    resolver     quali componenti uso, collegati come
    effetti      cosa cambio di quello che ho scelto     <- questo file
    builder      dove finisce ogni vertice

Un effetto **non crea un componente**. Cambia i parametri di cio' che verra'
costruito, oppure la geometria di cio' che e' stato costruito, oppure la posa
finale — e in quale dei tre modi lo faccia deve essere dichiarato, non dedotto.

## Sei stadi, e l'ordine e' il contratto

    structural   il grafo, prima che esista geometria
    proportion   i parametri, prima del build
    local        i vertici di una parte
    global       i vertici del modello
    style        l'esagerazione del linguaggio visivo
    final        posa, centratura, appoggio

La distinzione fra `proportion` e i quattro stadi geometrici e' quella che
conta: una proporzione cambia **cosa si costruisce**, una deformazione cambia
**cio' che e' costruito**. Allungare una gamba cambiando la sua lunghezza da'
una gamba piu' lunga; allungarla stirando i vertici da' una gamba deformata.

## Dove finisce questo passo

I due stadi che vengono prima della geometria si applicano **qui**: i parametri
esistono gia'. I quattro geometrici si **programmano**: la mesh non c'e'
ancora, e inventarla per poterla deformare sarebbe il modo piu' rapido di
sbagliare due volte. Il builder ricevera' un elenco ordinato di operazioni con
i bersagli gia' risolti.

## Effetto non e' stile

Lo stile e' il linguaggio visivo di tutto il modello ed e' scelto una volta;
l'effetto e' una modifica intenzionale che qualcuno ha chiesto. `low_poly` non
e' un effetto e `perspective_exaggeration` non e' uno stile. Che un giorno un
`StyleProfile` possa portarsi dietro delle esagerazioni non cambia questo: sono
due sistemi, e mescolarli vorrebbe dire non sapere piu' chi ha deciso cosa.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.core.errors import Report
from app.core.graph import FROM_DERIVED, FROM_EFFECT, FROM_TRAIT, EffectRequest
from app.core.params import ExpressionError, evaluate, numeric
from app.core.params import resolve as resolve_params
from app.core.resolved import ResolvedComposition, ResolvedNode, ResolvedValue
from app.core.vocabulary import (SCOPE_GROUP, SCOPE_MODEL, SCOPE_PART,
                                 SCOPE_ROLE, SCOPE_SUBTREE, STAGES,
                                 STAGES_BEFORE_GEOMETRY, EffectSpec)

SEPARATOR = ":"


# --------------------------------------------------------------------------- #
# Ambito
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Scope:
    """Su che cosa agisce un effetto. Cinque modi, nessuna categoria.

    `role:leg` funziona se il grafo contiene componenti che dichiarano quel
    ruolo, e non funziona altrimenti: l'effetto non sa che cosa sia una gamba,
    sa cercare un'etichetta.
    """

    kind: str = SCOPE_MODEL
    value: str = ""

    @classmethod
    def parse(cls, text: str, host: str = "") -> "Scope":
        """`model`, `part:testa`, `subtree:corpo`, `group:metallo`, `role:leg`.

        Un ambito che nomina un nodo senza dirne l'id si riferisce al nodo su
        cui l'effetto e' stato chiesto: `part:` da solo vuol dire "questo".
        """
        testo = (text or SCOPE_MODEL).strip()
        kind, _, value = testo.partition(SEPARATOR)
        kind = kind.strip() or SCOPE_MODEL
        value = value.strip()
        if kind in (SCOPE_PART, SCOPE_SUBTREE) and not value:
            value = host
        return cls(kind=kind, value=value)

    @property
    def names_a_node(self) -> bool:
        return self.kind in (SCOPE_PART, SCOPE_SUBTREE)

    def targets(self, composition: ResolvedComposition) -> list[ResolvedNode]:
        if self.kind == SCOPE_MODEL:
            return list(composition.walk())
        if self.kind == SCOPE_PART:
            nodo = composition.node(self.value)
            return [nodo] if nodo is not None else []
        if self.kind == SCOPE_SUBTREE:
            return self._subtree(composition, self.value)
        if self.kind == SCOPE_GROUP:
            return [n for n in composition.walk()
                    if self.value in (n.tags | n.component.tags)]
        if self.kind == SCOPE_ROLE:
            return [n for n in composition.walk() if n.component.role == self.value]
        return []

    @staticmethod
    def _subtree(composition: ResolvedComposition, id: str) -> list[ResolvedNode]:
        radice = composition.node(id)
        if radice is None:
            return []
        fuori, pila = [], [radice]
        while pila:
            nodo = pila.pop(0)
            fuori.append(nodo)
            pila.extend(composition.children(nodo.id))
        return fuori

    def describe(self) -> str:
        return self.kind if not self.value else "%s:%s" % (self.kind, self.value)


# --------------------------------------------------------------------------- #
# Un effetto messo in programma
# --------------------------------------------------------------------------- #
@dataclass
class PlannedEffect:
    """Un effetto validato, con i suoi bersagli gia' risolti.

    Per gli stadi che vengono prima della geometria e' un resoconto di cio' che
    e' stato fatto; per gli altri e' un'istruzione precisa per il builder, che
    non dovra' ne' cercare i bersagli ne' validare i numeri.
    """

    spec: EffectSpec
    scope: Scope
    amount: float = 1.0
    params: dict[str, Any] = field(default_factory=dict)
    targets: tuple[str, ...] = ()
    host: str = ""                       # il nodo su cui era stato chiesto
    changed: tuple[str, ...] = ()        # nodi effettivamente modificati

    @property
    def id(self) -> str:
        return self.spec.id

    @property
    def stage(self) -> str:
        return self.spec.stage

    @property
    def priority(self) -> int:
        return self.spec.priority

    def describe(self) -> str:
        return "%s [%s] su %s (%.2f) -> %d bersagli" % (
            self.id, self.stage, self.scope.describe(), self.amount,
            len(self.targets))


@dataclass
class EffectedComposition:
    """La composizione dopo gli effetti: parametri cambiati, geometria in coda.

    La composizione risolta resta accessibile e non viene sostituita — stessa
    regola del piano rispetto al risolto: per capire perche' un modello e'
    venuto cosi', servono tutti e tre gli strati.
    """

    composition: ResolvedComposition
    applied: list[PlannedEffect] = field(default_factory=list)   # gia' applicati
    planned: list[PlannedEffect] = field(default_factory=list)   # per il builder
    report: Report = field(default_factory=Report)

    @property
    def ok(self) -> bool:
        return self.report.ok

    @property
    def style(self) -> str:
        return self.composition.style

    def node(self, id: str) -> ResolvedNode | None:
        return self.composition.node(id)

    def walk(self):
        return self.composition.walk()

    def refs(self) -> list[str]:
        return self.composition.refs()

    def stage(self, name: str) -> list[PlannedEffect]:
        return [e for e in self.planned if e.stage == name]

    def for_node(self, id: str) -> list[PlannedEffect]:
        return [e for e in self.planned if id in e.targets]

    def describe(self) -> str:
        righe = [self.composition.describe()]
        for effetto in self.applied:
            righe.append("applicato: %s" % effetto.describe())
        for effetto in self.planned:
            righe.append("in programma: %s" % effetto.describe())
        return "\n".join(righe)

    def to_dict(self) -> dict:
        fuori = self.composition.to_dict()
        fuori["effects"] = [
            {"id": e.id, "stage": e.stage, "scope": e.scope.describe(),
             "amount": e.amount, "params": dict(e.params),
             "targets": list(e.targets),
             "state": "applicato" if e in self.applied else "in programma"}
            for e in self.applied + self.planned]
        return fuori


# --------------------------------------------------------------------------- #
# Contesto passato a una deformazione
# --------------------------------------------------------------------------- #
@dataclass
class EffectContext:
    """Quello che una deformazione riceve, oltre alla mesh.

    Il core dichiara **cosa arriva**, non come si usa: un plugin puo' spostare
    vertici, ricostruire con il kernel, passare per un campo implicito o fare
    qualcosa che ancora non esiste. Il contratto e' la firma e il tipo del
    risultato:

        stadi geometrici        apply(mesh, ctx) -> mesh
        stadi prima della       apply(composition, ctx) -> None
        geometria

    Due firme perche' sono due cose diverse: un effetto strutturale lavora sul
    grafo risolto, che a quel punto e' l'unica cosa che esiste; una
    deformazione lavora su una mesh, che a quel punto e' l'unica cosa che
    conta. Un effetto di **proporzione** non ha bisogno di nessuna delle due:
    dichiara le sue `ParamRule` e non scrive codice.
    """

    amount: float = 1.0
    params: dict[str, Any] = field(default_factory=dict)
    node: ResolvedNode | None = None
    composition: ResolvedComposition | None = None
    bounds: Any = None
    report: Report | None = None
    # Dove il gruppo colpito e' **appeso**, e fin dove arriva. Due punti, in
    # coordinate del modello, che il builder calcola una volta per effetto e
    # per gruppo: il primo e' l'innesto da cui il gruppo pende, il secondo il
    # suo punto piu' lontano da li'.
    #
    # Servono a una **posa**, e solo a quella. Ruotare un braccio verso il
    # basso vuol dire ruotarlo attorno alla spalla: senza il perno, una
    # rotazione attorno all'origine lo stacca dal corpo, e un effetto che
    # ricavasse il perno dai propri punti ne troverebbe uno diverso per ogni
    # pezzo del braccio. Non sono un sistema di pose: sono i due numeri che
    # solo chi ha assemblato il modello puo' conoscere.
    pivot: Any = None
    reach: Any = None

    def get(self, name: str, default: Any = None) -> Any:
        return self.params.get(name, default)


# --------------------------------------------------------------------------- #
# La pipeline
# --------------------------------------------------------------------------- #
class EffectPipeline:
    """Valida, ordina, applica cio' che si puo' applicare, programma il resto."""

    def __init__(self, registry) -> None:
        self.registry = registry

    # ------------------------------------------------------------------ run #
    def run(self, composition: ResolvedComposition,
            report: Report | None = None) -> EffectedComposition:
        # `or` non basta: un `Report` vuoto e' falso, e le diagnosi degli
        # effetti finirebbero in un referto separato da quello della risoluzione
        if report is None:
            report = composition.report if composition.report is not None else Report()
        out = EffectedComposition(composition=composition, report=report)

        richiesti = self._validate(composition, report)
        richiesti = self._resolve_conflicts(richiesti, report)
        richiesti.sort(key=self._ordine)

        for effetto in richiesti:
            if effetto.stage in STAGES_BEFORE_GEOMETRY:
                self._apply_now(effetto, composition, report)
                out.applied.append(effetto)
            else:
                out.planned.append(effetto)

        if out.applied:
            self._rederive(composition, report)
        return out

    # ------------------------------------------------------- ricalcolo #
    @staticmethod
    def _rederive(composition: ResolvedComposition, report: Report) -> None:
        """Ricalcola i parametri derivati dopo che gli effetti hanno cambiato i loro.

        Serve perche' `porta.altezza = parent.altezza * 0.5` era stata calcolata
        **prima** che un effetto alzasse la casa: senza questo passaggio la porta
        resta della misura di prima, e la casa cresce intorno a lei. Non e' un
        errore che si vede in una diagnosi — si vede nel modello, tardi.

        Un parametro che un effetto ha cambiato **non** si ricalcola: la
        decisione piu' recente vince, altrimenti la formula cancellerebbe la
        richiesta di chi ha chiesto l'effetto.
        """
        for nodo in composition.walk():
            derivati = {n: s for n, s in nodo.component.params.items()
                        if s.is_derived and nodo.source(n) not in (FROM_EFFECT, FROM_TRAIT)}
            if not derivati:
                continue
            padre = composition.node(nodo.link.parent) if nodo.link else None
            radice = composition.node(composition.root)
            ambiti = {"self": numeric(nodo.values),
                      "parent": numeric(padre.values) if padre else {},
                      "root": numeric(radice.values) if radice else {}}
            for nome, spec in derivati.items():
                try:
                    nuovo = spec.coerce(evaluate(spec.derived, ambiti["self"], ambiti))
                except ExpressionError:
                    continue                      # gia' riferito dal resolver
                prima = nodo.values.get(nome)
                if nuovo == prima:
                    continue
                nodo.values[nome] = nuovo
                ambiti["self"] = numeric(nodo.values)
                nodo.sources[nome] = ResolvedValue(nuovo, FROM_DERIVED,
                                                   expression=spec.derived,
                                                   previous=prima)

    @staticmethod
    def _ordine(effetto: PlannedEffect) -> tuple:
        """Stadio, poi priorita', poi id. Mai l'ordine in cui sono arrivati.

        Dipendere dall'ordine di un dizionario o di un JSON vorrebbe dire che
        lo stesso piano, riscritto con le stesse cose in ordine diverso, da' un
        modello diverso.
        """
        stadio = STAGES.index(effetto.stage) if effetto.stage in STAGES else len(STAGES)
        return (stadio, -effetto.priority, effetto.id)

    # ------------------------------------------------------------ validazione #
    def _validate(self, composition: ResolvedComposition,
                  report: Report) -> list[PlannedEffect]:
        fuori: list[PlannedEffect] = []
        richieste = list(composition.effects) + self._from_params(composition, report)
        for host, richiesta in richieste:
            effetto = self._one(host, richiesta, composition, report)
            if effetto is not None:
                fuori.append(effetto)
        return fuori

    @staticmethod
    def _from_params(composition: ResolvedComposition,
                     report: Report) -> list[tuple[str, EffectRequest]]:
        """Gli effetti che un **parametro** chiede, tradotti in richieste normali.

        E' tutto quello che `ParamEffect` aggiunge al sistema: una traduzione.
        Da qui in poi una piega chiesta da `curve = 0.8` e una piega scritta nel
        piano sono la stessa cosa, e passano dalla stessa validazione — effetto
        inesistente, ambito non dichiarato, valore fuori intervallo.

        Non si scrive in `composition.effects`: la pipeline puo' girare due
        volte sulla stessa composizione, e un elenco che cresce a ogni giro
        darebbe due pieghe dove ne era stata chiesta una.
        """
        fuori: list[tuple[str, EffectRequest]] = []
        for nodo in composition.walk():
            legami = tuple(getattr(nodo.component, "param_effects", ()) or ())
            if not legami:
                continue
            gia_nel_piano = {r.type for r in nodo.effects}
            for legame in legami:
                spec = nodo.component.params.get(legame.param)
                if spec is None:
                    report.warn("PARAM_EFFECT_PARAM_MISSING",
                                "'%s' pilota '%s' ma non e' un parametro di '%s'"
                                % (legame.param, legame.type, nodo.component.id),
                                where=nodo.path,
                                alternatives=sorted(nodo.component.params)[:6])
                    continue
                # Il piano vince sulla dichiarazione del componente, come per i
                # parametri e per i figli: se qualcuno ha chiesto quell'effetto
                # su questo nodo, il legame non ne aggiunge un secondo.
                if legame.type in gia_nel_piano:
                    report.note("PARAM_EFFECT_SUPERSEDED",
                                "'%s' e' gia' chiesto sul nodo: '%s' non lo raddoppia"
                                % (legame.type, legame.param), where=nodo.path)
                    continue
                valore = nodo.values.get(legame.param, spec.default)
                if not legame.wanted(valore):
                    continue
                scope = Scope.parse(legame.scope, host=nodo.id).describe()
                if legame.drives_amount:
                    richiesta = EffectRequest(type=legame.type, scope=scope,
                                              amount=float(valore))
                else:
                    richiesta = EffectRequest(type=legame.type, scope=scope,
                                              params={legame.parameter: valore})
                report.note("PARAM_EFFECT_REQUESTED",
                            "'%s' = %s chiede '%s.%s'"
                            % (legame.param, valore, legame.type, legame.parameter),
                            where=nodo.path, why="dichiarato da '%s'" % nodo.component.id)
                fuori.append((nodo.id, richiesta))
        return fuori

    def _one(self, host: str, richiesta: EffectRequest,
             composition: ResolvedComposition,
             report: Report) -> PlannedEffect | None:
        spec = self.registry.effect(richiesta.type)
        if spec is None:
            report.add("EFFECT_NOT_FOUND", "effetto sconosciuto: '%s'" % richiesta.type,
                       where=host,
                       why="nessun plugin installato lo dichiara",
                       alternatives=[e.id for e in self.registry.effects()][:6])
            return None

        if spec.stage not in STAGES:
            report.add("EFFECT_INCOMPATIBLE",
                       "'%s' non dichiara uno stadio valido" % spec.id, where=host,
                       why="stadio dichiarato: %r" % spec.stage,
                       alternatives=list(STAGES))
            return None

        scope = Scope.parse(richiesta.scope, host=host)
        if not spec.fits_scope(scope.kind):
            report.add("EFFECT_INCOMPATIBLE",
                       "'%s' non si applica a un ambito '%s'" % (spec.id, scope.kind),
                       where=host,
                       why="dichiara: %s" % ", ".join(spec.scopes),
                       alternatives=list(spec.scopes))
            return None

        if scope.names_a_node and composition.node(scope.value) is None:
            report.add("EFFECT_TARGET_NOT_FOUND",
                       "'%s' punta a un nodo che non c'e': '%s'"
                       % (spec.id, scope.value), where=host,
                       alternatives=[n.id for n in composition.walk()][:6])
            return None

        bersagli = scope.targets(composition)
        if not bersagli:
            report.warn("EFFECT_SCOPE_EMPTY",
                        "'%s' non trova niente su cui agire" % spec.id, where=host,
                        why="ambito %s" % scope.describe())
            return None

        amount = self._amount(spec, richiesta, report, host)
        params = resolve_params(spec.params, richiesta.params, report=report,
                                where="%s@%s" % (spec.id, host))
        return PlannedEffect(spec=spec, scope=scope, amount=amount, params=params,
                             targets=tuple(n.id for n in bersagli), host=host)

    @staticmethod
    def _amount(spec: EffectSpec, richiesta: EffectRequest, report: Report,
                host: str) -> float:
        chiesto = float(richiesta.amount)
        valore = float(spec.amount.coerce(chiesto))
        if abs(valore - chiesto) > 1e-9:
            report.warn("EFFECT_OUT_OF_RANGE",
                        "'%s': intensita' %s portata a %s"
                        % (spec.id, chiesto, valore), where=host,
                        why="l'intervallo dichiarato e' %s..%s"
                            % (spec.amount.min, spec.amount.max))
        return valore

    @staticmethod
    def _resolve_conflicts(effetti: list[PlannedEffect],
                           report: Report) -> list[PlannedEffect]:
        """Due effetti che si contraddicono si scartano **entrambi**.

        Tenerne uno vorrebbe dire scegliere al posto di chi ha scritto il
        piano, e la scelta sarebbe arbitraria: nessuno dei due e' piu' voluto
        dell'altro. Meglio dire che la richiesta si contraddice.
        """
        in_conflitto: set[int] = set()
        for i, uno in enumerate(effetti):
            for j, altro in enumerate(effetti):
                if j <= i or not uno.spec.conflicts_with(altro.spec):
                    continue
                in_conflitto.update((i, j))
                report.add("EFFECT_CONFLICT",
                           "'%s' e '%s' non possono stare insieme"
                           % (uno.id, altro.id), where=uno.host,
                           why="dichiarati in conflitto: nessuno dei due si applica",
                           alternatives=[uno.id, altro.id])
        return [e for i, e in enumerate(effetti) if i not in in_conflitto]

    # ------------------------------------------------- effetti di parametri #
    def _apply_now(self, effetto: PlannedEffect, composition: ResolvedComposition,
                   report: Report) -> None:
        if effetto.spec.touches_parameters:
            self._apply_params(effetto, composition, report)
            return
        chiamata = effetto.spec.apply
        if chiamata is None:
            report.note("EFFECT_SCOPE_EMPTY",
                        "'%s' non cambia niente" % effetto.id, where=effetto.host,
                        why="non dichiara parametri da cambiare ne' una funzione")
            return
        try:
            chiamata(composition, EffectContext(
                amount=effetto.amount, params=effetto.params,
                composition=composition, report=report))
        except Exception as exc:                              # noqa: BLE001
            self._failed(effetto, exc, report)

    def _apply_params(self, effetto: PlannedEffect,
                      composition: ResolvedComposition, report: Report) -> None:
        """Cambia i parametri dei bersagli, **una volta sola per lineage**.

        E' la regola che questo progetto ha imparato rompendo un modello: un
        braccio e il suo avambraccio hanno lo stesso ruolo, e accorciarli
        entrambi accorcia l'avambraccio dentro un braccio gia' accorciato. Il
        risultato non e' "piu' corto", e' rotto. Quindi: fra due nodi con lo
        stesso ruolo sulla stessa discendenza, cambia solo il piu' alto.
        """
        toccati: list[str] = []
        ruoli_fatti: set[tuple[str, str]] = set()      # (id del nodo, ruolo)

        for id in effetto.targets:
            nodo = composition.node(id)
            if nodo is None:
                continue
            ruolo = nodo.component.role
            if ruolo and self._antenato_gia_fatto(nodo, ruolo, composition,
                                                  ruoli_fatti):
                report.note("EFFECT_SKIPPED_IN_LINEAGE",
                            "'%s' non si riapplica dentro '%s'" % (effetto.id, ruolo),
                            where=nodo.path,
                            why="un antenato con lo stesso ruolo l'ha gia' ricevuto")
                continue
            if self._change_node(effetto, nodo, composition, report):
                toccati.append(id)
                if ruolo:
                    ruoli_fatti.add((nodo.id, ruolo))
        effetto.changed = tuple(toccati)

    @staticmethod
    def _antenato_gia_fatto(nodo: ResolvedNode, ruolo: str,
                            composition: ResolvedComposition,
                            fatti: set[tuple[str, str]]) -> bool:
        corrente = nodo
        while corrente is not None and corrente.link is not None:
            corrente = composition.node(corrente.link.parent)
            if corrente is None:
                return False
            if (corrente.id, ruolo) in fatti:
                return True
        return False

    def _change_node(self, effetto: PlannedEffect, nodo: ResolvedNode,
                     composition: ResolvedComposition, report: Report) -> bool:
        schema = nodo.component.params
        cambiato = False
        for regola in effetto.spec.changes:
            if not regola.wants_node(nodo.component):
                continue
            for nome, spec in sorted(schema.items()):
                if not regola.wants_param(nome, spec):
                    continue
                if self._change_param(effetto, regola, nodo, nome, spec, report):
                    cambiato = True
        return cambiato

    def _change_param(self, effetto: PlannedEffect, regola, nodo: ResolvedNode,
                      nome: str, spec, report: Report) -> bool:
        prima = nodo.values.get(nome)
        if not isinstance(prima, (int, float)) or isinstance(prima, bool):
            return False
        variabili = numeric(nodo.values)
        variabili.update({"value": float(prima), "amount": effetto.amount})
        try:
            grezzo = evaluate(regola.expression, variabili)
        except ExpressionError as exc:
            self._failed(effetto, exc, report, where=nodo.path)
            return False

        # il valore passa comunque dal contratto del parametro: un effetto puo'
        # spingere, non sfondare
        dopo = spec.coerce(grezzo)
        if abs(float(dopo) - float(grezzo)) > 1e-9:
            report.note("EFFECT_OUT_OF_RANGE",
                        "'%s' su '%s.%s': %s riportato a %s"
                        % (effetto.id, nodo.id, nome, grezzo, dopo),
                        where=nodo.path,
                        why="l'intervallo del parametro e' %s..%s"
                            % (spec.min, spec.max))
        if dopo == prima:
            return False
        nodo.values[nome] = dopo
        nodo.sources[nome] = ResolvedValue(dopo, FROM_EFFECT, origin=effetto.id,
                                           expression=regola.expression,
                                           previous=prima)
        return True

    @staticmethod
    def _failed(effetto: PlannedEffect, errore: Exception, report: Report,
                where: str = "") -> None:
        """Un effetto che fallisce lo dice. Non sparisce in silenzio."""
        gravita = effetto.spec.on_failure
        messaggio = "'%s' non si e' potuto applicare: %s" % (effetto.id, errore)
        dove = where or effetto.host
        if gravita == "fatal":
            report.add("EFFECT_APPLICATION_FAILED", messaggio, where=dove,
                       why="dichiarato indispensabile dal suo plugin")
        elif gravita == "cosmetic":
            report.note("EFFECT_APPLICATION_FAILED", messaggio, where=dove)
        else:
            report.warn("EFFECT_APPLICATION_FAILED", messaggio, where=dove,
                        why="il modello resta costruibile senza")


def apply_effects(composition: ResolvedComposition, registry,
                  report: Report | None = None) -> EffectedComposition:
    """Da una composizione risolta a una con gli effetti dentro."""
    return EffectPipeline(registry).run(composition, report=report)
