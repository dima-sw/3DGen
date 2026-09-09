"""Immagine di riferimento: misura locale, modello vision, effetto sul piano.

Le immagini sono sintetiche e generate qui: nessun file di prova da versionare,
nessun servizio esterno, risultati identici su qualunque macchina.
"""
from __future__ import annotations

import numpy as np
import pytest

from app.ai import reference
from app.ai.provider import LLMError, LLMProvider, OfflineProvider
from app.ai.reference import ImageHints, ReferenceError
from app.build.builder import build_scene
from app.core.session import Session
from app.core.spec import GenerationPlan


def rettangolo(path, larghezza: int, altezza: int, colore=(200, 30, 30),
               sfondo=(240, 240, 240), tela=(400, 400)):
    """Una figura piena su sfondo uniforme: sagoma e colore noti in partenza."""
    from PIL import Image

    pixels = np.zeros((tela[1], tela[0], 3), dtype=np.uint8)
    pixels[:, :] = sfondo
    y0 = (tela[1] - altezza) // 2
    x0 = (tela[0] - larghezza) // 2
    pixels[y0:y0 + altezza, x0:x0 + larghezza] = colore
    Image.fromarray(pixels).save(path)
    return path


@pytest.fixture
def auto_rossa(tmp_path):
    """Vista laterale di un'auto rossa: lunga il doppio e mezzo dell'altezza."""
    return rettangolo(tmp_path / "auto.png", 300, 120, colore=(200, 30, 30))


@pytest.fixture
def foto_auto(tmp_path):
    """Due 'foto' di un'auto rossa: sagoma con abitacolo, ruote e strada.

    Serve una figura piu' realistica del rettangolo: il riconoscimento per
    sagoma vive proprio della differenza fra il cofano e il tetto, e lo sfondo
    e' doppio (cielo e asfalto) come in qualunque foto vera.
    """
    from PIL import Image, ImageDraw

    ROSSO, GOMMA = (198, 32, 34), (28, 28, 30)
    CIELO, ASFALTO = (205, 210, 216), (120, 122, 125)

    def disegna(nome, corpo, tetto, ruote):
        image = Image.new("RGB", (900, 500), CIELO)
        d = ImageDraw.Draw(image)
        d.rectangle([0, 400, 900, 500], fill=ASFALTO)
        d.rounded_rectangle(corpo, radius=24, fill=ROSSO)
        d.polygon(tetto, fill=ROSSO)
        for ruota in ruote:
            d.ellipse(ruota, fill=GOMMA)
        path = tmp_path / nome
        image.save(path)
        return str(path)

    return {
        "lato": disegna("lato.png", [120, 250, 780, 375],
                        [(300, 250), (380, 185), (560, 185), (620, 250)],
                        [[200, 330, 300, 430], [600, 330, 700, 430]]),
        "fronte": disegna("fronte.png", [330, 250, 660, 375],
                          [(370, 250), (400, 185), (590, 185), (620, 250)],
                          [[320, 350, 380, 420], [610, 350, 670, 420]]),
    }


class VisionFinta(LLMProvider):
    """Accetta immagini e risponde sempre la stessa cosa."""

    name = "vision-finta"

    def __init__(self, risposta: str = "un'automobile rossa, bassa e allungata"):
        self.risposta = risposta
        self.viste = 0
        self.ultimo_contenuto = None

    def available(self) -> bool:
        return True

    def complete_json(self, system, user, temperature=0.2):
        if isinstance(user, list):
            self.viste += 1
            self.ultimo_contenuto = user
            return {"descrizione": self.risposta}
        raise LLMError("questo provider serve solo per le immagini")


class VisionCieca(LLMProvider):
    """Rifiuta le immagini, come farebbe un modello di solo testo."""

    name = "vision-cieca"

    def __init__(self):
        self.chiamate = 0

    def available(self) -> bool:
        return True

    def complete_json(self, system, user, temperature=0.2):
        self.chiamate += 1
        raise LLMError("questo modello non accetta immagini")


# --------------------------------------------------------------------------- #
# Misura locale
# --------------------------------------------------------------------------- #
def test_proportions_are_measured(auto_rossa):
    hints = reference.analyse(auto_rossa)
    assert hints.aspect == pytest.approx(300 / 120, rel=0.08)
    assert hints.elongation == pytest.approx(2.5, rel=0.08)
    assert hints.width_ratio is None, "una vista sola non conosce la larghezza"


def test_dominant_colour_is_the_object_not_the_background(auto_rossa):
    hints = reference.analyse(auto_rossa)
    r, g, b = (int(hints.dominant[i:i + 2], 16) for i in (1, 3, 5))
    assert r > 150 and g < 90 and b < 90, "rosso, non il grigio dello sfondo"


def test_a_tall_object_is_not_called_elongated(tmp_path):
    hints = reference.analyse(rettangolo(tmp_path / "torre.png", 60, 300))
    assert hints.aspect < 0.4
    assert hints.elongation > 2.0, "l'allungamento non dipende dall'orientamento"


def test_a_symmetric_shape_is_recognised(auto_rossa):
    assert reference.analyse(auto_rossa).symmetry > 0.95


def test_an_asymmetric_shape_is_recognised(tmp_path):
    """La simmetria si misura dentro la sagoma, non rispetto all'inquadratura.

    Serve quindi una forma davvero asimmetrica — un triangolo rettangolo — non
    un rettangolo spostato di lato, che resta specularmente identico a se'.
    """
    from PIL import Image

    pixels = np.full((200, 200, 3), 240, dtype=np.uint8)
    for riga in range(20, 180):
        pixels[riga, 20:20 + (riga - 20)] = (40, 120, 200)
    path = tmp_path / "triangolo.png"
    Image.fromarray(pixels).save(path)
    assert reference.analyse(path).symmetry < 0.75


def test_a_uniform_image_still_gives_numbers(tmp_path):
    """Senza sfondo distinguibile non si solleva: si misura tutta l'immagine."""
    hints = reference.analyse(rettangolo(tmp_path / "pieno.png", 400, 400,
                                         colore=(90, 90, 90), sfondo=(90, 90, 90)))
    assert hints.aspect == pytest.approx(1.0, rel=0.02)
    assert hints.coverage == pytest.approx(1.0, rel=0.02)


def test_a_missing_file_is_a_clear_error(tmp_path):
    with pytest.raises(ReferenceError, match="inesistente"):
        reference.analyse(tmp_path / "non_c_e.png")


def test_a_corrupt_file_is_a_clear_error(tmp_path):
    rotto = tmp_path / "rotto.png"
    rotto.write_bytes(b"questo non e' una immagine")
    with pytest.raises(ReferenceError, match="illeggibile"):
        reference.analyse(rotto)


def test_analysis_is_deterministic(auto_rossa):
    assert reference.analyse(auto_rossa).dominant == reference.analyse(auto_rossa).dominant


def test_a_large_image_is_reduced_before_measuring(tmp_path):
    """Una foto da 12 megapixel non deve costare secondi."""
    import time

    grande = rettangolo(tmp_path / "grande.png", 2400, 1000, tela=(4000, 3000))
    inizio = time.perf_counter()
    hints = reference.analyse(grande)
    assert time.perf_counter() - inizio < 3.0
    assert hints.aspect == pytest.approx(2.4, rel=0.1)


# --------------------------------------------------------------------------- #
# Due viste
# --------------------------------------------------------------------------- #
def test_two_views_give_the_third_dimension(tmp_path, auto_rossa):
    fronte = rettangolo(tmp_path / "fronte.png", 150, 120, colore=(200, 30, 30))
    hints = reference.analyse_views(auto_rossa, fronte)
    assert hints.views == 2
    assert hints.length_ratio == pytest.approx(2.5, rel=0.1)
    assert hints.width_ratio == pytest.approx(1.25, rel=0.1)


def test_one_view_leaves_the_width_undetermined(auto_rossa):
    hints = reference.analyse_views(auto_rossa)
    assert hints.views == 1 and hints.width_ratio is None


# --------------------------------------------------------------------------- #
# Modello vision
# --------------------------------------------------------------------------- #
def test_vision_receives_the_image_inline(auto_rossa):
    provider = VisionFinta()
    testo = reference.describe_with_vision(auto_rossa, provider)
    assert testo == "un'automobile rossa, bassa e allungata"
    tipi = [p["type"] for p in provider.ultimo_contenuto]
    assert tipi == ["text", "image_url"]
    url = provider.ultimo_contenuto[1]["image_url"]["url"]
    assert url.startswith("data:image/png;base64,")


def test_a_blind_model_does_not_stop_the_generation(auto_rossa):
    provider = VisionCieca()
    assert reference.describe_with_vision(auto_rossa, provider) == ""
    assert provider.chiamate == 1, "si prova una volta sola"


def test_without_a_provider_nothing_is_asked(auto_rossa):
    assert reference.describe_with_vision(auto_rossa, None) == ""


def test_the_prompt_falls_back_to_geometry(auto_rossa):
    """Senza vision e senza sagoma riconoscibile resta la sola geometria."""
    testo, hints = reference.prompt_from_image(auto_rossa, provider=None)
    assert hints.dominant in testo
    if not hints.shape:
        assert "allungato" in testo


def test_the_shape_is_recognised_from_the_photo(foto_auto):
    hints = reference.analyse(foto_auto["lato"])
    assert hints.shape == "vehicle"
    assert "sagoma da 'vehicle'" in hints.describe()


def test_two_backgrounds_do_not_widen_the_object(foto_auto):
    """Cielo e asfalto insieme: la sagoma resta quella dell'auto.

    Con un colore di sfondo solo, la striscia d'asfalto entrava nella sagoma e
    l'auto risultava larga quanto l'inquadratura.
    """
    hints = reference.analyse(foto_auto["lato"])
    assert hints.aspect == pytest.approx(2.7, rel=0.15), "non 900/500 di inquadratura"
    assert hints.coverage < 0.5


def test_words_win_over_the_silhouette(foto_auto):
    """Se l'utente dice cosa vuole, l'ipotesi sulla sagoma non serve piu'."""
    testo, hints = reference.prompt_from_image(foto_auto["lato"], "una casa di mattoni")
    assert testo == "una casa di mattoni"
    assert hints.shape == "vehicle", "l'ipotesi resta registrata, ma non decide"


def test_the_prompt_prefers_the_description(auto_rossa):
    testo, _ = reference.prompt_from_image(auto_rossa, provider=VisionFinta())
    assert "automobile rossa" in testo


def test_the_user_text_is_kept_alongside_the_description(auto_rossa):
    testo, _ = reference.prompt_from_image(auto_rossa, "ma con sei ruote",
                                           provider=VisionFinta())
    assert "automobile rossa" in testo and "sei ruote" in testo


# --------------------------------------------------------------------------- #
# Effetto sul piano
# --------------------------------------------------------------------------- #
def piano_veicolo(**params) -> GenerationPlan:
    base = {"length": 4.4, "height": 1.8, "width": 1.85}
    base.update(params)
    return GenerationPlan(prompt="un'auto", object_type="auto",
                          template="vehicle", params=base)


def test_hints_set_the_colour_and_lock_it():
    plan = apply(ImageHints(dominant="#c81e1e", length_ratio=2.5))
    body = next(m for m in plan.materials if m.name == "body")
    assert body.base_color == "#c81e1e"
    assert "body" in plan.locked, "le varianti non devono ricolorarlo"


def apply(hints: ImageHints) -> GenerationPlan:
    return reference.apply_hints(piano_veicolo(), hints)


def test_hints_set_the_length_from_the_measured_ratio():
    plan = apply(ImageHints(dominant="#c81e1e", length_ratio=2.5))
    assert plan.params["length"] == pytest.approx(1.8 * 2.5, rel=0.01)
    assert "length" in plan.locked


def test_an_unknown_width_is_left_alone():
    plan = apply(ImageHints(dominant="#c81e1e", length_ratio=2.5))
    assert plan.params["width"] == 1.85, "non si inventa cio' che non si e' visto"
    assert "width" not in plan.locked


def test_a_known_width_is_applied():
    plan = apply(ImageHints(dominant="#c81e1e", length_ratio=2.5, width_ratio=1.1))
    assert plan.params["width"] == pytest.approx(1.8 * 1.1, rel=0.01)


def test_measures_stay_inside_the_template_limits():
    """Un rapporto assurdo viene clampato, non produce un piano non valido."""
    plan = apply(ImageHints(dominant="#c81e1e", length_ratio=40.0))
    assert plan.params["length"] <= 12.0
    assert build_scene(plan).triangle_count > 0


def test_hints_survive_a_new_variant():
    """La variante successiva deve continuare ad assomigliare al riferimento."""
    from app.ai.variation import vary

    plan = apply(ImageHints(dominant="#c81e1e", length_ratio=2.5))
    lunghezza = plan.params["length"]
    variato = vary(plan, seed=12345)
    assert variato.params["length"] == pytest.approx(lunghezza)
    assert next(m for m in variato.materials if m.name == "body").base_color == "#c81e1e"


def test_hints_colour_an_assembly_too():
    """Anche senza template, il colore va sul materiale piu' usato."""
    from app.core.spec import AssemblySpec, AttachSpec, PartSpec

    plan = GenerationPlan(
        template="freeform", strategy="assembly",
        assembly=AssemblySpec(root="corpo", parts=[
            PartSpec(id="corpo", recipe="body", material="skin", tags=["body"]),
            PartSpec(id="testa", recipe="head", material="skin", tags=["head"],
                     attach=AttachSpec(parent="corpo", socket="head")),
        ]))
    reference.apply_hints(plan, ImageHints(dominant="#2244aa"))
    assert next(m for m in plan.materials if m.name == "skin").base_color == "#2244aa"


# --------------------------------------------------------------------------- #
# Il criterio della milestone, dal principio alla fine
# --------------------------------------------------------------------------- #
def test_a_red_car_photo_gives_a_red_vehicle_without_a_vision_model(auto_rossa):
    """Il criterio: foto di un'auto rossa -> veicolo rosso, proporzioni simili.

    Il provider e' offline: nessun modello vision, nessuna rete. Restano solo
    le misure locali, e devono bastare.
    """
    session = Session(provider=OfflineProvider())
    version = session.generate_from_image(auto_rossa, "un'automobile", seed=7)

    colore = next(m for m in version.plan.materials
                  if m.name == "body").base_color
    r, g, b = (int(colore[i:i + 2], 16) for i in (1, 3, 5))
    assert r > 150 and g < 90 and b < 90, "il veicolo e' rosso come la foto"

    rapporto = version.plan.params["length"] / version.plan.params["height"]
    assert rapporto == pytest.approx(2.5, rel=0.15), "proporzioni simili"
    assert version.scene.triangle_count > 0
    assert "ruota" in version.scene.summary() or version.scene.nodes


def test_a_photo_alone_is_enough(foto_auto):
    """Il criterio nella sua forma piu' dura: **solo** la foto.

    Nessun modello vision, nessuna parola dell'utente. Il tipo di oggetto viene
    dal confronto della sagoma con il catalogo procedurale.
    """
    session = Session(provider=OfflineProvider())
    version = session.generate_from_image(foto_auto["lato"],
                                          front=foto_auto["fronte"], seed=11)

    assert version.plan.template == "vehicle", "una foto d'auto da' un veicolo"
    colore = next(m for m in version.plan.materials if m.name == "body").base_color
    r, g, b = (int(colore[i:i + 2], 16) for i in (1, 3, 5))
    assert r > 140 and g < 90 and b < 90, "ed e' rosso"

    lunghezza, altezza = version.plan.params["length"], version.plan.params["height"]
    assert lunghezza / altezza == pytest.approx(2.68, rel=0.2), "proporzioni della foto"


def test_a_reference_generation_is_still_an_ordinary_version(auto_rossa):
    """Deve restare modificabile, variabile ed esportabile come le altre."""
    session = Session(provider=OfflineProvider())
    session.generate_from_image(auto_rossa, "un'automobile", seed=7)
    lunghezza = session.current_plan.params["length"]

    session.revariate(seed=99)
    assert session.current_plan.params["length"] == pytest.approx(lunghezza)
    assert session.can_undo()
    assert session.undo().plan.params["length"] == pytest.approx(lunghezza)


def test_the_reference_is_recorded_in_the_message(auto_rossa):
    session = Session(provider=OfflineProvider())
    version = session.generate_from_image(auto_rossa, seed=3)
    assert "riferimento:" in version.message
    assert "colore" in version.plan.notes
