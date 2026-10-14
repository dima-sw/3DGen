# 3DGen Low Poly Design Bible v2

This document defines the visual language for future 3DGen plugins.

The central thesis is:

> Low poly does not mean a realistic model with fewer polygons. Low poly is an intentional stylization language.

3DGen should generate models that read clearly, feel designed, and use polygons as visual decisions. A good model is not a smooth object impoverished by decimation. It is a collection of deliberate planes, masses, proportions, colors, and negative spaces.

This is a design guide, not a new core API. Do not hardcode these rules into the core. Use them first as authoring rules for plugin authors.

## Current Architecture Observations

3DGen already has the right architectural separation for this direction:

- The core knows `Component`, `Piece`, sockets, capabilities, graphs, effects, styles, validation, and scenes.
- Plugins own visual decisions: profiles, meshes, proportions, sockets, materials, tags, and detail-level expansion.
- The geometry kernel favors procedural polygon construction through `grow()` and `block()`.
- The low-poly style profile already measures `faces_per_normal`, triangle budget, and flat materials.
- Validation mostly checks technical correctness: finite geometry, degenerate triangles, sockets, joint gaps, declared requirements, excessive interpenetration, style thresholds.
- Visual analysis already has domain-agnostic signals such as silhouette solidity, visible part share, largest part share, and triangle ranges.

This is good. The next step is not more realism. The next step is a stronger authoring language.

## Core Thesis

Low-poly design should be judged by readability, intentional planes, and silhouette strength.

Bad low poly:

- starts from a realistic anatomy or object and merely reduces polygon count;
- spends polygons uniformly;
- adds details because the real object has them;
- produces many tiny facets on forms that should be broad planes;
- technically uses flat shading but visually reads like a poorly sampled smooth surface.

Good low poly:

- starts from the iconic read of the object;
- exaggerates semantic features;
- reserves polygons for silhouette, articulation, and recognition;
- uses large, coherent planar regions;
- uses color and material groups to separate masses;
- keeps empty spaces visible.

## Silhouette First

The silhouette is the first read of a model. If the object is reduced to a black shape from the front, side, and three-quarter view, it should still be identifiable.

Plugin authors should allocate geometry in this order:

1. Polygons that change the outer profile.
2. Polygons that create readable negative space.
3. Polygons that support deformation or pose.
4. Polygons that create semantic recognition.
5. Internal surface detail.

If a feature does not affect any of those, it probably does not deserve geometry.

Examples:

- A fish tail and fins deserve polygons because they change the silhouette.
- A frog's raised eyes deserve geometry because they define the subject.
- A house roof deserves custom planes because it changes the iconic read.
- A humanoid wrist joint is structurally useful, but visually less important than head, shoulders, hands, and stance.
- A tree branch matters when it creates readable space between trunk and foliage; a barely visible twig does not.

## Shape Hierarchy

Every model should be designed as three levels:

### 1. Primary Masses

The largest readable volumes. These define what the object is.

### 2. Secondary Forms

Forms that explain structure or subtype. They should support the primary masses, not compete with them.

### 3. Accents

Small, characteristic details. Accents should be few, bold, and placed where they read.

Detail levels should map to this hierarchy:

- `detail 1`: iconic silhouette and primary masses.
- `detail 2`: secondary forms.
- `detail 3`: characteristic accents.

Detail level must not mean "more triangles everywhere".

Detail level describes semantic and visual importance, not geometric size. A
small feature belongs to detail 1 when removing it destroys recognition: the
fox ears are physically small but artistically primary. Conversely, a large
surface may remain a submesh or a detail-2 form when it does not need an
independent semantic identity.

Benchmark lesson from `vehicle_stylized`:

- Detail 1 should feel like a finished iconic object, not an unfinished version. The compact car remained readable with only body, cabin, and four wheels.
- Detail 2 is strongest when it explains structure: hood plane, windshield plane, underbody, and wheel-arch treatment changed how the car was understood without changing the subject.
- Detail 3 needs a stricter noise check. Headlights and grille added identity from the front; mirrors and hubcaps were much less important from several views.

Evidence from `fox_stylized` confirms the same hierarchy with a different
shape language: detail 1 is already a complete animal silhouette, detail 2
explains organic structure, and detail 3 adds face and material accents. The
hierarchy is shared; the forms assigned to it are domain-specific.

### Examples By Object

Humanoid:

- Primary masses: torso, head, arms, legs, stance.
- Secondary forms: pelvis/chest split, neck, hands, feet, shoulder line.
- Accents: nose, eyes, hair, fingers, equipment sockets.

Quadruped animal:

- Primary masses: body barrel, head, four legs, tail.
- Secondary forms: chest/hips, neck, paws/hooves, ears or horns.
- Accents: eyes, snout, mane, claws, spots or crest if they change read.

Car:

- Primary masses: body block, cabin, four wheels.
- Secondary forms: hood/trunk split, wheel arches, windshield plane.
- Accents: headlights, grille, mirrors, spoiler, door cuts if readable.

House:

- Primary masses: wall block, roof block.
- Secondary forms: roof pitch, door, window grouping, chimney.
- Accents: handle, trim, shutters, small roof cap.

Tree:

- Primary masses: trunk, crown.
- Secondary forms: large branches, crown lobes, roots if visible.
- Accents: nest, fruit, cut branch, bird perch.

Weapon:

- Primary masses: blade, handle.
- Secondary forms: guard, pommel, blade taper.
- Accents: gem, grip bands, notch, spike.

## Shape Language

A component should have a visual personality before it has domain detail.

The same shape language can apply across domains:

- `boxy`: stable, built, heavy, mechanical, toy-like.
- `rounded/faceted`: friendly, organic, soft but still planar.
- `triangular`: fast, sharp, directional, dangerous.
- `tapered`: elegant, aerodynamic, limb-like, natural.
- `chunky`: strong, cute, durable, stylized.
- `elongated`: fast, fragile, elegant, strange.
- `sharp`: aggressive, magical, metallic, predatory.

Examples:

- A boxy animal reads like a toy creature.
- A triangular car reads as fast even with few details.
- A chunky sword reads heroic or cartoonish.
- A tapered tree reads windswept or stylized.
- A rounded/faceted robot can read friendly even if made of metal.

The first two benchmarks make these words more actionable:

- **Tapered** means a cross-section shrinks along a meaningful axis, the
  silhouette converges, or the form has directional flow. It is not a synonym
  for "made with grow()".
- **Chunky** means broad primary masses, short or sturdy proportions, and a
  low-frequency silhouette. Large wheels or features can reinforce it.
- **Angular** means strong normal changes, wedge or triangular silhouettes, and
  deliberate direction changes rather than arbitrary triangulation.
- **Elongated** means the main axis and counter-lines are visibly extended, as
  in the car body or fox torso, muzzle, and tail. It must not collapse the
  negative spaces needed for recognition.

The vehicle is best described as chunky, faceted, and tapered. The fox is
angular, tapered, elongated, and faceted. These are geometric decisions, not
labels: authors should be able to name the profile, planes, axis, proportion,
and negative space that make each word visible.

For now, shape language should remain an authoring rule. Later, it may become:

- plugin metadata such as `shape_language: chunky`;
- style parameters for plugin-local proportions;
- style-stage effects for broad exaggeration;
- planner vocabulary hints.

Do not add API for this yet. First, prove the language in authored plugins.

## Component Identity Versus Submesh Construction

A feature deserves Component identity when one or more of these are true:

- it is externally replaceable;
- it is externally attachable;
- it is a meaningful target for effects;
- it owns a real capability or socket contract;
- it has an independent detail corridor;
- it is a semantically meaningful child of the model.

A feature should usually remain a submesh when it only creates planes,
triangulates a larger shape, has no external semantic identity, or cannot be
meaningfully replaced independently. The car supports Components for body,
cabin, wheels, fenders, lights, and other replaceable/attachable parts. The fox
supports Components for body, head, ears, legs, tail, and explicitly mounted
face accents, while cheek planes, paws, neck transitions, and inner
construction remain local geometry.

Node count is not a design goal. Give a feature graph identity when the graph
can make a useful promise about it; otherwise keep the promise inside the
owning Piece.

## Exaggeration

Principle:

> Readability is more important than physical accuracy.

Semantic features may be deliberately exaggerated when they improve recognition.

Good exaggeration:

- increases identity;
- improves silhouette;
- remains consistent with the model's shape language;
- is obvious from several views;
- does not become accidental realism.

Examples:

- Character: head, hands, shoulders, feet, hair mass.
- Car: wheels, cabin, grille, headlights, fenders.
- Animal: eyes, snout, ears, horns, tail, paws.
- House: roof, door, windows, chimney.
- Tree: trunk taper, crown lobes, branch gaps.
- Weapon: blade taper, guard width, handle proportions.

Avoid using anatomical correctness as the default target. A low-poly hand may be a block with a thumb. A low-poly eye may be a bold block or bead. A low-poly shoulder may be a strong silhouette wedge, not a correct deltoid.

## Planar Design

Flat shading is not enough. Planes must be designed.

A good low-poly mesh has deliberate changes of normal:

- broad side planes;
- clear bevel planes;
- readable angled surfaces;
- sharp transitions where the form turns;
- large triangles or quads where triangles are intentional.

A poor low-poly mesh has many normals because a smooth surface was sampled.

The current kernel supports this idea:

- `grow()` creates ring-based forms with predictable polygon counts.
- `block()` creates honest boxy forms.
- Manual meshes are used correctly where a specific planar object is needed, such as the house roof.

Where `grow()` is enough:

- limbs;
- trunks;
- fish bodies;
- tapered handles;
- organic masses with few stations.

Where custom planar design is better:

- roofs;
- vehicles;
- stylized torsos with deliberate chest/waist/hip planes;
- paws, hands, boots, helmets;
- mechanical panels;
- faceted rocks and crystals;
- broad leaf clusters.

`grow()` is a topology tool, not a style. It is a good fit when a ring-based
cross-section progression is the form: the car wheels, tapered animal limbs,
and some organic masses are useful examples. It is artistically wrong when it
forces a ring progression onto a car body, cabin, fox head, cheek planes, or a
tail that should read as a broad plume rather than a cone. A form can be
organic and still need manual planes; a form can be mechanical and still use
`grow()` when its section progression is honest.

Custom planar geometry is expected when visual planes are semantically
important. The car body/cabin and the fox head/muzzle/ears/tail use local
meshes because their exact planes carry identity. Manual geometry is not an
architecture failure. A kernel primitive should be promoted only when the
same geometric contract repeats across domains without losing the artistic
decision.

Do not increase `sides` because a form feels too rough. First ask whether the form needs a new plane, a stronger taper, a block, a bevel, or a silhouette change.

## Polygon Allocation

Rule:

> Spend polygons where they affect silhouette, deformation, or semantic recognition.

Spend polygons on:

- outside contour;
- holes and negative spaces;
- joints or parts that will rotate;
- sockets that must visually align;
- subject identifiers;
- broad planes that need to catch light differently.

Avoid:

- uniform tessellation;
- increasing `sides` without a reason;
- micro-faces that are invisible at normal view distance;
- geometric detail that does not change the read;
- dense meshes on flat surfaces;
- multiple small pieces that occupy the same visual role;
- detail 3 that only means "more components".

Polygon count should be budgeted by visual importance, not physical size alone. A small eye can deserve more visual priority than an anatomically accurate elbow if the eye identifies the creature.

Benchmark lesson from `vehicle_stylized`:

- A large primary mass may legitimately dominate surface area. In the compact car, the body is the largest part because that is how the subject reads; this is not automatically a flaw.
- Repeated accents are expensive. A cheap accent repeated four or six times can cost more than a primary mass, so repeated detail 3 pieces need their own audit.
- Triangle count, area share, and visual value are separate questions. Measure first; interpret in the domain and view where the feature is supposed to read.

### Accent cost and accent readability

These are two different audits:

- **Accent cost:** how many triangles, nodes, materials, and repeated instances
  the feature consumes relative to its visual importance.
- **Accent readability:** whether the feature is actually visible in the
  canonical views where it is meant to contribute.

The car showed the cost problem: repeated hubcaps and mirrors can consume a
surprising detail-3 budget while contributing little outside selected views.
The fox showed the readability problem: an eye can have a valid node, mesh,
material, parent, socket, and frame while being fully occluded by the head.
Every important accent needs both audits. These are authoring checks, not new
core metrics or universal quality gates.

## Flat Shading

Flat shading should reveal deliberate planes.

A mesh is suspicious when:

- every triangle has a different normal;
- the object reads like a noisy curved blob;
- large surfaces are broken into many arbitrary triangles;
- increasing triangle count makes the shape smoother but not clearer.

A mesh is strong when:

- adjacent triangles form larger planar regions;
- hard edges correspond to design decisions;
- normal changes support silhouette and material contrast;
- flat faces are big enough to read.

The current `faces_per_normal` metric is useful but incomplete. It catches "sampled smoothness", but it does not know whether the resulting design is attractive.

Benchmark lesson from `vehicle_stylized`:

- `faces_per_normal` was informative for the body and cabin because it confirmed broad planar regions rather than sampled curvature.
- It was less informative for simple boxes and tiny accents: a mediocre rectangular detail can score well because each quad is planar.
- A good faceted object may intentionally have many normals. The metric should keep catching accidental smooth sampling, not become an aesthetic score.

## Color And Material Design

Color should support shape readability.

Use:

- reduced palettes;
- strong contrast between primary masses;
- semantic material names shared across plugins;
- color to separate shape roles;
- flat color blocks instead of texture-like noise.

Avoid:

- turning the material system into a texture generator;
- many tiny color changes;
- realistic material complexity that fights the simple geometry;
- low-contrast masses that collapse into one silhouette.

Good examples:

- skin, hair, eye, mouth separate a character head.
- masonry, tile, wood separate house body, roof, openings.
- metal separates weapon blade and guard.
- leaf and wood separate tree crown and trunk.

Color is part of the model's readability. It should not hide weak geometry, but it can make hierarchy obvious.

## Negative Space

A stylized model needs readable empty spaces.

Important negative spaces:

- between arms and torso;
- between legs;
- under a car;
- between wheels and body;
- between tree trunk and branches;
- between roof and wall projections;
- around horns, ears, fins, tails, wings, and appendices.

Negative space is why a model reads as a figure rather than a block. A silhouette that fills its entire bounding box may be valid for a house, but it is usually bad for a creature, tree, vehicle, or character.

The existing visual metrics around silhouette solidity and visible parts are useful starting points. They should remain broad heuristics, not hard aesthetic law.

Benchmark lesson from `vehicle_stylized`:

- Negative space does not require boolean cutouts. It can be authored by separating masses: raised chassis, wheels outside the body width, and secondary forms that frame the gap instead of subtracting from a blob.
- Additive fenders can be a valid stylized wheel-arch solution when they clarify wheel/body separation. They become a workaround only if they hide the gap or pretend to be realistic cut geometry.

Across the car and fox, the stronger general rule is:

> Prefer relational separation before subtractive geometry when the desired
> negative space can be read from stance and placement.

This does not prohibit booleans. It says that separated wheels, legs, tail,
belly, chassis, and appendages should be tried before a subtractive operation.

## Attachment And Surface Readability

An attachment has three distinct correctness levels:

1. **Structural attachment:** the graph, parent, capability, socket, frame,
   and insert are valid.
2. **Surface attachment:** the child geometry actually reaches or intersects
   the intended local surface rather than merely matching a socket plane.
3. **Visual attachment/readability:** enough of the child remains exposed to
   communicate the feature in its intended views.

The fox eye fix is concrete evidence for the distinction. The eyes passed the
structural checks but were inside the effective head surface. A plugin-specific
exposure test then caught the failure and the accent was made surface-aware.
This rule must remain an authoring and plugin-test concern, not a universal
quality gate in the core.

For visible surface-mounted features, derive sockets from the actual local
surface or profile whenever practical instead of from a generic center offset.
The same reasoning applies to a light on a car, a window accessory, a gem on a
weapon, fruit on a tree, an armor plate, or a control button. A truthful frame
is necessary, but it is not sufficient evidence of visual placement.

## Detail Levels

Detail levels should express artistic hierarchy:

- `detail 1`: iconic silhouette.
- `detail 2`: secondary forms.
- `detail 3`: accents and characteristic features.

Examples:

- Humanoid detail 1: body, head, arms, legs, stance.
- Humanoid detail 2: torso split, neck, hands/feet.
- Humanoid detail 3: face accents, hair, fingers.
- House detail 1: wall block and roof.
- House detail 2: door and major openings.
- House detail 3: windows, handle, trim.
- Tree detail 1: trunk and crown.
- Tree detail 2: large branch sockets or crown lobes.
- Tree detail 3: nest, bird, fruit, small accents.

Audit of current behavior:

- `humanoid` mostly follows this: level 3 opens torso and limbs into readable subforms.
- `architecture` follows it well: roof at level 1, door at level 2, windows at level 3.
- `fish` uses tail at level 2; it would benefit from making fins more explicit as silhouette features.
- `nature` is functional: tree gets foliage at level 2, but crown shape could better express secondary forms.
- `humanoid_anatomical` has excellent structural levels, but artistically risks interpreting higher detail as more anatomy and more joints.

## Domain Studies

### Humanoid

Recognizable forms:

- head;
- torso;
- arms;
- legs;
- shoulder width;
- hands;
- feet;
- face/hair accents.

Design notes:

- The head and hands can be larger than realistic.
- Stance matters: arms and legs should separate from the torso enough to create negative space.
- The torso should be a designed mass, not a small anatomy lesson.

### Animal

Recognizable forms:

- body barrel;
- head;
- legs;
- tail;
- ears/horns;
- snout;
- eyes;
- paws/hooves/wings/fins depending on species.

Design notes:

- Species identity often lives in head silhouette, tail, ears, and limb stance.
- Exaggerate what makes the animal readable, not what is anatomically present.

### Vehicle

Recognizable forms:

- main body;
- cabin;
- wheels or tracks;
- hood/front;
- windshield;
- wheel arches;
- undercarriage negative space;
- lights/grille as accents.

Design notes:

- Vehicles are mostly planar design problems.
- Wheels and cabin usually deserve silhouette priority.
- Low-poly vehicles should not be rounded CAD shapes with few facets.

### Architecture

Recognizable forms:

- wall mass;
- roof mass;
- door;
- windows;
- chimney;
- porch/steps;
- roof pitch;
- facade rhythm.

Design notes:

- Big planes are good.
- A roof should be a designed mesh, not an accidental wedge.
- Openings should be bold enough to read as pattern and scale.

### Vegetation

Recognizable forms:

- trunk;
- crown;
- major branches;
- roots or base flare;
- crown lobes;
- fruit/nest/flowers as accents.

Design notes:

- Avoid "green sphere on stick".
- Create crown silhouette with lobes or asymmetric masses.
- Negative spaces between branches are more valuable than many tiny twigs.

### Weapon

Recognizable forms:

- blade;
- handle;
- guard;
- pommel;
- point;
- edge width;
- grip bands or gem as accent.

Design notes:

- Weapons should have strong directionality.
- Silhouette and taper matter more than bevel realism.
- The guard often does more for recognition than blade micro-detail.

## Audit Of Current Plugins

Classification terms:

- `GOOD STYLIZED LOW POLY`: clear silhouette, intentional planes, useful exaggeration.
- `FUNCTIONAL BUT GENERIC`: works technically and reads, but lacks strong visual authorship.
- `TRYING TO APPROXIMATE REALISM`: spends geometry toward anatomy/real-world correctness more than stylized read.
- `NEEDS REDESIGN`: weak silhouette, unclear hierarchy, or poor fit for the style.

### humanoid

Classification: `GOOD STYLIZED LOW POLY`, with some generic areas.

Why:

- Uses large readable masses.
- Hands and feet are simplified but recognizable.
- Head uses muzzle, eyes, nose, mouth, ears, hair as strong accents.
- Detail 3 generally maps to secondary forms and accents.

Risks:

- Some proportions are inherited from procedural ratios rather than an explicit design language.
- Limbs can feel tube-like if profiles are not pushed.

### humanoid_anatomical

Classification: `TRYING TO APPROXIMATE REALISM`, architecturally excellent but artistically risky.

Why:

- Demonstrates nested chains, compatibility, facial parts, distal sockets, and real pivot structure.
- However, it spends many components and polygons on anatomical segmentation.
- It can look like a more realistic humanoid simplified down, rather than a stylized figure designed up.

Compared with `humanoid`:

- `humanoid_anatomical` is structurally richer.
- `humanoid` is often more direct as stylized low-poly.
- More nodes and triangles do not automatically make the result artistically better.
- The useful lesson from `humanoid_anatomical` is architecture and articulation, not "future plugins should be more anatomical".

### creature

Classification: `GOOD STYLIZED LOW POLY`.

Why:

- Frog head is a strong example: wide low cranium, top eyes, wide snout.
- Dragon head uses long snout and horns: clear silhouette identifiers.
- Uses exaggeration by subject identity rather than realism.

Risks:

- It is mostly head-focused. Future animal bodies need equally strong silhouettes.

### fish

Classification: `GOOD STYLIZED LOW POLY`.

Why:

- Body is a designed fusiform mass.
- Odd side count avoids overly symmetrical flat sides.
- Tail and fins are planar silhouette features.
- The code explicitly treats fins as laminas, not tubes.

Risks:

- Fins could become more visible in generated default bodies.
- The plugin is a strong architectural compatibility case but not yet a complete fish design language.

### architecture

Classification: `GOOD STYLIZED LOW POLY`.

Why:

- House reads from primary masses: wall block plus roof.
- Roof is manually modeled to produce correct large planes.
- Door and windows map well to detail levels.

Risks:

- It is intentionally minimal. Future buildings need facade rhythm, roof variants, and larger shape-language differences.

### robot

Classification: `FUNCTIONAL BUT GENERIC`, and currently style-incompatible by design.

Why:

- It exists to prove style filtering, not to be a low-poly design example.
- Box head is readable but not a full low-poly robot language.

Risk:

- Do not treat it as a template for future robots until a low-poly robot style is authored.

### weapon

Classification: `GOOD STYLIZED LOW POLY`.

Why:

- Sword is three semantic masses: handle, guard, blade.
- Guard and blade taper are silhouette-defining.
- Pointed blade is economical and readable.

Risks:

- Future weapons need stronger shape-language variants: chunky heroic, sharp villainous, ceremonial, broken, heavy, etc.

### nature

Classification: `FUNCTIONAL BUT GENERIC`.

Why:

- Tree, foliage, nest, bird are readable and compatible.
- The nest as a concave bowl is a good low-poly idea.
- Bird uses body plus beak and sockets for wings.

Risks:

- Tree crown is still close to "faceted blob on trunk".
- Branches are mostly sockets rather than visible negative-space forms.
- Vegetation needs a stronger silhouette language.

### space

Classification: `FUNCTIONAL BUT GENERIC`, with a valid exception.

Why:

- Planet is intentionally faceted and declares `faceted`, so normal-per-face is legitimate.
- It is correct as a surface provider.

Risks:

- A planet is almost pure primary mass. Future space objects need craters, rings, asteroids, stations, and silhouettes that do more than "sphere".

## Quality Metrics

Current metrics that mostly measure technical correctness:

- finite coordinates;
- empty geometry;
- degenerate triangles;
- invalid sockets;
- declared requirements such as watertight, connected, manifold;
- bounds sanity;
- joint gap;
- excessive submersion/interpenetration;
- triangle budget.

Current metrics that partially measure style:

- `faces_per_normal`: catches sampled smoothness.
- `silhouette_fill`: catches overly full silhouettes.
- visual solidity/blobbiness: catches blob-like results.
- visible part share: catches invisible planned details.
- largest part share: catches one mass dominating the scene.
- aspect and triangle range: broad sanity checks.

Benchmark lesson from `vehicle_stylized`:

- `blobbiness`/visual solidity is a useful broad signal for whether wheels, chassis gaps, and cabin separation create an articulated outline. It is not inherently a vehicle-quality score.
- `largest part share` is a measurement, not a verdict. A vehicle, house, rock, or weapon may correctly have one dominant primary mass.
- `visible part share` catches planned details that vanish, but it does not know whether the remaining visible detail is artistically necessary.
- Metrics should be reported with a domain interpretation by the plugin author. The core should not convert these heuristics into universal aesthetic gates.

Proposed future domain-agnostic metrics, not implemented yet:

- `silhouette complexity`: number and distribution of contour changes from canonical views.
- `tiny triangle ratio`: share of triangles below a visual area threshold.
- `normal clustering`: whether normals form meaningful plane groups.
- `planar region distribution`: balance between broad planes and tiny facets.
- `polygon concentration`: whether triangles are spent on a few small details while primary forms stay weak.
- `symmetry deviation`: how much intended bilateral symmetry drifts.
- `part-size hierarchy`: whether primary masses dominate secondary forms and accents.
- `negative-space openness`: whether gaps remain visible between expected separated masses.
- `view stability`: whether the object remains recognizable from front, side, and three-quarter views.

Hard deterministic gates should remain about correctness:

- no invalid sockets;
- no non-finite geometry;
- no missing declared sockets;
- no broken parent-child attachments;
- no unexpected joint gaps;
- no severe degenerate geometry;
- style compatibility respected.

Artistic heuristics should remain advisory:

- silhouette complexity;
- blobbiness;
- normal clustering;
- polygon allocation;
- proportion exaggeration;
- color contrast;
- visual hierarchy.

Do not turn the core into an aesthetic judge. The core can report measurements. Plugin authors and style guides decide what the measurements mean.

### Interpretation after two benchmarks

| metric | what it measures | vehicle taught us | fox taught us | what it cannot tell us |
| --- | --- | --- | --- | --- |
| `silhouette_fill` | occupied pixels in a projected silhouette grid | front/side fill reflects body, cabin, wheels, and chassis gaps | front/side fill reflects ears, muzzle, legs, belly, and tail | whether a high or low fill is aesthetically correct |
| `blobbiness` / solidity | how much the silhouette fills its convex envelope | wheel and chassis separation lowers the envelope fill | legs, tail, ears, and muzzle create a less blob-like animal | whether a value is better across domains |
| `largest_part_share` | area contribution of the dominant part | a large car body is expected and can still be healthy | the torso/head can dominate without invalidating fox identity | whether dominance is an artistic flaw |
| `visible_parts` | parts above the generic area threshold | catches detail pieces that disappear at scale | tiny eyes can be readable but still fall below the threshold | visual readability of small accents or semantic importance |
| `faces_per_normal` | average planar reuse versus sampled curvature | useful for body/cabin and broad vehicle planes | useful for faceted animal masses, less decisive for tiny blocks | whether the planes are well designed or attractive |
| triangle budget | geometry cost | detail 3 reaches 412 triangles with many repeated accents | detail 3 reaches 476 triangles with face and tail accents | visual value, recognition, or quality by itself |

The two benchmark metrics are measurements, not aesthetic judgments. A
front-view silhouette fill and a side-view silhouette fill answer different
design questions. Report them with the intended view and feature, never as a
single universal score.

## Current Geometry Kernel Limits

The kernel is intentionally small and useful, but future low-poly authoring may want more primitives.

Current strengths:

- predictable topology;
- `grow()` for tapered procedural solids;
- `block()` for boxy masses;
- flat-friendly construction;
- simple profiles;
- easy socket alignment.

Current limits:

- `grow()` encourages tube-like thinking if overused.
- Ring profiles do not naturally create designed bevels or panel planes.
- Concave forms require manual composition or inverted meshes.
- Branching forms are not a first-class primitive.
- Vehicle-like panels, wheel arches, and cutouts are awkward.
- Crown/lobe vegetation forms need manual composition.
- Controlled asymmetry is possible but not ergonomic.
- There is no dedicated planar wedge, bevel block, arch, fork, claw, hoof, or wheel primitive.

Benchmark evidence from `vehicle_stylized`:

- The car needed plugin-local manual meshes for body and cabin because they were not generic tubes; they were arranged planar regions.
- The car needed simple local helpers for panel-like boxes whose base face sits on the socket. This points toward a possible `panel`, but one benchmark is not enough to add it to the kernel.
- The wheels were serviceable with `grow(..., sides=8)`. A dedicated `wheel` primitive is plausible, but the benchmark did not prove that the kernel needs it yet.
- Wheel wells were solved through separation and fenders, not `arch_cutout`. The benchmark exposed friction but did not justify a subtractive arch primitive.

Useful future primitives, not to add now:

- `wedge`: roof, snout, hood, crystal, stylized chest.
- `beveled_block`: boxy but readable mechanical/toy forms.
- `panel`: flat plate with thickness and sockets.
- `fork`: horns, antlers, branches, claws.
- `arch_cutout`: wheel wells, doors, windows.
- `wheel`: faceted cylinder with bold side planes.
- `leaf_cluster`: faceted foliage lobes.
- `hoof/paw block`: stylized animal feet.
- `crest/spike strip`: dragons, helmets, roofs, leaves.
- `asymmetric_lobe`: tree crowns, rocks, organic masses.

Do not add these until one or two benchmark models prove the need.

Primitive status after the first benchmark:

- `wedge`: potentially useful. The car body and cabin needed tapered planar forms, but the current evidence comes from one domain.
- `beveled_block`: benchmark did not justify it. The car used chunky planar masses, but not enough true bevel language to prove a generic primitive.
- `panel`: clearly useful as an authoring pattern, potentially useful as a primitive. Hood, windshield, underbody, grille, spoiler, and mirrors all wanted thin socket-aligned planar volumes.
- `wheel`: potentially useful. The faceted wheel is common enough to watch, but `grow()` handled this benchmark without much friction.
- `arch_cutout`: should remain plugin-local for now. The car demonstrated that additive separation can replace cutouts in a stylized design.

### Primitive evidence matrix after two domains

The matrix records evidence, not a roadmap. No primitive is implemented by
this document.

| primitive | vehicle evidence | fox evidence | other existing plugin evidence | domain independent? | status |
| --- | --- | --- | --- | --- | --- |
| `wedge` | body/cabin/hood transitions use converging planar forms | cheek, muzzle, and lower muzzle use explicit wedges | creature snouts use blocks or grow; architecture roof is a two-slope prism | likely, but contracts still differ | MULTI-DOMAIN CANDIDATE |
| `beveled_block` | chunky body details want planes, but no repeated bevel contract | no direct need; blocks and wedges are enough | robot/accessory blocks are boxy, not proven bevels | not proven | WATCH |
| `panel` | hood, windshield, grille, spoiler, mirrors, and fenders repeat the thin aligned pattern | little direct evidence | architecture door/window and accessory mask use thin blocks | pattern repeats, primitive not yet necessary | WATCH |
| `wheel` | four faceted wheels and hubcaps; `grow()` works | none | none | no | KEEP PLUGIN-LOCAL |
| `arch_cutout` | wheel wells were solved by spacing and additive fenders | none | architecture openings are additive components | not justified | NOT JUSTIFIED |
| `paw/hoof block` | none | paws are local submeshes inside legs | creature feet are not a proven shared contract | not proven | WATCH |
| `fork` | none | none | nature has branch concepts but no repeated fork geometry contract yet | not proven | NOT JUSTIFIED |
| `crest/spike strip` | spoiler is a local accent | ears and tail planes are not a strip | creature horns/accessory helmet crest are related but not identical | not proven | WATCH |
| `asymmetric_lobe` | none | tail plume is authored directly, not as a lobe primitive | nature crown masses are a future test, not current evidence | unknown | WATCH |
| `leaf_cluster` | none | none | nature foliage uses organic masses, but no cross-domain repetition | unknown | NOT JUSTIFIED |

### Wedge analysis

`wedge` is the first credible multi-domain kernel candidate, but it is not yet
ready to implement. The car needs converging hood/body/cabin transitions and
the fox needs muzzle, cheek, and head transitions. Existing architecture and
creature plugins show adjacent patterns, while the weapon blade is a pointed
grow form rather than proof of the same API.

A future conceptual API should stay minimal: a base profile, a tip profile,
an axis/length, and optional orientation. It must express a converging volume
without smuggling in vehicle or anatomy semantics. The next benchmark should
test whether the same wedge contract survives another domain before any kernel
change.

### Panel analysis

The car provides strong pattern evidence, but `block()` plus a truthful base
socket already expresses most panels without much boilerplate. Architecture
doors/windows and accessory masks are related thin blocks, not yet a common
surface-panel contract. Keep `panel` as a plugin-local authoring pattern and
watch it; do not add a primitive merely to rename a block.

## Authoring Rules

Before writing geometry:

1. Draw the front, side, and three-quarter silhouette in words.
2. Name the primary masses.
3. Name the secondary forms.
4. Name the accents.
5. Decide the shape language.
6. Decide what is exaggerated.
7. Decide which negative spaces must remain visible.
8. Decide what each detail level means artistically.
9. Allocate polygons by silhouette, deformation, and recognition.
10. Choose materials/colors to reinforce mass hierarchy.

While writing geometry:

- prefer broad planes over many small facets;
- prefer strong profiles over high side counts;
- use manual meshes when planes matter;
- use `block()` when the object wants boxiness;
- use `grow()` when taper or organic mass matters;
- distinguish semantic components from geometric subparts;
- keep sockets truthful and visible in the design;
- do not add detail that cannot be seen;
- do not hide weak geometry under color.

After writing geometry:

- inspect front, side, and three-quarter views;
- check silhouette and negative spaces;
- check whether detail 1 alone identifies the object;
- check whether detail 2 adds secondary forms;
- check whether detail 3 adds accents, not noise;
- check whether repeated accents consume more budget than their visual contribution earns;
- check whether every `Component` deserves graph identity, or whether it is only a submesh inside a `Piece`;
- run technical validation;
- review style metrics as heuristics, not verdicts.

### View-specific design audit

For every defining feature, state the views in which it must communicate:

- **front:** width, symmetry, ear/roof/cabin/headlight read, and front
  negative spaces;
- **side:** length, taper, stance, belly/chassis clearance, and directional
  profile;
- **three-quarter:** attachment, overlap, depth order, and the relationship
  between primary masses.

A feature is not successfully designed merely because it works in one
canonical view. It may be intentionally view-specific, but that intention
must be explicit. Useful exaggeration must survive the views in which the
feature is expected to carry identity; it does not need to be equally obvious
from every angle.

### Recommended visual iteration loop

This is an authoring workflow, not an autonomous visual judge:

1. Write the design specification and view responsibilities.
2. Build detail 1 and render front, side, and three-quarter views.
3. Fix silhouette, proportions, primary masses, and negative space.
4. Build detail 2 and render again.
5. Fix secondary structural read and attachments.
6. Build detail 3 and render again.
7. Audit accent cost, accent exposure, and view readability.
8. Run deterministic geometry tests and interpret metrics by domain.

Tests should encode proxies that support the design: negative-space bounds,
accent exposure, subtree/attachment presence, detail-level component presence,
silhouette measurements, and triangle breakdowns. They should not encode
"beautiful" as a boolean.

## Cross-Benchmark Evidence After Two Domains

### Comparison table

| property | `vehicle_stylized` | `fox_stylized` |
| --- | --- | --- |
| primary shape language | chunky, faceted, tapered | angular, tapered, elongated, faceted |
| dominant silhouette features | low body, cabin, four wheels, ground clearance | ears, pointed muzzle, tail plume, slender stance |
| primary masses | body, cabin, wheels | body, head, four legs, tail |
| secondary forms | hood, windshield, underbody, fenders, wheel framing | chest/hip shaping, muzzle refinement, paws, ear bases, tail taper |
| accents | headlights, grille, mirrors, spoiler, hubcaps | eyes, nose, inner ears, tail-tip color |
| negative-space strategy | chassis/ground and wheel/body separation through stance and fenders | belly, leg gaps, tail/body gap, ear notch through placement and separation |
| planar/manual geometry | sectioned body, cabin, base-aligned local panels | head/muzzle wedges, ears, tail plume, face profiles |
| `grow()` usage | wheels and hubcaps | cranial/organic masses and tapered limbs; tail only where station progression is honest |
| `block()` usage | panels, fenders, lights, grille, underbody | paws, accents, and compact planar subforms |
| component count at detail 3 | 24 nodes / 23 geometry pieces | 15 nodes / 14 geometry pieces |
| detail 3 triangles | 412 | 476 |
| main kernel friction | thin panels, wheel arches, cutout temptation | wedge/profile composition and surface-aware visible attachments |

The table separates domain-specific identity from repeated authoring lessons.
Both models are complete at detail 1, use separation to create negative space,
and reserve detail 3 for recognition. They differ in what carries that read:
mechanical mass and repeated wheels for the car; ears, muzzle, tail, and stance
for the fox.

The first benchmark was `vehicle_stylized`: a small stylized compact car.

What it proved:

- A non-humanoid benchmark is useful because it forces planar design, stance, repeated parts, and negative space.
- `detail 1` can be complete with only primary masses: body, cabin, and four wheels.
- `detail 2` can explain structure without realism: hood plane, windshield plane, fenders, and underbody.
- `detail 3` needs careful restraint. Headlights and grille clearly improved front identity; mirrors and hubcaps were more view-dependent.
- Wheel wells do not need a core cutout primitive to read. The benchmark used separation, stance, and additive fenders.
- The most important metrics were not verdicts. `largest_part_share`, `blobbiness`, and `visible_parts` all needed domain interpretation.

Numbers from the accepted benchmark:

- `detail 1`: 7 nodes, 6 pieces, 144 triangles.
- `detail 2`: 14 nodes, 13 pieces, 228 triangles.
- `detail 3`: 24 nodes, 23 pieces, 412 triangles.
- `detail 3` largest part share: 0.434, produced by the main body.
- `detail 3` blobbiness: 0.685, useful as an articulation signal, not as a car-quality score.

The main unresolved question is component granularity: some detail pieces deserve graph identity, while others may only be geometric subparts. Future benchmarks should continue to separate semantic structure from construction convenience.

The second benchmark was `fox_stylized`: a stylized angular, elongated,
tapered fox.

What it proved:

- Detail 1 can be a complete animal silhouette: body, head, ears, four legs,
  and tail already communicate the subject.
- Detail 2 can explain organic structure through chest/hip shaping, muzzle
  refinement, paws, and tail planes without becoming anatomical.
- Detail 3 accents need an exposure/readability audit in addition to graph and
  frame correctness. The eye fix exposed a real gap between structural and
  visual attachment.
- Ears are physically small but belong to detail 1 because they are identity
  anchors. Physical size is not a detail-level rule.
- The fox needed manual wedge and planar geometry alongside `grow()` and
  `block()`. Organic subject matter did not make a universal organic primitive
  appropriate.

Accepted benchmark numbers:

- `vehicle_stylized` detail 1/2/3: `7/14/24` nodes, `6/13/23` geometry
  pieces, `144/228/412` triangles.
- `fox_stylized` detail 1/2/3: `9/9/15` nodes, `8/8/14` geometry pieces,
  `256/412/476` triangles.
- Vehicle detail 3 largest part share: `0.434`; blobbiness: `0.685`.
- Fox detail 3 largest part share: about `0.391`; blobbiness: about `0.671`.

The current artifact reports 14 fox geometry pieces; the earlier planning note
that said "about 12 pieces" was an approximation and is not used as a design
rule.

### Shared, single-domain, and speculative rules

**Proven across domains:**

- detail levels describe semantic/visual importance, not polygon size;
- detail 1 must already be a finished visual design;
- negative space can often come from separation and stance before subtraction;
- manual/plugin-local planar geometry is valid when planes carry identity;
- `grow()` is a topology choice, not a style choice;
- metrics are measurements that need domain/view interpretation;
- graph identity should follow semantic contracts, not construction convenience;
- important accents need both cost and readability audits;
- defining features need front/side/three-quarter responsibilities.

**Proven mainly by one benchmark and now reusable as a test pattern:**

- fox: a valid structural attachment can still be fully embedded in the
  parent's real surface, so visible accents need a plugin-specific exposure
  test;
- vehicle: repeated accents can spend significant budget while helping only
  one view, so repeated detail needs an explicit cost audit.

**Still hypotheses:**

- `wedge` should become a kernel primitive;
- `panel` should become a kernel primitive;
- `fork`, `asymmetric_lobe`, and `leaf_cluster` are cross-domain needs;
- any universal aesthetic score would be useful;
- the next benchmark should validate a particular kernel API rather than the
  broader authoring language.

## BEFORE IMPLEMENTATION Checklist

Every future plugin author should answer these before writing geometry:

1. What is the fundamental silhouette and what should it communicate as a black
   shape from front, side, and three-quarter views?
2. What are the primary masses, secondary forms, and defining accents?
3. Is detail 1 already a complete visual design rather than a placeholder?
4. Which features are identity-critical even if physically small?
5. Which proportions, planes, and shape-language decisions are deliberately
   exaggerated?
6. Which negative spaces must remain readable, and can separation/stance make
   them before subtraction?
7. Which features are semantic Components and which are only submesh
   construction?
8. Is each surface-mounted feature actually exposed, not merely structurally
   attached? What plugin-specific proxy will test that?
9. Does each detail-3 accent earn its repeated polygon and material cost?
10. Which views must each defining feature read from: front, side, three-quarter,
    or a declared subset?
11. Am I using `grow()` because the form is ring-progressive, or merely because
    the subject is organic?
12. Which materials separate major masses without hiding weak geometry?
13. Which details are intentionally omitted?
14. Which checks are technical gates, and which metrics are only domain-specific
    artistic heuristics?

The author should record the answers before implementation and revisit them
after each detail-level render.

## Recommended Third Benchmark

The next benchmark should maximize new evidence, not minimize implementation
effort.

| candidate | new evidence | main risk | recommendation |
| --- | --- | --- | --- |
| Tree | branching, controlled asymmetry, crown lobes, hierarchical silhouette, organic negative spaces, non-anatomical form | foliage can collapse into a sphere-on-stick | strongest choice |
| Bird | wings as semantic planar components, beak, thin legs, repeated feather cost | may repeat fox's animal/head lessons before testing branching | useful later |
| Stylized house/building | facade rhythm, openings, roof/wedge/panel composition | architecture already has partial evidence | useful later |
| Robot | modularity, panels, articulation, semantic replacement | existing robot is intentionally generic and may test architecture more than art | useful after panel evidence |
| Rock/crystal | pure planes, asymmetry, silhouette without semantic details | weak test of graph identity and attachments | useful for planar language later |

Tree is the recommended third domain. It adds the largest missing set of
questions: branching, fork-like structure, controlled asymmetry, crown lobes,
major negative spaces, and organic silhouette without anatomy. It can provide
the first real evidence for `fork`, `asymmetric_lobe`, and `leaf_cluster`.
This is a recommendation only; no tree plugin is created by this document.
