"""Il cristallo: una superficie che nessun altro vocabolario aveva.

Lucida, quasi non ruvida e un po' trasparente. E' l'unica cosa che questo
plugin dichiara oltre alle forme, e sta con le forme che la usano.
"""
from app.core.material import MaterialSpec

MATERIALI = [
    MaterialSpec(name="crystal", base_color="#7ac7db", roughness=0.08,
                 metallic=0.1, opacity=0.75,
                 description="cristallo: lucido, freddo, un po' trasparente"),
]
