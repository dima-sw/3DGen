"""Validazione di un piano che arriva da fuori.

Un piano scritto da un modello linguistico e' **testo che somiglia a un
piano**. Prima di arrivare al resolver deve passare quattro controlli, in
quest'ordine, perche' ognuno da' per buono cio' che il precedente ha stabilito:

    schema      e' un oggetto della forma giusta?         chiavi, tipi, annidamento
    grafo       sta in piedi come albero?                 id unici, un padre solo
    registry    nomina cose che esistono?                 componenti, effetti, stili
    parametri   i numeri sono numeri, e stanno dentro?    nomi e intervalli

Il quarto e' il piu' morbido apposta: un valore fuori intervallo non e' un
piano sbagliato, e' una richiesta che il componente riportera' dentro i propri
limiti. Un **nome** di parametro che non esiste invece e' un errore, perche' un
modello che scrive `larghezza` invece di `width` crede di aver chiesto qualcosa
e non ha chiesto niente.

## Perche' non basta `CompositionGraph.from_dict`

Perche' quella e' una lettura, non una difesa: solleva sul primo dato storto e
si ferma li'. Qui si vuole l'elenco **completo** dei difetti, perche' la
correzione e' una sola e deve poterli affrontare tutti insieme.
"""
from __future__ import annotations

from typing import Any

from app.core.errors import Report
from app.core.graph import CompositionGraph

MAX_NODI = 200            # un piano piu' grande di cosi' e' un errore, non un modello
MAX_PROFONDITA = 12

# Le chiavi che un nodo puo' avere. Tutto il resto e' rumore, e viene detto:
# un modello che scrive "position" crede di aver posizionato qualcosa.
CHIAVI_NODO = {"id", "ref", "swap", "params", "effects", "children", "at", "on",
               "optional", "on_request", "level", "scale_mode", "insert",
               "roll", "tags"}
CHIAVI_RADICE = {"version", "style", "detail_level", "seed", "root"}
CHIAVI_EFFETTO = {"type", "scope", "amount", "target"}


def validate_plan(data: Any, registry, *, style: str = "",
                  report: Report | None = None) -> tuple[CompositionGraph | None,
                                                         Report]:
    """Da JSON a `CompositionGraph`, o a niente con l'elenco dei motivi."""
    report = report if report is not None else Report()
    controllo = _Controllo(registry, style=style, report=report)
    return controllo.run(data), report


class _Controllo:
    """Lo stato di una validazione: le diagnosi e gli id gia' visti."""

    def __init__(self, registry, *, style: str = "",
                 report: Report | None = None) -> None:
        self.registry = registry
        self.style = style
        self.report = report if report is not None else Report()
        self.visti: set[str] = set()
        self.nodi = 0

    # ------------------------------------------------------------------ run #
    def run(self, data: Any) -> CompositionGraph | None:
        if not isinstance(data, dict):
            self.report.add("PLAN_NOT_AN_OBJECT",
                            "il piano non e' un oggetto JSON",
                            why="ricevuto %s" % type(data).__name__)
            return None

        for chiave in sorted(set(data) - CHIAVI_RADICE):
            self.report.warn("PLAN_UNKNOWN_KEY", "chiave ignorata: '%s'" % chiave,
                             alternatives=sorted(CHIAVI_RADICE))
        radice = data.get("root")
        if not isinstance(radice, dict):
            self.report.add("PLAN_NO_ROOT", "il piano non ha una radice",
                            why="serve un oggetto 'root' con almeno 'ref'")
            return None

        stile = self.style or str(data.get("style") or "low_poly")
        if self.registry.style(stile) is None and self.registry.styles():
            self.report.add("PLAN_STYLE_NOT_FOUND",
                            "stile inesistente: '%s'" % stile,
                            alternatives=[s.id for s in self.registry.styles()])
            return None

        livello = self._intero(data.get("detail_level"), 2, "detail_level", 1, 5)
        seme = self._intero(data.get("seed"), 0, "seed", 0, 2 ** 31)

        self._nodo(radice, profondita=0)
        if not self.report.ok:
            return None

        grafo = CompositionGraph(style=stile, detail_level=livello, seed=seme,
                                 version=str(data.get("version") or "1.0"))
        try:
            self._costruisci(grafo, radice, "")
        except Exception as exc:                       # noqa: BLE001
            self.report.add("PLAN_NOT_BUILDABLE",
                            "il piano non si e' potuto montare: %s" % exc)
            return None
        return grafo

    # --------------------------------------------------------------- schema #
    def _nodo(self, voce: Any, profondita: int, dove: str = "root") -> None:
        if not isinstance(voce, dict):
            self.report.add("NODE_NOT_AN_OBJECT", "un nodo non e' un oggetto",
                            where=dove)
            return
        self.nodi += 1
        if self.nodi > MAX_NODI:
            self.report.add("PLAN_TOO_LARGE",
                            "il piano ha piu' di %d nodi" % MAX_NODI, where=dove)
            return
        if profondita > MAX_PROFONDITA:
            self.report.add("PLAN_TOO_DEEP",
                            "il piano scende oltre %d livelli" % MAX_PROFONDITA,
                            where=dove)
            return

        for chiave in sorted(set(voce) - CHIAVI_NODO):
            self.report.warn("NODE_UNKNOWN_KEY",
                             "chiave ignorata su '%s': '%s'" % (dove, chiave),
                             where=dove, alternatives=sorted(CHIAVI_NODO))

        id = self._id(voce, dove)
        componente = self._ref(voce, id)
        self._params(voce, componente, id)
        self._effects(voce, id)
        self._on(voce, id)

        figli = voce.get("children")
        if figli is None:
            return
        if not isinstance(figli, list):
            self.report.add("CHILDREN_NOT_A_LIST",
                            "'children' non e' un elenco", where=id)
            return
        for figlio in figli:
            self._nodo(figlio, profondita + 1, id)

    def _id(self, voce: dict, dove: str) -> str:
        """L'id, o uno costruito. Un piano senza id non e' un piano rotto.

        Un modello che dimentica un id ha comunque detto cosa vuole; inventarne
        uno stabile a partire dal riferimento costa una riga e salva una
        correzione. Un id **ripetuto** invece e' un errore vero: due nodi con lo
        stesso nome sono due cose che il piano non sa piu' distinguere.
        """
        id = str(voce.get("id") or "").strip()
        if not id:
            base = str(voce.get("ref") or voce.get("swap") or "nodo")
            id = (base.partition(":")[2] or base).replace(".", "_") or "nodo"
            voce["id"] = self._libero(id)
            return voce["id"]
        if id in self.visti:
            self.report.add("DUPLICATE_NODE_ID",
                            "due nodi si chiamano '%s'" % id, where=dove,
                            why="gli id di un piano devono essere unici")
            return id
        self.visti.add(id)
        return id

    def _libero(self, base: str) -> str:
        if base not in self.visti:
            self.visti.add(base)
            return base
        n = 2
        while "%s_%d" % (base, n) in self.visti:
            n += 1
        self.visti.add("%s_%d" % (base, n))
        return "%s_%d" % (base, n)

    # ------------------------------------------------------------- registry #
    def _ref(self, voce: dict, id: str):
        """Il componente nominato, se esiste. Un id inventato non passa.

        Si accetta anche un riferimento **per capability** — «mettici qualcosa
        che fornisce questo» — perche' e' il modo in cui un piano scritto senza
        sapere quali plugin ci sono resta valido. Chi lo risolve e' il resolver;
        qui basta sapere che qualcuno la fornisce.
        """
        ref = str(voce.get("swap") or voce.get("ref") or "").strip()
        if not ref:
            self.report.add("NODE_NO_REF", "il nodo '%s' non dice cosa costruire" % id,
                            where=id)
            return None

        componente = self.registry.component(ref)
        if componente is not None:
            if self.style and not componente.supports_style(self.style):
                self.report.add(
                    "PLAN_STYLE_INCOMPATIBLE",
                    "'%s' non e' fatto per lo stile '%s'" % (ref, self.style),
                    where=id, alternatives=[c.id for c in self.registry.components(
                        style=self.style)][:6])
            return componente

        if ":" not in ref:
            omonimi = self.registry.named(ref)
            if len(omonimi) == 1:
                return omonimi[0]
            if len(omonimi) > 1:
                self.report.add("AMBIGUOUS_COMPONENT",
                                "'%s' non basta a scegliere: %d candidati"
                                % (ref, len(omonimi)), where=id,
                                alternatives=[c.id for c in omonimi][:6])
                return None
            if self.registry.providers(capability=ref):
                return None            # riferimento per capability: legittimo
        self.report.add("COMPONENT_NOT_FOUND", "nessun componente '%s'" % ref,
                        where=id,
                        why="il piano puo' usare solo gli id del vocabolario",
                        alternatives=[c.id for c in self.registry.search(ref)][:6]
                        or self._vicini(ref))
        return None

    def _vicini(self, ref: str) -> list[str]:
        """Qualche id vero, per chi deve correggere. Meglio pochi che nessuno."""
        nome = ref.partition(":")[2] or ref
        tutti = [c.id for c in self.registry.components()]
        somiglianti = [i for i in tutti if nome[:4] and nome[:4] in i]
        return sorted(somiglianti)[:6] or sorted(tutti)[:6]

    # ----------------------------------------------------------- parametri #
    def _params(self, voce: dict, componente, id: str) -> None:
        params = voce.get("params")
        if params is None:
            return
        if not isinstance(params, dict):
            self.report.add("PARAMS_NOT_AN_OBJECT",
                            "'params' non e' un oggetto", where=id)
            voce.pop("params", None)
            return
        if componente is None:
            return

        for nome in sorted(params):
            spec = componente.params.get(nome)
            if spec is None:
                self.report.add(
                    "PARAM_NOT_FOUND",
                    "'%s' non ha un parametro '%s'" % (componente.id, nome),
                    where=id, alternatives=sorted(componente.params)[:8],
                    why="un nome inventato sembra una richiesta e non lo e'")
                continue
            valore = params[nome]
            if isinstance(valore, bool) or not isinstance(valore, (int, float, str)):
                self.report.add("PARAM_NOT_A_VALUE",
                                "'%s.%s' non e' un valore" % (id, nome), where=id)
                continue
            self._intervallo(spec, valore, nome, id)

    def _intervallo(self, spec, valore, nome: str, id: str) -> None:
        """Fuori intervallo si segnala e si lascia passare: il componente clampa.

        Rifiutare il piano per questo vorrebbe dire spendere l'unica correzione
        su un numero che il sistema sa gia' aggiustare da solo.
        """
        if not isinstance(valore, (int, float)):
            return
        minimo, massimo = getattr(spec, "min", None), getattr(spec, "max", None)
        if minimo is not None and valore < minimo:
            self.report.note("PARAM_OUT_OF_RANGE",
                             "%s.%s = %g, sotto il minimo %g" % (id, nome, valore,
                                                                 minimo), where=id)
        elif massimo is not None and valore > massimo:
            self.report.note("PARAM_OUT_OF_RANGE",
                             "%s.%s = %g, sopra il massimo %g" % (id, nome, valore,
                                                                  massimo), where=id)

    # -------------------------------------------------------------- effetti #
    def _effects(self, voce: dict, id: str) -> None:
        effetti = voce.get("effects")
        if effetti is None:
            return
        if not isinstance(effetti, list):
            self.report.add("EFFECTS_NOT_A_LIST", "'effects' non e' un elenco",
                            where=id)
            voce.pop("effects", None)
            return
        for effetto in effetti:
            if not isinstance(effetto, dict):
                self.report.add("EFFECT_NOT_AN_OBJECT",
                                "un effetto non e' un oggetto", where=id)
                continue
            tipo = str(effetto.get("type") or "").strip()
            if not tipo:
                self.report.add("EFFECT_NO_TYPE", "un effetto non dice quale sia",
                                where=id)
                continue
            spec = self.registry.effect(tipo)
            if spec is None:
                self.report.add(
                    "EFFECT_NOT_FOUND", "nessun effetto '%s'" % tipo, where=id,
                    why="il piano puo' usare solo gli effetti del vocabolario",
                    alternatives=[e.id for e in self.registry.effects()][:8])
                continue
            # Le chiavi in piu' sono i **parametri dell'effetto**: `direction`
            # per una posa, `axis` per una piega. Non sono rumore da ignorare —
            # senza di loro meta' degli effetti non si potrebbe chiedere da un
            # piano — ma devono esistere, come per i componenti.
            for chiave in sorted(set(effetto) - CHIAVI_EFFETTO):
                if chiave in spec.params:
                    continue
                self.report.add(
                    "EFFECT_PARAM_NOT_FOUND",
                    "l'effetto '%s' non ha un parametro '%s'" % (tipo, chiave),
                    where=id, alternatives=sorted(spec.params)[:8],
                    why="un nome inventato sembra una richiesta e non lo e'")

    def _on(self, voce: dict, id: str) -> None:
        dove = voce.get("on")
        if dove is None:
            return
        if not isinstance(dove, str) or not dove.strip():
            self.report.add("ON_NOT_A_PATH", "'on' non e' un percorso", where=id)
            voce.pop("on", None)

    # ------------------------------------------------------------- numeri #
    def _intero(self, valore, predefinito: int, nome: str,
                minimo: int, massimo: int) -> int:
        if valore is None:
            return predefinito
        try:
            numero = int(valore)
        except (TypeError, ValueError):
            self.report.warn("PLAN_BAD_NUMBER",
                             "'%s' non e' un numero: uso %d" % (nome, predefinito))
            return predefinito
        if not minimo <= numero <= massimo:
            self.report.warn("PLAN_BAD_NUMBER",
                             "'%s' fuori intervallo: uso %d" % (nome, predefinito))
            return predefinito
        return numero

    # -------------------------------------------------------- costruzione #
    def _costruisci(self, grafo: CompositionGraph, voce: dict, padre: str) -> None:
        """Dal JSON validato al grafo. Qui non si scopre piu' niente.

        Si passa per l'API del grafo — `set_root`, `add_child`, `attach` — e non
        si scrivono i suoi campi a mano: le tre operazioni raccontano intenzioni
        diverse, e un piano ricostruito senza di loro perderebbe la differenza
        fra «di che cosa e' fatto» e «che cosa porta».
        """
        from app.core.capability import Requirement

        id = str(voce["id"])
        ref = str(voce.get("ref") or voce.get("swap") or "")
        dove = voce.get("at") or {}
        requisito = Requirement(capability=str(dove.get("capability") or ""),
                                socket_id=str(dove.get("socket") or ""),
                                side=str(dove.get("side") or ""),
                                tags=frozenset(dove.get("tags") or ()))
        params = dict(voce.get("params") or {})
        percorso = str(voce.get("on") or "")
        aggiunto = bool(voce.get("optional") or voce.get("on_request") or percorso)

        if not padre:
            grafo.set_root(id, ref, **params)
        elif aggiunto:
            grafo.attach(id, ref, "" if percorso else padre, requirement=requisito,
                         on=percorso,
                         on_request=bool(voce.get("on_request", True)),
                         optional=bool(voce.get("optional", True)),
                         level=int(voce.get("level", 2)),
                         scale_mode=str(voce.get("scale_mode") or "socket"),
                         insert=float(voce.get("insert", 0.35)), **params)
        else:
            grafo.add_child(id, ref, padre, requirement=requisito,
                            level=int(voce.get("level", 2)),
                            scale_mode=str(voce.get("scale_mode") or "none"),
                            insert=float(voce.get("insert", 0.35)), **params)
        # `swap` senza `ref` e' gia' diventato il riferimento del nodo: non c'e'
        # niente da sostituire. Registrare comunque una sostituzione da se' a se'
        # riempirebbe la diagnostica di scambi che non sono avvenuti.
        if voce.get("swap") and voce.get("ref"):
            grafo.swap(id, str(voce["swap"]),
                       scale_mode=str(voce.get("scale_mode") or "none"))
        for effetto in voce.get("effects") or []:
            extra = {k: v for k, v in effetto.items() if k not in CHIAVI_EFFETTO}
            grafo.effect(str(effetto["type"]),
                         str(effetto.get("scope") or "model"), target=id,
                         amount=float(effetto.get("amount", 1.0)), **extra)
        for figlio in voce.get("children") or []:
            self._costruisci(grafo, figlio, id)
