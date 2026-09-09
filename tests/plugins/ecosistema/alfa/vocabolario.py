"""Un effetto e uno stile, dichiarati dallo stesso plugin dei componenti."""
from app.core.params import RATIO, ParamSpec
from app.core.vocabulary import (SCOPE_MODEL, SCOPE_PART, STAGE_PROPORTION,
                                 EffectSpec, StyleProfile)

ALLUNGA = EffectSpec(
    id="allunga",
    description="tira una cosa lungo il suo asse di crescita",
    scopes=(SCOPE_MODEL, SCOPE_PART),
    params={"quanto": ParamSpec(1.0, RATIO, min=0.1, max=3.0)},
    stage=STAGE_PROPORTION,
    tags=frozenset({"deformazione"}),
)

SOLO_SU_ALFA = EffectSpec(
    id="solo_su_alfa",
    stage=STAGE_PROPORTION,
    description="ha senso solo su chi fornisce cosa_alfa",
    scopes=(SCOPE_PART,),
    applies_to=frozenset({"cosa_alfa"}),
)

SPIGOLOSO = StyleProfile(
    id="spigoloso",
    description="pochi lati, niente smussi",
    params={"lati": 4, "smussatura": 0.0, "triangoli": 900},
    tags=frozenset({"prova"}),
)
