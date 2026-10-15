"""Component Lab: prendere un componente installato e vedere cosa sa fare.

Funziona su **qualunque** componente del registry, procedurale o mesh-backed,
e la frase precedente e' il punto: il laboratorio non sa da dove viene la
geometria, perche' passa dalla pipeline vera. Non c'e' un ramo per i GLB, e un
test legge questo file cercando `mesh_backed` e non lo trova.

Che cosa offre, e da dove lo prende:

    params()          i `ParamSpec` del componente, con intervallo e ruolo
    traits()          i trait **compatibili**: quelli di cui una regola
                      installata accetta questo componente. Nessuna euristica
                      — si riusa `TraitResolver._matches`, cioe' lo stesso
                      giudizio che decidera' davvero se il trait lo colpisce
    effects()         gli effetti che dichiarano di avere senso su cio' che
                      questo componente fornisce (`Registry.effects_for`)
    detail_levels()   quanti nodi esistono a ciascun livello, **misurati** da
                      una build vera e non dedotti dagli `Attachment`
    build()           un piano normale attraverso `Session.build`
    randomize()       valori validi a caso, dentro gli intervalli dichiarati
    save_variant()    la configurazione come `VariantRecipe`

## Non modifica niente

Il laboratorio non scrive nel registry — non potrebbe, e' congelato — e non
tocca il `Component`. Costruisce **piani**, che sono la cosa che il progetto
considera l'artefatto (regola 7 di `PROJECT-INDEX`). Finche' l'utente non
salva una variant, non resta niente: un test costruisce con parametri strani,
poi ricostruisce con i predefiniti e verifica che la geometria sia tornata
identica.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

from app.authoring import errors
from app.authoring.errors import AuthoringError
from app.authoring.model import CANDIDATE
from app.authoring.variant import VariantRecipe

MAX_DETAIL = 5


@dataclass
class ParamKnob:
    """Un parametro come uno slider lo vede: nome, tipo, intervallo, ruolo."""

    name: str
    type: str = "float"
    default: Any = 0.0
    min: float | None = None
    max: float | None = None
    semantic_role: str = ""
    unit: str = ""
    description: str = ""
    choices: tuple = ()
    derived: bool = False
    effect: str = ""                 # l'effetto che questo parametro pilota

    @property
    def adjustable(self) -> bool:
        """Si puo' muovere? Un valore derivato lo calcola il sistema."""
        return not self.derived

    @property
    def bounded(self) -> bool:
        return self.min is not None and self.max is not None

    def describe(self) -> str:
        span = ("[%s, %s]" % (self.min, self.max)) if self.bounded else "senza limiti"
        pieces = [self.name, self.type, span]
        if self.semantic_role:
            pieces.append("ruolo " + self.semantic_role)
        if self.effect:
            pieces.append("-> " + self.effect)
        return "  ".join(pieces)


@dataclass
class LabResult:
    """Una build del laboratorio: cosa si e' chiesto e cosa ne e' venuto."""

    values: dict = field(default_factory=dict)
    traits: tuple = ()
    effects: tuple = ()
    detail_level: int = 2
    result: Any = None
    plan: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.result is not None and self.result.ok

    @property
    def triangles(self) -> int:
        return 0 if self.result is None else int(self.result.triangles)

    @property
    def nodes(self) -> list[str]:
        resolved = getattr(self.result, "resolved", None)
        return [] if resolved is None else [n.path for n in resolved.walk()]

    def bounds(self):
        scene = None if self.result is None else self.result.scene()
        return None if scene is None or not scene.nodes else scene.bounds()

    def extents(self):
        bounds = self.bounds()
        return None if bounds is None else tuple(float(v) for v in bounds[1] - bounds[0])

    def diagnostics(self) -> list[dict]:
        """Le diagnostiche vere del referto, con la loro gravita'."""
        if self.result is None or self.result.report is None:
            return []
        return [{"code": d.code, "message": d.message, "where": d.where,
                 "why": d.why, "severity": d.severity}
                for d in self.result.report.sorted()]

    def describe(self) -> str:
        extents = self.extents()
        misura = ("%.3f x %.3f x %.3f" % extents) if extents else "niente"
        return "livello %d | %d triangoli | %s | %s" % (
            self.detail_level, self.triangles, misura,
            "ok" if self.ok else "referto non ok")


class _MatchNode:
    """Il minimo che `TraitResolver._matches` legge: un componente e dei tag.

    Esiste per riusare quel giudizio invece di riscriverlo. Un secondo
    matcher qui vorrebbe dire che il laboratorio offre un trait che poi non
    colpisce — che e' peggio di non offrirlo.
    """

    __slots__ = ("component", "tags")

    def __init__(self, component):
        self.component = component
        self.tags = frozenset()


class ComponentLab:
    """Un componente installato, con i suoi parametri e il suo referto."""

    def __init__(self, session, component_id: str, *, style: str = "low_poly",
                 detail_level: int = 2) -> None:
        self.session = session
        self.style = style
        self.detail_level = int(detail_level)
        registry = session.catalog()
        component = registry.component(component_id)
        if component is None:
            raise AuthoringError(errors.UNKNOWN_COMPONENT,
                                 "nessun componente installato con id %r "
                                 "(cercato anche come nome)" % component_id)
        self.component = component
        self.component_id = component.id
        self._values: dict[str, Any] = self.defaults()
        self._traits: tuple = ()
        self._effects: tuple = ()
        # Le parti di cui il componente e' fatto non cambiano muovendo uno
        # slider, e scoprirle costa una build: si misurano una volta per livello.
        self._subtree_cache: dict[int, list] = {}

    # ------------------------------------------------------------- lettura #
    def params(self) -> list[ParamKnob]:
        driven = {b.param: "%s.%s" % (b.type, b.parameter)
                  for b in self.component.param_effects}
        knobs = []
        for name, spec in sorted(self.component.params.items()):
            knobs.append(ParamKnob(
                name=name, type=spec.type, default=spec.default,
                min=spec.min, max=spec.max,
                semantic_role=getattr(spec, "semantic_role", ""),
                unit=spec.unit, description=spec.description,
                choices=tuple(spec.choices or ()), derived=bool(spec.derived),
                effect=driven.get(name, "")))
        return knobs

    def defaults(self) -> dict:
        """I valori dichiarati. I derivati non entrano: li calcola il sistema."""
        return {name: spec.default
                for name, spec in self.component.params.items()
                if not spec.derived}

    def subtree(self, detail_level: int = MAX_DETAIL) -> list:
        """Questo componente piu' le parti che diventa, **risolte davvero**.

        Serve perche' un trait su un composite colpisce quasi sempre una parte
        e non la radice: `std:head_scale` filtra `role in (head, face)`, e la
        testa non e' la radice — e' un figlio che la radice dichiara. Guardare
        solo il componente direbbe «nessun trait compatibile» su un umanoide
        intero, che e' falso e misurato falso (`V5-RESULTS.md` §9).

        Si **risolve** invece di leggere gli `Attachment`, e la differenza non
        e' di comodo: `Component.children` e' una callable, e quella di
        `humanoid_anatomical:torso` legge valori che il resolver deriva dal
        padre (`height`, `hip_width`). Chiamarla con i soli predefiniti alza
        `KeyError` — misurato — quindi l'unico modo onesto di sapere di quali
        parti un componente e' fatto e' chiederlo a chi lo compone.

        E' la correzione che il debito 12 di `PROJECT-INDEX` chiede per il
        filtro di rilevanza del vocabolario — seguire la composizione
        dichiarata — fatta qui, dove si puo': il laboratorio ha il componente
        in mano e puo' costruirlo, mentre il retrieval ha solo la rosa e nessun
        grafo. Il debito nel vocabolario resta aperto, e questo non lo chiude.
        """
        level = int(detail_level)
        cached = self._subtree_cache.get(level)
        if cached is not None:
            return cached
        found: dict[str, Any] = {self.component.id: self.component}
        built = self.build(detail_level=level, check=False, remember=False)
        resolved = getattr(built.result, "resolved", None)
        if resolved is not None:
            for node in resolved.walk():
                component = getattr(node, "component", None)
                if component is not None:
                    found.setdefault(component.id, component)
        parts = [found[k] for k in sorted(found)]
        self._subtree_cache[level] = parts
        return parts

    def traits(self) -> list:
        """I trait semantici di cui una regola accetta questo componente o una sua parte."""
        from app.core.traits import TraitResolver

        registry = self.session.catalog()
        parts = self.subtree()
        found: dict[str, Any] = {}
        for rule in registry.trait_rules():
            if rule.trait in found:
                continue
            if not any(TraitResolver._matches(rule.match, _MatchNode(part), self.style)
                       for part in parts):
                continue
            spec = registry.trait(rule.trait)
            if spec is not None:
                found[spec.id] = spec
        return [found[k] for k in sorted(found)]

    def structural_traits(self) -> list:
        """I trait strutturali il cui bersaglio e' una parte di questo componente.

        Un trait strutturale conta i **figli dichiarati**, quindi la domanda
        giusta la si fa sul sottoalbero e non sulla radice. Si riusa il
        selettore della regola (`StructuralTarget.matches`), che e' lo stesso
        giudizio che la riscrittura usera' davvero.
        """
        registry = self.session.catalog()
        parts = self.subtree()
        found: dict[str, Any] = {}
        for rule in registry.structural_trait_rules():
            if rule.trait in found:
                continue
            if not any(rule.target.matches(None, component=part) for part in parts):
                continue
            spec = registry.structural_trait(rule.trait)
            if spec is not None:
                found[spec.id] = spec
        return [found[k] for k in sorted(found)]

    def effects(self) -> list:
        """Gli effetti compatibili: quelli che dichiarano di valere qui."""
        registry = self.session.catalog()
        caps = [c.name for c in self.component.provides] or [""]
        found: dict[str, Any] = {}
        for effect in registry.effects():
            if any(effect.fits(cap) for cap in caps):
                found[effect.id] = effect
        return [found[k] for k in sorted(found)]

    def _declared_refs(self, component, detail_level: int) -> list[str]:
        """I riferimenti che un componente dichiara, chiesti a lui.

        `children` e' una callable e puo' esplodere su valori che non si
        aspetta: un plugin che non risponde non fa cadere il laboratorio, dice
        che non dichiara figli. Non e' indulgenza — e' che un elenco di parti
        non e' il posto dove scoprire un difetto di un plugin.
        """
        from app.core.component import BuildContext

        if component.children is None:
            return []
        values = {name: spec.default for name, spec in component.params.items()
                  if not spec.derived}
        if component.id == self.component_id:
            values.update(self._values)
        ctx = BuildContext(style=self.style, detail_level=int(detail_level))
        try:
            children = component.children(values, ctx)
        except Exception:                          # noqa: BLE001 - un plugin
            return []
        return [c.component for c in children
                if c.wanted_at(int(detail_level), c.on_request)]

    def declared_children(self, detail_level: int = MAX_DETAIL) -> list[str]:
        """I figli che il componente dichiara a questo livello. Solo i suoi."""
        return self._declared_refs(self.component, detail_level)

    # --------------------------------------------------------------- piano #
    def plan(self, *, values: dict | None = None, traits=(), effects=(),
             detail_level: int | None = None, node_id: str = "subject",
             seed: int = 0) -> dict:
        """Il piano che il laboratorio costruisce. Un piano normale."""
        requested = dict(self._values)
        requested.update(values or {})
        root: dict[str, Any] = {"id": node_id, "ref": self.component_id,
                                "params": requested}
        chosen_effects = [dict(e) for e in (effects or self._effects)]
        if chosen_effects:
            root["effects"] = chosen_effects
        plan: dict[str, Any] = {
            "version": "1.3", "style": self.style,
            "detail_level": int(detail_level if detail_level is not None
                                else self.detail_level),
            "seed": int(seed), "root": root}
        chosen_traits = [dict(t) for t in (traits or self._traits)]
        if chosen_traits:
            plan["traits"] = chosen_traits
        return plan

    def build(self, values: dict | None = None, *, traits=(), effects=(),
              detail_level: int | None = None, check: bool = True,
              remember: bool = True) -> LabResult:
        """Costruisce davvero, attraverso `Session.build`.

        `remember` tiene i valori come stato del laboratorio, cosi' muovere uno
        slider dopo l'altro e' incrementale; passando `False` si misura una
        configurazione senza cambiare quella corrente.
        """
        from app.core.session import Options

        requested = dict(self._values)
        requested.update(values or {})
        chosen_traits = tuple(dict(t) for t in traits) or self._traits
        chosen_effects = tuple(dict(e) for e in effects) or self._effects
        level = int(detail_level if detail_level is not None else self.detail_level)
        plan = self.plan(values=requested, traits=chosen_traits,
                         effects=chosen_effects, detail_level=level)
        result = self.session.build(plan, Options(style=self.style,
                                                  detail_level=level, check=check))
        if remember:
            self._values = requested
            self._traits = chosen_traits
            self._effects = chosen_effects
            self.detail_level = level
        return LabResult(values=requested, traits=chosen_traits,
                         effects=chosen_effects, detail_level=level,
                         result=result, plan=plan)

    def detail_levels(self, levels=range(1, MAX_DETAIL + 1)) -> dict[int, list[str]]:
        """Quali nodi esistono a ciascun livello. Misurato, non dedotto.

        Serve a distinguere il `detail_level` dal LOD di una mesh: qui crescono
        i **nodi**, non i triangoli di una tassellazione. Un composite che a
        livello 1 e' corpo + testa + ali e a livello 3 aggiunge occhi, corna e
        artigli lo dice con questa tabella.
        """
        out: dict[int, list[str]] = {}
        for level in levels:
            built = self.build(detail_level=int(level), check=False, remember=False)
            out[int(level)] = built.nodes
        return out

    # ------------------------------------------------------------- comandi #
    def reset(self) -> LabResult:
        """Torna ai predefiniti dichiarati, e dimentica trait ed effetti."""
        self._values = self.defaults()
        self._traits = ()
        self._effects = ()
        return self.build()

    def randomize(self, seed: int = 0) -> LabResult:
        """Valori validi a caso: dentro gli intervalli, mai fuori.

        «Validi» non e' un modo di dire: un parametro senza `min`/`max` non si
        tocca, perche' inventargli un intervallo vorrebbe dire scegliere al
        posto dell'autore. Un `enum` prende una delle sue `choices`.
        """
        rng = random.Random(int(seed))
        values = dict(self.defaults())
        for name, spec in sorted(self.component.params.items()):
            if spec.derived:
                continue
            if spec.choices:
                values[name] = rng.choice(list(spec.choices))
            elif spec.min is not None and spec.max is not None:
                raw = rng.uniform(float(spec.min), float(spec.max))
                values[name] = spec.coerce(raw)
        return self.build(values)

    def save_variant(self, name: str, *, description: str = "",
                     coverage: str = CANDIDATE) -> VariantRecipe:
        """La configurazione corrente come ricetta. Nessuna mesh duplicata."""
        changed = {k: v for k, v in self._values.items()
                   if k in self.component.params
                   and self.component.params[k].default != v}
        return VariantRecipe(base=self.component_id, name=name,
                             params=changed, traits=self._traits,
                             effects=self._effects, description=description,
                             coverage=coverage, detail_level=self.detail_level,
                             style=self.style)

    # ------------------------------------------------------------- lettura #
    @property
    def values(self) -> dict:
        return dict(self._values)

    def describe(self) -> str:
        return "%s | %d params | %d trait | %d effetti" % (
            self.component_id, len(self.component.params), len(self.traits()),
            len(self.effects()))
