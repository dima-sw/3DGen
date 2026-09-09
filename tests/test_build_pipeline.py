"""Dal piano alla mesh: la pipeline intera, con geometria vera.

    Registry -> CompositionGraph -> Resolver -> EffectPipeline -> Builder -> mesh

I test che contano davvero sono in fondo: un umanoide con la testa di rana e le
gambe di spada, e una casa su un pianeta, costruiti **dallo stesso builder**.
Se quei due passano, l'architettura non e' specifica per un dominio; se uno dei
due avesse avuto bisogno di una riga di codice propria, non lo sarebbe.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import trimesh

from app.build.assembler import Builder, BuildResult, build
from app.build.validate import validate
from app.core.budget import TRIANGLES, Budget
from app.core.capability import Capability, Requirement, mount
from app.core.component import Attachment, Component, Piece
from app.core.effect import apply_effects
from app.core.graph import CompositionGraph
from app.core.params import DISTANCE, ParamSpec
from app.core.registry import Registry, load
from app.core.resolver import resolve
from app.core.socket import socket
from app.geometry.kernel import block, grow

QUI = Path(__file__).resolve().parent
INTERNI = QUI.parent / "app" / "plugins"
TERZE_PARTI = QUI / "plugins" / "terze_parti"


@pytest.fixture(scope="module")
def mondo() -> Registry:
    """Vocabolario del mondo, primitive, effetti e stile: tutto installato."""
    r = load([INTERNI])
    assert not r.report.errors(), r.report.describe()
    return r.freeze()


@pytest.fixture(scope="module")
def esterno() -> Registry:
    r = load([TERZE_PARTI])
    assert not r.report.errors(), r.report.describe()
    return r.freeze()


def chiedi(capability: str = "", **kwargs) -> Requirement:
    return Requirement(capability=capability, **kwargs)


def tubo(lunghezza: float = 1.0, raggio: float = 0.1, lati: int = 8):
    """Un solido vero che cresce lungo +X, con base e punta."""
    mesh = grow([(0.0, raggio), (1.0, raggio)], sides=lati, length=lunghezza, axis=0)
    return mesh, {
        "base": socket("base", (0.0, 0.0, 0.0), (-1.0, 0.0, 0.0), radius=raggio),
        "tip": socket("tip", (lunghezza, 0.0, 0.0), (1.0, 0.0, 0.0), radius=raggio,
                      provides="segmento"),
    }


def pezzo_vero(id: str, lunghezza: float = 1.0, raggio: float = 0.1,
               **kwargs) -> Component:
    """Un componente con geometria, senza significato."""
    def costruisci(v, ctx):
        mesh, sockets = tubo(v["length"], v["radius"])
        return Piece(mesh=mesh, sockets=sockets, material="prova")

    base = dict(
        params={"length": ParamSpec(lunghezza, DISTANCE, min=0.01, max=99.0,
                                    semantic_role="length"),
                "radius": ParamSpec(raggio, DISTANCE, min=0.001, max=9.0,
                                    semantic_role="girth")},
        provides=(Capability("segmento"),),
        mounts=(mount("segmento", socket_id="tip", capacity=0),))
    base.update(kwargs)
    return Component(id=id, build=costruisci, **base)


def registro(*componenti) -> Registry:
    r = Registry()
    for c in componenti:
        r.register_component(c)
    return r


def catena(reg: Registry, quanti: int, **kwargs) -> BuildResult:
    """Una catena di pezzi veri, uno dentro l'altro."""
    g = CompositionGraph()
    g.set_root("n0", "prova:pezzo")
    for i in range(1, quanti):
        g.add_child("n%d" % i, "prova:pezzo", "n%d" % (i - 1),
                    requirement=chiedi("segmento"))
    return build(resolve(g, reg), **kwargs)


def umanoide(detail_level: int = 2, gambe: bool = True) -> CompositionGraph:
    g = CompositionGraph(detail_level=detail_level)
    g.set_root("corpo", "humanoid:body", height=1.8)
    g.add_child("torso", "humanoid:torso", "corpo", requirement=chiedi("core_mount"))
    g.add_child("testa", "humanoid:head", "torso", requirement=chiedi("head_mount"))
    for nome, lato in (("braccio_l", "l"), ("braccio_r", "r")):
        g.add_child(nome, "humanoid:arm", "torso",
                    requirement=chiedi("limb_mount", side=lato,
                                       tags=frozenset({"alto"})))
    if gambe:
        for nome, lato in (("gamba_l", "l"), ("gamba_r", "r")):
            g.add_child(nome, "humanoid:leg", "torso",
                        requirement=chiedi("limb_mount", side=lato,
                                           tags=frozenset({"basso"})))
    return g


def casa_e_pianeta() -> CompositionGraph:
    g = CompositionGraph()
    g.set_root("casa", "architecture:house")
    g.add_child("mondo", "space:planet", "casa", requirement=chiedi("surface"))
    return g


# --------------------------------------------------------------------------- #
# Il contratto di costruzione
# --------------------------------------------------------------------------- #
def test_a_component_becomes_a_real_mesh():
    reg = registro(pezzo_vero("prova:pezzo"))
    out = catena(reg, 1)
    assert out.ok
    assert isinstance(out.node("n0").mesh, trimesh.Trimesh)
    assert out.triangles > 0 and out.vertices > 0


def test_a_component_may_have_no_geometry_at_all(mondo):
    """Un contenitore esiste per tenere insieme, non per essere visto."""
    out = build(resolve(umanoide(), mondo))
    corpo = out.node("corpo")
    assert corpo is not None and corpo.mesh is None
    assert "core" in corpo.sockets, "ma i suoi innesti servono lo stesso"


def test_the_builder_does_not_recompute_the_parameters(mondo):
    """I valori arrivano gia' risolti: rifarli sarebbe un secondo parere."""
    g = umanoide()
    g.override("torso", width=0.9)
    risolto = resolve(g, mondo)
    atteso = dict(risolto.node("torso").values)

    build(risolto)
    assert risolto.node("torso").values == atteso


def test_the_build_order_is_deterministic(mondo):
    prima = [n.id for n in build(resolve(umanoide(), mondo)).walk()]
    for _ in range(4):
        assert [n.id for n in build(resolve(umanoide(), mondo)).walk()] == prima


def test_every_mesh_knows_where_it_came_from(mondo):
    """Serve al debug, all'animazione e all'esportazione."""
    out = build(resolve(umanoide(), mondo))
    testa = out.node("testa")
    assert testa.metadata["plugin"] == "humanoid"
    assert testa.metadata["component"] == "humanoid:head"
    assert testa.metadata["path"] == "corpo/torso/testa"
    assert testa.metadata["role"] == "head"


def test_each_piece_keeps_its_own_mesh(mondo):
    """Niente fusione d'ufficio: sono pezzi distinti, con destini distinti."""
    out = build(resolve(umanoide(), mondo))
    assert len(out.meshes()) == len(out.geometry()) >= 5
    assert len({id(m) for m in out.meshes()}) == len(out.meshes())


def test_the_pieces_can_be_asked_for_as_one_mesh(mondo):
    out = build(resolve(umanoide(), mondo))
    intero = out.combined()
    assert len(intero.faces) == out.triangles


def test_the_result_can_become_a_scene(mondo):
    """La scena e' cio' che l'esportatore consuma."""
    scena = build(resolve(umanoide(), mondo)).scene()
    assert isinstance(scena, trimesh.Scene)
    assert len(scena.geometry) >= 5


def test_the_existing_exporter_consumes_the_result(mondo, tmp_path):
    """L'esportatore non e' stato riscritto: la scena e' gia' cio' che si aspetta."""
    from app.build.exporter import write_scene

    out = build(resolve(umanoide(), mondo))
    file = write_scene(out.scene(), tmp_path / "modello.glb", "glb")
    assert file.exists() and file.stat().st_size > 0


def test_a_node_keeps_transform_and_mesh_apart(mondo):
    """L'animazione ha bisogno di una trasformazione, non di vertici gia' mossi."""
    out = build(resolve(umanoide(), mondo))
    testa = out.node("testa")
    locale = np.asarray(testa.piece.mesh.vertices)
    mondiale = np.asarray(testa.mesh.vertices)
    atteso = np.array([testa.placement.apply_point(p) for p in locale])
    assert np.allclose(mondiale, atteso)


# --------------------------------------------------------------------------- #
# Socket dichiarati contro socket veri
# --------------------------------------------------------------------------- #
def test_a_declared_mount_that_is_not_built_is_reported():
    """La promessa contro il fatto: fin qui nessuno poteva confrontarle."""
    def senza(v, ctx):
        return Piece(mesh=block((1.0, 1.0, 1.0), axis=0), sockets={})

    bugiardo = Component(id="prova:bugiardo", build=senza,
                         mounts=(mount("attacco", socket_id="promesso"),))
    g = CompositionGraph()
    g.set_root("r", "prova:bugiardo")

    out = build(resolve(g, registro(bugiardo)))
    assert "DECLARED_SOCKET_MISSING" in out.report.codes()
    assert out.ok, "un avviso: il pezzo esiste comunque"


def test_the_missing_socket_can_be_made_an_error():
    def senza(v, ctx):
        return Piece(mesh=block((1.0, 1.0, 1.0), axis=0), sockets={})

    bugiardo = Component(id="prova:bugiardo", build=senza,
                         mounts=(mount("attacco", socket_id="promesso"),))
    g = CompositionGraph()
    g.set_root("r", "prova:bugiardo")

    out = Builder(strict_sockets=True).run(resolve(g, registro(bugiardo)))
    assert not out.ok


def test_sockets_built_without_being_declared_are_not_an_error():
    """Un plugin puo' generarli in base ai parametri: vietarlo sarebbe assurdo."""
    def generoso(v, ctx):
        mesh, sockets = tubo()
        sockets["extra"] = socket("extra", (0.5, 0.0, 0.0), (0.0, 1.0, 0.0))
        return Piece(mesh=mesh, sockets=sockets)

    c = Component(id="prova:generoso", build=generoso,
                  mounts=(mount("segmento", socket_id="tip"),))
    g = CompositionGraph()
    g.set_root("r", "prova:generoso")

    out = build(resolve(g, registro(c)))
    assert out.ok
    assert out.node("r").metadata["undeclared_sockets"] == ["base", "extra"]


def test_all_declared_mounts_of_the_world_plugins_are_really_built(mondo):
    """Il debito lasciato aperto al passo 3, finalmente saldato."""
    for nome, grafo in (("umanoide", umanoide(detail_level=3)),
                        ("casa", casa_e_pianeta())):
        out = build(resolve(grafo, mondo))
        assert "DECLARED_SOCKET_MISSING" not in out.report.codes(), \
            "%s: %s" % (nome, out.report.describe())


def test_an_own_socket_that_does_not_exist_does_not_crash():
    padre = pezzo_vero("prova:padre")
    figlio = pezzo_vero("prova:figlio")
    g = CompositionGraph()
    g.set_root("p", "prova:padre")
    g.add_child("f", "prova:figlio", "p", requirement=chiedi("segmento"),
                own_socket="inventato")

    out = build(resolve(g, registro(padre, figlio)))
    assert "OWN_SOCKET_NOT_FOUND" in out.report.codes()
    assert out.node("f") is not None, "posato lo stesso, sulla base della convenzione"


def test_a_parent_without_the_socket_refuses_the_child():
    def nudo(v, ctx):
        return Piece(mesh=block((1.0, 1.0, 1.0), axis=0), sockets={})

    padre = Component(id="prova:padre", build=nudo,
                      mounts=(mount("segmento", socket_id="tip"),))
    figlio = pezzo_vero("prova:figlio")
    g = CompositionGraph()
    g.set_root("p", "prova:padre")
    g.add_child("f", "prova:figlio", "p", requirement=chiedi("segmento"))

    out = build(resolve(g, registro(padre, figlio)))
    assert "PARENT_SOCKET_NOT_FOUND" in out.report.codes()
    assert out.node("f") is None and "f" in out.skipped


# --------------------------------------------------------------------------- #
# Posa e scala
# --------------------------------------------------------------------------- #
def test_a_child_lands_on_the_socket_of_its_parent():
    reg = registro(pezzo_vero("prova:pezzo"))
    out = catena(reg, 2)
    padre, figlio = out.node("n0"), out.node("n1")

    innesto = padre.socket_world("tip")
    base = figlio.socket_world("base")
    distanza = float(np.linalg.norm(innesto.position - base.position))
    assert distanza == pytest.approx(innesto.radius * figlio.node.link.insert,
                                     abs=1e-9), "la sola compenetrazione voluta"


def test_scale_mode_none_keeps_the_declared_measures():
    padre = pezzo_vero("prova:padre", raggio=0.4)
    figlio = pezzo_vero("prova:figlio", raggio=0.05)
    g = CompositionGraph()
    g.set_root("p", "prova:padre")
    g.add_child("f", "prova:figlio", "p", requirement=chiedi("segmento"),
                scale_mode="none")

    out = build(resolve(g, registro(padre, figlio)))
    assert out.node("f").placement.scale == pytest.approx(1.0)


def test_scale_mode_socket_brings_a_foreign_part_to_the_mount():
    """Una testa costruita con le sue misure non sta su un collo qualunque."""
    padre = pezzo_vero("prova:collo", raggio=0.18)
    figlio = pezzo_vero("prova:testa", raggio=0.8)
    g = CompositionGraph()
    g.set_root("p", "prova:collo")
    g.add_child("f", "prova:testa", "p", requirement=chiedi("segmento"),
                scale_mode="socket")

    out = build(resolve(g, registro(padre, figlio)))
    assert out.node("f").placement.scale == pytest.approx(0.18 / 0.8, rel=1e-6)


def test_scaling_stays_uniform_so_the_shape_is_not_distorted():
    padre = pezzo_vero("prova:collo", raggio=0.18)
    figlio = pezzo_vero("prova:testa", raggio=0.8)
    g = CompositionGraph()
    g.set_root("p", "prova:collo")
    g.add_child("f", "prova:testa", "p", requirement=chiedi("segmento"),
                scale_mode="socket")

    out = build(resolve(g, registro(padre, figlio)))
    prima = out.node("f").piece.mesh.bounds[1] - out.node("f").piece.mesh.bounds[0]
    dopo = out.node("f").mesh.bounds[1] - out.node("f").mesh.bounds[0]
    rapporti = np.sort(dopo)[::-1] / np.sort(prima)[::-1]
    assert np.allclose(rapporti, rapporti[0], rtol=1e-6), "stesse proporzioni"


def test_a_child_points_where_the_socket_sends_it():
    """Il figlio esce nel verso in cui il padre lo manda: l'orientamento conta."""
    def con_lato(v, ctx):
        mesh, sockets = tubo()
        sockets["lato"] = socket("lato", (0.5, 0.0, 0.1), (0.0, 0.0, 1.0),
                                 radius=0.05, provides="segmento")
        return Piece(mesh=mesh, sockets=sockets)

    padre = Component(id="prova:padre", build=con_lato,
                      params=pezzo_vero("x").params,
                      mounts=(mount("segmento", socket_id="lato"),))
    figlio = pezzo_vero("prova:figlio", raggio=0.05)
    g = CompositionGraph()
    g.set_root("p", "prova:padre")
    g.add_child("f", "prova:figlio", "p",
                requirement=Requirement(capability="segmento", socket_id="lato"))

    out = build(resolve(g, registro(padre, figlio)))
    crescita = out.node("f").placement.apply_direction([1.0, 0.0, 0.0])
    assert crescita[2] == pytest.approx(1.0, abs=1e-6), "cresce lungo +Z"


# --------------------------------------------------------------------------- #
# Effetti geometrici
# --------------------------------------------------------------------------- #
def test_a_local_effect_touches_only_its_target(mondo):
    g = umanoide()
    g.effect("bend", scope="part:braccio_l", amount=0.8)

    con = build(apply_effects(resolve(g, mondo), mondo))
    senza = build(resolve(umanoide(), mondo))
    assert not np.allclose(con.node("braccio_l").piece.mesh.vertices,
                           senza.node("braccio_l").piece.mesh.vertices)
    assert np.allclose(con.node("braccio_r").piece.mesh.vertices,
                       senza.node("braccio_r").piece.mesh.vertices)


def test_a_deformation_keeps_the_topology(mondo):
    g = umanoide()
    g.effect("bend", scope="part:braccio_l", amount=0.8)

    con = build(apply_effects(resolve(g, mondo), mondo))
    senza = build(resolve(umanoide(), mondo))
    assert con.triangles == senza.triangles
    assert np.array_equal(con.node("braccio_l").mesh.faces,
                          senza.node("braccio_l").mesh.faces)


def test_a_global_effect_reaches_the_whole_model(mondo):
    g = umanoide()
    g.effect("perspective_exaggeration", scope="model", amount=0.8)

    con = build(apply_effects(resolve(g, mondo), mondo))
    senza = build(resolve(umanoide(), mondo))
    diversi = [n.id for n in con.walk()
               if n.mesh is not None
               and not np.allclose(n.mesh.vertices, senza.node(n.id).mesh.vertices)]
    assert len(diversi) == len(con.geometry()), "tutti i pezzi, non uno"


def test_a_subtree_effect_stops_at_the_subtree(mondo):
    g = umanoide(detail_level=3)
    g.effect("bend", scope="subtree:braccio_l", amount=0.8)

    con = build(apply_effects(resolve(g, mondo), mondo))
    senza = build(resolve(umanoide(detail_level=3), mondo))
    for id in ("braccio_l", "braccio_l/omero", "braccio_l/avambraccio"):
        assert not np.allclose(con.node(id).piece.mesh.vertices,
                               senza.node(id).piece.mesh.vertices), id
    for id in ("torso", "testa", "braccio_r"):
        assert np.allclose(con.node(id).piece.mesh.vertices,
                           senza.node(id).piece.mesh.vertices), id


def test_a_role_effect_finds_what_declares_that_role(mondo):
    """`role:arm` trova omero e avambraccio se il plugin li ha dichiarati cosi'."""
    g = umanoide(detail_level=3)
    g.effect("bend", scope="role:arm", amount=0.5)

    fatto = apply_effects(resolve(g, mondo), mondo)
    bersagli = set(fatto.planned[0].targets)
    assert {"braccio_l", "braccio_l/omero", "braccio_l/avambraccio"} <= bersagli
    assert "torso" not in bersagli


def test_a_group_effect_finds_a_tag(mondo):
    g = umanoide()
    g.swap("gamba_l", "weapon:sword")
    g.effect("bend", scope="group:metallo", amount=0.4)

    fatto = apply_effects(resolve(g, mondo), mondo)
    assert fatto.planned[0].targets == ("gamba_l",)


def test_the_builder_does_not_resolve_the_scope_again(mondo):
    """I bersagli arrivano gia' risolti: cercarli di nuovo sarebbe un secondo parere."""
    g = umanoide()
    g.effect("bend", scope="part:braccio_l", amount=0.5)
    fatto = apply_effects(resolve(g, mondo), mondo)
    fatto.planned[0].targets = ("braccio_r",)          # il builder si fida

    out = build(fatto)
    senza = build(resolve(umanoide(), mondo))
    assert np.allclose(out.node("braccio_l").piece.mesh.vertices,
                       senza.node("braccio_l").piece.mesh.vertices)
    assert not np.allclose(out.node("braccio_r").piece.mesh.vertices,
                           senza.node("braccio_r").piece.mesh.vertices)


def test_the_builder_never_reruns_the_stages_already_applied(mondo):
    g = umanoide()
    g.effect("lanky", scope="model", amount=1.0)

    fatto = apply_effects(resolve(g, mondo), mondo)
    lunghezza = fatto.node("braccio_l").values["length"]
    out = build(fatto)
    assert out.node("braccio_l").node.values["length"] == lunghezza
    assert not [e for e in out.effects if e.stage == "proportion"]


def test_the_stages_are_applied_in_order(mondo):
    """Locale prima di globale: chi arriva dopo lavora su cio' che c'e' gia'."""
    g = umanoide()
    g.effect("perspective_exaggeration", scope="model", amount=0.5)
    g.effect("bend", scope="part:braccio_l", amount=0.5)

    out = build(apply_effects(resolve(g, mondo), mondo))
    assert [e.id for e in out.effects] == ["fx:bend",
                                           "fx:perspective_exaggeration"]


# --------------------------------------------------------------------------- #
# Deformazione e socket: la regressione
# --------------------------------------------------------------------------- #
def test_a_bent_part_carries_its_sockets_with_it():
    """Se la mesh si piega e i socket restano fermi, i figli finiscono nel vuoto."""
    reg = registro(pezzo_vero("prova:pezzo"))
    reg.load_directory(INTERNI)

    g = CompositionGraph()
    g.set_root("a", "prova:pezzo")
    g.add_child("b", "prova:pezzo", "a", requirement=chiedi("segmento"))
    g.effect("bend", scope="part:a", amount=1.0)

    out = build(apply_effects(resolve(g, reg), reg))
    piegato = out.node("a")
    punta = piegato.sockets["tip"]
    vicini = np.linalg.norm(
        np.asarray(piegato.piece.mesh.vertices) - punta.position, axis=1)
    assert float(vicini.min()) < 0.2, "il socket e' rimasto sulla geometria"


def test_a_child_of_a_bent_part_stays_attached():
    reg = registro(pezzo_vero("prova:pezzo"))
    reg.load_directory(INTERNI)

    g = CompositionGraph()
    g.set_root("a", "prova:pezzo")
    g.add_child("b", "prova:pezzo", "a", requirement=chiedi("segmento"))
    g.effect("bend", scope="part:a", amount=1.0)

    out = build(apply_effects(resolve(g, reg), reg))
    validate(out)
    assert "JOINT_GAP" not in out.report.codes(), out.report.describe()


def test_bending_and_scaling_together_keep_the_joint():
    reg = registro(pezzo_vero("prova:grande", raggio=0.3),
                   pezzo_vero("prova:piccolo", raggio=0.02))
    reg.load_directory(INTERNI)

    g = CompositionGraph()
    g.set_root("a", "prova:grande")
    g.add_child("b", "prova:piccolo", "a", requirement=chiedi("segmento"),
                scale_mode="socket")
    g.effect("bend", scope="part:a", amount=0.9)

    out = build(apply_effects(resolve(g, reg), reg))
    validate(out)
    assert "JOINT_GAP" not in out.report.codes(), out.report.describe()


def test_a_global_deformation_moves_containers_too(mondo):
    """Un contenitore senza mesh ha comunque i socket a cui i figli si tengono."""
    g = umanoide()
    g.effect("perspective_exaggeration", scope="model", amount=1.0)

    out = build(apply_effects(resolve(g, mondo), mondo))
    validate(out)
    assert "JOINT_GAP" not in out.report.codes(), out.report.describe()


def test_an_effect_declares_what_happens_to_the_sockets(mondo):
    """La scelta e' nel contratto, non nella consuetudine."""
    piega = mondo.effect("bend")
    assert piega.socket_policy == "preserve"
    assert piega.moves_points, "una mappa di punti muove vertici e socket insieme"


# --------------------------------------------------------------------------- #
# Verifica della geometria
# --------------------------------------------------------------------------- #
def test_a_finite_model_passes(mondo):
    out = build(resolve(umanoide(detail_level=3), mondo))
    validate(out, style=mondo.style("low_poly"))
    assert out.ok, out.report.describe()


def test_non_finite_coordinates_are_caught():
    def rotto(v, ctx):
        mesh, sockets = tubo()
        vertici = np.asarray(mesh.vertices).copy()
        vertici[0][0] = np.nan
        mesh.vertices = vertici
        return Piece(mesh=mesh, sockets=sockets)

    c = Component(id="prova:rotto", build=rotto, params=pezzo_vero("x").params)
    g = CompositionGraph()
    g.set_root("r", "prova:rotto")

    out = build(resolve(g, registro(c)))
    validate(out)
    assert "NON_FINITE_GEOMETRY" in out.report.codes()


def test_an_empty_mesh_is_caught():
    def vuoto(v, ctx):
        return Piece(mesh=trimesh.Trimesh(vertices=[], faces=[]), sockets={})

    c = Component(id="prova:vuoto", build=vuoto)
    g = CompositionGraph()
    g.set_root("r", "prova:vuoto")

    out = build(resolve(g, registro(c)))
    validate(out)
    assert "EMPTY_GEOMETRY" in out.report.codes()


def test_a_socket_without_a_direction_is_caught():
    def storto(v, ctx):
        mesh, sockets = tubo()
        s = sockets["tip"]
        s.direction = np.zeros(3)
        return Piece(mesh=mesh, sockets=sockets)

    c = Component(id="prova:storto", build=storto, params=pezzo_vero("x").params)
    g = CompositionGraph()
    g.set_root("r", "prova:storto")

    out = build(resolve(g, registro(c)))
    validate(out)
    assert "INVALID_SOCKET" in out.report.codes()


def test_only_declared_requirements_are_checked():
    """Una lamina aperta e' aperta apposta: non e' un difetto per tutti."""
    def aperta(v, ctx):
        mesh = trimesh.Trimesh(vertices=[[0, 0, 0], [1, 0, 0], [0, 1, 0]],
                               faces=[[0, 1, 2]])
        return Piece(mesh=mesh, sockets={})

    libera = Component(id="prova:libera", build=aperta)
    severa = Component(id="prova:severa", build=aperta,
                       requires=frozenset({"watertight"}))

    for componente, atteso in ((libera, False), (severa, True)):
        g = CompositionGraph()
        g.set_root("r", componente.id)
        out = build(resolve(g, registro(componente)))
        validate(out)
        assert ("GEOMETRY_REQUIREMENT" in out.report.codes()) is atteso


def test_the_style_criterion_applies_only_if_the_style_asks(mondo):
    """Nessun criterio d'ufficio: uno stile che non lo dichiara non lo vuole."""
    def sfaccettato(v, ctx):
        mesh = trimesh.creation.icosphere(subdivisions=1, radius=0.5)
        return Piece(mesh=mesh, sockets={})

    c = Component(id="prova:sfera", build=sfaccettato)
    g = CompositionGraph()
    g.set_root("r", "prova:sfera")
    out = build(resolve(g, registro(c)))

    validate(out)
    assert "STYLE_QUALITY" not in out.report.codes(), "senza stile, nessun giudizio"

    validate(out, style=mondo.style("low_poly"))
    assert "STYLE_QUALITY" in out.report.codes(), "con il low poly, si'"


def test_a_component_can_declare_itself_faceted(mondo):
    """Una sfera ha legittimamente una normale per faccia."""
    def sfaccettato(v, ctx):
        return Piece(mesh=trimesh.creation.icosphere(subdivisions=1, radius=0.5))

    c = Component(id="prova:sfera", build=sfaccettato,
                  requires=frozenset({"faceted"}))
    g = CompositionGraph()
    g.set_root("r", "prova:sfera")

    out = build(resolve(g, registro(c)))
    validate(out, style=mondo.style("low_poly"))
    assert "STYLE_QUALITY" not in out.report.codes()


def test_the_style_measures_the_designed_geometry_not_the_deformed_one(mondo):
    """Una piega rende non complanari quadrilateri che erano piatti.

    Lo stile giudica **come e' stata costruita** una forma, non che cosa le e'
    stato fatto dopo: altrimenti chiedere una deformazione farebbe fallire il
    controllo di qualita' di una geometria disegnata benissimo.
    """
    g = umanoide()
    g.effect("bend", scope="part:braccio_l", amount=1.0)

    out = build(apply_effects(resolve(g, mondo), mondo))
    validate(out, style=mondo.style("low_poly"))
    assert "STYLE_QUALITY" not in out.report.codes(), out.report.describe()


def test_the_triangle_budget_of_the_style_is_watched(mondo):
    from app.core.vocabulary import StyleProfile

    out = build(resolve(umanoide(), mondo))
    stretto = StyleProfile(id="prova:strettissimo", params={"triangle_budget": 4})
    validate(out, style=stretto)
    assert "STYLE_QUALITY" in out.report.codes()


# --------------------------------------------------------------------------- #
# Budget
# --------------------------------------------------------------------------- #
def test_the_triangle_budget_is_the_builders_own(mondo):
    """Nodi ed espansioni li conta il resolver; i triangoli solo la geometria."""
    budget = Budget(triangles=20)
    out = build(resolve(umanoide(), mondo), budget=budget)
    assert "BUDGET_EXCEEDED" in out.report.codes()
    assert budget.used(TRIANGLES) > 20


def test_going_over_budget_does_not_break_a_mesh(mondo):
    out = build(resolve(umanoide(), mondo), budget=Budget(triangles=20))
    for costruito in out.geometry():
        assert costruito.triangles == len(costruito.piece.mesh.faces), \
            "nessuna mesh e' stata tagliata a meta'"


def test_over_budget_the_optional_parts_are_the_ones_left_out():
    reg = registro(pezzo_vero("prova:pezzo"))
    g = CompositionGraph()
    g.set_root("a", "prova:pezzo")
    g.add_child("b", "prova:pezzo", "a", requirement=chiedi("segmento"))
    g.attach("c", "prova:pezzo", "b", requirement=chiedi("segmento"))

    out = build(resolve(g, reg), budget=Budget(triangles=30))
    assert "a" in out.nodes and "b" in out.nodes, "cio' che l'oggetto e' resta"
    assert "c" not in out.nodes, "cio' che porta, no"


# --------------------------------------------------------------------------- #
# Costruzione parziale
# --------------------------------------------------------------------------- #
def test_a_structural_component_that_fails_is_an_error():
    def esplode(v, ctx):
        raise RuntimeError("non ci riesco")

    reg = registro(pezzo_vero("prova:pezzo"),
                   Component(id="prova:rotto", build=esplode,
                             provides=(Capability("segmento"),)))
    g = CompositionGraph()
    g.set_root("a", "prova:pezzo")
    g.add_child("b", "prova:rotto", "a", requirement=chiedi("segmento"))

    out = build(resolve(g, reg))
    assert "COMPONENT_BUILD_FAILED" in out.report.codes()
    assert not out.ok and "b" in out.skipped


def test_an_optional_component_that_fails_is_a_warning():
    def esplode(v, ctx):
        raise RuntimeError("non ci riesco")

    reg = registro(pezzo_vero("prova:pezzo"),
                   Component(id="prova:cappello", build=esplode,
                             provides=(Capability("segmento"),)))
    g = CompositionGraph()
    g.set_root("a", "prova:pezzo")
    g.attach("cappello", "prova:cappello", "a", requirement=chiedi("segmento"))

    out = build(resolve(g, reg))
    assert "COMPONENT_BUILD_FAILED" in out.report.codes()
    assert out.ok, "una testa senza cappello e' ancora una testa"
    assert out.node("a") is not None


def test_a_failed_node_takes_its_subtree_with_it():
    def esplode(v, ctx):
        raise RuntimeError("non ci riesco")

    reg = registro(pezzo_vero("prova:pezzo"),
                   Component(id="prova:rotto", build=esplode,
                             provides=(Capability("segmento"),),
                             mounts=(mount("segmento", socket_id="tip"),)))
    g = CompositionGraph()
    g.set_root("a", "prova:pezzo")
    g.add_child("b", "prova:rotto", "a", requirement=chiedi("segmento"))
    g.add_child("c", "prova:pezzo", "b", requirement=chiedi("segmento"))

    out = build(resolve(g, reg))
    assert out.skipped == ["b", "c"], "senza il padre non c'e' dove posarsi"


def test_one_broken_branch_does_not_stop_the_others():
    def esplode(v, ctx):
        raise RuntimeError("non ci riesco")

    reg = registro(pezzo_vero("prova:pezzo"),
                   Component(id="prova:rotto", build=esplode,
                             provides=(Capability("segmento"),)))
    g = CompositionGraph()
    g.set_root("a", "prova:pezzo")
    g.add_child("rotto", "prova:rotto", "a", requirement=chiedi("segmento"))
    g.add_child("buono", "prova:pezzo", "a", requirement=chiedi("segmento"))

    out = build(resolve(g, reg))
    assert out.node("buono") is not None and out.node("buono").mesh is not None


# --------------------------------------------------------------------------- #
# I casi che contano
# --------------------------------------------------------------------------- #
def test_end_to_end_a_humanoid_with_a_frog_head_and_a_sword_leg(mondo):
    """Piano, vocabolario, risoluzione, effetti, mesh. Tutto vero."""
    g = umanoide()
    g.swap("testa", "creature:frog_head")
    g.swap("gamba_l", "weapon:sword")

    out = build(apply_effects(resolve(g, mondo), mondo))
    validate(out, style=mondo.style("low_poly"))

    assert out.ok, out.report.describe()
    assert out.node("testa").ref == "creature:frog_head"
    assert out.node("gamba_l").ref == "weapon:sword"
    assert "humanoid:head" not in [n.ref for n in out.walk()]
    assert out.triangles > 50 and np.all(np.isfinite(out.bounds))
    assert "JOINT_GAP" not in out.report.codes(), "niente pezzi staccati"


def test_end_to_end_a_house_on_a_planet(mondo):
    """Lo stesso builder, un vocabolario che non ha niente in comune."""
    out = build(apply_effects(resolve(casa_e_pianeta(), mondo), mondo))
    validate(out, style=mondo.style("low_poly"))

    assert out.ok, out.report.describe()
    assert {"architecture:house", "space:planet", "architecture:door",
            "architecture:roof"} <= {n.ref for n in out.walk()}
    assert out.triangles > 50


def test_the_two_worlds_go_through_the_very_same_code(mondo):
    """Nessuna riga di builder e' specifica per uno dei due."""
    umano = build(resolve(umanoide(), mondo))
    casa = build(resolve(casa_e_pianeta(), mondo))
    assert umano.ok and casa.ok
    assert type(umano) is type(casa)


def test_end_to_end_with_all_the_effects(mondo):
    g = umanoide()
    g.swap("testa", "creature:frog_head")
    g.swap("gamba_l", "weapon:sword")
    g.effect("lanky", scope="model", amount=0.8)
    g.effect("bend", scope="part:braccio_l", amount=0.5)
    g.effect("perspective_exaggeration", scope="model", amount=0.4)

    fatto = apply_effects(resolve(g, mondo), mondo)
    out = build(fatto)
    validate(out, style=mondo.style("low_poly"))

    # lo stesso modello, con le stesse sostituzioni, ma senza effetti
    nudo = umanoide()
    nudo.swap("testa", "creature:frog_head")
    nudo.swap("gamba_l", "weapon:sword")
    senza = build(resolve(nudo, mondo))

    assert out.ok, out.report.describe()
    assert [e.id for e in fatto.applied] == ["fx:lanky"], "la proporzione, prima"
    assert out.triangles == senza.triangles, "una deformazione non aggiunge facce"
    assert out.node("braccio_l").node.values["length"] > \
        senza.node("braccio_l").node.values["length"], "lanky ha allungato"


def test_the_whole_pipeline_is_deterministic(mondo):
    def genera():
        g = umanoide(detail_level=3)
        g.swap("testa", "creature:frog_head")
        g.effect("lanky", scope="model", amount=0.7)
        g.effect("perspective_exaggeration", scope="model", amount=0.3)
        return build(apply_effects(resolve(g, mondo), mondo))

    atteso = genera()
    for _ in range(3):
        altro = genera()
        assert [n.id for n in altro.walk()] == [n.id for n in atteso.walk()]
        for costruito in altro.walk():
            riferimento = atteso.node(costruito.id)
            assert costruito.ref == riferimento.ref
            if costruito.mesh is not None:
                assert np.allclose(costruito.mesh.vertices,
                                   riferimento.mesh.vertices)


def test_end_to_end_a_piercing_on_a_simple_head(mondo):
    """detail_level 1, e il piercing compare davvero nella mesh."""
    g = CompositionGraph(detail_level=1)
    g.set_root("corpo", "humanoid:body", height=1.8)
    g.add_child("torso", "humanoid:torso", "corpo", requirement=chiedi("core_mount"),
                level=1)
    g.add_child("testa", "humanoid:head", "torso", requirement=chiedi("head_mount"),
                level=3)
    g.add_child("naso", "humanoid:nose", "testa", requirement=chiedi("face_mount"),
                level=3)
    g.attach("piercing", "accessories:piercing", "naso", requirement=chiedi("anchor"),
             scale_mode="socket")

    out = build(resolve(g, mondo))
    validate(out)
    assert out.ok, out.report.describe()
    assert out.node("piercing") is not None
    assert out.node("piercing").triangles > 0
    assert "braccio_l" not in out.nodes, "il resto della testa non si e' espanso"


def test_end_to_end_a_third_party_plugin(esterno):
    """Il core non ha mai visto questa roba, e la costruisce lo stesso."""
    g = CompositionGraph(detail_level=3)
    g.set_root("blob", "external_test_plugin:quantum_blob")

    out = build(resolve(g, esterno))
    validate(out)
    assert out.ok, out.report.describe()
    assert out.node("blob").triangles > 0
    assert out.node("blob/cristallo") is not None, "e anche cio' che ci cresce sopra"
    assert out.triangles > 0


def test_end_to_end_deep_nesting():
    """A dentro B dentro C dentro D dentro E, con geometria vera."""
    reg = registro(pezzo_vero("prova:pezzo", lunghezza=0.5, raggio=0.08))
    out = catena(reg, 5)
    validate(out)

    assert out.ok, out.report.describe()
    assert [n.id for n in out.walk()] == ["n0", "n1", "n2", "n3", "n4"]
    assert out.node("n4").node.depth == 4
    assert "JOINT_GAP" not in out.report.codes()
    misura = out.size
    assert misura[0] > 2.0, "la catena si e' davvero allungata"


def test_deep_nesting_is_deterministic():
    reg = registro(pezzo_vero("prova:pezzo", lunghezza=0.5, raggio=0.08))
    atteso = catena(reg, 6)
    for _ in range(3):
        altro = catena(reg, 6)
        assert np.allclose(altro.combined().vertices, atteso.combined().vertices)


# --------------------------------------------------------------------------- #
# Confini
# --------------------------------------------------------------------------- #
def test_the_builder_never_names_a_thing_of_the_world():
    """Se comparisse `if plugin == "humanoid"`, l'architettura sarebbe finita."""
    proibite = ("humanoid", "umanoid", "animal", "animale", "fish", "pesce",
                "dragon", "drago", "house", "casa", "planet", "pianeta",
                "vehicle", "veicolo", "weapon", "arma", "tree", "albero",
                "frog", "rana", "robot", "head", "testa", "torso")
    for nome in ("assembler.py", "validate.py"):
        testo = (QUI.parent / "app" / "build" / nome).read_text(encoding="utf-8")
        codice = "\n".join(r for r in testo.lower().splitlines()
                           if not r.strip().startswith("#"))
        for parola in proibite:
            assert "'%s'" % parola not in codice and '"%s"' % parola not in codice, \
                "%s nomina %s" % (nome, parola)


def test_the_builder_does_not_import_the_old_pipeline():
    """La regola della transizione: niente moduli nuovi sul vecchio percorso."""
    for nome in ("assembler.py", "validate.py"):
        testo = (QUI.parent / "app" / "build" / nome).read_text(encoding="utf-8")
        for vecchio in ("app.build.builder", "app.build.strategy",
                        "app.geometry.composition", "app.geometry.templates",
                        "app.core.spec"):
            assert "import %s" % vecchio not in testo
            assert "from %s" % vecchio not in testo
