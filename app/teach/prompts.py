"""Il compilatore di prompt. Un prompt qui e' un **contratto**, non una domanda.

Sette prompt, e ciascuno ha una regola che lo definisce:

    decomposizione      che cosa l'oggetto **e'**. Niente Python, niente mesh,
                        niente coordinate, niente API di 3DGen (§4)
    raffinamento        la stessa domanda, con la risposta di prima davanti e
                        le regole di granularita' (§7, §8)
    idoneita'           un dossier di metadata, e quattro stati possibili. La
                        modalita' economica: nessun codice (§13, §14)
    deep validation     il codice o il JSON, con un tetto di dimensione, e solo
                        quando i metadata non sono bastati (§15)
    visiva              alcune varianti rese piu' il testo bersaglio; nessuna
                        API vision nuova (§17)
    implementazione     la specifica che 3DGen ha gia' deciso, piu' le **sole**
                        API necessarie, piu' il formato di risposta (§24-§27)
    riparazione         la specifica, i file generati, le diagnostiche vere e
                        il comportamento atteso (§34)

## Tre decisioni che valgono per tutti

**Il prompt e lo schema sono identici nelle due modalita'.** §5 lo chiede: che
la risposta arrivi incollata a mano o da un provider configurato, il testo e lo
schema sono gli stessi oggetti. Non esiste una variante «per il provider».

**Il testo di terze parti passa da `sanitize()`.** La descrizione e i tag di un
componente installato sono scritti da chi ha fatto il plugin, e finiscono in un
prompt: e' la regola 6 di `PROJECT-INDEX`, applicata qui perche' valga per gli
stessi motivi. Un plugin non deve poter infilare istruzioni in una domanda che
qualcuno porra' a un modello.

**Sono in inglese, e il resto del progetto non lo e'.** La differenza e'
deliberata: `SISTEMA` del planner e' italiano e viene mandato a un fornitore
configurato, mentre questi vengono **copiati dall'utente** in ChatGPT, Claude,
Codex o Gemini, e lo schema di risposta ha i campi in inglese. Un prompt e il
suo schema in due lingue diverse sono un prompt che si fraintende.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.planner.vocabulary import sanitize
from app.teach.contracts import contract_for
from app.teach.model import (BACKENDS, COMPOSITE, DATA_MESH, PROCEDURAL,
                             SUITABILITY, TeachProject)
from app.teach.schema import (DECOMPOSITION_SCHEMA, IMPLEMENTATION_SCHEMA,
                              REFINEMENT_SCHEMA, SUITABILITY_SCHEMA,
                              VISUAL_SCHEMA)
from app.teach.spec import ComponentSpec

# Quanto codice si manda in una deep validation. Un tetto, perche' §15 lo
# chiede con queste parole: non migliaia di righe per predefinito.
DEEP_LIMIT = 24000
MAX_DOSSIER_ITEMS = 12

ONLY_JSON = ("Answer with one JSON object and nothing else: no prose before or "
             "after it, no markdown fence, no comments.")


def _schema_block(schema: dict) -> str:
    return "RESPONSE SCHEMA (strict; every other key is refused)\n%s" % json.dumps(
        schema, indent=2, sort_keys=True)


def _clean(value: Any, limit: int = 160) -> str:
    """Testo di terze parti ridotto a un valore di campo. Vedi la testata."""
    return sanitize(value, limit)


# --------------------------------------------------------------------------- #
# 1. Decomposizione concettuale (§4)
# --------------------------------------------------------------------------- #
DECOMPOSITION_RULES = """\
WHEN TO CREATE A SUB-PART - create one when at least one of these is true:
  it can be reused on a different object;
  it can vary independently from its parent;
  it has a recognisable semantic role of its own;
  it can itself hold sub-parts;
  it can be left out (optional);
  it appears more than once;
  it is only needed at a higher level of detail.

WHEN NOT TO - do not split when the split adds no capability: do not go down to
materials, surfaces, polygons, cells, molecules or atoms. A part that cannot be
built, reused or varied on its own is not a part, it is a detail of its parent's
shape. Stop at the level a person would name when describing the object out loud.

REPEATED PARTS - a part that appears N times is ONE node with "count": N. Never
one node per instance, never a node whose name is a plural, and never a left
node beside a right node: one node, counted. Names are singular.

MANDATORY VS OPTIONAL - "mandatory": true means the object is not itself without
that part. "mandatory": false means a recognisable instance of the object can
exist without it. Be strict: most decorative or breed-specific parts are optional.

IMPORTANCE - 0.0 to 1.0: how much that part carries the recognisability of the
whole. A silhouette-defining part is near 1.0, a small detail near 0.1.

DETAIL LEVEL - 1 for the parts that must exist even in the simplest version,
2 for the normal version, 3 and above for fine detail. The root is 1."""

DECOMPOSITION_SYSTEM = """\
You decompose a concept into the parts an object of that kind is made of.

This is an ontology task, not a modelling task. Do NOT write code, geometry,
meshes, vertices, triangles, coordinates, transforms, file formats, or anything
about any 3D engine or its API. Do NOT choose or name existing assets or
components. Describe only WHAT THE OBJECT IS MADE OF.

%s

%s""" % (DECOMPOSITION_RULES, ONLY_JSON)


def decomposition_prompt(concept: str, *, style_target: str = "",
                         detail_target: int = 2,
                         description: str = "") -> tuple[str, str]:
    """Pass 1: «di che cosa e' fatto questo oggetto?». Solo ontologia."""
    righe = ["CONCEPT", str(concept).strip(), ""]
    if description:
        righe += ["WHAT THE USER MEANS BY IT", _clean(description, 400), ""]
    if style_target:
        righe += ["STYLE TARGET (context only; it must not change the parts)",
                  _clean(style_target, 120), ""]
    righe += ["DETAIL TARGET",
              "level %d: parts needed above this level may still be listed, "
              "with their own detail_level." % int(detail_target), "",
              "TASK",
              "List the parts a %r is made of, as a tree." % str(concept).strip(),
              "", _schema_block(DECOMPOSITION_SCHEMA)]
    return DECOMPOSITION_SYSTEM, "\n".join(righe)


# --------------------------------------------------------------------------- #
# 2. Raffinamento (§7)
# --------------------------------------------------------------------------- #
REFINEMENT_SYSTEM = """\
You refine a draft decomposition into a hierarchy of reusable 3D components.

Still no code, no geometry, no coordinates, no engine API, and still no naming
of existing assets. What you may do:

  add sub-parts that are missing;
  merge parts that were split too finely;
  correct mandatory/optional;
  give more precise semantic roles;
  assign detail levels;
  turn N duplicated nodes into one node with "count": N;
  mark which nodes are better treated as a composition of their children
  (a node with children and no shape of its own).

%s

%s""" % (DECOMPOSITION_RULES, ONLY_JSON)


def refinement_prompt(project: TeachProject) -> tuple[str, str]:
    """Pass 2: la stessa domanda, con la risposta di prima davanti."""
    if project.root is None:
        hierarchy = "{}"
    else:
        hierarchy = json.dumps(_ontology(project.root), indent=2, sort_keys=True)
    righe = ["CONCEPT", project.concept, ""]
    if project.description:
        righe += ["DESCRIPTION", _clean(project.description, 400), ""]
    if project.style_target:
        righe += ["STYLE TARGET", _clean(project.style_target, 120), ""]
    righe += ["DETAIL TARGET", "level %d" % project.detail_target, "",
              "HIERARCHY FROM PASS 1", hierarchy, "",
              "TASK",
              "Refine this hierarchy into reusable 3D components, following the "
              "rules above. Return the whole tree, not a patch, and list what "
              "you changed in \"changes\".",
              "", _schema_block(REFINEMENT_SCHEMA)]
    return REFINEMENT_SYSTEM, "\n".join(righe)


def _ontology(node) -> dict:
    """Il nodo nella forma dello schema: senza id, senza stato.

    Gli id non si mandano: li deriva il sistema dai nomi (regola 15 di
    `PROJECT-INDEX` applicata all'ontologia), e mandarli inviterebbe il modello
    a riscriverli. E lo stato non si manda perche' il raffinamento riguarda che
    cosa l'oggetto e', non che cosa la libreria ha.
    """
    data: dict[str, Any] = {"name": node.name, "mandatory": bool(node.mandatory),
                            "count": int(node.count),
                            "importance": round(node.importance, 2),
                            "detail_level": int(node.detail_level)}
    if node.role:
        data["role"] = node.role
    if node.description:
        data["description"] = node.description
    if node.children:
        data["children"] = [_ontology(c) for c in node.children]
    return data


# --------------------------------------------------------------------------- #
# 3. Il dossier di un candidato (§13)
# --------------------------------------------------------------------------- #
def _measure(session, component_id: str, *, style: str,
             detail_level: int) -> tuple[int, Any]:
    """Triangoli e ingombro di un componente installato, misurati davvero."""
    if session is None:
        return 0, None
    from app.core.session import Options

    plan = {"version": "1.3", "style": style, "detail_level": int(detail_level),
            "seed": 0, "root": {"id": "subject", "ref": component_id}}
    try:
        result = session.build(plan, Options(style=style,
                                             detail_level=int(detail_level),
                                             check=False))
    except Exception:                                      # noqa: BLE001
        return 0, None
    if result is None:
        return 0, None
    scene = result.scene()
    bounds = scene.bounds() if scene is not None and scene.nodes else None
    return int(result.triangles), bounds


def candidate_dossier(project: TeachProject, node_id: str, component_id: str,
                      registry, *, session=None) -> str:
    """Il dossier programmatico di §13. Metadata e comportamento, non codice.

    E' la **modalita' economica**: tutto cio' che segue si legge dal registry e
    da una build, e il Python del componente non ci entra. Chi ha bisogno del
    codice chiede una deep validation, e paga quella.
    """
    node = project.require_node(node_id)
    component = registry.component(component_id)
    if component is None:
        return "component %s is not installed" % component_id
    state = project.state(node_id)
    candidate = state.candidate(component_id)
    parent = project.parent_of(node_id)

    righe = ["TARGET", "",
             "concept:            %s" % project.concept,
             "path:               %s" % node.id,
             "requested part:     %s" % node.name,
             "requested role:     %s" % (node.role or "(none declared)"),
             "mandatory:          %s" % ("yes" if node.mandatory else "no"),
             "count:              %d" % node.count,
             "detail level:       %d" % node.detail_level,
             "style:              %s" % (project.style_target or project.style)]
    if node.description:
        righe.append("part description:   %s" % _clean(node.description, 300))
    if project.description:
        righe.append("semantic context:   %s" % _clean(project.description, 300))
    if parent is not None:
        parent_state = project.state(parent.id)
        righe.append("parent:             %s%s" % (
            parent.name, "" if parent_state.solution is None
            else " -> " + parent_state.solution.ref))
    siblings = []
    if parent is not None:
        siblings = ["%s%s" % (c.name, "" if c.count == 1 else " x%d" % c.count)
                    for c in parent.children if c.id != node.id]
    if siblings:
        righe.append("siblings:           %s" % ", ".join(siblings[:MAX_DOSSIER_ITEMS]))

    righe += ["", "CANDIDATE", "",
              "component:          %s" % component.id,
              "plugin:             %s" % component.plugin,
              "role:               %s" % (component.role or "(none declared)"),
              "description:        %s" % _clean(component.description, 300),
              "tags:               %s" % ", ".join(sorted(component.tags)),
              "provides:           %s" % ", ".join(sorted(c.name for c
                                                          in component.provides)),
              "mounts:             %s" % ", ".join(
                  sorted("%s%s" % (m.capability, "" if not m.side
                                   else " (%s)" % m.side)
                         for m in component.mounts)) or "(none)",
              "styles:             %s" % (", ".join(sorted(component.styles))
                                          or "any"),
              "requires:           %s" % (", ".join(sorted(component.requires))
                                          or "(nothing declared)")]

    params = []
    for name, spec in sorted(component.params.items()):
        if spec.derived:
            continue
        span = ("[%s, %s]" % (spec.min, spec.max)) if spec.min is not None \
            and spec.max is not None else "unbounded"
        role = getattr(spec, "semantic_role", "")
        params.append("  %-18s %-9s %-18s default %-8s%s"
                      % (name, spec.type, span, spec.default,
                         "  role " + role if role else ""))
    righe += ["", "params:" if params else "params:             (none)"]
    righe += params[:MAX_DOSSIER_ITEMS]

    roles = sorted({getattr(s, "semantic_role", "")
                    for s in component.params.values()
                    if getattr(s, "semantic_role", "")})
    righe.append("semantic roles:     %s" % (", ".join(roles) or "(none)"))
    backed = ["%s -> %s.%s" % (b.param, b.type, b.parameter)
              for b in component.param_effects]
    righe.append("effect-backed:      %s" % (", ".join(backed) or "(none)"))

    caps = [c.name for c in component.provides] or [""]
    effects = sorted({e.id for cap in caps for e in registry.effects_for(cap)})
    righe.append("usable effects:     %s" % (", ".join(effects[:MAX_DOSSIER_ITEMS])
                                             or "(none)"))

    children: list[str] = []
    if session is not None:
        from app.authoring.lab import ComponentLab

        try:
            lab = ComponentLab(session, component.id, style=project.style,
                               detail_level=node.detail_level)
            children = list(lab.declared_children(node.detail_level))
            traits = [t.id for t in lab.traits()]
        except Exception:                                  # noqa: BLE001
            traits = []
    else:
        traits = []
    righe.append("declared children:  %s" % (", ".join(children[:MAX_DOSSIER_ITEMS])
                                             or "(none)"))
    righe.append("traits that reach:  %s" % (", ".join(traits[:MAX_DOSSIER_ITEMS])
                                             or "(none)"))

    frame = component.frame
    if frame is None or getattr(frame, "empty", True):
        righe.append("frame:              (not declared)")
    else:
        righe.append("frame:              growth %s, front %s, up %s"
                     % (frame.growth_axis or "-", frame.front or "-",
                        frame.up or "-"))

    triangles, bounds = _measure(session, component.id, style=project.style,
                                 detail_level=node.detail_level)
    if triangles:
        righe.append("triangles:          %d (measured at detail %d)"
                     % (triangles, node.detail_level))
    if bounds is not None:
        size = bounds[1] - bounds[0]
        righe.append("bounds:             %.3f x %.3f x %.3f"
                     % (float(size[0]), float(size[1]), float(size[2])))

    if candidate is not None:
        righe += ["", "WHY 3DGEN PROPOSED IT", "",
                  "state:              %s" % candidate.verdict,
                  "retrieval score:    %.3f" % candidate.score]
        for item in candidate.evidence:
            righe.append("  %-18s %s" % (item.kind, _clean(item.detail, 200)))
    return "\n".join(righe)


# --------------------------------------------------------------------------- #
# 4. Idoneita' (§14)
# --------------------------------------------------------------------------- #
SUITABILITY_SYSTEM = """\
You judge whether an existing 3D component can play a requested part.

You are given what the part must be, and the declared contract and measured
shape of one installed component. Decide between four answers:

  SUITABLE                  it can play that part as it is;
  SUITABLE_WITH_PARAMETERS  it can, once its declared parameters are set to the
                            values you give in "suggested_params";
  NEEDS_VISUAL_CHECK        the metadata are not enough to tell; someone must
                            look at it;
  NOT_SUITABLE              it cannot play that part.

Rules:
  "suggested_params" may name ONLY parameters the component declares, with
  numeric values inside the declared range. Nothing else.
  You are making a RECOMMENDATION. You cannot mark anything as validated: a
  human or a deterministic check decides that.
  Say what you based the answer on, in "reason", in one or two sentences.

%s""" % ONLY_JSON


def suitability_prompt(project: TeachProject, node_id: str, component_id: str,
                       registry, *, session=None) -> tuple[str, str]:
    """Il prompt di idoneita': il dossier, piu' quattro stati possibili."""
    dossier = candidate_dossier(project, node_id, component_id, registry,
                               session=session)
    righe = [dossier, "",
             "TASK",
             "Can %s play the part %r of a %s?" % (component_id,
                                                   project.require_node(node_id).name,
                                                   project.concept),
             "", _schema_block(SUITABILITY_SCHEMA)]
    return SUITABILITY_SYSTEM, "\n".join(righe)


# --------------------------------------------------------------------------- #
# 5. Deep validation (§15)
# --------------------------------------------------------------------------- #
def deep_validation_prompt(project: TeachProject, node_id: str,
                           component_id: str, registry, *, session=None,
                           limit: int = DEEP_LIMIT) -> tuple[str, str]:
    """Il secondo livello: il codice o il JSON, con un tetto di dimensione.

    Solo quando metadata e comportamento esposto non bastano, perche' costa:
    per un componente di codice si manda il **sorgente dei moduli del plugin**,
    per un componente dati il **JSON completo** — e mai il GLB, che e' binario e
    non si legge. Il tetto e' dichiarato (`DEEP_LIMIT`) e il prompt dice quando
    e' scattato, invece di troncare in silenzio.
    """
    component = registry.component(component_id)
    dossier = candidate_dossier(project, node_id, component_id, registry,
                               session=session)
    blocchi = [dossier, "", "IMPLEMENTATION", ""]
    if component is None:
        blocchi.append("(component not installed)")
    else:
        info = registry.plugin(component.plugin)
        root = Path(getattr(info, "path", None) or ".") if info else Path(".")
        declared = list(getattr(info, "sources", ()) or []) if info else []
        declared += list(getattr(info, "data_components", ()) or []) if info else []
        spent = 0
        for relative in declared:
            source = root / relative
            try:
                text = source.read_text(encoding="utf-8-sig")
            except OSError:
                continue
            if spent + len(text) > int(limit):
                blocchi.append("--- %s: omitted, the %d character limit was "
                               "reached ---" % (relative, int(limit)))
                continue
            spent += len(text)
            blocchi += ["--- %s ---" % relative, text]
        if not declared:
            blocchi.append("(no readable source: the plugin declares none)")
        blocchi.append("")
        blocchi.append("The GLB files are NOT included: binary geometry is not "
                       "readable as text, and the measured shape above is what "
                       "it says.")
    blocchi += ["", "TASK",
                "With the implementation in front of you, answer the same "
                "question as before.", "", _schema_block(SUITABILITY_SCHEMA)]
    return SUITABILITY_SYSTEM, "\n".join(blocchi)


# --------------------------------------------------------------------------- #
# 6. Validazione visiva (§17)
# --------------------------------------------------------------------------- #
VISUAL_SYSTEM = """\
You are shown renders of the same 3D component in several configurations, and
told what part it must play. Say which configurations could play that part, and
which one is the best match.

You are making a RECOMMENDATION: the person decides.

%s""" % ONLY_JSON


def visual_validation_prompt(project: TeachProject, node_id: str,
                             component_id: str, variants, *,
                             registry=None) -> tuple[str, str]:
    """Il prompt da dare, con le immagini, a un modello che le immagini le vede.

    Nessuna API vision nuova (§17): 3DGen rende le immagini e scrive la
    domanda, l'utente le porta dove vuole. `variants` e' un elenco di
    `{"label", "params", "image"}` — l'immagine e' un percorso su disco, e il
    prompt la nomina perche' chi incolla sappia quale file e' quale.
    """
    node = project.require_node(node_id)
    righe = ["TARGET", "",
             "concept:        %s" % project.concept,
             "part:           %s (%s)" % (node.name, node.id),
             "requested role: %s" % (node.role or "(none declared)"),
             "style:          %s" % (project.style_target or project.style),
             "mandatory:      %s" % ("yes" if node.mandatory else "no"),
             "count:          %d" % node.count]
    if node.description:
        righe.append("description:    %s" % _clean(node.description, 300))
    righe += ["", "COMPONENT", component_id, "", "VARIANTS SHOWN", ""]
    for item in variants:
        values = dict(item.get("params", {}))
        righe.append("  %-10s %s" % (item.get("label", "?"),
                                     ", ".join("%s=%s" % (k, v)
                                               for k, v in sorted(values.items()))
                                     or "defaults"))
        if item.get("image"):
            righe.append("             image: %s" % item["image"])
    righe += ["", "TASK",
              "For each variant say whether it could be the %r of a %s, and "
              "name the best match." % (node.name, project.concept),
              "", _schema_block(VISUAL_SCHEMA)]
    return VISUAL_SYSTEM, "\n".join(righe)


# --------------------------------------------------------------------------- #
# 7. Implementazione (§24-§27)
# --------------------------------------------------------------------------- #
ENVELOPE_RULES = """\
HOW TO DELIVER THE FILES

Return one JSON object with a "files" array. Each file has a "path" relative to
the plugin folder and its full "content" as a string.

  paths are relative, use forward slashes, and never contain "..";
  no absolute paths, no drive letters, no UNC paths;
  allowed extensions: .json, .py, .md, .txt;
  no other file, and nothing outside the plugin folder.

Do NOT modify 3DGen itself. You are writing a plugin, and a plugin never
touches the core, the resolver, the builder, the effect pipeline or the session."""

IMPLEMENTATION_SYSTEM = """\
You implement one component of a 3DGen plugin, against a contract that has
already been decided.

The contract below is not a suggestion and not a starting point: the
capability the component must provide, the sockets it must expose, the children
it must host, the axis convention, the triangle budget and the parameter names
are decisions the system has already made, and something else depends on each
of them. Implement exactly that contract.

%s

%s""" % (ENVELOPE_RULES, ONLY_JSON)


def _spec_block(spec: ComponentSpec) -> str:
    righe = ["TARGET", "", "component id:       %s" % spec.component_id,
             "plugin id:          %s   (the manifest MUST declare exactly this "
             "id)" % spec.plugin_id,
             "concept node:       %s" % spec.node,
             "part:               %s" % spec.name,
             "role:               %s" % (spec.role or "(none declared)"),
             "mandatory:          %s" % ("yes" if spec.mandatory else "no"),
             "count:              %d" % spec.count,
             "detail level:       %d" % spec.detail_level,
             "", "PURPOSE", "", _clean(spec.description, 400) or
             "(the hierarchy declares no description for this part)",
             "", "STYLE", "", spec.style_target or spec.style,
             "", "CONTRACT", "",
             "must provide:       %s%s" % (", ".join(spec.provides) or "(nothing)",
                                           "   <- declare this capability, it is "
                                           "not installed yet"
                                           if spec.declares_capability else ""),
             "attaches to:        %s" % (spec.parent_component or
                                         "a composite this run will write"),
             "own socket:         base"]
    if spec.mounts:
        righe.append("must accept:")
        for mount in spec.mounts:
            righe.append("  %-18s on socket %-14s for %s%s%s"
                         % (mount["capability"], mount["socket_id"],
                            mount["for"],
                            "" if mount["count"] == 1 else " x%d" % mount["count"],
                            "" if mount["mandatory"] else " (optional)"))
    if spec.required_sockets:
        righe.append("sockets:")
        for socket in spec.required_sockets:
            righe.append("  %-14s %s" % (socket["name"], socket["purpose"]))
    if spec.semantic_parameters:
        righe += ["", "PUBLIC PARAMETERS", "",
                  "Declare at least one parameter for each of these semantic "
                  "roles, so the",
                  "installed semantic traits reach this component without a new "
                  "rule:",
                  "  " + ", ".join(spec.semantic_parameters)]
    if spec.children:
        righe += ["", "CHILDREN (already validated; declare them as they are)", ""]
        for child in spec.children:
            righe.append("  %s" % json.dumps(child, sort_keys=True))
    if spec.siblings:
        righe += ["", "SIBLINGS (context; do not implement them)", ""]
        for sibling in spec.siblings:
            righe.append("  %-16s %-10s %s" % (sibling["name"],
                                               sibling["coverage"],
                                               sibling["component"] or "-"))
    if spec.frame:
        righe += ["", "FRAME (the convention that holds here)", "",
                  "  " + json.dumps(spec.frame, sort_keys=True),
                  "  Declare it, and build consistently with it."]
    else:
        righe += ["", "FRAME", "",
                  "  Nobody around this node declares an axis convention, so do "
                  "not invent one.",
                  "  You may declare your own `frame` if the shape has an "
                  "unambiguous up and front."]
    righe += ["", "TRIANGLE BUDGET", "", "  at most %d triangles at detail %d"
              % (spec.triangle_budget, spec.detail_level)]
    if spec.notes:
        righe += ["", "NOTES", ""] + ["  - %s" % n for n in spec.notes]
    return "\n".join(righe)


def _reference_block(spec: ComponentSpec, registry) -> str:
    """I riferimenti, resi con la **stessa** funzione del vocabolario di produzione.

    `ComponentEntry.to_text()` e' cio' che il planner vede: usarla qui vuol
    dire che un modello e il planner leggono la stessa descrizione di un
    componente, e che nessuno scrive una parafrasi che divergera'.
    """
    from app.core.planner.vocabulary import _componente

    if not spec.reference_components:
        return ""
    righe = ["REFERENCE COMPONENTS (installed; the closest things the library "
             "already has)", ""]
    for cid in spec.reference_components:
        component = registry.component(cid)
        if component is None:
            continue
        righe.append(_componente(component).to_text())
    return "\n".join(righe)


TESTS_BLOCK = """\
MANDATORY SELF-CHECKS

The system will run its own validators on what you return (schema, registry
verification, resolver, geometry quality gate, triangle budget, semantic
retrieval). Before answering, check by reading your own output that:

  the component declares the capability it was told to provide;
  every socket named above exists, with a non-zero direction and up that are
  not parallel, and a positive radius;
  every mount names a socket that exists;
  each declared child names an installed component id exactly as given;
  the geometry is triangles only, with no NaN and no infinity;
  nothing reads a file, opens a network connection, or depends on global state;
  the same inputs give the same geometry, every time."""


def implementation_prompt(spec: ComponentSpec, registry, *,
                          backend: str = "") -> tuple[str, str]:
    """Il prompt di implementazione, per il backend scelto. §25, §26, §27."""
    chosen = backend or spec.backend
    if chosen not in BACKENDS:
        chosen = PROCEDURAL
    blocchi = [_spec_block(spec), "", "BACKEND", "",
               "  %s   (%s)" % (chosen, spec.backend_reason), "",
               contract_for(chosen)]
    if chosen == DATA_MESH:
        blocchi += ["", "THE MESH", "",
                    "  The geometry already exists and is NOT yours to invent: "
                    "it is the file",
                    "  below, and it will be placed at `meshes/%s.glb` inside "
                    "the plugin." % spec.name,
                    "  Write the JSON that declares it: do not emit GLB bytes, "
                    "do not emit",
                    "  base64, do not emit vertices.",
                    "", "  asset: %s" % (spec.asset or "(supplied separately)")]
    reference = _reference_block(spec, registry)
    if reference:
        blocchi += ["", reference]
    blocchi += ["", TESTS_BLOCK, "", "TASK", "",
                "Write the files of a plugin that installs %s exactly as "
                "specified." % spec.component_id,
                "", _schema_block(IMPLEMENTATION_SCHEMA)]
    return IMPLEMENTATION_SYSTEM, "\n".join(blocchi)


def composite_prompt(spec: ComponentSpec, registry) -> tuple[str, str]:
    """Il prompt del composite. Esiste, e di solito non serve.

    Quando ogni figlio necessario e' validato, la composizione e' **decisa**: i
    componenti, i requirement, i parametri e i conteggi sono tutti nella
    specifica, e 3DGen la scrive da se' (`TeachService.emit_composite`), senza
    rete e senza fiducia da concedere. Questo prompt serve al caso in cui chi
    costruisce voglia che un modello decida la disposizione — e anche allora
    riceve un contratto, non una domanda aperta.
    """
    return implementation_prompt(spec, registry, backend=COMPOSITE)


# --------------------------------------------------------------------------- #
# 8. Riparazione (§34)
# --------------------------------------------------------------------------- #
REPAIR_SYSTEM = """\
A plugin you produced did not pass the system's validators. Fix it.

You are given the original contract, the files as they were received, and the
real diagnostics - the codes and messages the validators emitted, not a
paraphrase. Change what the diagnostics point at, and nothing else.

Return the complete files again, not a patch.

%s

%s""" % (ENVELOPE_RULES, ONLY_JSON)


def repair_prompt(spec: ComponentSpec, registry, *, files, diagnostics,
                  attempt: int = 1) -> tuple[str, str]:
    """Il prompt di riparazione: contratto, file, diagnostiche vere, attese."""
    blocchi = [_spec_block(spec), "", "BACKEND", "", "  %s" % spec.backend, "",
               "ATTEMPT", "", "  this is repair attempt %d" % int(attempt), "",
               "FILES AS RECEIVED", ""]
    for item in files:
        blocchi += ["--- %s ---" % item.get("path", "?"),
                    str(item.get("content", ""))]
    blocchi += ["", "WHAT THE VALIDATORS SAID", ""]
    for row in diagnostics:
        blocchi.append("  %-10s %-32s %s" % (row.get("severity", ""),
                                             row.get("code", ""),
                                             _clean(row.get("message", ""), 240)))
        if row.get("why"):
            blocchi.append("             why: %s" % _clean(row["why"], 240))
        if row.get("where"):
            blocchi.append("             where: %s" % row["where"])
    blocchi += ["", "EXPECTED BEHAVIOUR", "",
                "  the plugin loads; %s builds; the geometry passes the quality "
                "gate; the" % spec.component_id,
                "  triangle count stays at or below %d; the declared capability "
                "and sockets" % spec.triangle_budget,
                "  are present; the semantic index finds the component by its "
                "own name.",
                "", TESTS_BLOCK, "", "TASK", "",
                "Return the corrected files.", "",
                _schema_block(IMPLEMENTATION_SCHEMA)]
    return REPAIR_SYSTEM, "\n".join(blocchi)


def render(system: str, user: str) -> str:
    """Il prompt come l'utente lo copia: una cosa sola, con i due blocchi."""
    return "%s\n\n%s\n%s\n" % (system.strip(), "=" * 72, user.strip())


__all__ = ["DECOMPOSITION_RULES", "DEEP_LIMIT", "ENVELOPE_RULES", "SUITABILITY",
           "candidate_dossier", "composite_prompt", "decomposition_prompt",
           "deep_validation_prompt", "implementation_prompt",
           "refinement_prompt", "render", "repair_prompt", "suitability_prompt",
           "visual_validation_prompt"]
