"""I cinque casi d'oro: restano verdi, per sempre.

Non sono test di regressione fra tanti: sono **il** criterio. Se questi cinque
girano, il sistema fa quello per cui esiste — comporre pezzi di vocabolari che
non si conoscono, in un modello vero, a partire da una frase.

    A   persona con testa di rana, corpo di pesce, gambe di spada, alta e magra
    B   casa con un pianeta enorme sopra
    C   albero con un nido e un uccello
    D   robot con testa di drago, corpo di pesce, ali e cristalli
    E   il caso completo: braccia multiple, accessori annidati, due effetti

E non verificano soltanto che non esploda. Per ognuno si controlla, con gli
stessi criteri: quali plugin sono stati scelti, che i riferimenti risolti siano
quelli, che gli attacchi abbiano trovato un innesto, che i parametri chiesti
siano arrivati, che gli effetti si vedano, che la mesh esista e stia nel budget,
che i pezzi siano dove i socket dicono, che non ci siano diagnosi gravi, e che
due esecuzioni diano lo stesso modello.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import numpy as np
import pytest

from app.ai.provider import OfflineProvider
from app.build.validate import silhouette_fill
from app.core.planner.planner import MockPlanner
from app.core.session import Options, Session

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_scenari import COPIONI, MOSTRO_COMPLETO      # noqa: E402


# --------------------------------------------------------------------------- #
# Caso E: tutto insieme
# --------------------------------------------------------------------------- #
def _caso_completo() -> dict:
    """Il mostro, con quattro braccia, accessori annidati e due effetti.

    Parte dal piano del traguardo e aggiunge le tre cose che mancavano: due
    braccia in piu' sugli innesti ventrali del corpo di pesce, una catena di
    accessori profonda quattro — capelli, casco, visiera, cristallo — e un
    secondo effetto sopra il primo.
    """
    piano = copy.deepcopy(MOSTRO_COMPLETO)
    torso = piano["root"]["children"][0]
    for nome, lato in (("braccio_extra_l", "l"), ("braccio_extra_r", "r")):
        torso["children"].append({
            "id": nome, "ref": "humanoid:arm", "insert": 1.15,
            "at": {"capability": "limb_mount", "side": lato}})

    casco = torso["children"][0]["children"][0]["children"][0]["children"][0]
    casco["children"] = [{
        "id": "visiera", "ref": "accessories:visor", "optional": True,
        "scale_mode": "socket", "at": {"capability": "visor_mount"},
        "children": [{"id": "cristallo", "ref": "fantasy:crystal",
                      "optional": True, "scale_mode": "socket",
                      "at": {"capability": "anchor"}}]}]
    piano["root"]["effects"].append(
        {"type": "perspective_exaggeration", "scope": "model", "amount": 0.5})
    return piano


CASO_COMPLETO = _caso_completo()
PROMPT_COMPLETO = ("persona con testa di rana, corpo di pesce, gambe di spada, "
                   "braccia multiple, accessori ricorsivi, alta e magra, "
                   "con una prospettiva stranissima")

# nome: (prompt, componenti che devono comparire, parti minime)
CASI = {
    "A": ("una persona con la testa di rana e le gambe di spada, molto alta e magra",
          {"humanoid:body", "creature:frog_head", "weapon:sword"}, 5),
    "B": ("una casa con un pianeta enorme sopra",
          {"architecture:house", "space:planet"}, 3),
    "C": ("un albero con un nido e un uccello sopra",
          {"nature:tree", "nature:nest", "nature:bird"}, 4),
    "D": ("un robot con testa di drago, corpo di pesce, ali e cristalli luminosi",
          {"creature:dragon_head", "fish:fish_body", "fantasy:wing",
           "fantasy:crystal"}, 5),
    "E": (PROMPT_COMPLETO,
          {"creature:frog_head", "fish:fish_body", "weapon:sword",
           "accessories:helmet", "accessories:visor", "fantasy:crystal"}, 10),
}


@pytest.fixture(scope="module")
def sessione() -> Session:
    copioni = dict(COPIONI)
    copioni[PROMPT_COMPLETO] = CASO_COMPLETO
    return Session(provider=OfflineProvider(), planner=MockPlanner(scripts=copioni))


@pytest.fixture(scope="module")
def modelli(sessione):
    return {nome: sessione.generate(prompt) for nome, (prompt, _, _) in CASI.items()}


def riferimenti(risultato) -> set[str]:
    return {n.ref for n in risultato.resolved.walk()}


# --------------------------------------------------------------------------- #
# I criteri, per tutti e cinque
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("nome", sorted(CASI))
def test_the_right_plugins_are_chosen(modelli, nome):
    """Selezione dei componenti: quelli che la frase nomina, davvero risolti."""
    voluti = CASI[nome][1]
    assert voluti <= riferimenti(modelli[nome]), \
        sorted(voluti - riferimenti(modelli[nome]))


@pytest.mark.parametrize("nome", sorted(CASI))
def test_every_attachment_found_a_socket(modelli, nome):
    """Nessun pezzo appeso al vuoto: ogni figlio ha un innesto e un socket."""
    risultato = modelli[nome]
    for nodo in risultato.resolved.walk():
        if nodo.link is None:
            continue
        assert nodo.link.parent, nodo.id
        assert nodo.link.parent_socket or nodo.link.capability, nodo.id


@pytest.mark.parametrize("nome", sorted(CASI))
def test_the_model_has_geometry_and_stays_in_the_budget(modelli, nome):
    risultato = modelli[nome]
    parti = CASI[nome][2]
    assert len(risultato.build.geometry()) >= parti
    assert 100 < risultato.triangles < 3200, risultato.triangles
    assert np.all(np.isfinite(risultato.build.bounds))


@pytest.mark.parametrize("nome", sorted(CASI))
def test_no_fatal_diagnostics(modelli, nome):
    gravi = [d for d in modelli[nome].diagnostics if d.fatal]
    assert not gravi, [d.describe() for d in gravi]


@pytest.mark.parametrize("nome", sorted(CASI))
def test_every_piece_sits_where_its_socket_says(modelli, nome):
    """Ogni pezzo tocca il socket da cui pende: nessun giunto aperto."""
    risultato = modelli[nome]
    for costruito in risultato.build.walk():
        if costruito.mesh is None or not len(costruito.mesh.vertices):
            continue
        padre = risultato.build.nodes.get(costruito.parent)
        if padre is None or not costruito.parent_socket:
            continue
        innesto = padre.socket_world(costruito.parent_socket)
        if innesto is None:
            continue
        punti = np.asarray(costruito.mesh.vertices, dtype=float)
        distanza = float(np.min(np.linalg.norm(punti - innesto.position, axis=1)))
        misura = float(np.max(costruito.mesh.bounds[1] - costruito.mesh.bounds[0]))
        assert distanza <= max(innesto.radius * 3.0, misura), \
            "%s e' a %.3f dal proprio innesto" % (costruito.id, distanza)


@pytest.mark.parametrize("nome", sorted(CASI))
def test_the_same_prompt_gives_the_same_model(sessione, nome):
    """Determinismo dalla frase al vertice."""
    prompt = CASI[nome][0]
    uno = sessione.generate(prompt, remember=False)
    due = sessione.generate(prompt, remember=False)
    assert uno.plan_json == due.plan_json
    assert uno.triangles == due.triangles
    assert np.allclose(uno.build.bounds, due.build.bounds)


# --------------------------------------------------------------------------- #
# Quello che ogni caso deve mostrare in particolare
# --------------------------------------------------------------------------- #
def test_case_a_swaps_without_leaving_the_old_part(modelli):
    """Una sostituzione non lascia due pezzi: la testa umana non c'e' piu'."""
    usati = riferimenti(modelli["A"])
    assert "humanoid:head" not in usati
    assert "humanoid:leg" not in usati


def test_case_a_shows_the_effect_it_asked_for(sessione):
    """«Alta e magra» si vede: piu' alta e piu' stretta di quella normale."""
    prompt = CASI["A"][0]
    magra = sessione.generate(prompt, remember=False)
    senza = copy.deepcopy(magra.plan_json)
    senza["root"].pop("effects", None)
    normale = sessione.build(senza)

    assert magra.build.size[1] > normale.build.size[1] * 1.15
    snellezza = magra.build.size[0] / magra.build.size[1]
    assert snellezza < normale.build.size[0] / normale.build.size[1]


def test_case_b_carries_the_parameters_the_plan_asked_for(modelli):
    """I parametri arrivano fino alla geometria: il pianeta e' enorme davvero."""
    risultato = modelli["B"]
    pianeta = risultato.resolved.node("planet")
    assert pianeta.values["radius"] > 20
    mesh = risultato.build.node("planet").mesh
    assert float(mesh.extents.max()) > pianeta.values["radius"]


def test_case_c_is_a_chain_three_deep(modelli):
    """Albero, ramo, nido, uccello: ognuno appeso al precedente."""
    risolto = modelli["C"].resolved
    nido, uccello = risolto.node("nest"), risolto.node("bird")
    assert nido.link.capability == "branch_mount"
    assert uccello.link.parent == "nest"
    assert max(n.depth for n in risolto.walk()) >= 2


def test_case_d_mixes_four_vocabularies(modelli):
    plugin = {r.partition(":")[0] for r in riferimenti(modelli["D"])}
    assert len(plugin) >= 4, plugin


def test_case_e_has_more_than_two_arms(modelli):
    braccia = [n.id for n in modelli["E"].resolved.walk()
               if n.ref == "humanoid:arm"]
    assert len(braccia) >= 4, braccia


def test_case_e_nests_accessories_four_deep(modelli):
    """Capelli, casco, visiera, cristallo: un accessorio ha i propri accessori."""
    risolto = modelli["E"].resolved
    catena = ["capelli", "casco", "visiera", "cristallo"]
    for figlio, padre in zip(catena[1:], catena):
        assert risolto.node(figlio) is not None, figlio
        assert risolto.node(figlio).link.parent == padre
    assert risolto.node("cristallo").depth >= 6


def test_case_e_applies_both_effects(modelli):
    applicati = {e.id for e in modelli["E"].effects.applied}
    programmati = {e.id for e in modelli["E"].effects.planned}
    assert "fx:lanky" in applicati, "una proporzione si applica prima del build"
    assert "fx:perspective_exaggeration" in programmati, "una deformazione dopo"


def test_case_e_is_still_a_figure_and_not_a_blob(modelli):
    """Cinque vocabolari, due effetti, e la sagoma resta articolata."""
    assert silhouette_fill(modelli["E"].build) < 0.72


# --------------------------------------------------------------------------- #
# Quello che i cinque casi dimostrano insieme
# --------------------------------------------------------------------------- #
def test_all_five_go_through_the_same_pipeline(modelli):
    """Nessun ramo speciale: la stessa strada per una casa e per un mostro."""
    for nome, risultato in modelli.items():
        assert risultato.plan_json, nome
        assert risultato.plan is not None, nome
        assert risultato.resolved.refs(), nome
        assert risultato.effects is not None, nome
        assert risultato.build.meshes(), nome


def test_the_core_never_named_any_of_this():
    """Nessuno dei nomi di questi cinque casi compare nel core."""
    import pathlib
    import re

    radice = pathlib.Path(__file__).resolve().parents[1] / "app" / "core"
    parole = re.compile(r"\b(rana|frog|drago|dragon|pesce|fish|casa|house|"
                        r"pianeta|planet|albero|tree|uccello|bird|spada|sword|"
                        r"robot|umanoide|humanoid)\b", re.I)
    colpevoli = []
    for file in radice.rglob("*.py"):
        testo = file.read_text(encoding="utf-8")
        # i commenti spiegano con degli esempi: si guarda il codice
        codice = "\n".join(r for r in testo.splitlines()
                           if not r.strip().startswith("#"))
        codice = re.sub(r'"""(?:.|\n)*?"""', "", codice)
        for trovato in parole.findall(codice):
            colpevoli.append("%s: %s" % (file.name, trovato))
    assert not colpevoli, colpevoli
