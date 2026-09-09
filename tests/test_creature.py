"""Parser semantico e costruzione di creature, anche impossibili."""
from __future__ import annotations

import numpy as np
import pytest

from app.ai.creature import (
    ARCHETYPE_DEFAULTS, BODY_PRESETS, HEAD_PRESETS, CreatureSpec,
    build_assembly, looks_like_creature, parse_creature,
)
from app.ai.text import has_word, normalize
from app.geometry.composition import compose


def parse(prompt: str) -> CreatureSpec:
    return parse_creature(prompt)


# --------------------------------------------------------------------------- #
# Riconoscimento
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("prompt", [
    "crea un pesce", "un lupo", "una creatura strana", "un animale a quattro zampe",
    "un mostro con sei tentacoli", "una persona", "un uccello",
    "un essere con corpo di lupo e testa di drago",
])
def test_creature_prompts_are_recognised(prompt):
    assert looks_like_creature(normalize(prompt))


@pytest.mark.parametrize("prompt", [
    "crea una jeep", "una casa a due piani", "una spada medievale",
    "un tavolo rotondo", "un cubo", "asdfgh qwerty",
    "un robot umanoide con armatura",      # il template parametrico lo fa meglio
])
def test_non_creature_prompts_are_left_to_the_templates(prompt):
    assert not looks_like_creature(normalize(prompt))


def test_template_words_lose_priority_when_the_request_is_exotic():
    """Un robot normale resta al template; uno con i tentacoli no."""
    assert not looks_like_creature(normalize("un robot umanoide"))
    assert looks_like_creature(normalize("un robot con sei tentacoli"))
    assert looks_like_creature(normalize("un androide con testa di lupo"))


@pytest.mark.parametrize("prompt", [
    "qualcosa di indefinito",       # "fin" e' dentro "indefinito"
    "una scala di legno",           # "ala" e' dentro "scala"
    "un lavoro di un giorno",       # "corno" e' dentro "giorno"
])
def test_substring_false_positives_do_not_trigger_composition(prompt):
    """Regressione: il confronto per sottostringa attivava la composizione."""
    assert not looks_like_creature(normalize(prompt))


def test_has_word_matches_whole_words_only():
    assert not has_word("qualcosa di indefinito", ["fin"])
    assert has_word("sei pinne dorsali", ["pinne"])


# --------------------------------------------------------------------------- #
# Innesti: "con il corpo di X", "testa di Y"
# --------------------------------------------------------------------------- #
def test_graft_reads_body_and_head_separately():
    spec = parse("un pesce con il corpo di una persona e una coda da pesce")
    assert spec.body == "human"
    assert spec.head == "fish"
    assert spec.archetype == "humanoid"
    assert spec.tail == "fish"


@pytest.mark.parametrize("prompt,expected", [
    ("con il corpo di una persona", "human"),
    ("con corpo di un lupo", "wolf"),
    ("con il corpo della persona", "human"),
    ("con corpo di cavallo", "horse"),
])
def test_articles_do_not_swallow_the_species(prompt, expected):
    """Regressione: l'alternanza un|uno|una consumava 'un' e leggeva 'a'."""
    assert parse("una creatura " + prompt).body == expected


def test_head_graft_wins_over_word_order():
    spec = parse("una creatura con testa di squalo e corpo di cavallo")
    assert spec.head == "shark" and spec.body == "horse"


# --------------------------------------------------------------------------- #
# Conteggi e modificatori
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("prompt,attribute,expected", [
    ("una creatura con quattro braccia", "arms", 4),
    ("una creatura con sei tentacoli", "tentacles", 6),
    ("una creatura con otto zampe", "legs", 8),
    ("una creatura con due ali", "wings", 2),
    ("una creatura con due corna", "horns", 2),
])
def test_explicit_counts_win(prompt, attribute, expected):
    assert getattr(parse(prompt), attribute) == expected


def test_archetype_defaults_apply_when_nothing_is_said():
    assert parse("un pesce").tail == "fish"
    assert parse("un lupo").legs == ARCHETYPE_DEFAULTS["quadruped"]["legs"]
    assert parse("un uccello").wings == 2
    assert parse("un polpo").tentacles == 8


def test_armor_and_size_are_read():
    assert parse("una creatura con corazza metallica").armor is True
    grande = parse("un lupo gigante")
    piccolo = parse("un lupo piccolo")
    assert grande.scale > 1.0 > piccolo.scale


def test_measured_height_sets_the_scale():
    assert parse("una creatura alta 3 metri").scale == pytest.approx(3.0 / 1.7, rel=0.01)


# --------------------------------------------------------------------------- #
# Dal parser all'assemblaggio
# --------------------------------------------------------------------------- #
def test_assembly_has_one_part_per_declared_appendage():
    spec = parse("una creatura con corpo di lupo, sei tentacoli e due ali")
    assembly, _ = build_assembly(spec)
    ids = [p.id for p in assembly.parts]
    assert sum(1 for i in ids if i.startswith("tentacolo_")) == 6
    assert sum(1 for i in ids if i.startswith("ala_")) == 2
    assert assembly.root == "corpo"


def test_every_part_of_an_assembly_finds_its_socket():
    """Se un socket manca, la parte sparisce senza rumore: qui deve rumoreggiare."""
    for prompt in ("un pesce", "una persona", "un lupo", "un uccello",
                   "un pesce con il corpo di una persona e quattro braccia",
                   "un animale con corpo di lupo, sei tentacoli, ali e corazza"):
        assembly, _ = build_assembly(parse(prompt))
        result = compose(assembly)
        assert not result.warnings, "%s -> %s" % (prompt, result.warnings)
        assert len(result.parts) == len(assembly.parts)


def test_bilateral_symmetry_is_preserved():
    assembly, _ = build_assembly(parse("una persona con quattro braccia"))
    result = compose(assembly)
    for left, right in (("braccio_0", "braccio_1"), ("braccio_2", "braccio_3"),
                        ("coscia_0", "coscia_1")):
        a = result.by_id(left).centre()
        b = result.by_id(right).centre()
        assert a[0] == pytest.approx(-b[0], abs=1e-6), "%s/%s non simmetrici" % (left, right)
        assert a[1] == pytest.approx(b[1], abs=1e-6)


def test_head_on_a_neck_faces_forward_not_upward():
    """Regressione: sul collo verticale la testa guardava in alto."""
    assembly, _ = build_assembly(parse("una persona"))
    result = compose(assembly)
    testa = result.by_id("testa")
    # il muso della testa e' il suo +X locale
    facing = testa.placement.apply_direction(np.array([1.0, 0.0, 0.0]))
    assert facing[1] < 0.4, "la testa non deve guardare verso l'alto"
    assert abs(facing[2]) > 0.8, "deve guardare avanti, lungo Z"


def test_head_on_a_body_follows_the_body_axis():
    assembly, _ = build_assembly(parse("un pesce"))
    result = compose(assembly)
    facing = result.by_id("testa").placement.apply_direction(np.array([1.0, 0.0, 0.0]))
    assert facing[0] > 0.9, "sul corpo orizzontale la testa guarda in avanti"


def test_species_presets_are_data_not_code():
    """Aggiungere una specie deve costare una riga di dizionario."""
    assert "wolf" in BODY_PRESETS and "dragon" in HEAD_PRESETS

    # Tutte le specie devono descriversi con le stesse chiavi — altrimenti
    # aggiungerne una vorrebbe dire ricordarsi quali — e ogni chiave deve
    # esistere davvero nella ricetta, o sarebbe un numero scritto nel vuoto.
    from app.geometry.recipe import get_recipe, load_catalog

    load_catalog()
    attese = set(BODY_PRESETS["generic"])
    ammesse = set(get_recipe("body").params)
    for nome, preset in BODY_PRESETS.items():
        assert set(preset) == attese, nome
        assert set(preset) <= ammesse, nome
    attese = set(HEAD_PRESETS["generic"])
    ammesse = set(get_recipe("head").params)
    for nome, preset in HEAD_PRESETS.items():
        assert set(preset) == attese, nome
        assert set(preset) <= ammesse, nome
