"""La memoria delle validazioni: perche' non sta dentro `Component`.

§19 della milestone chiede di valutare se l'associazione «questa parte, questo
componente, questa ricetta, validato» debba poter essere esportata, e dice
esplicitamente di **non** aggiungere `validated_for` a `Component` senza
necessita', e di documentare la decisione. Questa e' la decisione.

## Perche' non in `Component`

Un `Component` installato non **ha** una validazione, cosi' come non ha una
copertura (V6 §2): e' nella libreria o non c'e'. «`creature:eye` va bene come
occhio di drago» non e' una proprieta' dell'occhio — e' il giudizio di chi ha
costruito un drago, e domani qualcuno costruira' una lucertola e avra' un
giudizio diverso sullo stesso pezzo. Metterlo nel componente vorrebbe dire:

* un campo che cresce con il numero di concetti imparati, dentro un oggetto
  congelato nel registry;
* un plugin di terze parti che dichiara di essere stato validato per qualcosa,
  cioe' una dichiarazione che chi la legge non puo' verificare;
* e, soprattutto, una conoscenza che **sparisce disinstallando il plugin del
  concetto**, mentre riguarda il componente di un altro plugin.

## Dove sta invece

In un file a parte, `teach_knowledge.json`, accanto alla libreria. Un record e'
piatto e nomina soltanto cose che esistono altrove:

    concept   dragon          il concetto durante il quale si e' deciso
    path      dragon.head.eye il nodo concettuale
    role/name eye             come si chiamava la parte: e' la chiave di riuso
    component creature:eye    il componente installato
    recipe    dragon_eye      la `VariantRecipe`, se c'era
    params    {...}           i parametri confermati

La chiave di riuso e' **(role, name)**, non il percorso: e' cio' che fa si' che
imparare `wyvern` ritrovi l'occhio del drago (§39), perche' un occhio di wyvern
e un occhio di drago sono lo stesso `role`. E resta un'**evidenza**, non una
promozione: la copertura la legge come `prior_validation` e il nodo diventa
`CANDIDATE`, non `VALIDATED`. Un giudizio dato su un concetto non e' un giudizio
dato su un altro, e fingere che lo sia sarebbe la bugia che §10 vieta.

## Le ricette viaggiano con i record

Una validazione che nomina `recipe dragon_eye` senza portare la ricetta non si
puo' riusare, quindi lo store tiene anche le `VariantRecipe` nominate. Sono
piccole per costruzione (V6 §14: meno di 700 byte, nessuna mesh).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.authoring.variant import VariantRecipe
from app.core.config import SETTINGS
from app.teach import errors
from app.teach.errors import TeachError
from app.teach.model import VALIDATED, TeachProject, slug

FORMAT_VERSION = 1
FILENAME = "teach_knowledge.json"


def default_path() -> Path:
    """Accanto alla libreria dell'utente, non dentro i plugin installati."""
    return Path(SETTINGS.library_dir) / FILENAME


@dataclass(frozen=True)
class KnowledgeRecord:
    """Una scelta confermata. Nomina cose che vivono altrove."""

    concept: str
    path: str
    component: str
    role: str = ""
    name: str = ""
    recipe: str = ""
    params: tuple = ()               # coppie ordinate: un record e' immutabile
    decided_by: str = "user"

    @property
    def values(self) -> dict:
        return {k: v for k, v in self.params}

    def key(self) -> tuple[str, str]:
        """La chiave di riuso: (role, name), normalizzata."""
        return (slug(self.role, ""), slug(self.name, ""))

    def describe(self) -> str:
        pieces = ["%s -> %s" % (self.path, self.component)]
        if self.recipe:
            pieces.append("recipe " + self.recipe)
        pieces.append(self.decided_by + " validated")
        return " | ".join(pieces)

    def to_dict(self) -> dict:
        data: dict[str, Any] = {"concept": self.concept, "path": self.path,
                                "component": self.component,
                                "decided_by": self.decided_by}
        for key in ("role", "name", "recipe"):
            value = getattr(self, key)
            if value:
                data[key] = value
        if self.params:
            data["params"] = self.values
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "KnowledgeRecord":
        params = dict(data.get("params", {}) or {})
        return cls(concept=str(data.get("concept", "")),
                   path=str(data.get("path", "")),
                   component=str(data.get("component", "")),
                   role=str(data.get("role", "")), name=str(data.get("name", "")),
                   recipe=str(data.get("recipe", "")),
                   params=tuple(sorted(params.items())),
                   decided_by=str(data.get("decided_by", "user")))


@dataclass
class TeachKnowledge:
    """Lo store delle validazioni. Un file, nessun indice, nessun database."""

    records: tuple[KnowledgeRecord, ...] = ()
    recipes: dict = field(default_factory=dict)
    path: Path | None = None

    def __post_init__(self) -> None:
        self.records = tuple(self.records)

    # ------------------------------------------------------------- lettura #
    def records_for(self, *, role: str = "", name: str = "") -> list[KnowledgeRecord]:
        """I record che valgono per una parte con questo ruolo o questo nome."""
        wanted = (slug(role, ""), slug(name, ""))
        found = []
        for record in self.records:
            key = record.key()
            if wanted[0] and key[0] and wanted[0] == key[0]:
                found.append(record)
            elif wanted[1] and key[1] and wanted[1] == key[1]:
                found.append(record)
        return found

    def record_for(self, component: str, *, role: str = "",
                   name: str = "") -> KnowledgeRecord | None:
        found = [r for r in self.records_for(role=role, name=name)
                 if r.component == component]
        return found[-1] if found else None

    def components(self) -> set[str]:
        return {r.component for r in self.records}

    def variant(self, name: str) -> VariantRecipe | None:
        return self.recipes.get(name)

    # ------------------------------------------------------------- scrittura #
    def add(self, record: KnowledgeRecord,
            recipe: VariantRecipe | None = None) -> KnowledgeRecord:
        """Aggiunge un record; sostituisce quello identico invece di duplicarlo."""
        kept = tuple(r for r in self.records
                     if not (r.path == record.path and r.concept == record.concept
                             and r.component == record.component))
        self.records = kept + (record,)
        if recipe is not None:
            self.recipes[recipe.name] = recipe
        return record

    def merge(self, project: TeachProject) -> list[KnowledgeRecord]:
        """Prende dal progetto ogni nodo validato che punta a un componente.

        Non prende i nodi generati da questo stesso Teach quando il componente
        appartiene al plugin del concetto: quella non e' una validazione
        riusabile, e' il plugin nuovo — chi lo installa lo trova per retrieval
        come qualunque altro, e non serve un record che lo dica.
        """
        added: list[KnowledgeRecord] = []
        for node in project.nodes():
            state = project.state(node.id)
            if state.coverage != VALIDATED or state.solution is None:
                continue
            solution = state.solution
            if project.owns(solution.ref):
                continue
            record = KnowledgeRecord(
                concept=project.concept, path=node.id, component=solution.ref,
                role=node.role, name=node.name, recipe=solution.recipe,
                params=tuple(sorted(solution.params.items())),
                decided_by=solution.decided_by)
            recipe = project.variant(solution.recipe) if solution.recipe else None
            self.add(record, recipe)
            added.append(record)
        return added

    # --------------------------------------------------- serializzazione #
    def to_dict(self) -> dict:
        return {"format": FORMAT_VERSION,
                "records": [r.to_dict() for r in self.records],
                "recipes": {k: v.to_dict() for k, v in sorted(self.recipes.items())}}

    @classmethod
    def from_dict(cls, data: dict) -> "TeachKnowledge":
        if not isinstance(data, dict):
            raise TeachError(errors.PROJECT_INVALID,
                             "la conoscenza Teach e' un oggetto JSON")
        if int(data.get("format", 0) or 0) != FORMAT_VERSION:
            raise TeachError(errors.PROJECT_INVALID,
                             "formato della conoscenza %r non leggibile"
                             % data.get("format"))
        return cls(records=tuple(KnowledgeRecord.from_dict(r)
                                 for r in data.get("records", ())),
                   recipes={str(k): VariantRecipe.from_dict(v) for k, v
                            in dict(data.get("recipes", {})).items()})

    def save(self, path=None) -> Path:
        target = Path(path or self.path or default_path())
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True),
                          encoding="utf-8")
        self.path = target
        return target

    @classmethod
    def load(cls, path=None) -> "TeachKnowledge":
        """Carica, oppure restituisce uno store vuoto: l'assenza non e' un errore."""
        source = Path(path or default_path())
        if not source.is_file():
            return cls(path=source)
        try:
            data = json.loads(source.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as exc:
            raise TeachError(errors.PROJECT_INVALID,
                             "conoscenza Teach illeggibile: %s" % exc) from exc
        store = cls.from_dict(data)
        store.path = source
        return store

    def describe(self) -> str:
        return "%d validazioni, %d ricette" % (len(self.records), len(self.recipes))
