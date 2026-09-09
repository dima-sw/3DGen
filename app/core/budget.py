"""Quanto ci si puo' permettere di costruire.

## Budget non e' detail_level

Sono due cose diverse e vanno tenute separate:

    detail_level   quanto a fondo VOGLIO esplorare la struttura
    budget         quanto POSSO permettermi di costruire

Un piano puo' chiedere dettaglio 10 e fermarsi al 4 perche' i triangoli sono
finiti. Il contrario e' altrettanto normale: dettaglio 2 con budget enorme si
ferma al 2, perche' non c'e' altro da espandere.

Confondere i due porta a scrivere `max_depth = detail_level`, che e' il modo
sbagliato di fermarsi: si smette di scendere anche quando ci sarebbe spazio, e
non si smette quando lo spazio e' finito.

## Diagnostica invece di fallimento

Quando il budget si esaurisce non si solleva: si annota **dove** ci si e'
fermati e **quanto** mancava. E' l'informazione che serve a chi legge, e
domani all'unica correzione dell'LLM.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from app.core.errors import Report

# Cosa si puo' esaurire. Nominati, perche' la diagnostica li cita.
TRIANGLES = "triangoli"
NODES = "nodi"
EXPANSIONS = "espansioni"
SECONDS = "secondi"

LIMITS = (TRIANGLES, NODES, EXPANSIONS, SECONDS)


@dataclass
class Budget:
    """Contabilita' di cio' che una costruzione puo' consumare.

    `None` su un limite significa "non ho un tetto per questo". Un budget senza
    limiti e' valido e non rallenta niente: serve nei test e quando si vuole
    davvero costruire tutto.
    """

    triangles: int | None = None
    nodes: int | None = None
    expansions: int | None = None
    seconds: float | None = None

    spent: dict[str, float] = field(default_factory=lambda: {k: 0.0 for k in LIMITS})
    started: float = field(default_factory=time.perf_counter)
    # dove ci si e' fermati, per la diagnostica
    stopped_at: str = ""
    stopped_on: str = ""

    # ------------------------------------------------------------- lettura #
    def limit(self, kind: str) -> float | None:
        return {TRIANGLES: self.triangles, NODES: self.nodes,
                EXPANSIONS: self.expansions, SECONDS: self.seconds}.get(kind)

    def used(self, kind: str) -> float:
        if kind == SECONDS:
            return time.perf_counter() - self.started
        return self.spent.get(kind, 0.0)

    def remaining(self, kind: str) -> float | None:
        tetto = self.limit(kind)
        return None if tetto is None else tetto - self.used(kind)

    def exhausted(self) -> str:
        """Il primo limite senza piu' margine, o stringa vuota. Ordine stabile."""
        for kind in LIMITS:
            resto = self.remaining(kind)
            if resto is not None and resto <= 0:
                return kind
        return ""

    def overflowed(self) -> str:
        """Il primo limite **oltrepassato**, o stringa vuota.

        Diverso da `exhausted`: una spesa che finisce il budget esatto ci sta
        dentro, quella successiva no. Confonderli fa perdere l'ultimo pezzo —
        pagato e poi buttato via perche' dopo non restava niente.
        """
        for kind in LIMITS:
            resto = self.remaining(kind)
            if resto is not None and resto < 0:
                return kind
        return ""

    @property
    def ok(self) -> bool:
        return not self.exhausted()

    # ------------------------------------------------------------ scrittura #
    def spend(self, kind: str, amount: float = 1.0, where: str = "") -> bool:
        """Consuma. Restituisce se questa spesa **ci stava**.

        Non "se dopo resta margine": chi chiama paga prima di costruire, e un
        pezzo che entrava esatto nel budget va costruito, non scartato perche'
        dopo di lui non restava piu' niente.
        """
        if kind in self.spent:
            self.spent[kind] += float(amount)
        superato = self.overflowed()
        if superato and not self.stopped_on:
            self.stopped_on, self.stopped_at = superato, where
        return not superato

    def afford(self, kind: str, amount: float = 1.0) -> bool:
        """C'e' spazio per questa spesa, senza farla?"""
        resto = self.remaining(kind)
        return resto is None or resto >= amount

    def stop(self, where: str, kind: str = "") -> None:
        if not self.stopped_on:
            self.stopped_on, self.stopped_at = kind or self.exhausted() or "", where

    # ----------------------------------------------------------- sottobudget #
    def share(self, fraction: float, label: str = "") -> "Budget":
        """Una quota di questo budget, per un sottoalbero.

        Propagazione volutamente elementare: una frazione dei limiti, non un
        allocatore. Serve a impedire che un ramo si mangi tutto, non a
        distribuire in modo ottimo — quella e' una decisione da prendere quando
        ci sara' un caso vero che la chiede.

        Il figlio **non** ha un tempo proprio: il tempo scorre per tutti allo
        stesso modo, e frazionarlo darebbe scadenze che non vogliono dire niente.
        """
        f = max(min(float(fraction), 1.0), 0.0)

        def quota(valore, restante):
            if valore is None:
                return None
            return max(int(min(valore, max(restante, 0)) * f), 0)

        figlio = Budget(
            triangles=quota(self.triangles, self.remaining(TRIANGLES) or 0),
            nodes=quota(self.nodes, self.remaining(NODES) or 0),
            expansions=quota(self.expansions, self.remaining(EXPANSIONS) or 0),
            seconds=self.remaining(SECONDS))
        figlio.started = self.started
        figlio.stopped_at = label
        return figlio

    def absorb(self, child: "Budget") -> None:
        """Riporta nel budget padre cio' che un sottobudget ha consumato."""
        for kind in (TRIANGLES, NODES, EXPANSIONS):
            self.spent[kind] = self.spent.get(kind, 0.0) + child.spent.get(kind, 0.0)
        if child.stopped_on and not self.stopped_on:
            self.stopped_on, self.stopped_at = child.stopped_on, child.stopped_at

    # ---------------------------------------------------------- diagnostica #
    def report_to(self, report: Report, detail_level: int | None = None) -> None:
        """Annota l'esaurimento, dicendo dove e di quanto."""
        superato = self.stopped_on or self.exhausted()
        if not superato:
            return
        tetto = self.limit(superato)
        report.warn(
            "BUDGET_EXCEEDED",
            "budget esaurito: %s" % superato,
            where=self.stopped_at,
            why="tetto %s, stimato %s%s" % (
                self._fmt(tetto), self._fmt(self.used(superato)),
                "" if detail_level is None else ", dettaglio chiesto %d" % detail_level))

    @staticmethod
    def _fmt(value) -> str:
        if value is None:
            return "nessuno"
        return "%.1f" % value if isinstance(value, float) else str(value)

    def describe(self) -> str:
        pezzi = []
        for kind in LIMITS:
            tetto = self.limit(kind)
            if tetto is not None:
                pezzi.append("%s %s/%s" % (kind, self._fmt(self.used(kind)),
                                           self._fmt(tetto)))
        return ", ".join(pezzi) or "nessun limite"


# Tetti di una generazione qualunque, quando nessuno ne ha chiesti di propri.
# Non sono numeri sacri: sono numeri **finiti**, che e' la sola cosa che conta.
STANDARD_NODES = 400
STANDARD_EXPANSIONS = 400
STANDARD_SECONDS = 20.0


def standard() -> Budget:
    """Il budget di una generazione che non ne ha chiesto uno.

    Largo abbastanza da non tagliare niente di sensato, finito abbastanza da
    fermare cio' che non finirebbe.
    """
    return Budget(nodes=STANDARD_NODES, expansions=STANDARD_EXPANSIONS,
                  seconds=STANDARD_SECONDS)


def unlimited() -> Budget:
    """Un budget senza tetti.

    **Per i test e per i casi controllati. Mai come predefinito di una
    generazione vera.** Una ricorsione valida non e' una ricorsione che
    finisce: un componente che si annida riducendo un parametro puo' scendere
    per sempre, restando perfettamente legittimo a ogni passo. Le uniche cose
    che lo fermano sono il rilevamento della ripetizione e **il budget**; se il
    budget non c'e', non si ferma niente.

    Chi costruisce l'API di produzione — la `Session`, la riga di comando —
    deve passare un budget esplicito. `standard()` esiste apposta.
    """
    return Budget()
