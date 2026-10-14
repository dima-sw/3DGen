# Stylized Low-Poly Compact Car

This benchmark is a deliberately designed compact car, not a generic vehicle placeholder.

## Intent

The car should read as friendly, compact, toy-like, robust, and slightly sporty. The shape language is **chunky + tapered + rounded/faceted**: the vehicle is built from a few bold masses with planar sides, chamfer-like tapers, and faceted wheels.

It is not a realistic CAD car. It is a readable game/thumbnail asset that must remain recognizable from front, side, and three-quarter views at low detail.

## Exaggeration

- Wheels are oversized so the silhouette reads instantly as a playful compact car rather than a sedan shell.
- Track width is pushed outward so the stance feels stable and toy-like.
- Body width is broad and squat, with a mild front taper, so the front has character without becoming aerodynamic realism.
- The cabin is tall enough to be friendly and readable, but shorter than the body length so the car keeps a sporty wedge.
- Windshield and glass mass are large, because stylized cars need the cabin to read from distance.
- Headlights are oversized simple blocks, used as expression rather than realistic lamps.
- Wheel arches are represented by separate fender volumes instead of boolean cutouts, preserving low-poly clarity and avoiding a core primitive.

## Negative Space

The car intentionally leaves visible air between the ground, wheels, body, and fenders:

- `ground_clearance` raises the body above the wheel centerline.
- The body is narrower than the outer wheel track, leaving side separation.
- Four fender blocks sit above/around the wheels but do not replace the wheel wells with smooth boolean holes.
- The underbody is a dark narrow strip so the gap below the body remains visible.

This plugin does not use or request a core `arch_cutout`. The friction is real: wheel wells are hard to express with only additive primitives. The chosen local solution is to design the silhouette around gaps and separate fender masses, which is more honest for low-poly than subtractive smooth arches.

## Planar Design

The car is built from large deliberate planes:

- Body: bottom, side, tapered front face, rear face, upper hood-like plane.
- Cabin: trapezoid side planes, front windshield plane, roof plane, rear glass plane.
- Fenders: blocky separate masses above wheels.
- Front fascia: grille and headlights as simple planar blocks.
- Wheels: octagonal cylinders with flat facets.

No blob, capsule, SDF blend, texture trick, or smooth car body is used.

## Detail Levels

`detail_level=1` is the iconic silhouette:

- body
- cabin
- four oversized wheels

`detail_level=2` adds secondary forms:

- hood panel
- windshield panel
- fenders / wheel-arch treatment
- underbody strip
- front/rear differentiation through anchors and body taper

`detail_level=3` adds a few accents:

- headlights
- grille
- mirrors
- small rear roof spoiler
- simple hubcaps

The accents are deliberately few; each one supports readability.

## Parameters

The public parameters are semantic and compact:

- `length`
- `width`
- `height`
- `wheel_size`
- `cabin_ratio`
- `ground_clearance`
- `stance`
- `chunkiness`
- `front_taper`

Derived measurements such as body height, wheelbase, track width, tire thickness, fender size, and panel placement stay plugin-local.

## Components

The hierarchy is semantic rather than CAD-like:

- `car`
  - `body`
    - hood panel
    - fenders
    - underbody
    - headlights
    - grille
  - `cabin`
    - windshield
    - mirrors
    - rear roof spoiler
  - four wheels
    - hubcaps

The root also owns the four wheel sockets. Symmetry is implemented by the plugin through left/right sockets and repeated attachments, not by core changes.

## Capabilities

The plugin introduces:

- `vehicle`: the complete root car.
- `vehicle_mount`: internal structural mounts for car pieces.
- `wheel_mount`: wheel replacement socket with real future value.

It also reuses existing generic capabilities where appropriate:

- `anchor` on the front and rear body for small external accessories.
- `gear_mount` on the cabin roof for a roof accessory or cargo.

The first cross-plugin test should use an existing small accessory on a front `anchor`; this is meaningful as a tow hook or hood charm without inventing a new core concept.

## Materials

The palette is reduced:

- `car_body`
- `car_body_dark`
- `glass`
- `tire`
- `light_warm`
- `dark_accent`
- `metal` where a small accessory needs it

There is no texture, PBR complexity, or material-based detail substitution.

## Benchmark Expectations

The benchmark should produce PNGs and GLBs under `output/stylized_car_benchmark/` for detail levels 1, 2, and 3, using existing renderer/exporter paths only.

Black silhouettes are optional: they should be generated only if the renderer supports a material override without new renderer code. Otherwise the benchmark should report geometric silhouette metrics and note the omission.
