"""I banchi di prova con i plugin veri.

Non provano piu' che l'architettura regga — quello lo fanno i test del core.
Provano che **produca geometria utile**: un umanoide riconoscibile, una casa su
un pianeta, un mostro fatto di pezzi di quattro vocabolari diversi, e che tutto
questo passi dallo stesso resolver, dagli stessi effetti e dallo stesso builder.

La differenza fra i due enunciati e' enorme, ed e' la ragione di questo file.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from app.build.assembler import build
from app.build.validate import validate
from app.core.capability import Requirement
from app.core.effect import apply_effects
from app.core.graph import CompositionGraph
from app.core.registry import Registry, load
from app.core.resolver import resolve

QUI = Path(__file__).resolve().parent
PLUGIN = QUI.parent / "app" / "plugins"
TERZE_PARTI = QUI / "plugins" / "terze_parti"


@pytest.fixture(scope="module")
def catalogo() -> Registry:
    """Tutti i plugin installati, congelati per la durata dei banchi."""
    r = load([PLUGIN])
    assert not r.report.errors(), r.report.describe()
    return r.freeze()


def chiedi(capability: str = "", **kwargs) -> Requirement:
    return Requirement(capability=capability, **kwargs)


ALTO = frozenset({"alto"})
BASSO = frozenset({"basso"})


def figura(height: float = 1.8, detail_level: int = 2) -> CompositionGraph:
    """Il piano di una figura umanoide completa.

    E' l'unico posto in cui questi test nominano delle parti del corpo: da qui
    in poi tutto passa per capability e socket.
    """
    g = CompositionGraph(detail_level=detail_level)
    g.set_root("corpo", "humanoid:body", height=height)
    g.add_child("torso", "humanoid:torso", "corpo", requirement=chiedi("core_mount"))
    g.add_child("collo", "humanoid:neck", "torso", requirement=chiedi("head_mount"),
                insert=0.3)
    g.add_child("testa", "humanoid:head", "collo", requirement=chiedi("head_mount"),
                insert=0.25)
    for nome, lato in (("braccio_l", "l"), ("braccio_r", "r")):
        g.add_child(nome, "humanoid:arm", "torso", insert=1.15,
                    requirement=chiedi("limb_mount", side=lato, tags=ALTO))
    for nome, lato in (("gamba_l", "l"), ("gamba_r", "r")):
        g.add_child(nome, "humanoid:leg", "torso", insert=0.9,
                    requirement=chiedi("limb_mount", side=lato, tags=BASSO))
    return g


def casa_su_pianeta(raggio: float = 40.0) -> CompositionGraph:
    g = CompositionGraph()
    g.set_root("casa", "architecture:house", width=6.0, height=4.5, depth=5.0)
    g.add_child("pianeta", "space:planet", "casa", requirement=chiedi("surface"),
                radius=raggio, insert=0.0)
    return g


def costruisci(g: CompositionGraph, catalogo: Registry, *, effetti: bool = True):
    fatto = apply_effects(resolve(g, catalogo), catalogo) if effetti \
        else resolve(g, catalogo)
    out = build(fatto)
    validate(out, style=catalogo.style("low_poly"))
    return out


def gravi(out) -> list:
    return [d for d in out.report if d.fatal]


# --------------------------------------------------------------------------- #
# Banco 1: l'umanoide vero
# --------------------------------------------------------------------------- #
def test_a_humanoid_is_built_and_is_the_height_it_asked_for(catalogo):
    out = costruisci(figura(1.8), catalogo)
    assert not gravi(out), out.report.describe()
    assert out.size[1] == pytest.approx(1.8, rel=0.02), \
        "alto 1,80 per costruzione, senza fattori di resa da rimisurare"
    assert out.triangles > 300


@pytest.mark.parametrize("altezza", [0.6, 1.8, 6.0])
def test_the_proportions_hold_at_any_size(catalogo, altezza):
    """La stessa figura a taglie diverse: cambia la scala, non la forma."""
    out = costruisci(figura(altezza), catalogo)
    assert out.size[1] == pytest.approx(altezza, rel=0.02)
    forma = out.size / altezza
    riferimento = costruisci(figura(1.8), catalogo).size / 1.8
    assert np.allclose(forma, riferimento, rtol=0.02), "le proporzioni non ballano"


def test_the_humanoid_has_no_detached_or_swallowed_parts(catalogo):
    out = costruisci(figura(1.8, detail_level=3), catalogo)
    assert "JOINT_GAP" not in out.report.codes(), out.report.describe()
    assert "PART_SUBMERGED" not in out.report.codes(), out.report.describe()


def test_at_high_detail_the_limbs_become_their_segments(catalogo):
    out = costruisci(figura(1.8, detail_level=3), catalogo)
    pezzi = {n.ref for n in out.geometry()}
    assert {"humanoid:upper_arm", "humanoid:forearm", "humanoid:hand",
            "humanoid:thigh", "humanoid:calf", "humanoid:foot"} <= pezzi
    assert out.node("braccio_l").mesh is None, "il braccio intero non si costruisce"
    assert out.node("torso").mesh is None, "e nemmeno il torso"


def test_at_high_detail_the_face_appears(catalogo):
    out = costruisci(figura(1.8, detail_level=3), catalogo)
    pezzi = {n.ref for n in out.geometry()}
    assert {"humanoid:eye", "humanoid:nose", "humanoid:mouth", "humanoid:ear",
            "humanoid:hair"} <= pezzi


def test_the_humanoid_respects_the_low_poly_style(catalogo):
    out = costruisci(figura(1.8), catalogo)
    assert "STYLE_QUALITY" not in out.report.codes(), out.report.describe()


# --------------------------------------------------------------------------- #
# Banco 2: casa e pianeta
# --------------------------------------------------------------------------- #
def test_a_house_stands_on_a_planet(catalogo):
    out = costruisci(casa_su_pianeta(), catalogo)
    assert not gravi(out), out.report.describe()
    assert {"architecture:house", "architecture:roof", "architecture:door",
            "space:planet"} <= {n.ref for n in out.geometry()}


def test_the_house_and_the_planet_go_through_the_same_code(catalogo):
    """Nessuna specializzazione: due domini, una sola pipeline."""
    umano = costruisci(figura(1.8), catalogo)
    mondo = costruisci(casa_su_pianeta(), catalogo)
    assert type(umano) is type(mondo)
    assert not gravi(umano) and not gravi(mondo)


def test_the_planet_is_enormous_and_nothing_complains(catalogo):
    """Quattro metri di casa su ottanta di pianeta: e' solo una superficie grande."""
    out = costruisci(casa_su_pianeta(raggio=80.0), catalogo)
    assert not gravi(out), out.report.describe()
    assert out.size.max() > 100.0


def test_the_house_opens_its_windows_only_at_high_detail(catalogo):
    g = casa_su_pianeta()
    g.detail_level = 3
    dettagliata = costruisci(g, catalogo)
    assert len([n for n in dettagliata.geometry()
                if n.ref == "architecture:window"]) == 2
    assert not [n for n in costruisci(casa_su_pianeta(), catalogo).geometry()
                if n.ref == "architecture:window"]


# --------------------------------------------------------------------------- #
# Banco 3: il mostro
# --------------------------------------------------------------------------- #
def mostro(detail_level: int = 3) -> CompositionGraph:
    """Testa di rana con capelli e casco, corpo di pesce, gambe di spada, ali.

    Quattro vocabolari diversi, piu' gli accessori, piu' un piercing sul naso
    che la testa di rana non ha nemmeno: lo prende dal muso, perche' quello che
    conta e' la capability.
    """
    g = figura(1.8, detail_level=detail_level)
    g.swap("testa", "creature:frog_head")
    g.swap("torso", "fish:fish_body")
    for gamba in ("gamba_l", "gamba_r"):
        g.swap(gamba, "weapon:sword", scale_mode="fit_replaced")
    g.attach("capelli", "humanoid:hair", "testa", requirement=chiedi("hair_mount"),
             scale_mode="socket", insert=0.45)
    g.attach("casco", "accessories:helmet", "capelli",
             requirement=chiedi("gear_mount"), scale_mode="socket", insert=0.3)
    g.attach("visiera", "accessories:visor", "casco",
             requirement=chiedi("visor_mount"), scale_mode="socket")
    g.attach("piercing", "accessories:piercing", "testa",
             requirement=chiedi("anchor"), scale_mode="socket")
    g.attach("ala", "fish:fin", "torso", scale_mode="socket",
             requirement=chiedi("gear_mount"))
    return g


def test_the_monster_is_built_from_four_vocabularies(catalogo):
    out = costruisci(mostro(), catalogo)
    assert not gravi(out), out.report.describe()
    plugin = {n.metadata["plugin"] for n in out.geometry()}
    assert {"humanoid", "creature", "fish", "weapon", "accessories"} <= plugin


def test_the_monster_keeps_every_swapped_part_and_no_ghost(catalogo):
    out = costruisci(mostro(), catalogo)
    usati = {n.ref for n in out.walk()}
    assert "creature:frog_head" in usati and "humanoid:head" not in usati
    assert "fish:fish_body" in usati and "humanoid:torso" not in usati
    assert "weapon:sword" in usati and "humanoid:leg" not in usati


def test_the_accessories_nest_four_deep(catalogo):
    """testa -> capelli -> casco -> visiera, senza una riga per le decorazioni."""
    out = costruisci(mostro(), catalogo)
    catena = []
    corrente = out.node("visiera")
    while corrente is not None:
        catena.append(corrente.ref)
        corrente = out.node(corrente.parent) if corrente.parent else None
    assert catena[:4] == ["accessories:visor", "accessories:helmet",
                          "humanoid:hair", "creature:frog_head"]


def test_the_monster_holds_together(catalogo):
    out = costruisci(mostro(), catalogo)
    assert "JOINT_GAP" not in out.report.codes(), out.report.describe()


def test_the_monster_is_deterministic(catalogo):
    atteso = costruisci(mostro(), catalogo)
    for _ in range(2):
        altro = costruisci(mostro(), catalogo)
        assert [n.id for n in altro.walk()] == [n.id for n in atteso.walk()]
        assert np.allclose(altro.combined().vertices, atteso.combined().vertices)


# --------------------------------------------------------------------------- #
# La terza modalita' di scala
# --------------------------------------------------------------------------- #
def _gamba_di_spada(catalogo, modo: str):
    g = figura(1.8)
    g.swap("gamba_l", "weapon:sword", scale_mode=modo)
    out = costruisci(g, catalogo, effetti=False)
    spada, gamba = out.node("gamba_l"), out.node("gamba_r")
    return (float(np.max(spada.mesh.bounds[1] - spada.mesh.bounds[0]))
            / float(np.max(gamba.mesh.bounds[1] - gamba.mesh.bounds[0])))


def test_the_three_scale_modes_do_three_different_things(catalogo):
    """Il caso che ha reso necessaria la terza modalita'.

        none           la spada resta lunga quanto una spada: gambe sbilenche
        socket         si porta al raggio dell'anca: diventa lunga quattro volte
        fit_replaced   sta grande come la gamba che sostituisce
    """
    assert _gamba_di_spada(catalogo, "none") < 0.85
    assert _gamba_di_spada(catalogo, "socket") > 2.0
    assert _gamba_di_spada(catalogo, "fit_replaced") == pytest.approx(1.0, abs=0.08)


def test_fit_replaced_without_a_replaced_component_changes_nothing(catalogo):
    """Non c'e' niente da eguagliare: si tengono le proprie misure, e si dice."""
    g = figura(1.8)
    g.add_child("in_mano", "weapon:sword", "braccio_l",
                requirement=chiedi("limb_mount"), scale_mode="fit_replaced")
    out = costruisci(g, catalogo, effetti=False)
    assert out.node("in_mano").placement.scale == pytest.approx(1.0)


# --------------------------------------------------------------------------- #
# Effetti sulla geometria vera
# --------------------------------------------------------------------------- #
def test_lanky_changes_the_shape_not_only_the_numbers(catalogo):
    g = figura(1.8)
    g.effect("lanky", scope="model", amount=1.0)

    magro = costruisci(g, catalogo)
    normale = costruisci(figura(1.8), catalogo)
    assert magro.size[1] > normale.size[1], "piu' alto"
    assert magro.node("torso").mesh.bounds[1][2] < \
        normale.node("torso").mesh.bounds[1][2], "e piu' stretto"
    assert magro.triangles == normale.triangles, "senza aggiungere un triangolo"


def test_bend_moves_the_vertices_of_one_part_only(catalogo):
    g = figura(1.8)
    g.effect("bend", scope="part:braccio_l", amount=0.9)

    piegato = costruisci(g, catalogo)
    dritto = costruisci(figura(1.8), catalogo)
    assert not np.allclose(piegato.node("braccio_l").mesh.vertices,
                           dritto.node("braccio_l").mesh.vertices)
    assert np.allclose(piegato.node("braccio_r").mesh.vertices,
                       dritto.node("braccio_r").mesh.vertices)


def test_perspective_exaggeration_reaches_the_whole_model(catalogo):
    g = figura(1.8)
    g.effect("perspective_exaggeration", scope="model", amount=0.8)

    esagerato = costruisci(g, catalogo)
    normale = costruisci(figura(1.8), catalogo)
    diversi = [n.id for n in esagerato.geometry()
               if not np.allclose(n.mesh.vertices, normale.node(n.id).mesh.vertices)]
    assert len(diversi) == len(esagerato.geometry())


def test_the_three_effects_together_on_the_real_monster(catalogo):
    """Il caso completo: quattro vocabolari e i tre effetti insieme."""
    g = mostro()
    g.effect("lanky", scope="model", amount=0.9)
    g.effect("bend", scope="role:lama", amount=0.4)
    g.effect("perspective_exaggeration", scope="model", amount=0.3)

    out = costruisci(g, catalogo)
    senza = costruisci(mostro(), catalogo)

    assert not gravi(out), out.report.describe()
    assert out.triangles == senza.triangles, "le deformazioni non aggiungono facce"
    assert out.size[1] > senza.size[1], "lanky ha allungato la figura"
    assert np.all(np.isfinite(out.bounds))


# --------------------------------------------------------------------------- #
# Deformazione e socket, su geometria vera
# --------------------------------------------------------------------------- #
def coda_con_anello(piega: float = 0.0) -> CompositionGraph:
    g = CompositionGraph(detail_level=2)
    g.set_root("coda", "fish:tail")
    g.attach("anello", "accessories:piercing", "coda",
             requirement=chiedi("anchor"), scale_mode="socket")
    if piega:
        g.effect("bend", scope="part:coda", amount=piega)
    return g


def test_a_child_follows_the_socket_of_a_bent_parent(catalogo):
    """Il caso che il passo 6 poteva solo simulare: una coda piegata con sopra
    qualcosa.

    Se il socket non seguisse la deformazione, il figlio resterebbe dove la coda
    stava prima di piegarsi — e nel modello si vedrebbe un pezzo per aria.
    """
    piegata = costruisci(coda_con_anello(1.0), catalogo)
    assert not gravi(piegata), piegata.report.describe()
    assert "JOINT_GAP" not in piegata.report.codes()

    # l'anello sta **sulla punta deformata**, non dove la punta stava prima
    punta = piegata.node("coda").socket_world("punta")
    base = piegata.node("anello").socket_world("base")
    scarto = float(np.linalg.norm(punta.position - base.position))
    assert scarto < punta.radius * 1.2, "il giunto e' quello, meno l'incastro"


def test_bending_the_parent_actually_moves_the_child(catalogo):
    dritta = costruisci(coda_con_anello(), catalogo)
    piegata = costruisci(coda_con_anello(1.0), catalogo)

    assert not np.allclose(piegata.node("anello").mesh.bounds,
                           dritta.node("anello").mesh.bounds), \
        "il figlio si e' spostato con il socket, non e' rimasto indietro"


# --------------------------------------------------------------------------- #
# Compenetrazione
# --------------------------------------------------------------------------- #
def test_the_expected_overlap_of_a_joint_is_not_a_defect(catalogo):
    """Un braccio entra nella spalla apposta: senza, si vedrebbe la fessura."""
    out = costruisci(figura(1.8), catalogo)
    assert "PARTS_INTERPENETRATE" not in out.report.codes(), out.report.describe()
    assert "PART_SUBMERGED" not in out.report.codes()


def test_a_swallowed_part_is_reported(catalogo):
    """Un braccio spinto dentro la spalla dieci volte piu' del dovuto.

    L'innesto prevedeva `raggio x insert` di compenetrazione. Con un `insert`
    dieci volte tanto il braccio finisce dentro il torace, e la misura lo dice
    proprio perche' sa quanta sovrapposizione era prevista.
    """
    g = figura(1.8)
    g.add_child("braccio_dentro", "humanoid:arm", "torso", insert=40.0,
                requirement=chiedi("limb_mount", side="l", tags=ALTO))

    out = costruisci(g, catalogo, effetti=False)
    assert "PART_SUBMERGED" in out.report.codes(), out.report.describe()


def test_the_overlap_thresholds_can_be_tightened_by_the_style(catalogo):
    from app.core.vocabulary import StyleProfile

    out = build(resolve(figura(1.8), catalogo))
    severo = StyleProfile(id="prova:severo",
                          params={"max_submersion": 0.0, "max_overlap": 0.0})
    validate(out, style=severo)
    assert "PART_SUBMERGED" in out.report.codes()


# --------------------------------------------------------------------------- #
# Terze parti, con geometria vera
# --------------------------------------------------------------------------- #
def test_a_third_party_plugin_builds_next_to_the_real_ones():
    """Nessuna modifica al core: il plugin esterno passa dalla stessa pipeline."""
    reg = load([PLUGIN, TERZE_PARTI])
    assert not reg.report.errors(), reg.report.describe()

    g = CompositionGraph(detail_level=3)
    g.set_root("blob", "external_test_plugin:quantum_blob")
    out = build(apply_effects(resolve(g, reg), reg))
    validate(out, style=reg.style("low_poly"))

    assert not gravi(out), out.report.describe()
    assert out.triangles > 0
    assert out.node("blob/cristallo") is not None


def test_a_third_party_component_is_refused_where_it_does_not_fit():
    """Un blob quantistico al posto di una testa: non fornisce `head_mount`.

    Il rifiuto **e'** la risposta giusta, e arriva con l'elenco di chi quella
    capability la fornisce davvero. Il core non sa cosa sia un blob quantistico
    ne' cosa sia una testa: sa leggere due contratti e vedere che non combaciano.
    """
    reg = load([PLUGIN, TERZE_PARTI])
    g = figura(1.8)
    g.swap("testa", "external_test_plugin:quantum_blob", scale_mode="socket")

    out = build(resolve(g, reg))
    codici = out.report.codes()
    assert "PROVIDER_INCOMPATIBLE" in codici
    voce = [d for d in out.report if d.code == "PROVIDER_INCOMPATIBLE"][0]
    assert "creature:frog_head" in voce.alternatives


def test_a_third_party_component_fits_where_its_contract_matches():
    """Lo stesso blob su un innesto che accetta cio' che fornisce."""
    reg = load([PLUGIN, TERZE_PARTI])
    g = CompositionGraph(detail_level=2)
    g.set_root("blob", "external_test_plugin:quantum_blob")
    g.attach("anello", "accessories:piercing", "blob",
             requirement=chiedi("resonance_mount"), scale_mode="socket")

    out = build(resolve(g, reg))
    validate(out)
    assert out.node("blob").triangles > 0


# --------------------------------------------------------------------------- #
# La convenzione, per chi scrive un plugin
# --------------------------------------------------------------------------- #
def test_every_installed_component_declares_a_base_socket(catalogo):
    """Senza `base` un pezzo non sa posarsi: e' il minimo del contratto."""
    from app.core.component import BuildContext
    from app.core.params import resolve as resolve_params

    mancanti = []
    for componente in catalogo.components():
        pezzo = componente.build(resolve_params(componente.params), BuildContext())
        if "base" not in pezzo.sockets:
            mancanti.append(componente.id)
    assert not mancanti, "senza socket 'base': %s" % ", ".join(mancanti)


def test_every_installed_component_has_finite_sockets(catalogo):
    from app.core.component import BuildContext
    from app.core.params import resolve as resolve_params

    for componente in catalogo.components():
        pezzo = componente.build(resolve_params(componente.params), BuildContext())
        for nome, s in pezzo.sockets.items():
            assert np.all(np.isfinite(s.position)), (componente.id, nome)
            assert float(np.linalg.norm(s.direction)) > 1e-6, (componente.id, nome)


def test_the_authoring_helper_catches_a_reversed_component():
    """L'aiuto per chi scrive plugin: dice cosa non torna, guardando la geometria."""
    from app.core.authoring import verify_frame
    from app.core.component import Piece
    from app.core.socket import socket
    from app.geometry.kernel import grow

    mesh = grow([(0.0, 0.1), (1.0, 0.1)], sides=6, length=1.0, axis=0)
    storto = Piece(mesh=mesh, sockets={
        "base": socket("base", (0, 0, 0), (1, 0, 0))})     # guarda in avanti
    report = verify_frame(storto, "+X", name="prova")
    assert "BASE_SOCKET_REVERSED" in report.codes()

    giusto = Piece(mesh=mesh, sockets={
        "base": socket("base", (0, 0, 0), (-1, 0, 0))})
    assert verify_frame(giusto, "+X", name="prova").ok


def test_the_authoring_helper_accepts_every_real_component(catalogo):
    """Cio' che e' installato rispetta la convenzione che il documento descrive."""
    from app.core.authoring import growth_axis, verify_frame
    from app.core.component import BuildContext
    from app.core.params import resolve as resolve_params

    for componente in catalogo.components():
        pezzo = componente.build(resolve_params(componente.params), BuildContext())
        base = pezzo.sockets.get("base")
        if pezzo.mesh is None or base is None:
            continue
        # l'asse dichiarato e' l'opposto del verso del socket di base: e' la
        # dichiarazione, e il verificatore controlla che la geometria la rispetti
        asse = _asse_dal_socket(base)
        report = verify_frame(pezzo, asse, name=componente.id)
        assert report.ok, "%s (%s): %s" % (componente.id, asse, report.describe())


def _asse_dal_socket(base) -> str:
    crescita = -np.asarray(base.direction, dtype=float)
    indice = int(np.argmax(np.abs(crescita)))
    return "%s%s" % ("+" if crescita[indice] >= 0 else "-", "XYZ"[indice])


# --------------------------------------------------------------------------- #
# Silhouette
# --------------------------------------------------------------------------- #
def test_a_figure_leaves_gaps_and_a_box_does_not(catalogo):
    """La misura che distingue una figura da una massa.

    Braccia e gambe lasciano vuoti nella sagoma; un cubo riempie la propria
    scatola. Non e' un giudizio — una casa e' legittimamente una scatola — ma e'
    un numero che dice se una forma si legge da lontano.
    """
    from app.build.validate import silhouette_fill

    figura_piena = silhouette_fill(costruisci(figura(1.8, detail_level=3),
                                              catalogo))
    g = CompositionGraph()
    g.set_root("cubo", "primitives:block", length=1.0, height=1.0, width=1.0)
    cubo = silhouette_fill(costruisci(g, catalogo, effetti=False))

    assert cubo > 0.98, "un cubo riempie tutto"
    assert figura_piena < 0.80, "una figura no"


def test_the_silhouette_check_runs_only_if_the_style_asks(catalogo):
    """Imporlo a tutti vorrebbe dire vietare i cubi."""
    from app.core.vocabulary import StyleProfile

    g = CompositionGraph()
    g.set_root("cubo", "primitives:block", length=1.0, height=1.0, width=1.0)
    out = build(resolve(g, catalogo))

    validate(out, style=catalogo.style("low_poly"))
    assert "STYLE_QUALITY" not in out.report.codes(), "il low poly non lo chiede"

    esigente = StyleProfile(id="prova:esigente",
                            params={"silhouette_max_fill": 0.5})
    validate(out, style=esigente)
    assert "STYLE_QUALITY" in out.report.codes()


def test_the_silhouette_is_deterministic(catalogo):
    from app.build.validate import silhouette_fill

    misure = {round(silhouette_fill(costruisci(figura(1.8), catalogo)), 6)
              for _ in range(3)}
    assert len(misure) == 1


# --------------------------------------------------------------------------- #
# Accessori: componenti normali, non una classe a parte
# --------------------------------------------------------------------------- #
def test_a_mask_goes_on_a_face(catalogo):
    """`Testa -> Mascherina`, con un attacco facoltativo e su richiesta."""
    g = figura(1.8)
    g.attach("mascherina", "accessories:mask", "testa",
             requirement=chiedi("face_mount"), scale_mode="socket")

    out = costruisci(g, catalogo)
    assert not gravi(out), out.report.describe()
    assert out.node("mascherina").triangles > 0
    assert out.node("mascherina").parent == "testa"


def test_a_piercing_goes_on_a_nose_at_the_lowest_detail(catalogo):
    """`Testa -> Naso -> Piercing` con `detail_level = 1`.

    Il naso normalmente compare solo al livello 3. Qui il piano lo nomina, e
    nominarlo apre un corridoio: la testa e il naso entrano perche' il piercing
    e' stato chiesto, senza che il resto del volto si espanda. Il naso del piano
    prende anche il posto di quello che la testa dichiarerebbe da se': il piano
    vince sulla dichiarazione.
    """
    g = figura(1.8, detail_level=1)
    g.add_child("naso", "humanoid:nose", "testa", level=3,
                requirement=chiedi("face_mount", tags=("naso",)))
    g.attach("anellino", "accessories:piercing", "naso",
             requirement=chiedi("anchor"), scale_mode="socket")

    out = costruisci(g, catalogo)
    assert not gravi(out), out.report.describe()
    assert out.node("anellino").triangles > 0
    assert out.node("naso") is not None
    assert out.node("testa/naso") is None, "non ce ne sono due"
    assert not [n for n in out.geometry() if n.ref == "humanoid:eye"],         "il resto del volto non si e' espanso"


def test_an_accessory_is_an_ordinary_component(catalogo):
    """Nessuna classe `Decoration`: e' l'attacco a farne un accessorio."""
    from app.core.component import Component

    for id in ("accessories:mask", "accessories:helmet", "accessories:visor",
               "accessories:piercing"):
        assert isinstance(catalogo.component(id), Component)


# --------------------------------------------------------------------------- #
# Posa: cio' che due vocabolari compatibili non possono concordare da soli
# --------------------------------------------------------------------------- #
def _figura_con_corpo_di_pesce(effetto: bool = False) -> CompositionGraph:
    g = figura(1.8)
    g.swap("torso", "fish:fish_body")
    if effetto:
        g.effect("align", scope="role:arm", direction="down")
    return g


def _larghezza(out, id: str) -> float:
    punti = np.asarray(out.node(id).mesh.vertices, dtype=float)
    return float(punti[:, 0].max() - punti[:, 0].min())


def test_arms_on_a_fish_body_come_out_sideways(catalogo):
    """Il difetto, misurato prima di correggerlo.

    Le pinne pettorali di un pesce puntano di lato, e un braccio umano
    innestato li' esce orizzontale. Non e' un errore di nessuno dei due
    plugin: e' che una posa non e' una capability.
    """
    out = costruisci(_figura_con_corpo_di_pesce(), catalogo)
    assert not gravi(out), out.report.describe()
    assert _larghezza(out, "braccio_l") > 0.5, "il braccio si sviluppa in larghezza"


def test_arms_on_a_fish_body_can_be_pointed_down_without_touching_the_plugin(catalogo):
    """«Orienta le braccia verso il basso», e nessun plugin cambia."""
    prima = costruisci(_figura_con_corpo_di_pesce(), catalogo)
    dopo = costruisci(_figura_con_corpo_di_pesce(effetto=True), catalogo)

    assert not gravi(dopo), dopo.report.describe()
    assert _larghezza(dopo, "braccio_l") < _larghezza(prima, "braccio_l") * 0.4
    # il modello resta largo quanto le gambe, che nessuno ha chiesto di girare:
    # un effetto fa quello che gli si chiede e non un dito di piu'
    assert dopo.size[0] < prima.size[0] * 0.85, "il modello non e' piu' largo cosi'"
    assert dopo.triangles == prima.triangles, "una posa non aggiunge geometria"


def test_a_pose_turns_each_group_around_its_own_joint(catalogo):
    """Due braccia, due perni: girarle attorno a uno solo ne farebbe volare via uno."""
    out = costruisci(_figura_con_corpo_di_pesce(effetto=True), catalogo)
    sinistro = np.asarray(out.node("braccio_l").mesh.vertices, dtype=float)
    destro = np.asarray(out.node("braccio_r").mesh.vertices, dtype=float)
    assert sinistro[:, 0].mean() < 0 < destro[:, 0].mean(), "restano ognuno dal suo lato"
    assert abs(sinistro[:, 0].mean() + destro[:, 0].mean()) < 0.02, "simmetrici"


def test_a_pose_carries_the_whole_subtree_with_it(catalogo):
    """Un braccio ruotato porta con se' omero, avambraccio e mano.

    E' il motivo per cui una posa e' una mappa di punti come le altre: la
    stessa funzione muove i vertici e i socket, e i pezzi non si separano.
    """
    piano = figura(1.8, detail_level=3)
    fermo = costruisci(piano, catalogo)
    piano_mosso = figura(1.8, detail_level=3)
    piano_mosso.effect("rotate", scope="subtree:braccio_l", axis="Z", angle=40.0)
    mosso = costruisci(piano_mosso, catalogo)

    assert not gravi(mosso), mosso.report.describe()
    for id in ("braccio_l/omero", "braccio_l/avambraccio", "braccio_l/mano"):
        a = np.asarray(fermo.node(id).mesh.vertices, dtype=float).mean(axis=0)
        b = np.asarray(mosso.node(id).mesh.vertices, dtype=float).mean(axis=0)
        assert float(np.linalg.norm(b - a)) > 1e-4, "%s non si e' mosso" % id
    fermo_r = np.asarray(fermo.node("braccio_r/mano").mesh.vertices,
                         dtype=float).mean(axis=0)
    mosso_r = np.asarray(mosso.node("braccio_r/mano").mesh.vertices,
                         dtype=float).mean(axis=0)
    assert np.allclose(fermo_r, mosso_r), "l'altro braccio non c'entra"


def test_a_rotated_limb_stays_attached_to_its_joint(catalogo):
    """Ruotare attorno all'innesto, non attorno all'origine."""
    piano = figura(1.8)
    piano.effect("rotate", scope="subtree:braccio_l", axis="Z", angle=60.0)
    out = costruisci(piano, catalogo)
    assert "JOINT_GAP" not in out.report.codes(), out.report.describe()


def test_a_pose_is_reproducible(catalogo):
    misure = {tuple(np.round(costruisci(_figura_con_corpo_di_pesce(effetto=True),
                                        catalogo).size, 6)) for _ in range(3)}
    assert len(misure) == 1


def test_offset_and_mirror_move_a_group_without_deforming_it(catalogo):
    """Trasla e specchia: rigide, e si vede — la taglia del pezzo non cambia."""
    for effetto, extra in (("offset", {"axis": "Y", "distance": 0.3}),
                           ("mirror", {"axis": "X"})):
        piano = figura(1.8)
        piano.effect(effetto, scope="subtree:braccio_l", **extra)
        out = costruisci(piano, catalogo)
        assert not gravi(out), out.report.describe()
        fermo = costruisci(figura(1.8), catalogo)
        a = np.asarray(fermo.node("braccio_l").mesh.vertices, dtype=float)
        b = np.asarray(out.node("braccio_l").mesh.vertices, dtype=float)
        assert np.allclose(np.sort(a.max(axis=0) - a.min(axis=0)),
                           np.sort(b.max(axis=0) - b.min(axis=0)), atol=1e-6)


def test_the_same_pose_works_on_another_vocabulary(catalogo):
    """`align` non sa cosa sia un braccio: sa dove un gruppo e' appeso.

    La prova non e' leggere il codice: e' che la stessa identica richiesta
    orienti la coda di un pesce, che non ha spalle, non ha ruoli anatomici e
    non e' mai stata pensata insieme a un braccio.
    """
    def coda(effetto: bool) -> CompositionGraph:
        g = CompositionGraph()
        g.set_root("pesce", "fish:fish_body")
        g.add_child("pinna", "fish:fin", "pesce", requirement=chiedi("limb_mount"))
        if effetto:
            g.effect("align", scope="subtree:pinna", direction="up")
        return g

    ferma = costruisci(coda(False), catalogo)
    mossa = costruisci(coda(True), catalogo)
    assert not gravi(mossa), mossa.report.describe()
    a = np.asarray(ferma.node("pinna").mesh.vertices, dtype=float)
    b = np.asarray(mossa.node("pinna").mesh.vertices, dtype=float)
    assert b[:, 1].max() > a[:, 1].max() + 1e-3, "la pinna adesso punta in su"
    assert mossa.triangles == ferma.triangles
