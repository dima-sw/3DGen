"""Il kernel poligonale e il plugin come vocabolario.

Il criterio che regge tutto e' `faces_per_normal`: dice se una mesh e' stata
**disegnata** (quadrilateri piani, due o piu' facce per direzione di normale) o
**campionata** da un campo implicito (una normale per faccia, cioe' una bolla).
La pipeline da cui si veniva stava a 1,05.

Questo file era scritto contro il primo sistema a plugin — `app.plugins.base`,
`app.plugins.build`, `app.plugins.humanoid` — che il core nuovo ha sostituito.
Le domande sono rimaste tutte, una per una; a cambiare e' cio' a cui vengono
poste. Dove la risposta del sistema nuovo e' **diversa**, e non solo scritta
diversamente, il test lo dice.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import trimesh

from app.build.assembler import build
from app.core.capability import Requirement
from app.core.effect import apply_effects
from app.core.graph import FROM_EFFECT, CompositionGraph
from app.core.params import resolve as resolve_params
from app.core.registry import Registry, load
from app.core.resolver import resolve
from app.geometry.kernel import block, faces_per_normal, grow, ring, sweep

PLUGIN = Path(__file__).resolve().parent.parent / "app" / "plugins"


@pytest.fixture(scope="module")
def catalogo() -> Registry:
    r = load([PLUGIN])
    assert not r.report.errors(), r.report.describe()
    return r.freeze()


def chiedi(capability: str = "", **kwargs) -> Requirement:
    return Requirement(capability=capability, **kwargs)


def figura(catalogo, *, height: float = 1.8, detail_level: int = 2,
           effetto: str = "") -> CompositionGraph:
    """Il piano di una figura, con le parti dichiarate dal livello 1.

    Il livello dell'attacco e' del **piano**, non del componente: chi compone
    dice quando una parte compare, e qui si vuole poter guardare tutti e tre i
    livelli di dettaglio dello stesso corpo.
    """
    g = CompositionGraph(detail_level=detail_level)
    g.set_root("corpo", "humanoid:body", height=height)
    g.add_child("torso", "humanoid:torso", "corpo", level=1,
                requirement=chiedi("core_mount"))
    g.add_child("collo", "humanoid:neck", "torso", level=1, insert=0.3,
                requirement=chiedi("head_mount"))
    g.add_child("testa", "humanoid:head", "collo", level=1, insert=0.25,
                requirement=chiedi("head_mount"))
    for nome, lato in (("braccio_l", "l"), ("braccio_r", "r")):
        g.add_child(nome, "humanoid:arm", "torso", level=1, insert=1.15,
                    requirement=chiedi("limb_mount", side=lato,
                                       tags=frozenset({"alto"})))
    for nome, lato in (("gamba_l", "l"), ("gamba_r", "r")):
        g.add_child(nome, "humanoid:leg", "torso", level=1, insert=0.9,
                    requirement=chiedi("limb_mount", side=lato,
                                       tags=frozenset({"basso"})))
    if effetto:
        g.effect(effetto, scope="model")
    return g


def costruisci(catalogo, **kwargs):
    piano = figura(catalogo, **kwargs)
    return build(apply_effects(resolve(piano, catalogo), catalogo))


def disegnata(out) -> trimesh.Trimesh:
    """La geometria com'era prima di ogni effetto.

    La planarita' va misurata li': un pezzo piegato ha legittimamente una
    normale per faccia, e misurarlo dopo direbbe che il disegno e' peggiorato
    quando invece e' stato deformato apposta.
    """
    pezzi = [n.designed for n in out.walk()
             if n.designed is not None and len(n.designed.vertices)]
    return trimesh.util.concatenate(pezzi)


# --------------------------------------------------------------------------- #
# Il kernel
# --------------------------------------------------------------------------- #
def test_a_ring_has_the_vertices_it_says():
    assert len(ring(6, 0.0, 0.2, 0.2)) == 6
    assert len(ring(12, 0.0, 0.2, 0.1)) == 12


def test_a_sweep_is_closed_and_predictable():
    """Il conto dei poligoni si sa in partenza: e' meta' del valore del kernel."""
    anelli = [ring(6, y, 0.2, 0.2) for y in (0.0, 0.5, 1.0)]
    mesh = sweep(anelli)
    assert mesh.is_watertight
    # 2 fasce x 6 lati x 2 triangoli + due tappi da 4 triangoli
    assert len(mesh.faces) == 2 * 6 * 2 + 2 * 4


def test_swept_quads_are_flat():
    """La prova del nove del disegnato: due facce per direzione di normale."""
    mesh = grow([(0.0, 0.2), (0.5, 0.25), (1.0, 0.15)], sides=6, length=1.0)
    assert faces_per_normal(mesh) >= 2.0


def test_an_elliptical_section_stays_flat():
    """Anelli circolari piu' scala affine: e' cio' che salva la planarita'.

    Costruendo direttamente anelli ellittici i quadrilateri del fianco non sono
    piani e si torna a una normale per faccia, cioe' a una bolla.
    """
    stazioni = [(0.0, 0.2), (0.5, 0.25), (1.0, 0.15)]
    tonda = grow(stazioni, sides=6, length=1.0)
    schiacciata = grow(stazioni, sides=6, length=1.0, flat=0.5)

    assert faces_per_normal(schiacciata) >= 2.0
    # Un esagono ha i vertici su un asse e le facce sull'altro, quindi le due
    # trasversali non misurano uguale: il confronto va fatto con se stessa.
    assert schiacciata.extents[2] == pytest.approx(tonda.extents[2] * 0.5, rel=1e-3)
    assert schiacciata.extents[1] == pytest.approx(tonda.extents[1], rel=1e-3)


def test_a_block_is_a_box():
    mesh = block((0.2, 0.3, 0.15), sides=4, squash=1.0)
    assert mesh.is_watertight
    assert len(mesh.faces) == 12, "sei facce, due triangoli l'una"
    assert faces_per_normal(mesh) == pytest.approx(2.0)
    assert np.allclose(mesh.extents, [0.2, 0.3, 0.15], atol=1e-6)


def test_rings_must_agree_on_the_vertex_count():
    with pytest.raises(ValueError, match="stesso numero"):
        sweep([ring(6, 0.0, 0.2, 0.2), ring(8, 1.0, 0.2, 0.2)])


# --------------------------------------------------------------------------- #
# Il plugin come vocabolario
# --------------------------------------------------------------------------- #
def test_the_plugin_is_a_vocabulary_not_a_catalogue(catalogo):
    """Parti componibili, non modelli preconfezionati."""
    nomi = {c.name for c in catalogo.components(plugin="humanoid")}
    assert {"body", "torso", "head", "arm", "leg", "hand", "foot", "eye",
            "hair"} <= nomi
    assert not ({"soldato", "mago", "eroe", "personaggio"} & nomi)


def test_every_rule_declares_its_parameters(catalogo):
    """Un parametro numerico deve stare dentro i propri limiti gia' da fermo."""
    for componente in catalogo.components():
        for chiave, spec in componente.params.items():
            if not isinstance(spec.default, (int, float)) \
                    or spec.min is None or spec.max is None:
                continue
            assert spec.min <= spec.default <= spec.max, \
                "%s.%s" % (componente.id, chiave)


def test_parameters_are_clamped_not_trusted(catalogo):
    """Il piano puo' chiedere qualunque numero; il componente decide il suo.

    La casa e non la testa, perche' le misure della testa sono **derivate**
    dall'altezza della figura: li' il numero del piano viene ricalcolato, che
    e' una regola diversa da questa e ha i suoi test.
    """
    casa = catalogo.component("architecture:house")
    valori = resolve_params(casa.params,
                            {"width": 9e3, "depth": -5.0, "inventato": 1.0})
    assert valori["width"] == casa.params["width"].max
    assert valori["depth"] == casa.params["depth"].min
    assert "inventato" not in valori


# --------------------------------------------------------------------------- #
# Livelli di dettaglio
# --------------------------------------------------------------------------- #
def test_more_detail_means_more_parts(catalogo):
    conti = [len(costruisci(catalogo, detail_level=n).meshes()) for n in (1, 2, 3)]
    assert conti == sorted(conti) and conti[0] < conti[-1]


def test_expansion_replaces_the_parent(catalogo):
    """Al livello alto il torso **non esiste piu'**: al suo posto ci sono i pezzi.

    Se restasse, ci sarebbe geometria doppia dentro il petto e il conto dei
    triangoli crescerebbe per niente.
    """
    basso = {n.id for n in costruisci(catalogo, detail_level=2).geometry()}
    alto = {n.id for n in costruisci(catalogo, detail_level=3).geometry()}
    assert "torso" in basso
    assert "torso" not in alto, "il torso doveva essere sostituito"
    assert {"torso/bacino", "torso/petto"} <= alto
    assert "braccio_l" not in alto and "braccio_l/omero" in alto


def test_features_are_added_not_substituted(catalogo):
    """Occhi, naso e capelli si aggiungono alla testa: non la sostituiscono."""
    alto = {n.id for n in costruisci(catalogo, detail_level=3).geometry()}
    assert "testa" in alto
    assert {"testa/occhio_l", "testa/occhio_r", "testa/naso", "testa/bocca",
            "testa/capelli"} <= alto


def test_detail_does_not_explode_the_triangle_count(catalogo):
    """Il vantaggio del costruito: il conto si sa, e cresce piano."""
    triangoli = [costruisci(catalogo, detail_level=n).triangles for n in (1, 2, 3)]
    assert triangoli[0] < triangoli[-1]
    assert triangoli[-1] < triangoli[0] * 2.5, triangoli
    assert triangoli[-1] < 1500, "e' un low poly, non un modello denso"


# --------------------------------------------------------------------------- #
# Altezza
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("altezza", [0.9, 1.8, 3.2])
def test_height_is_exact_by_construction(catalogo, altezza):
    """Le regole lavorano in frazioni di uno: l'altezza non ha fattori di resa."""
    out = costruisci(catalogo, height=altezza)
    assert float(out.size[1]) == pytest.approx(altezza, rel=2e-3)


def test_height_is_exact_at_every_detail(catalogo):
    """A ogni livello, e con lo scarto che il dettaglio aggiunge davvero.

    Al livello alto i piedi e i capelli sporgono da cio' che il livello basso
    misurava: il modello e' alto un po' di piu', e non c'e' niente da
    correggere. Fingere che sia identico vorrebbe dire ritarare le frazioni
    finche' il numero torna — che e' l'errore da cui si veniva.
    """
    for livello in (1, 2, 3):
        alto = float(costruisci(catalogo, detail_level=livello).size[1])
        assert alto == pytest.approx(1.8, rel=0.03), (livello, alto)


def test_a_proportion_effect_changes_the_height_and_says_so(catalogo):
    """Differenza vera con il sistema vecchio, e voluta.

    Prima l'altezza veniva rinormalizzata dopo l'effetto: «alto 1,80» restava
    1,80 anche chiedendo di allungare tutto. Adesso un effetto che allunga
    allunga, e il modello e' piu' alto — perche' i parametri cambiati restano
    leggibili e nessuno li corregge di nascosto.
    """
    normale = costruisci(catalogo).size[1]
    magro = costruisci(catalogo, effetto="lanky")
    assert magro.size[1] > normale * 1.2
    valori = [n for n in magro.composition.walk()
              if any(v.source == FROM_EFFECT for v in n.sources.values())]
    assert valori, "il cambiamento e' scritto nella provenienza dei parametri"


def test_the_model_grows_from_its_own_origin(catalogo):
    """Il corpo cresce dall'origine, e le gambe scendono sotto.

    Il sistema vecchio spostava tutto perche' appoggiasse su y=0. Qui non lo fa
    nessuno: l'appoggio e' una **posa**, cioe' un effetto dello stadio `final`,
    e finche' non lo si chiede il modello resta dove i componenti l'hanno
    costruito. Il test fissa il fatto, cosi' se un giorno cambia si vede.
    """
    out = costruisci(catalogo)
    assert float(out.bounds[0][1]) < -0.5, "le gambe stanno sotto l'origine"
    assert float(out.bounds[1][1]) > 0.5


# --------------------------------------------------------------------------- #
# Effetti
# --------------------------------------------------------------------------- #
def test_an_effect_is_applied_once_per_role(catalogo):
    """La regressione che ha sfasciato il chibi.

    Il braccio veniva accorciato, e poi veniva accorciato di nuovo l'omero
    dentro un braccio gia' corto: i pezzi non arrivavano piu' dove il genitore
    li aspettava e il modello si apriva in una pila di scatole.
    """
    out = costruisci(catalogo, detail_level=3, effetto="lanky")
    toccati = [n.id for n in out.composition.walk()
               if n.component.role == "arm"
               and any(v.source == FROM_EFFECT for v in n.sources.values())]
    assert toccati == ["braccio_l", "braccio_r"], toccati


def test_limb_segments_share_the_role_of_the_whole_limb(catalogo):
    """Omero e avambraccio non hanno un ruolo proprio: e' quello dell'arto."""
    for nome in ("upper_arm", "forearm"):
        assert catalogo.component("humanoid:%s" % nome).role == "arm", nome
    for nome in ("thigh", "calf"):
        assert catalogo.component("humanoid:%s" % nome).role == "leg", nome


@pytest.mark.parametrize("effetto", ["lanky", "chunky"])
def test_no_effect_breaks_the_model_apart(catalogo, effetto):
    """Nessun giunto si apre: un effetto non puo' smontare il corpo.

    Il sistema vecchio lo chiedeva confrontando gli ingombri di tutti i pezzi a
    coppie, e con un braccio in diagonale rispondeva "staccato" a un braccio
    attaccatissimo. La domanda giusta e' quella che sa dove sono gli innesti:
    un giunto e' aperto se il figlio non arriva al socket del padre, e questo
    lo misura il validatore.
    """
    from app.build.validate import validate

    out = costruisci(catalogo, detail_level=3, effetto=effetto)
    assert len(out.meshes()) >= 20
    referto = validate(out, style=catalogo.style("low_poly"))
    assert "JOINT_GAP" not in referto.codes(), referto.describe()


def test_effects_actually_change_the_proportions(catalogo):
    """Se un effetto non si vede, non e' un effetto."""
    def forma(effetto: str) -> float:
        misure = costruisci(catalogo, effetto=effetto).size
        return float(misure[0] / misure[1])          # larghezza su altezza

    normale = forma("")
    assert forma("lanky") < normale * 0.95, "il magro deve venire piu' stretto"
    assert forma("chunky") > normale * 1.15, "il tozzo deve venire piu' largo"


def test_an_unknown_effect_is_reported_and_the_model_is_built_anyway(catalogo):
    """Un effetto che non esiste non fa fallire una generazione."""
    out = costruisci(catalogo, effetto="pizza_margherita")
    assert "EFFECT_NOT_FOUND" in out.report.codes()
    assert out.meshes(), "il modello c'e' lo stesso"


# --------------------------------------------------------------------------- #
# Il criterio: disegnato, non campionato
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("livello", [1, 2, 3])
def test_the_model_is_designed_not_sampled(catalogo, livello):
    """Sotto 1,55 facce per normale non e' low poly, e' una bolla decimata."""
    mesh = disegnata(costruisci(catalogo, detail_level=livello))
    assert faces_per_normal(mesh) >= 1.8, faces_per_normal(mesh)


def test_it_beats_the_sampled_pipeline_by_a_wide_margin(catalogo):
    """Il confronto con cio' da cui si veniva: 1,05 facce per normale."""
    assert faces_per_normal(disegnata(costruisci(catalogo, detail_level=3))) > 2.0


def test_every_piece_is_closed(catalogo):
    """Pezzi separati, ma ognuno un solido: serve all'export e alla stampa."""
    out = costruisci(catalogo, detail_level=3)
    aperti = [n.id for n in out.geometry()
              if len(n.mesh.vertices) and not n.mesh.is_watertight]
    assert not aperti, aperti


# --------------------------------------------------------------------------- #
# Innesti dichiarati
# --------------------------------------------------------------------------- #
def test_details_are_declared_as_mounts_not_as_structure(catalogo):
    """Cio' che una parte *ha* e' un'altra cosa da cio' che una parte *e'*."""
    from app.core.component import BuildContext

    testa = catalogo.component("humanoid:head")
    nomi = {m.socket_id for m in testa.mounts}
    assert {"viso", "cima"} <= nomi
    pezzo = testa.build(resolve_params(testa.params, {}), BuildContext())
    for innesto in testa.mounts:
        assert pezzo.socket(innesto.socket_id) is not None, innesto.socket_id


def test_a_mount_declares_what_fits_in_it(catalogo):
    for componente in catalogo.components():
        for innesto in componente.mounts:
            assert innesto.capability, \
                "%s: un innesto senza capability non dice cosa ci va" % componente.id
