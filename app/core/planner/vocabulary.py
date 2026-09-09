"""Il vocabolario: cio' che il planner puo' nominare, e niente altro.

    registry     cosa e' installato, in oggetti Python
    vocabolario  cosa se ne puo' dire a un modello linguistico   <- questo file
    planner      che piano ne esce
    validazione  se quel piano sta in piedi

Il planner non vede il codice dei plugin. Non vede le funzioni `build`, non
vede i moduli, non vede gli oggetti: vede **contratti** — che cosa un
componente e', che cosa accetta, che numeri si possono cambiare. E' la stessa
distinzione che regge tutto il resto del progetto: il contratto e' pubblico,
l'implementazione e' del plugin.

## Perche' e' un oggetto e non una stringa

Perche' due destinatari hanno bisogno di due forme. Un modello vuole del testo
compatto; la validazione, la spiegazione di una scelta e la riparazione di un
piano vogliono dei dati. Costruire il testo da capo ogni volta vorrebbe dire
due descrizioni dello stesso vocabolario che possono divergere.

## Le descrizioni dei plugin sono dati, non istruzioni

Un plugin puo' essere scritto da chiunque, e la sua `description` finisce
dentro il contesto di un modello linguistico. Se quel testo potesse contenere
righe che *sembrano* istruzioni — «ignora quanto sopra», un finto blocco di
sistema, un delimitatore che chiude la sezione dei dati — un plugin di terze
parti diventerebbe un modo per pilotare il planner di chi lo installa.

Qui non si prova a **riconoscere** un testo malevolo: riconoscerlo e' una gara
che si perde. Si toglie invece la possibilita' di fingere struttura:

    ogni testo di terze parti sta su una riga sola      niente righe finte
    ogni testo e' racchiuso fra virgolette              niente sezioni finte
    i delimitatori del formato vengono neutralizzati    niente blocchi finti
    la lunghezza e' limitata                            niente muri di testo

Quello che resta e' una frase fra virgolette dentro un campo `description`, che
un modello legge come cio' che e': il valore di un campo. Il prompt di sistema
lo dice a chiare lettere, ma il prompt e' l'ultima difesa, non la prima.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

MAX_DESCRIZIONE = 160          # caratteri di un testo di terze parti
MAX_ELENCO = 12                # quante voci si elencano prima di dire «e altri»

# Tutto cio' che potrebbe far credere a un modello che il dato sia finito e sia
# cominciata un'istruzione. Non e' un elenco di parole vietate: sono i
# **delimitatori** del formato in cui il dato viene consegnato.
_STRUTTURA = re.compile(r"[`\r\n\t\x00-\x1f\x7f]+")
_MARCATORI = re.compile(r"(?i)\b(system|assistant|user)\s*:")


def sanitize(testo: Any, limite: int = MAX_DESCRIZIONE) -> str:
    """Un testo di terze parti, ridotto a un valore di campo.

    Una riga sola, senza delimitatori, senza marcatori di ruolo, corta. Non
    viene giudicato il contenuto: viene tolta la forma con cui potrebbe
    spacciarsi per qualcosa di diverso da un dato.
    """
    if testo is None:
        return ""
    ridotto = _STRUTTURA.sub(" ", str(testo))
    ridotto = _MARCATORI.sub(lambda m: m.group(0).replace(":", " -"), ridotto)
    ridotto = " ".join(ridotto.split())
    if len(ridotto) > limite:
        ridotto = ridotto[:limite - 1].rstrip() + "…"
    return ridotto


# --------------------------------------------------------------------------- #
# Le voci
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ParamEntry:
    """Un parametro: nome, tipo, intervallo. L'LLM sceglie dentro, non fuori."""

    name: str
    type: str = "float"
    min: float | None = None
    max: float | None = None
    default: Any = None
    choices: tuple = ()
    unit: str = ""
    role: str = ""
    derived: bool = False
    description: str = ""

    def to_dict(self) -> dict:
        fuori: dict[str, Any] = {"name": self.name, "type": self.type}
        if self.min is not None:
            fuori["min"] = self.min
        if self.max is not None:
            fuori["max"] = self.max
        if self.default is not None:
            fuori["default"] = self.default
        if self.choices:
            fuori["choices"] = list(self.choices)
        for chiave, valore in (("unit", self.unit), ("role", self.role),
                               ("description", self.description)):
            if valore:
                fuori[chiave] = valore
        if self.derived:
            fuori["derived"] = True
        return fuori

    def to_text(self) -> str:
        if self.choices:
            intervallo = "{%s}" % ", ".join(str(c) for c in self.choices)
        elif self.min is not None and self.max is not None:
            intervallo = "[%g, %g]" % (self.min, self.max)
        else:
            intervallo = self.type
        coda = " derivato" if self.derived else ""
        return "%s: %s %s%s" % (self.name, self.type, intervallo, coda)


@dataclass(frozen=True)
class MountEntry:
    """Un innesto: che cosa un componente **accetta**, e quanti."""

    capability: str
    side: str = ""
    tags: tuple[str, ...] = ()
    capacity: int = 1

    def to_dict(self) -> dict:
        fuori: dict[str, Any] = {"capability": self.capability}
        if self.side:
            fuori["side"] = self.side
        if self.tags:
            fuori["tags"] = list(self.tags)
        if self.capacity != 1:
            fuori["capacity"] = self.capacity
        return fuori

    def to_text(self) -> str:
        extra = [p for p in (self.side, ", ".join(self.tags)) if p]
        return "%s%s" % (self.capability,
                         " (%s)" % " ".join(extra) if extra else "")


@dataclass(frozen=True)
class ComponentEntry:
    """Un componente, come contratto: cio' che e', cio' che accetta, cio' che regola."""

    id: str
    description: str = ""
    provides: tuple[str, ...] = ()
    mounts: tuple[MountEntry, ...] = ()
    params: tuple[ParamEntry, ...] = ()
    tags: tuple[str, ...] = ()
    role: str = ""
    styles: tuple[str, ...] = ()
    plugin: str = ""

    def to_dict(self) -> dict:
        fuori: dict[str, Any] = {"id": self.id}
        if self.description:
            fuori["description"] = self.description
        if self.provides:
            fuori["provides"] = list(self.provides)
        if self.mounts:
            fuori["accepts"] = [m.to_dict() for m in self.mounts]
        if self.params:
            fuori["params"] = [p.to_dict() for p in self.params]
        for chiave, valore in (("role", self.role), ("tags", list(self.tags)),
                               ("styles", list(self.styles))):
            if valore:
                fuori[chiave] = valore
        return fuori

    def to_text(self) -> str:
        righe = ['- %s "%s"' % (self.id, self.description)]
        if self.provides:
            righe.append("    e': %s" % ", ".join(self.provides))
        if self.mounts:
            righe.append("    accetta: %s"
                         % "; ".join(m.to_text() for m in self.mounts))
        liberi = [p for p in self.params if not p.derived]
        if liberi:
            righe.append("    params: %s"
                         % "; ".join(p.to_text() for p in liberi[:MAX_ELENCO]))
        if self.tags:
            righe.append("    tag: %s" % ", ".join(self.tags))
        return "\n".join(righe)


@dataclass(frozen=True)
class EffectEntry:
    """Un effetto: che cosa fa, dove si applica, con che numeri."""

    id: str
    description: str = ""
    stage: str = ""
    scopes: tuple[str, ...] = ()
    amount: ParamEntry | None = None
    params: tuple[ParamEntry, ...] = ()
    applies_to: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        fuori: dict[str, Any] = {"id": self.id, "stage": self.stage,
                                 "scopes": list(self.scopes)}
        if self.description:
            fuori["description"] = self.description
        if self.amount is not None:
            fuori["amount"] = self.amount.to_dict()
        if self.params:
            fuori["params"] = [p.to_dict() for p in self.params]
        if self.applies_to:
            fuori["applies_to"] = list(self.applies_to)
        if self.conflicts:
            fuori["conflicts"] = list(self.conflicts)
        return fuori

    def to_text(self) -> str:
        righe = ['- %s "%s"' % (self.id, self.description),
                 "    stadio: %s; ambiti: %s" % (self.stage, ", ".join(self.scopes))]
        if self.amount is not None:
            righe.append("    amount: %s" % self.amount.to_text())
        if self.params:
            righe.append("    params: %s"
                         % "; ".join(p.to_text() for p in self.params))
        if self.applies_to:
            righe.append("    per: %s" % ", ".join(self.applies_to))
        return "\n".join(righe)


@dataclass(frozen=True)
class CapabilityEntry:
    """Una capability: chi la fornisce e chi la accetta."""

    name: str
    description: str = ""
    providers: tuple[str, ...] = ()
    mounts: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        fuori: dict[str, Any] = {"name": self.name}
        if self.description:
            fuori["description"] = self.description
        if self.providers:
            fuori["provided_by"] = list(self.providers[:MAX_ELENCO])
        if self.mounts:
            fuori["accepted_by"] = list(self.mounts[:MAX_ELENCO])
        return fuori

    def to_text(self) -> str:
        return "- %s: la forniscono %s; la accettano %s" % (
            self.name,
            ", ".join(self.providers[:6]) or "nessuno",
            ", ".join(self.mounts[:6]) or "nessuno")


@dataclass(frozen=True)
class PluginEntry:
    id: str
    version: str = "0.0.0"
    name: str = ""
    description: str = ""

    def to_dict(self) -> dict:
        return {"id": self.id, "version": self.version, "name": self.name,
                "description": self.description}

    def to_text(self) -> str:
        return '- %s %s "%s"' % (self.id, self.version, self.description)


@dataclass(frozen=True)
class StyleEntry:
    id: str
    description: str = ""

    def to_dict(self) -> dict:
        return {"id": self.id, "description": self.description}

    def to_text(self) -> str:
        return '- %s "%s"' % (self.id, self.description)


# --------------------------------------------------------------------------- #
# Il vocabolario
# --------------------------------------------------------------------------- #
@dataclass
class Vocabulary:
    """Tutto cio' che si puo' nominare in un piano, in una forma sola.

    Non e' una copia del registry: e' la sua **faccia pubblica**. Cambia da
    solo quando cambiano i plugin, e nessuno deve aggiornare il planner perche'
    e' arrivato un pianeta.
    """

    plugins: tuple[PluginEntry, ...] = ()
    components: tuple[ComponentEntry, ...] = ()
    capabilities: tuple[CapabilityEntry, ...] = ()
    effects: tuple[EffectEntry, ...] = ()
    styles: tuple[StyleEntry, ...] = ()
    tags: tuple[str, ...] = ()
    style: str = "low_poly"
    detail_level: int = 2
    metadata: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------- lettura #
    def component(self, id: str) -> ComponentEntry | None:
        for voce in self.components:
            if voce.id == id:
                return voce
        return None

    def effect(self, id: str) -> EffectEntry | None:
        nudo = id.partition(":")[2] or id
        for voce in self.effects:
            if voce.id == id or (voce.id.partition(":")[2] or voce.id) == nudo:
                return voce
        return None

    def ids(self) -> list[str]:
        return [c.id for c in self.components]

    def providers_of(self, capability: str) -> list[str]:
        return [c.id for c in self.components if capability in c.provides]

    def acceptors_of(self, capability: str) -> list[str]:
        return [c.id for c in self.components
                if any(m.capability == capability for m in c.mounts)]

    def __len__(self) -> int:
        return len(self.components)

    # ------------------------------------------------------------- uscita #
    def to_dict(self) -> dict:
        return {
            "style": self.style, "detail_level": self.detail_level,
            "plugins": [p.to_dict() for p in self.plugins],
            "components": [c.to_dict() for c in self.components],
            "capabilities": [c.to_dict() for c in self.capabilities],
            "effects": [e.to_dict() for e in self.effects],
            "styles": [s.to_dict() for s in self.styles],
            "tags": list(self.tags),
        }

    def to_json(self, indent: int | None = None) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent,
                          sort_keys=False)

    def to_text(self) -> str:
        """La forma compatta per un modello linguistico.

        Sezioni con un titolo, una voce per riga. Le descrizioni di terze parti
        stanno fra virgolette e su una riga sola: e' il punto in cui la
        sanificazione fatta a monte diventa visibile.
        """
        blocchi = [
            ("COMPONENTI (usa questi id, e nessun altro)",
             [c.to_text() for c in self.components]),
            ("CAPABILITY (come i pezzi si incastrano)",
             [c.to_text() for c in self.capabilities]),
            ("EFFETTI (usa questi id, e nessun altro)",
             [e.to_text() for e in self.effects]),
            ("STILI", [s.to_text() for s in self.styles]),
            ("TAG", ["- " + ", ".join(self.tags)] if self.tags else []),
            ("PLUGIN INSTALLATI", [p.to_text() for p in self.plugins]),
        ]
        fuori = []
        for titolo, righe in blocchi:
            if righe:
                fuori.append("## %s\n%s" % (titolo, "\n".join(righe)))
        return "\n\n".join(fuori)

    def fingerprint(self) -> str:
        """Un'impronta stabile del vocabolario.

        Serve al planner finto, che deve dare lo stesso piano a parita' di
        prompt, vocabolario e seme. Con CRC32 e non con `hash()`, che in Python
        cambia a ogni processo.
        """
        from zlib import crc32

        return "%08x" % crc32(self.to_json().encode("utf-8"))


# --------------------------------------------------------------------------- #
# Costruzione dal registry
# --------------------------------------------------------------------------- #
def _param(nome: str, spec) -> ParamEntry:
    return ParamEntry(
        name=nome, type=getattr(spec, "type", "float"),
        min=getattr(spec, "min", None), max=getattr(spec, "max", None),
        default=spec.default if isinstance(spec.default, (int, float, str)) else None,
        choices=tuple(getattr(spec, "choices", ()) or ()),
        unit=sanitize(getattr(spec, "unit", ""), 16),
        role=sanitize(getattr(spec, "semantic_role", ""), 24),
        derived=bool(getattr(spec, "derived", "")),
        description=sanitize(getattr(spec, "description", ""), 80))


def _componente(componente) -> ComponentEntry:
    return ComponentEntry(
        id=componente.id,
        description=sanitize(componente.description),
        provides=tuple(sorted(c.name for c in componente.provides)),
        mounts=tuple(MountEntry(capability=m.capability, side=m.side,
                                tags=tuple(sorted(m.tags)), capacity=m.capacity)
                     for m in componente.mounts),
        params=tuple(_param(n, s) for n, s in sorted(componente.params.items())),
        tags=tuple(sorted(componente.tags)),
        role=sanitize(componente.role, 32),
        styles=tuple(sorted(componente.styles)),
        plugin=componente.plugin)


def _effetto(effetto) -> EffectEntry:
    return EffectEntry(
        id=effetto.id,
        description=sanitize(effetto.description),
        stage=effetto.stage, scopes=tuple(effetto.scopes),
        amount=_param("amount", effetto.amount) if effetto.amount else None,
        params=tuple(_param(n, s) for n, s in sorted(effetto.params.items())),
        applies_to=tuple(sorted(effetto.applies_to)),
        conflicts=tuple(sorted(effetto.conflicts)),
        tags=tuple(sorted(effetto.tags)))


def build_vocabulary(registry, *, style: str = "low_poly",
                     detail_level: int = 2) -> Vocabulary:
    """Dal registry al vocabolario. Deterministico, e senza codice dentro.

    Si elencano solo i componenti che lo **stile chiesto** ammette: proporre a
    un modello un pezzo che verra' poi rifiutato e' un giro di correzione
    sprecato, e la correzione e' una sola.
    """
    componenti = [c for c in registry.components() if c.supports_style(style)]
    componenti.sort(key=lambda c: c.id)

    capacita = []
    for nome in registry.capabilities():
        info = registry.capability(nome)
        capacita.append(CapabilityEntry(
            name=nome, description=sanitize(info.description),
            providers=tuple(info.providers), mounts=tuple(info.mounts)))

    return Vocabulary(
        plugins=tuple(PluginEntry(id=p.id, version=p.version,
                                  name=sanitize(p.name, 48),
                                  description=sanitize(p.description))
                      for p in sorted(registry.plugins(), key=lambda p: p.id)),
        components=tuple(_componente(c) for c in componenti),
        capabilities=tuple(capacita),
        effects=tuple(_effetto(e) for e in sorted(registry.effects(),
                                                  key=lambda e: e.id)),
        styles=tuple(StyleEntry(id=s.id, description=sanitize(s.description))
                     for s in sorted(registry.styles(), key=lambda s: s.id)),
        tags=tuple(registry.tags()),
        style=style, detail_level=detail_level,
        metadata={"components": len(componenti),
                  "plugins": len(registry.plugins())})
