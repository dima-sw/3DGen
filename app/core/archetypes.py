"""Archetypes, Profiles and deterministic concept resolution.

This module owns metadata and selection only.  It never builds geometry and it
never treats tags as proof that a component implements an Archetype.  Concrete
roots enter the resolver through explicit :class:`ImplementationBinding`
objects; the Component contract remains authoritative for roles, capabilities
and public parameters.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

# I gradini della degradazione, dal piu' preciso al piu' approssimato. Sono
# stringhe e non un enum perche' finiscono in un progetto salvato: un progetto
# riaperto fra un anno deve poter dire "proxy di categoria" anche se nel
# frattempo qualcuno ha aggiunto un gradino.
# I primi quattro valori esistevano gia' prima di V2 e sono scritti nei
# progetti salvati: restano identici, parola per parola. I tre nuovi seguono la
# stessa lingua per non avere un campo mezzo in inglese e mezzo in italiano.
MATCH_DIRECT = "direct implementation"
MATCH_BINDING_EXACT = "exact"
MATCH_ANCESTOR = "ancestor/body-plan proxy"
MATCH_SPECIALIZATION = "descendant/specialization implementation"
MATCH_NAME = "declared component name"
MATCH_SUBJECT = "semantic subject proxy"
MATCH_PROXY = "weak semantic proxy"
MATCH_PLAN_ROOT = "root supplied by the plan"

# Sotto questo punteggio semantico un candidato non e' una somiglianza, e'
# un'omonimia. Meglio dire che non c'e' niente di adatto che costruire qualcosa
# di scollegato: e' la regola che impedisce «jeep» -> «casco».
MIN_CONFIDENCE = 0.08

# Quanti candidati guardare prima di scegliere. Oltre, si sta solo rimestando
# rumore: l'indice e' gia' ordinato per rilevanza.
MAX_CANDIDATES = 24


def _readable(value: Any) -> str:
    """Un adattamento o una mancanza, in una riga."""
    if isinstance(value, dict):
        pezzi = [str(value[k]) for k in ("trait", "param", "param_role", "kind",
                                         "description", "value")
                 if value.get(k) not in (None, "")]
        return " ".join(pezzi) or str(value)
    return str(value)


def _tuple(value: Any) -> tuple:
    if value is None:
        return ()
    if isinstance(value, (list, tuple, set, frozenset)):
        return tuple(value)
    return (value,)


def _jsonable(value: Any) -> Any:
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return value.to_dict()
    if hasattr(value, "__dict__"):
        return {k: _jsonable(v) for k, v in vars(value).items()
                if not k.startswith("_")}
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable(v) for v in value]
    return value


def _request(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "__dict__"):
        return {k: _jsonable(v) for k, v in vars(value).items()
                if not k.startswith("_")}
    return {"value": value}


def _request_key(value: Any, structural: bool = False) -> tuple:
    item = _request(value)
    target = item.get("target")
    if isinstance(target, dict):
        target = tuple(sorted((str(k), repr(v)) for k, v in target.items()))
    return (str(item.get("trait") or item.get("param") or item.get("name") or ""),
            str(item.get("on") or "root"), str(item.get("scope") or
                                                  ("local" if structural else "subtree")),
            repr(target) if structural else "")


@dataclass
class ArchetypeSpec:
    id: str
    aliases: tuple[str, ...] = ()
    description: str = ""
    parents: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    required_roles: tuple[str, ...] = ()
    preferred_roles: tuple[str, ...] = ()
    required_capabilities: tuple[str, ...] = ()
    preferred_capabilities: tuple[str, ...] = ()
    default_traits: tuple[Any, ...] = ()
    structural_expectations: tuple[Any, ...] = ()
    component_preferences: tuple[Any, ...] = ()
    layout_preferences: tuple[Any, ...] = ()
    owner: str = ""
    version: str = "1.0.0"

    def __post_init__(self) -> None:
        for name in ("aliases", "parents", "tags", "required_roles",
                     "preferred_roles", "required_capabilities",
                     "preferred_capabilities", "default_traits",
                     "structural_expectations", "component_preferences",
                     "layout_preferences"):
            setattr(self, name, _tuple(getattr(self, name)))

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "aliases": list(self.aliases),
                "description": self.description, "parents": list(self.parents),
                "tags": list(self.tags), "required_roles": list(self.required_roles),
                "preferred_roles": list(self.preferred_roles),
                "required_capabilities": list(self.required_capabilities),
                "preferred_capabilities": list(self.preferred_capabilities),
                "default_traits": [_jsonable(v) for v in self.default_traits],
                "structural_expectations": [_jsonable(v)
                                              for v in self.structural_expectations],
                "component_preferences": [_jsonable(v)
                                            for v in self.component_preferences],
                "layout_preferences": [_jsonable(v)
                                        for v in self.layout_preferences],
                "owner": self.owner, "version": self.version}


@dataclass
class ProfileSpec:
    id: str
    aliases: tuple[str, ...] = ()
    description: str = ""
    archetypes: tuple[str, ...] = ()
    includes: tuple[str, ...] = ()
    default_traits: tuple[Any, ...] = ()
    structural_defaults: tuple[Any, ...] = ()
    param_role_preferences: tuple[Any, ...] = ()
    component_preferences: tuple[Any, ...] = ()
    style_preferences: tuple[Any, ...] = ()
    owner: str = ""
    version: str = "1.0.0"

    def __post_init__(self) -> None:
        for name in ("aliases", "archetypes", "includes", "default_traits",
                     "structural_defaults", "param_role_preferences",
                     "component_preferences", "style_preferences"):
            setattr(self, name, _tuple(getattr(self, name)))

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "aliases": list(self.aliases),
                "description": self.description, "archetypes": list(self.archetypes),
                "includes": list(self.includes),
                "default_traits": [_jsonable(v) for v in self.default_traits],
                "structural_defaults": [_jsonable(v)
                                         for v in self.structural_defaults],
                "param_role_preferences": [_jsonable(v)
                                             for v in self.param_role_preferences],
                "component_preferences": [_jsonable(v)
                                           for v in self.component_preferences],
                "style_preferences": [_jsonable(v) for v in self.style_preferences],
                "owner": self.owner, "version": self.version}


@dataclass
class ImplementationBinding:
    id: str
    implementation: str
    supported_archetypes: tuple[str, ...] = ()
    owner: str = ""
    version: str = "1.0.0"

    def __post_init__(self) -> None:
        self.supported_archetypes = _tuple(self.supported_archetypes)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "implementation": self.implementation,
                "supported_archetypes": list(self.supported_archetypes),
                "owner": self.owner, "version": self.version}


@dataclass
class ConceptDiagnostic:
    code: str
    message: str
    severity: str = "error"
    where: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message,
                "severity": self.severity, "where": self.where}


@dataclass
class ConceptCoverage:
    candidate: str
    hard_compatible: bool = False
    match: str = ""
    supported: list[dict[str, Any]] = field(default_factory=list)
    unsupported: list[dict[str, Any]] = field(default_factory=list)
    conflicting: list[dict[str, Any]] = field(default_factory=list)
    preferred_hits: int = 0
    score: tuple[int, ...] = ()
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"candidate": self.candidate, "hard_compatible": self.hard_compatible,
                "match": self.match, "supported": list(self.supported),
                "unsupported": list(self.unsupported),
                "conflicting": list(self.conflicting),
                "preferred_hits": self.preferred_hits, "score": list(self.score),
                "reasons": list(self.reasons)}


@dataclass
class ConceptResolutionPlan:
    requested_concept: str
    semantic_source: str = "local"
    archetypes: list[str] = field(default_factory=list)
    profiles: list[str] = field(default_factory=list)
    candidate_bindings: list[dict[str, Any]] = field(default_factory=list)
    selected_binding: str = ""
    selected_root_implementation: str = ""
    adaptations: list[dict[str, Any]] = field(default_factory=list)
    materialized_traits: list[dict[str, Any]] = field(default_factory=list)
    materialized_structural_traits: list[dict[str, Any]] = field(default_factory=list)
    materialized_params: dict[str, Any] = field(default_factory=dict)
    param_role_preferences: list[dict[str, Any]] = field(default_factory=list)
    component_preferences: list[dict[str, Any]] = field(default_factory=list)
    style_preferences: list[dict[str, Any]] = field(default_factory=list)
    coverage: list[dict[str, Any]] = field(default_factory=list)
    unsupported: list[dict[str, Any]] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)
    diagnostics: list[dict[str, Any]] = field(default_factory=list)
    # Come si e' arrivati al risultato. `match` dice **che tipo** di risposta e'
    # questa — un'implementazione esatta o un'approssimazione, e di che genere —
    # `strategy` elenca i gradini provati in ordine, e `confidence` e' il
    # punteggio semantico del candidato scelto, non un giudizio di qualita'.
    match: str = ""
    confidence: float = 0.0
    strategy: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.selected_root_implementation) and not any(
            d.get("severity", "error") == "error" for d in self.diagnostics)

    @property
    def approximate(self) -> bool:
        """Vero quando cio' che si e' costruito non e' cio' che era stato chiesto."""
        return bool(self.selected_root_implementation) and self.match not in (
            "", MATCH_DIRECT, MATCH_NAME, MATCH_BINDING_EXACT, MATCH_PLAN_ROOT)

    def describe(self) -> str:
        """La degradazione in righe leggibili. La stessa che finisce in
        `GenerationResult.explain()`, perche' una spiegazione che esiste in due
        versioni e' una che prima o poi diverge."""
        if not self.requested_concept:
            return ""
        righe = ["richiesto: '%s'" % self.requested_concept]
        if not self.selected_root_implementation:
            righe.append("nessuna implementazione utilizzabile")
            for voce in self.diagnostics:
                righe.append("  %s: %s" % (voce.get("code", ""), voce.get("message", "")))
            return "\n".join(righe)
        if self.approximate:
            righe.append("implementazione esatta: non installata")
            righe.append("scelto per approssimazione: %s"
                         % self.selected_root_implementation)
        else:
            righe.append("scelto: %s" % self.selected_root_implementation)
        if self.match:
            righe.append("tipo di corrispondenza: %s" % self.match)
        if self.confidence:
            righe.append("punteggio semantico: %.3f" % self.confidence)
        if self.strategy:
            righe.append("gradini provati: %s" % " -> ".join(self.strategy))
        for voce in self.unsupported:
            righe.append("non supportato: %s" % _readable(voce))
        for voce in self.materialized_traits:
            righe.append("adattamento: %s" % _readable(voce))
        return "\n".join(righe)

    def to_dict(self) -> dict[str, Any]:
        return {"requested_concept": self.requested_concept,
                "semantic_source": self.semantic_source,
                "archetypes": list(self.archetypes),
                "profiles": list(self.profiles),
                "candidate_bindings": list(self.candidate_bindings),
                "selected_binding": self.selected_binding,
                "selected_root_implementation": self.selected_root_implementation,
                "adaptations": list(self.adaptations),
                "materialized_traits": list(self.materialized_traits),
                "materialized_structural_traits": list(self.materialized_structural_traits),
                "materialized_params": dict(self.materialized_params),
                "param_role_preferences": list(self.param_role_preferences),
                "component_preferences": list(self.component_preferences),
                "style_preferences": list(self.style_preferences),
                "coverage": list(self.coverage), "unsupported": list(self.unsupported),
                "conflicts": list(self.conflicts), "provenance": dict(self.provenance),
                "diagnostics": list(self.diagnostics),
                "match": self.match, "confidence": self.confidence,
                "strategy": list(self.strategy)}

    @classmethod
    def from_dict(cls, value: Any) -> "ConceptResolutionPlan | None":
        if not isinstance(value, dict) or not value.get("requested_concept"):
            return None
        fields = {f for f in cls.__dataclass_fields__}
        data = {k: value[k] for k in fields if k in value}
        for key in ("archetypes", "profiles", "candidate_bindings", "adaptations",
                    "materialized_traits", "materialized_structural_traits",
                    "param_role_preferences", "component_preferences",
                    "style_preferences", "coverage",
                    "unsupported", "conflicts", "diagnostics", "strategy"):
            data[key] = list(data.get(key) or [])
        data["provenance"] = dict(data.get("provenance") or {})
        data["materialized_params"] = dict(data.get("materialized_params") or {})
        return cls(**data)


def subject_capabilities(registry) -> frozenset[str]:
    """Le capability che descrivono un **soggetto intero**, ricavate dai dati.

    Una capability fornita da qualcuno e accettata da nessuno non e' un innesto:
    e' cio' che un componente **e'** quando sta da solo. `vehicle` e `animal` lo
    sono, `head_mount` no — una testa si attacca a qualcosa.

    Nessun nome e' scritto qui dentro: la regola e' strutturale, e un plugin che
    domani porti `spacecraft` entra nell'elenco senza che nessuno lo aggiorni.
    """
    fornite: set[str] = set()
    accettate: set[str] = set()
    for componente in registry.components():
        fornite |= {c.name for c in componente.provides}
        accettate |= {m.capability for m in componente.mounts if m.capability}
    return frozenset(fornite - accettate)


def normalize_reference(raw: str, lookup, ambiguous=None) -> tuple[str, str]:
    """Un id scritto male, ricondotto a uno vero — ma solo se e' sicuro.

    Un modello linguistico incolla prefissi che non esistono
    (`registered:archetype_metadata:felid`), cambia maiuscole, cita un alias.
    Rifiutare tutto costa un'intera generazione; correggere a casaccio costa la
    fiducia. La regola sta in mezzo: si tolgono i segmenti iniziali **uno alla
    volta** e ci si ferma al primo resto che identifica una cosa sola.

    Niente casi speciali per nessuna stringa: nessun prefisso e' nominato qui.
    Restituisce `(id, nota)`; la nota e' vuota se non si e' corretto niente.
    """
    testo = str(raw or "").strip()
    if not testo:
        return "", ""
    if lookup(testo) is not None:
        return testo, ""

    tentativi = [testo.lower()]
    pezzi = testo.split(":")
    for taglio in range(1, len(pezzi)):
        coda = ":".join(pezzi[taglio:])
        tentativi.append(coda)
        tentativi.append(coda.lower())
    for candidato in tentativi:
        if candidato == testo:
            continue
        if ambiguous is not None and ambiguous(candidato):
            continue              # un alias che indica due cose non si indovina
        trovato = lookup(candidato)
        if trovato is not None:
            vero = getattr(trovato, "id", candidato)
            return vero, "'%s' normalizzato in '%s'" % (testo, vero)
    return "", ""


class ConceptResolver:
    """Select a validated concrete root from semantic planner output."""

    def __init__(self, registry, index=None) -> None:
        self.registry = registry
        self._index = index

    # ------------------------------------------------------- degradazione #
    def index(self):
        """L'indice semantico dei componenti. Quello di V1, non un altro."""
        if self._index is None:
            from app.core.planner.retrieval import build_index

            self._index = build_index(self.registry)
        return self._index

    def _words(self, requested: str) -> list[str]:
        """Le parole della richiesta piu' i ponti dichiarati dai plugin."""
        from app.assets.semantic import tokenize
        from app.core.planner.retrieval import thesaurus_for

        ponti = thesaurus_for(self.registry)
        fuori: list[str] = []
        for parola in tokenize(requested):
            if parola not in fuori:
                fuori.append(parola)
            for sinonimo in ponti.get(parola, ()):
                if sinonimo not in fuori:
                    fuori.append(sinonimo)
        return fuori

    def by_name(self, requested: str):
        """Un componente che si chiama cosi'.

        E' il gradino fra «id esatto» e «approssimazione»: chi chiede `fox` e ha
        installato `fox_stylized:fox` non sta approssimando niente.
        """
        testo = str(requested or "").strip().lower()
        if not testo:
            return None
        esatti = [c for c in self.registry.components()
                  if c.id.partition(":")[2].lower() == testo]
        if not esatti:
            return None
        return sorted(esatti, key=lambda c: c.id)[0]

    def candidates(self, requested: str, *, style: str = "",
                   limit: int = MAX_CANDIDATES) -> list[tuple[Any, float, bool]]:
        """I candidati all'approssimazione, in ordine deterministico.

        Si interroga l'indice con la richiesta intera e con ogni parola
        ampliata dai sinonimi dichiarati: una richiesta che nomina una famiglia
        che la libreria chiama in un altro modo deve comunque arrivarci.

        L'ordine non e' il punteggio puro. Un componente che fornisce una
        capability **soggetto** viene prima di uno che somiglia di piu' ma e' un
        pezzo: per «jeep» la ruota somiglia piu' dell'auto, e l'auto e' la
        risposta giusta.
        """
        indice = self.index()
        ammessi = {c.id: c for c in self.registry.components()
                   if c.supports_style(style)}
        soggetti = subject_capabilities(self.registry)

        punteggi: dict[str, float] = {}
        for query in [requested] + self._words(requested):
            if not str(query).strip():
                continue
            for cid, score in indice.search(query, limit=limit):
                if cid in ammessi and score > punteggi.get(cid, 0.0):
                    punteggi[cid] = float(score)

        fuori = []
        for cid, score in punteggi.items():
            componente = ammessi[cid]
            soggetto = any(c.name in soggetti for c in componente.provides)
            fuori.append((componente, score, soggetto))
        # chiave: prima i soggetti, poi chi puo' ospitare figli, poi il
        # punteggio, poi l'id. Tutto deterministico, nessuna somma pesata.
        fuori.sort(key=lambda voce: (not voce[2], not voce[0].mounts,
                                     -round(voce[1], 6), voce[0].id))
        return fuori[:limit]

    def _approximate(self, requested: str, plan, style: str) -> bool:
        """L'ultimo gradino prima del fallimento: il meglio che c'e'.

        Vero se ha scelto qualcosa. Il candidato scelto viene sempre dichiarato
        come approssimazione, con il suo punteggio: un'approssimazione taciuta
        e' una bugia, non un ripiego.
        """
        candidati = self.candidates(requested, style=style)
        plan.strategy.append("approssimazione semantica")
        if not candidati:
            self._diagnostic(plan, "CONCEPT_NO_CANDIDATE",
                             "nessun componente semanticamente vicino a '%s'"
                             % requested, requested)
            return False

        componente, score, soggetto = candidati[0]
        if score < MIN_CONFIDENCE:
            self._diagnostic(
                plan, "CONCEPT_TOO_FAR",
                "nessun componente abbastanza vicino a '%s': il migliore e' "
                "'%s' con punteggio %.3f" % (requested, componente.id, score),
                requested)
            return False

        plan.selected_root_implementation = componente.id
        plan.match = MATCH_SUBJECT if soggetto else MATCH_PROXY
        plan.confidence = round(float(score), 6)
        plan.coverage.append(ConceptCoverage(
            candidate=componente.id, hard_compatible=True, match=plan.match,
            reasons=["richiesto '%s', non installato" % requested,
                     "scelto per somiglianza semantica (%.3f)" % score]).to_dict())
        plan.candidate_bindings.extend(
            {"candidate": c.id, "score": round(float(s), 6), "subject": bool(j)}
            for c, s, j in candidati[:6])
        plan.provenance.update({
            "requested_concept": requested,
            "semantic_source": plan.semantic_source,
            "selected_root_implementation": componente.id,
            "match": plan.match,
            "confidence": plan.confidence,
            "registry_plugins": {p.id: p.version for p in self.registry.plugins()},
        })
        plan.diagnostics.append({
            "code": "CONCEPT_APPROXIMATED",
            "message": "'%s' non esiste: uso '%s' (%s, punteggio %.3f)"
                       % (requested, componente.id, plan.match, score),
            "severity": "warning", "where": requested})
        return True

    def resolve(self, requested_concept: str, *, archetypes: Iterable[str] = (),
                profiles: Iterable[str] = (), adaptations: Iterable[Any] = (),
                semantic_source: str = "local", style: str = "",
                implementation_hint: str = "") -> ConceptResolutionPlan:
        requested = str(requested_concept or "").strip()
        plan = ConceptResolutionPlan(requested_concept=requested,
                                     semantic_source=semantic_source or "local")

        # Gradino 1: l'id esatto. Chi lo nomina non sta approssimando niente.
        plan.strategy.append("id esatto")
        direct = self.registry.component(requested)
        if direct is not None:
            plan.selected_root_implementation = direct.id
            plan.match = MATCH_DIRECT
            plan.provenance.update({"requested_concept": requested,
                                    "semantic_source": "local_direct",
                                    "selected_root_implementation": direct.id,
                                    "match": MATCH_DIRECT})
            return plan

        # Gradino 2: il nome, senza il plugin davanti. `fox` -> `fox_stylized:fox`.
        plan.strategy.append("nome del componente")
        per_nome = self.by_name(requested)
        if per_nome is not None:
            plan.selected_root_implementation = per_nome.id
            plan.match = MATCH_NAME
            plan.provenance.update({"requested_concept": requested,
                                    "semantic_source": plan.semantic_source,
                                    "selected_root_implementation": per_nome.id,
                                    "match": MATCH_NAME})
            return plan

        plan.strategy.append("archetipi e binding")
        arch_ids = self._resolve_archetype_ids(archetypes, plan)
        profile_ids = self._resolve_profile_ids(profiles, plan)

        if not arch_ids and not profile_ids:
            exact_profile = self.registry.profile(requested)
            if exact_profile is not None:
                profile_ids = [exact_profile.id]
                for aid in exact_profile.archetypes:
                    if self.registry.archetype(aid) is not None and aid not in arch_ids:
                        arch_ids.append(self.registry.archetype(aid).id)
            else:
                exact_arch = self.registry.archetype(requested)
                if exact_arch is not None:
                    arch_ids = [exact_arch.id]
                    plan.semantic_source = "local"

        requested_arches = list(arch_ids)
        plan.archetypes = self._expand_archetypes(arch_ids, plan)
        plan.profiles = profile_ids
        if not plan.archetypes and not plan.profiles:
            # Nessun archetipo: non e' un fallimento, e' la condizione normale
            # di una libreria che non tiene un catalogo parallelo. Si scende al
            # gradino semantico, che lavora su cio' che i componenti dichiarano.
            plan.diagnostics.append({
                "code": "CONCEPT_UNKNOWN",
                "message": "'%s' non e' un concetto registrato: provo per "
                           "somiglianza semantica" % requested,
                "severity": "warning", "where": requested})
            self._approximate(requested, plan, style)
            return plan

        for pid in profile_ids:
            profile = self.registry.profile(pid)
            if profile is not None and profile.archetypes and not (
                    set(profile.archetypes) & set(plan.archetypes)):
                self._diagnostic(
                    plan, "PROFILE_INCOMPATIBLE",
                    "Profile '%s' non si applica agli Archetype richiesti" % pid,
                    pid)

        trait_defaults, structural_defaults, param_role_prefs, component_prefs, style_prefs = \
            self._materialize_defaults(plan.archetypes, profile_ids, plan)
        plan.adaptations = [item for item in
                            (self._adaptation(a) for a in adaptations) if item]
        self._validate_adaptation_conflicts(plan)
        plan.param_role_preferences = self._dedupe_dicts(param_role_prefs)
        plan.component_preferences = self._dedupe_dicts(component_prefs)
        plan.style_preferences = self._dedupe_dicts(style_prefs)
        candidates = self._candidates(plan.archetypes, requested_arches, plan, style)
        for binding, component, match in candidates:
            coverage = self._preflight(binding, component, plan, style,
                                       plan.adaptations)
            coverage.match = match
            coverage.score = self._score(coverage, plan.archetypes, component)
            plan.coverage.append(coverage.to_dict())

        plan.candidate_bindings = [dict(item) for item in plan.coverage]
        valid = [item for item in plan.coverage if item.get("hard_compatible")]
        valid.sort(key=lambda item: (tuple(-x for x in item.get("score", ())),
                                     item.get("candidate", "")))
        if not valid:
            # Nessun binding regge: non e' la fine della strada, e' la fine di
            # **questo** gradino. Il catalogo degli archetipi copre una parte
            # della libreria; cio' che i componenti dichiarano la copre tutta.
            plan.diagnostics.append({
                "code": "IMPLEMENTATION_NOT_FOUND",
                "message": "nessuna implementation dichiarata per '%s': provo "
                           "per somiglianza semantica" % requested,
                "severity": "warning", "where": requested})
            plan.provenance["implementation_hint"] = implementation_hint or ""
            plan.unsupported.extend({**item, "reason": "no compatible implementation"}
                                    for item in plan.adaptations)
            self._approximate(requested, plan, style)
            return plan

        selected = valid[0]
        plan.match = {"exact": MATCH_BINDING_EXACT,
                      "ancestor/body-plan proxy": MATCH_ANCESTOR,
                      "descendant/specialization implementation":
                          MATCH_SPECIALIZATION}.get(selected.get("match", ""),
                                                    MATCH_ANCESTOR)
        plan.selected_binding = selected["candidate"]
        binding = self.registry.implementation_binding(plan.selected_binding)
        plan.selected_root_implementation = binding.implementation
        plan.unsupported.extend(selected.get("unsupported", ()))
        plan.conflicts.extend(selected.get("conflicting", ()))
        plan.materialized_traits = self._dedupe_defaults(trait_defaults)
        plan.materialized_structural_traits = self._dedupe_defaults(structural_defaults,
                                                                    structural=True)
        plan.materialized_traits.extend(self._supported_adaptations(
            plan.adaptations, selected))
        plan.materialized_params.update(self._supported_params(selected))
        self._mark_materialized(selected)
        plan.provenance.update({
            "requested_concept": requested,
            "semantic_source": plan.semantic_source,
            "selected_binding": plan.selected_binding,
            "selected_root_implementation": plan.selected_root_implementation,
            "match": selected.get("match", ""),
            "implementation_hint": implementation_hint or "",
            "registry_plugins": {p.id: p.version for p in self.registry.plugins()},
        })
        return plan

    def _resolve_archetype_ids(self, values, plan) -> list[str]:
        return self._resolve_ids(values, plan, self.registry.archetype,
                                 self.registry.archetype_ambiguous, "Archetype",
                                 "ARCHETYPE_NOT_FOUND", "ARCHETYPE_ALIAS_AMBIGUOUS")

    def _resolve_profile_ids(self, values, plan) -> list[str]:
        return self._resolve_ids(values, plan, self.registry.profile,
                                 self.registry.profile_ambiguous, "Profile",
                                 "PROFILE_NOT_FOUND", "PROFILE_ALIAS_AMBIGUOUS")

    def _resolve_ids(self, values, plan, lookup, ambiguous, what,
                     missing_code, ambiguous_code) -> list[str]:
        """Gli id citati, ricondotti a quelli veri quando si puo'.

        Un id che non esiste **non** e' piu' un errore fatale: la diagnosi resta
        — chi legge deve sapere che il modello ha citato qualcosa di inventato —
        ma e' un avviso, e la risoluzione prosegue sui gradini successivi.
        """
        result: list[str] = []
        for value in values or ():
            grezzo = str(value)
            spec = lookup(grezzo)
            if spec is None:
                vero, nota = normalize_reference(grezzo, lookup, ambiguous)
                if vero:
                    spec = lookup(vero)
                    plan.diagnostics.append({
                        "code": "CONCEPT_ID_NORMALIZED", "message": nota,
                        "severity": "warning", "where": grezzo})
            if spec is None:
                code = ambiguous_code if ambiguous(grezzo) else missing_code
                plan.diagnostics.append({
                    "code": code,
                    "message": "%s non disponibile: '%s'" % (what, grezzo),
                    "severity": "warning", "where": grezzo})
                continue
            if spec.id not in result:
                result.append(spec.id)
        return result

    def _expand_archetypes(self, ids: list[str], plan) -> list[str]:
        out: list[str] = []

        def visit(aid: str, stack: tuple[str, ...] = ()) -> None:
            if aid in stack:
                self._diagnostic(plan, "ARCHETYPE_CYCLE",
                                 "ciclo Archetype: %s" % " -> ".join(stack + (aid,)), aid)
                return
            spec = self.registry.archetype(aid)
            if spec is None:
                self._diagnostic(plan, "ARCHETYPE_NOT_FOUND",
                                 "Archetype non disponibile: '%s'" % aid, aid)
                return
            for parent in sorted(spec.parents):
                visit(parent, stack + (aid,))
            if spec.id not in out:
                out.append(spec.id)

        for aid in ids:
            visit(aid)
        return out

    def _materialize_defaults(self, archetypes, profiles, plan):
        trait_layers = []
        structural_layers = []
        param_role_prefs, component_prefs, style_prefs = [], [], []
        depth_cache: dict[str, int] = {}

        def archetype_depth(aid: str) -> int:
            if aid in depth_cache:
                return depth_cache[aid]
            spec = self.registry.archetype(aid)
            parents = [p for p in (spec.parents if spec else ())
                       if self.registry.archetype(p) is not None]
            depth_cache[aid] = 0 if not parents else 1 + max(
                archetype_depth(p) for p in parents)
            return depth_cache[aid]

        for aid in archetypes:
            spec = self.registry.archetype(aid)
            if spec is None:
                continue
            rank = archetype_depth(aid)
            trait_layers.append((rank, aid, spec.default_traits))
            structural_layers.append((rank, aid, spec.structural_expectations))
            component_prefs.extend(_request(v) for v in spec.component_preferences)
            style_prefs.extend(_request(v) for v in spec.layout_preferences)
        seen_profiles: set[str] = set()

        def profile(profile_id: str, depth: int = 0) -> None:
            if profile_id in seen_profiles:
                self._diagnostic(plan, "PROFILE_CYCLE",
                                 "ciclo nei Profile includes: '%s'" % profile_id,
                                 profile_id)
                return
            spec = self.registry.profile(profile_id)
            if spec is None:
                return
            seen_profiles.add(profile_id)
            for included in sorted(spec.includes):
                profile(included, depth + 1)
            # Included profiles are defaults for their includer. Reversing the
            # recursion depth gives the including profile higher precedence.
            rank = 10_000 - depth
            trait_layers.append((rank, profile_id, spec.default_traits))
            structural_layers.append((rank, profile_id, spec.structural_defaults))
            param_role_prefs.extend(_request(v) for v in spec.param_role_preferences)
            component_prefs.extend(_request(v) for v in spec.component_preferences)
            style_prefs.extend(_request(v) for v in spec.style_preferences)
            seen_profiles.remove(profile_id)

        for pid in profiles:
            profile(pid)
        traits = self._merge_layers(trait_layers, plan, "TRAIT_DEFAULT_CONFLICT")
        structural = self._merge_layers(structural_layers, plan,
                                        "STRUCTURAL_DEFAULT_CONFLICT", structural=True)
        return traits, structural, param_role_prefs, component_prefs, style_prefs

    def _merge_layers(self, layers, plan, code, structural=False):
        declarations: dict[tuple, list[tuple[int, str, dict]]] = {}
        for layer in layers:
            if len(layer) == 3 and isinstance(layer[0], int):
                rank, source, values = layer
            else:
                rank, source, values = 0, "", layer
            for raw in values or ():
                item = _request(raw)
                if not item.get("trait"):
                    continue
                key = _request_key(item, structural=structural)
                declarations.setdefault(key, []).append((rank, source, item))
        merged = []
        provenance = plan.provenance.setdefault("materialized_defaults", [])
        for key in sorted(declarations, key=repr):
            choices = declarations[key]
            winning_rank = max(rank for rank, _, _ in choices)
            winners = [(source, item) for rank, source, item in choices
                       if rank == winning_rank]
            values = {repr(item.get("value")) for _, item in winners}
            if len(values) > 1:
                conflict = {"channel": list(key), "sources": [s for s, _ in winners],
                            "values": [item for _, item in winners]}
                plan.conflicts.append(conflict)
                self._diagnostic(plan, code,
                                 "default incompatibili sul channel '%s'" % (key,),
                                 str(key))
                continue
            source, item = sorted(winners, key=lambda entry: entry[0])[0]
            merged.append(item)
            provenance.append({"channel": list(key), "source": source,
                               "value": item.get("value")})
        return merged

    def _candidates(self, archetypes, requested_archetypes, plan, style):
        out = []
        for binding in self.registry.implementation_bindings():
            component = self.registry.component(binding.implementation)
            if component is None:
                continue
            match = self._binding_match(binding, archetypes, requested_archetypes)
            if match:
                out.append((binding, component, match))
        return out

    def _binding_match(self, binding, expanded, requested) -> str:
        supported = set(binding.supported_archetypes)
        if supported & set(requested):
            return "exact"
        if supported & set(self._ancestors_of(expanded)):
            return "ancestor/body-plan proxy"
        requested_set = set(requested)
        if any(requested_set & set(self._archetype_ancestors(aid))
               for aid in sorted(supported)):
            return "descendant/specialization implementation"
        return ""

    def _ancestors_of(self, requested):
        # `requested` is already expanded ancestor-first; excluding the last
        # exact ids yields the proxy candidates without any name inference.
        return list(requested)

    def _archetype_ancestors(self, archetype_id: str) -> list[str]:
        out: list[str] = []
        visited: set[str] = set()

        def visit(aid: str, stack: tuple[str, ...] = ()) -> None:
            if aid in stack or aid in visited:
                return
            visited.add(aid)
            spec = self.registry.archetype(aid)
            if spec is None:
                return
            for parent in sorted(spec.parents):
                if parent not in out:
                    out.append(parent)
                visit(parent, stack + (aid,))

        visit(archetype_id)
        return out

    def _declarative_subtree(self, root, style: str):
        """Walk declared Components without building meshes or resolving poses."""
        from app.core.component import BuildContext

        out = []
        pending = [(root.id.partition(":")[2] or root.id, root,
                    {name: spec.default for name, spec in root.params.items()}, 0)]
        while pending and len(out) < 200:
            path, component, values, depth = pending.pop(0)
            out.append((path, component))
            if component.children is None or depth >= 12:
                continue
            ctx = BuildContext(style=style or "low_poly", detail_level=5,
                               depth=depth, seed=0, path=path)
            try:
                attachments = component.expand(values, ctx)
            except Exception:  # preflight remains conservative and mesh-free
                continue
            for attachment in attachments:
                child = self._component_ref(attachment.component, component.plugin)
                if child is None:
                    continue
                child_values = {name: spec.default
                                for name, spec in child.params.items()}
                for name, value in attachment.params.items():
                    if name in child.params:
                        try:
                            child_values[name] = child.params[name].coerce(value)
                        except (TypeError, ValueError):
                            pass
                pending.append((path + "/" + attachment.id, child,
                                child_values, depth + 1))
        return out

    def _component_ref(self, ref: str, home: str):
        if ":" in ref:
            return self.registry.component(ref)
        local = self.registry.component("%s:%s" % (home, ref)) if home else None
        if local is not None:
            return local
        candidates = self.registry.named(ref)
        return candidates[0] if len(candidates) == 1 else None

    def _preflight(self, binding, component, plan, style, adaptations):
        coverage = ConceptCoverage(candidate=binding.id)
        subtree = self._declarative_subtree(component, style)
        components = [item[1] for item in subtree]
        role_groups, capability_groups = [], []
        preferred_roles, preferred_caps = set(), set()
        for aid in plan.archetypes:
            spec = self.registry.archetype(aid)
            if spec is None:
                continue
            if spec.required_roles:
                role_groups.append((aid, set(spec.required_roles)))
            if spec.required_capabilities:
                capability_groups.append((aid, set(spec.required_capabilities)))
            preferred_roles |= set(spec.preferred_roles)
            preferred_caps |= set(spec.preferred_capabilities)
        roles = {item.role for item in components if item.role}
        caps = {c.name for item in components for c in item.provides}
        caps |= {m.capability for item in components for m in item.mounts
                 if m.capability}
        hard = True
        for aid, alternatives in role_groups:
            if not (roles & alternatives):
                hard = False
                coverage.conflicting.append({"kind": "required_role", "source": aid,
                                              "alternatives": sorted(alternatives)})
        for aid, alternatives in capability_groups:
            if not (caps & alternatives):
                hard = False
                coverage.conflicting.append({"kind": "required_capability",
                                              "source": aid,
                                              "alternatives": sorted(alternatives)})
        if style and not component.supports_style(style):
            hard = False
            coverage.conflicting.append({"kind": "style", "value": style})
        coverage.hard_compatible = hard
        coverage.preferred_hits = len((roles & preferred_roles) |
                                      (caps & preferred_caps))
        for preference in plan.param_role_preferences:
            role = str(preference.get("param_role") or preference.get("role") or "")
            if role and any(getattr(spec, "semantic_role", "") == role
                            for item in components for spec in item.params.values()):
                coverage.preferred_hits += 1
        for preference in plan.component_preferences:
            role = str(preference.get("role") or "")
            capability = str(preference.get("capability") or "")
            if ((role and role in roles) or
                    (capability and capability in caps)):
                coverage.preferred_hits += 1
        for adaptation in adaptations:
            self._cover_adaptation(adaptation, component, style, coverage, subtree)
        coverage.reasons.append("binding=%s" % binding.id)
        if not hard:
            coverage.reasons.append("hard requirements failed")
        return coverage

    def _cover_adaptation(self, adaptation, component, style, coverage, subtree):
        item = dict(adaptation)
        trait_id = str(item.get("trait") or "")
        if trait_id:
            trait = self.registry.trait(trait_id)
            if trait is not None:
                nodes = subtree if str(item.get("scope") or "subtree") == "subtree" \
                    else subtree[:1]
                rules = self.registry.trait_rules(trait.id)
                matching = [(path, candidate) for path, candidate in nodes
                            if any(self._trait_rule_matches(rule, candidate, style)
                                   for rule in rules)]
                unmatched = [(path, candidate) for path, candidate in nodes
                             if not any(self._trait_rule_matches(rule, candidate, style)
                                        for rule in rules)]
                ignored = [(path, candidate) for path, candidate in unmatched
                           if self._decorative(candidate)]
                unsupported = [(path, candidate) for path, candidate in unmatched
                               if not self._decorative(candidate)]
                detail = self._coverage_detail(
                    item, True, matching, unsupported, ignored,
                    "fully_supported" if matching and not unsupported
                    else "partially_supported" if matching else "unsupported")
                if matching:
                    coverage.supported.append({**item, "coverage_details": detail})
                else:
                    coverage.unsupported.append({**item,
                                                 "reason": "no matching TraitRule",
                                                 "coverage_details": detail})
                return
            structural = self.registry.structural_trait(trait_id)
            if structural is not None:
                rules = self.registry.structural_trait_rules(structural.id)
                matching = [(path, candidate) for path, candidate in subtree[:1]
                            if not rules or any(
                                self._structural_rule_matches(rule, candidate)
                                for rule in rules)]
                unsupported = [] if matching else subtree[:1]
                detail = self._coverage_detail(
                    item, True, matching, unsupported, [],
                    "fully_supported" if matching else "unsupported")
                if matching:
                    coverage.supported.append({**item, "coverage_details": detail})
                else:
                    coverage.unsupported.append({**item,
                                                 "reason": "no matching StructuralTraitRule",
                                                 "coverage_details": detail})
                return
            coverage.unsupported.append({
                **item, "reason": "contract not registered",
                "coverage_details": self._coverage_detail(
                    item, False, [], subtree, [], "unsupported")})
            return
        param = str(item.get("param") or "")
        role = str(item.get("param_role") or "")
        if param and param in component.params:
            if component.params[param].derived:
                coverage.unsupported.append({
                    **item, "reason": "derived parameter is read-only",
                    "coverage_details": self._coverage_detail(
                        item, True, [], subtree[:1], [], "unsupported")})
                return
            try:
                component.params[param].coerce(item.get("value"))
            except (TypeError, ValueError) as exc:
                coverage.unsupported.append({
                    **item, "reason": str(exc),
                    "coverage_details": self._coverage_detail(
                        item, True, [], subtree[:1], [], "unsupported")})
            else:
                coverage.supported.append({**item, "coverage_details":
                    self._coverage_detail(item, True, subtree[:1], [], [],
                                          "fully_supported")})
        elif role:
            matches = sorted(name for name, spec in component.params.items()
                             if not spec.derived and
                             getattr(spec, "semantic_role", "") == role)
            if len(matches) == 1:
                coverage.supported.append({**item, "resolved_param": matches[0],
                                           "coverage_details":
                    self._coverage_detail(item, True, subtree[:1], [], [],
                                          "fully_supported")})
            elif len(matches) > 1:
                coverage.unsupported.append({
                    **item, "reason": "ambiguous parameter role",
                    "coverage_details": self._coverage_detail(
                        item, True, [], subtree[:1], [], "unsupported")})
            else:
                coverage.unsupported.append({
                    **item, "reason": "public parameter unavailable",
                    "coverage_details": self._coverage_detail(
                        item, False, [], subtree[:1], [], "unsupported")})
        else:
            coverage.unsupported.append({
                **item, "reason": "public parameter unavailable",
                "coverage_details": self._coverage_detail(
                    item, False, [], subtree[:1], [], "unsupported")})

    @staticmethod
    def _decorative(component) -> bool:
        return component.role in ("accent", "detail") or bool(
            {"accent", "detail"} & set(component.tags))

    @staticmethod
    def _coverage_detail(requested, contract_found, supported, unsupported, ignored,
                         classification):
        def entries(values):
            return [{"path": path, "component": component.id,
                     "role": component.role} for path, component in values]

        return {"requested": dict(requested),
                "contract_found": bool(contract_found),
                "where_supported": entries(supported),
                "where_unsupported": entries(unsupported),
                "where_ignored": entries(ignored),
                "coverage": classification,
                "materialized": False}

    @staticmethod
    def _trait_rule_matches(rule, component, style):
        match = rule.match
        tags = set(component.tags)
        caps = {c.name for c in component.provides}
        caps |= {m.capability for m in component.mounts if m.capability}
        roles = set(match.roles)
        return ((not match.styles or style in match.styles) and
                (not roles or component.role in roles) and
                (not match.tags or set(match.tags) <= tags) and
                (not match.capabilities or any(c in caps for c in match.capabilities)) and
                (not match.param_roles or any(getattr(p, "semantic_role", "") in
                                               match.param_roles
                                               for p in component.params.values())) and
                (not match.params or any(p in component.params for p in match.params)) and
                (not match.components or component.id in match.components or
                 component.name in match.components))

    @staticmethod
    def _structural_rule_matches(rule, component):
        target = rule.target
        return ((not target.role or target.role == component.role) and
                (not target.capability or component.provides_capability(target.capability)) and
                (not target.tags or set(target.tags) <= set(component.tags)) and
                (not target.components or component.id in target.components or
                 component.name in target.components))

    @staticmethod
    def _score(coverage, archetypes, component):
        match_rank = {"exact": 2,
                      "descendant/specialization implementation": 1}.get(
                          coverage.match, 0)
        supported = len(coverage.supported)
        unsupported = len(coverage.unsupported)
        conflicting = len(coverage.conflicting)
        family_surface = len(component.provides) + len(component.mounts)
        return (match_rank, supported, coverage.preferred_hits, family_surface, -unsupported,
                -conflicting, -len(archetypes))

    @staticmethod
    def _adaptation(value):
        return dict(value) if isinstance(value, dict) else {}

    @staticmethod
    def _dedupe_defaults(values, structural=False):
        out, seen = [], set()
        for value in values:
            item = _request(value)
            key = _request_key(item, structural=structural)
            if key not in seen:
                seen.add(key)
                out.append(item)
        return out

    @staticmethod
    def _dedupe_dicts(values):
        out, seen = [], set()
        for value in values:
            item = _request(value)
            key = repr(sorted(item.items()))
            if key not in seen:
                seen.add(key)
                out.append(item)
        return out

    @staticmethod
    def _supported_adaptations(adaptations, selected):
        supported = selected.get("supported", ())
        return [v for v in adaptations
                if v.get("trait") and any(
                    all(candidate.get(key) == value for key, value in v.items())
                    for candidate in supported)]

    @staticmethod
    def _supported_params(selected):
        params = {}
        for item in selected.get("supported", ()):
            name = str(item.get("param") or item.get("resolved_param") or "")
            if name:
                params[name] = item.get("value")
        return params

    @staticmethod
    def _mark_materialized(selected):
        for item in selected.get("supported", ()):
            details = item.get("coverage_details")
            if isinstance(details, dict):
                details["materialized"] = True

    @staticmethod
    def _validate_adaptation_conflicts(plan):
        channels: dict[tuple[str, str], dict[str, Any]] = {}
        for item in plan.adaptations:
            if item.get("trait"):
                channel = ("trait", str(item["trait"]))
            elif item.get("param"):
                channel = ("param", str(item["param"]))
            elif item.get("param_role"):
                channel = ("param_role", str(item["param_role"]))
            else:
                continue
            previous = channels.get(channel)
            if previous is not None and previous.get("value") != item.get("value"):
                conflict = {"channel": list(channel), "existing": previous,
                            "incoming": item}
                plan.conflicts.append(conflict)
                ConceptResolver._diagnostic(
                    plan, "ADAPTATION_CONFLICT",
                    "adattamenti incompatibili sul channel '%s'" % (channel,),
                    str(channel))
            else:
                channels[channel] = item

    @staticmethod
    def _diagnostic(plan, code, message, where=""):
        plan.diagnostics.append({"code": code, "message": message,
                                 "severity": "error", "where": where})


def resolve_concept(registry, requested_concept: str, **kwargs) -> ConceptResolutionPlan:
    return ConceptResolver(registry).resolve(requested_concept, **kwargs)
