"""La specifica tecnica di un componente mancante. **La decide 3DGen, non l'AI.**

E' §22 della milestone, e la frase del titolo e' il punto: quando un nodo e'
`MISSING`, cio' che manca e' geometria, non un contratto. Il contratto lo
possiede il sistema — sa quale capability il padre accetta, quali figli sono
gia' validati, quale convenzione d'asse vale in quel punto dell'albero, quanti
triangoli costano i pezzi simili che ha gia' — e lo scrive **prima** di
chiedere niente a nessuno. Il modello riceve una specifica gia' decisa e la
implementa.

Tutto si deriva da dati dichiarati:

    il padre            la capability che accetta, e la sua convenzione d'asse
    i figli validati    i loro id, i loro requirement, i loro parametri
    i fratelli          che cosa la libreria si aspetta accanto a questa parte
    la libreria         i ruoli semantici che i pezzi con lo stesso ruolo
                        dichiarano, e i triangoli che costano davvero
    il nodo             ruolo, count, detail level, importanza, descrizione

## La raccomandazione di backend, e perche' non e' una tabella di parole

§23 chiede una raccomandazione fra `procedural_python`, `data_mesh` e
`composite`, e vieta di cablare «tail», «horn» o qualunque altro nome nel
motore. La regola e' percio' **strutturale**, e si legge in tre righe:

    composite           tutti i figli mandatory che servono a questo livello
                        sono gia' soddisfatti: non c'e' niente da modellare,
                        il nodo **e'** la disposizione di pezzi che esistono
    data_mesh           per questo nodo e' stato fornito un GLB: la forma
                        esiste gia' e va dichiarata, non generata
    procedural_python   tutto il resto, e la ragione e' onesta: 3DGen non puo'
                        generare un GLB da un testo (§23 lo dice), quindi
                        raccomandare `data_mesh` senza un asset vorrebbe dire
                        raccomandare una cosa che il sistema non sa fare

I tre restano sempre elencati in `backend_candidates`, in quest'ordine di
preferenza, e l'utente li cambia: e' una raccomandazione, non un obbligo.

## La coda, e perche' e' dai dettagli verso l'alto

§21 chiede un ordine dependency-aware: parti fini riutilizzabili, poi i
composite intermedi, poi le parti principali, poi la radice. L'ordine e' quindi
**topologico sui discendenti** (un nodo non viene prima di una sua parte), poi
per profondita' decrescente (piu' profondo = piu' fine), poi per importanza
**crescente** — i dettagli utili prima delle parti principali, che e' la frase
della milestone — poi per id, cosi' e' deterministico.

Un nodo con figli ancora mancanti non e' bloccato se la sua implementazione e'
indipendente: un pezzo procedurale non ha bisogno dei suoi figli per esistere,
un composite si'. Vedi `next_buildable`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.authoring.model import check_name
from app.teach.model import (BACKENDS, COMPOSITE, DATA_MESH, PROCEDURAL,
                             VALIDATED, TeachNode, TeachProject, slug)

# Il budget dichiarato quando non c'e' niente da misurare. E' un valore
# dichiarato, non una misura, e `ComponentSpec.notes` lo dice: un numero
# presentato come misura quando non lo e' sarebbe la bugia peggiore di tutte.
DEFAULT_TRIANGLE_BUDGET = 240
BUDGET_HEADROOM = 1.5          # quanto si concede sopra la mediana misurata
MAX_REFERENCES = 3


def component_name_for(project: TeachProject, node: TeachNode) -> str:
    """Il nome di file e di id che il componente nuovo avra'.

    Passa da `check_name` di V6: quel nome diventa `plugin:nome` e
    `meshes/nome.glb`, quindi uno spazio o un `..` sarebbero un id e un
    percorso insieme. Se due nodi si ridurrebbero allo stesso nome vince il
    primo e il secondo prende il prefisso del padre: un id duplicato in un
    plugin e' un plugin che non si carica.
    """
    base = slug(node.name, "part")
    taken = set()
    for other in project.nodes():
        if other.id == node.id:
            break
        taken.add(slug(other.name, "part"))
    if base in taken:
        parent = project.parent_of(node.id)
        if parent is not None:
            base = "%s_%s" % (slug(parent.name, "part"), base)
    return check_name(base, "nome del componente")


def plugin_for(project: TeachProject, node: TeachNode) -> str:
    """In quale plugin finisce il componente generato per questo nodo.

    Uno per componente, piu' uno per la radice: le tre ragioni stanno accanto a
    `TeachProject.plugin_named`, e la prima e' che un plugin dati non puo'
    contenere Python.
    """
    if project.root is not None and node.id == project.root.id:
        return project.pack_plugin
    return project.plugin_named(component_name_for(project, node))


def _semantic_roles(registry, node: TeachNode) -> tuple[str, ...]:
    """I ruoli semantici che la libreria dichiara per parti di questo ruolo.

    Si leggono dai componenti installati con lo stesso `role`; se nessuno ha
    quel ruolo, si leggono dai ruoli che i **trait installati** sanno pilotare,
    perche' dichiararne uno di quelli e' il modo di far arrivare la
    variabilita' esistente a un pezzo nuovo (V5 §2). Nessun elenco nel codice.
    """
    wanted = slug(node.role, "")
    found: set[str] = set()
    if wanted:
        for component in registry.components():
            if slug(component.role, "") != wanted:
                continue
            found |= {getattr(s, "semantic_role", "")
                      for s in component.params.values()
                      if getattr(s, "semantic_role", "")}
    if found:
        return tuple(sorted(found))
    for rule in registry.trait_rules():
        for patch in getattr(rule, "patches", ()) or ():
            role = getattr(patch, "semantic_role", "")
            if role:
                found.add(role)
    return tuple(sorted(found))


def _references(project: TeachProject, node: TeachNode, registry,
                limit: int = MAX_REFERENCES) -> tuple[str, ...]:
    """I componenti installati che somigliano a questa parte, per ruolo o per tag.

    Non sono esempi scelti a mano: sono cio' che la libreria ha di piu' vicino,
    e servono al prompt come riferimento di stile e di costo. Vengono ordinati
    con il punteggio che i candidati del nodo hanno gia'.
    """
    from app.teach.coverage import variants

    wanted_role = slug(node.role, "")
    names = set(variants(node.name)) | set(variants(node.role))
    scores = {c.component_id: c.score for c in project.state(node.id).candidates}
    found: list[tuple[float, str]] = []
    for component in registry.components():
        if project.owns(component.id):
            continue
        same_role = bool(wanted_role) and slug(component.role, "") == wanted_role
        same_name = bool(names & {str(t).lower() for t in component.tags})
        if not (same_role or same_name):
            continue
        found.append((-scores.get(component.id, 0.0), component.id))
    found.sort()
    return tuple(cid for _, cid in found[:max(0, int(limit))])


def _measured_budget(session, references, *, style: str,
                     detail_level: int) -> tuple[int, str]:
    """Il budget di triangoli, misurato costruendo i riferimenti.

    Misurato e non dichiarato quando si puo': i pezzi simili che la libreria ha
    costruiscono un numero di triangoli vero, e la mediana di quelli piu' un
    margine e' un tetto onesto. Senza riferimenti, o senza sessione, resta il
    valore dichiarato — e la nota lo dice.
    """
    if session is None or not references:
        return DEFAULT_TRIANGLE_BUDGET, ("budget dichiarato (nessun riferimento "
                                         "da misurare)")
    from app.core.session import Options

    counts: list[int] = []
    for ref in references:
        plan = {"version": "1.3", "style": style, "detail_level": int(detail_level),
                "seed": 0, "root": {"id": "subject", "ref": ref}}
        try:
            result = session.build(plan, Options(style=style,
                                                 detail_level=int(detail_level),
                                                 check=False))
        except Exception:                                  # noqa: BLE001
            continue
        if result is not None and result.triangles:
            counts.append(int(result.triangles))
    if not counts:
        return DEFAULT_TRIANGLE_BUDGET, ("budget dichiarato (i riferimenti non "
                                         "si sono costruiti)")
    counts.sort()
    median = counts[len(counts) // 2]
    return (max(24, int(round(median * BUDGET_HEADROOM))),
            "budget misurato: mediana %d triangoli su %d riferimenti, piu' il %d%%"
            % (median, len(counts), int((BUDGET_HEADROOM - 1.0) * 100)))


def _frame_for(project: TeachProject, node: TeachNode, registry) -> dict:
    """La convenzione d'asse che vale in questo punto dell'albero.

    Quella del padre, se il padre ha un componente che la dichiara; altrimenti
    quella del suo plugin. Se nessuno la dichiara, **vuota**: un frame
    inventato insegnerebbe una convenzione che nessuno ha scritto, ed e' la
    regola 27 di `PROJECT-INDEX`.
    """
    parent = project.parent_of(node.id)
    if parent is None:
        return {}
    state = project.state(parent.id)
    ref = ""
    if state.solution is not None:
        ref = state.solution.ref
    elif state.candidates:
        ref = state.candidates[0].component_id
    component = registry.component(ref) if ref else None
    if component is None:
        return {}
    frame = component.frame
    if frame is None or getattr(frame, "empty", True):
        info = registry.plugin(component.plugin)
        frame = getattr(info, "frame", None)
    if frame is None or getattr(frame, "empty", True):
        return {}
    return {k: v for k, v in (("growth_axis", frame.growth_axis),
                              ("front", frame.front), ("up", frame.up)) if v}


def _parent_capability(project: TeachProject, node: TeachNode,
                       registry) -> tuple[str, str, bool]:
    """La capability che il nodo deve **fornire** per attaccarsi al padre.

    Tre casi, in quest'ordine:

        il padre ha un componente     si sceglie fra cio' che quel componente
                                      accetta: prima una capability che un
                                      pezzo installato con lo stesso ruolo del
                                      nodo fornisce davvero, poi una che un
                                      candidato del nodo fornisce, poi la prima
        il padre non ne ha            il padre sara' un composite scritto da
                                      noi, quindi la capability si **dichiara**
                                      nuova: `<ruolo>_mount`. Dichiararne una
                                      e' dati, non codice (V6 §9)
        non c'e' padre                e' la radice: non si attacca a niente
    """
    parent = project.parent_of(node.id)
    if parent is None:
        return "", "", False
    state = project.state(parent.id)
    ref = state.solution.ref if state.solution is not None else (
        state.candidates[0].component_id if state.candidates else "")
    known = set(registry.capabilities())
    component = registry.component(ref) if ref else None
    if component is None:
        declared = "%s_mount" % slug(node.role or node.name, "part")
        return declared, "", declared not in known
    accepted = sorted({m.capability for m in component.mounts if m.capability})
    if not accepted:
        declared = "%s_mount" % slug(node.role or node.name, "part")
        return declared, component.id, declared not in known
    wanted_role = slug(node.role, "")
    if wanted_role:
        for capability in accepted:
            for other in registry.providers(capability):
                if not other.provides_capability(capability):
                    continue
                if slug(other.role, "") == wanted_role:
                    return capability, component.id, False
    for candidate in project.state(node.id).candidates:
        other = registry.component(candidate.component_id)
        if other is None:
            continue
        shared = {c.name for c in other.provides} & set(accepted)
        if shared:
            return sorted(shared)[0], component.id, False
    return accepted[0], component.id, False


# --------------------------------------------------------------------------- #
# La specifica
# --------------------------------------------------------------------------- #
@dataclass
class ComponentSpec:
    """Il contratto di un componente che non esiste ancora. Deciso da 3DGen."""

    node: str
    component_id: str
    name: str
    plugin_id: str = ""
    role: str = ""
    description: str = ""
    mandatory: bool = True
    count: int = 1
    detail_level: int = 2
    importance: float = 0.5
    style: str = "low_poly"
    style_target: str = ""
    backend: str = PROCEDURAL
    backend_candidates: tuple[str, ...] = BACKENDS
    backend_reason: str = ""
    provides: tuple[str, ...] = ()
    declares_capability: bool = False
    parent: str = ""
    parent_component: str = ""
    mounts: tuple[dict, ...] = ()
    required_sockets: tuple[dict, ...] = ()
    semantic_parameters: tuple[str, ...] = ()
    children: tuple[dict, ...] = ()
    siblings: tuple[dict, ...] = ()
    frame: dict = field(default_factory=dict)
    triangle_budget: int = DEFAULT_TRIANGLE_BUDGET
    reference_components: tuple[str, ...] = ()
    asset: str = ""
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("backend_candidates", "provides", "mounts",
                     "required_sockets", "semantic_parameters", "children",
                     "siblings", "reference_components", "notes"):
            setattr(self, name, tuple(getattr(self, name)))

    def to_dict(self) -> dict:
        data: dict[str, Any] = {
            "node": self.node, "id": self.component_id, "name": self.name,
            "plugin": self.plugin_id,
            "role": self.role, "description": self.description,
            "mandatory": bool(self.mandatory), "count": int(self.count),
            "detail_level": int(self.detail_level),
            "importance": round(float(self.importance), 3),
            "style": self.style, "style_target": self.style_target,
            "backend": self.backend,
            "backend_candidates": list(self.backend_candidates),
            "backend_reason": self.backend_reason,
            "provides": list(self.provides),
            "declares_capability": bool(self.declares_capability),
            "parent": self.parent, "parent_component": self.parent_component,
            "mounts": [dict(m) for m in self.mounts],
            "required_sockets": [dict(s) for s in self.required_sockets],
            "semantic_parameters": list(self.semantic_parameters),
            "children": [dict(c) for c in self.children],
            "siblings": [dict(s) for s in self.siblings],
            "frame": dict(self.frame),
            "triangle_budget": int(self.triangle_budget),
            "reference_components": list(self.reference_components),
            "notes": list(self.notes)}
        if self.asset:
            data["asset"] = self.asset
        return data

    def describe(self) -> str:
        return "%s -> %s (%s, budget %d tri)" % (self.node, self.component_id,
                                                 self.backend,
                                                 self.triangle_budget)


def recommend_backend(project: TeachProject, node: TeachNode) -> tuple[str, tuple[str, ...], str]:
    """La raccomandazione, piu' l'ordine completo e la ragione. Vedi la testata."""
    wanted = [c for c in node.children if c.mandatory and project.relevant(c)]
    satisfied = [c for c in wanted
                 if project.state(c.id).coverage == VALIDATED]
    state = project.state(node.id)
    if wanted and len(satisfied) == len(wanted):
        reason = ("tutti i %d figli mandatory di questo livello sono validati: "
                  "il nodo e' la loro disposizione, non una forma nuova"
                  % len(wanted))
        order = (COMPOSITE, PROCEDURAL, DATA_MESH)
    elif state.asset:
        reason = ("per questo nodo e' stato fornito un asset (%s): la forma "
                  "esiste e va dichiarata, non generata" % state.asset)
        order = (DATA_MESH, COMPOSITE, PROCEDURAL)
    else:
        reason = ("nessun asset fornito e %s: 3DGen non puo' generare un GLB da "
                  "un testo, quindi la sola forma ottenibile e' parametrica"
                  % ("%d figli mandatory su %d ancora non validati"
                     % (len(wanted) - len(satisfied), len(wanted)) if wanted
                     else "il nodo non ha figli mandatory a questo livello"))
        order = (PROCEDURAL, COMPOSITE, DATA_MESH) if wanted else \
            (PROCEDURAL, DATA_MESH, COMPOSITE)
    chosen = state.backend if state.backend in BACKENDS else order[0]
    if chosen != order[0]:
        reason = "scelto dall'utente (%s); la raccomandazione era %s" % (
            chosen, order[0])
        order = (chosen,) + tuple(b for b in order if b != chosen)
    return chosen, order, reason


def build_spec(project: TeachProject, node_id: str, registry, *,
               session=None) -> ComponentSpec:
    """La specifica tecnica di un nodo. Deterministica a parita' di libreria."""
    node = project.require_node(node_id)
    state = project.state(node_id)
    parent = project.parent_of(node_id)
    capability, parent_component, declares = _parent_capability(project, node,
                                                                registry)
    backend, order, reason = recommend_backend(project, node)

    mounts: list[dict] = []
    sockets: list[dict] = [{
        "name": "base",
        "purpose": "own_socket: dove questa parte si attacca a chi la contiene",
        "direction": "verso l'esterno, opposto all'asse di crescita"}]
    children: list[dict] = []
    for child in node.children:
        if not project.relevant(child):
            continue
        child_state = project.state(child.id)
        satisfied = child_state.coverage == VALIDATED and child_state.solution
        child_component = registry.component(
            child_state.solution.ref) if satisfied else None
        if child_component is not None:
            provided = sorted({c.name for c in child_component.provides})
            child_capability = provided[0] if provided else (
                "%s_mount" % slug(child.role or child.name, "part"))
        else:
            child_capability = "%s_mount" % slug(child.role or child.name, "part")
        socket_name = slug(child.name, "child")
        mounts.append({"capability": child_capability, "socket_id": socket_name,
                       "for": child.id, "count": int(child.count),
                       "mandatory": bool(child.mandatory)})
        sockets.append({"name": socket_name,
                        "purpose": "ospita %s%s" % (child.name,
                                                    "" if child.count == 1
                                                    else " x%d" % child.count),
                        "capability": child_capability})
        if child_component is not None:
            entry = {"id": socket_name, "component": child_state.solution.ref,
                     "level": int(child.detail_level),
                     "requirement": {"capability": child_capability},
                     "count": int(child.count)}
            if child_state.solution.params:
                entry["params"] = dict(child_state.solution.params)
            children.append(entry)

    siblings: list[dict] = []
    if parent is not None:
        for other in parent.children:
            if other.id == node.id or not project.relevant(other):
                continue
            other_state = project.state(other.id)
            siblings.append({
                "node": other.id, "name": other.name, "role": other.role,
                "count": int(other.count), "coverage": other_state.coverage,
                "component": "" if other_state.solution is None
                else other_state.solution.ref})

    references = _references(project, node, registry)
    budget, budget_note = _measured_budget(session, references,
                                           style=project.style,
                                           detail_level=node.detail_level)
    notes = [budget_note, reason]
    if declares:
        notes.append("la capability %r non e' installata: il componente la "
                     "dichiara, e il composite del padre la accettera'"
                     % capability)
    if node.count > 1:
        notes.append("il nodo compare %d volte: una parte sola, montata %d "
                     "volte dal padre, non %d componenti"
                     % (node.count, node.count, node.count))

    name = component_name_for(project, node)
    plugin_id = plugin_for(project, node)
    return ComponentSpec(
        node=node.id, component_id="%s:%s" % (plugin_id, name),
        name=name, plugin_id=plugin_id, role=node.role,
        description=node.description, mandatory=node.mandatory, count=node.count,
        detail_level=node.detail_level, importance=node.importance,
        style=project.style, style_target=project.style_target,
        backend=backend, backend_candidates=order, backend_reason=reason,
        provides=(capability,) if capability else (),
        declares_capability=declares,
        parent="" if parent is None else parent.id,
        parent_component=parent_component, mounts=tuple(mounts),
        required_sockets=tuple(sockets), children=tuple(children),
        siblings=tuple(siblings),
        semantic_parameters=_semantic_roles(registry, node),
        frame=_frame_for(project, node, registry), triangle_budget=budget,
        reference_components=references, asset=state.asset, notes=tuple(notes))


# --------------------------------------------------------------------------- #
# La coda
# --------------------------------------------------------------------------- #
def _unsatisfied_descendants(project: TeachProject, node: TeachNode) -> int:
    return sum(1 for other in node.walk()
               if other.id != node.id and other.mandatory
               and project.relevant(other)
               and project.state(other.id).coverage != VALIDATED)


def build_queue(project: TeachProject) -> list[TeachNode]:
    """I nodi mandatory ancora da soddisfare, dai dettagli verso la radice.

    Topologico sui discendenti, poi profondita' decrescente, poi importanza
    crescente, poi id. Vedi la testata per il perche' dell'importanza crescente.
    """
    wanted = project.mandatory_missing()
    return sorted(wanted, key=lambda n: (_unsatisfied_descendants(project, n),
                                         -n.depth, n.importance, n.id))


def next_buildable(project: TeachProject) -> TeachNode | None:
    """Il primo nodo della coda che si puo' davvero affrontare adesso.

    Un composite ha bisogno dei suoi figli; un pezzo procedurale o dichiarato
    da un asset no — §21 lo dice con le stesse parole. Quindi un nodo e'
    affrontabile se i suoi figli mandatory sono validati **oppure** se il suo
    backend non e' `composite`.
    """
    for node in build_queue(project):
        if _unsatisfied_descendants(project, node) == 0:
            return node
        backend, _, _ = recommend_backend(project, node)
        if backend != COMPOSITE:
            return node
    return None


def queue_text(project: TeachProject) -> str:
    righe = []
    for index, node in enumerate(build_queue(project), start=1):
        backend, _, _ = recommend_backend(project, node)
        righe.append("%2d. %-28s profondita' %d  importanza %.2f  %s"
                     % (index, node.id, node.depth, node.importance, backend))
    return "\n".join(righe) or "nessun nodo mandatory da costruire"
