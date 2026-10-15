"""Una configurazione utile, salvata senza duplicare la geometria.

Il caso e' quello del Component Lab: si apre `creature:eye`, si muovono tre
slider, e quello che si vede e' un occhio di drago. La cosa sbagliata da fare
e' esportare una mesh nuova — sarebbe la stessa geometria, due volte su disco,
con due identita' da mantenere. La cosa giusta e' salvare **cio' che si e'
deciso**: la base, i parametri, i trait e gli effetti.

    {"base": "creature:eye", "name": "dragon_eye",
     "params": {"width": 1.4, "height": 0.7},
     "traits": [{"trait": "std:part_scale", "value": 1.2}],
     "effects": [{"type": "fx:bend", "amount": 0.3, "scope": "part"}]}

E' il formato minimo coerente con il sistema, e non e' un formato nuovo: ogni
campo e' un pezzo di piano. `to_plan()` lo rende un piano che `Session.build`
accetta, e `to_attachment()` lo rende un `Attachment` che un composite puo'
contenere.

## Il limite, dichiarato

Un `Attachment` porta `params`, e non porta trait ne' effetti: sono cose del
**piano**, non della parentela fra due componenti. Quindi una variant che
dichiara solo parametri si incorpora in un composite senza perdere niente, e
una che dichiara trait o effetti no — `embeddable` dice quale delle due si ha
davanti, e `AuthoringService.validate()` lo segnala invece di perderlo in
silenzio. La via d'uscita, se servira', e' un parametro `effect`-backed sul
componente base: un numero che chiede una piega e' un parametro, e i parametri
viaggiano.

## Il ponte verso V7

    yellow candidate  ->  l'utente muove i parametri  ->  Save Variant  ->  green

`coverage` parte da `CANDIDATE` e `promote()` la porta a `VALIDATED`. Nessun
provider AI decide niente qui: V6 rappresenta lo stato, V7 lo decidera'.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.authoring import errors
from app.authoring.errors import AuthoringError
from app.authoring.model import CANDIDATE, COVERAGE, VALIDATED, check_name

FORMAT_VERSION = 1


@dataclass
class VariantRecipe:
    """Base piu' decisioni. Mai una mesh, mai un percorso di file."""

    base: str
    name: str
    params: dict = field(default_factory=dict)
    traits: tuple[dict, ...] = ()
    effects: tuple[dict, ...] = ()
    description: str = ""
    coverage: str = CANDIDATE
    detail_level: int = 2
    style: str = "low_poly"

    def __post_init__(self) -> None:
        self.name = check_name(self.name, "nome della variant")
        if not str(self.base).strip():
            raise AuthoringError(errors.PROJECT_INVALID,
                                 "una variant deve dichiarare la propria base")
        self.traits = tuple(dict(t) for t in self.traits)
        self.effects = tuple(dict(e) for e in self.effects)
        self.params = dict(self.params)
        if self.coverage not in COVERAGE:
            self.coverage = CANDIDATE

    # ------------------------------------------------------------- lettura #
    @property
    def embeddable(self) -> bool:
        """Si puo' incorporare in un composite senza perdere niente?

        Vero quando dichiara soltanto parametri: un `Attachment` li porta.
        Falso con trait o effetti, che sono cose del piano.
        """
        return not self.traits and not self.effects

    def promote(self) -> "VariantRecipe":
        """Da candidato a validato. E' l'utente che lo decide, non un modello."""
        self.coverage = VALIDATED
        return self

    # ---------------------------------------------------------- traduzioni #
    def to_plan(self, *, node_id: str = "subject", style: str = "",
                detail_level: int | None = None, seed: int = 0) -> dict:
        """Un piano di composizione normale. Nessuna chiave nuova."""
        plan: dict[str, Any] = {
            "version": "1.3", "style": style or self.style,
            "detail_level": int(detail_level if detail_level is not None
                                else self.detail_level),
            "seed": int(seed),
            "root": {"id": node_id, "ref": self.base, "params": dict(self.params)},
        }
        if self.effects:
            plan["root"]["effects"] = [dict(e) for e in self.effects]
        if self.traits:
            plan["traits"] = [dict(t) for t in self.traits]
        return plan

    def to_attachment(self, child_id: str = "", *, level: int = 2) -> dict:
        """L'arco che un composite dichiara per usare questa variant.

        Porta i parametri. Trait ed effetti restano fuori — vedi la testata.
        """
        return {"id": child_id or self.name, "component": self.base,
                "level": int(level), "params": dict(self.params)}

    def lost_in_attachment(self) -> list[str]:
        """Che cosa si perde incorporandola. Vuoto quando `embeddable`."""
        lost = []
        if self.traits:
            lost.append("%d trait" % len(self.traits))
        if self.effects:
            lost.append("%d effetti" % len(self.effects))
        return lost

    # --------------------------------------------------- serializzazione #
    def to_dict(self) -> dict:
        data: dict[str, Any] = {"base": self.base, "name": self.name,
                                "params": dict(self.params),
                                "coverage": self.coverage,
                                "detail_level": int(self.detail_level),
                                "style": self.style}
        if self.traits:
            data["traits"] = [dict(t) for t in self.traits]
        if self.effects:
            data["effects"] = [dict(e) for e in self.effects]
        if self.description:
            data["description"] = self.description
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "VariantRecipe":
        if not isinstance(data, dict):
            raise AuthoringError(errors.PROJECT_INVALID,
                                 "una variant recipe e' un oggetto JSON")
        return cls(base=str(data.get("base", "")), name=str(data.get("name", "")),
                   params=dict(data.get("params", {})),
                   traits=tuple(data.get("traits", ())),
                   effects=tuple(data.get("effects", ())),
                   description=str(data.get("description", "")),
                   coverage=str(data.get("coverage", CANDIDATE)),
                   detail_level=int(data.get("detail_level", 2)),
                   style=str(data.get("style", "low_poly")))

    def save(self, path) -> Path:
        """Un file minuscolo. Nessun GLB accanto: un test lo verifica."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(dict(self.to_dict(), format=FORMAT_VERSION),
                                     indent=2, sort_keys=True), encoding="utf-8")
        return target

    @classmethod
    def load(cls, path) -> "VariantRecipe":
        source = Path(path)
        if not source.is_file():
            raise AuthoringError(errors.FILE_MISSING,
                                 "variant recipe assente: %s" % source)
        try:
            data = json.loads(source.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as exc:
            raise AuthoringError(errors.PROJECT_INVALID,
                                 "variant illeggibile: %s" % exc) from exc
        return cls.from_dict(data)

    def describe(self) -> str:
        pieces = ["%s = %s" % (k, v) for k, v in sorted(self.params.items())]
        if self.traits:
            pieces.append("%d trait" % len(self.traits))
        if self.effects:
            pieces.append("%d effetti" % len(self.effects))
        return "%s (da %s): %s" % (self.name, self.base,
                                   ", ".join(pieces) or "niente di modificato")
