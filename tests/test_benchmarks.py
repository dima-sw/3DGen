"""I cinque banchi di prova del progetto.

Non sono test di dettaglio: sono la definizione di cosa il software deve saper
fare. Quelli ancora rossi sono marcati `xfail(strict=True)`, quindi il giorno in
cui iniziano a passare la suite lo dice a voce alta invece di restare silenziosa.

    1. oggetto noto                 -> generatore parametrico
    2. oggetto noto ma modificato   -> nessun generatore nuovo da scrivere
    3. oggetto non previsto         -> composizione, senza template dedicato
    4. ibrido fra due categorie     -> parti di categorie diverse, unite
    5. completamente inventato      -> nessun percorso puo' dire "non so farlo"
"""
from __future__ import annotations

import pytest

from app.ai.provider import OfflineProvider
from app.core.session import Session

OFFLINE = OfflineProvider()

DA_FARE_COMPOSIZIONE = "richiede il motore di composizione (voce 1 del TODO)"
DA_FARE_APERTO = "richiede il generatore aperto (voce 4 del TODO)"


def genera(prompt: str) -> Session:
    session = Session(provider=OFFLINE)
    session.generate_legacy(prompt)
    return session


def tag_presenti(session: Session) -> set[str]:
    return {t for node in session.scene.nodes for t in node.tags}


def ruote_a_terra(session: Session) -> int:
    """Pneumatici montati sugli assi: la scorta non e' una ruota a terra.

    Le varianti possono aggiungere la scorta, quindi contare il tag 'tire'
    renderebbe il banco di prova instabile.
    """
    return len([n for n in session.scene.nodes
                if n.id.startswith("tire_") and "spare" not in n.tags])


# --------------------------------------------------------------------------- #
# 1. Oggetto noto: deve usare il generatore parametrico. Verde da subito.
# --------------------------------------------------------------------------- #
def test_benchmark_1_oggetto_noto():
    s = genera("crea una jeep")
    assert s.current_plan.template == "vehicle"
    assert s.current_plan.strategy == "template"
    assert ruote_a_terra(s) == 4
    assert s.scene.by_id("body").mesh.is_watertight
    assert s.scene.triangle_count > 1000


# --------------------------------------------------------------------------- #
# 2. Oggetto noto ma modificato oltre i parametri previsti.
#    Non deve servire scrivere un "generatore jeep a 6 ruote".
# --------------------------------------------------------------------------- #
def test_benchmark_2_oggetto_noto_modificato():
    s = genera("crea una jeep con sei ruote, cassone posteriore e cabina aperta")
    assert s.current_plan.template == "vehicle", "nessun generatore nuovo: lo stesso, con un asse in piu'"
    assert s.current_plan.params["axle_count"] == 3
    assert ruote_a_terra(s) == 6
    assert "bed" in tag_presenti(s)
    assert s.current_plan.params["has_roof"] is False
    assert s.scene.by_id("body").mesh.is_watertight


# --------------------------------------------------------------------------- #
# 3. Oggetto non previsto da nessun template.
#    Oggi risponde con un cubo: e' il limite che la composizione deve togliere.
# --------------------------------------------------------------------------- #
def test_benchmark_3_oggetto_non_previsto():
    s = genera("crea un pesce")
    assert s.current_plan.strategy == "assembly", "niente template dedicato al pesce"
    tags = tag_presenti(s)
    assert {"body", "tail", "fin"} <= tags, "un pesce ha corpo, coda e pinne"

    # non deve essere una sola primitiva mascherata da pesce
    assert len(s.scene.nodes) > 1 and s.scene.triangle_count > 2000
    # affusolato, non un ovale: il lato lungo domina, comunque sia orientato
    corto, medio, lungo = sorted(s.scene.dimensions())
    assert lungo > medio * 1.6, "il corpo deve essere affusolato"

    # e deve essere un corpo unico, non pezzi appoggiati
    from app.geometry.composition import compose, fused_mesh
    fuso = fused_mesh(compose(s.current_plan.assembly), resolution=72)
    assert fuso.is_watertight
    assert len(fuso.split(only_watertight=False)) == 1


# --------------------------------------------------------------------------- #
# 4. Ibrido fra due categorie. Il banco di prova decisivo.
# --------------------------------------------------------------------------- #
def test_benchmark_4_ibrido():
    s = genera("crea un pesce con il corpo di una persona, quattro braccia e una coda da pesce")
    tags = tag_presenti(s)
    assert "torso" in tags, "il corpo viene dall'umanoide"
    assert "tail" in tags, "la coda viene dal pesce"
    assert len([n for n in s.scene.nodes if "arm" in n.tags]) >= 4
    # e deve essere un corpo solo, non tre pezzi appoggiati
    assert len(s.scene.nodes) >= 4


# --------------------------------------------------------------------------- #
# 5. Completamente inventato: nessuna combinazione prevista da nessuno.
# --------------------------------------------------------------------------- #
def test_benchmark_5_completamente_inventato():
    s = genera("crea un animale con corpo di lupo, sei tentacoli, "
               "ali da pipistrello e corazza metallica")
    tags = tag_presenti(s)
    assert "body" in tags
    assert len([n for n in s.scene.nodes if "tentacle" in n.tags]) == 6
    assert "wing" in tags
    assert s.scene.triangle_count > 3000


# --------------------------------------------------------------------------- #
# Regola 9: qualunque richiesta produce qualcosa. Questa deve restare verde
# in ogni momento della vita del progetto.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("prompt", [
    "crea una jeep",
    "crea un pesce",
    "un pesce con il corpo di una persona",
    "un animale con corpo di lupo e sei tentacoli",
    "qualcosa che nessuno ha mai previsto",
    "asdfgh qwerty zxcvbn",
])
def test_nessuna_richiesta_resta_senza_risposta(prompt):
    s = genera(prompt)
    assert s.scene is not None and s.scene.nodes, "regola 9: mai 'non so farlo'"
    assert s.scene.triangle_count > 0
