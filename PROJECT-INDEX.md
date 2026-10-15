# 3DGen — Project Index (for AI agents)

Machine-oriented index of the repository. Written to let another AI understand
the architecture, locate code, and make changes without re-exploring the tree.
Generated 2026-10-15 from the working tree; updated after milestones V1
(semantic retrieval), V2 (explainable semantic degradation), V3 (structural
selectors + stable node identity), V3.5 (planner contract robustness), V4
(mesh-backed components declared in data), V5 (semantic variability + the
geometric frame contract), V6 (component authoring) and V7 (Teach 3DGen). See
"Repository state" at the end.

Language note: code identifiers, docstrings and comments are mostly **Italian**
(`grafo` = graph, `nodo` = node, `piano` = plan, `pezzo` = piece, `innesto` =
socket/graft, `stile` = style, `verifica` = check, `risolvi` = resolve,
`costruisci` = build, `dove` = where, `padre` = parent, `figlio` = child).
Public API names are English. Docs are mixed Italian/English.

---

## 1. What the system is

3DGen turns a natural-language prompt into a low-poly 3D model by **composing
pre-existing components** supplied by plugins. An LLM never generates geometry:
it writes a JSON **composition plan** (which components, how attached, which
parameters, which effects). A deterministic engine resolves, builds and
measures that plan.

One sentence: *prompt → semantic plan → registry lookup → capability resolution
→ effect pipeline → deterministic geometry → quality gate → glTF/OBJ/STL/PLY.*

Core invariant: **the core has no domain knowledge**. It knows only that a
component `provides` capabilities and `accepts` capabilities. No `if
object == "house"` anywhere. Adding a plugin never requires a core change.

---

## 2. Pipeline (authoritative order)

```
prompt
 → Session.generate()                      app/core/session.py
 → shortlist (semantic retrieval)          app/core/planner/retrieval.py   [V1]
 → build_vocabulary(shortlist)             app/core/planner/vocabulary.py
 → Planner (LLM or Mock)                   app/core/planner/planner.py
 → ConceptResolver (degradation ladder)    app/core/archetypes.py          [V2]
 → validate_plan → CompositionGraph        app/core/planner/plans.py, app/core/graph.py
 → StructuralTraitResolver (graph rewrite)  app/core/structural.py
 → Resolver → ResolvedComposition          app/core/resolver.py, app/core/resolved.py
     (+ frame compatibility check [V5])    app/core/frame.py
 → TraitResolver (semantic params)         app/core/traits.py
 → LayoutEngine (socket synthesis)         app/core/layout.py
 → EffectPipeline → EffectedComposition    app/core/effect.py
 → Builder → BuildResult                   app/build/assembler.py
 → validate (geometry quality gate)        app/build/validate.py
 → to_scene / export                       app/build/scene.py, app/build/exporter.py
```

**[V4] The pipeline above is unchanged by mesh-backed components.** A component
whose geometry comes from a GLB is an ordinary `Component` whose `build` loads a
file instead of calling the kernel, so every stage after `Registry` is blind to
the difference. Three lines in the whole tree know that data plugins exist, and
all three are in `app/core/registry.py` (542, 680, 716) where manifests are
read. `grep -rn "mesh_backed\|kind == \"data\"" app/build/ app/core/` outside
the loader and the registry returns nothing, and that is the measurement, not
the intention.

**[V5] The pipeline above is unchanged by semantic variability.** A parameter
that drives an installed effect becomes an ordinary `EffectRequest` inside the
existing `EffectPipeline` (`app/core/effect.py:_from_params`, the only new
code), and a semantic trait reaches an imported mesh through the `semantic_role`
machinery that V1 already had. The frame check is a **comparison of two declared
strings** added where the resolver already links a child to a parent; it never
rotates anything, and `grep -rn "mesh_backed" app/build/ app/core/` outside the
loader and the registry still returns nothing.

**[V6] The pipeline above is unchanged by authoring.** `app/authoring/` is a
layer *above* `Session`, not inside it: it writes a data plugin and installs it,
and from that moment the preview is an ordinary generation. One grep is the
measurement — `grep -rn "app.authoring\|app\.ui" app/core/ app/build/
app/geometry/` returns nothing — and the only core change the milestone needed
is that a **data** component may now omit `mesh` (`app/core/data_plugin.py`),
which `Piece.mesh = None` had always allowed.

**[V7] The pipeline above is unchanged by Teach 3DGen, and that is the point.**
`app/teach/` is a layer above `app/authoring/`, which is a layer above
`Session`: it decides *which components a concept needs*, it writes prompts,
it stages what a model answers, and when a component is accepted it installs an
ordinary data or code plugin. From that moment a learned concept is an ordinary
generation — `Session.generate("a cartoon dragon")` builds `dragon_pack:dragon`
with the local planner and no network. The grep is the measurement:
`grep -rn "app.teach" app/core/ app/build/ app/geometry/ app/authoring/`
returns nothing, and the only core change the milestone needed is a **removal
of duplication** (the data-format key lists became module constants).

Effect stages, in fixed order (`app/core/vocabulary.py:56-62`):
`structural` → `proportion` → `local` → `global` → `style` → `final`.
`proportion` changes **parameters before build**; `local`/`global`/`style`
change **vertices after build**; `final` is pose/centering/grounding. The order
is the contract.

At most **one** repair round-trip to the LLM: a failed plan produces a
diagnostic brief (`app/core/planner/repair.py`), the plan is rewritten once,
and the better-scoring of the two plans wins (`plan_score`).

---

## 3. Entry points

| Path | Role |
| --- | --- |
| `main.py` | launches the PySide desktop UI |
| `cli.py` | CLI; same `Session` API as the UI (~30 flags: `--plan`, `--explain`, `--detail`, `--style`, `--out`, `--png`, `--save`, `--find`, `--load`, `--project`, `--game-ready`, `--animate`, `--providers`, `--hardware`, `--recover`) |
| `app/core/session.py` | **the single entry point** — `Session`, `Options`, `GenerationResult`, undo/redo history |
| `app/ui/main_window.py` | UI shell; also provider/failover selection, and **[V6]** the two doors to authoring |
| `app/authoring/service.py` | **[V6]** `AuthoringService` — the programmatic authoring API, with no Qt anywhere |
| `app/ui/authoring_window.py` | **[V6]** `AuthoringWindow` (7 pages) and `ComponentLabDialog`; a thin client of the service |
| `app/teach/service.py` | **[V7]** `TeachService` — the programmatic Teach API: decompose, cover, validate, generate, install, complete. No Qt anywhere |
| `app/ui/teach_window.py` | **[V7]** `TeachWindow` (5 pages); a thin client of the service, read by token to prove it |

**[V3] Two identities per node, and they are not the same thing.** The
`planner node id` (`CompositionNode.id`) is a free name written by the model and
used to address things (`on`, `swap`, `target`, diagnostics). The `stable node
identity` (`CompositionGraph.identity(id)`) is derived by the system —
`sha1(parent identity | ref | requirement signature | ordinal)` — so it cannot
be written by the LLM, survives serialization because it is recomputed (old
`.my3d` files gain it with no format change), ignores params and effects,
survives a `swap`, is invariant to renames, and distinguishes structural clones.
Declared limit: deleting a same-signature sibling shifts the ordinals after it.
The full reasoning is at the top of `app/core/graph.py`.

`Session` public surface: `generate(prompt, options)`, `plan(prompt)`,
`build(plan)`, `regenerate()`, `configure_ai(provider, model, chain)`,
`export(path)`, `save_project(path)`, `catalog()`,
`vocabulary(style, prompt="", shortlist=None)`, `component_index()`,
`shortlist(prompt, style)`, `undo()`/`redo()`/`goto(i)`, **[V6]**
`reload_plugins(*paths)`, properties `current`, `current_plan`, `scene`,
`result`.

**[V6]** `reload_plugins()` is how the vocabulary changes without restarting: it
never writes into a frozen registry, it builds another one from the same
directories plus the new ones, and it drops the per-style vocabulary cache and
the semantic index. New paths are *added*, because installing a plugin must not
lose the library you had. It exists on `Session` and not in the authoring layer
for rule 8: UI, CLI and tests all go through `Session`.

`vocabulary()` with no prompt is the whole library (cached per style, the
pre-V1 behaviour); with a prompt or a shortlist it is restricted to the
retrieved components.

**[V4]** `Session` also carries `missing_plugins` and `changed_plugins` — what
an opened project used and no longer finds, and what it finds but changed
(version, or content at the same version). The same information is on each
rebuilt `result.diagnostics` as `PLUGIN_VERSION_CHANGED` /
`PLUGIN_CONTENT_CHANGED`, so reopening a project reads like any other
generation.

`Options` is deliberately tiny: `style`, `detail_level`, `seed`, `budget`,
`repair`, `check`, **[V5]** `frame_policy`. Everything else belongs in the plan,
because the plan is the only place a decision stays readable. `frame_policy`
(`diagnose` / `strict`) is the one exception on purpose: it is not a property of
a model but of how severe *this project* wants to be with the assets it
installs, and `app/core/frame.py` explains why no third value converts.

`GenerationResult` carries `ok`, `diagnostics`, `triangles`, `scene()`,
`mesh()`, `explain()`, `changes()`, `skipped()`, `structural_changes()`
(**[V3.5]**, which structural requests were *applied*, read from
`StructuralTraitResolution.applied`), `describe()`, `to_dict()`,
`shortlist` + `retrieval()` (what the planner was shown, and why),
`concept_resolution` + `degradation()` (**[V2]**, why the model is not exactly
what was asked for — empty when it is), and provider provenance (`requested_provider/model`, `actual_provider/model`,
`failover_count`).

---

## 4. Core modules (`app/core/`)

| File | Lines | Contents |
| --- | --- | --- |
| `session.py` | 1116 | `Session`, `Options`, `GenerationResult`, `Version` history; **[V3.5]** `structural_changes()`, and `skipped()` also reports skipped structural requests and unsupported concept adaptations |
| `registry.py` | 1354 | `Registry`, `PluginInfo`, `CapabilityInfo`, plugin discovery/manifest reading, `freeze()`, `verify()` |
| `resolver.py` | 873 | `Resolver` — candidate scoring and socket matching (weights: capability 16, side 8, style 4, tag 1); **[V5]** `_frame`, the frame comparison on every link, and `frame_policy` |
| `archetypes.py` | 1188 | `ArchetypeSpec`, `ProfileSpec`, `ImplementationBinding`, `ConceptResolver`, `ConceptResolutionPlan`, coverage/diagnostics; **[V2]** `subject_capabilities`, `normalize_reference`, `MATCH_*`, the degradation ladder |
| `graph.py` | 842 | `CompositionGraph`, `CompositionNode`, `EffectRequest`, `Operation`; param provenance (`FROM_DEFAULT/DERIVED/OVERRIDE/EFFECT/TRAIT`); `to_dict`/`from_dict`; **[V3]** derived stable node identity (`identity`/`identities`/`by_identity`, `_signature`, `_digest`) and `structural_provenance` |
| `effect.py` | 568 | `Scope`, `PlannedEffect`, `EffectContext`, `EffectPipeline`, `apply_effects`; **[V5]** `_from_params` translates a component's `ParamEffect` declarations into ordinary `EffectRequest`s (it never writes `composition.effects`, so a second run does not double them) |
| `structural.py` | 810 | structural traits: `StructuralTarget`, `EnsureCountOperation`, `GraphRewritePlan`, `StructuralTraitResolver` (cap `MAX_STRUCTURAL_COUNT = 64`); **[V3]** selector-based prototype choice (`_locate`/`_discover`/`_rank`), `on` as a search scope, clone provenance, `UNKNOWN_TRAIT_SKIPPED`; **[V3.5]** `_prototipo_mancante` — `mode` decides the severity of a missing prototype (`exact` fatal, `best_effort` warning + skipped) and the `why` names the three moves that fix it |
| `layout.py` | 427 | `LayoutRegion`, `LayoutFrame`, `LayoutPlacement`, `LayoutPlan`, `LayoutEngine`, `fan_policy`, `linear_policy` |
| `traits.py` | 426 | semantic traits: `TraitSpec`, `TraitRule`, `TraitMatch`, `ParamPatch`, `TraitResolver`, `resolve_traits`. **Unchanged by V5** — a test greps it for `mesh`/`glb`/`mesh_backed` and finds nothing |
| `frame.py` | 310 | **[V5]** the axis convention as a contract: `FrameSpec` (`growth_axis`/`front`/`up`), `compare()` → `compatible` / `convertible` / `ambiguous` / `undeclared`, `rotation_to()`, `move()` (the `fx:rotate` request that would reconcile two frames), policies `diagnose`/`strict`. Compares **only** `up` and `front`, never `growth_axis`, and never converts |
| `params.py` | 273 | `ParamSpec`, sandboxed expression `evaluate()` (AST whitelist), scopes `self`/`parent`/`root`, types FLOAT/INT/BOOL/ENUM/STRING/VECTOR2/VECTOR3/COLOR |
| `resolved.py` | 263 | `ResolvedNode`, `ResolvedLink`, `ResolvedValue`, `ResolvedComposition` |
| `component.py` | 240 | `Component`, `Attachment`, `Piece`, `BuildContext`; **[V5]** `Component.frame` and `Component.param_effects` |
| `capability.py` | 242 | `Capability`, `Requirement`, `Mount`, `best_match`, match tiers (`EXACT_ID 5` … `INCOMPATIBLE -1`), sides `l/r/center/top/bottom/front/back` |
| `socket.py` | 238 | `Socket`, `Placement`, `attach()`, scale modes `none`/`socket`/`fit_replaced` |
| `vocabulary.py` | — | `EffectSpec`, `ParamRule`, `StyleProfile`, scopes, **stage constants**; **[V5]** `ParamEffect` — the mirror of `ParamRule`: how a *parameter* asks for an effect |
| `project.py` | 315 | `.my3d` format v2 — stores plans + plugin identities/versions, not meshes; **[V4]** `ProjectInfo.fingerprints` + `changed_plugins()`, which turn `PLUGIN_VERSION_CHANGED` / `PLUGIN_CONTENT_CHANGED` into diagnostics on the *rebuilt* result |
| `data_plugin.py` | 613 | **[V4]** the data-only loader: JSON + GLB/glTF → the existing `Component`/`Piece`/`Socket`/`ParamSpec`/`Attachment`/`LayoutRegion`/`MaterialSpec`. `safe_path()` confines every resource to the plugin directory, `load_component()`, `load_material()`, `DataPluginError` with stable codes (`DATA_PATH_UNSAFE`, `DATA_MESH_*`, `DATA_PARAM_UNSUPPORTED`, `DATA_FRAME_INVALID`, `DATA_JSON_INVALID`, `DATA_SCHEMA_INVALID`, `DATA_FILE_MISSING`). No Python from the plugin is ever imported. **[V5]** a parameter declares `transform` **or** `effect` (a `ParamEffect` naming an installed effect), never both and never neither |
| others | — | `budget.py` (triangle budgets), `constraints.py`, `material.py`, `scene.py`, `authoring.py` (socket helpers, frame verification), `recovery.py`, `hardware.py`, `errors.py`, `logging_setup.py`, `config.py` (`Settings`, `ProviderSpec`, `DEFAULT_CHAIN`) |

### Planner (`app/core/planner/`)

- `planner.py` (630) — `Planner` ABC, `MockPlanner` (offline word-matching),
  `LLMPlanner`, `make_planner`, Italian system prompt `SISTEMA`, repair prompt
  `CORREZIONE`. Limits: `MAX_NODI = 14`, `MAX_PROFONDITA = 4`.
  **[V3.5]** `SISTEMA` now documents `traits` and `structural_traits` as plan
  keys and states the difference generically (properties of parts that exist vs
  how many parts there are) plus what `mode` does. Before V3.5 the string
  `structural_traits` did not appear in the prompt at all, and the only
  trait-shaped slot shown was `concept.adaptations` — which can never become a
  structural trait. That was the measured reason the layer was never called; see
  `V3.5-RESULTS.md` §1. The prompt names no domain word: a test asserts that
  `arm`, `wheel`, `tail` and their Italian forms never appear in it.
- `schema.py` (207) — JSON Schema `PLAN_SCHEMA`, version **1.3**. A plan has
  `oneOf: [concept, root]`, plus `version`, `style`, `detail_level`, `seed`,
  `traits[]`, `structural_traits[]`.
- `plans.py` (634) — `validate_plan()` → `CompositionGraph`. Hard limits
  `MAX_NODI = 200`, `MAX_PROFONDITA = 12`. **[V3]** the policy for unknown
  optional elements is documented at the top of the file: an unknown semantic or
  structural trait becomes `UNKNOWN_TRAIT_SKIPPED` (warning, dropped from the
  plan); a missing root component, a malformed element, an *ambiguous* trait
  name, an invalid value on a known trait and an unknown effect stay fatal.
  **[V3.5]** a third category, which is *not* a widening of the second:
  `_appiattisci_params` flattens a nested `params` object on a **known** effect
  when every inner key is a declared parameter of that effect and none
  conflicts with a value already present — then there is nothing to decide, and
  it reports `EFFECT_PARAMS_FLATTENED` (warning). One unknown key, one
  conflict, or a `params` that is not an object, and the reading is no longer
  unique: `EFFECT_PARAM_NOT_FOUND`, fatal as before, plus a non-fatal
  `EFFECT_PARAMS_NOT_FLATTENED` saying why. The three categories differ by *how
  much choice they require*, not by severity. No effect is known by name.
- `retrieval.py` (427) — **[V1]** the stage between prompt and planner.
  `document_for(component)` (searchable text from declared metadata only),
  `stamp_for` / `registry_signature` (invalidation), `ComponentIndex`,
  `build_index`, `query_groups`, `shortlist`, `thesaurus_for`,
  `estimate_tokens`. Reuses the engine in `app/assets/semantic.py` through its
  `Corpus` hook — there is no second retrieval engine. Tunables: `SHORTLIST=28`,
  `PER_GROUP=8`, `PER_PLUGIN=10`, `CLOSURE=10`, `THRESHOLD=0.02`,
  `FALLBACK_MAX=120`.
- `vocabulary.py` (977) — what the LLM is shown: `ComponentEntry`,
  `EffectEntry`, `TraitEntry`, `ArchetypeEntry`, `ProfileEntry`,
  `BindingEntry`, `CapabilityEntry`. `build_vocabulary(registry, *, style,
  detail_level, components=None)` — passing `components` restricts capabilities,
  effects, traits, structural traits, plugins and tags to that shortlist too, so
  the payload scales with the shortlist and not with the library.
  **`sanitize()` is a security boundary**:
  third-party descriptions are flattened to one quoted line, control chars
  stripped, `system:`/`assistant:`/`user:` markers removed, 160-char cap. A
  plugin must not be able to inject instructions into the planner.
  **[V3.5]** `TraitEntry` carries three fields that decide whether a trait can
  be *chosen* rather than merely listed, and all three are data a plugin had
  already declared: `plan_key` (the JSON key it is written under — the section
  title is a caption, the key is the contract), `aliases` (**all** the safe
  ones, because aliases are the words a request uses: `braccia`, `ruote`; V3
  kept the first and threw the rest away) and `selects` (what the trait
  touches, derived from its rules' declared targets — `role:arm`, `tag:wheel`,
  `component:plugin:piece`). The two section titles now name their plan key.
  `selects` follows the shortlist like `CapabilityEntry.providers` does: a
  component id outside the shortlist is not named, or the payload would start
  growing with the installed library again. `std:instance_count` is the only
  structural trait with no `selects`, because it is the only one with no rule —
  the request has to point at a node with `on`, and its `purpose` says so.
- `repair.py` (253) — `repair_brief()`, `plan_score()`, `PlanScore`.
  **[V3.5]** `STRUCTURAL_PROTOTYPE_NOT_FOUND` and `STRUCTURAL_EXACT_OVERCOUNT`
  joined `CORREGGIBILI`. Once the planner really writes `structural_traits`, a
  right trait on a root that lacks that part is a new and plausible plan, and
  it is the `SOCKET_INCOMPATIBLE` family: the plan named two things that do not
  go together. `STRUCTURAL_VALUE_CONFLICT` stays out — the diagnostic cannot
  say which of two counts the author meant.

### Plan shape

```json
{
  "version": "1.3",
  "style": "low_poly",
  "detail_level": 2,
  "traits": [{"trait": "body_mass", "value": 0.8, "on": "torso", "scope": "subtree", "op": "set"}],
  "structural_traits": [{"trait": "arm_count", "value": 4, "mode": "best_effort",
                          "target": {"capability": "limb_mount"}}],
  "root": {
    "id": "body", "ref": "humanoid:body",
    "params": {"height": 1.8},
    "effects": [{"type": "fx:lanky", "amount": 0.4, "scope": "subtree"}],
    "children": [{"id": "head", "swap": "creature:frog_head", "on": "head/nose"}]
  }
}
```

Key semantics: `swap` replaces a declared child instead of adding one; `on`
addresses a nested path (`"head/nose"`) that the plan never named, without
duplicating it; the plan **wins over** component declarations without deleting
them. `mode` on a structural trait is the author's call about approximation:
`exact` fails the plan when the count cannot be reached, `best_effort` builds
the rest and declares the request lost (**[V3.5]** — it used to fail in both
modes, see `V3.5-RESULTS.md` §6.2).

---

## 5. Five extension layers above plain components

These are the newest and least documented parts of the system. Three of them
change *what exists* and *how much*; the last two, added in V5, change *how the
things that exist are shaped* and *whether two of them agree on which way is
up*.

1. **Semantic traits** (`app/core/traits.py`) — a named semantic knob
   (`body_mass`, `leafiness`) that a plugin maps onto public component
   parameters or effects via `TraitRule`/`ParamPatch`. Scope `local` or
   `subtree`; op `set` or `add`. Applied *after* resolution, *before* effects.
   Reference plugins: `body_mass_extension`, `tree_leafiness_extension`,
   **[V5]** `variability_extension`.

   **[V5] The relative-proportion vocabulary, and why three of the six select
   by role.** `variability_extension` installs six traits and 19 rules: three
   generic (`std:part_scale`, `std:width`, `std:length`, addressed with `on` +
   `scope`) and three role-selective (`std:head_scale`, `std:hand_scale`,
   `std:limb_length`, whose rules filter on the component's declared `role`).
   The three selective ones exist because `on` **addresses a node** and a
   humanoid's head is not a node of the plan: it is a child the component
   declares itself, so its id is the path `subject/torso/neck/head`, which the
   planner never wrote. `on: "head"` gives `TRAIT_TARGET_NOT_FOUND`; a
   role-selective trait has no such question, and a test proves the result is
   identical under four different root ids. It is V3's lesson — select, never
   address — applied to the semantic layer.

   Every patch declares `semantic_role`, never `param`: that is what makes the
   same trait reach a procedural component and a GLB when both declare the same
   role. The role vocabulary (`length`, `girth`, `width`, `height`, `scale`,
   `curvature`) lives in the components and in the plugin, never in the core;
   `grep` for any of the trait names in `app/core/` returns nothing.

   Declared boundary: a generic trait with `scope: subtree` plus a selective
   one write the same `(node, param)` channel on the selected part, so both are
   dropped with `TRAIT_RULE_CONFLICT`. The form that works for "bigger creature
   with a huge head" is `part_scale` with `scope: local` on the root plus
   `head_scale`. See `V5-RESULTS.md` §5.

2. **Structural traits** (`app/core/structural.py`) — change the *graph*, not
   parameters: "four arms", "six wheels", "three tails". Produces
   `EnsureCountOperation`s that clone a prototype node. Modes `exact` /
   `best_effort`. Runs before resolution. Reference plugins:
   `multi_arm_extension`, `multi_wheel_extension`, `multi_tail_extension`.

   **[V3]** The prototype is **selected, not addressed**. `StructuralTraitRule.
   prototype` was a literal node path (`car/wheel_fl`), which made a semantic
   behaviour depend on the id the planner happened to write. The rule's existing
   `target` (`StructuralTarget`: role / capability / tags / components) now
   answers both "what am I counting" and "what do I clone" — one selector per
   rule, no new selector type, and the three installed rules simply dropped the
   field. `prototype` survives as an optional path for `std:instance_count`,
   where the request itself points at a node. `StructuralTraitRequest.on` became
   a **search scope**: a path that resolution replaced is ignored instead of
   fatal. The documented tie-breaking, in order, is component exact match →
   role → capability → tags → the parent declares a `LayoutRegion` accepting the
   node → depth → path, in a strict pass and then a partial one. Clones inherit
   the prototype's parent relation and `Attachment`, so `LayoutEngine` still
   decides *where* while the trait decides *how many*.

   **[V3.5]** V3 made the layer correct and nothing called it. The reason was
   never the engine: the system prompt did not name the `structural_traits` key,
   the section title was a caption rather than a key, two aliases out of three
   were thrown away (including the Italian ones a request actually uses), no
   entry said *what* a trait counts, and on the audit's own "four arms" prompt
   `character:arm_count` was not in the vocabulary at all — so the model copied
   `instance_count`, which is **the alias of an installed trait**
   (`std:instance_count`), into the wrong key. Fixed in prompt, vocabulary
   metadata and plugin manifests; measured with a real LLM, which now writes
   `structural_traits` on exactly the prompts that ask for a count and builds
   six wheels. Full analysis in `V3.5-RESULTS.md`.

3. **Concept resolution and degradation** (`app/core/archetypes.py`) — a plan
   may say `{"concept": {"requested": "jeep"}}` instead of a component tree.
   **[V2]** `ConceptResolver` walks a ladder and always says which rung it
   stopped on (`ConceptResolutionPlan.match`, `.confidence`, `.strategy`,
   `.approximate`, `.describe()`):

   ```text
   1 exact id          2 component name      3 archetypes/bindings
   4 semantic proxy    5 root from the plan  6 explicit failure
   ```

   Rungs 1–3 are the pre-V2 path (`ArchetypeSpec` hierarchies with cycle
   detection, `ImplementationBinding`, `ConceptCoverage`, `_preflight`) and are
   now **optional enrichment**: when the catalog does not cover a concept, rung
   4 ranks installed components from the V1 index. `subject_capabilities()`
   derives "this component is a whole subject" structurally — a capability
   provided by someone and accepted by nobody — so a new plugin participates
   with no binding written by hand. `normalize_reference()` repairs invented id
   prefixes only when the remainder is unambiguous, and reports every repair.

4. **[V5] Parameter-driven effects** (`app/core/vocabulary.py:ParamEffect`) —
   a component parameter that **asks for an installed effect** instead of
   rebuilding geometry. It is the mirror of `ParamRule` (which says how an
   effect changes a parameter) and it exists for components whose geometry
   cannot be regenerated: an imported mesh has one state, so "more curved" can
   only be a deformation. Five data fields (`param`, `type`, `parameter`,
   `scope`, `neutral`) and no code; the whole implementation is
   `EffectPipeline._from_params`, which turns the declaration into an ordinary
   `EffectRequest` and lets the existing validation judge it. The plan wins over
   the declaration (`PARAM_EFFECT_SUPERSEDED`), the request is readable
   (`PARAM_EFFECT_REQUESTED`), and `Registry.verify()` refuses a binding whose
   effect, knob or scope does not exist (`COMPONENT_EFFECT_NOT_FOUND`,
   `COMPONENT_EFFECT_KNOB_UNKNOWN`, `COMPONENT_EFFECT_SCOPE_UNSUPPORTED`,
   `COMPONENT_EFFECT_PARAM_UNKNOWN`) — at verify time and not at load time, for
   the same reason dependencies are checked there.

5. **[V5] The frame contract** (`app/core/frame.py`) — a component (or, in one
   line, a whole plugin) declares `growth_axis`, `front` and `up`, and the
   resolver compares the declarations of parent and child on every link. What
   it compares is the point: **only `up` and `front`**, because those are the
   two the socket frame does *not* reconcile; `growth_axis` is local and a limb
   growing `+X` off a `+Y` torso is the convention, not a defect. Four
   outcomes: `compatible`, `convertible` (both frames complete → the rotation
   is unique, so the diagnostic names it *and* the `fx:rotate` request that
   would apply it), `ambiguous` (one frame incomplete → the rotation is
   undetermined, so guessing it would be inventing), `undeclared` (nothing to
   compare — the declared limit of the contract). It **never converts**:
   rotating a child against the socket the parent declared would be a second
   placement system. `Options.frame_policy` is `diagnose` (warning) or `strict`
   (fatal, and `FRAME_CONVERTIBLE` is in `repair.CORREGGIBILI`, so the single
   repair round-trip gets the move).

`LayoutEngine` (`app/core/layout.py`) sits alongside: when many siblings must
share a parent surface, declared `LayoutRegion`s plus a `LayoutPolicy`
(`fan`, `linear`) synthesize the sockets instead of the plugin hardcoding them.

---

## 5-bis. [V6] The authoring layer (`app/authoring/`)

A layer **above** `Session`, not inside it. It turns an existing 3D model into
reusable 3DGen knowledge: a data plugin in the V4/V5 format. No new permanent
model of a `Component`, no second deformation engine, no Python generated.

| File | Lines | Contents |
| --- | --- | --- |
| `service.py` | 1816 | `AuthoringService` — the programmatic API, `CapabilityView`, `ValidationReport`, `InstallResult` |
| `model.py` | 718 | `AuthoringProject`, `SourceModel`, `SceneObject`, `DraftComponent`, `DraftSocket`, `DraftParam`, `DraftChild`, the coverage states, `.3dgenproj` serialization |
| `lab.py` | 415 | `ComponentLab`, `ParamKnob`, `LabResult` — any installed component, procedural or mesh-backed |
| `gizmo.py` | 240 | readable socket/frame gizmos as ordinary `SceneNode`s, plus deterministic snap helpers |
| `emit.py` | 239 | project → `plugin.json` + `components/*.json` + `meshes/*.glb` + `materials/*.json` |
| `variant.py` | 182 | `VariantRecipe` — base + params + traits + effects, never a mesh |
| `inspect.py` | 175 | `load_model` / `LoadedModel.extract` / `export_glb`; reuses `data_plugin`'s confined glTF reader |
| `errors.py` | 42 | `AuthoringError` with stable `AUTHORING_*` codes |

Five decisions worth knowing before changing this layer:

1. **The service is the contract, the window is a client.** Nothing in
   `app/authoring/` imports Qt, and a test builds a whole plugin without
   opening a window. `tests/test_authoring_ui.py` reads
   `app/ui/authoring_window.py` **by token** and asserts it contains no
   `trimesh`, `json`, `emit_plugin`, `load_component`, `Registry`, `np`,
   `load_model` or `export_glb`. V7 will call the service, not widgets.
2. **The preview does not simulate: it emits and installs.** `_stage()` writes
   the plugin into a scratch directory and installs it in a throwaway
   `Session`, so a preview is an ordinary generation and what you see is what
   you will save — the same JSON read by the same loader. Re-emission happens
   only when `AuthoringProject.fingerprint()` changes, and that digest
   *excludes* editor state (selection, visibility, current component,
   destination, coverage, notes). A parameter travels in the **plan**, so
   moving a slider costs 1.2 ms instead of 131.
3. **Coverage lives in the project, never in `Component`.**
   `VALIDATED`/`CANDIDATE`/`MISSING`/`PROXY` is the judgement of whoever is
   assembling a concept, not a property of a piece: an installed component is
   either in the library or absent. It never reaches the emitted JSON, and a
   parameterized test checks all four values.
4. **A draft reference names three things with one field.** `draft:<key>` a
   component of this project, `variant:<name>` a recipe declared here, anything
   else an **installed** component. That is what makes a mixed hierarchy
   (imported body + `creature:eye` + `fantasy:wing`) an ordinary case instead
   of a separate feature.
5. **A gizmo is geometry, not an overlay.** The viewport draws a `Scene`, so a
   gizmo is an extra mesh tagged `gizmo` (disc, direction arrow, up bar). Those
   nodes never count as triangles, never export, never reach the plugin — a
   test sums them and compares. The gizmo is **not draggable** in V6: there is
   no picking in the viewport, and sockets move through snaps and numeric
   fields.

`ComponentLab.subtree()` is the one place that **resolves** instead of reading
declared `Attachment`s, and the reason is measured: `Component.children` is a
callable, and `humanoid_anatomical:torso`'s reads values the resolver derives
from its parent (`height`, `hip_width`), so calling it with plain defaults
raises `KeyError`. It is the fix debt 12 asks for — follow the declared
composition — applied where it is possible; the retrieval relevance filter still
has only the shortlist, so **that debt stays open**.

---

## 5-ter. [V7] The Teach layer (`app/teach/`)

A layer **above** `app/authoring/`, which is above `Session`. It does not
generate geometry and it does not know what a dragon is: it decides **which
components a concept needs**, measures what the installed library already
covers, compiles the prompts that ask a model for the rest, stages what comes
back, and installs what is accepted. Once a concept is `LEARNED`, an ordinary
`Session` builds it with no AI at all — that is the milestone's own final test.

| File | Lines | Contents |
| --- | --- | --- |
| `service.py` | 1622 | `TeachService` — every operation as a method; `PromptBundle`, `TeachReport`, `CompletionReport` |
| `model.py` | 1079 | `TeachProject`, `TeachNode`, `NodeState`, `Candidate`, `Evidence`, `Solution`, `SuitabilityRecord`, `Attempt`, `ArtifactRecord`, `Exchange`, `Progress`, `.teach3d` |
| `staging.py` | 732 | the envelope, path confinement, `inspect_python` (AST), trust, `validate_artifact`, `install` |
| `prompts.py` | 730 | the seven prompts and the candidate dossier |
| `coverage.py` | 649 | the thirteen named evidences, the four states, the recompute |
| `spec.py` | 517 | `ComponentSpec`, the backend recommendation, the dependency-aware queue |
| `contracts.py` | 245 | 3DGen's own API, **generated** by reading 3DGen |
| `knowledge.py` | 240 | `TeachKnowledge` — validation memory, outside `Component` |
| `schema.py` | 192 | the four strict response schemas |
| `_runner.py` | 103 | loading a staged plugin in a subprocess (robustness, **not** a sandbox) |
| `errors.py` | 59 | `TeachError` with stable `TEACH_*` codes |

Eight decisions worth knowing before changing this layer:

1. **The ontology and the state are separate.** `TeachNode` is what the object
   *is* (parts, count, mandatory, importance, detail level, role);
   `NodeState` is what we know about *covering* it (coverage, candidates with
   their evidence, the chosen solution, AI recommendations, generation
   attempts). Keeping them apart is why a refinement pass can rewrite the
   hierarchy without losing a validated decision, and why coverage can be
   recomputed after **every** install without touching the ontology.
   `TeachProject.tree()` merges them for whoever only reads.
2. **A node's identity is a path, and a model cannot write it.**
   `dragon.head.eye` is derived from the names (`parent.slug(name)`, with `_2`
   for same-named siblings) and the response schema has no `id` field at all.
   It is rule 15 applied to the ontology. Its declared limit: states survive
   **by id**, so a node the refinement renames is a new node and its decision
   is dropped — with `TEACH_DECISION_LOST`, never in silence.
3. **Coverage is evidence, not a threshold.** Every candidate carries *named*
   evidence and the state is read from the names, never from their sum:
   `CANDIDATE` = identity **and** context, `PROXY` = identity without context
   or context with similarity, `MISSING` = neither, `VALIDATED` = **never**
   from evidence. A retrieval score of 1.0 alone is not even a proxy. The
   weights only order candidates, and they live in one constant.
4. **One retrieval engine.** Candidates come from `ComponentIndex.search` — the
   V1 index the `Session` already uses — plus the providers of a capability
   read from the `Registry`. Similarity is measured only on the *part's* own
   queries (`part_queries`): the measured reason is that «dragon horn» scores
   0.40 against `creature:dragon_head`, so a concept-wide query would make the
   concept's head a proxy for every part and nothing would ever read `MISSING`.
5. **A concept's root accepts only whole subjects**, via V2's
   `subject_capabilities()` — a capability provided by someone and accepted by
   nobody. Without it the best candidate for a dragon is a dragon *head*, and
   the damage does not stop there, because a child reads its `capability`
   evidence from what the parent accepts. This closes debt 13 **here**; in the
   planner's vocabulary it stays open.
6. **The technical spec belongs to 3DGen, not to the model.** When a node is
   `MISSING` what is missing is geometry, not a contract: the capability, the
   sockets, the children, the frame, the triangle budget and the parameter
   roles are decisions the system already made, and the prompt hands them over
   as a contract. The backend recommendation is structural — `composite` when
   every mandatory child is satisfied, `data_mesh` when a GLB was supplied,
   `procedural_python` otherwise, because **3DGen cannot generate a GLB from
   text** — and the user can override it.
7. **Generated Python is code, and it is never trusted by default.**
   `import_implementation` writes files and inspects them with the AST; it
   imports nothing. `validate_artifact`, `accept_artifact` and `artifact_lab`
   all **raise** `TEACH_TRUST_REQUIRED` on a code artifact until somebody calls
   `trust_artifact`. The static checks are warnings and the report says so in
   words; `isolate=True` runs the load in a subprocess with a timeout and is
   documented as robustness, **not** confinement. Nothing here is called a
   sandbox, and a test reads the files to prove it.
8. **Validation memory is not a field on `Component`.** A component does not
   *have* a validation any more than it has a coverage: that is the judgement
   of whoever built a concept. It lives in `teach_knowledge.json` next to the
   library, keyed on **(role, name)** so a second concept finds it, and it
   stays an **evidence** (`prior_validation`) — a judgement given about a
   dragon is not a judgement given about a wyvern. See `V7-RESULTS.md` §17.

`TeachService.emit_composite()` writes the root (and any intermediate)
composite itself, with `AuthoringService` of V6 and not a second emitter: when
every child is validated there is nothing to decide, so no model and no trust
are involved. A child with `count: N` becomes **N attachments** on the same
component, each with its own socket.

---

## 6. Geometry, build, output

- `app/geometry/kernel.py` — the only *procedural* low-level mesh maker: `ring`, `sweep`,
  `profile_sweep`, `grow`, `block`, `faces_per_normal`. Backed by `trimesh` +
  `numpy`. `app/geometry/uv.py` for UVs.
- `app/build/assembler.py` (766) — `Builder`, `BuiltNode`, `BuildResult`;
  places pieces by socket attachment, applies per-stage deformations, enforces
  the triangle budget. Joint tolerance `GIUNTO_MASSIMO = 0.02`.
- `app/build/validate.py` (500) — deterministic quality gate: manifold /
  watertight / connected / no-degenerate, coordinate sanity, socket sanity,
  joint gaps, triangle limits, `silhouette_fill`, interpenetration (AABB-based
  — a known approximation), style conformance. **No LLM judges geometry.**
- `app/build/visual.py` — `VisualReport`, silhouette/solidity analysis,
  `VisualCriteria`.
- `app/build/optimize.py` — LODs (`make_lods`, `regenerate_lod`), decimation,
  `merge_by_material`, `collision_mesh`, `prepare_for_game` /
  `export_game_ready` with engine presets.
- `app/build/exporter.py` — `.glb`, `.obj`, `.stl`, `.ply`; `safe_output_path`
  guards Windows reserved names.
- `app/anim/` — `skeleton.py`, `pose.py`, `clip.py`, `gltf.py` (skinned glTF).
- `app/assets/` — `AssetLibrary` (saved plans + `auto_tags`), `semantic.py`
  (`Corpus`, `Embedder`, `TfidfEmbedder`, `RemoteEmbedder`, `SemanticIndex`).
  One engine, two corpora: `ASSETS` powers `--find` over saved assets,
  `COMPONENTS` (defined in `planner/retrieval.py`) powers the planner shortlist.
  A persisted index records its corpus and is refused if read as the other.
  `THESAURUS` is the default synonym bridge; `expand()` and `TfidfEmbedder`
  accept an injected one.
- `app/materials/` — material library and procedural textures.
- `app/ui/` — `main_window.py` (three doors in the toolbar: Authoring,
  Component Lab, **[V7]** Teach, all on the same `Session`), `viewport.py`,
  `render_core.py`, `offscreen.py`, `workers.py` (threaded generation),
  `authoring_window.py`, **[V7]** `teach_window.py`.

---

## 7. AI providers (`app/ai/provider.py`, 476 lines)

`LLMProvider` ABC → `ChatProvider` (OpenAI-compatible HTTP),
`OfflineProvider`, `FailoverProvider`. `make_provider(name, model, chain)`.
Providers expose `available`, `structured` (native structured output),
`complete_json(system, user, schema)`, `provenance`, `set_phase`,
`record_request_metrics`.

Configured entirely through `.env` (see `.env.example`): `GROQ_API_KEY`,
`GEMINI_API_KEY`, `MISTRAL_API_KEY`, `CLOUDFLARE_API_KEY` +
`CLOUDFLARE_ACCOUNT_ID`, `NVIDIA_API_KEY`, `CEREBRAS_API_KEY`,
`OPENROUTER_API_KEY`, `COHERE_API_KEY`, `HF_API_KEY`, `OPENAI_API_KEY`,
`DEEPSEEK_API_KEY`, `OLLAMA_ENDPOINT`/`OLLAMA_MODEL`, plus `GEN3D_LLM_CHAIN`,
`GEN3D_LOG_LEVEL`, `GEN3D_OUTPUT_DIR`, `GEN3D_LIBRARY_DIR`, `GEN3D_TIMEOUT`.

Rules worth knowing before touching this code:
- the default model comes from the provider's own backend registry; failover
  uses the **next candidate's** default model, not the primary model id;
- legacy per-provider model vars (`HF_MODEL`, `OPENROUTER_MODEL`) are ignored
  for remote providers, kept readable only for compatibility;
- the chain keeps its configured order but normalizes `OpenRouter` last among
  remotes, immediately before `Ollama`;
- an incompletely configured provider stays "not configured" and never blocks
  startup;
- with no provider at all the pipeline still runs via `MockPlanner`, and the
  result explicitly records `planner = "mock"`. No silent fallback.

---

## 8. Plugins (`app/plugins/`)

Discovery is by directory + `plugin.json` manifest. Manifest keys: `id`,
`version`, `name`, `description`, `author`, `license`, `tags`, `components[]`,
`effects[]`, `styles[]`, `materials[]`, `traits[]`, `archetypes[]`,
`profiles[]`, `bindings[]`, `capabilities[]` (name + description + tags),
`dependencies[]`, `metadata{}`, `synonyms{}`, **[V5]** `frame{}`. Component ids
are `plugin:name`.

**[V5] `frame` in the manifest is the axis convention of the plugin**, and it
applies to every component of that plugin that does not declare its own
(`Registry.register_component`). It is the promotion `VISION-GAP` §8 asked for:
`humanoid_anatomical` wrote the same thing in `metadata` as Italian prose —
true, and comparable by nobody. One line per plugin instead of one per piece,
because a convention belongs to the plugin's author. Five plugins declare one,
which gives **53 of the 97 components** a comparable frame; a malformed axis
refuses the plugin with `INVALID_MANIFEST` instead of being ignored.

**[V4] Two kinds of plugin, one discovery.** `type` is `"code"` (the default,
every installed plugin today) or `"data"`. A code plugin declares Python files
and they are imported; a **data** plugin declares `components[]` and
`materials[]` as **JSON files** beside GLB/glTF meshes, and nothing of it is
imported — `PluginInfo.sources` stays empty, `sys.path` is untouched, a `.py`
in the directory is never opened. A data manifest accepts only `id`, `version`,
`type`, `name`, `description`, `author`, `license`, `homepage`, `tags`,
`dependencies`, `capabilities`, `metadata`, `synonyms`, `components`,
`materials`; the keys that name Python in a code plugin (`effects`, `styles`,
`traits`, `archetypes`, `profiles`, `bindings`, and `components` holding a
`.py`) are refused with `INVALID_MANIFEST`. `PluginInfo` also carries
`kind`, `data_components`, `data_materials` and `fingerprint` — the sha256 of
the *referenced contents* (manifest, JSON, meshes, external glTF resources) by
plugin-relative path, so moving a plugin does not change its identity while
editing a GLB does. That fingerprint feeds retrieval invalidation
(`stamp_for` / `registry_signature`) and `.my3d` diagnostics.

The data component format is the existing models in JSON — `id`, `name`,
`description`, `role`, `tags`, `styles`, `requires`, `material`, `provides`,
`mounts`, `sockets`, `params`, `children`, `layout_regions` — plus exactly two
additions: `mesh` (the GLB path, relative to the component file) and a declared
parameter **strategy**. A parameter without one is refused rather than assumed:
see `V4-RESULTS.md` §6.

**[V7] Those key lists are module constants now**, in
`app/core/data_plugin.py`: `SOCKET_KEYS`, `PARAM_KEYS`, `EFFECT_KEYS`,
`CHILD_KEYS`, `COMPONENT_KEYS`, `DATA_MANIFEST_KEYS`. They were literals inside
the functions that enforce them *and* copied into `Registry._read_manifest` and
`app/authoring/emit.py`; V7 had to **state** them to a model
(`app/teach/contracts.py`), which would have been a fourth copy. Now there is
one tuple, and a prompt test compares the generated text against it. Behaviour
is identical and `tests/test_data_plugin.py` passed unmodified.

**[V6] `mesh` is optional, and that is a composite.** A data component with no
`mesh` is a container: `Piece.mesh = None`, and the geometry comes from its
children. It had always been legal for a *code* component (`humanoid:body` is
the historical one) and the loader demanded it anyway, so a knight made of
body, head, sword and shield had to be declared as one monolithic mesh or not at
all. Two rules keep the case unambiguous, both V4's policy applied to a new
case: **without `mesh` children are required** (a component with neither
geometry nor children is nothing, `DATA_SCHEMA_INVALID`) and **without `mesh` no
`transform` is accepted** (`scale_x` multiplies a mesh; scaling only the sockets
would move the children without shrinking them, `DATA_PARAM_UNSUPPORTED`). An
`effect` parameter stays allowed, because an effect scoped `subtree` deforms the
children. This is the only non-additive contract change of V6; see
`V6-RESULTS.md` §3 and §22.

**[V5] A parameter declares `transform` *or* `effect`, never both and never
neither** (`DATA_PARAM_UNSUPPORTED` either way, because there is no non-arbitrary
order between a scale and a deformation):

```json
"width":     {"default": 1.0, "min": 0.2, "max": 3.0,
              "transform": "scale_x", "semantic_role": "width"},
"curvature": {"default": 0.0, "min": -1.0, "max": 1.0,
              "semantic_role": "curvature",
              "effect": {"type": "fx:bend", "parameter": "amount",
                         "scope": "part", "neutral": 0.0}}
```

A `transform` is one of `scale_x` / `scale_y` / `scale_z` / `uniform_scale` and
must stay positive (a negative factor would mirror the mesh); an
`effect`-backed value **may** be negative, because the direction of a bend is a
sign. The `effect` object accepts exactly four keys — three strings and a
number — so a data plugin cannot even *name* a callable, a module, an
expression or a matrix: ten hostile cases are parameterized. `neutral` is the
value that asks for nothing. `frame` (`growth_axis`/`front`/`up`) now goes
through `app/core/frame.py` like every other frame, and its `growth_axis` is
still verified with `app/core/authoring.py:verify_frame` and **diagnosed, never
corrected**. Unknown keys are refused, not ignored.

`synonyms` (**[V1]**, data only, no code) maps a word to equivalent words and
feeds the retrieval thesaurus through `Registry.synonyms()`: it is how the
library — not the core — knows that a jeep is a car. `vehicle_stylized`
declares 9 such bridges. **[V3.5]** the three `multi_*_extension` plugins
declare 8 bridges of their own (16 distinct words in all), for the plurals and Italian forms of the word each one owns
(`braccia` → `braccio`/`arm`, `ruote` → `ruota`/`wheel`, `code` →
`coda`/`tail`). Without them the retrieval shortlist for «quattro braccia»
contained no arm at all, so the relevance filter hid `character:arm_count` and
the planner could not have chosen it — measured in `V3.5-RESULTS.md` §1.5.
`Registry.synonyms()` reads every manifest, including plugins that declare no
component, so this needed no code.

Current registry contents (measured, not from docs):
**23 plugins, 97 components, 30 materials, 12 effects, 27 capabilities,
9 archetypes, 1 profile, 3 bindings, 8 semantic traits, 4 structural traits,
39 declared synonyms.** All 23 are code plugins: **[V4]** deliberately
converted none of them. The data-only plugins live in
`tests/data_plugin_fixtures.py`, which writes real directories of JSON + GLB to
disk (`mesh_fixture`: a knight, a body, a head and a crest; `mesh_vehicle`: a
mesh body with procedural wheels and declared layout regions; **[V5]**
`mesh_variable`: a head whose scales carry `semantic_role`s, a tail whose
`curvature` drives `fx:bend`, and a host that accepts both).

| Plugin | Provides |
| --- | --- |
| `primitives` | block, tube; `low_poly` style; base materials |
| `humanoid` | body, torso, pelvis, chest, neck, head, eyes, nose, mouth, ears, hair, arms, legs, hands, feet |
| `humanoid_anatomical` | more anatomical procedural humanoid: human proportions, layered torso, chained limbs, detailed face. Convention: torso/head grow +Y, limbs +X, front faces +Z |
| `creature` | frog head, dragon head, protruding eye |
| `fish` | body, tail, fin |
| `nature` | tree, canopy, nest, bird |
| `fantasy` | wing, crystal |
| `architecture` | house, roof, door, window |
| `space` | planet (declared simply as a very large `surface`) |
| `weapon` | sword, guard, grip (declares `limb_mount`, so it can replace a leg) |
| `accessories` | face mask, helmet, visor, piercing |
| `robot` | head — realistic style only, exists to prove style rejection |
| `fx` (dir `effects/`) | lanky, chunky, bend, perspective_exaggeration, rotate, align, offset, mirror; **[V5]** squash, elongate, taper, twist (`effects/forma.py`) |
| `fox_stylized` | authored angular low-poly fox benchmark + palette |
| `tree_stylized` | authored chunky asymmetric tree benchmark + palette |
| `vehicle_stylized` | authored low-poly compact car benchmark + palette |
| `body_mass_extension` | semantic trait `body_mass` |
| `tree_leafiness_extension` | semantic trait `leafiness` |
| `variability_extension` | **[V5]** six relative-proportion traits (`part_scale`, `width`, `length`, `head_scale`, `hand_scale`, `limb_length`), 19 rules, 25 word bridges |
| `multi_arm_extension` / `multi_wheel_extension` / `multi_tail_extension` | structural traits (counts) |
| `archetype_metadata` | archetype catalog, generic profiles, bindings for installed roots |

The three `*_stylized` plugins are **benchmarks**: deliberately hand-authored
assets used to prove the generic contracts are sufficient. Their manifest
`metadata` records `core_changes` / `kernel_changes` (both `none`) and the
generic contracts reused. Keep that property when editing them.

No plugin is privileged. Copying a plugin directory changes the vocabulary the
planner sees, automatically.

---

## 9. Tests, tools, benchmarks

`2070 tests` (`python -m pytest -q`; `pytest.ini` + `conftest.py` at root,
and **[V7]** `tests/conftest.py` with the two shared Teach fixtures — an
offline `Session` and a `TeachService` whose staging lives under `tmp_path`).
Tests target the **contracts between** modules, not just units:
`test_core_contracts.py`, `test_core_registry.py`, `test_core_resolver.py`,
`test_core_graph.py`, `test_core_effects.py`, `test_planner_core.py`,
`test_planner_llm.py`, `test_api_freeze.py` (frozen public API),
`test_traits.py`, `test_structural_layout.py`, `test_archetypes.py`,
`test_profiles.py`, `test_concept_resolution.py`, `test_build_pipeline.py`,
`test_validation.py`, `test_visual.py`, `test_golden.py`, `test_performance.py`,
`test_benchmark_reale.py`, `test_distribution.py`, `test_ui.py`,
`test_fox_stylized.py`, `test_tree_stylized.py`, `test_vehicle_stylized.py`,
`test_humanoid_anatomical.py`, `test_ai_providers.py`,
`test_retrieval.py` (**[V1]**, 41 tests: component indexing, fingerprint
invalidation, search, shortlist, plugin synonyms, restricted vocabulary,
sanitize unchanged, and a 1 000-component synthetic library),
`test_degradation.py` (**[V2]**, 33 tests: the ladder, id normalization,
concept-vs-root precedence, explanation, `.my3d` persistence, and a library that
grows through metadata alone),
`test_planner_contract.py` (**[V3.5]**, 38 tests: a structural trait is visible
in the vocabulary and distinguishable from a semantic one, the word bridge is
library data, an ambiguous alias is never offered, the restricted vocabulary
names no component outside the shortlist, the prompt names both plan keys and no
domain word, a **prompt-reading** deterministic provider writes the installed
trait for arms/wheels/tails, removing the plugin makes it vanish instead of
being invented, nested-`params` flattening with the six cases that stay fatal,
flat and flattened plans converge to the same graph and the same geometry,
`mode` really distinguishes `exact` from `best_effort`, and the single repair
round-trip now fires on an incompatible structural request and carries moves
rather than role names. The provider deliberately reads only the rendered text,
because what was missing in V3 was in the text and a test that reads the
vocabulary objects would not have seen it),
`test_structural_identity.py` (**[V3]**, 56 tests: selector-based prototypes,
rename invariance, 2/4/6 arms with the anatomical chain verified, 4/6/8 wheels
under four different root ids, tails, stable identity, clone provenance,
serialization round-trip including a real `.my3d`, the unknown-optional-trait
policy with the seven cases that stay fatal, and cross-plugin composition),
`tests/test_data_plugin.py` (**[V4]**, 101 tests: the loader boundary — a valid
manifest and definition become the existing models, every malformed shape is
refused with a code instead of guessed at, ten hostile paths plus the `uri`s
inside a glTF are confined, GLB missing / truncated / wrong-version / empty /
non-triangular, a multi-node GLB keeps every node transform, sockets and frames
from data, the four transform parameters with the socket radius measured as a
disc area, the three-step material policy, children and layout regions, the
`requires`-driven validation policy, and three tests that a data plugin's own
Python is never imported, never run and never even opened),
`tests/test_data_plugin_integration.py` (**[V4]**, 24 tests: real GLBs through
the ordinary pipeline — Piece, scene and material, detail 1/2/3 recursion,
mesh↔procedural mounting in **both** directions verified geometrically,
deterministic transform params, index invalidation on install and on removal,
`paladin` degrading to a mesh-backed knight with no binding, `wheel_count` 4
and 6 on a mesh body with procedural wheels, `fx:bend` moving vertices and
sockets by the same map, export to glb/obj/stl/ply, `.my3d` round-trip with no
mesh in the archive, and version/content change diagnostics).
`tests/test_semantic_variability.py` (**[V5]**, 65 tests: the two parameter
strategies and the ten hostile `effect` declarations a data plugin cannot even
name, the four `Registry.verify()` refusals, an effect-backed parameter moving
mesh **and** sockets by the same map with the source GLB untouched and the
result deterministic, the plan winning over the declaration, a *procedural*
component driving an effect too, the same trait reaching a procedural and a
mesh-backed part through the same `semantic_role` in four combinations and in
one mixed plan, the six new traits measured on the installed procedural library,
the cartoon benchmark in one plan, role-selective traits invariant to the root
id, `detail_level` staying separate from variability at three levels, the four
new effects (declared scopes and ranges, the squash/elongate conflict, the axis
each one names, sockets on vertices, geometric validity, absence from the core),
and what the planner is shown in the **rendered text**),
`tests/test_frame_contract.py` (**[V5]**, 27 tests: the contract alone — named
axes, refused frames, a right-handed orthonormal basis only for a complete
frame, the four outcomes in seven cases, the rotation that really maps one frame
onto the other, and `growth_axis` never counting as a disagreement — then the
declaration (manifest, component overriding it, malformed manifest, data
component), the comparison during resolution (a coherent composition says
nothing, an undeclared frame says nothing, the outcome recorded on every edge),
the dragon chimera, the two policies and their project round-trip, and
`ambiguous` kept distinct from `convertible`).
`tests/test_authoring.py` (**[V6]**, 112 tests: import and inspection with no
inference, stable object keys, refused formats, the source file never modified,
selection and one-object-per-component, six component names that could become a
path, the meshless composite and the two loader rules, hierarchy as ordinary
attachments with a cycle refused before it exists, sockets as ordinary
`Socket`s with the gizmo data round-tripping through the production loader, the
five snap helpers and mirror as its own inverse, capabilities with providers and
acceptors plus a new one declared as new, metadata reaching the installed
component and an unknown field refused, coverage in all four values never
reaching the plugin and surviving in the project, the real semantic index and
«will my component be found?», the production rendering of what the planner
sees, a transform parameter measured ×4 and an effect-backed one with its
neutral, seven hostile effect bindings, only installed strategies offered, the
frame declared on plugin and component with the convertible move named and never
applied, the three material rows, detail level that is not LOD, validation with
three severities from the real validators, the V4 layout of the saved plugin
with only the needed geometry and the node transforms kept, installing without a
restart with the index and the vocabulary invalidated, a hierarchy mixing
imported geometry with installed components, variant recipes, the authoring
project round trip, an existing data plugin reopened and rebuilt identically, no
Python ever executed, path confinement for component names and glTF `uri`s, and
two end-to-end runs),
`tests/test_component_lab.py` (**[V6]**, 26 tests: the same six asserts
parameterized over a procedural **and** a mesh-backed component, the file read
by token to prove there is no backend branch, compatible traits following the
resolved composition, structural traits by selector, an offered trait that
really applies, compatible effects and one applied, detail levels measured with
real builds, variability kept separate from detail, and the variant recipes —
only what changed, the same geometry rebuilt, a file under 700 bytes, a refused
name, yellow→green with no provider, and no variant of a variant),
`tests/test_authoring_ui.py` (**[V6]**, 25 tests: the declared flow in seven
pages, the context bar answering the four questions, every table mirroring the
service, a refused operation becoming a status line instead of a traceback, only
installed strategies offered with `axis` absent, the rendered planner text, the
real search, the frame table with its move, the validation table, a build from
the window, gizmo nodes that are not the model, save and install, the lab dialog
with its sliders and labels, `Save as defaults` writing on the draft and not on
the library, and **the window holding no authoring logic**, read by token).
`tests/test_teach_model.py` (**[V7]**, 58 tests: node ids as paths derived from
names and never component ids, same-named siblings kept distinct, the twelve
malformed decompositions plus depth and size, the cycle that **cannot** be
expressed and the reference that is refused, an import that executes nothing,
the two passes and decisions that survive or are declared lost, the four states
through a round trip, the two progress formulas and the detail target, the
project round trip with prompts, responses, attempts, artifacts and recipes, an
unknown format refused, no geometry at any depth, validation memory that is not
a field on `Component`, the `(role, name)` reuse key, and a concept's three
plugins),
`tests/test_teach_coverage.py` (**[V7]**, 44 tests: the state read from the
*names* of the evidence in six cases, no amount of evidence producing a green,
a perfect retrieval score that is not even a candidate, identity-without-context
and context-with-similarity, the context words and the component's declared
words, the singular variants, part queries kept apart from concept-wide ones,
the root filter through `subject_capabilities()`, the part that must be
mountable, the dragon benchmark with all four states and the real candidates,
the capped list ordered by evidence, a recompute that touches neither a solution
nor a decision, a vanished solution that decays, prior validation as evidence
and not as a promotion, and the domain-word grep over the **code** of ten
modules, comments and docstrings stripped),
`tests/test_teach_prompts.py` (**[V7]**, 48 tests: the four schemas refusing
unknown keys and valid as JSON Schema, pass 1 forbidding geometry and the engine
API, the granularity rules, pass 2 without ids and without state, the prompt and
the schema as one object, the dossier that is metadata and never source, a
hostile description through `sanitize()`, suitability with its four states and
its ban on validating, deep validation with a declared cap, visual validation
with no vision API, the **generated** API contract compared against
`dataclasses.fields`, the kernel signatures, the absence of the core, the data
keys read from the loader, an ASCII contract, the implementation prompt as a
contract, the bounded envelope, one contract per backend, reference components
rendered with the production function, and repair carrying real diagnostics),
`tests/test_teach_staging.py` (**[V7]**, 81 tests: the envelope as object, text
and markdown block, seventeen malformed shapes, eleven hostile paths, ten
refused extensions, the three size caps, staging under the declared plugin
folder, a manifest that cannot rename the plugin, an asset copied byte for byte,
the kind read from the files, the AST inspection in seven cases with a
configurable flag list, no message calling itself a sandbox, **nothing executed
without trust** at four call sites and measured from the effect, trust surviving
in the project, a data plugin needing none and its `.py` never opened, the
subprocess reporting the same thing and surviving a plugin that explodes,
validation with the real validators, an attempt recorded with its codes, repair
as a new attempt, installation registering the library and not the staging, the
index invalidated, and rejection keeping the history),
`tests/test_teach_endtoend.py` (**[V7]**, 43 tests: the dragon benchmark with
its **measured** coverage, plurals turned into counts, the queue from the fine
parts up, yellow→green through a variant with no duplicated geometry, an AI
recommendation that cannot write green even at confidence 1.0, an invented
parameter dropped, the visual verdict, rendered variants inside declared ranges,
blue→red by decision, the technical specification, the three backend
recommendations and the override, a newly declared capability, a data-only
response validated with nothing executed, Python staged and not run until
trusted, an install recomputing coverage, **the whole cycle to `LEARNED`**, the
counts satisfied in the composite, a root with no mesh of its own, **a normal
`Session` finding and building the learned concept**, the export, an early
finish that stays `LEARNING`, persistence halfway with the artifact recovered
from disk, a plugin that changed after the Teach, knowledge reuse on a second
concept, no background work, no Qt, and a whole concept taught with no user
interface),
`tests/test_teach_ui.py` (**[V7]**, 35 tests: the five declared pages, the two
modes, a response refused into a status line, every table mirroring the service,
the tree with its four colours and **no green after an analysis**, the node form,
a forced state and a green refused without a solution, the candidate table and
the real dossier, the four prompts, yellow→green from the window, the Component
Lab on the chosen candidate, the queue and the spec panel, only the installed
backends, **the whole generation flow from the window** with the source visible
before trust and the refusal without it, the question that trust asks, the
repair prompt, the completion table, save and reopen, a provider that does not
answer, **the window holding no Teach logic** read by token, and the third door
on the same `Session`).
Fixture plugins live in `tests/plugins/` (including intentionally malformed
ones, and **[V5]** `variabilita/procedural_probe`, a code plugin that declares
the V5 parameter roles plus one `ParamEffect`, so the semantic layer can be
measured on procedural and mesh-backed geometry with the same assert); the
data-only fixtures are written to a tmp dir by
`tests/data_plugin_fixtures.py`, **[V6]** `tests/authoring_fixtures.py`
exports a real five-part GLB (`Body`, `Head`, `Eye_L`, `Eye_R`, `Sword`) — the
ideal case the milestone describes, a model that already arrives split into
parts — and **[V7]** `tests/teach_fixtures.py` holds the deterministic AI
responses (a realistic dragon decomposition with the defects a pass 1 really
has, its refinement, the four suitability verdicts, procedural / data /
composite implementation envelopes, a real one-object GLB to supply as an
asset, and the seventeen malformed envelopes and twelve malformed
decompositions).

`tools/`: `benchmark.py`, `render_benchmark.py`, `render_scenari.py`,
`archetype_benchmark.py`, `archetype_validation.py`, `semantic_traits_benchmark.py`,
`structural_layout_benchmark.py`, `fox_stylized_benchmark.py`,
`tree_stylized_benchmark.py`, `ai_provider_smoke.py`,
`data_plugin_benchmark.py` (**[V4]**: plugin discovery, GLB load, build,
semantic index and total local generation, for a procedural, a mesh-backed and
a mixed composition), `variability_benchmark.py` (**[V5]**: the cost of a
transform parameter, an effect-backed parameter, a semantic trait on mesh /
procedural / mixed trees and frame validation, plus the six milestone prompts
split into *intent recognized* / *trait applied* / *geometry changed* / *visual
result*, the last one measured with the existing `app/build/visual.py:analyse`),
`authoring_benchmark.py` (**[V6]**: GLB import, cold staging, preview rebuild,
slider update, Component Lab, detail preview, semantic search, validation, save,
install, reindex and the authoring project round trip, with an explicit
*interactive* verdict at a declared 100 ms threshold),
`teach_benchmark.py` (**[V7]**: the two ontology passes, the coverage analysis,
a node's candidates, the dossier, the four prompts, the lab, the variant, the
technical spec, the implementation prompt, staging, validation in process and in
a subprocess, accept, both composites, the completion report, save and reopen,
`Session.shortlist` and `Session.generate` **outside** Teach, and the coverage
of a second concept — same 100 ms threshold, and it prints the learned tree),
`teach_provider_audit.py` (**[V7]**: pass 1 and pass 2 against a **real**
provider with `jsonschema` checking both responses, then the coverage and the
next prompt. It is evidence and not the Definition of Done: with no provider
configured it says so and exits 0).

Local pipeline performance (no network): total 6–13 ms median — plugin load
16 ms, vocabulary 3 ms, local planner 1 ms, resolver 0.2 ms, effects 0.1 ms,
builder 3–10 ms, quality 1–3 ms.

**[V5]** Variability cost, same machine, median of 7
(`python tools/variability_benchmark.py 7`): a transform parameter is free
(1.04 ms against a 1.20 ms baseline build), an effect-backed parameter costs
**+0.5 ms** (1.54 ms — one validated `EffectRequest` plus a point map), a
semantic trait costs **less on an imported mesh than on a procedural component**
(1.13 ms vs 2.31 ms, because the mesh is not rebuilt), 3.74 ms on a mixed tree,
and the whole trait layer costs **~5 ms on 97** for 113 channels applied over
the 37 nodes of `humanoid_anatomical:body` (102.4 ms against 97.3 ms without).
**Frame validation does not register**: `compare()` is 0.0034 ms, and the
chimera's two policies (20.9 ms `diagnose`, 20.5 ms `strict`) differ by less
than the noise.

**[V6]** Authoring cost, same machine, median of 7
(`python tools/authoring_benchmark.py 7`). The target is not «fast», it is
**interactive**, and the row that matters is **a slider update at 1.17 ms**:
parameters travel in the plan, so moving one neither rewrites the plugin nor
reloads the registry. Importing a 5-object GLB is 3.4 ms, a preview rebuild
2.7 ms (3.7 with the quality gate), full validation 13.8 ms, saving the plugin
10.3 ms, reloading the registry 56.9 ms, reindexing 100 components 17.0 ms, and
«install and test» end to end 92.4 ms. The one expensive row is **cold staging
at 131 ms** — emitting the plugin plus loading 24 plugins — and it is the
declared price of letting the preview go through the real pipeline instead of
simulating it; it is paid once per structural change, not per keystroke.

**[V7]** Teach cost, same machine, median of 7
(`python tools/teach_benchmark.py 7`). The row that matters is the **coverage
analysis at 29.5 ms** for 10 nodes over 97 components — ~3 ms per node — because
it is recomputed after *every* install. The technical spec is 0.75 ms, the
implementation prompt 1.4 ms, staging a response (AST inspection included)
6.6 ms, the dossier 5.4 ms, a lab build 2.5 ms: everything the user waits on is
interactive. What is not: validating in process 5.4 ms but **in a subprocess
2887 ms** (an interpreter plus `trimesh`, ~530×, which is why it is off by
default), `accept` 91 ms (install + reindex + recompute), the intermediate
composite 185 ms, the **root composite 467 ms**, the completion report 128 ms,
reopening a project 60 ms, and `Session.generate` outside Teach 153 ms. A second
concept costs the same as the first (32 vs 29 ms), because the knowledge store
is read once.

**[V4]** Mesh-backed cost, same machine, median of 7
(`python tools/data_plugin_benchmark.py 7`): building a GLB-backed piece is
**cheaper** than a procedural one (0.26 ms vs 3.47 ms — a copy plus a scale),
and the cost moves to installation: ~5.4 ms per data component against ~1.4 ms
per code plugin, half of it the sha256 content fingerprint. Loading 22 code
plugins is 31 ms; adding one data plugin with 4 components and 3 GLBs makes it
54 ms. The semantic index does not notice the difference (15.2 → 15.1 ms),
because documents are built from declared metadata, not from geometry.

---

## 10. Documentation map

| Doc | Subject |
| --- | --- |
| `README.md` | human-facing overview and philosophy (English) |
| `ARCHITETTURA-CORE.md` (39 KB) | why the core is shaped this way, what was removed |
| `ARCHITETTURA-PLUGIN.md` (31 KB) | analysis behind the plugin architecture |
| `PLUGIN-AUTORI.md` (19 KB) | write a plugin without reading the core |
| `SEMANTIC-TRAITS-AND-EXTENSIONS.md` (28 KB) | semantic trait layer |
| `STRUCTURAL-TRAITS-AND-LAYOUT.md` (31 KB) | structural traits + layout engine |
| `STRUCTURAL-LAYOUT-VISUAL-POSTMORTEM.md` (6 KB) | what the visual results showed |
| `ARCHETYPES-AND-PROFILES.md` (56 KB) | concept resolution layer |
| `LOW-POLY-DESIGN.md` (49 KB) | the visual language |
| `TODO.md` | honest list of what is missing |
| `V1-RESULTS.md` … `V7-RESULTS.md` | what each milestone changed, measured |
| `V3-PLAN.md` | the V3 design note, written before the code |

README links `PLUGIN-AUTHORS.md`, `ARCHITECTURE-CORE.md`,
`ARCHITECTURE-PLUGIN.md`; the files on disk carry the Italian names above. Those
links are currently broken.

---

## 11. Known gaps (from `TODO.md`, still accurate)

1. Voice/text editing of an existing model (`Session.modify`) was removed with
   the legacy pipeline. Returning it needs a planner that *rewrites* a plan.
2. Image-to-model was removed for the same reason; the UI button is hidden.
   `reference.py` would have to emit a composition plan.
3. The offline planner matches words only — a plugin that forgets its tags is
   invisible to it, and the degradation is silent.
4. Knees do not bend: thigh, calf and foot are **siblings** on leg sockets, not
   a chain. Fixed by a test; fixing it properly is a composition choice inside
   `humanoid`.
5. Nothing grounds the model unless asked. `Scene.ground_offset` and
   `to_scene(ground=True)` exist, but there is no `ground` effect in the `final`
   stage.
6. Interpenetration is measured with axis-aligned boxes, so crossed blades read
   as overlapping without touching.
7. ~~Vocabulary size grows with plugins~~ — **fixed in V1**. The payload now
   follows the retrieved shortlist: 9 991 → 1 469–3 788 tokens on the eight
   audit prompts, and ~38 453 → 560–1 236 tokens on a 1 000-component library.
   See `V1-RESULTS.md`.
8. No validation against a real frontier model yet — single-repair, plan scoring
   and structured output are proven against fake providers.
9. ~~Structural traits depend on literal node paths~~ — **fixed in V3**. The
   prototype is chosen with the rule's own selector; `car` / `jeep` / `jeep1` /
   `auto_01` all produce six wheels, and `character:arm_count` builds 2/4/6
   anatomical arm chains on a plugin that had never worked. See `V3-RESULTS.md`.
10. ~~The planner does not use `structural_traits`~~ — **fixed in V3.5**. The
    diagnosis was wrong in one important way: `instance_count` was never
    invented, it is the alias of the installed `std:instance_count`, and it was
    the only structural trait the model was shown. Five measured causes, none in
    the engine: the prompt named neither plan key, a concept `adaptation` can
    never become a structural trait, the section title was a caption rather than
    a key, two aliases out of three were discarded, and on the audit's four-arms
    prompt `character:arm_count` was absent from the vocabulary because no bridge
    joined `braccia` to `braccio`. With a real LLM the planner now writes
    `structural_traits` on exactly the prompts that ask for a count, and
    «jeep with six wheels» builds six wheels (228 → 284 triangles). See
    `V3.5-RESULTS.md`.
11. ~~A nested `params` object on a known effect still kills a valid plan~~ —
    **fixed in V3.5**. It is normalized only when every inner key is a declared
    parameter of that effect and none conflicts with a value already present;
    then `EFFECT_PARAMS_FLATTENED`, and the flat and flattened plans converge to
    the same graph and the same geometry. An unknown key, a conflict, a `params`
    that is not an object and an unknown effect all stay fatal.
12. **The structural-trait relevance filter asks the wrong question.** It shows
    a trait when a shortlisted component satisfies its rule's target, but a
    structural trait works on a component's **declared children**, which
    retrieval does not index: `humanoid_anatomical:body` in the shortlist with
    no arm in it hid `arm_count`. The V3.5 word bridges work around this for the
    three installed traits; the real fix is to follow declared `Attachment`s
    transitively.
13. **Retrieval ranks parts above wholes.** «un robot con quattro braccia» gives
    a shortlist of arm pieces and no body, which is why a real model chose
    `humanoid:leg` as the root. `subject_capabilities()` from V2 already knows
    what a whole subject is, and retrieval does not use it.
14. **The `MockPlanner` writes no structural traits**, so the offline benchmark
    cannot exercise that layer at all.
15. ~~A component can only exist if Python builds it~~ — **fixed in V4**. A
    `type: "data"` plugin declares JSON components beside GLB/glTF meshes and
    installs ordinary `Component`s with no plugin code executed; `paladin`
    degrades onto a mesh-backed knight with no binding written by hand, and
    `wheel_count` clones procedural wheels onto a mesh body. See
    `V4-RESULTS.md`.
16. ~~**[V4] A data component's only parameter vocabulary is positive
    scaling**~~ — **fixed in V5.** A parameter declares `transform` **or**
    `effect`, and an `effect` binding names an installed `EffectSpec` plus one of
    its declared knobs. `curvature` on an imported tail drives `fx:bend` through
    the existing pipeline, moving vertices and sockets by the same map; the whole
    implementation is `EffectPipeline._from_params`. A data plugin still cannot
    name a callable, a module, an expression or a matrix. See `V5-RESULTS.md` §3.
17. **[V5] `frame` is a verified contract, and it still does not convert.** A
    mesh that contradicts its declared `growth_axis` gets
    `GROWTH_AXIS_MISMATCH` and is left alone, as in V4; what is new is that two
    *components* are compared on `up` and `front` at every link, so the
    fish-body/dragon-head/wings chimera now produces three explicit
    `FRAME_CONVERTIBLE` warnings naming the 180° rotation around Y and the
    `fx:rotate` request that applies it, fatal under `frame_policy: strict`.
    V5 deliberately chose the second of the two outcomes the milestone allowed:
    the composition is **not** silently accepted any more, and it is not
    auto-rotated either, because that would be a second placement system. 18 of
    the 23 plugins declare no frame, so for them the contract says nothing — that
    is its declared limit. See `V5-RESULTS.md` §7–§8.
18. **[V4] glTF materials arrive as colour, not as material.** A
    `baseColorFactor`, vertex colours or a texture become an "imported"
    `MaterialSpec` tint plus the colours kept on the mesh. No UVs, no PBR.
19. **[V4] One `mesh` per component**: no declared LODs, no variants, and
    `.my3d` never embeds the GLB — a project is reproducible only while the
    plugin is installed, which `changed_plugins` now reports.
20. **[V4] The content fingerprint is recomputed on every load** (~2.7 ms per
    GLB). With hundreds of data components it needs a cache keyed on mtime and
    size; it is the first number that degrades.
21. **A plan-declared child silently disappears at `detail_level 1`.**
    `validate_plan` gives it `level 2` by default and `wanted_at(1)` is false:
    no node, no diagnostic, `ok=True`. Same family as the lost requests V3.5
    closed for traits. Found while writing the V4 benchmark; not fixed.
22. ~~**`app/build/` is not under version control.**~~ — **fixed before V5.**
    `.gitignore` is `/build/` (anchored) and the six modules are tracked from
    commit `f5f0d8b`. For five milestones the "files changed" list was
    incomplete by construction; from V5 on it is not.
23. **[V5] A generic trait with `scope: subtree` and a role-selective trait
    collide.** Both write the same `(node, param)` channel on the selected part,
    so `TRAIT_RULE_CONFLICT` drops both — the existing policy, which refuses to
    choose for the author. Diagnosed, not fixed; the way out is a selector *in
    the request* (`{"trait": "part_scale", "role": "head"}`), which is a plan
    schema change. `V5-RESULTS.md` §5.
24. **[V5] A data parameter drives only numeric knobs.** `fx:bend`'s `axis`
    stays whatever the effect declares as its default, so a tail growing along
    +Z cannot say, from data, that its bend is computed along Z. Admitting a
    **constant** for the binding's other knobs is the declared next step.
25. **[V5] The installed library's semantic roles were not reassigned.**
    `humanoid:mouth.width` declares `girth`, and `std:width` reaches it that way
    rather than by its own name. Revising the 259 declared roles (134 `girth`,
    113 `length`, 12 `ratio`) would also change `std:body_mass`, so it is a
    content milestone with its own measurement.
26. **[V5] `repair_brief` mixes `alternatives` between entries sharing a code.**
    Three `FRAME_CONVERTIBLE` on three nodes give three entries with the right
    `where`, but the rendered text can show one node's suggested move next to
    another's message. It affects every code equally and predates V5.
27. **`MATERIAL_REDECLARED` noise**: `tree_stylized` redeclares `wood` with a
    second colour; the first declaration wins. It is a warning, so
    `report.ok` stays true, but it is in every registry report.

28. **[V6] The socket gizmo is readable but not draggable.** There is no
    picking in the viewport, so a socket moves through the snap helpers and the
    numeric fields. Adding it means a ray cast against the scene and a notion of
    «grabbed handle» — new code in the viewport, not in the contract. Declared
    rather than faked with a gizmo that cannot be grabbed.
29. **[V6] Selection is per scene node, never per face.** A GLB that arrives as
    one piece cannot be split inside 3DGen. Face selection needs a full mesh
    editor and auto-segmentation is another milestone, so this is the case where
    authoring does not help.
30. **[V6] Reopening a data plugin does not recover the object selection.** The
    per-component GLB is copied byte for byte, so nothing is lost; but whoever
    wants a different cut re-imports the original file. The editor-only field
    that would avoid it was deliberately not added — see `V6-RESULTS.md` §18.
31. **[V6] A variant recipe carrying traits or effects cannot be embedded in a
    composite.** An `Attachment` carries `params`; traits and effects are things
    of the *plan*. `embeddable` says which of the two you have and
    `AUTHORING_VARIANT_NOT_EMBEDDABLE` reports it instead of losing it quietly.
    The declared way out is an `effect`-backed parameter on the base component.
32. **[V6] Cold staging costs 131 ms**, and it grows with the number of GLBs a
    project rewrites. The way out is re-emitting only the changed files, which
    means a fingerprint **per component** instead of per project — and it makes
    debt 20 more expensive, because the registry recomputes its content
    fingerprint on every staging.
33. ~~**[V6] Coverage exists and is wired to nothing**~~ — **decided in V7.**
    `app/teach/coverage.py` reads the installed library against a concept's
    hierarchy and produces the four states from *named evidence*, never from a
    score threshold. The states themselves are still V6's, imported from
    `app/authoring/model.py`: two lists of four strings that must stay equal
    are one list too many.
34. **[V6] No authored or learned plugin was added to the installed library.**
    The data plugins of V4, V5, V6 and V7 all live in tests and temporary
    folders: the library is still 23 plugins and 97 components, all code. The
    day one lands in `app/plugins/`, that is a content milestone with its own
    measurement — and it is also how one finds out which part of the tool is
    actually annoying.
35. **[V7] A recursive response schema is not accepted by every structured
    output backend.** Groq answers `400 json_validate_failed` on the
    decomposition schema, which uses `$ref: "#/$defs/node"`. The external mode
    works identically, so nothing is blocked; the declared way out is a
    depth-flattened **variant** of the schema for those providers, not a
    replacement — an ontology has no known depth. Measured in
    `V7-RESULTS.md` §22.
36. **[V7] A validation record does not know when it went stale.** It records
    the plugin but not its fingerprint, so a component that changed afterwards
    still reads as a valid `prior_validation`. `TeachService.changed_components()`
    detects it **inside** a project; the knowledge store does not.
37. **[V7] A generated component is validated on its own, not on its parent.**
    It is loaded, built, measured and searched standalone; compatibility with
    the parent and the children is exercised later, when the composite is
    emitted. Building a `parent + child` plan inside the validation is the
    obvious next step.
38. **[V7] A composite's sockets are a declared convention.** They spread
    around a circle facing outwards: structurally correct, visually mediocre —
    the same distinction `TODO` draws at point 4-bis between structural
    correctness and layout quality. The way out is declaring `LayoutRegion`s on
    the composite, which `AuthoringService` already knows how to do.
39. **[V7] The knowledge store is linear.** Six records cost nothing; thousands
    will need an index on `(role, name)`, and the real question is whether the
    store should become a `Corpus` of the semantic index — the answer coherent
    with rule 10 — instead of a table.
40. **[V7] Raising `detail_target` after an analysis does not warn.** It works,
    and the nodes that become relevant start from zero with no diagnostic
    saying so. Same family as `TEACH_DECISION_LOST`, from the opposite side.

Explicitly out of scope for now: marketplace, remote registry, a real plugin
sandbox, cloud execution, background jobs, autonomous infinite loops, automatic
trust of generated Python, auto-generated GLB from text, unbounded repair loops,
full IK, full collision engine, CAD solver, distributed build, database. And,
still not started: `Session.modify`, image-to-model, arbitrary face editing,
sculpting, a UV editor, rigging, auto-segmentation, animation authoring, an
agent swarm.

---

## 12. Repository state (2026-10-15, after V7)

```text
main                      3141e04  checkpoint pre-V1 (the whole extension layer)
v1-semantic-index         a05c0d4  V1: semantic retrieval before the planner
                          193734b  V2: explainable semantic degradation
                          f5f0d8b  checkpoint V4: V3 + V3.5 + V4, plus app/build/
v5-semantic-variability   34f4791  V5: semantic variability + frame contract
                         (working) V6: component authoring
                         (working) V7: Teach 3DGen
```

**`f5f0d8b` is the V4 checkpoint, and it is the first commit whose file list is
complete.** It captured the whole working tree from V3 through V4 — which had
been uncommitted for three milestones — plus the six modules of `app/build/`
that the unanchored `build/` pattern had kept out of every previous commit
(§11.22, now closed). The suite was measured at 1506 green before it.

`3141e04` on `main` is the restore point: it captured everything that had been
sitting uncommitted (traits / structural / layout / archetype layer, the
stylized benchmark plugins, `humanoid_anatomical`, `archetype_metadata`, the
design docs, `PRODUCT-AUDIT.md`, `VISION-GAP.md`). The history before it
(`b124ee4`) predates all of that.

V1 and V2 both live on `v1-semantic-index`. V1 added
`app/core/planner/retrieval.py` and `tests/test_retrieval.py` and modified
`app/assets/semantic.py`, `app/core/planner/vocabulary.py`,
`app/core/registry.py`, `app/core/session.py`,
`app/plugins/vehicle_stylized/plugin.json`, `tests/test_api_freeze.py`.
V2 added `tests/test_degradation.py` and modified `app/core/archetypes.py`,
`app/core/session.py`, `app/core/planner/{retrieval,vocabulary,planner}.py`,
`tests/test_api_freeze.py`.
V3 added `tests/test_structural_identity.py` (56 tests), `V3-PLAN.md` (the
design note written before touching code) and `V3-RESULTS.md`, and modified
`app/core/structural.py`, `app/core/graph.py`, `app/core/planner/plans.py`,
`app/core/session.py`, the three `multi_*_extension` rules (one line removed
each), `tests/test_api_freeze.py` and `tests/test_traits.py` — the last one a
**deliberate contract change**, documented in `V3-RESULTS.md` §5.1.
V3.5 added `tests/test_planner_contract.py` (38 tests) and `V3.5-RESULTS.md`,
and modified `app/core/planner/{planner,vocabulary,plans,repair}.py`,
`app/core/{structural,session,registry}.py`, the three `multi_*_extension`
plugins (trait `purpose` and aliases, plus `synonyms` in each manifest),
`tests/test_api_freeze.py` (additive) and the two payload thresholds in
`tests/test_archetypes.py` and `tests/test_ai_providers.py` — **deliberate
contract changes**, documented in `V3.5-RESULTS.md` §7.2.
V4 added `app/core/data_plugin.py` (535 lines), `tests/test_data_plugin.py`
(101 tests), `tests/test_data_plugin_integration.py` (24 tests),
`tests/data_plugin_fixtures.py`, `tools/data_plugin_benchmark.py` and
`V4-RESULTS.md`, and modified `app/core/registry.py` (data discovery, manifest
validation, content fingerprint), `app/core/project.py` (fingerprints +
`changed_plugins()`), `app/core/graph.py` (`insert`/`roll` now survive
serialization — a **pre-existing** round-trip defect the milestone's `.my3d`
test exposed), `app/core/session.py` (`changed_plugins`, and `scene()` keeping
its registry), `app/core/{resolved,resolver,scene}.py`,
`app/core/planner/retrieval.py`, `app/build/{assembler,scene}.py` (ignored by
git) and `tests/test_api_freeze.py` (additive). Three declared contract
changes, all additive, in `V4-RESULTS.md` §23.
V5 added `app/core/frame.py` (310 lines),
`app/plugins/effects/effects/forma.py` (squash / elongate / taper / twist),
`app/plugins/variability_extension/` (six traits, 19 rules, 25 word bridges),
`tests/plugins/variabilita/procedural_probe/` (the procedural counterpart used
to prove backend independence), `tests/test_semantic_variability.py` (65 tests),
`tests/test_frame_contract.py` (27 tests), `tools/variability_benchmark.py` and
`V5-RESULTS.md`, and modified `app/core/vocabulary.py` (`ParamEffect`),
`app/core/component.py` (`frame`, `param_effects`), `app/core/effect.py`
(`_from_params`), `app/core/{resolver,resolved}.py` (the frame comparison on
every link), `app/core/registry.py` (`PluginInfo.frame`, the plugin frame as the
default, `_verify_param_effects`), `app/core/data_plugin.py` (the `effect`
strategy), `app/core/session.py` (`Options.frame_policy`),
`app/core/planner/vocabulary.py` (semantic roles and effect-backed knobs in the
rendered text), `app/core/planner/repair.py` (`FRAME_CONVERTIBLE` among the
repairable codes), `app/build/assembler.py` (piece bounds for local
deformations — a **pre-existing** socket desynchronization the milestone's own
probe exposed, `V5-RESULTS.md` §12), `cli.py` (`--frame-policy`), five plugin
manifests (one `frame` line each), `tests/data_plugin_fixtures.py` and
`tests/test_api_freeze.py` (additive). Four declared contract changes, all
additive, in `V5-RESULTS.md` §16.
V6 added `app/authoring/` (nine modules, 3869 lines: `service.py`, `model.py`,
`lab.py`, `gizmo.py`, `emit.py`, `variant.py`, `inspect.py`, `errors.py`,
`__init__.py`), `app/ui/authoring_window.py` (1627 lines),
`tests/authoring_fixtures.py`, `tests/test_authoring.py` (112 tests),
`tests/test_component_lab.py` (26 tests), `tests/test_authoring_ui.py`
(25 tests), `tools/authoring_benchmark.py` and `V6-RESULTS.md`, and modified
`app/core/data_plugin.py` (optional `mesh`, the two composite rules),
`app/core/session.py` (`reload_plugins`), `app/ui/main_window.py` (two toolbar
actions on the same `Session`) and `tests/test_api_freeze.py` (additive). Two
declared contract changes in `V6-RESULTS.md` §22, one of them — optional `mesh`
— the only **non-additive** change of the milestone, and a widening: every
definition that was valid before still is, and `tests/test_data_plugin.py`
passed unmodified.
V7 added `app/teach/` (eleven modules plus `__init__`, 5504 lines:
`service.py`, `model.py`, `staging.py`, `prompts.py`, `coverage.py`, `spec.py`,
`contracts.py`, `knowledge.py`, `schema.py`, `_runner.py`, `errors.py`),
`app/ui/teach_window.py` (995 lines), `tests/conftest.py`,
`tests/teach_fixtures.py`, `tests/test_teach_model.py` (58 tests),
`tests/test_teach_coverage.py` (44), `tests/test_teach_prompts.py` (48),
`tests/test_teach_staging.py` (81), `tests/test_teach_endtoend.py` (43),
`tests/test_teach_ui.py` (35), `tools/teach_benchmark.py`,
`tools/teach_provider_audit.py` and `V7-RESULTS.md`, and modified
`app/core/data_plugin.py` (the six key tuples promoted to module constants),
`app/core/registry.py` and `app/authoring/emit.py` (both read
`DATA_MANIFEST_KEYS` instead of keeping a copy) and `app/ui/main_window.py` (a
third toolbar action on the same `Session`). **`tests/test_api_freeze.py` was
not touched**: V7 adds nothing to the frozen surface. The one declared change
is a *removal* of duplication, documented in `V7-RESULTS.md` §25.
Results in `V1-RESULTS.md`, `V2-RESULTS.md`, `V3-RESULTS.md`,
`V3.5-RESULTS.md`, `V4-RESULTS.md`, `V5-RESULTS.md`, `V6-RESULTS.md` and
`V7-RESULTS.md`.

Scratch/output dirs to ignore (all git-ignored): `.tmp-tests/`,
`audit-images/`, `output/`, `build/`, `dist/`, `library/`, `__pycache__/`,
`.pytest_cache/`. Measurement artefacts and audit images live in
`audit-images/` and are deliberately not versioned.

---

## 13. Rules to respect when changing this codebase

1. No domain knowledge in the core. If a change needs to know what a house is,
   it belongs in a plugin.
2. `provides` and `accepts` are not interchangeable. A torso provides a place
   for a head; it is not a head.
3. Effects never create components. They modify parameters, vertices or pose.
4. Stage order is a contract (`app/core/vocabulary.py`). Changing it changes
   every model.
5. Quality is deterministic and numeric. Never ask a model whether geometry
   looks good.
6. Plugin-supplied text reaching the planner must pass
   `app/core/planner/vocabulary.py:sanitize()`.
7. The plan, not the mesh, is the artifact. `.my3d` and the asset library store
   plans plus plugin versions so a divergent regeneration can be explained.
8. UI, CLI and tests all go through `Session`, and concept resolution happens
   in `Session._verifica` — the one phase `generate()`, `build()` and a
   hand-written plan all reach. Never add a second generation path.
9. `tests/test_api_freeze.py` guards the public API — a signature change there
   is a deliberate decision, not a refactor side effect.
10. One retrieval engine. Indexing something new means adding a `Corpus` in
    `app/assets/semantic.py`, never a second index.
11. Domain word bridges ("a jeep is a car") are plugin data in `plugin.json`
    under `synonyms`, never code in the core.
12. An approximation is always declared. If the engine did not build what was
    asked for, `ConceptResolutionPlan.match` says so, `degradation()` explains
    it and the `.my3d` keeps it.
13. A hallucinated optional field (a concept, an archetype id, an unknown
    trait) must not destroy an otherwise valid plan. Degrade, diagnose,
    continue. The boundary is in `app/core/planner/plans.py`: what can be
    ignored safely is ignored and declared; what makes the plan ambiguous or
    unbuildable stays fatal — in particular an *ambiguous* name is not an
    unknown one, because skipping it would mean choosing on the author's behalf.
14. A structural rule selects its prototype, it never addresses one. If a change
    needs to know that the root is called `car`, it is wrong.
    `tests/test_structural_identity.py::test_structural_result_is_invariant_to_planner_node_ids`
    exists to make that regression fail.
15. The id the planner writes is not the identity of a node. Anything that has to
    recognise "the same arm" across a rewrite uses
    `CompositionGraph.identity()`, which the system derives and the model cannot
    write.
16. **A capability the planner cannot see does not exist.** V3 proved the
    structural layer worked and nothing called it, for a whole milestone,
    because the plan key was absent from the prompt and the trait was absent
    from the shortlist. Before concluding that a model "won't use" something,
    print what the model is actually shown:
    `Session().vocabulary(prompt=...)` and `LLMPlanner._render_message(...)`.
    `tests/test_planner_contract.py` asserts on the rendered **text** for
    exactly this reason — a test that reads the vocabulary objects would have
    passed throughout V3.
17. Every trait entry the planner sees says **which plan key it belongs to** and
    **what it selects**, derived from the rule's declared target. A knob with a
    numeric range and no stated subject cannot be chosen, only guessed.
18. Three categories of malformed plan element, distinguished by how much
    choice they require — not by severity: *unknown* is ignored and declared,
    *ambiguous or invalid* stays fatal, *wrong shape with a single possible
    reading* is normalized and declared. Adding a fourth is a decision; see
    `app/core/planner/plans.py` and `V3.5-RESULTS.md` §4.
19. `mode` on a structural trait belongs to the plan's author. `exact` fails,
    `best_effort` builds the rest and declares the request lost. The engine does
    not invent a tolerance, and `best_effort` never fails the plan.
20. **A component may get its geometry from a file, and nothing downstream may
    ask which.** `Component → build → Piece` is the whole contract; the three
    lines that know data plugins exist are in `app/core/registry.py`. A
    `if component.mesh_backed:` anywhere in `app/build/` or in the resolver is
    the regression, and `V4-RESULTS.md` §1 has the grep that proves it absent.
21. **A data plugin is data.** No import, no module path, no callback, no
    expression, no file outside its own directory — `safe_path()` is the only
    way a data plugin names a resource, and `DataPluginError` carries a code.
    Adding a key to the data format that names executable anything is not an
    extension, it is a different feature.
22. **A declaration the loader does not understand is refused, never ignored.**
    This is the opposite of rule 13 on purpose: a hallucinated field in a *plan*
    is a model's guess and must degrade, while an unknown field in an *authored
    file* is a contract mismatch that a future version would otherwise read
    backwards.
23. A request that was lost must be readable. `skipped()` for what did not
    happen, `structural_changes()` for what did; `ok=True` means geometry came
    out, never that the request was satisfied.
24. **A semantic trait targets a declared role, tag or parameter role — never a
    node path.** Rule 14 held for structural traits since V3; V5 found the same
    fragility in the semantic layer, because `on` addresses a node and the parts
    a request names (a head, a hand, a leg) are children the *component*
    declares, whose ids are paths the planner never wrote. That is why
    `std:head_scale` exists next to `std:part_scale`, and why
    `tests/test_semantic_variability.py::test_a_role_selective_trait_is_invariant_to_the_root_node_id`
    exists to make that regression fail.
25. **A parameter may ask for an effect; it may not be one.** `ParamEffect`
    names an installed `EffectSpec` and one of its declared knobs, and the
    translation into an `EffectRequest` lives in the `EffectPipeline`. A second
    deformation engine anywhere — in the data loader, in the trait resolver, in
    the builder — is the regression. The geometry still passes through the
    effect system, always.
26. **The frame contract compares `up` and `front`, and nothing else.**
    `growth_axis` is local and the socket frame already decides a child's
    rotation; comparing it would put a warning on every limb of every humanoid.
    And the contract **never converts**: it computes the rotation, names it, and
    names the installed `fx:rotate` that would apply it. Rotating a child
    against the socket its parent declared is a second placement system.
27. **An undeclared frame is silence, not a default.** A component that declares
    no convention is compared with nobody and produces no diagnostic. Inventing
    a convention for it would turn 18 plugins into noise, and a false frame is
    worse than no frame — for a planet or a cube, "where is the front" has no
    answer.
28. **[V6] Authoring is a layer above `Session`, and the UI is never the only
    way.** Every authoring operation exists as a method on `AuthoringService`,
    nothing in `app/authoring/` imports Qt, and
    `tests/test_authoring_ui.py::test_the_window_holds_no_authoring_logic`
    exists to make that regression fail. A panel that starts deciding something
    by itself means two ways of building a plugin, and the second one is the one
    V7 cannot call.
29. **[V6] A preview is a build, not a simulation.** The authoring layer emits
    a real data plugin and installs it in a throwaway `Session`; it never calls
    `trimesh` to approximate what the pipeline would produce. The moment a
    preview stops being an ordinary generation it starts lying, and it will lie
    in exactly the way the next pipeline change introduces.
30. **[V6] Editor state does not belong in the library.** Selection,
    visibility, the current component, the destination and the coverage of a
    part are properties of the work in progress, and the emitted plugin carries
    none of them. `AuthoringProject.fingerprint()` excludes them too, which is
    both the correctness argument and the reason a slider is responsive.
31. **[V7] A coverage state is read from named evidence, never from a score.**
    `CANDIDATE` needs identity *and* context; `VALIDATED` comes only from a
    confirmed solution, and no amount of evidence produces it.
    `tests/test_teach_coverage.py::test_no_amount_of_evidence_produces_validated`
    exists to make that regression fail. A model **recommends**: every
    `import_*` method writes a record, never a coverage.
32. **[V7] Generated Python is not trusted until somebody says so.** Staging
    writes files and inspects them; it imports nothing. Validating, installing
    or opening a code artifact in the lab all raise `TEACH_TRUST_REQUIRED`
    first. The static checks are warnings and are described as warnings, a
    subprocess is robustness and is described as robustness, and the word
    «sandbox» never appears in a message — because there is no sandbox. Adding
    one is a milestone, not a paragraph.
33. **[V7] The technical contract of a missing component belongs to 3DGen.**
    The capability, the sockets, the children, the frame, the budget and the
    parameter roles are derived from declared data and handed to the model as
    decisions. A prompt that asks a model to *choose* one of those is the
    regression, and a backend recommendation that names a part («a tail is
    procedural») is the other one: the rule is structural and
    `tests/test_teach_coverage.py` greps the code for domain words.
34. **[V7] The ontology of a concept is not the state of its coverage.**
    `TeachNode` is what the object is, `NodeState` is what we know about
    covering it, and merging them would mean losing a validated decision every
    time a refinement pass rewrites the hierarchy.
35. **[V7] A concept's root is a whole subject.** Candidates for it must
    provide a capability nobody accepts (`subject_capabilities()`), and parts
    must provide at least one capability or nothing can mount them. Without the
    first rule a dragon's best candidate is a dragon head, and because children
    read their context from the parent, one wrong root moves every child.
