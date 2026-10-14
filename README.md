# 3DGen — Universal Composition Engine

Describe an object in words, get a **low-poly 3D model made from real, reusable parts**, modify its composition plan, and export it.

```bash
python main.py                                       # desktop interface
python cli.py "a person with a frog's head"          # command line
python cli.py "a tree with a nest" --out tree.glb --png
python cli.py "a house" --detail 3                   # more parts, not more triangles
python cli.py "a house" --plan                       # the JSON plan written by the LLM
python cli.py "a house" --explain                    # why each part was chosen
python cli.py "a sword" --save "Good blade"          # save to the library
python cli.py --library                              # list the library
python cli.py --find "something with wings"          # semantic search
python cli.py --load <id>                            # reload a saved asset
python cli.py --providers                            # AI provider status
python -m pytest -q                                  # 895 tests
```

---

## How It Works

```text
USER PROMPT
    ↓
SESSION              the single entry point: UI, CLI, tests
    ↓
LLM PLANNER          one call, at most one correction
    ↓
COMPOSITION GRAPH    JSON: which parts, how they are attached, with which parameters
    ↓
REGISTRY             what is installed
    ↓
RESOLVER             what is compatible with what
    ↓
EFFECT PIPELINE      what changes, and in which order
    ↓
BUILDER              where every vertex ends up
    ↓
REAL 3D MODEL
```

The **core does not know what a house is**.

It does not know what a humanoid, fish, or planet is — and it should not.

The core only knows that a component **provides** certain capabilities and **accepts** others. That is enough to combine parts written by different people who never had to coordinate with each other.

The LLM does **not** generate geometry.

It generates a **plan**.

The planner selects and combines components that already exist in the registry. It cannot invent a vertex.

---

## What's Inside

**12 plugins, 44 components, 19 materials, 8 effects, 23 capabilities.**

| Plugin         | What it provides                                                                               |
| -------------- | ---------------------------------------------------------------------------------------------- |
| `humanoid`     | body, torso, pelvis, chest, neck, head, eyes, nose, mouth, ears, hair, arms, legs, hands, feet |
| `creature`     | frog head, dragon head, protruding eye                                                         |
| `fish`         | body, tail, fin                                                                                |
| `nature`       | tree, canopy, nest, bird                                                                       |
| `fantasy`      | wing, crystal                                                                                  |
| `architecture` | house, roof, door, window                                                                      |
| `space`        | planet                                                                                         |
| `weapon`       | sword                                                                                          |
| `accessories`  | face mask, helmet, visor, piercing                                                             |
| `robot`        | head — realistic style only, used to test rejection                                            |
| `primitives`   | block, tube, `low_poly` style, base materials                                                  |
| `fx`           | lanky, chunky, bend, perspective_exaggeration, rotate, align, offset, mirror                   |

None of these plugins is privileged.

Adding a new one does **not** require changing a single line in the core.

Copy a plugin directory, and the vocabulary changes automatically — including what the planner sees.

See **[PLUGIN-AUTHORS.md](PLUGIN-AUTHORS.md)**.

---

## The Ideas That Hold Everything Together

### The contract is what a part provides, not how it is built

A component is a function that returns **geometry and attachment points**.

It may use the polygon kernel, an imported mesh, or something that does not even exist yet.

The core does not care.

---

### `provides` and `mounts` are not the same thing

A child **provides** a `head_mount`.

A parent **accepts** it.

Reversing the two would mean that a torso *is* a head instead of providing a place where a head can be attached.

The distinction is fundamental to the composition system.

---

### The plan wins over declarations — without deleting them

A component declares what it is made of.

The composition plan can replace one of those parts.

For example, if a humanoid normally contains a standard head, the plan can replace it with a frog head.

The plan can also target a specific path:

```text
on: "head/nose"
```

This makes it possible to attach something to a part that was never explicitly named by the plan — **without recreating it and without duplicating it**.

---

### Effects never create components

Effects modify existing things.

Depending on the effect, they can change:

* parameters before building,
* vertices after building,
* or the final pose.

There are six effect stages, and their order is part of the contract.

The pipeline is deterministic:

```text
PLAN
 ↓
PARAMETER EFFECTS
 ↓
COMPONENT BUILD
 ↓
GEOMETRY EFFECTS
 ↓
POSE EFFECTS
 ↓
QUALITY CHECK
```

---

### Quality is deterministic

Quality is measured from the actual geometry that was generated.

The system checks numerical properties such as:

* planarity,
* triangle budget,
* silhouette,
* joints,
* intersections / interpenetration.

There is no language model judging whether a model "looks good".

Given the same inputs, the checks produce the same results.

La finestra permette di scegliere il provider AI primario e il failover
automatico. Il modello predefinito appartiene al registry backend del provider;
il failover usa
il modello di default del candidato successivo, non il model ID primario. La
variabili modello legacy tipo `HF_MODEL` o `OPENROUTER_MODEL` sono ignorate per
i provider remoti: restano leggibili solo per compatibilita'. La
catena mantiene l'ordine configurato per gli altri provider e normalizza
`OpenRouter` come ultimo remoto, subito prima di `Ollama`. Cloudflare Workers
AI richiede sia il token sia l'account ID; il nome legacy `cloudflare_id` e'
accettato per quest'ultimo. Un provider incompleto resta non configurato e non
impedisce l'avvio.

---

### Plugin descriptions are data

Plugin descriptions are passed to the planner as data.

They are reduced to a single quoted line without delimiters or role markers.

An installed plugin must never be able to inject instructions into your planner simply by writing something malicious in its description.

A plugin describes **what it provides**.

It does not get to tell the LLM what to do.

---

## Saving Your Work

A `.my3d` project contains the **composition plans**, not the meshes.

That means a project can be only a few kilobytes instead of several megabytes.

The model can then be regenerated:

* at a different detail level,
* with different parameters,
* with updated plugins,
* or with a different compatible component.

The project also stores the installed plugin versions.

This matters because if a project regenerates into a different model, the system must be able to explain **why**.

Example:

```python
from app.core.session import Options, Session

session = Session()

result = session.generate(
    "a house with a huge planet above it"
)

print(result.describe())

print("\n".join(result.explain()))

session.export("house.glb")
session.save_project("project.my3d")
```

---

## Offline Mode

The system works **without an AI API key**.

When no provider is configured, the same pipeline still runs.

A local planner selects components by matching the words in the request against the names, tags, and descriptions in the component vocabulary.

It is intentionally worse than a real language model.

And the result explicitly records:

```text
planner = "mock"
```

A silent fallback would be worse than an explicit limitation.

This makes it possible to distinguish between:

```text
real LLM planning
```

and:

```text
local vocabulary matching
```

without ambiguity.

---

## AI Providers

AI providers are interchangeable.

The core does not know or care which API is being used.

Provider configuration lives outside the core and can be supplied through `.env`.

See:

```text
.env.example
```

The architecture is designed so that adding or replacing a provider does not require changing the composition engine.

---

## Plugin Architecture

The plugin system is deliberately designed around **capabilities**, not categories.

The core does not contain logic such as:

```python
if object == "house":
    ...
elif object == "fish":
    ...
elif object == "human":
    ...
```

Instead, plugins expose components through contracts.

For example:

```text
Component
 ├── provides
 │    └── head_mount
 │
 ├── accepts
 │    └── body_mount
 │
 └── build(parameters)
      ├── geometry
      └── attachment points
```

This means a component can be reused in combinations its original author never anticipated.

A frog head does not need to know that it will eventually be attached to:

* a humanoid,
* a robot,
* a creature,
* or something created by another plugin.

Compatibility is resolved by the core.

See **[PLUGIN-AUTHORS.md](PLUGIN-AUTHORS.md)** for how to write a plugin without reading the core.

---

## Composition Is Data

The important part of a generated model is not the final mesh.

It is the **composition plan** that produced it.

Conceptually:

```json
{
  "component": "humanoid.body",
  "children": {
    "head": {
      "component": "creature.frog_head"
    }
  }
}
```

The plan describes:

* which components are used,
* where they are attached,
* which parameters they receive,
* which components replace others,
* and which effects are applied.

The builder simply executes that plan.

This separation makes the system:

* reproducible,
* editable,
* testable,
* serializable,
* explainable,
* and independent of any particular LLM.

---

## Explainability

Every generated asset can explain why it contains what it contains.

```bash
python cli.py "a house with a huge planet above it" --explain
```

The explanation is derived from the actual composition process.

It can describe things such as:

```text
house → architecture.house
roof → architecture.roof
planet → space.planet
planet placement → offset + alignment
```

The explanation is not an LLM-generated justification after the fact.

It comes from the decisions actually made by the planner, resolver, and effect pipeline.

---

## Detail Levels

Detail does **not** primarily mean "more triangles".

For example:

```bash
python cli.py "a house" --detail 1
python cli.py "a house" --detail 2
python cli.py "a house" --detail 3
```

Higher detail can mean **more meaningful components**:

```text
detail 1
└── house

detail 2
├── house
├── roof
└── door

detail 3
├── house
├── roof
├── door
├── windows
└── additional architectural parts
```

The goal is semantic complexity, not blindly increasing polygon count.

---

## Asset Library

Generated plans can be saved to the local asset library.

```bash
python cli.py "a sword" --save "Good blade"
```

List saved assets:

```bash
python cli.py --library
```

Search by meaning:

```bash
python cli.py --find "something with wings"
```

Reload an asset:

```bash
python cli.py --load <id>
```

Because the library stores composition plans rather than only meshes, saved assets remain editable and regeneratable.

---

## Command Line Interface

The CLI exposes the same `Session` entry point used by the desktop application.

This is intentional.

There is no separate generation engine for the CLI and another one for the UI.

Both use:

```text
Session
   ↓
Planner
   ↓
Composition Graph
   ↓
Registry
   ↓
Resolver
   ↓
Effects
   ↓
Builder
   ↓
Quality
```

This keeps behavior consistent between:

* the desktop application,
* command-line usage,
* automated tests,
* and future integrations.

---

## Desktop Interface

Run:

```bash
python main.py
```

The desktop interface is simply another client of the same session API.

It does not bypass the planner, registry, resolver, or builder.

This keeps the UI thin and the core reusable.

---

## Project Format

Projects use the `.my3d` format.

A project stores:

```text
composition plan
plugin identities
plugin versions
generation parameters
effect configuration
```

It does **not** need to store the generated mesh.

That makes projects lightweight and allows them to be regenerated later.

For example:

```text
house.my3d
    ↓
change detail
    ↓
change component
    ↓
update plugin
    ↓
regenerate
    ↓
new house.glb
```

---

## Determinism

The system is designed so that the same inputs produce reproducible results wherever possible.

The geometry builder does not ask an LLM to improvise.

The quality system does not ask an AI model to make a subjective decision.

The pipeline is based on explicit data:

```text
prompt
→ plan
→ components
→ parameters
→ effects
→ geometry
→ measurements
```

This makes failures debuggable.

If something goes wrong, the system can identify **which stage** produced the problem.

---

## Performance

A complete generation without network access runs in milliseconds on a normal machine.

Current benchmark:

| Step               |      Median |
| ------------------ | ----------: |
| Plugin loading     |       16 ms |
| Planner vocabulary |        3 ms |
| Local planner      |        1 ms |
| Resolver           |      0.2 ms |
| Effects            |      0.1 ms |
| Builder            |     3–10 ms |
| Quality checks     |      1–3 ms |
| **Total**          | **6–13 ms** |

Run the benchmark yourself:

```bash
python tools/benchmark.py
```

These numbers measure the local pipeline and do not include network latency or external LLM inference.

---

## Testing

The project currently has:

```text
895 tests
```

Run the complete suite:

```bash
python -m pytest -q
```

The test suite covers the core contracts, including:

* plugin discovery,
* component registration,
* capability resolution,
* composition plans,
* replacements,
* nested attachment paths,
* effect ordering,
* geometry generation,
* quality checks,
* serialization,
* project regeneration,
* provider behavior,
* CLI behavior,
* and offline planning.

The goal is not simply to test individual components.

It is to test the **contracts between them**.

---

## Architecture

At a high level:

```text
                         ┌──────────────────┐
                         │    User Prompt   │
                         └────────┬─────────┘
                                  │
                                  ▼
                         ┌──────────────────┐
                         │     Session      │
                         └────────┬─────────┘
                                  │
                                  ▼
                         ┌──────────────────┐
                         │   LLM Planner    │
                         └────────┬─────────┘
                                  │
                                  ▼
                         ┌──────────────────┐
                         │ Composition Graph│
                         └────────┬─────────┘
                                  │
                    ┌─────────────┴─────────────┐
                    ▼                           ▼
             ┌─────────────┐             ┌─────────────┐
             │   Registry  │             │  Components │
             └──────┬──────┘             └─────────────┘
                    │
                    ▼
             ┌─────────────┐
             │   Resolver  │
             └──────┬──────┘
                    │
                    ▼
             ┌─────────────┐
             │    Effects  │
             └──────┬──────┘
                    │
                    ▼
             ┌─────────────┐
             │   Builder   │
             └──────┬──────┘
                    │
                    ▼
             ┌─────────────┐
             │ Quality Gate│
             └──────┬──────┘
                    │
                    ▼
             ┌─────────────┐
             │  Real 3D    │
             │    Model    │
             └─────────────┘
```

The important boundary is between **semantic planning** and **geometry generation**.

The LLM operates on the former.

The deterministic engine operates on the latter.

---

## Documentation

* **[PLUGIN-AUTHORS.md](PLUGIN-AUTHORS.md)** — write a plugin without reading the core.
* **[ARCHITECTURE-CORE.md](ARCHITECTURE-CORE.md)** — why the core is designed this way, and what was removed to get here.
* **[ARCHITECTURE-PLUGIN.md](ARCHITECTURE-PLUGIN.md)** — the analysis that led to the plugin architecture.
* **[TODO.md](TODO.md)** — what is still missing.

---

## Design Philosophy

3DGen is deliberately **not** an AI mesh generator.

The AI does not need to learn how to draw a vertex.

It needs to understand what the user wants and translate that intent into a composition of existing, compatible parts.

The geometry engine then does the deterministic work.

That distinction gives the project a different architecture:

```text
Traditional AI 3D generation

prompt
  ↓
AI
  ↓
mesh
```

3DGen:

```text
prompt
  ↓
semantic plan
  ↓
existing components
  ↓
capability resolution
  ↓
deterministic composition
  ↓
real geometry
```

This makes the system modular rather than monolithic.

A new component does not require retraining a model.

A new plugin does not require changing the core.

A new effect does not require teaching the planner how to generate geometry.

And a saved project does not have to contain a giant mesh.

---

## In One Sentence

**3DGen turns natural-language descriptions into deterministic, explainable, low-poly 3D compositions by having an LLM choose from a universal registry of real components instead of generating geometry itself.**
