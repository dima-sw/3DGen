"""Il materiale: un nome, un colore, due numeri.

Stava dentro `core/spec.py`, il contratto fra l'LLM e la vecchia pipeline
geometrica, insieme a `GenerationPlan` e ai suoi componenti. Non era il suo
posto: un materiale non ha niente a che fare con il modo in cui un piano viene
scritto, e infatti sopravvive a quel modulo. Lo usano la scena, l'export, la
libreria delle texture e l'interfaccia.

## Il colore appartiene a chi dichiara la forma

Un componente dice `material="skin"` e non `#c98a5a`: il nome e' un
riferimento, la tinta e' una decisione dello stile visivo. Chi decide la tinta
e' il **plugin**, che registra i propri `MaterialSpec` come registra i propri
componenti — il registry li raccoglie allo stesso modo. Un plugin che porta
cristalli porta anche il colore di un cristallo, e il core non ha un elenco di
materiali del mondo da tenere aggiornato.

Un nome che nessuno ha dichiarato non e' un errore: si prende il predefinito e
si va avanti, perche' un modello grigio e' meglio di un modello mancante.

## Perche' il nome non e' qualificato

Componenti, effetti e stili si chiamano `plugin:nome`, perche' due plugin
possono legittimamente avere due teste diverse. Un materiale no: `skin` e' un
nome che piu' plugin usano **volendo la stessa cosa**, come una capability. Chi
lo dichiara per primo lo definisce, e chi lo ridichiara diverso viene riferito
invece che sovrascrivere in silenzio.
"""
from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
PREDEFINITO = "default"


class MaterialSpec(BaseModel):
    """Come appare una superficie. Nient'altro: niente texture, niente shader."""

    model_config = ConfigDict(extra="ignore")

    name: str
    base_color: str = "#9aa0a6"
    roughness: float = Field(0.6, ge=0.0, le=1.0)
    metallic: float = Field(0.0, ge=0.0, le=1.0)
    opacity: float = Field(1.0, ge=0.05, le=1.0)
    description: str = ""

    @field_validator("base_color")
    @classmethod
    def _hex(cls, v: str) -> str:
        """Un colore storto non fa fallire un plugin: diventa grigio."""
        v = v.strip()
        if not v.startswith("#"):
            v = "#" + v
        if not HEX_RE.match(v):
            return "#9aa0a6"
        return v.lower()

    def rgba(self) -> tuple[float, float, float, float]:
        h = self.base_color.lstrip("#")
        r, g, b = (int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
        return (r, g, b, self.opacity)

    def describe(self) -> str:
        return "%s %s (r=%.2f m=%.2f)" % (self.name, self.base_color,
                                          self.roughness, self.metallic)


def default_material(name: str = PREDEFINITO) -> MaterialSpec:
    """Il ripiego: un grigio neutro con il nome chiesto."""
    return MaterialSpec(name=name or PREDEFINITO)
