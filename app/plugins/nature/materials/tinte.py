"""I materiali della natura: quelli che questo vocabolario porta con se'.

`leaf`, `straw` e `feather` non esistono nel plugin delle primitive, e non
devono esistere li': un plugin che porta un albero porta anche il colore di una
foglia. Chi installa solo `primitives` non ha ne' foglie ne' il loro nome.
"""
from app.core.material import MaterialSpec

MATERIALI = [
    MaterialSpec(name="leaf", base_color="#4f8c4b", roughness=0.72,
                 description="fogliame, chioma"),
    MaterialSpec(name="straw", base_color="#c7a860", roughness=0.78,
                 description="paglia, fieno, rametti secchi"),
    MaterialSpec(name="feather", base_color="#b88c57", roughness=0.66,
                 description="piume"),
]
