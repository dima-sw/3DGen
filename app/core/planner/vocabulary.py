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
MAX_CONCEPT_SHORTLIST = 24     # contratti operativi; l'indice globale resta completo

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
class TraitEntry:
    id: str
    alias: str = ""
    description: str = ""
    type: str = "float"
    min: float | None = None
    max: float | None = None
    choices: tuple = ()
    ops: tuple[str, ...] = ()
    scopes: tuple[str, ...] = ()
    purpose: str = ""

    def to_dict(self) -> dict:
        fuori: dict[str, Any] = {"id": self.id, "type": self.type,
                                 "ops": list(self.ops),
                                 "scopes": list(self.scopes)}
        if self.alias:
            fuori["alias"] = self.alias
        if self.description:
            fuori["description"] = self.description
        if self.min is not None:
            fuori["min"] = self.min
        if self.max is not None:
            fuori["max"] = self.max
        if self.choices:
            fuori["choices"] = list(self.choices)
        if self.purpose:
            fuori["purpose"] = self.purpose
        return fuori

    def to_text(self) -> str:
        name = self.alias or self.id
        if self.choices:
            domain = "{%s}" % ", ".join(str(c) for c in self.choices)
        elif self.min is not None and self.max is not None:
            domain = "[%g, %g]" % (self.min, self.max)
        else:
            domain = self.type
        return '- %s %s ops=%s scopes=%s purpose="%s"' % (
            name, domain, ",".join(self.ops), ",".join(self.scopes),
            self.purpose or self.description)


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


@dataclass(frozen=True)
class ArchetypeEntry:
    """One compact entry in the global concept index."""

    id: str
    aliases: tuple[str, ...] = ()
    description: str = ""

    def to_dict(self) -> dict:
        return {"id": self.id, "aliases": list(self.aliases),
                "description": self.description}

    def to_text(self) -> str:
        return '- %s aliases=%s "%s"' % (
            self.id, ",".join(self.aliases), self.description)


@dataclass(frozen=True)
class ArchetypeDetailEntry:
    """Bounded operational data, separate from the global index."""

    id: str
    parents: tuple[str, ...] = ()
    required_roles: tuple[str, ...] = ()
    preferred_roles: tuple[str, ...] = ()
    required_capabilities: tuple[str, ...] = ()
    preferred_capabilities: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {"id": self.id, "parents": list(self.parents),
                "required_roles": list(self.required_roles),
                "preferred_roles": list(self.preferred_roles),
                "required_capabilities": list(self.required_capabilities),
                "preferred_capabilities": list(self.preferred_capabilities)}

    def to_text(self) -> str:
        return ("- %s parents=%s required_roles=%s required_capabilities=%s"
                % (self.id, ",".join(self.parents), ",".join(self.required_roles),
                   ",".join(self.required_capabilities)))


@dataclass(frozen=True)
class ProfileEntry:
    id: str
    aliases: tuple[str, ...] = ()
    archetypes: tuple[str, ...] = ()
    description: str = ""

    def to_dict(self) -> dict:
        return {"id": self.id, "aliases": list(self.aliases),
                "archetypes": list(self.archetypes),
                "description": self.description}

    def to_text(self) -> str:
        return '- %s archetypes=%s "%s"' % (
            self.id, ",".join(self.archetypes), self.description)


@dataclass(frozen=True)
class BindingEntry:
    id: str
    implementation: str
    supported_archetypes: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {"id": self.id, "implementation": self.implementation,
                "supported_archetypes": list(self.supported_archetypes)}

    def to_text(self) -> str:
        return "- %s implementation=%s supports=%s" % (
            self.id, self.implementation, ",".join(self.supported_archetypes))


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
    traits: tuple[TraitEntry, ...] = ()
    structural_traits: tuple[TraitEntry, ...] = ()
    styles: tuple[StyleEntry, ...] = ()
    archetypes: tuple[ArchetypeEntry, ...] = ()
    archetype_details: tuple[ArchetypeDetailEntry, ...] = ()
    profiles: tuple[ProfileEntry, ...] = ()
    bindings: tuple[BindingEntry, ...] = ()
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
            "traits": [t.to_dict() for t in self.traits],
            "structural_traits": [t.to_dict() for t in self.structural_traits],
            "styles": [s.to_dict() for s in self.styles],
            "archetypes": [a.to_dict() for a in self.archetypes],
            "archetype_details": [a.to_dict() for a in self.archetype_details],
            "profiles": [p.to_dict() for p in self.profiles],
            "bindings": [b.to_dict() for b in self.bindings],
            "tags": list(self.tags),
        }

    def to_json(self, indent: int | None = None) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent,
                          sort_keys=False)

    def to_text(self, compact: bool = False) -> str:
        """La forma compatta per un modello linguistico.

        Sezioni con un titolo, una voce per riga. Le descrizioni di terze parti
        stanno fra virgolette e su una riga sola: e' il punto in cui la
        sanificazione fatta a monte diventa visibile.
        """
        if compact:
            return self.to_compact_text()
        blocchi = [
            ("COMPONENTI (usa questi id, e nessun altro)",
             [c.to_text() for c in self.components]),
            ("CAPABILITY (come i pezzi si incastrano)",
             [c.to_text() for c in self.capabilities]),
            ("EFFETTI (usa questi id, e nessun altro)",
             [e.to_text() for e in self.effects]),
            ("TRAITS (usa questi id o alias sicuri, e nessun altro)",
             [t.to_text() for t in self.traits]),
            ("STRUCTURAL TRAITS (contano o duplicano istanze; niente coordinate)",
             [t.to_text() for t in self.structural_traits]),
            ("STILI", [s.to_text() for s in self.styles]),
            ("ARCHETYPE GLOBAL INDEX", [a.to_text() for a in self.archetypes]),
            ("ARCHETYPE SHORTLIST", [a.to_text() for a in self.archetype_details]),
            ("PROFILES", [p.to_text() for p in self.profiles]),
            ("TAG", ["- " + ", ".join(self.tags)] if self.tags else []),
            ("PLUGIN INSTALLATI", [p.to_text() for p in self.plugins]),
        ]
        fuori = []
        for titolo, righe in blocchi:
            if righe:
                fuori.append("## %s\n%s" % (titolo, "\n".join(righe)))
        return "\n\n".join(fuori)

    def to_compact_text(self) -> str:
        """Forma senza sezioni duplicate, per endpoint con body piu' piccoli.

        I componenti conservano tutto cio' che serve a scegliere un id, a
        collegarlo e a valorizzare i parametri. Capability aggregate, plugin
        installati e tag globali sono gia' implicati dai contratti dei pezzi e
        non vengono ripetuti nel prompt. I set di parametri condivisi sono
        dichiarati una volta e referenziati: il contratto resta completo senza
        duplicarlo fra root e parti dello stesso plugin.
        """
        signatures = {
            componente.id: tuple(p.to_text() for p in componente.params
                                 if not p.derived)[:MAX_ELENCO]
            for componente in self.components
        }
        counts: dict[tuple[str, ...], int] = {}
        for signature in signatures.values():
            if signature:
                counts[signature] = counts.get(signature, 0) + 1
        param_refs: dict[tuple[str, ...], str] = {}
        for componente in self.components:
            signature = signatures[componente.id]
            if signature and counts.get(signature, 0) > 1 \
                    and signature not in param_refs:
                param_refs[signature] = "P%d" % (len(param_refs) + 1)

        componenti = []
        for componente in self.components:
            parti = [componente.id]
            if componente.provides:
                parti.append("provides=" + ",".join(componente.provides))
            if componente.mounts:
                accetta = []
                for mount in componente.mounts:
                    lato = ":" + mount.side if mount.side else ""
                    accetta.append(mount.capability + lato)
                parti.append("accepts=" + ",".join(accetta))
            signature = signatures[componente.id]
            if signature in param_refs:
                parti.append("params=@" + param_refs[signature])
            elif signature:
                parti.append("params=" + ";".join(signature))
            componenti.append("- " + " | ".join(parti))

        param_sets = ["- @%s %s" % (ref, ";".join(signature))
                      for signature, ref in param_refs.items()]

        effetti = []
        for effetto in self.effects:
            parti = [effetto.id]
            if effetto.scopes:
                parti.append("scopes=" + ",".join(effetto.scopes))
            if effetto.amount is not None:
                parti.append("amount=" + effetto.amount.to_text())
            if effetto.params:
                parti.append("params=" + ";".join(
                    p.to_text() for p in effetto.params[:MAX_ELENCO]))
            effetti.append("- " + " | ".join(parti))

        traits = []
        for trait in self.traits:
            traits.append("- " + " | ".join([
                trait.alias or trait.id,
                trait.type,
                "ops=" + ",".join(trait.ops),
                "scopes=" + ",".join(trait.scopes),
                "range=%s..%s" % (trait.min, trait.max)
                if trait.min is not None or trait.max is not None else "",
            ]).strip(" |"))

        structural_traits = []
        for trait in self.structural_traits:
            structural_traits.append("- " + " | ".join([
                trait.alias or trait.id,
                trait.type,
                "modes=" + ",".join(trait.ops),
                "range=%s..%s" % (trait.min, trait.max)
                if trait.min is not None or trait.max is not None else "",
            ]).strip(" |"))

        archetypes = ["- %s aliases=%s \"%s\"" %
                      (a.id, ",".join(a.aliases), a.description)
                      for a in self.archetypes]
        profiles = ["- %s -> %s" % (p.id, ",".join(p.archetypes))
                    for p in self.profiles]
        blocchi = [("CONCEPT INDEX (semantic data)", archetypes),
                   ("PROFILES (bounded references)", profiles),
                   ("PARAM SETS (shared component contracts)", param_sets),
                   ("COMPONENTI (usa questi id, e nessun altro)", componenti),
                   ("EFFETTI (usa questi id, e nessun altro)", effetti),
                   ("TRAITS (usa questi id o alias sicuri, e nessun altro)", traits),
                   ("STRUCTURAL TRAITS (usa per conteggi espliciti)",
                    structural_traits),
                   ("STILI", ["- " + s.id for s in self.styles])]
        return "\n\n".join("## %s\n%s" % (titolo, "\n".join(righe))
                            for titolo, righe in blocchi if righe)

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


def _trait(trait, registry) -> TraitEntry:
    alias = ""
    for candidate in trait.aliases:
        if registry.trait(candidate) is trait:
            alias = candidate
            break
    value = trait.value
    return TraitEntry(
        id=trait.id, alias=sanitize(alias, 32),
        description=sanitize(trait.description),
        type=getattr(value, "type", "float"),
        min=getattr(value, "min", None), max=getattr(value, "max", None),
        choices=tuple(getattr(value, "choices", ()) or ()),
        ops=tuple(trait.operations), scopes=tuple(trait.scopes),
        purpose=sanitize(trait.purpose or trait.description))


def _structural_trait(trait, registry) -> TraitEntry:
    alias = ""
    for candidate in trait.aliases:
        if registry.structural_trait(candidate) is trait:
            alias = candidate
            break
    value = trait.value
    return TraitEntry(
        id=trait.id, alias=sanitize(alias, 32),
        description=sanitize(trait.description),
        type=getattr(value, "type", "float"),
        min=getattr(value, "min", None), max=getattr(value, "max", None),
        choices=tuple(getattr(value, "choices", ()) or ()),
        ops=tuple(trait.modes), scopes=("local", "children"),
        purpose=sanitize(trait.purpose or trait.description))


def _rilevante_trait(trait, registry, ruoli: set[str], tag: set[str],
                     ids: set[str]) -> bool:
    """Un trait serve se una delle sue regole puo' toccare la rosa.

    Una regola senza bersaglio vale su tutto e resta sempre; una che nomina
    ruoli, tag o componenti resta solo se quelli sono davanti al planner. Non e'
    una semplificazione: proporre un trait che non ha dove applicarsi e' un modo
    di invitare a usarlo.
    """
    regole = registry.trait_rules(trait.id)
    if not regole:
        return True
    for regola in regole:
        bersaglio = regola.match
        voluti = (set(bersaglio.roles), set(bersaglio.tags),
                  set(bersaglio.components))
        if not any(voluti):
            return True
        if voluti[0] and voluti[0] & ruoli:
            return True
        if voluti[1] and voluti[1] <= tag:
            return True
        if voluti[2] and voluti[2] & ids:
            return True
    return False


def _rilevante_structural(trait, registry, ruoli: set[str], tag: set[str],
                          ids: set[str]) -> bool:
    regole = registry.structural_trait_rules(trait.id)
    if not regole:
        return True
    for regola in regole:
        bersaglio = regola.target
        ruolo = {bersaglio.role} if bersaglio.role else set()
        voluti_tag = set(bersaglio.tags)
        componenti = set(bersaglio.components) | ({regola.component}
                                                  if regola.component else set())
        if not (ruolo or voluti_tag or componenti):
            return True
        if ruolo & ruoli or (voluti_tag and voluti_tag & tag) or componenti & ids:
            return True
    return False


def build_vocabulary(registry, *, style: str = "low_poly",
                     detail_level: int = 2, components=None) -> Vocabulary:
    """Dal registry al vocabolario. Deterministico, e senza codice dentro.

    Si elencano solo i componenti che lo **stile chiesto** ammette: proporre a
    un modello un pezzo che verra' poi rifiutato e' un giro di correzione
    sprecato, e la correzione e' una sola.

    `components` e' la rosa scelta a monte (vedi `planner/retrieval.py`). Quando
    c'e', tutto il resto si restringe con lei: capability, effetti, trait e
    plugin elencati sono quelli che hanno a che fare con quei pezzi. Senza
    questo, filtrare i componenti servirebbe a poco — le altre sezioni
    continuerebbero a crescere con la libreria installata.
    """
    tutti = [c for c in registry.components() if c.supports_style(style)]
    if components is None:
        componenti = list(tutti)
        rosa = False
    else:
        ammessi = {c.id for c in tutti}
        componenti = [c for c in components if c.id in ammessi]
        rosa = True
    if not rosa:
        # Senza rosa non c'e' una rilevanza da rispettare: l'alfabetico e'
        # l'unico ordine stabile. Con la rosa l'ordine **e'** l'informazione.
        componenti.sort(key=lambda c: c.id)

    ids = {c.id for c in componenti}
    ruoli = {c.role for c in componenti if c.role}
    tag = {t for c in componenti for t in c.tags}
    capability_rosa = {p.name for c in componenti for p in c.provides}
    capability_rosa |= {m.capability for c in componenti for m in c.mounts
                        if m.capability}

    capacita = []
    for nome in registry.capabilities():
        if rosa and nome not in capability_rosa:
            continue
        info = registry.capability(nome)
        # providers e mounts elencano id: senza filtrarli, una capability
        # riporterebbe nel prompt tutta la libreria che la rosa ha appena escluso
        fornitori = tuple(i for i in info.providers if not rosa or i in ids)
        innesti = tuple(i for i in info.mounts if not rosa or i in ids)
        capacita.append(CapabilityEntry(
            name=nome, description=sanitize(info.description),
            providers=fornitori, mounts=innesti))

    effetti = []
    for effetto in sorted(registry.effects(), key=lambda e: e.id):
        if rosa and effetto.applies_to and not (set(effetto.applies_to)
                                                & (capability_rosa | tag)):
            continue
        effetti.append(_effetto(effetto))

    traits = [t for t in registry.traits()
              if not rosa or _rilevante_trait(t, registry, ruoli, tag, ids)]
    strutturali = [t for t in registry.structural_traits()
                   if not rosa or _rilevante_structural(t, registry, ruoli,
                                                        tag, ids)]
    plugin = [p for p in sorted(registry.plugins(), key=lambda p: p.id)
              if not rosa or any(c.plugin == p.id for c in componenti)]

    return Vocabulary(
        plugins=tuple(PluginEntry(id=p.id, version=p.version,
                                  name=sanitize(p.name, 48),
                                  description=sanitize(p.description))
                      for p in plugin),
        components=tuple(_componente(c) for c in componenti),
        capabilities=tuple(capacita),
        effects=tuple(effetti),
        traits=tuple(_trait(t, registry) for t in traits),
        structural_traits=tuple(_structural_trait(t, registry)
                                for t in strutturali),
        styles=tuple(StyleEntry(id=s.id, description=sanitize(s.description))
                     for s in sorted(registry.styles(), key=lambda s: s.id)),
        archetypes=tuple(ArchetypeEntry(
            id=a.id, aliases=tuple(sanitize(v, 32) for v in a.aliases),
            description=sanitize(a.description)) for a in registry.archetypes()),
        archetype_details=tuple(ArchetypeDetailEntry(
            id=a.id, parents=tuple(a.parents),
            required_roles=tuple(a.required_roles),
            preferred_roles=tuple(a.preferred_roles),
            required_capabilities=tuple(a.required_capabilities),
            preferred_capabilities=tuple(a.preferred_capabilities))
            for a in registry.archetypes()[:MAX_CONCEPT_SHORTLIST]),
        profiles=tuple(ProfileEntry(
            id=p.id, aliases=tuple(sanitize(v, 32) for v in p.aliases),
            archetypes=tuple(p.archetypes), description=sanitize(p.description))
            for p in registry.profiles()[:MAX_CONCEPT_SHORTLIST]),
        bindings=tuple(BindingEntry(
            id=b.id, implementation=b.implementation,
            supported_archetypes=tuple(b.supported_archetypes))
            for b in registry.implementation_bindings()[:MAX_CONCEPT_SHORTLIST]),
        tags=tuple(sorted(tag)) if rosa else tuple(registry.tags()),
        style=style, detail_level=detail_level,
        metadata={"components": len(componenti),
                  "installed_components": len(tutti),
                  "shortlisted": rosa,
                  "plugins": len(plugin),
                   "archetypes": len(registry.archetypes()),
                  "concept_shortlist_limit": MAX_CONCEPT_SHORTLIST,
                  "concept_shortlist_entries": min(len(registry.archetypes()),
                                                     MAX_CONCEPT_SHORTLIST),
                  "profiles": len(registry.profiles()),
                  "bindings": len(registry.implementation_bindings())})
