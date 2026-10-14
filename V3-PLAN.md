# V3-PLAN — Structural selectors + stable node identity

Design note written **before** any implementation, from a full read of
`PROJECT-INDEX.md`, `VISION-GAP.md`, `V2-RESULTS.md`, `PRODUCT-AUDIT.md`,
`TODO.md` and of the code actually on disk at `193734b`
(`app/core/structural.py`, `graph.py`, `layout.py`, `resolved.py`,
`planner/plans.py`, `planner/schema.py`, `project.py`, `session.py`, the three
`multi_*_extension` plugins, `fox_stylized`, `vehicle_stylized`,
`humanoid_anatomical`, `tests/test_structural_layout.py`,
`tests/test_api_freeze.py`, `tests/test_traits.py`).

**No source file has been modified yet.** This is the plan to execute.

---

## 1. Facts measured from the tree, not taken from the docs

* `StructuralTraitRule` has `prototype: str` and it is a **node path**
  (`corpo/torso/arm_l`, `car/wheel_fl`, `fox/body/tail`).
  `StructuralTraitResolver._prototype` resolves it with `graph.node(path)` and
  then `_materialize_path`, so the planner's node ids leak into semantics.
* `StructuralTarget` already selects by `role` / `capability` / `tags` /
  `components`, and each of the three rules **already declares one** in its
  `target` field. The correct prototype selector already exists in the data;
  nothing new has to be invented.
* The current tests pass only because they use the ids the rules expect:
  `_run("corpo", ...)`, `_run("car", ...)`, `_run("fox", ...)` in
  `tests/test_structural_layout.py`. The request's `on` is a literal path too.
* `_materialize_path` does something essential and easy to lose: besides the
  prototype chain it materializes **the prototype parent's whole declared
  sibling set**. That is why 10 wheels come out 5 left / 5 right — clones cycle
  over `wheel_fl/fr/rl/rr` via `prototypes[i % len(prototypes)]`.
* `.my3d` reload goes `project.load` -> `Session.restore` -> `Session.build(dict)`
  -> `_verifica` -> **`validate_plan`**, not `CompositionGraph.from_dict`. Any
  new per-node key emitted by `graph.to_dict()` would therefore be dropped with
  `NODE_UNKNOWN_KEY` on reload. This constrains the stable-identity design.
* `graph.to_dict()` already emits root-level `graph_rewrite_plan` and
  `layout_plan`, which are **not** in `plans.CHIAVI_RADICE` — today they produce
  benign `PLAN_UNKNOWN_KEY` warnings on reload.
* `graph.operations` is never serialized.
* Unknown trait is fatal in two places: `plans._traits` (`TRAIT_NOT_FOUND`) and
  `plans._structural_traits` / `structural._operations`
  (`STRUCTURAL_TRAIT_NOT_FOUND`).

## 2. Decisions

### 2.1 Prototype by selector, reusing `target` — no second selector type

`StructuralTraitRule.prototype` becomes **optional**. When it is empty the
prototype is selected with the rule's existing `target` (falling back to the
request's `target`). One selector per rule: the thing you count is the thing you
clone. A rule that genuinely needs them different can still declare a literal
`prototype` path — kept for back-compatibility, used by the synthetic
`std:instance_count` rule and by
`test_third_party_structural_trait_uses_only_generic_rewrite_runtime`.

The three extension rules drop `prototype` entirely and keep `target` unchanged.
That is DoD #3.

### 2.2 Selection over the resolved tree, then the existing path machinery

`_apply` resolves the graph once per operation (as `_materialize_path` already
does), walks the `ResolvedComposition`, collects candidates, picks one, and feeds
**its resolved path** into the existing `_materialize_path` +
`_compatible_siblings` + `_clone` machinery. The literal path survives only as a
runtime-discovered implementation detail; it is never authored. This keeps the
side-symmetry behaviour of section 1 for free.

### 2.3 Documented tie-breaking

Two passes. Strict first: candidates satisfying the whole selector. If empty, a
graded pass over candidates satisfying at least one facet, with a diagnostic
saying the prototype was chosen by partial match. Within a pass, ascending:

1. component exact match (`rule.component` or `target.components`)
2. role match
3. capability match
4. tag overlap (descending)
5. the parent declares a `LayoutRegion` whose `allows()` accepts the node
6. depth (shallowest — the top of the repeated group, not a link in its chain)
7. resolved path (stable order)

Facets 2-4 are constant inside the strict pass by construction; they discriminate
in the graded pass. Facets 5-6 are what make `character:arm_count` pick
`shoulder_l` (parent `torso` declares `left_arm_region` / `right_arm_region`,
`allows_role="arm"`) over `upper_arm` / `elbow` / `forearm`, which share
`role="arm"` at detail >= 2. At detail 1 `arm_l` / `arm_r` are
`humanoid_anatomical:arm` and win on facet 1.

No domain word enters the core: all seven facets read declared data.

### 2.4 `on` becomes a scope hint, not an address

`StructuralTraitRequest.on` (default `"root"`) restricts the candidate search to
the subtree of the resolved node with that exact path when such a node exists,
and is otherwise ignored. `on="corpo/torso/arm_l"` at detail >= 2 names a node
that the `replaces` chaining removed, so it falls back to the whole tree instead
of failing — the resilience the milestone asks for.

### 2.5 Parent and insertion from contracts only

The clone's parent is the prototype's own parent relation; the clone copies the
prototype's `Attachment`, hence its `Requirement` (capability + side + tags) and
`own_socket`, so socket compatibility is preserved. `LayoutEngine` then
distributes through the parent's declared `LayoutRegion` + `LayoutPolicy`. The
structural trait decides *how many*; layout decides *where*. Separation
unchanged.

Creating a prototype **from scratch** by selector (no instance declared anywhere)
stays out of V3: all three extensions and the cross-plugin case have a declared
instance. The existing literal-path from-scratch branch is kept. Recorded as
debt, not silently dropped.

### 2.6 Stable identity: derived, not a new persisted field

The milestone prefers derivation, and section 1 shows a persisted per-node key
cannot survive `.my3d` reload without widening the LLM-facing plan schema. So:

```
CompositionGraph.identity(node_id)   -> str   derived, memoized
CompositionGraph.identities()        -> dict  node id -> identity
CompositionGraph.by_identity(value)  -> node
```

`identity = sha1(parent_identity | ref | attachment signature | ordinal)[:12]`,
where the attachment signature is `own_socket` plus the requirement (capability,
socket_id, side, sorted tags), and the ordinal counts siblings with the same
(ref, signature) in `graph.order`. The root derives from `ref` alone.

Properties: system-generated by construction (a pure function — the LLM cannot
write it); survives serialization because it is recomputed, so old `.my3d` files
gain it with no format change; uses `node.ref`, not `resolved_ref`, so a `swap`
keeps the identity (same node, different provider); invariant to planner node id
renames and to parameter or effect changes; clones differ by ordinal.

Known limit, to be stated plainly in `V3-RESULTS.md`: deleting a same-signature
sibling shifts the ordinals after it. V3 has no delete path (`Session.modify` is
V4), so this is a declared boundary, not a hidden one.

`planner node id` (`CompositionNode.id`: free, written by the LLM, the address
used by `on`, `swap`, `target` and diagnostics) and `stable node identity`
(derived, structural, used by rewrites and provenance) both stay, and the
difference gets a docstring section in `app/core/graph.py`.

### 2.7 Clone provenance: serializable, reusing what exists

Enrich the existing `Operation` detail and
`StructuralTraitResolution.applied` / `created` with `trait`, `rule`, the
prototype identity, the clone identity, `clone_index` and `clone_count`. Because
`operations` is not serialized, add one root-level, deliberately
diagnostic-only list `CompositionGraph.structural_provenance`, emitted by
`to_dict()`, read back by `from_dict` **and** by `validate_plan` (added to
`CHIAVI_RADICE`), with entries whose identity matches no existing node dropped on
load — so a hallucinated blob cannot inject anything.

### 2.8 Unknown optional trait: warning plus skipped, as a general rule

Formalized as: *an unknown optional element produced by the planner must not
destroy an otherwise valid structure when it can be ignored safely.*

It becomes `warn("UNKNOWN_TRAIT_SKIPPED", ... trait = <name>)` and the element is
dropped from the graph's trait list, in `plans._traits`,
`plans._structural_traits` and `structural._operations`.

Deliberately still fatal: `TRAIT_AMBIGUOUS` (ambiguous, not unknown),
`TRAIT_NO_ID` / `TRAIT_NO_VALUE` (malformed, i.e. schema),
`TRAIT_*_UNSUPPORTED` (known trait, invalid value), `COMPONENT_NOT_FOUND`,
impossible essential attachments, and `EFFECT_NOT_FOUND` — the milestone scopes
the new policy to semantic and structural traits, and an effect is attached to a
named node, so widening it would weaken `tests/test_core_effects.py:119`,
`tests/test_planner_core.py:297` and `tests/test_plugins.py:328` beyond the
stated scope. Recorded as a decision, with the exact shape of the change, not as
an oversight.

`GenerationResult.skipped()` gains the skipped traits, derived from the report
(no new field), so `explain()` and `to_dict()` show them.

`tests/test_traits.py:285-301` encodes the old contract (`graph is None` for an
unknown trait). It is **deliberately rewritten**, not quietly adjusted: the new
assertions are graph not None, `UNKNOWN_TRAIT_SKIPPED` in `report.codes()`,
`graph.traits == []`. The reason belongs in `V3-RESULTS.md`: the old contract let
a single hallucinated optional field destroy a valid root, which is the same
defect V2 section 1.4 removed from the `concept` branch.

## 3. Work still to do, in order

1. `app/core/structural.py` — selector-based `_prototype`, documented
   tie-breaking, `on` as scope, provenance fields, unknown-trait warning.
2. `app/core/graph.py` — `identity()` / `identities()` / `by_identity()`,
   `structural_provenance`, docstring on the two kinds of id.
3. `app/core/planner/plans.py` — unknown trait policy, `structural_provenance`
   in `CHIAVI_RADICE`.
4. `app/core/session.py` — `skipped()` surfaces `UNKNOWN_TRAIT_SKIPPED`.
5. The three `multi_*_extension` rules — drop `prototype`.
6. `tests/test_api_freeze.py` — additive update (new graph methods and field).
7. `tests/test_traits.py` — the one deliberate contract change.
8. New tests: selector-based prototypes; rename invariance (build a plan, rename
   every planner node id arbitrarily, apply the same structural trait, compare
   the resulting semantic structure); 2/4/6 arms **with the anatomical chain
   verified**, not just a surface count; 4/6/8 wheels under root ids `car` /
   `jeep` / `jeep1` / `auto_01` with none of those names in any rule; tails;
   stable identity across rewrite and serialization; clone provenance;
   plan -> graph -> rewrite -> serialize -> deserialize round-trip; unknown
   optional trait policy; cross-plugin composition (humanoid body + creature
   head + `arm_count = 4`) checking that unrelated parts are untouched.
9. Full suite, then the 8 `PRODUCT-AUDIT` prompts with a real LLM, then latency
   measurements for rewrite, layout and identity overhead.
10. `V3-RESULTS.md`, and only then `PROJECT-INDEX.md` and `TODO.md` from the real
    working tree.
