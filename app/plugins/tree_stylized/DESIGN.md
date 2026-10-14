# Stylized Low-Poly Tree

Design specification for the third 3DGen artistic benchmark.

This file is design-only. It does not define a manifest, Python components,
materials, tests, benchmark scripts, or kernel primitives. The future plugin
must be authored after this specification is reviewed.

The benchmark must answer one question:

> Can 3DGen produce controlled organic irregularity without anatomy, smooth
> blobs, or random noise?

It must not modify the existing `nature` plugin. That plugin is a compatibility
scenario containing a simple trunk, a foliage child, branch sockets, a nest,
and a bird. Its tree is intentionally close to a faceted blob on a trunk and
its branch sockets are not yet a designed branch silhouette. `tree_stylized`
is a separate visual benchmark, not a replacement or a copy.

## TREE-A. Plugin identity

### Proposed name

`tree_stylized`

### Responsibility

Provide one complete, deliberately authored broad-canopy tree with a strong
trunk, visible major branch structure, a small hierarchy of crown lobes,
controlled asymmetry, and intentional negative spaces.

The plugin owns tree-specific proportions, profiles, local planar meshes,
materials, sockets, and detail-level expansion. It must not teach the core
what a branch or a crown is. It must reuse general contracts when their
meaning is truthful.

### What this benchmark is not

- a realistic tree with fewer polygons;
- a trunk cylinder with a green sphere;
- a botanical simulator;
- a recursive L-system;
- a collection of random icospheres;
- a leaf-by-leaf or twig-by-twig asset;
- a new kernel primitive experiment disguised as a plugin.

The design order is:

```text
silhouette -> trunk flow -> major branch rhythm -> crown masses
-> negative spaces -> sparse accents
```

## TREE-B. Shape language

The proposed shape language is:

```text
tapered + chunky + asymmetric + faceted
```

These words are geometric commitments, not mood labels.

### Tapered

- the trunk narrows upward, but does not become a uniform cone;
- major branches narrow toward their outer ends;
- crown lobes converge slightly toward their outer contour;
- cross-sections change at a few intentional stations rather than through
  high-frequency noise.

### Chunky

- the trunk has a broad, stable base;
- the major branches are few and visually substantial;
- the crown is made from large masses, not many equal small pieces;
- the model remains readable at thumbnail scale;
- roots or base flare may widen the grounding without becoming a root system.

### Asymmetric

- the crown center is deliberately offset;
- branch heights and angles are unequal;
- lobe sizes have a visible hierarchy;
- one side is dominant while the opposite side balances it;
- there is no perfect bilateral mirror, but the tree still has visual balance.

Asymmetry means controlled imbalance that improves the silhouette. It does not
mean random displacement.

### Faceted

- large planes catch light differently;
- normal changes happen at profile or silhouette decisions;
- trunk and branches use a low number of meaningful sides;
- crown lobes have broad planar regions;
- no smooth sphere is decimated into arbitrary micro-faces.

## TREE-C. Canonical tree type

The first benchmark is a **stylized broad-canopy tree with a strong trunk,
visible branch structure, and asymmetric crown lobes**.

This is deliberately less specific than an oak, willow, or magical fantasy
tree. It gives the benchmark room to test branching and composition without
requiring botanical correctness. The identity should feel suitable for a game
world or readable thumbnail: sturdy, slightly irregular, and designed around
its silhouette.

The canonical tree has:

- a broad trunk base with a restrained lean;
- three or four visible major branch directions;
- one dominant crown lobe;
- two medium lobes;
- one or two supporting/rear lobes;
- clear windows between trunk, branches, and crown masses.

The crown is a composition of masses, not one sphere and not a cloud of equal
parts.

## TREE-D. Silhouette responsibilities

The tree must be rendered from front, side, and three-quarter views before it
is accepted. The three-quarter view is the primary design audit, but no view
may be treated as the only truth.

### Front

The front view must show:

- a broad but tapered trunk;
- a readable main branch split;
- unequal crown width on the two sides;
- the dominant lobe and the lower medium lobe;
- at least two intentional openings between trunk, branches, and crown;
- enough separation that the tree is not a single dark vertical mass.

The front view is responsible for the tree's width, stance, branch split, and
controlled asymmetry.

### Side

The side view must avoid a flat wall of foliage. It must show:

- crown depth, not only crown width;
- a forward/back branch variation;
- a slight trunk lean or section change;
- at least one lobe separation in depth;
- an opening under the main canopy;
- a trunk-to-crown relationship that is not a cylinder below a disk.

The side view is responsible for depth ordering and the directional flow of
the trunk and branches.

### Three-quarter

The three-quarter view is the main composition audit. It must show:

- hierarchical branching rather than a radial bundle;
- overlap between crown lobes without total merging;
- the dominant lobe in front or above a supporting lobe;
- at least one negative-space window passing through the crown;
- the asymmetric crown center;
- actual branch geometry connecting trunk regions to crown masses.

The tree should read as a designed hierarchy: trunk, branch split, supported
lobes, and open spaces.

## TREE-E. Primary, secondary, and accent hierarchy

| hierarchy | parts | detail level | visual job |
| --- | --- | --- | --- |
| Primary | trunk/base, crown composition, indispensable major branch structure | 1 | establish the complete tree silhouette and stance |
| Secondary | branch splits, lobe differentiation, root flare, trunk profile refinement, one supporting branch | 2 | explain how the primary masses are organized |
| Accents | one or two small visible branches, fruit, nest, sparse leaf cluster, bark notch, hanging element | 3 | add character without filling the tree with small objects |

Major branches belong to detail 1 when removing them destroys the tree's
identity or closes the intended negative spaces. Physical size alone must not
push them to a later level.

Detail 3 has a strict budget. Repeated leaf accents are especially dangerous:
their cost and readability must be audited separately. The base benchmark does
not require hundreds of leaves, bark microgeometry, or a complete botanical
branch hierarchy.

## TREE-F. Crown hierarchy

The crown must be a deliberate composition of four to six broad masses. A
recommended default arrangement is:

```text
              dominant upper lobe
          medium left       medium right
                 supporting rear/side lobe
```

The exact positions may change with the authored profile, but the hierarchy
must remain stable:

- one dominant lobe establishes the primary crown read;
- two medium lobes create width and asymmetry;
- one or two supporting lobes provide depth or a side counterweight;
- no more than one small accent lobe is added at detail 3.

Each lobe needs an explicit reason:

- what part of the outer silhouette it changes;
- which canonical view must read it;
- which branch or trunk region supports it;
- which lobe it overlaps;
- which negative-space opening it preserves.

The lobes may be submeshes inside one crown Component. A lobe does not become a
Component merely because it is a separate mesh. It deserves identity only if
it has a meaningful attachment, replacement, effect target, or child contract.

The crown should use custom faceted lobe meshes or carefully composed local
profiles. A smooth sphere, an icosphere collection, and noise deformation are
not acceptable shortcuts.

## TREE-G. Branch hierarchy

Branching is a silhouette and composition system, not animal anatomy.

The default structure should be limited to:

```text
trunk
├ major branch left or forward
├ major branch right or rear
└ upper split toward the dominant crown lobe
```

The exact directional labels are less important than the visual roles. Major
branches must:

- support a crown lobe or explain its position;
- create a visible negative-space window;
- guide the eye through the silhouette;
- remain thick enough to read at benchmark render distance;
- stop before becoming a recursive twig generator.

Do not model:

```text
trunk -> shoulder -> elbow -> twig -> twig -> twig
```

If a branch is externally attachable or supports a nest, fruit, bird, lantern,
or another semantic child, it may deserve Component identity. Otherwise a
branch can remain a local submesh or a single branch-structure component.

## TREE-H. Intentional negative spaces

Negative space is a primary feature of this benchmark. At least four openings
must be designed before implementation:

| opening | responsible view | location | visual purpose |
| --- | --- | --- | --- |
| trunk split window | front and three-quarter | between the two lower major branches | proves that branches are real forms, not sockets hidden in foliage |
| under-canopy opening | side and three-quarter | above the trunk and below the lowest crown lobe | separates trunk flow from crown mass |
| crown-lobe window | front and three-quarter | between the dominant and one medium lobe | makes the crown hierarchical instead of solid |
| rear/side opening | side and three-quarter | between a rear lobe and a forward branch | gives depth and prevents a flat foliage wall |
| optional root gap | front or side | between two broad base flares | supports grounding without a realistic root system |

Each opening should be created by separation, placement, taper, and overlap
before any subtractive geometry is considered. The tree must not depend on a
boolean cutout to recover a silhouette that was not designed.

## TREE-I. Controlled asymmetry

The canonical shape is deterministic and intentionally unbalanced:

- the crown center is offset slightly from the trunk axis;
- the dominant lobe is higher and larger on one side;
- the opposite medium lobe is lower and smaller;
- branch heights and angles are unequal;
- the trunk lean counterbalances the dominant crown mass;
- a rear/side lobe exists mainly for three-quarter depth.

The asymmetry must be visually balanced. The tree should not look broken,
collapsed, or accidentally mirrored.

The first implementation must not use random displacement. A public
`asymmetry` parameter, if retained after authoring tests, controls named
deterministic decisions such as crown offset, branch angle difference, lobe
size ratio, and trunk lean. It is not a random amount.

## TREE-J. Component versus submesh plan

The initial plan favors semantic identity over mesh count:

| part | Component or submesh | reason |
| --- | --- | --- |
| tree root | Component | owns public parameters, surface mounting, and the complete subject |
| trunk | Component | primary mass, branch host, and meaningful replacement target |
| major branch host/branch | Component only when it owns a child contract; otherwise trunk submesh | a branch that supports nest, fruit, bird, or lantern has real graph identity |
| crown composition | one Component | primary visual mass and foliage host |
| crown lobes | submeshes inside crown by default | visual construction pieces with no independent contract |
| dominant lobe | submesh unless externally targetable | size and importance do not automatically require a node |
| roots/base flare | trunk submesh | grounding planes, not a replaceable root system |
| secondary branch split | trunk/branch submesh or one branch child | use a Component only if it is a meaningful `on:` target or subgraph host |
| fruit/nest/hanging element | optional Component/attachment | independent semantic accent and cross-plugin target |
| individual leaves/twigs | omit or local submesh | repeated pieces have high cost and weak identity in this benchmark |

The benchmark should prefer a small number of semantic nodes, but it should
not hide a branch that genuinely needs to accept external children inside an
opaque mesh. This is the exact Component/submesh tradeoff the third benchmark
is meant to test.

## TREE-K. Public parameters

Use a compact set of semantic parameters. The first design proposal is eight
parameters; all lobe sizes, socket positions, and local widths are derived.

| parameter | purpose | qualitative range | semantic role |
| --- | --- | --- | --- |
| `height` | total tree height | compact to tall, while preserving crown/trunk hierarchy | length |
| `trunk_width` | base trunk girth | slender but stable to chunky | girth |
| `trunk_taper` | upward narrowing | restrained to pronounced | ratio |
| `crown_width` | total crown span | narrow upright to broad canopy | girth |
| `crown_height` | vertical crown span | compressed to tall layered crown | length |
| `branch_spread` | reach and separation of major branches | close split to open canopy | ratio |
| `asymmetry` | deterministic crown/branch imbalance | near-balanced to clearly offset | ratio |
| `lean` | controlled trunk/crown directional offset | upright to gently windswept | ratio |

`root_flare` may be derived from `trunk_width` and `chunkiness` rather than
becoming a ninth public parameter. `crown_density` should not be a free leaf
count: the authored lobe hierarchy is the design, not a density slider.

Derived values should control:

- branch thickness and length;
- lobe size hierarchy;
- crown center offset;
- socket positions;
- base flare width;
- the amount of overlap between supporting forms.

## TREE-L. Capability and socket plan

Reuse general contracts only where their meaning is correct.

### Mounting behavior

- The tree accepts a general `surface` mount at its base when it needs to sit
  on a ground, platform, or scene surface.
- The trunk or semantic branch Components expose existing `branch_mount`
  sockets for a nest, fruit, bird, lantern, or similar attachment.
- A branch may expose a general `anchor` when the attachment is not inherently
  a perch or branch occupant.
- A crown may expose a general foliage/crown mount only if an existing contract
  has that meaning; do not invent a tree-specific capability for convenience.

The socket position and direction must be derived from the actual trunk or
branch profile. A socket that is mathematically centered but buried in the
visible surface is not a successful visual attachment.

Do not create `tree_branch_mount`, `tree_crown_mount`, or another
tree-specific capability. The existing nature contracts should be reused when
they are truthful; otherwise the mismatch should be documented instead of
hidden behind a new name.

### Cross-plugin compositions

The design should allow future compositions such as:

```text
tree -> branch -> nature:nest
tree -> branch -> nature:bird
tree -> crown -> fruit
tree -> branch -> lantern
```

These are contract tests for semantic attachment, not required detail-3
content in the base benchmark.

## TREE-M. Detail 1, 2, and 3

### Detail 1: complete tree

Detail 1 must already be a finished visual design. It includes:

- the tapered, slightly leaning trunk;
- the broad base or restrained flare needed for grounding;
- the crown composition with a dominant lobe and medium lobes;
- the indispensable major branch split;
- the primary negative-space windows;
- deterministic controlled asymmetry.

It must not be `trunk + blob placeholder`. If the major branches are necessary
to read the tree, they are detail 1 even when they are small relative to the
crown.

### Detail 2: secondary structure

Detail 2 may add:

- clearer branch splits and branch-to-lobe transitions;
- supporting crown lobes;
- root flare planes;
- a more deliberate trunk section profile;
- one secondary branch that improves a defined view.

Every addition must explain structure or preserve a designed negative space.
Detail 2 must not be a rescue pass for a weak detail 1.

### Detail 3: restrained character

Detail 3 may add only a few deliberately visible accents:

- one or two small but readable branch accents;
- one fruit, nest, or hanging element;
- a sparse leaf cluster only if it has a declared view responsibility;
- a bark notch or base accent if it changes a canonical read.

No hundreds of leaves, bark noise, twig recursion, or repeated decorative
objects. Every repeated accent needs cost and readability evidence.

## Trunk, roots, and branch geometry

### Trunk and base

The trunk is not a uniform cylinder. It should use a few intentional profile
stations with:

- a broad lower section;
- a restrained upward taper;
- a slight deterministic lean or offset;
- a small number of broad planar faces;
- an optional split transition that leads into the major branches.

The base flare is a few broad wedges or planes. It is not a realistic root
network. Its job is grounding, chunkiness, and a stable silhouette.

### Major branches

`grow()` is plausible when a branch is genuinely a tapered section progression
with a few authored stations. It is not automatically correct because a branch
is organic. The future author should compare:

- a local profile/grow branch with explicit taper;
- a manual branch plane when the silhouette or split is more important than
  ring topology;
- separate child branches on truthful sockets.

The first implementation should reveal the real friction instead of hiding it
behind a recursive helper.

### Crown

The crown is likely plugin-local manual geometry or a combination of low-side
profiles and planar lobe meshes. It should prioritize:

- outer contour;
- lobe hierarchy;
- broad facets;
- overlap and depth;
- internal openings.

Do not choose an icosphere or smooth primitive and then deform it with noise.

## TREE-N. Materials

Use a reduced palette that supports, but does not replace, the geometry:

- existing `wood` for the trunk when its shared meaning is correct;
- existing `leaf` for the main foliage when its shared meaning is correct;
- one darker foliage variant only if lobe separation cannot be read through
  planes and placement alone;
- one restrained accent material for fruit, nest, or a hanging element.

Do not add realistic bark textures, per-leaf colors, or material noise. Color
may clarify lobe hierarchy and depth ordering, but the black silhouette and
the planes must still carry the tree identity.

## TREE-O. Seed and variation policy

The benchmark has one canonical deterministic shape. The default seed must not
change:

- primary trunk/crown identity;
- number and hierarchy of major lobes;
- main branch responsibilities;
- required negative spaces;
- the shape language.

If controlled variations are explored later, a seed may vary only bounded
secondary decisions:

- small branch-angle changes;
- lobe offsets within declared windows;
- minor crown asymmetry;
- optional accent placement.

Every seeded variation must remain deterministic, visually balanced, and inside
the same silhouette contract. `every seed = random tree` is explicitly out of
scope.

## TREE-P. View responsibilities

| feature | front | side | three-quarter | why |
| --- | --- | --- | --- | --- |
| trunk/base flare | width, grounding, slight lean | taper and section flow | overlap with branch split | establishes the primary anchor |
| main split | visible window between branches | depth order of forward/rear arms | hierarchy and attachment | proves branching is geometry |
| dominant branch | silhouette direction | forward/back reach | supports dominant lobe | gives the crown a visual leader |
| crown composition | width and asymmetry | depth and vertical layering | overlap and hierarchy | replaces the single-sphere read |
| dominant lobe | upper contour | front/back depth | primary crown mass | establishes visual priority |
| medium lobes | side openings | depth support | overlap/counterweight | prevents a single dominant blob |
| crown-lobe window | readable opening | may narrow in side view | must remain visible | makes negative space intentional |
| under-canopy opening | lower mass separation | trunk/crown separation | depth window | keeps the model open |
| root flare | grounding silhouette | contact and lean | base depth | stabilizes chunky language |

## TREE-Q. Kernel expectations

No kernel primitive is implemented by this specification.

| candidate | preliminary status | reason |
| --- | --- | --- |
| `fork` | POSSIBLY USEFUL | the benchmark finally has real branch splits, but truthful child sockets may express them without a geometry primitive |
| `asymmetric_lobe` | POSSIBLY USEFUL | crown masses need controlled asymmetry, but the first lobe contract may be too tree-specific and should remain local initially |
| `leaf_cluster` | PROBABLY UNNECESSARY | the benchmark intentionally uses large crown masses; leaf-level representation is not required for the identity |
| `wedge` | POSSIBLY USEFUL | root flare and trunk transitions may repeat the car/fox wedge pattern, but tree evidence should be collected before promotion |
| `grow` | USE EXISTING TOOL SELECTIVELY | useful for honest tapered sections, not a style shortcut |
| `block` | USE EXISTING TOOL SELECTIVELY | useful for compact base planes or accents, not for the crown itself |

### Fork question

Do not confuse a geometry fork with a `CompositionGraph` parent that has two
children. The first test should attempt:

```text
parent trunk
├ branch A
└ branch B
```

with truthful sockets and separate branch Components or submeshes. A kernel
`fork` is justified only if several domains need the same geometric operation,
not because a tree contains a fork.

### Asymmetric lobe question

An `asymmetric_lobe` would need to serve trees, rocks, clouds, bushes, creature
tail masses, or terrain decoration. If its parameters describe a tree crown
rather than a general lobe profile, keep it plugin-local.

### Leaf cluster question

Do not assume foliage must be leaf-based. The benchmark deliberately tests
whether a few large faceted masses communicate the canopy better than leaves.
`leaf_cluster` remains unnecessary unless a later view audit proves that a
small repeated foliage accent has independent visual value.

## TREE-R. Expected failure modes

| failure | render symptom | correction direction |
| --- | --- | --- |
| green sphere on stick | one round crown, no branch read | design lobe hierarchy and visible branch connections |
| random noisy crown | many equal bumps, no dominant contour | reduce masses and author explicit hierarchy |
| too many equal lobes | crown has no primary read | keep one dominant, two medium, few supporting lobes |
| straight cylinder trunk | uniform vertical tube below foliage | use taper, lean, section changes, and base flare |
| hidden branches | sockets exist but no branch silhouette is visible | expose branch geometry and preserve windows into the crown |
| branch hierarchy too deep | tree becomes twig recursion | stop at major branch roles; omit small hierarchy |
| closed negative spaces | trunk/crown becomes one solid mass | separate placement before subtraction |
| artificial symmetry | left/right crown mirrors each other | apply deterministic height, angle, and lobe-size differences |
| broken asymmetry | tree looks collapsed or accidental | counterbalance dominant mass with trunk lean and supporting lobe |
| detail-3 leaf explosion | triangle count grows while read does not | remove repeated leaves; keep one declared accent |
| disconnected crown | lobes float above branches or trunk | derive attachments from the actual local surface/profile |
| too many Components | every lobe/twig becomes a graph node | reserve identity for contracts and semantic children |
| branch tubes | branches read as smooth pipes or cones | reduce sides, author stations, and use planar transitions |
| color-only identity | tree reads only with foliage material | rework silhouette, gaps, and planes before palette |

## TREE-S. Visual acceptance criteria

The future implementation is accepted only when:

### Detail 1

- it is already a complete stylized tree;
- trunk, crown, indispensable branch split, asymmetry, and primary gaps read;
- it does not resemble trunk plus sphere.

### Silhouette and views

- front, side, and three-quarter views have distinct readable responsibilities;
- side view contains crown depth and is not a flat foliage wall;
- three-quarter view shows branch hierarchy and lobe overlap;
- the important gaps remain visible in their declared views.

### Crown and branches

- the crown is a hierarchy of large faceted masses, not a sphere or noise field;
- major branches visibly support or guide crown masses;
- the trunk and branch widths taper without becoming cones;
- asymmetry is deterministic, intentional, and visually balanced.

### Polygon use

- most geometry serves trunk silhouette, branch hierarchy, crown contour,
  planes, or required negative space;
- detail 3 remains sparse;
- no leaf/twig count is used as a proxy for completeness.

### Style and architecture

- the model is stylized low-poly, not a decimated realistic tree;
- Component identity follows semantic contracts;
- surface-mounted attachments are tested for exposure, not only socket validity;
- metrics are reported as measurements and not converted into aesthetic scores;
- no core, kernel, quality-gate, or renderer changes are needed to express the
  design.

## Supporting visual audits

### Priority

**Highest priority:** trunk outer contour, major branch split, crown outer
contour, dominant/medium lobe hierarchy, and the four required negative-space
windows.

**Medium priority:** trunk planes, branch taper stations, root flare, lobe
internal planes, and the one supporting rear/side lobe.

**Low priority:** bark notches, sparse leaf clusters, fruit/nest accents, and
small hanging elements. They are optional until the primary read is stable.

No rigid triangle target is set before the first implementation. The benchmark
must report triangle cost by hierarchy and view rather than optimize a number
in isolation.

### Black silhouette thought test

If the whole tree is black, the following must remain readable:

- crown outline and its dominant side;
- trunk taper and base grounding;
- the main branch split;
- at least three open windows;
- crown depth through three-quarter overlap;
- the difference between the trunk and the crown hierarchy;
- the controlled imbalance of the canopy.

If a feature exists only because a material color reveals it, it is not yet a
primary feature. Color may reinforce the read after the silhouette works.

## TREE-T. Files changed

This specification phase creates exactly one file:

```text
app/plugins/tree_stylized/DESIGN.md
```

No `plugin.json`, component Python, materials, tests, benchmark script, core
change, kernel change, vehicle change, fox change, or existing-plugin change
belongs to this phase.
