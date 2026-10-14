# 3DGen — Project Index (for AI agents)

Machine-oriented index of the repository. Written to let another AI understand
the architecture, locate code, and make changes without re-exploring the tree.
Generated 2026-10-14 from the working tree (many files are still uncommitted —
see "Repository state" at the end).

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
 → ConceptResolver (optional)              app/core/archetypes.py
 → Planner (LLM or Mock)                   app/core/planner/planner.py
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

`Session` public surface: `generate(prompt, options)`, `plan(prompt)`,
`build(plan)`, `regenerate()`, `configure_ai(provider, model, chain)`,
`export(path)`, `save_project(path)`, `catalog()`, `vocabulary(style)`,
`undo()`/`redo()`/`goto(i)`, properties `current`, `current_plan`, `scene`,
`result`.

`Options` is deliberately tiny: `style`, `detail_level`, `seed`, `budget`,
`repair`, `check`. Everything else belongs in the plan, because the plan is the
only place a decision stays readable.

`GenerationResult` carries `ok`, `diagnostics`, `triangles`, `scene()`,
`mesh()`, `explain()`, `changes()`, `skipped()`, `describe()`, `to_dict()`, and
provider provenance (`requested_provider/model`, `actual_provider/model`,
`failover_count`).

---

## 4. Core modules (`app/core/`)

| File | Lines | Contents |
| --- | --- | --- |
| `session.py` | 951 | `Session`, `Options`, `GenerationResult`, `Version` history |
| `registry.py` | 1216 | `Registry`, `PluginInfo`, `CapabilityInfo`, plugin discovery/manifest reading, `freeze()`, `verify()` |
| `resolver.py` | 873 | `Resolver` — candidate scoring and socket matching (weights: capability 16, side 8, style 4, tag 1) |
| `archetypes.py` | 883 | `ArchetypeSpec`, `ProfileSpec`, `ImplementationBinding`, `ConceptResolver`, `ConceptResolutionPlan`, coverage/diagnostics |
| `graph.py` | 644 | `CompositionGraph`, `CompositionNode`, `EffectRequest`, `Operation`; param provenance (`FROM_DEFAULT/DERIVED/OVERRIDE/EFFECT/TRAIT`); `to_dict`/`from_dict` |
| `effect.py` | 568 | `Scope`, `PlannedEffect`, `EffectContext`, `EffectPipeline`, `apply_effects` |
| `structural.py` | 473 | structural traits: `StructuralTarget`, `EnsureCountOperation`, `GraphRewritePlan`, `StructuralTraitResolver` (cap `MAX_STRUCTURAL_COUNT = 64`) |
| `layout.py` | 427 | `LayoutRegion`, `LayoutFrame`, `LayoutPlacement`, `LayoutPlan`, `LayoutEngine`, `fan_policy`, `linear_policy` |
| `traits.py` | 426 | semantic traits: `TraitSpec`, `TraitRule`, `TraitMatch`, `ParamPatch`, `TraitResolver`, `resolve_traits` |
| `params.py` | 273 | `ParamSpec`, sandboxed expression `evaluate()` (AST whitelist), scopes `self`/`parent`/`root`, types FLOAT/INT/BOOL/ENUM/STRING/VECTOR2/VECTOR3/COLOR |
| `resolved.py` | 263 | `ResolvedNode`, `ResolvedLink`, `ResolvedValue`, `ResolvedComposition` |
| `component.py` | 240 | `Component`, `Attachment`, `Piece`, `BuildContext` |
| `capability.py` | 242 | `Capability`, `Requirement`, `Mount`, `best_match`, match tiers (`EXACT_ID 5` … `INCOMPATIBLE -1`), sides `l/r/center/top/bottom/front/back` |
| `socket.py` | 238 | `Socket`, `Placement`, `attach()`, scale modes `none`/`socket`/`fit_replaced` |
| `vocabulary.py` | — | `EffectSpec`, `StyleProfile`, scopes, **stage constants** |
| `project.py` | 251 | `.my3d` format v2 — stores plans + plugin identities/versions, not meshes |
| others | — | `budget.py` (triangle budgets), `constraints.py`, `material.py`, `scene.py`, `authoring.py` (socket helpers, frame verification), `recovery.py`, `hardware.py`, `errors.py`, `logging_setup.py`, `config.py` (`Settings`, `ProviderSpec`, `DEFAULT_CHAIN`) |

### Planner (`app/core/planner/`)

- `planner.py` (602) — `Planner` ABC, `MockPlanner` (offline word-matching),
  `LLMPlanner`, `make_planner`, Italian system prompt `SISTEMA`, repair prompt
  `CORREZIONE`. Limits: `MAX_NODI = 14`, `MAX_PROFONDITA = 4`.
- `schema.py` (207) — JSON Schema `PLAN_SCHEMA`, version **1.3**. A plan has
  `oneOf: [concept, root]`, plus `version`, `style`, `detail_level`, `seed`,
  `traits[]`, `structural_traits[]`.
- `plans.py` (472) — `validate_plan()` → `CompositionGraph`. Hard limits
  `MAX_NODI = 200`, `MAX_PROFONDITA = 12`.
- `vocabulary.py` (760) — what the LLM is shown: `ComponentEntry`,
  `EffectEntry`, `TraitEntry`, `ArchetypeEntry`, `ProfileEntry`,
  `BindingEntry`, `CapabilityEntry`. **`sanitize()` is a security boundary**:
  third-party descriptions are flattened to one quoted line, control chars
  stripped, `system:`/`assistant:`/`user:` markers removed, 160-char cap. A
  plugin must not be able to inject instructions into the planner.
- `repair.py` (232) — `repair_brief()`, `plan_score()`, `PlanScore`.

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
them.

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
   `EnsureCountOperation`s that clone a prototype node and materialize
   addressed paths. Modes `exact` / `best_effort`. Runs before resolution.
   Reference plugins: `multi_arm_extension`, `multi_wheel_extension`,
   `multi_tail_extension`.

3. **Archetypes / profiles / bindings** (`app/core/archetypes.py`) — concept
   resolution. A plan may say `{"concept": {"requested": "fox"}}` instead of a
   component tree; `ConceptResolver` maps the concept to archetypes (semantic
   families, inheritable), profiles (reusable default trait bundles) and
   `ImplementationBinding`s (concept → installed component), then reports
   `ConceptCoverage` per requested adaptation: supported, unsupported or
   ignored. Registered by the `archetype_metadata` plugin.

`LayoutEngine` (`app/core/layout.py`) sits alongside: when many siblings must
share a parent surface, declared `LayoutRegion`s plus a `LayoutPolicy`
(`fan`, `linear`) synthesize the sockets instead of the plugin hardcoding them.

---

## 6. Geometry, build, output

- `app/geometry/kernel.py` — the only low-level mesh maker: `ring`, `sweep`,
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
  (`TfidfEmbedder`, `RemoteEmbedder`, `SemanticIndex`) powering `--find`.
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
`dependencies[]`, `metadata{}`. Component ids are `plugin:name`.

Current registry contents (measured, not from docs):
**22 plugins, 97 components, 30 materials, 8 effects, 27 capabilities,
9 archetypes, 1 profile, 3 bindings, 2 semantic traits, 4 structural traits.**

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

`1213 tests collected` (`python -m pytest -q`; `pytest.ini` + `conftest.py` at
root). Tests target the **contracts between** modules, not just units:
`test_core_contracts.py`, `test_core_registry.py`, `test_core_resolver.py`,
`test_core_graph.py`, `test_core_effects.py`, `test_planner_core.py`,
`test_planner_llm.py`, `test_api_freeze.py` (frozen public API),
`test_traits.py`, `test_structural_layout.py`, `test_archetypes.py`,
`test_profiles.py`, `test_concept_resolution.py`, `test_build_pipeline.py`,
`test_validation.py`, `test_visual.py`, `test_golden.py`, `test_performance.py`,
`test_benchmark_reale.py`, `test_distribution.py`, `test_ui.py`,
`test_fox_stylized.py`, `test_tree_stylized.py`, `test_vehicle_stylized.py`,
`test_humanoid_anatomical.py`, `test_ai_providers.py`. Fixture plugins live in
`tests/plugins/` (including intentionally malformed ones).

`tools/`: `benchmark.py`, `render_benchmark.py`, `render_scenari.py`,
`archetype_benchmark.py`, `archetype_validation.py`, `semantic_traits_benchmark.py`,
`structural_layout_benchmark.py`, `fox_stylized_benchmark.py`,
`tree_stylized_benchmark.py`, `ai_provider_smoke.py`.

Local pipeline performance (no network): total 6–13 ms median — plugin load
16 ms, vocabulary 3 ms, local planner 1 ms, resolver 0.2 ms, effects 0.1 ms,
builder 3–10 ms, quality 1–3 ms.

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
7. Vocabulary size grows with plugins (~16 KB / ~4100 tokens at 44 components);
   at a few hundred it must be filtered by capability and tag before being sent.
8. No validation against a real frontier model yet — single-repair, plan scoring
   and structured output are proven against fake providers.

Explicitly out of scope for now: marketplace, remote registry, plugin sandbox,
cloud execution, auto-generated plugins, unbounded repair loops, LLM visual
judgement, full IK, full collision engine, CAD solver, distributed build,
database.

---

## 12. Repository state (2026-10-14)

Branch `main`, synced with `origin/main` at `0f8a0b2 Update README.md`.

A large amount of work is **uncommitted**: the whole traits / structural /
layout / archetype layer and the stylized benchmark plugins. Untracked:
`app/core/{traits,structural,layout,archetypes}.py`, 9 plugin directories,
10 test files, 7 tools, 5 design docs. Modified: `app/core/` (component,
config, effect, graph, registry, resolved, session, planner/*), `app/ai/provider.py`,
`app/ui/main_window.py`, `.env.example`, `README.md`, 4 test files.

Consequence for an agent reading the committed history: the last commit
(`b124ee4`) predates the three extension layers. Trust the working tree and this
index, not `git log`.

Scratch/output dirs to ignore: `.tmp-tests/`, `output/`, `build/`, `dist/`,
`library/`, `__pycache__/`, `.pytest_cache/`.

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
8. UI, CLI and tests all go through `Session`. Never add a second generation
   path.
9. `tests/test_api_freeze.py` guards the public API — a signature change there
   is a deliberate decision, not a refactor side effect.
