# Structural Layout Visual Postmortem

This report audits the generated V1 benchmarks after structural validity and
geometric fit were already green. It intentionally does not add a new macro
feature, policy, trait, solver, or AI step.

## POST-A. Nine-tail diagnosis

The nine-tail graph is correct: 9 semantic tail nodes, 9 virtual placements,
9 distinct socket names, and uniform angular separation of 17.5 degrees.

The baseline root-frame measurement is the important result:

| metric | baseline |
| --- | ---: |
| minimum root-frame distance | 0.0117 |
| maximum root-frame distance | 0.0936 |
| child envelope radius | 0.1100 |
| adjacent AABB overlap ratio, mean | 0.873 |
| adjacent AABB overlap ratio, maximum | 0.915 |
| total elevation span | 0.0936 |
| effective depth separation | 0.0000 |

The cause is not the count or the angular formula. The fox region uses the
same vector for fan axis and elevation up, so `cross(axis, up)` is zero and
its declared depth offset cannot separate frames. The remaining elevation
span is much smaller than the child envelope. The fan is therefore attached
correctly but visually behaves like a thick continuous rear mass.

## POST-B. Fan correction

Two existing-contract experiments were evaluated and rejected:

1. Alternating depth offsets reduced the mean AABB overlap, but produced two
   occluding depth layers and fewer readable silhouettes in rear view.
2. A large elevation span separated roots numerically, but moved the outer
   tails behind or above the body in three-quarter view.

Neither experiment is retained. The final code is back on the V1 baseline;
the postmortem does not claim an unsupported visual improvement.

## POST-C. Before/after fox metrics

There is no accepted correction, so the final benchmark remains the baseline.
The rejected experiments are recorded above as evidence, rather than being
presented as an improvement. The final images are:

- [rear.png](output/structural_layout_benchmark/nine_tail_fox/rear.png)
- [three_quarter.png](output/structural_layout_benchmark/nine_tail_fox/three_quarter.png)
- [layout_plan.json](output/structural_layout_benchmark/nine_tail_fox/layout_plan.json)

## POST-D. Wheel diagnosis

The car does not have a real proximity defect. In the built local frame:

- body X bounds: `[-0.7254, 0.7254]`;
- wheel centers: `x = +/-0.8370`;
- wheel radius after scale-to-fit: `0.2428`;
- inner wheel edge: `0.5942`, overlapping the body-side envelope rather than
  floating away from it;
- wheel bottom: `y = 0.0472`, close to the ground contract;
- symmetry: 5 left and 5 right.

The apparent lateral distance in the render is camera perspective, not a
layout or virtual-socket error.

## POST-E. Wheel correction

No correction applied. The current plugin-owned region preserves longitudinal
distribution, bilateral symmetry, ground relation, and orientation. The
scale-to-fit path is exercised by the benchmark and remains deterministic.

## POST-F. Six-arm audit

The humanoid remains the cleanest architectural validation: 6 arms, 3 per
side, 6 distinct virtual sockets, no layout problems, and a readable torso
relationship. Its minimum root-frame distance is `0.0270`; the region is
intentionally compact because this is a structural benchmark, not an anatomy
beauty pass. No artistic correction was justified.

## POST-G. Layout correctness levels

V1 now distinguishes these concepts in the benchmark report:

1. Structural correctness: nodes, counts, groups, IDs.
2. Geometric correctness: valid frames, attachments, capacity, fit and scale.
3. Visual readability: a heuristic observation that repeated parts remain
   distinguishable in the intended view.

The third level is diagnostic language, not an aesthetic score or an LLM
judge. The current code does not add a `beauty_score`.

## POST-H. Core changes

No new public API was added for this postmortem. The V1 `LayoutRegion`, `fan`,
`linear`, virtual sockets and envelope contract were sufficient to measure the
failure. The existing fan math remains unchanged after the experiments were
rejected.

## POST-I. Plugin affordance changes

No final plugin affordance change was retained. The existing fox region is the
evidence: its current contract can express a fan, but not a readable nine-part
fan without making a stronger decision about projected envelope separation.
The car and humanoid regions remain unchanged.

## POST-J. Tests

The dedicated structural/layout tests cover distinct placements, duplicate
frames, count matrices, scale-to-fit, failure below minimum scale, third-party
traits and policies, save/load and idempotence. The benchmark harness rewrites
the canonical PNGs, GLBs, plans and provenance under
`output/structural_layout_benchmark/`.

## POST-K. Full suite

Final result: **1157 passed, 6 warnings**. The six warnings are the existing
numeric `trimesh` warnings from optimize tests. Benchmark warnings
`PARTS_INTERPENETRATE` remain non-fatal style diagnostics for fox/humanoid;
there are no attachment or `LayoutProblem` failures in the three benchmarks.

## POST-L. Remaining limitations

The fan does not perform collision solving or projected envelope packing. Its
angular frames are mathematically deterministic, while visual readability can
still be weak when the child envelope is wide relative to the angular span.
The car and humanoid cases are within their intended affordances.

## POST-M. Evidence for a new generic API

The evidence does **not** justify adding a richer `LayoutRegion`, an extra
orientation constraint, or a new policy in this phase. One benchmark exposes a
real readability limit, but the two direct affordance corrections tested were
not acceptable and only the fox demonstrates the missing contract. The right
future question is whether a generic projected-envelope readability contract
is needed across at least two independent domains. That belongs in a later
design task, not in this V1 postmortem.

The durable lesson is:

> Valid placement is not necessarily readable placement.

> Layout policy owns generic placement mathematics; plugin LayoutRegion owns
> domain-specific affordances.
