# 3DGen — Project Index (for AI agents)

Machine-oriented index of the repository. Written to let another AI understand
the architecture, locate code, and make changes without re-exploring the tree.
Generated 2026-10-14 from the working tree; updated after milestones V1
(semantic retrieval), V2 (explainable semantic degradation), V3 (structural
selectors + stable node identity), V3.5 (planner contract robustness) and V4
(mesh-backed components declared in data). See "Repository state" at the end.

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
| `app/ui/main_window.py` | UI shell; also provider/failover selection |

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
`shortlist(prompt, style)`, `undo()`/`redo()`/`goto(i)`, properties `current`,
`current_plan`, `scene`, `result`.

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
`repair`, `check`. Everything else belongs in the plan, because the plan is the
only place a decision stays readable.

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
| `resolver.py` | 873 | `Resolver` — candidate scoring and socket matching (weights: capability 16, side 8, style 4, tag 1) |
| `archetypes.py` | 1188 | `ArchetypeSpec`, `ProfileSpec`, `ImplementationBinding`, `ConceptResolver`, `ConceptResolutionPlan`, coverage/diagnostics; **[V2]** `subject_capabilities`, `normalize_reference`, `MATCH_*`, the degradation ladder |
| `graph.py` | 842 | `CompositionGraph`, `CompositionNode`, `EffectRequest`, `Operation`; param provenance (`FROM_DEFAULT/DERIVED/OVERRIDE/EFFECT/TRAIT`); `to_dict`/`from_dict`; **[V3]** derived stable node identity (`identity`/`identities`/`by_identity`, `_signature`, `_digest`) and `structural_provenance` |
| `effect.py` | 568 | `Scope`, `PlannedEffect`, `EffectContext`, `EffectPipeline`, `apply_effects` |
| `structural.py` | 810 | structural traits: `StructuralTarget`, `EnsureCountOperation`, `GraphRewritePlan`, `StructuralTraitResolver` (cap `MAX_STRUCTURAL_COUNT = 64`); **[V3]** selector-based prototype choice (`_locate`/`_discover`/`_rank`), `on` as a search scope, clone provenance, `UNKNOWN_TRAIT_SKIPPED`; **[V3.5]** `_prototipo_mancante` — `mode` decides the severity of a missing prototype (`exact` fatal, `best_effort` warning + skipped) and the `why` names the three moves that fix it |
| `layout.py` | 427 | `LayoutRegion`, `LayoutFrame`, `LayoutPlacement`, `LayoutPlan`, `LayoutEngine`, `fan_policy`, `linear_policy` |
| `traits.py` | 426 | semantic traits: `TraitSpec`, `TraitRule`, `TraitMatch`, `ParamPatch`, `TraitResolver`, `resolve_traits` |
| `params.py` | 273 | `ParamSpec`, sandboxed expression `evaluate()` (AST whitelist), scopes `self`/`parent`/`root`, types FLOAT/INT/BOOL/ENUM/STRING/VECTOR2/VECTOR3/COLOR |
| `resolved.py` | 263 | `ResolvedNode`, `ResolvedLink`, `ResolvedValue`, `ResolvedComposition` |
| `component.py` | 240 | `Component`, `Attachment`, `Piece`, `BuildContext` |
| `capability.py` | 242 | `Capability`, `Requirement`, `Mount`, `best_match`, match tiers (`EXACT_ID 5` … `INCOMPATIBLE -1`), sides `l/r/center/top/bottom/front/back` |
| `socket.py` | 238 | `Socket`, `Placement`, `attach()`, scale modes `none`/`socket`/`fit_replaced` |
| `vocabulary.py` | — | `EffectSpec`, `StyleProfile`, scopes, **stage constants** |
| `project.py` | 315 | `.my3d` format v2 — stores plans + plugin identities/versions, not meshes; **[V4]** `ProjectInfo.fingerprints` + `changed_plugins()`, which turn `PLUGIN_VERSION_CHANGED` / `PLUGIN_CONTENT_CHANGED` into diagnostics on the *rebuilt* result |
| `data_plugin.py` | 535 | **[V4]** the data-only loader: JSON + GLB/glTF → the existing `Component`/`Piece`/`Socket`/`ParamSpec`/`Attachment`/`LayoutRegion`/`MaterialSpec`. `safe_path()` confines every resource to the plugin directory, `load_component()`, `load_material()`, `DataPluginError` with stable codes (`DATA_PATH_UNSAFE`, `DATA_MESH_*`, `DATA_PARAM_UNSUPPORTED`, `DATA_FRAME_INVALID`, `DATA_JSON_INVALID`, `DATA_SCHEMA_INVALID`, `DATA_FILE_MISSING`). No Python from the plugin is ever imported |
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

## 5. Three extension layers above plain components

These are the newest and least documented parts of the system.

1. **Semantic traits** (`app/core/traits.py`) — a named semantic knob
   (`body_mass`, `leafiness`) that a plugin maps onto public component
   parameters or effects via `TraitRule`/`ParamPatch`. Scope `local` or
   `subtree`; op `set` or `add`. Applied *after* resolution, *before* effects.
   Reference plugins: `body_mass_extension`, `tree_leafiness_extension`.

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

`LayoutEngine` (`app/core/layout.py`) sits alongside: when many siblings must
share a parent surface, declared `LayoutRegion`s plus a `LayoutPolicy`
(`fan`, `linear`) synthesize the sockets instead of the plugin hardcoding them.

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
- `app/ui/` — `main_window.py`, `viewport.py`, `render_core.py`,
  `offscreen.py`, `workers.py` (threaded generation).

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
`dependencies[]`, `metadata{}`, `synonyms{}`. Component ids are `plugin:name`.

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
additions: `mesh` (the GLB path, relative to the component file) and
`params[*].transform`, which must be one of `scale_x` / `scale_y` / `scale_z`
/ `uniform_scale`. A parameter without a declared transform is refused rather
than assumed: see `V4-RESULTS.md` §6. `frame` (`growth_axis`/`front`/`up`) is
verified with `app/core/authoring.py:verify_frame` and **diagnosed, never
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
**22 plugins, 97 components, 30 materials, 8 effects, 27 capabilities,
9 archetypes, 1 profile, 3 bindings, 2 semantic traits, 4 structural traits,
16 declared synonyms.** All 22 are code plugins: **[V4]** deliberately
converted none of them. The data-only plugins live in
`tests/data_plugin_fixtures.py`, which writes real directories of JSON + GLB to
disk (`mesh_fixture`: a knight, a body, a head and a crest; `mesh_vehicle`: a
mesh body with procedural wheels and declared layout regions).

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
| `fx` (dir `effects/`) | lanky, chunky, bend, perspective_exaggeration, rotate, align, offset, mirror |
| `fox_stylized` | authored angular low-poly fox benchmark + palette |
| `tree_stylized` | authored chunky asymmetric tree benchmark + palette |
| `vehicle_stylized` | authored low-poly compact car benchmark + palette |
| `body_mass_extension` | semantic trait `body_mass` |
| `tree_leafiness_extension` | semantic trait `leafiness` |
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

`1506 tests` (`python -m pytest -q`; `pytest.ini` + `conftest.py` at root).
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
Fixture plugins live in `tests/plugins/` (including intentionally malformed
ones); the data-only fixtures are written to a tmp dir by
`tests/data_plugin_fixtures.py`.

`tools/`: `benchmark.py`, `render_benchmark.py`, `render_scenari.py`,
`archetype_benchmark.py`, `archetype_validation.py`, `semantic_traits_benchmark.py`,
`structural_layout_benchmark.py`, `fox_stylized_benchmark.py`,
`tree_stylized_benchmark.py`, `ai_provider_smoke.py`,
`data_plugin_benchmark.py` (**[V4]**: plugin discovery, GLB load, build,
semantic index and total local generation, for a procedural, a mesh-backed and
a mixed composition).

Local pipeline performance (no network): total 6–13 ms median — plugin load
16 ms, vocabulary 3 ms, local planner 1 ms, resolver 0.2 ms, effects 0.1 ms,
builder 3–10 ms, quality 1–3 ms.

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
| `V1-RESULTS.md` / `V2-RESULTS.md` / `V3-RESULTS.md` / `V3.5-RESULTS.md` / `V4-RESULTS.md` | what each milestone changed, measured |
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
16. **[V4] A data component's only parameter vocabulary is positive scaling**
    (`scale_x/y/z`, `uniform_scale`). Mapping a parameter onto an installed
    *effect* — the same move `TraitRule` already makes for public parameters —
    is the declared next step; until then an imported mesh has no semantic knob
    of its own, and a semantic trait reaches it only through `role`, `tags` and
    `param_roles`.
17. **[V4] `frame` diagnoses, it does not convert.** A mesh that contradicts its
    declared `growth_axis` gets `GROWTH_AXIS_MISMATCH` and is left alone. The
    dragon standing on its tail is still standing on its tail.
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
22. **`app/build/` is not under version control.** `.gitignore:11` is `build/`,
    which also matches `app/build/`, so `assembler.py`, `validate.py`,
    `scene.py`, `exporter.py`, `optimize.py` and `visual.py` are in no commit
    (`git check-ignore -v app/build/scene.py`). Until the pattern is anchored
    (`/build/`), the "files changed" list of **every** milestone is incomplete
    by construction, and three of those files were changed by V4.
23. **`MATERIAL_REDECLARED` noise**: `tree_stylized` redeclares `wood` with a
    second colour; the first declaration wins. It is a warning, so
    `report.ok` stays true, but it is in every registry report.

Explicitly out of scope for now: marketplace, remote registry, plugin sandbox,
cloud execution, auto-generated plugins, unbounded repair loops, LLM visual
judgement, full IK, full collision engine, CAD solver, distributed build,
database.

---

## 12. Repository state (2026-10-14, after V4)

```text
main                 3141e04  checkpoint pre-V1 (the whole extension layer committed)
v1-semantic-index    a05c0d4  V1: semantic retrieval before the planner
                     193734b  V2: explainable semantic degradation
                     (working) V3: structural selectors + stable node identity
                     (working) V3.5: planner contract robustness
                     (working) V4: mesh-backed components declared in data
```

Everything from V3 onwards is **uncommitted working tree**, and `app/build/` is
git-ignored on top of that (§11.22), so `git status` is not a complete picture
of what changed.

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
Results in `V1-RESULTS.md`, `V2-RESULTS.md`, `V3-RESULTS.md`,
`V3.5-RESULTS.md` and `V4-RESULTS.md`.

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
