"""Orchestrazione AI: prompt -> GenerationPlan, e prompt -> modifica del piano.

Pipeline:  prompt -> LLM -> JSON -> validazione Pydantic -> clamp sui parametri
del template -> GenerationPlan. Se un solo passaggio fallisce si ricade sul
planner a regole: l'utente ottiene comunque un modello.
"""
from __future__ import annotations

import copy
import json
import random
from typing import Any

from app.ai import offline
from app.ai.prompts import editor_system, planner_system, repair_system
from app.ai.variation import vary
from app.ai.provider import LLMError, LLMProvider, OfflineProvider, make_provider
from app.core.logging_setup import get
from app.core.style import clamp_density
from app.core.spec import EditPlan, GenerationPlan, MaterialSpec
from app.geometry.templates import TEMPLATES, load_all

log = get("ai.planner")


def sanitize_assembly(plan: GenerationPlan) -> list[str]:
    """Scarta cio' che l'LLM ha inventato: ricette, socket e parametri inesistenti.

    Non solleva: toglie le parti impossibili e riporta cosa ha tolto. Un
    assemblaggio parzialmente valido produce comunque un modello.
    """
    from app.geometry.recipe import get_recipe, load_catalog

    load_catalog()
    assembly = plan.assembly
    if assembly is None:
        return []

    removed: list[str] = []
    valid: list = []
    known: dict[str, object] = {}

    for part in assembly.parts:
        recipe = get_recipe(part.recipe)
        if recipe is None:
            removed.append("parte '%s': ricetta '%s' inesistente" % (part.id, part.recipe))
            continue
        part.params = {k: v for k, v in part.params.items() if k in recipe.params}
        known[part.id] = recipe.build(part.params)
        valid.append(part)

    # secondo giro: gli attacchi si possono controllare solo a parti note
    checked: list = []
    ids = {p.id for p in valid}
    for part in valid:
        if part.attach is not None:
            if part.attach.parent not in ids:
                removed.append("parte '%s': padre '%s' inesistente"
                               % (part.id, part.attach.parent))
                continue
            parent_part = known.get(part.attach.parent)
            if parent_part is not None and parent_part.socket(part.attach.socket) is None:
                removed.append("parte '%s': socket '%s' assente su '%s'"
                               % (part.id, part.attach.socket, part.attach.parent))
                continue
        checked.append(part)

    assembly.parts = checked
    if assembly.root not in {p.id for p in checked} and checked:
        assembly.root = checked[0].id
    return removed


def _sanitize_plan(plan: GenerationPlan) -> GenerationPlan:
    """Forza il piano dentro i limiti dichiarati dal template."""
    load_all()
    if plan.strategy == "assembly" and plan.assembly is not None and plan.assembly.parts:
        # un piano compositivo non ha template: non va ricondotto a uno
        if not plan.seed:
            plan.seed = random.randint(1, 10**6)
        return plan
    tmpl = TEMPLATES.get(plan.template)
    if tmpl is None:
        log.warning("template '%s' inesistente, ripiego su 'primitive'", plan.template)
        plan.template = "primitive"
        tmpl = TEMPLATES["primitive"]
    plan.params = tmpl.sanitize(plan.params)
    known = set(tmpl.materials)
    plan.materials = [m for m in plan.materials if m.name in known or m.name == "default"]
    if not plan.seed:
        plan.seed = random.randint(1, 10**6)
    return plan


def generate_plan(prompt: str, provider: LLMProvider | None = None,
                  seed: int | None = None) -> tuple[GenerationPlan, str]:
    """Restituisce (piano, messaggio per l'utente).

    Ogni chiamata produce una variante diversa: al piano viene applicato un
    disturbo controllato (app/ai/variation.py) che non tocca mai cio' che
    l'utente ha chiesto esplicitamente. Passando `seed` si riottiene
    esattamente la stessa variante.
    """
    provider = provider or make_provider()
    nonce = seed if seed is not None else random.randrange(1, 10**9)

    if isinstance(provider, OfflineProvider):
        plan = vary(_sanitize_plan(offline.plan(prompt)), nonce)
        return plan, "Piano creato in locale (variante %d)." % plan.seed

    # Il nonce serve anche all'LLM: con temperatura alta produce piani diversi
    # a parita' di richiesta, invece di ripetere sempre la stessa risposta.
    user = "%s\n\n[variante #%d: se la richiesta lascia liberta', fai una scelta " \
           "diversa dalle precedenti]" % (prompt, nonce)
    try:
        raw = provider.complete_json(planner_system(), user, temperature=0.7)
        raw["prompt"] = prompt
        plan = GenerationPlan.model_validate(raw)
        if plan.assembly is not None and plan.assembly.parts:
            plan.strategy = "assembly"
            plan.template = plan.template or "freeform"
            scartate = sanitize_assembly(plan)
            for motivo in scartate:
                log.warning("assemblaggio dell'LLM ripulito: %s", motivo)
            if not plan.assembly.parts:
                raise LLMError("assemblaggio senza parti valide")
        # cio' che l'LLM ha deciso esplicitamente e' intoccabile per le varianti
        plan.locked = [k for k in (raw.get("params") or {})] + \
                      [m.name for m in plan.materials]
        plan = vary(_sanitize_plan(plan), nonce)
        plan, _, notes = check_and_repair(plan, provider)
        if notes:
            plan.notes = (plan.notes + " | " + "; ".join(notes)).strip(" |")
        used = getattr(provider, "last_used", "") or provider.name
        log.info("piano da %s: template=%s densita=%.2f seed=%d",
                 used, plan.template, plan.density, plan.seed)
        return plan, "Piano creato da %s: %s" % (used, plan.notes or plan.object_type)
    except (LLMError, ValueError, KeyError, TypeError) as exc:
        log.warning("planner LLM fallito (%s), uso le regole locali", exc)
        plan = vary(_sanitize_plan(offline.plan(prompt)), nonce)
        return plan, "LLM non disponibile (%s). Piano creato in locale." % exc


def _assembly_from_archetype(plan: GenerationPlan) -> GenerationPlan | None:
    """Ricostruisce l'assemblaggio dall'archetipo, che legge tutta la richiesta."""
    from app.ai import creature

    text = plan.prompt or plan.object_type
    if not text or not creature.looks_like_creature(creature.normalize(text)):
        return None
    try:
        assembly, materials = creature.build_assembly(creature.parse_creature(text))
    except Exception as exc:
        log.warning("archetipo non costruito: %s", exc)
        return None
    rebuilt = plan.model_copy(deep=True)
    rebuilt.assembly = assembly
    rebuilt.strategy = "assembly"
    if not rebuilt.materials:
        rebuilt.materials = materials
    return rebuilt


def check_and_repair(plan: GenerationPlan, provider: LLMProvider | None = None
                     ) -> tuple[GenerationPlan, list, list[str]]:
    """Valida, ripara da sola, e solo se resta un errore chiede aiuto all'LLM.

    Regola 10: il costo AI di una generazione e' costante. Qui la chiamata in
    piu' e' **una**, e solo quando la riparazione deterministica non basta.
    """
    from app.build.validation import errors, validate_and_repair

    if plan.assembly is None or not plan.assembly.parts:
        return plan, [], []

    repaired, _, issues, applied = validate_and_repair(plan.assembly, prompt=plan.prompt)
    plan.assembly = repaired
    notes = list(applied)

    # Se manca cio' che l'utente ha chiesto, il problema non e' geometrico: il
    # piano ha ignorato la richiesta. L'archetipo la legge per intero.
    if any(i.code == "MISSING_REQUESTED_FEATURE" for i in issues):
        rebuilt = _assembly_from_archetype(plan)
        if rebuilt is not None:
            plan = rebuilt
            notes.append("richiesta non rispettata dal piano: ricostruito dall'archetipo")
            repaired, _, issues, applied = validate_and_repair(plan.assembly, prompt=plan.prompt)
            plan.assembly = repaired
            notes += applied

    remaining = errors(issues)
    if not remaining or provider is None or isinstance(provider, OfflineProvider):
        return plan, issues, notes

    try:
        raw = provider.complete_json(
            repair_system(json.dumps(plan.model_dump(), ensure_ascii=False)[:6000], remaining),
            "Correggi il piano.", temperature=0.2)
        raw["prompt"] = plan.prompt
        corrected = GenerationPlan.model_validate(raw)
        if corrected.assembly is None or not corrected.assembly.parts:
            raise LLMError("la correzione non contiene un assemblaggio")
        corrected.strategy = "assembly"
        sanitize_assembly(corrected)
        _, _, after, _ = validate_and_repair(corrected.assembly)
        if len(errors(after)) < len(remaining):
            notes.append("piano corretto dall'LLM (%d problemi -> %d)"
                         % (len(remaining), len(errors(after))))
            log.info("correzione accettata: %s", notes[-1])
            return corrected, after, notes
        notes.append("correzione dell'LLM scartata: non migliorava")
    except (LLMError, ValueError, KeyError, TypeError) as exc:
        log.warning("correzione non riuscita (%s): tengo il piano riparato", exc)
        notes.append("correzione non riuscita: %s" % exc)

    return plan, issues, notes


def revariate(plan: GenerationPlan, seed: int | None = None) -> tuple[GenerationPlan, str]:
    """Nuova variante dello stesso piano, senza interpellare l'LLM: istantanea."""
    fresh = vary(copy.deepcopy(plan), seed)
    return fresh, "Nuova variante (seed %d)." % fresh.seed


# --------------------------------------------------------------------------- #
# Editing
# --------------------------------------------------------------------------- #
def apply_edit(plan: GenerationPlan, edits: EditPlan) -> GenerationPlan:
    """Applica operazioni strutturate. Nessun codice viene mai eseguito."""
    load_all()
    new = copy.deepcopy(plan)
    tmpl = TEMPLATES.get(new.template)
    touched: set[str] = set()

    for op in edits.ops:
        if op.op == "set_template":
            target = str(op.value)
            if target in TEMPLATES:
                new.template = target
                new.params = {}
                new.materials = []
                tmpl = TEMPLATES[target]
        elif op.op == "set_density":
            try:
                new.density = clamp_density(float(op.value))
            except (TypeError, ValueError):
                log.info("densita' non numerica ignorata: %r", op.value)
        elif op.op == "set_param" and tmpl and op.path in tmpl.params:
            new.params[op.path] = tmpl.params[op.path].coerce(op.value)
            touched.add(op.path)
        elif op.op == "scale_param" and tmpl and op.path in tmpl.params:
            current = new.params.get(op.path, tmpl.params[op.path].default)
            if isinstance(current, (int, float)) and not isinstance(current, bool):
                new.params[op.path] = tmpl.params[op.path].coerce(current * float(op.factor or 1.0))
                touched.add(op.path)
        elif op.op == "set_material":
            payload: dict[str, Any] = op.value if isinstance(op.value, dict) else {}
            name = op.target or (tmpl.primary_material if tmpl else "default")
            if not name:
                continue
            existing = next((m for m in new.materials if m.name == name), None)
            base = existing or (tmpl.materials.get(name) if tmpl else None) or MaterialSpec(name=name)
            merged = base.model_dump()
            merged.update({k: v for k, v in payload.items() if k in merged})
            merged["name"] = name
            updated = MaterialSpec.model_validate(merged)
            new.materials = [m for m in new.materials if m.name != name] + [updated]
            touched.add(name)

    if tmpl:
        new.params = tmpl.sanitize(new.params)
    new.locked = sorted(set(new.locked) | touched)
    return new


def edit_plan(prompt: str, plan: GenerationPlan,
              provider: LLMProvider | None = None) -> tuple[GenerationPlan, str]:
    provider = provider or make_provider()
    load_all()
    tmpl = TEMPLATES.get(plan.template)

    if isinstance(provider, OfflineProvider) or tmpl is None:
        edits = offline.edit(prompt, plan)
        return apply_edit(plan, edits), edits.summary or "Nessuna modifica applicata."

    schema = "\n".join("- %s (%s)" % (k, p.desc or "") for k, p in tmpl.params.items())
    system = editor_system(plan.template, plan.density, plan.params,
                           list(tmpl.materials), schema)
    try:
        raw = provider.complete_json(system, prompt, temperature=0.15)
        edits = EditPlan.model_validate(raw)
        if not edits.ops:
            raise LLMError("nessuna operazione restituita")
        return apply_edit(plan, edits), edits.summary or "Modifica applicata."
    except (LLMError, ValueError, KeyError, TypeError) as exc:
        log.warning("editor LLM fallito (%s), uso le regole locali", exc)
        edits = offline.edit(prompt, plan)
        return apply_edit(plan, edits), (edits.summary or "Nessuna modifica") + " (locale)"
