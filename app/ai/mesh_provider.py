"""Generazione AI di mesh: la quarta strategia, l'ultima risorsa.

Serve per cio' che nemmeno la composizione riesce a esprimere. Non e' la strada
principale e non deve diventarlo: e' lenta, costa, e non si controlla. Qui c'e'
l'interfaccia, la pulizia di cio' che arriva e il ripiego automatico; il
provider vero richiede un servizio esterno.

Una mesh che arriva da fuori non e' utilizzabile com'e': puo' avere normali
invertite, vertici doppi, scala arbitraria, orientamento casuale e nessun punto
di attacco. `clean_incoming` la riporta nelle convenzioni del progetto prima che
tocchi la scena.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import trimesh

from app.core.logging_setup import get

log = get("ai.mesh")


@dataclass
class MeshRequest:
    """Cosa si chiede al generatore, e dentro quali vincoli."""

    prompt: str
    target_size: float = 1.0          # dimensione massima desiderata, in metri
    socket_radius: float = 0.0        # se > 0, la parte va innestata li'
    up_axis: int = 1
    forward_axis: int = 0
    max_faces: int = 40_000
    timeout: float = 60.0
    seed: int = 0


class MeshGenerationError(RuntimeError):
    pass


class MeshGenerator(ABC):
    """Contratto comune a ogni fornitore di mesh."""

    name = "abstract"

    @abstractmethod
    def available(self) -> bool:
        """Falso se manca la chiave, il servizio o la connessione."""

    @abstractmethod
    def generate(self, request: MeshRequest) -> trimesh.Trimesh:
        """Mesh grezza, nelle unita' e nell'orientamento del fornitore."""


# --------------------------------------------------------------------------- #
# Pulizia: nessuna mesh esterna entra in scena com'e'
# --------------------------------------------------------------------------- #
def clean_incoming(mesh: trimesh.Trimesh, request: MeshRequest) -> trimesh.Trimesh:
    """Riporta una mesh esterna nelle convenzioni del progetto.

    Fonde i vertici coincidenti, toglie le facce degeneri, ricalcola le
    normali, scala alla dimensione chiesta e appoggia l'origine sulla base,
    dove il resto del sistema si aspetta di trovarla.
    """
    if mesh is None or len(mesh.faces) == 0:
        raise MeshGenerationError("mesh vuota")

    out = mesh.copy()
    out.merge_vertices()
    try:
        out.update_faces(out.nondegenerate_faces())
        out.update_faces(out.unique_faces())
    except Exception:
        pass
    out.remove_unreferenced_vertices()
    if len(out.faces) == 0:
        raise MeshGenerationError("dopo la pulizia non resta geometria")

    try:
        out.fix_normals()
    except Exception as exc:
        log.warning("normali non ricalcolate: %s", exc)

    if len(out.faces) > request.max_faces:
        from app.build.optimize import decimate_to

        out = decimate_to(out, request.max_faces)

    extents = out.bounds[1] - out.bounds[0]
    longest = float(np.max(extents))
    if longest > 1e-6 and request.target_size > 0:
        out.apply_scale(request.target_size / longest)

    # origine al centro della base: la stessa convenzione dei template
    lower = out.bounds[0]
    centre = (out.bounds[0] + out.bounds[1]) / 2.0
    out.apply_translation([-centre[0], -lower[1], -centre[2]])
    return out


def quality_report(mesh: trimesh.Trimesh) -> dict[str, Any]:
    """Cosa e' arrivato davvero: serve a decidere se tenerla."""
    components = 1
    try:
        components = len(mesh.split(only_watertight=False))
    except Exception:
        pass
    return {
        "faces": len(mesh.faces),
        "vertices": len(mesh.vertices),
        "watertight": bool(mesh.is_watertight),
        "components": components,
        "volume": float(mesh.volume) if mesh.is_watertight else 0.0,
    }


def is_acceptable(mesh: trimesh.Trimesh, min_faces: int = 50,
                  max_components: int = 12) -> tuple[bool, str]:
    """Filtro minimo: una mesh AI inutilizzabile non deve entrare in scena."""
    report = quality_report(mesh)
    if report["faces"] < min_faces:
        return False, "troppo poche facce (%d)" % report["faces"]
    if report["components"] > max_components:
        return False, "troppi pezzi separati (%d)" % report["components"]
    extents = mesh.bounds[1] - mesh.bounds[0]
    if float(np.min(extents)) <= 1e-6:
        return False, "geometria piatta o degenere"
    return True, "ok"


# --------------------------------------------------------------------------- #
# Fornitori
# --------------------------------------------------------------------------- #
class HuggingFaceMeshGenerator(MeshGenerator):
    """Modelli text-to-3D ospitati (Hunyuan3D, TripoSR e simili).

    **Richiede un servizio esterno**: chiave HuggingFace e un modello che
    esponga l'inferenza. Senza, `available()` e' falso e il gestore delle
    strategie passa oltre senza che l'utente se ne accorga.
    """

    name = "huggingface"

    def __init__(self, model: str = "", api_key: str = "") -> None:
        from app.core.config import SETTINGS

        self.model = model or "tencent/Hunyuan3D-2"
        self.api_key = api_key or SETTINGS.api_key("huggingface")
        self.endpoint = "https://api-inference.huggingface.co/models/%s" % self.model

    def available(self) -> bool:
        return bool(self.api_key)

    def generate(self, request: MeshRequest) -> trimesh.Trimesh:
        import io

        import requests

        if not self.available():
            raise MeshGenerationError("nessuna chiave per %s" % self.name)
        try:
            response = requests.post(
                self.endpoint,
                headers={"Authorization": "Bearer %s" % self.api_key},
                json={"inputs": request.prompt},
                timeout=request.timeout,
            )
        except Exception as exc:
            raise MeshGenerationError("servizio irraggiungibile: %s" % exc) from exc

        if response.status_code >= 400:
            raise MeshGenerationError("%s ha risposto %d: %s"
                                      % (self.name, response.status_code, response.text[:160]))
        try:
            return trimesh.load(io.BytesIO(response.content), file_type="glb", force="mesh")
        except Exception as exc:
            raise MeshGenerationError("risposta non interpretabile: %s" % exc) from exc


def _stable_seed(text: str) -> int:
    """Un seme che dipende solo dal testo, non dal processo che lo calcola."""
    import zlib

    return int(zlib.crc32(text.encode("utf-8")))


class ProceduralStubGenerator(MeshGenerator):
    """Sostituto locale del servizio: costruisce un volume dalla descrizione.

    Non e' un modello: serve a poter sviluppare, testare e dimostrare l'intero
    percorso (richiesta, pulizia, controllo, innesto, ripiego) senza dipendere
    da un servizio esterno. In produzione viene scavalcato dal fornitore vero.
    """

    name = "stub"

    def available(self) -> bool:
        return True

    def generate(self, request: MeshRequest) -> trimesh.Trimesh:
        from app.geometry import sdf
        from app.geometry.surface import to_mesh

        # `hash()` sulle stringhe e' randomizzato a ogni processo: usarlo qui
        # rendeva lo stub diverso a ogni esecuzione, e il test che lo dichiara
        # deterministico passava solo perche' confrontava due chiamate dentro
        # lo stesso processo. CRC32 e' stabile ovunque e per sempre.
        rng = np.random.default_rng(_stable_seed(request.prompt) + request.seed)
        blobs: list[sdf.Field] = []
        for index in range(int(rng.integers(3, 6))):
            radii = tuple(float(v) for v in rng.uniform(0.18, 0.42, size=3))
            offset = tuple(float(v) for v in rng.uniform(-0.35, 0.35, size=3))
            blobs.append(sdf.Translate(sdf.Ellipsoid(radii), offset))
        field = sdf.Union(blobs, blend=0.12)
        return to_mesh(field, resolution=48)


# --------------------------------------------------------------------------- #
# Orchestrazione
# --------------------------------------------------------------------------- #
@dataclass
class MeshAttempt:
    generator: str
    ok: bool
    detail: str = ""
    seconds: float = 0.0


@dataclass
class MeshOutcome:
    mesh: trimesh.Trimesh | None = None
    generator: str = ""
    attempts: list[MeshAttempt] = field(default_factory=list)
    report: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.mesh is not None


class MeshService:
    """Prova i generatori in ordine e restituisce solo mesh utilizzabili."""

    def __init__(self, generators: list[MeshGenerator] | None = None,
                 max_seconds: float = 90.0) -> None:
        self.generators = generators if generators is not None else default_generators()
        self.max_seconds = max_seconds

    def generate(self, request: MeshRequest) -> MeshOutcome:
        outcome = MeshOutcome()
        for generator in self.generators:
            if not generator.available():
                outcome.attempts.append(MeshAttempt(generator.name, False, "non configurato"))
                continue
            start = time.perf_counter()
            try:
                raw = generator.generate(request)
                mesh = clean_incoming(raw, request)
                acceptable, reason = is_acceptable(mesh)
                elapsed = time.perf_counter() - start
                if not acceptable:
                    outcome.attempts.append(MeshAttempt(generator.name, False, reason, elapsed))
                    continue
                if elapsed > self.max_seconds:
                    outcome.attempts.append(
                        MeshAttempt(generator.name, False, "troppo lenta", elapsed))
                    continue
                outcome.mesh = mesh
                outcome.generator = generator.name
                outcome.report = quality_report(mesh)
                outcome.attempts.append(MeshAttempt(generator.name, True, "ok", elapsed))
                log.info("mesh AI da %s: %s", generator.name, outcome.report)
                return outcome
            except Exception as exc:
                outcome.attempts.append(MeshAttempt(generator.name, False, str(exc)[:120],
                                                    time.perf_counter() - start))
                log.warning("generatore '%s' fallito: %s", generator.name, exc)
        return outcome


def default_generators() -> list[MeshGenerator]:
    """Solo i fornitori realmente configurati. Lo stub non e' fra questi:
    va chiesto esplicitamente, altrimenti mascherebbe l'assenza del servizio."""
    generators: list[MeshGenerator] = []
    remote = HuggingFaceMeshGenerator()
    if remote.available():
        generators.append(remote)
    return generators
