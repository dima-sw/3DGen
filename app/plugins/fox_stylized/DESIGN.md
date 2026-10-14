# Stylized Low-Poly Fox

Design specification for the future `fox_stylized` plugin.

This document is intentionally design-only. It does not define Python code,
plugin metadata, materials files, tests, or geometry. The implementation must
be authored after the silhouette and component contracts below have been
reviewed.

## FOX-A. Proposed plugin identity

### Name

`fox_stylized`

### Responsibility

Provide a complete, immediately readable stylized fox with a small number of
semantic masses, strong silhouette exaggeration, deliberate planar changes,
and three artistic detail levels.

The plugin should own fox-specific proportions, meshes, colors, sockets, and
detail expansion. It must not teach the core about foxes and must not turn the
composition graph into a mesh hierarchy editor.

The primary benchmark is a standing or slightly forward-leaning fox. It should
be recognizable without texture and without zoological anatomy.

## FOX-B. Shape language

The initial shape language is:

`angular + tapered + elongated`

with one deliberate counterweight: the torso and tail base remain broad enough
to read as designed masses instead of a chain of tubes.

- **Angular:** head, ears, chest, paws, and tail planes have intentional turns.
- **Tapered:** muzzle, legs, ears, and tail narrow toward meaningful ends.
- **Elongated:** the body and muzzle establish forward direction; the tail gives
  the side silhouette a long counter-line.
- **Faceted, not smooth:** use a few large planes and strong profile changes.
- **Graphic:** color blocks reinforce the masses but never carry recognition
  alone.

The result should feel like a designed low-poly animal, not a realistic fox
with fewer sides and not a body assembled from standard cylinders.

## FOX-C. Silhouette

### Side view

This is the most important canonical view. It must communicate, in this order:

1. A slender but not fragile torso with a clear belly line.
2. A forward-facing wedge head.
3. A pointed muzzle extending ahead of the chest.
4. Two large triangular ears rising above the head.
5. Four separated legs with visible space below the abdomen.
6. A large tail attached at the rear hip, with a broad base and a tapered,
   slightly lifted plume.

The tail should be a dominant secondary silhouette line, approximately as long
as the body or longer. It should not merge into the torso or hide completely
behind a hind leg in the default three-quarter pose.

The forelegs should sit slightly forward of the chest and the hind legs should
sit clearly behind the torso center. The spacing is more important than
anatomical joint accuracy.

### Front view

The front view must remain recognizably fox-like rather than becoming a generic
dog, cat, or wolf.

- The ears are tall, triangular, and visibly separated at their inner edges.
- The head is wider through the cheek and narrower toward the muzzle.
- The muzzle projects forward and down as a narrow wedge rather than a round
  snout.
- The chest is broad enough to anchor the head, while the legs remain slender.
- The eyes are not the main recognition mechanism; the ear and muzzle outline
  must work before eyes are added.

The default front pose should turn the muzzle very slightly toward the camera
without destroying the forward-facing read. The front silhouette must retain
two readable leg gaps and must not become one dark torso shape.

### Three-quarter view

The three-quarter view is the main design audit view. It must show:

- the wedge and taper of the muzzle;
- broad but faceted chest width;
- both ear triangles, with their bases visibly attached to the head;
- the tail attachment at the rear hip;
- front and rear leg separation;
- the belly gap and the tail-to-hind-leg gap.

The tail should remain readable from at least one front three-quarter and one
rear three-quarter view. It may overlap part of the body, but must not become an
unreadable tube behind it.

## FOX-D. Primary, secondary, and accents

| hierarchy | parts | detail level | visual job | allocation rule |
| --- | --- | --- | --- | --- |
| Primary | body/torso, head, four legs, tail | 1 | establish fox silhouette, stance, and empty spaces | spend geometry on contour, separation, and broad planes |
| Secondary | chest mass, hip shaping, neck wedge, muzzle refinement, paws, ear bases, tail taper | 2 | explain fox structure and improve the angular language | add only forms that change a canonical-view read |
| Accents | eyes, nose, inner ear planes, tail-tip color, optional small chest accent | 3 | reinforce identity after the silhouette already works | keep bold, sparse, and view-audited |

The ears are physically small compared with the torso but artistically primary:
they belong in detail 1 because removing them would damage species recognition.
The same rule applies to the tail. Physical size must not decide detail level.

The muzzle belongs to the head's semantic design, but its refinement can be a
detail 2 geometric subpart. It should not automatically become a graph node.

Repeated accents require an explicit budget audit. Two eyes and one nose are
enough for the default fox. Do not spend detail 3 on claws, individual toes,
whiskers, fur strands, or repeated fur tufts.

## FOX-E. Exaggerations

### Tail

The tail is one of the four identity anchors, alongside ears, muzzle, and
slender stance.

- Default length: roughly one body length, with a plausible range from slightly
  shorter than the body to about one and a half body lengths.
- Default volume: broad at the hip, full through the middle, visibly tapered at
  the tip.
- Default elevation: lifted enough to create a tail-to-hind-leg opening, not
  hanging as a vertical tube.
- Default construction: a faceted broad plume or two-to-four angular stations,
  not a smooth cone.

### Ears

Ears should be large, tall, and triangular. They need enough width at the base
to read as attached planes, while the tips remain clearly pointed. They should
not be tiny cones placed on a generic head.

### Muzzle

The muzzle is longer and more pointed than a generic dog-like block. Its top
line should taper toward the nose, while the cheek remains broad enough to
separate the wedge from the head.

### Paws

Paws may be slightly oversized relative to the legs so that the legs terminate
clearly in side and three-quarter views. They remain simple blocks or tapered
end planes, never toe collections.

### Legs

Legs should be slender enough to create negative space but broad enough to stay
visible at normal render distance. Four legs are a stance system, not an
anatomical study. Use a few planar changes rather than many joint segments.

### Torso

The torso is simplified and slightly elongated. Avoid sculpted muscles. A broad
chest transition and a restrained hip plane are sufficient to support the
silhouette.

## FOX-F. Negative spaces

The following spaces are intentional design features and must remain visible in
canonical renders:

- **Between the front legs:** an open vertical slit from below the chest toward
  the ground plane.
- **Between the rear legs:** a distinct opening below the hip, not a single rear
  block.
- **Under the abdomen:** a continuous belly gap that separates the torso from
  the ground and lets the legs read independently.
- **Between tail and hind leg/body:** a triangular or tapered opening in the
  default side and three-quarter poses.
- **Between the ears:** a visible notch above the head; the ear planes should
  not merge into one crown.
- **Between muzzle and chest:** in three-quarter view, the muzzle projection
  should remain separate from the chest contour.

These gaps should be authored by placement, taper, and separation first. Do not
make the torso a blob and then depend on boolean cutouts to recover the
silhouette.

## FOX-G. Planned components

The table separates semantic graph identity from construction subparts.

| part | component or submesh | why |
| --- | --- | --- |
| fox root | semantic Component | owns the complete subject, public parameters, and root contract |
| body/torso | semantic Component | primary mass; provides head, limb, and general core attachment locations |
| head | semantic Component | primary identity mass; a plausible replacement and face host |
| paired ears | one semantic Component with two geometric subparts | ears are identity-critical, but left/right ear replacement is not yet a proven general contract |
| front-left leg | semantic limb Component | contributes stance and may need a general limb replacement or pose attachment |
| front-right leg | semantic limb Component | same contract as the opposite foreleg, with side metadata |
| rear-left leg | semantic limb Component | contributes rear negative space and stance |
| rear-right leg | semantic limb Component | same contract as the opposite hind leg |
| tail | semantic Component | major identity mass and a likely future replacement target |
| chest and hip shaping | geometric submesh inside body | explains structure but does not need independent graph identity in the first benchmark |
| neck transition | geometric submesh between body and head | avoids a chain of tiny anatomical nodes |
| muzzle wedge | geometric submesh inside head | visually important, but a head-level construction detail until replacement proves useful |
| paws | geometric submesh inside each leg | small repeated end forms; separate components would spend graph complexity without a contract |
| ear inner planes | geometric submesh inside paired ears | material/plane accent, not a semantic part |
| eyes and nose | geometric submeshes or one face accent piece inside head | characteristic accents; keep them replaceable only through an existing general face contract |
| tail tip and chest accent | material regions or submeshes | color blocking, not independent objects |

The first implementation should target roughly ten semantic nodes at most,
including the root, body, head, ears, four legs, and tail. It must not expose
every cheek plane, joint, paw, or facial accent as a Component.

## FOX-H. Public parameters

Use nine public parameters. All other dimensions, socket positions, plane
widths, and accent sizes should be derived from them.

| parameter | default concept | qualitative range | semantic role | visible effect |
| --- | --- | --- | --- | --- |
| `body_length` | normalized 1.0 | compact to clearly elongated | main torso proportion | controls side-view direction and tail/leg placement |
| `torso_height` | about half of body length | low/slender to moderately deep | primary body mass | controls belly line, chest presence, and under-body space |
| `head_size` | about half body length in visual importance | small but readable to deliberately large | species recognition | changes head/body ratio and front-view presence |
| `leg_length` | long enough to open the belly gap | squat to slender/long | stance and negative space | controls visible space below torso and overall alertness |
| `tail_length` | about one body length | slightly short to very long | primary identity exaggeration | controls rear silhouette and tail-to-body ratio |
| `tail_volume` | broad plume, not tube | narrow plume to oversized plume | tail mass and silhouette weight | controls tail readability and the tail/body counter-line |
| `ear_size` | tall triangles clearly above head | moderate to oversized | species identifier | controls ear notch, front silhouette, and alert expression |
| `muzzle_length` | pointed forward wedge | short fox-like wedge to strongly elongated | species identifier | controls fox/dog distinction and forward direction |
| `chunkiness` | restrained, below torso dominance | slender to sturdy | global stylization bias | widens masses and legs without changing semantic part count |

Parameter derivations:

- leg spacing derives from `torso_height`, `chunkiness`, and the stance role;
  it must not close the front/rear gaps at the default values;
- ear base width derives from `head_size` and `ear_size`, while ear height is
  allowed to grow more strongly so the ears stay triangular rather than blunt;
- tail base derives from hip width and `tail_volume`; tail tip width narrows
  independently so a large tail does not become a cylinder;
- muzzle width and height derive from `head_size`, `muzzle_length`, and
  `chunkiness`, with taper increasing toward the nose;
- eye and nose size remain derived accents and are not public parameters in the
  first benchmark.

## FOX-I. Capability and socket plan

Reuse existing general contracts where their meaning is correct.

### Reuse candidates

- `core_mount`: body/root attachment if the existing core contract is needed.
- `head_mount`: body provides a head replacement location.
- `limb_mount`: body provides four limb locations, distinguished by side and
  front/rear tags where the current resolver supports them.
- `face_mount`: head can expose face attachment locations for general eyes,
  nose, or face accents, following the existing semantic contract.
- `gear_mount`: body/back location only for a genuinely general back accessory,
  not as a disguised fox-only tail contract.

### Deliberate deferrals

- Do not invent `fox_tail_mount`, `ear_mount`, or another fox-specific
  capability for the first benchmark.
- Tail replacement is artistically useful, but the project does not yet prove a
  general appendage contract distinct from a limb or accessory. Keep the tail as
  one semantic Component and record this as a future architecture question.
- Do not use `segment` merely to reproduce a tail as a chain. A segmented tail
  is a geometric strategy, not automatically a graph contract.

The socket layout must serve visible attachment truth: the head socket should
land inside the neck transition, limb sockets should align with the body mass,
and the tail socket should land inside the hip volume. Sockets are not excuses
to add hidden filler geometry.

## FOX-J. Detail levels

### Detail 1: complete fox

Detail 1 must be a finished silhouette, not a prototype.

- body/torso;
- head;
- large triangular ears;
- four separated legs;
- large tail;
- default forward stance and belly gap;
- primary color blocks only if needed to keep masses legible.

No eyes, nose, claws, toes, fur, or joint anatomy is required for recognition.
If the ears or tail are removed and the subject stops reading as a fox, they
were incorrectly assigned to a higher level.

### Detail 2: secondary structure

Detail 2 adds forms that explain the design without turning it anatomical:

- chest and hip shaping;
- a deliberate neck wedge;
- pointed muzzle refinement;
- simple paws;
- tail station/taper shaping;
- ear base planes or a stronger ear fold.

Every addition must be visible in at least one canonical view and must support
the primary shape language.

### Detail 3: characteristic accents

Detail 3 adds only:

- two bold eyes;
- one nose;
- inner ear planes;
- a light tail-tip material region;
- optionally one restrained chest accent.

Detail 3 must not add anatomical joints, fur strands, individual claws, toes,
whiskers, or many face pieces. Repeated accent cost and view visibility must be
audited before adding any optional element.

## FOX-K. Kernel expectations

The expected implementation should evaluate existing primitives before writing
local helpers.

| tool or candidate | status | expected use and reason |
| --- | --- | --- |
| `grow()` | likely needed | tapered legs, broad tail stations, or a simple organic core when rings preserve the intended planes |
| `block()` | likely needed | paws, compact chest/hip blocks, or deliberately boxy end forms |
| manual meshes | likely needed | head wedge, torso planes, and tail plume where the exact silhouette matters more than generic rings |
| plugin-local wedge | likely needed | muzzle, neck, and possibly chest transitions before a generic kernel primitive is justified |
| plugin-local planar ears | likely needed | two triangular faceted forms are a direct silhouette feature and should be authored explicitly |
| plugin-local tail helper | possibly useful | can manage broad tapered stations or asymmetric plume planes without becoming a core API |
| `wedge` kernel primitive | possibly useful | fox muzzle and neck would exercise the candidate, but one benchmark cannot yet prove its general API |
| `fork` kernel primitive | probably unnecessary | the first fox has no horns, antlers, or branching structure that must be generalized |
| `paw/hoof block` | possibly useful | repeated paws may expose a reusable low-poly animal pattern, but `block()` may be sufficient initially |
| `asymmetric_lobe` | possibly useful | tail plume asymmetry may benefit from it, but a plugin-local mesh is safer for the first proof |
| `panel` kernel primitive | probably unnecessary | useful for vehicles and plates, but it does not describe the fox's primary organic masses |

No candidate primitive should be added to the kernel during the fox benchmark.
The benchmark should record where the plugin-local helpers feel repetitive or
where existing `grow()`/`block()` semantics become misleading.

## FOX-L. Expected failure modes

| failure | how it appears in renders | likely correction |
| --- | --- | --- |
| dog-like | muzzle is broad or blunt; ears too short; tail is secondary | increase muzzle taper/length, ear height, and tail dominance |
| wolf-like | torso too large and heavy; head too broad; tail hangs low | slim torso, sharpen muzzle, lift and enlarge the plume |
| cat-like | body too compact; legs too vertical; tail thin; muzzle absent | elongate body, open stance, broaden tail base, reinforce muzzle wedge |
| tube legs | legs look like four cylinders with no planar intent | reduce ring thinking, use tapered profiles and a few explicit planes |
| cone tail | tail narrows uniformly from hip to tip and reads like a horn | use broad middle stations, faceted plume planes, and non-uniform taper |
| blob torso | body fills its bounding box and hides belly/leg gaps | separate legs, lift belly line, simplify torso planes, audit negative space |
| tiny unreadable ears | front view loses the ear notch; side view has no triangular peaks | enlarge ears and their base planes at detail 1 |
| muzzle too realistic | many small planes describe anatomy but the silhouette remains blunt | remove planes, exaggerate the single forward wedge |
| too many facial accents | eyes, nose, mouth, and small pieces compete with ears and muzzle | keep eyes/nose bold; move the rest to omission or material only |
| closed negative spaces | front legs, rear legs, or tail gap merge into dark shapes | adjust placement and separation before adding geometry |
| density spent on joints | detail 2/3 adds knees and hocks while silhouette is weak | return budget to ears, tail, muzzle, belly gap, and stance |

The diagnostic renders must include front, side, front three-quarter, and rear
three-quarter views. A failure is judged by what disappears in those views, not
by a single close-up face render.

## FOX-M. Visual acceptance criteria

The future implementation is accepted only when the following statements are
true in authored renders:

- The side view reads as a fox before eyes or nose are added.
- The front view retains a fox-like ear and muzzle silhouette rather than a
  generic dog, cat, or wolf read.
- The tail is a dominant, clearly attached silhouette mass and remains visible
  from useful three-quarter views.
- Ears are intentionally triangular, large enough for detail 1, and separated
  at their inner edges.
- The muzzle is an angular tapered wedge, not a round or realistic snout.
- The torso is slender enough to leave visible space below it and between legs.
- The four legs read as a stance system without looking like identical tubes.
- Detail 1 is a complete fox; detail 2 explains structure; detail 3 adds only
  characteristic accents.
- The model remains recognizable as a black silhouette in side and three-quarter
  views, with the front view still communicating ears and muzzle.
- Large planar changes are intentional and visible; increasing polygon count is
  not required to make the model feel finished.
- Color blocking supports body, head, tail, and accent hierarchy but cannot be
  the only reason the model reads as a fox.
- The model remains stylized low-poly and does not resemble a decimated
  realistic fox, a fur simulation, or a collection of cylinders.

These are descriptive acceptance criteria, not aesthetic scores. Technical
validation and style measurements remain useful diagnostics, but they must be
interpreted for this domain and must not become universal beauty gates.

## FOX-N. Files planned for this phase

Created in this design phase:

- `app/plugins/fox_stylized/DESIGN.md`

Not created by this specification:

- `plugin.json`;
- component Python files;
- material files;
- tests;
- geometry or rendered benchmark assets.

