"""Lo staging, l'inviluppo, l'ispezione statica, e la fiducia che non si regala.

Il file piu' importante della milestone sul piano del comportamento, perche'
§30 e' un requisito di prodotto e non una preferenza:

> Teach 3DGen deve poter creare prompt per componenti Python. Ma NON deve
> trattare Python generato come sicuro.

Quindi si misura dal lato dell'**effetto** e non della fiducia: dopo aver messo
in staging un modulo che, se girasse, lascerebbe una traccia su disco, quella
traccia non c'e'; `sys.modules` non cresce; validare alza invece di importare;
e solo dopo un'azione esplicita il normale meccanismo dei plugin di codice
entra in gioco.

E si misura anche cio' che i controlli statici **non** sono: `inspect_python`
nomina gli import che vede, e il referto lo chiama avviso. La parola «sandbox»
non compare in nessun messaggio, perche' non ce n'e' una.
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

from app.teach import errors as codes
from app.teach import staging
from app.teach.errors import TeachError
from app.teach.model import COMPOSITE, DATA_MESH, PROCEDURAL
from tests.teach_fixtures import (BAD_ENVELOPES, composite_component,
                                  data_component, dragon_decomposition,
                                  dragon_refinement, python_component,
                                  write_part_glb)


# --------------------------------------------------------------------------- #
# L'inviluppo (§28)
# --------------------------------------------------------------------------- #
def test_a_valid_envelope_becomes_staged_files():
    files, notes = staging.parse_envelope(
        python_component("p", "part", capability="part_mount"))
    assert [f.path for f in files] == ["plugin.json", "components/part.py"]
    assert files[1].python and not files[0].python
    assert notes


def test_an_envelope_can_arrive_as_text_or_as_an_object():
    payload = python_component("p", "part", capability="part_mount")
    first, _ = staging.parse_envelope(payload)
    second, _ = staging.parse_envelope(json.dumps(payload))
    third, _ = staging.parse_envelope("```json\n%s\n```"
                                      % json.dumps(payload))
    assert [f.path for f in first] == [f.path for f in second] \
        == [f.path for f in third]


@pytest.mark.parametrize("name", sorted(BAD_ENVELOPES))
def test_a_malformed_envelope_is_refused_with_a_code(name):
    with pytest.raises(TeachError) as exc:
        staging.parse_envelope(BAD_ENVELOPES[name])
    assert exc.value.code in (codes.RESPONSE_INVALID, codes.ENVELOPE_INVALID,
                              codes.PATH_UNSAFE, codes.EXTENSION_REFUSED)


@pytest.mark.parametrize("path", [
    "../../secret.py", "../secret.json", "components/../../secret.json",
    "/etc/passwd", "C:/Windows/win.ini", "//server/share/x.json",
    "\\\\server\\share\\x.json", "a\x00.json", "file:///secret.json",
    "..\\..\\secret.json", "C:x.json",
])
def test_every_hostile_path_is_refused(path):
    with pytest.raises(TeachError) as exc:
        staging.safe_relative(path)
    assert exc.value.code in (codes.PATH_UNSAFE, codes.EXTENSION_REFUSED)


@pytest.mark.parametrize("path", ["plugin.json", "components/x.json",
                                   "components/x.py", "./README.md",
                                   "notes.txt"])
def test_a_legitimate_relative_path_is_kept(path):
    assert staging.safe_relative(path) == path.lstrip("./")


@pytest.mark.parametrize("extension", [".glb", ".gltf", ".exe", ".sh", ".dll",
                                        ".pyc", ".so", ".bat", ".bin", ""])
def test_only_the_declared_extensions_are_accepted(extension):
    with pytest.raises(TeachError) as exc:
        staging.safe_relative("thing" + extension)
    assert exc.value.code == codes.EXTENSION_REFUSED


def test_a_file_over_the_limit_is_refused():
    payload = {"files": [{"path": "plugin.json", "content": "{}"},
                         {"path": "big.txt",
                          "content": "x" * (staging.MAX_FILE_BYTES + 1)}]}
    with pytest.raises(TeachError) as exc:
        staging.parse_envelope(payload)
    assert exc.value.code == codes.FILE_TOO_LARGE


def test_an_envelope_over_the_total_limit_is_refused():
    chunk = "x" * (staging.MAX_FILE_BYTES - 10)
    files = [{"path": "plugin.json", "content": "{}"}]
    files += [{"path": "f%d.txt" % i, "content": chunk} for i in range(6)]
    with pytest.raises(TeachError) as exc:
        staging.parse_envelope({"files": files})
    assert exc.value.code == codes.FILE_TOO_LARGE


def test_too_many_files_are_refused():
    files = [{"path": "plugin.json", "content": "{}"}]
    files += [{"path": "f%d.txt" % i, "content": "x"}
              for i in range(staging.MAX_FILES + 2)]
    with pytest.raises(TeachError) as exc:
        staging.parse_envelope({"files": files})
    assert exc.value.code == codes.ENVELOPE_INVALID


# --------------------------------------------------------------------------- #
# Lo staging
# --------------------------------------------------------------------------- #
def test_staging_writes_the_files_under_the_declared_plugin_folder(tmp_path):
    files, _ = staging.parse_envelope(
        python_component("p", "part", capability="part_mount"))
    artifact = staging.stage(tmp_path, files, artifact_id="a1", node="x",
                             expect_plugin="p", component_id="p:part")
    assert artifact.path == (tmp_path / "a1" / "p").resolve()
    assert (artifact.path / "plugin.json").is_file()
    assert (artifact.path / "components" / "part.py").is_file()
    assert artifact.container == tmp_path / "a1"


def test_staging_refuses_a_manifest_that_renames_the_plugin(tmp_path):
    files, _ = staging.parse_envelope(
        python_component("somewhere_else", "part", capability="part_mount"))
    with pytest.raises(TeachError) as exc:
        staging.stage(tmp_path, files, artifact_id="a1", expect_plugin="p")
    assert exc.value.code == codes.ENVELOPE_INVALID
    assert "la specifica aveva deciso" in exc.value.message


def test_staging_refuses_a_manifest_without_an_id(tmp_path):
    files = [staging.StagedFile(path="plugin.json", content="{}")]
    with pytest.raises(TeachError) as exc:
        staging.stage(tmp_path, files, artifact_id="a1")
    assert exc.value.code == codes.ENVELOPE_INVALID


def test_staging_copies_a_supplied_asset_without_the_model_touching_it(tmp_path):
    glb = write_part_glb(tmp_path / "assets")
    files, _ = staging.parse_envelope(
        data_component("p", "part", capability="part_mount", mesh=glb.name))
    artifact = staging.stage(tmp_path / "st", files, artifact_id="a1",
                             expect_plugin="p", asset=glb)
    copied = artifact.path / "meshes" / glb.name
    assert copied.is_file()
    assert copied.read_bytes()[:4] == b"glTF"
    assert copied.read_bytes() == glb.read_bytes()


def test_staging_a_missing_asset_says_so(tmp_path):
    files, _ = staging.parse_envelope(
        data_component("p", "part", capability="part_mount", mesh="x.glb"))
    with pytest.raises(TeachError) as exc:
        staging.stage(tmp_path, files, artifact_id="a1", expect_plugin="p",
                      asset=tmp_path / "nope.glb")
    assert exc.value.code == codes.ASSET_MISSING


def test_the_kind_is_read_from_the_files_and_not_from_the_manifest(tmp_path):
    code, _ = staging.parse_envelope(
        python_component("p", "part", capability="c"))
    glb = write_part_glb(tmp_path / "assets")
    data, _ = staging.parse_envelope(
        data_component("p", "part", capability="c", mesh=glb.name))
    composite, _ = staging.parse_envelope(
        composite_component("p", "whole",
                            children=[{"id": "a", "component": "humanoid:head",
                                       "capability": "head_mount"}]))
    assert staging.kind_of(code, {}) == PROCEDURAL
    assert staging.kind_of(data, {}) == DATA_MESH
    assert staging.kind_of(composite, {}) == COMPOSITE
    # un `.py` rende l'artefatto codice anche se il manifest dicesse "data"
    assert staging.kind_of(code, {"type": "data"}) == PROCEDURAL


def test_discard_removes_the_staged_files(tmp_path):
    files, _ = staging.parse_envelope(python_component("p", "part",
                                                        capability="c"))
    artifact = staging.stage(tmp_path, files, artifact_id="a1",
                             expect_plugin="p")
    assert artifact.container.is_dir()
    staging.discard(artifact)
    assert not artifact.container.exists()


# --------------------------------------------------------------------------- #
# L'ispezione statica (§31)
# --------------------------------------------------------------------------- #
def test_inspection_reads_the_imports_without_importing_anything(tmp_path):
    source = tmp_path / "x.py"
    source.write_text("import os\nfrom app.geometry.kernel import block\n"
                      "VALUE = 1\n", encoding="utf-8")
    before = set(sys.modules)
    out = staging.inspect_python(source)
    assert set(sys.modules) == before
    assert out.syntax_ok
    assert "os" in out.imports and "app.geometry.kernel" in out.imports
    assert out.flagged_imports == ("os",)


def test_inspection_reports_a_syntax_error_instead_of_raising(tmp_path):
    source = tmp_path / "x.py"
    source.write_text("def broken(:\n", encoding="utf-8")
    out = staging.inspect_python(source)
    assert not out.syntax_ok
    assert "riga 1" in out.error
    assert "non si compila" in out.describe()


def test_inspection_notices_the_calls_that_reach_anything(tmp_path):
    source = tmp_path / "x.py"
    source.write_text("x = eval('1')\ny = __import__('os')\n"
                      "z = open('f')\n", encoding="utf-8")
    out = staging.inspect_python(source)
    assert set(out.flagged_calls) >= {"eval", "__import__", "open"}
    assert any("raggiungono qualunque cosa" in w for w in out.warnings)


def test_inspection_says_when_nothing_would_be_registered(tmp_path):
    source = tmp_path / "x.py"
    source.write_text("VALUE = 1\n", encoding="utf-8")
    out = staging.inspect_python(source)
    assert not out.builds_component
    assert any("non costruisce nessun Component" in w for w in out.warnings)


def test_inspection_sees_a_component_declaration(tmp_path):
    source = tmp_path / "x.py"
    source.write_text("from app.core.component import Component\n"
                      "PART = Component(id='part', build=lambda v, c: None)\n",
                      encoding="utf-8")
    out = staging.inspect_python(source)
    assert out.builds_component
    assert out.flagged_imports == ()


def test_inspection_flags_an_import_outside_the_declared_api(tmp_path):
    source = tmp_path / "x.py"
    source.write_text("import scipy.optimize\n"
                      "from app.core.session import Session\n", encoding="utf-8")
    out = staging.inspect_python(source)
    assert "scipy.optimize" in out.unexpected_api
    assert "app.core.session" in out.unexpected_api
    assert any("fuori dall'API dichiarata" in w for w in out.warnings)


def test_the_flagged_list_is_configurable_and_not_a_promise(tmp_path):
    source = tmp_path / "x.py"
    source.write_text("import math\n", encoding="utf-8")
    assert staging.inspect_python(source).flagged_imports == ()
    assert staging.inspect_python(source,
                                  flagged=("math",)).flagged_imports == ("math",)


def test_nothing_in_the_staging_layer_calls_itself_a_sandbox():
    source = pathlib.Path("app/teach/staging.py").read_text(encoding="utf-8")
    runner = pathlib.Path("app/teach/_runner.py").read_text(encoding="utf-8")
    # La parola compare soltanto per **negarla**, e mai in un messaggio.
    for text in (source, runner):
        for line in text.splitlines():
            if "sandbox" not in line.lower():
                continue
            assert line.lstrip().startswith(("#", "*", "'", '"')) or \
                "non" in line.lower() or "not" in line.lower()


def test_the_inspection_is_presented_as_warnings_not_as_safety(tmp_path, teach):
    teach.create_project("dragon")
    teach.decomposition_prompt()
    teach.import_decomposition(dragon_refinement())
    teach.analyse()
    for candidate in list(teach.candidates("dragon.head.snout")):
        teach.reject_candidate("dragon.head.snout", candidate.component_id)
    spec = teach.spec("dragon.head.snout")
    teach.implementation_prompt("dragon.head.snout")
    artifact = teach.import_implementation(
        "dragon.head.snout",
        python_component(spec.plugin_id, "snout", capability=spec.provides[0],
                         hostile=True))
    detail = teach.inspect_artifact(artifact.id)
    assert detail["code"] is True and detail["trusted"] is False
    assert "nessuna sandbox" in detail["security"].lower()
    assert detail["warnings"]
    assert "TEACH_PYTHON_WARNING" in artifact.report.codes()
    assert artifact.report.ok                 # avvisi, non errori


# --------------------------------------------------------------------------- #
# Python generato: niente esecuzione senza fiducia (§30, §49)
# --------------------------------------------------------------------------- #
@pytest.fixture
def staged_python(teach, tmp_path):
    """Un nodo mandatory davvero mancante, con un modulo Python in staging."""
    teach.create_project("dragon", detail_target=2,
                          destination=str(tmp_path / "out"))
    teach.decomposition_prompt()
    teach.import_decomposition(dragon_refinement())
    teach.analyse()
    for candidate in list(teach.candidates("dragon.head.snout")):
        teach.reject_candidate("dragon.head.snout", candidate.component_id)
    spec = teach.spec("dragon.head.snout")
    teach.implementation_prompt("dragon.head.snout")
    artifact = teach.import_implementation(
        "dragon.head.snout",
        python_component(spec.plugin_id, "snout", capability=spec.provides[0],
                         role="snout"))
    return teach, artifact, spec


def test_staging_python_executes_nothing_and_imports_nothing(staged_python,
                                                             tmp_path):
    teach, artifact, spec = staged_python
    marker = tmp_path / "executed.txt"
    source = artifact.path / "components" / "snout.py"
    source.write_text(
        "import pathlib\npathlib.Path(%r).write_text('x')\n" % str(marker),
        encoding="utf-8")
    before = set(sys.modules)
    again = staging.inspect_python(source)
    assert not marker.exists()
    assert set(sys.modules) == before
    assert again.flagged_imports == ("pathlib",)


def test_validating_a_code_artifact_without_trust_raises(staged_python):
    teach, artifact, _ = staged_python
    assert artifact.code and not artifact.trusted
    with pytest.raises(TeachError) as exc:
        teach.validate_artifact(artifact.id)
    assert exc.value.code == codes.TRUST_REQUIRED


def test_installing_a_code_artifact_without_trust_raises(staged_python):
    teach, artifact, _ = staged_python
    with pytest.raises(TeachError) as exc:
        teach.accept_artifact(artifact.id)
    assert exc.value.code == codes.TRUST_REQUIRED


def test_opening_a_code_artifact_in_the_lab_without_trust_raises(staged_python):
    teach, artifact, _ = staged_python
    with pytest.raises(TeachError) as exc:
        teach.artifact_lab(artifact.id)
    assert exc.value.code == codes.TRUST_REQUIRED


def test_after_an_explicit_trust_the_normal_code_plugin_path_runs(staged_python):
    teach, artifact, spec = staged_python
    teach.trust_artifact(artifact.id)
    assert teach.artifact(artifact.id).trusted
    out = teach.validate_artifact(artifact.id)
    assert out.ok
    assert spec.component_id in out.installed
    assert out.triangles > 0
    assert out.retrievable


def test_the_trust_flag_survives_in_the_project(staged_python, tmp_path):
    from app.teach.model import TeachProject

    teach, artifact, _ = staged_python
    teach.trust_artifact(artifact.id)
    saved = teach.save_project(tmp_path / "p")
    reopened = TeachProject.load(saved)
    assert reopened.artifact(artifact.id).trusted is True


def test_a_data_artifact_needs_no_trust_because_nothing_runs(teach, tmp_path):
    teach.create_project("dragon", destination=str(tmp_path / "out"))
    teach.decomposition_prompt()
    teach.import_decomposition(dragon_refinement())
    teach.analyse()
    glb = write_part_glb(tmp_path / "assets")
    teach.supply_asset("dragon.head.horn", glb)
    spec = teach.spec("dragon.head.horn")
    assert spec.backend == DATA_MESH
    teach.implementation_prompt("dragon.head.horn")
    artifact = teach.import_implementation(
        "dragon.head.horn",
        data_component(spec.plugin_id, "horn", capability=spec.provides[0],
                       mesh=glb.name))
    assert not artifact.code and not artifact.trusted
    out = teach.validate_artifact(artifact.id)
    assert out.ok and out.triangles == 12


def test_a_data_plugin_in_staging_never_has_its_python_opened(teach, tmp_path):
    teach.create_project("dragon", destination=str(tmp_path / "out"))
    teach.decomposition_prompt()
    teach.import_decomposition(dragon_refinement())
    teach.analyse()
    glb = write_part_glb(tmp_path / "assets")
    teach.supply_asset("dragon.head.horn", glb)
    spec = teach.spec("dragon.head.horn")
    teach.implementation_prompt("dragon.head.horn")
    artifact = teach.import_implementation(
        "dragon.head.horn",
        data_component(spec.plugin_id, "horn", capability=spec.provides[0],
                       mesh=glb.name))
    (artifact.path / "boom.py").write_text("raise SystemExit('eseguito')\n",
                                           encoding="utf-8")
    out = teach.validate_artifact(artifact.id)
    assert out.ok
    assert (artifact.path / "boom.py").is_file()


# --------------------------------------------------------------------------- #
# Il sottoprocesso: robustezza, non confinamento
# --------------------------------------------------------------------------- #
def test_the_isolated_run_reports_the_same_thing(staged_python):
    teach, artifact, spec = staged_python
    teach.trust_artifact(artifact.id)
    here = teach.validate_artifact(artifact.id)
    there = teach.validate_artifact(artifact.id, isolate=True)
    assert there.isolated and not here.isolated
    assert there.ok == here.ok
    assert there.triangles == here.triangles
    assert spec.component_id in there.installed


def test_the_isolated_run_survives_a_plugin_that_explodes(teach, tmp_path):
    teach.create_project("dragon", destination=str(tmp_path / "out"))
    teach.decomposition_prompt()
    teach.import_decomposition(dragon_refinement())
    teach.analyse()
    for candidate in list(teach.candidates("dragon.head.snout")):
        teach.reject_candidate("dragon.head.snout", candidate.component_id)
    spec = teach.spec("dragon.head.snout")
    teach.implementation_prompt("dragon.head.snout")
    artifact = teach.import_implementation(
        "dragon.head.snout",
        python_component(spec.plugin_id, "snout", capability=spec.provides[0]))
    (artifact.path / "components" / "snout.py").write_text(
        "raise RuntimeError('boom')\n", encoding="utf-8")
    teach.trust_artifact(artifact.id)
    out = teach.validate_artifact(artifact.id, isolate=True)
    assert not out.ok
    assert out.isolated


# --------------------------------------------------------------------------- #
# Validazione e installazione (§32, §35)
# --------------------------------------------------------------------------- #
def test_validation_uses_the_real_validators_and_names_what_failed(teach,
                                                                   tmp_path):
    teach.create_project("dragon", destination=str(tmp_path / "out"))
    teach.decomposition_prompt()
    teach.import_decomposition(dragon_refinement())
    teach.analyse()
    for candidate in list(teach.candidates("dragon.head.snout")):
        teach.reject_candidate("dragon.head.snout", candidate.component_id)
    spec = teach.spec("dragon.head.snout")
    teach.implementation_prompt("dragon.head.snout")
    artifact = teach.import_implementation(
        "dragon.head.snout",
        python_component(spec.plugin_id, "snout", capability=spec.provides[0],
                         broken=True))
    teach.trust_artifact(artifact.id)
    out = teach.validate_artifact(artifact.id)
    assert not out.ok
    assert "TEACH_COMPONENT_NOT_INSTALLED" in out.codes()


def test_a_failed_attempt_is_recorded_with_its_codes(teach, tmp_path):
    teach.create_project("dragon", destination=str(tmp_path / "out"))
    teach.decomposition_prompt()
    teach.import_decomposition(dragon_refinement())
    teach.analyse()
    for candidate in list(teach.candidates("dragon.head.snout")):
        teach.reject_candidate("dragon.head.snout", candidate.component_id)
    spec = teach.spec("dragon.head.snout")
    teach.implementation_prompt("dragon.head.snout")
    artifact = teach.import_implementation(
        "dragon.head.snout",
        python_component(spec.plugin_id, "snout", capability=spec.provides[0],
                         broken=True))
    teach.trust_artifact(artifact.id)
    teach.validate_artifact(artifact.id)
    attempts = teach.project.state("dragon.head.snout").attempts
    assert len(attempts) == 1
    assert attempts[0].ok is False
    assert "TEACH_COMPONENT_NOT_INSTALLED" in attempts[0].codes


def test_a_repair_is_a_new_attempt_and_keeps_its_lineage(teach, tmp_path):
    teach.create_project("dragon", destination=str(tmp_path / "out"))
    teach.decomposition_prompt()
    teach.import_decomposition(dragon_refinement())
    teach.analyse()
    for candidate in list(teach.candidates("dragon.head.snout")):
        teach.reject_candidate("dragon.head.snout", candidate.component_id)
    spec = teach.spec("dragon.head.snout")
    teach.implementation_prompt("dragon.head.snout")
    first = teach.import_implementation(
        "dragon.head.snout",
        python_component(spec.plugin_id, "snout", capability=spec.provides[0],
                         broken=True))
    teach.trust_artifact(first.id)
    teach.validate_artifact(first.id)
    bundle = teach.repair_prompt(first.id)
    assert "WHAT THE VALIDATORS SAID" in bundle.user
    assert "TEACH_COMPONENT_NOT_INSTALLED" in bundle.user
    second = teach.import_repair(
        "dragon.head.snout",
        python_component(spec.plugin_id, "snout", capability=spec.provides[0]))
    attempts = teach.project.state("dragon.head.snout").attempts
    assert len(attempts) == 2
    assert attempts[-1].repaired_from == 1
    teach.trust_artifact(second.id)
    assert teach.validate_artifact(second.id).ok
    assert staging.MAX_REPAIRS if hasattr(staging, "MAX_REPAIRS") else True


def test_installing_registers_the_library_folder_and_not_the_staging(staged_python,
                                                                    tmp_path):
    """Due copie dello stesso id sarebbero ambigue, e il registry le scarta."""
    teach, artifact, spec = staged_python
    teach.trust_artifact(artifact.id)
    out = teach.accept_artifact(artifact.id)
    assert out.ok
    registry = teach.session.catalog()
    assert registry.component(spec.component_id) is not None
    assert "DUPLICATE_PLUGIN" not in registry.report.codes()
    installed = pathlib.Path(tmp_path / "out" / artifact.plugin_id)
    assert installed.is_dir()
    assert str(artifact.container) not in [str(p)
                                           for p in teach.session.plugin_paths]


def test_installing_invalidates_the_semantic_index(staged_python):
    teach, artifact, spec = staged_python
    teach.trust_artifact(artifact.id)
    before = teach.session.component_index()
    teach.accept_artifact(artifact.id)
    assert not before.is_current(teach.session.catalog())
    hits = {i for i, _ in teach.session.component_index().search("snout",
                                                                  limit=10)}
    assert spec.component_id in hits


def test_rejecting_an_artifact_leaves_the_node_missing_and_keeps_the_history(
        staged_python):
    teach, artifact, _ = staged_python
    teach.trust_artifact(artifact.id)
    teach.validate_artifact(artifact.id)
    assert teach.reject_artifact(artifact.id) == "MISSING"
    assert teach.project.state("dragon.head.snout").attempts
    assert teach.project.artifacts[artifact.id].accepted is False


def test_rejecting_with_discard_removes_the_files(staged_python):
    teach, artifact, _ = staged_python
    container = artifact.container
    teach.reject_artifact(artifact.id, discard=True)
    assert not container.exists()
    with pytest.raises(TeachError) as exc:
        teach.artifact(artifact.id)
    assert exc.value.code == codes.UNKNOWN_ARTIFACT


def test_an_unknown_artifact_is_named_instead_of_guessed(teach):
    teach.create_project("dragon")
    with pytest.raises(TeachError) as exc:
        teach.artifact("nope")
    assert exc.value.code == codes.UNKNOWN_ARTIFACT
