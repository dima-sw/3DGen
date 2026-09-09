"""I contratti del core: capability, socket, parametri, vincoli, componenti.

Questi test verificano il **contratto**, non una categoria di oggetti. Se un
test qui dentro nomina un umanoide, un drago o una casa, il core ha imparato
qualcosa che non doveva sapere: i componenti di prova si chiamano `alfa` e
`beta` apposta.

L'ultimo gruppo e' una dimostrazione funzionante: due componenti di
"vocabolari" diversi, montati uno sull'altro attraverso i soli contratti, che
producono una mesh vera. Senza quella, questi sarebbero solo dataclass.
"""
from __future__ import annotations

import numpy as np
import pytest
import trimesh

from app.core.capability import (CAPABILITY, CAPABILITY_AND_SIDE,
                                 CAPABILITY_AND_TAGS, EXACT_ID, FALLBACK,
                                 INCOMPATIBLE, Capability, Requirement, best_match)
from app.core.component import Attachment, BuildContext, Component, Piece
from app.core.constraints import CLAMP, Constraint, check
from app.core.errors import ERROR, WARNING, Report
from app.core.params import (DISTANCE, ENUM, INT, RATIO, VECTOR3, ExpressionError,
                             ParamSpec, evaluate, resolve)
from app.core.socket import Placement, Socket, attach, socket


# --------------------------------------------------------------------------- #
# Diagnostica
# --------------------------------------------------------------------------- #
def test_a_diagnostic_says_what_where_why_and_what_else():
    report = Report()
    report.add("SOCKET_INCOMPATIBLE", "non posso attaccare 'beta' ad 'alfa'",
               where="radice/alfa", why="richiede 'mount_b', alfa offre 'mount_a'",
               alternatives=["gamma:mount_b", "delta:mount_b"])
    testo = report.describe()
    assert "radice/alfa" in testo
    assert "perche'" in testo and "mount_a" in testo
    assert "gamma:mount_b" in testo and "delta:mount_b" in testo


def test_a_report_separates_fatal_from_the_rest():
    report = Report()
    report.warn("A", "sospetto")
    report.add("B", "rotto")
    report.note("C", "per informazione")
    assert not report.ok
    assert [d.code for d in report.errors()] == ["B"]
    assert [d.code for d in report.sorted()] == ["B", "A", "C"], "prima gli errori"


def test_collecting_is_not_raising():
    """Un pezzo che non si attacca non fa cadere il modello: entra nel referto."""
    report = Report()
    report.add("X", "guaio")
    assert len(report) == 1 and bool(report)


# --------------------------------------------------------------------------- #
# Capability
# --------------------------------------------------------------------------- #
def presa(nome, capability, side="", tags=()):
    return socket(nome, (0, 0, 0), (1, 0, 0), provides=capability, side=side, tags=tags)


def test_the_five_resolution_levels_are_ordered():
    """L'ordine della specifica, espresso come punteggi confrontabili."""
    assert EXACT_ID > CAPABILITY_AND_SIDE > CAPABILITY_AND_TAGS > CAPABILITY \
        > FALLBACK > INCOMPATIBLE


def test_an_exact_socket_id_wins_over_everything():
    presa_giusta = presa("preciso", "mount")
    assert Requirement(socket_id="preciso").score(presa_giusta) == EXACT_ID


def test_capability_plus_side_beats_capability_alone():
    sinistra = presa("uno", "mount", side="l")
    generica = presa("due", "mount")
    richiesta = Requirement(capability="mount", side="l")
    assert richiesta.score(sinistra) == CAPABILITY_AND_SIDE
    assert richiesta.score(generica) == CAPABILITY


def test_tags_refine_a_capability_match():
    con_tag = presa("uno", "mount", tags=("pesante",))
    richiesta = Requirement(capability="mount", tags={"pesante"})
    assert richiesta.score(con_tag) == CAPABILITY_AND_TAGS


def test_a_missing_capability_is_incompatible():
    assert Requirement(capability="mount_b").score(presa("x", "mount_a")) == INCOMPATIBLE


def test_the_wrong_side_is_a_last_resort_not_a_refusal():
    """Meglio un braccio sul lato sbagliato che un braccio mancante."""
    assert Requirement(capability="mount", side="l").score(
        presa("x", "mount", side="r")) == FALLBACK


def test_the_best_match_is_deterministic():
    """A parita' di punteggio vince il primo per nome: due esecuzioni, stesso
    risultato. Altrimenti lo stesso piano darebbe modelli diversi."""
    prese = [presa("zeta", "mount"), presa("alfa", "mount"), presa("mu", "mount")]
    for _ in range(5):
        scelto, punteggio = best_match(Requirement(capability="mount"), prese)
        assert scelto.name == "alfa" and punteggio == CAPABILITY


def test_a_socket_can_provide_several_capabilities():
    presa_doppia = socket("x", (0, 0, 0), (1, 0, 0), provides=("mount_a", "mount_b"))
    assert presa_doppia.provides("mount_a") and presa_doppia.provides("mount_b")
    assert Requirement(capability="mount_b").score(presa_doppia) == CAPABILITY


# --------------------------------------------------------------------------- #
# Socket e orientamento
# --------------------------------------------------------------------------- #
def test_up_is_made_orthogonal_to_the_direction():
    s = socket("x", (0, 0, 0), (1, 0, 0), up=(1, 1, 0))
    assert abs(float(s.direction @ s.up)) < 1e-9


def test_a_degenerate_up_is_replaced_not_accepted():
    """`up` parallelo alla direzione lascerebbe il rollio indeterminato."""
    s = socket("x", (0, 0, 0), (0, 1, 0), up=(0, 1, 0))
    assert abs(float(s.direction @ s.up)) < 1e-9
    assert np.linalg.norm(s.up) == pytest.approx(1.0)


def test_the_socket_frame_is_orthonormal():
    frame = socket("x", (0, 0, 0), (0.3, 0.9, -0.2), up=(0, 0, 1)).frame()
    assert np.allclose(frame.T @ frame, np.eye(3), atol=1e-9)


def test_a_child_grows_away_from_the_parent_socket():
    """La convenzione: il figlio esce nel verso in cui il padre lo manda."""
    padre = socket("uscita", (0, 1, 0), (0, 1, 0))          # punta in alto
    base_figlio = socket("base", (0, 0, 0), (-1, 0, 0))     # cresce lungo +X
    posa = attach(Placement(), padre, base_figlio, insert=0.0)
    # la punta del figlio, che nel suo sistema sta a +X, deve finire in alto
    assert posa.apply_point((1, 0, 0))[1] > posa.apply_point((0, 0, 0))[1]


@pytest.mark.parametrize("direzione,atteso", [
    ((0, 1, 0), 1), ((0, -1, 0), 1), ((1, 0, 0), 0), ((0, 0, 1), 2),
])
def test_orientation_follows_the_declared_frame(direzione, atteso):
    """Il test che il contratto rende obbligatorio per i plugin di terze parti.

    Una parte nota, attaccata a socket che puntano in direzioni diverse, deve
    uscire allineata a quelle direzioni. Se un plugin sbaglia la convenzione,
    le sue parti si montano ruotate e il modello *sembra* costruito: e' un
    difetto lento da trovare, quindi lo si trova qui.
    """
    padre = socket("uscita", (0, 0, 0), direzione)
    base_figlio = socket("base", (0, 0, 0), (-1, 0, 0))
    posa = attach(Placement(), padre, base_figlio, insert=0.0)

    punta = posa.apply_point((1, 0, 0)) - posa.apply_point((0, 0, 0))
    assert abs(punta[atteso]) == pytest.approx(1.0, abs=1e-9)
    assert np.allclose(np.delete(punta, atteso), 0.0, atol=1e-9)


def test_scale_mode_none_keeps_the_declared_size():
    padre = socket("uscita", (0, 0, 0), (1, 0, 0), radius=1.0)
    figlio = socket("base", (0, 0, 0), (-1, 0, 0), radius=0.1)
    assert attach(Placement(), padre, figlio, scale_mode="none").scale == 1.0


def test_scale_mode_socket_fits_a_foreign_part():
    """Senza questo, ogni scambio fra vocabolari produce un fuori scala."""
    padre = socket("uscita", (0, 0, 0), (1, 0, 0), radius=1.0)
    figlio = socket("base", (0, 0, 0), (-1, 0, 0), radius=0.25)
    assert attach(Placement(), padre, figlio, scale_mode="socket").scale == \
        pytest.approx(4.0)


def test_placements_compose():
    interna = Placement(translation=np.array([1.0, 0.0, 0.0]), scale=2.0)
    esterna = Placement(translation=np.array([0.0, 3.0, 0.0]), scale=0.5)
    composta = interna.then(esterna)
    assert composta.scale == pytest.approx(1.0)
    assert np.allclose(composta.apply_point((0, 0, 0)), esterna.apply_point((1, 0, 0)))


# --------------------------------------------------------------------------- #
# Parametri
# --------------------------------------------------------------------------- #
def test_values_are_clamped_into_the_contract():
    schema = {"w": ParamSpec(0.5, DISTANCE, 0.1, 1.0)}
    assert resolve(schema, {"w": 99})["w"] == 1.0
    assert resolve(schema, {"w": -3})["w"] == 0.1


def test_an_unusable_value_falls_back_instead_of_exploding():
    schema = {"w": ParamSpec(0.5, DISTANCE, 0.1, 1.0)}
    assert resolve(schema, {"w": "non un numero"})["w"] == 0.5


def test_unknown_parameters_are_reported_with_suggestions():
    report = Report()
    resolve({"width": ParamSpec(1.0)}, {"widht": 2.0}, report=report)
    assert "PARAM_UNKNOWN" in report.codes()
    assert "width" in report.entries[0].alternatives


def test_clamping_is_annotated_not_silent():
    report = Report()
    resolve({"w": ParamSpec(0.5, DISTANCE, 0.0, 1.0)}, {"w": 9.0}, report=report)
    assert "PARAM_CLAMPED" in report.codes()


@pytest.mark.parametrize("tipo,dato,atteso", [
    (INT, 2.6, 3), (RATIO, "0.5", 0.5), (ENUM, "B", "b"),
])
def test_types_coerce_their_own_way(tipo, dato, atteso):
    spec = ParamSpec(default=0 if tipo != ENUM else "a", type=tipo,
                     choices=("a", "b") if tipo == ENUM else ())
    assert spec.coerce(dato) == atteso


def test_a_vector_parameter_keeps_its_arity():
    spec = ParamSpec(default=(0.0, 0.0, 0.0), type=VECTOR3, min=0.0, max=1.0)
    assert spec.coerce((2.0, -1.0)) == (1.0, 0.0, 0.0)


def test_derived_parameters_read_their_own_scope():
    schema = {"width": ParamSpec(0.4), "spacing": ParamSpec(0.0, derived="width * 0.5")}
    assert resolve(schema, {"width": 0.6})["spacing"] == pytest.approx(0.3)


def test_derived_parameters_read_parent_and_root():
    schema = {"h": ParamSpec(0.0, derived="parent.height * 0.22"),
              "r": ParamSpec(0.0, derived="root.height * 0.05")}
    valori = resolve(schema, {}, scopes={"parent": {"height": 2.0},
                                         "root": {"height": 10.0}})
    assert valori["h"] == pytest.approx(0.44)
    assert valori["r"] == pytest.approx(0.5)


def test_a_broken_expression_falls_back_and_is_reported():
    report = Report()
    schema = {"x": ParamSpec(7.0, derived="parent.non_esiste * 2")}
    assert resolve(schema, {}, scopes={"parent": {}}, report=report)["x"] == 7.0
    assert "PARAM_EXPRESSION" in report.codes()


@pytest.mark.parametrize("cattiva", [
    "__import__('os').system('x')", "open('/etc/passwd')", "a[0]",
    "lambda: 1", "self.__class__", "print(1)", "[1,2,3]",
])
def test_the_expression_language_refuses_anything_that_is_not_arithmetic(cattiva):
    with pytest.raises(ExpressionError):
        evaluate(cattiva, {"a": 1.0}, {"self": {"a": 1.0}})


def test_only_declared_scopes_are_reachable():
    with pytest.raises(ExpressionError, match="scope"):
        evaluate("altro.x", {}, {"self": {}})


def test_arithmetic_still_works():
    assert evaluate("max(1, 2) + clamp(9, 0, 3) * 2", {}) == pytest.approx(8.0)


# --------------------------------------------------------------------------- #
# Vincoli
# --------------------------------------------------------------------------- #
def test_a_violated_constraint_is_diagnosed_not_raised():
    report = Report()
    check([Constraint("spacing < width", message="escono dai bordi")],
          {"spacing": 2.0, "width": 1.0}, report=report)
    assert "CONSTRAINT_VIOLATED" in report.codes()
    assert "escono dai bordi" in report.describe()


def test_a_satisfied_constraint_says_nothing():
    report = Report()
    check([Constraint("a < b")], {"a": 1.0, "b": 2.0}, report=report)
    assert not report.entries


def test_a_clamping_constraint_corrects_itself():
    """La severita' utile: invece di segnalare, rimette a posto."""
    report = Report()
    valori = check([Constraint("spacing < width", severity=CLAMP,
                               target="spacing", to="width * 0.9",
                               message="occhi troppo distanti")],
                   {"spacing": 2.0, "width": 1.0},
                   schema={"spacing": ParamSpec(0.0, max=5.0)}, report=report)
    assert valori["spacing"] == pytest.approx(0.9)
    assert "CONSTRAINT_CLAMPED" in report.codes()


def test_a_constraint_can_read_the_parent():
    report = Report()
    check([Constraint("size < parent.size")], {"size": 3.0},
          scopes={"parent": {"size": 1.0}}, report=report)
    assert "CONSTRAINT_VIOLATED" in report.codes()


def test_an_unevaluable_constraint_does_not_stop_the_build():
    report = Report()
    check([Constraint("questo non e' valido ((")], {}, report=report)
    assert "CONSTRAINT_BROKEN" in report.codes() and report.ok


# --------------------------------------------------------------------------- #
# Component e Attachment
# --------------------------------------------------------------------------- #
def cubo(lato=1.0):
    def build(p, ctx):
        mesh = trimesh.creation.box((p["size"],) * 3)
        return Piece(mesh=mesh, sockets={
            "base": socket("base", (0, 0, 0), (-1, 0, 0),
                           radius=p["size"] * 0.5, provides="mount"),
            "top": socket("top", (0, p["size"] * 0.5, 0), (0, 1, 0),
                          radius=p["size"] * 0.4, provides=("mount", "anchor")),
        })
    return Component(id="prova:cubo", build=build,
                     params={"size": ParamSpec(lato, DISTANCE, 0.1, 10.0)},
                     provides=(Capability("blocco"),), tags={"prova"})


def test_a_component_declares_what_it_provides():
    c = cubo()
    assert c.plugin == "prova" and c.name == "cubo"
    assert c.provides_capability("blocco")


def test_a_component_with_no_declared_styles_fits_any_style():
    assert cubo().supports_style("qualunque_stile")


def test_a_component_can_exclude_styles():
    c = cubo()
    c.styles = frozenset({"low_poly"})
    assert c.supports_style("low_poly") and not c.supports_style("realistic")


def test_a_container_component_has_no_mesh_of_its_own():
    vuoto = Component(id="prova:contenitore",
                      build=lambda p, ctx: Piece(mesh=None))
    assert vuoto.build({}, BuildContext()).mesh is None


def test_structural_children_appear_with_the_detail_level():
    figlio = Attachment(id="a", component="prova:cubo", level=3)
    assert not figlio.wanted_at(2)
    assert figlio.wanted_at(3)


def test_a_decoration_is_a_component_plus_an_attachment():
    """Non esiste una classe Decoration: e' un componente montato diversamente."""
    decorazione = Attachment(id="ciondolo", component="prova:cubo",
                             optional=True, on_request=True)
    assert not decorazione.structural
    assert not decorazione.wanted_at(99), "non compare col livello"
    assert decorazione.wanted_at(1, requested=True), "compare se la chiedi"


def test_an_explicit_decoration_does_not_require_a_detailed_tree():
    """«una testa semplice con un piercing» deve restare semplice."""
    c = cubo()
    c.children = lambda p, ctx: [
        Attachment(id="dettaglio_fine", component="prova:cubo", level=4),
        Attachment(id="piercing", component="prova:cubo", on_request=True),
    ]
    figli = c.expand({"size": 1.0}, BuildContext(detail_level=1),
                     requested=["piercing"])
    assert [a.id for a in figli] == ["piercing"]


def test_the_same_component_can_be_structure_or_decoration():
    strutturale = Attachment(id="x", component="prova:cubo", level=1)
    decorativo = Attachment(id="y", component="prova:cubo", on_request=True)
    assert strutturale.structural and not decorativo.structural


# --------------------------------------------------------------------------- #
# Dimostrazione: due vocabolari, un solo contratto
# --------------------------------------------------------------------------- #
def piramide():
    """Un componente di un "altro plugin", con misure sue e un attacco suo."""
    def build(p, ctx):
        mesh = trimesh.creation.cone(radius=p["raggio"], height=p["raggio"] * 3)
        return Piece(mesh=mesh, sockets={
            "innesto": socket("innesto", (0, 0, 0), (0, -1, 0),
                              radius=p["raggio"], provides="mount")})
    return Component(id="altrove:guglia", build=build,
                     params={"raggio": ParamSpec(3.0, DISTANCE, 0.1, 20.0)},
                     tags={"altrove"})


def test_two_components_from_different_vocabularies_compose():
    """La prova che i contratti bastano: nessun registry, nessun resolver.

    Il cubo non sa che cosa sia una guglia, la guglia non sa che cosa sia un
    cubo, e il core non sa che cosa siano entrambi. Si incontrano su una
    capability e su un socket, e ne esce una mesh.
    """
    ctx = BuildContext()
    base = cubo().build(resolve(cubo().params, {"size": 1.0}), ctx)
    punta_regola = piramide()
    punta = punta_regola.build(resolve(punta_regola.params, {}), ctx)

    richiesta = Requirement(capability="mount")
    presa_padre, punteggio = best_match(richiesta, base.sockets.values())
    assert punteggio >= CAPABILITY

    posa = attach(Placement(), presa_padre, punta.sockets["innesto"],
                  scale_mode="socket", insert=0.0)

    montata = punta.mesh.copy()
    montata.apply_transform(posa.matrix())
    insieme = trimesh.util.concatenate([base.mesh, montata])

    # la guglia e' larga 3 di suo: senza adattamento coprirebbe il cubo
    assert posa.scale < 1.0, "la parte estranea si e' portata al raggio dell'innesto"
    assert insieme.extents[1] > base.mesh.extents[1], "la guglia sta sopra il cubo"
    assert len(insieme.faces) > len(base.mesh.faces)


def test_the_composition_is_deterministic():
    """Stesso contratto, stesso risultato: due costruzioni identiche."""
    def costruisci():
        ctx = BuildContext()
        base = cubo().build(resolve(cubo().params, {"size": 1.0}), ctx)
        p = piramide()
        punta = p.build(resolve(p.params, {}), ctx)
        presa, _ = best_match(Requirement(capability="mount"), base.sockets.values())
        return attach(Placement(), presa, punta.sockets["innesto"],
                      scale_mode="socket").matrix()

    assert np.allclose(costruisci(), costruisci())


def test_the_core_does_not_know_any_category():
    """Nessun modulo del core nomina un plugin o una categoria del mondo."""
    import pathlib
    import re

    proibiti = re.compile(
        r"\b(humanoid|umanoide|animal|animale|dragon|drago|planet|pianeta|"
        r"house|casa|vehicle|veicolo|weapon|arma|creature|creatura|tree|albero|"
        r"frog|rana|fish|pesce)\b", re.I)
    core = pathlib.Path(__file__).resolve().parents[1] / "app" / "core"
    nuovi = ("capability.py", "socket.py", "params.py", "constraints.py",
             "component.py", "errors.py")
    for nome in nuovi:
        testo = (core / nome).read_text(encoding="utf-8")
        # i commenti possono usare esempi; il codice no
        codice = "\n".join(r for r in testo.splitlines()
                           if not r.strip().startswith("#"))
        codice = re.sub(r'""".*?"""', "", codice, flags=re.S)
        trovati = set(proibiti.findall(codice))
        assert not trovati, "%s nomina %s" % (nome, sorted(trovati))


def test_no_new_module_imports_the_old_path():
    """La regola che impedisce di restare con due sistemi per sempre.

    Il vecchio percorso (ricette SDF, composizione per fusione, strategie) resta
    finche' i banchi non sono migrati. Ma niente di nuovo deve appoggiarcisi:
    se `core` o `plugins` cominciano a importarlo, la transizione non finisce
    piu' e ci si ritrova con due codebase invece di una.
    """
    import pathlib
    import re

    vecchi = re.compile(
        r"(from|import)\s+app\.(geometry\.(recipe|composition)|build\.strategy)")
    radice = pathlib.Path(__file__).resolve().parents[1] / "app"
    colpevoli = []
    for cartella in ("core", "plugins"):
        for file in (radice / cartella).rglob("*.py"):
            for numero, riga in enumerate(file.read_text(encoding="utf-8").splitlines(), 1):
                if vecchi.search(riga):
                    colpevoli.append("%s:%d  %s" % (file.name, numero, riga.strip()))
    assert not colpevoli, "\n".join(colpevoli)


def test_the_new_pipeline_never_reaches_for_the_old_one():
    """Il percorso nuovo, per intero, non importa niente di quello storico.

    E' la stessa regola di sopra, portata dove adesso vive il sistema: piano,
    vocabolario, planner, resolver, effetti, builder e validatore devono poter
    stare in piedi senza il mondo dei template e del campo implicito. Se un
    giorno uno di loro ci si appoggia, la migrazione non finisce piu'.
    """
    import pathlib
    import re

    vecchi = re.compile(r"(from|import)\s+app\.(build\.(builder|strategy|validation"
                        r"|optimize)|geometry\.(recipe|composition|templates)"
                        r"|ai\.(planner|creature|reference)|core\.spec|core\.scene)")
    radice = pathlib.Path(__file__).resolve().parents[1] / "app"
    nuovi = list((radice / "core" / "planner").rglob("*.py"))
    nuovi += [radice / "build" / "assembler.py", radice / "build" / "validate.py"]
    nuovi += [radice / "core" / nome for nome in
              ("graph.py", "resolver.py", "resolved.py", "effect.py",
               "vocabulary.py", "registry.py", "component.py", "authoring.py")]

    colpevoli = []
    for file in nuovi:
        for numero, riga in enumerate(file.read_text(encoding="utf-8").splitlines(), 1):
            if vecchi.search(riga):
                colpevoli.append("%s:%d  %s" % (file.name, numero, riga.strip()))
    assert not colpevoli, "\n".join(colpevoli)


def test_the_session_is_the_only_bridge_between_the_two_roads():
    """Un solo file tiene tutte e due le strade, e si vede quale.

    La `Session` importa ancora il builder storico, perche' `generate_legacy`,
    la libreria e l'animazione ci girano sopra; `project` lo importa per
    riaprire una cronologia salvata. Sono i due ponti rimasti, e questo test li
    fissa: quando la strada vecchia verra' tolta ci saranno due posti da
    cambiare, e finche' non lo si fa nessun terzo modulo puo' aggiungersi.
    """
    import pathlib
    import re

    ponte = re.compile(r"from\s+app\.build\.builder\s+import")
    radice = pathlib.Path(__file__).resolve().parents[1] / "app"
    files = sorted(p.relative_to(radice).as_posix()
                   for p in (radice / "core").rglob("*.py")
                   if ponte.search(p.read_text(encoding="utf-8")))
    # `project` ricostruisce le scene di una cronologia salvata, che sono fatte
    # di `GenerationPlan`: finche' esistono progetti vecchi da riaprire, quel
    # ponte serve. Sono due, sono questi, e non devono diventare tre.
    assert files == ["core/project.py", "core/session.py"], files
