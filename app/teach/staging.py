"""Lo staging: dove finisce cio' che un modello ha scritto, e nient'altro.

§29 e §30 della milestone, e la seconda e' quella che conta:

> Teach 3DGen deve poter creare prompt per componenti Python. Ma NON deve
> trattare Python generato come sicuro.

Quindi, letteralmente:

* niente di cio' che arriva viene scritto nella libreria installata;
* un plugin **dati** si valida senza eseguire niente — si legge, si carica in
  un registry usa e getta, si costruisce, si misura;
* un plugin di **codice** non viene importato, non viene eseguito e non viene
  installato finche' qualcuno non lo rende fidato con un gesto esplicito. Prima
  si mostrano i file, il sorgente, gli import, la dimensione e il manifest.

## Questo non e' una sandbox, e non viene chiamata cosi'

I controlli statici di `inspect_python` sono **utili** e non sono una garanzia:
un AST dice quali import compaiono nel testo, non che cosa il codice fara'.
`importlib`, `getattr` e una stringa bastano a raggiungere qualunque modulo, e
non e' un difetto di questi controlli, e' il motivo per cui non sono
sicurezza. Per questo:

* i risultati sono **avvisi**, e il nome del campo e' `warnings`;
* `trusted` non viene mai messo da qui: lo mette il chiamante, che ha chiesto
  all'utente;
* `isolate=True` esegue il caricamento in un sottoprocesso con un timeout, e
  serve a **non** far morire la UI su un ciclo infinito o un crash. Un
  sottoprocesso puo' ancora leggere il filesystem, aprire socket e lanciare
  processi: e' robustezza, non confinamento, e §30 vieta di chiamarlo altro.

Costruire una vera sandbox Python non e' questa milestone, e fingerne una
sarebbe peggio di non averla.

## I limiti dell'inviluppo

Percorsi relativi, nessun `..`, nessun percorso assoluto, nessun drive, nessun
UNC, estensioni da un elenco chiuso, un tetto per file e un tetto totale, un
numero massimo di file. E' `safe_path` di V4 dal lato della scrittura, piu' il
fatto che qui chi scrive e' un modello linguistico.
"""
from __future__ import annotations

import ast
import json
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath

from app.core.errors import Report
from app.teach import errors
from app.teach.errors import TeachError
from app.teach.model import COMPOSITE, DATA_MESH, PROCEDURAL, ArtifactRecord

# I limiti dell'inviluppo. Dichiarati, non impliciti.
ALLOWED_EXTENSIONS = (".json", ".py", ".md", ".txt")
MAX_FILES = 24
MAX_FILE_BYTES = 200_000
MAX_TOTAL_BYTES = 600_000
MANIFEST = "plugin.json"

# Gli import che fanno comparire un avviso. **Configurabile**, e non e' un
# elenco di cose proibite: e' un elenco di cose che chi legge il codice vuole
# sapere che ci sono. Un componente che costruisce geometria non ha bisogno di
# nessuno di questi.
FLAGGED_MODULES = (
    "os", "sys", "subprocess", "socket", "shutil", "pathlib", "glob",
    "tempfile", "requests", "urllib", "http", "ftplib", "smtplib", "ctypes",
    "importlib", "imp", "pickle", "marshal", "shelve", "multiprocessing",
    "threading", "asyncio", "signal", "pty", "resource", "webbrowser",
    "builtins", "__builtin__", "code", "codeop", "runpy", "pdb", "inspect",
)
# Le funzioni che permettono di raggiungere qualunque cosa senza nominarla.
FLAGGED_CALLS = ("eval", "exec", "compile", "__import__", "open", "getattr",
                 "setattr", "globals", "locals", "vars", "memoryview")

# I moduli di 3DGen che un componente ha un motivo legittimo di importare.
ALLOWED_API = ("app.core.capability", "app.core.component", "app.core.params",
               "app.core.socket", "app.core.layout", "app.core.material",
               "app.core.constraints", "app.core.vocabulary", "app.core.frame",
               "app.geometry.kernel", "app.geometry.uv", "numpy", "trimesh",
               "math", "dataclasses", "typing", "__future__")

RUN_TIMEOUT = 30.0


# --------------------------------------------------------------------------- #
# L'inviluppo
# --------------------------------------------------------------------------- #
@dataclass
class StagedFile:
    """Un file come e' arrivato: un percorso relativo e del testo."""

    path: str
    content: str

    @property
    def size(self) -> int:
        return len(self.content.encode("utf-8"))

    @property
    def suffix(self) -> str:
        return Path(self.path).suffix.lower()

    @property
    def python(self) -> bool:
        return self.suffix == ".py"

    def to_dict(self) -> dict:
        return {"path": self.path, "content": self.content}


def safe_relative(raw: str) -> str:
    """Un percorso relativo che non puo' uscire. Rifiuta, non corregge.

    I controlli sono quelli di `app/core/data_plugin.py:safe_path`, applicati a
    una stringa che un modello ha scritto: nessun percorso assoluto POSIX **ne'**
    Windows (su qualunque piattaforma, via `PureWindowsPath`), nessun drive,
    nessun UNC, nessun byte nullo, nessun segmento `..`, e un'estensione
    dall'elenco chiuso.
    """
    text = str(raw or "").strip().replace("\\", "/")
    if not text:
        raise TeachError(errors.PATH_UNSAFE, "percorso vuoto nell'inviluppo")
    if "\x00" in text:
        raise TeachError(errors.PATH_UNSAFE, "percorso con byte nullo")
    if text.startswith("/") or text.startswith("//"):
        raise TeachError(errors.PATH_UNSAFE, "percorso assoluto: %r" % raw)
    windows = PureWindowsPath(text)
    if windows.drive or windows.is_absolute() or ":" in text:
        raise TeachError(errors.PATH_UNSAFE,
                         "percorso assoluto o con drive: %r" % raw)
    parts = [p for p in text.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise TeachError(errors.PATH_UNSAFE,
                         "il percorso uscirebbe dalla cartella: %r" % raw)
    if not parts:
        raise TeachError(errors.PATH_UNSAFE, "percorso senza nome: %r" % raw)
    suffix = Path(parts[-1]).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise TeachError(errors.EXTENSION_REFUSED,
                         "estensione non ammessa %r in %r (ammesse: %s)"
                         % (suffix, raw, ", ".join(ALLOWED_EXTENSIONS)))
    return "/".join(parts)


def parse_envelope(raw) -> tuple[list[StagedFile], str]:
    """Legge l'inviluppo di §28. Non scrive niente e non esegue niente.

    Accetta un oggetto gia' deserializzato o il testo che l'utente ha
    incollato, perche' le due modalita' di §5 arrivano in queste due forme e il
    resto deve essere identico.
    """
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="replace")
    if isinstance(raw, str):
        text = raw.strip()
        if text.startswith("```"):
            # Un blocco di codice markdown e' il modo in cui una chat
            # restituisce JSON: si toglie l'involucro, non si indovina il resto.
            lines = [l for l in text.splitlines() if not l.strip().startswith("```")]
            text = "\n".join(lines).strip()
        try:
            raw = json.loads(text)
        except ValueError as exc:
            raise TeachError(errors.RESPONSE_INVALID,
                             "la risposta non e' JSON valido: %s" % exc) from exc
    if not isinstance(raw, dict):
        raise TeachError(errors.RESPONSE_INVALID,
                         "la risposta deve essere un oggetto JSON")
    unknown = set(raw) - {"files", "notes"}
    if unknown:
        raise TeachError(errors.ENVELOPE_INVALID,
                         "chiavi non ammesse nell'inviluppo: %s"
                         % ", ".join(sorted(unknown)))
    items = raw.get("files")
    if not isinstance(items, list) or not items:
        raise TeachError(errors.ENVELOPE_INVALID,
                         "l'inviluppo deve portare una lista 'files' non vuota")
    if len(items) > MAX_FILES:
        raise TeachError(errors.ENVELOPE_INVALID,
                         "troppi file: %d (massimo %d)" % (len(items), MAX_FILES))
    files: list[StagedFile] = []
    total = 0
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            raise TeachError(errors.ENVELOPE_INVALID, "un file e' un oggetto JSON")
        unknown = set(item) - {"path", "content"}
        if unknown:
            raise TeachError(errors.ENVELOPE_INVALID,
                             "chiavi non ammesse in un file: %s"
                             % ", ".join(sorted(unknown)))
        content = item.get("content")
        if not isinstance(content, str):
            raise TeachError(errors.ENVELOPE_INVALID,
                             "il contenuto di %r non e' una stringa"
                             % item.get("path"))
        path = safe_relative(item.get("path", ""))
        if path in seen:
            raise TeachError(errors.ENVELOPE_INVALID,
                             "lo stesso percorso due volte: %r" % path)
        seen.add(path)
        staged = StagedFile(path=path, content=content)
        if staged.size > MAX_FILE_BYTES:
            raise TeachError(errors.FILE_TOO_LARGE,
                             "%s pesa %d byte (massimo %d)"
                             % (path, staged.size, MAX_FILE_BYTES))
        total += staged.size
        if total > MAX_TOTAL_BYTES:
            raise TeachError(errors.FILE_TOO_LARGE,
                             "l'inviluppo supera %d byte in totale"
                             % MAX_TOTAL_BYTES)
        files.append(staged)
    if not any(f.path == MANIFEST for f in files):
        raise TeachError(errors.ENVELOPE_INVALID,
                         "manca %s: senza manifest non c'e' un plugin da "
                         "installare" % MANIFEST)
    return files, str(raw.get("notes", "") or "")


# --------------------------------------------------------------------------- #
# L'ispezione statica del Python (§31)
# --------------------------------------------------------------------------- #
@dataclass
class PythonInspection:
    """Che cosa si vede in un file Python **senza eseguirlo**. Avvisi, non garanzie."""

    path: str
    syntax_ok: bool = True
    error: str = ""
    imports: tuple[str, ...] = ()
    flagged_imports: tuple[str, ...] = ()
    flagged_calls: tuple[str, ...] = ()
    unexpected_api: tuple[str, ...] = ()
    size: int = 0
    builds_component: bool = False
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("imports", "flagged_imports", "flagged_calls",
                     "unexpected_api", "warnings"):
            setattr(self, name, tuple(getattr(self, name)))

    @property
    def clean(self) -> bool:
        """Nessun avviso. **Non** vuol dire sicuro: vedi la testata del file."""
        return self.syntax_ok and not self.warnings

    def describe(self) -> str:
        if not self.syntax_ok:
            return "%s: non si compila - %s" % (self.path, self.error)
        return "%s: %d byte, %d import, %s%s" % (
            self.path, self.size, len(self.imports),
            "registra un Component" if self.builds_component
            else "nessun Component di livello modulo",
            "" if not self.warnings else ", %d avvisi" % len(self.warnings))


def inspect_python(path, *, flagged=FLAGGED_MODULES,
                   allowed_api=ALLOWED_API) -> PythonInspection:
    """Legge un file Python con l'AST. Non lo importa e non lo esegue.

    Che cosa dice, e che cosa **non** dice: dice che il testo si compila, quali
    moduli nomina, quali chiamate pericolose nomina, se dichiara un `Component`
    di livello modulo (senza il quale il registry non registrerebbe niente), e
    quanto pesa. Non dice che cosa fara' all'esecuzione, e un'assenza di avvisi
    non e' un permesso.
    """
    source = Path(path)
    try:
        text = source.read_text(encoding="utf-8-sig")
    except OSError as exc:
        return PythonInspection(path=str(source), syntax_ok=False,
                                error=str(exc),
                                warnings=("il file non si legge",))
    try:
        tree = ast.parse(text, filename=str(source))
    except SyntaxError as exc:
        return PythonInspection(path=str(source), syntax_ok=False,
                                error="riga %s: %s" % (exc.lineno, exc.msg),
                                size=len(text.encode("utf-8")),
                                warnings=("il file non si compila",))

    imports: set[str] = set()
    calls: set[str] = set()
    builds = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module)
            if node.level:
                imports.add("." * node.level + (node.module or ""))
        elif isinstance(node, ast.Call):
            name = ""
            if isinstance(node.func, ast.Name):
                name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                name = node.func.attr
            if name in FLAGGED_CALLS:
                calls.add(name)
            if name == "Component":
                builds = True

    roots = {name.partition(".")[0] for name in imports}
    flagged_imports = sorted(roots & set(flagged))
    unexpected = sorted(name for name in imports
                        if not any(name == a or name.startswith(a + ".")
                                   for a in allowed_api))
    warnings: list[str] = []
    if flagged_imports:
        warnings.append("importa moduli che un componente non ha motivo di "
                        "usare: %s" % ", ".join(flagged_imports))
    if calls:
        warnings.append("nomina chiamate che raggiungono qualunque cosa: %s"
                        % ", ".join(sorted(calls)))
    if unexpected:
        warnings.append("importa moduli fuori dall'API dichiarata: %s"
                        % ", ".join(unexpected[:8]))
    if not builds:
        warnings.append("non costruisce nessun Component di livello modulo: il "
                        "registry non registrerebbe niente")
    return PythonInspection(path=str(source), imports=tuple(sorted(imports)),
                            flagged_imports=tuple(flagged_imports),
                            flagged_calls=tuple(sorted(calls)),
                            unexpected_api=tuple(unexpected),
                            size=len(text.encode("utf-8")),
                            builds_component=builds, warnings=tuple(warnings))


# --------------------------------------------------------------------------- #
# L'artefatto in staging
# --------------------------------------------------------------------------- #
@dataclass
class StagedArtifact:
    """Dei file su disco, fuori dalla libreria, con il loro referto."""

    id: str
    node: str
    kind: str
    container: Path                  # la cartella che il registry scandirebbe
    path: Path                       # la cartella del plugin dentro il container
    plugin_id: str
    component_id: str = ""
    files: tuple[StagedFile, ...] = ()
    inspections: tuple[PythonInspection, ...] = ()
    notes: str = ""
    trusted: bool = False
    report: Report = field(default_factory=Report)

    def __post_init__(self) -> None:
        self.files = tuple(self.files)
        self.inspections = tuple(self.inspections)

    @property
    def code(self) -> bool:
        """Contiene Python? Allora e' codice, e vale §30."""
        return any(f.python for f in self.files)

    @property
    def warnings(self) -> tuple[str, ...]:
        out: list[str] = []
        for item in self.inspections:
            out.extend("%s: %s" % (Path(item.path).name, w) for w in item.warnings)
        return tuple(out)

    @property
    def total_size(self) -> int:
        return sum(f.size for f in self.files)

    def manifest(self) -> dict:
        for item in self.files:
            if item.path == MANIFEST:
                try:
                    return json.loads(item.content)
                except ValueError:
                    return {}
        return {}

    def record(self) -> ArtifactRecord:
        return ArtifactRecord(id=self.id, node=self.node, kind=self.kind,
                              path=str(self.container),
                              files=tuple(f.path for f in self.files),
                              trusted=self.trusted, plugin_id=self.plugin_id,
                              warnings=self.warnings, notes=self.notes)

    def describe(self) -> str:
        return "%s | %s | %d file, %d byte | %s%s" % (
            self.id, self.kind, len(self.files), self.total_size,
            "codice" if self.code else "dati",
            "" if not self.warnings else " | %d avvisi" % len(self.warnings))


def kind_of(files, manifest: dict) -> str:
    """Di che specie e' questo artefatto. Dal contenuto, non da una dichiarazione.

    Un `.py` fra i file lo rende **codice**, anche se il manifest dicesse
    `type: "data"`: la specie la decide cio' che c'e' sul disco, perche' e' cio'
    che verrebbe importato. Fra i due casi dati, un componente senza `mesh` e'
    un composite.
    """
    if any(f.python for f in files):
        return PROCEDURAL
    for item in files:
        if item.path.startswith("components/") and item.path.endswith(".json"):
            try:
                data = json.loads(item.content)
            except ValueError:
                continue
            if isinstance(data, dict) and data.get("mesh"):
                return DATA_MESH
    return COMPOSITE if files else DATA_MESH


def stage(root, files, *, artifact_id: str, node: str = "",
          expect_plugin: str = "", component_id: str = "",
          asset=None, notes: str = "") -> StagedArtifact:
    """Scrive l'inviluppo nello staging. **Mai** nella libreria installata.

    Il manifest decide il nome della cartella del plugin, e un id diverso da
    quello che la specifica aveva dichiarato e' un errore: il resto del sistema
    ha gia' deciso che il componente si chiamera' `plugin:nome`, e un plugin con
    un altro id installerebbe un componente che nessuno sta aspettando.

    `asset` e' un GLB fornito dall'utente (§26): si copia dentro `meshes/`, e il
    modello non lo ha mai visto ne' scritto.
    """
    base = Path(root) / str(artifact_id)
    if base.exists():
        shutil.rmtree(base, ignore_errors=True)
    manifest: dict = {}
    for item in files:
        if item.path == MANIFEST:
            try:
                manifest = json.loads(item.content)
            except ValueError as exc:
                raise TeachError(errors.ENVELOPE_INVALID,
                                 "%s non e' JSON valido: %s"
                                 % (MANIFEST, exc)) from exc
    if not isinstance(manifest, dict) or not str(manifest.get("id", "")).strip():
        raise TeachError(errors.ENVELOPE_INVALID,
                         "%s non dichiara un id" % MANIFEST)
    plugin_id = str(manifest["id"]).strip()
    if expect_plugin and plugin_id != expect_plugin:
        raise TeachError(errors.ENVELOPE_INVALID,
                         "il manifest dichiara id %r ma la specifica aveva "
                         "deciso %r: il resto del sistema aspetta quel nome"
                         % (plugin_id, expect_plugin))
    target = (base / plugin_id).resolve()
    if not target.is_relative_to(base.resolve()):
        raise TeachError(errors.PATH_UNSAFE,
                         "l'id del plugin uscirebbe dallo staging: %r" % plugin_id)
    target.mkdir(parents=True, exist_ok=True)
    for item in files:
        destination = (target / item.path).resolve()
        if not destination.is_relative_to(target):
            raise TeachError(errors.PATH_UNSAFE,
                             "il file uscirebbe dalla cartella del plugin: %r"
                             % item.path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(item.content, encoding="utf-8")
    if asset is not None:
        source = Path(asset)
        if not source.is_file():
            raise TeachError(errors.ASSET_MISSING,
                             "l'asset dichiarato non c'e': %s" % source)
        meshes = target / "meshes"
        meshes.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, meshes / source.name)

    inspections = tuple(inspect_python(target / item.path)
                        for item in files if item.python)
    artifact = StagedArtifact(
        id=str(artifact_id), node=node, kind=kind_of(files, manifest),
        container=base, path=target, plugin_id=plugin_id,
        component_id=component_id, files=tuple(files), inspections=inspections,
        notes=notes)
    for warning in artifact.warnings:
        artifact.report.warn("TEACH_PYTHON_WARNING", warning,
                             where=artifact.id,
                             why="controllo statico: utile, non una garanzia "
                                 "di sicurezza")
    if artifact.code:
        artifact.report.note("TEACH_CODE_NOT_TRUSTED",
                             "l'artefatto contiene Python: non viene importato, "
                             "ne' eseguito, ne' installato senza un'azione "
                             "esplicita", where=artifact.id)
    return artifact


# --------------------------------------------------------------------------- #
# La validazione
# --------------------------------------------------------------------------- #
@dataclass
class StagedValidation:
    """L'esito di «carica, costruisci, misura». Nessun validatore nuovo."""

    report: Report = field(default_factory=Report)
    installed: tuple[str, ...] = ()
    triangles: int = 0
    built: bool = False
    retrievable: bool = False
    isolated: bool = False
    seconds: float = 0.0

    @property
    def ok(self) -> bool:
        return self.report.ok and self.built

    def codes(self) -> set[str]:
        return self.report.codes()

    def describe(self) -> str:
        return "%s | %d componenti | %d triangoli | %s | %s" % (
            "ok" if self.ok else "non ok", len(self.installed), self.triangles,
            "trovabile" if self.retrievable else "non trovabile",
            "sottoprocesso" if self.isolated else "in processo")


def validate_artifact(artifact: StagedArtifact, *, base_paths=(),
                      component_id: str = "", style: str = "low_poly",
                      detail_level: int = 2, isolate: bool = False,
                      timeout: float = RUN_TIMEOUT) -> StagedValidation:
    """Carica, costruisce, valida e cerca. Con i validatori che ci sono.

    Per un artefatto di **codice** serve `artifact.trusted`: senza, questa
    funzione **alza** invece di caricare, perche' caricare vorrebbe dire
    importare — e §30 dice che non si importa senza un gesto esplicito.

    `isolate=True` fa il caricamento in un sottoprocesso con un timeout. Serve
    a non far morire chi chiama su un ciclo infinito o un crash: non e'
    confinamento, e la testata del file lo dice.
    """
    if artifact.code and not artifact.trusted:
        raise TeachError(errors.TRUST_REQUIRED,
                         "l'artefatto %s contiene Python e non e' stato reso "
                         "fidato: niente viene importato finche' qualcuno non "
                         "lo decide" % artifact.id)
    inizio = time.perf_counter()
    wanted = component_id or artifact.component_id
    paths = [str(p) for p in base_paths] + [str(artifact.container)]
    if isolate:
        out = _validate_isolated(paths, wanted, style=style,
                                 detail_level=detail_level, timeout=timeout)
        out.seconds = time.perf_counter() - inizio
        return out
    out = _validate_here(paths, wanted, style=style, detail_level=detail_level)
    out.seconds = time.perf_counter() - inizio
    return out


def _validate_here(paths, component_id: str, *, style: str,
                   detail_level: int) -> StagedValidation:
    from app.core.session import Options, Session

    out = StagedValidation()
    session = Session(plugin_paths=tuple(paths))
    try:
        registry = session.catalog()
        out.report.extend(registry.report)
        out.installed = tuple(sorted(c.id for c in registry.components()
                                     if c.plugin == component_id.partition(":")[0]))
        if component_id and registry.component(component_id) is None:
            out.report.add("TEACH_COMPONENT_NOT_INSTALLED",
                           "'%s' non risulta installato dopo il caricamento"
                           % component_id,
                           why="l'id di un Component di codice e' non "
                               "qualificato nel modulo e il registry lo "
                               "qualifica con l'id del plugin")
            return out
        if not component_id:
            return out
        plan = {"version": "1.3", "style": style,
                "detail_level": int(detail_level), "seed": 0,
                "root": {"id": "subject", "ref": component_id}}
        result = session.build(plan, Options(style=style,
                                             detail_level=int(detail_level),
                                             check=True))
        if result is not None:
            out.triangles = int(result.triangles)
            out.built = bool(result.ok)
            if result.report is not None:
                out.report.extend(result.report)
        name = component_id.partition(":")[2].replace("_", " ")
        hits = {i for i, _ in session.component_index().search(name, limit=12)}
        out.retrievable = component_id in hits
        if not out.retrievable:
            out.report.warn("TEACH_NOT_RETRIEVABLE",
                            "'%s' e' installato ma una ricerca per %r non lo "
                            "trova" % (component_id, name),
                            why="il documento semantico nasce dai metadati "
                                "dichiarati: descrizione, ruolo e tag")
    finally:
        session.registry = None
    return out


def _validate_isolated(paths, component_id: str, *, style: str,
                       detail_level: int, timeout: float) -> StagedValidation:
    """Lo stesso caricamento, in un sottoprocesso con un timeout.

    Robustezza: un plugin che cicla per sempre o che fa cadere l'interprete non
    porta via la finestra. **Non** sicurezza: quel sottoprocesso ha lo stesso
    accesso di questo. §30.
    """
    out = StagedValidation(isolated=True)
    runner = Path(__file__).with_name("_runner.py")
    # `-E` ignora le variabili d'ambiente (PYTHONPATH e compagnia) e lascia il
    # sito dei pacchetti: `numpy` e `trimesh` servono per costruire, e un
    # avvio che non li trova non misura niente. Non e' confinamento, e la
    # testata del file lo dice: la cartella in cui il processo parte e' quella
    # del repository, **non** lo staging, cosi' un modulo piantato accanto ai
    # file generati non finisce davanti a quelli veri.
    command = [sys.executable, "-E", str(runner),
               "--component", component_id, "--style", style,
               "--detail", str(int(detail_level))]
    for path in paths:
        command += ["--path", path]
    try:
        done = subprocess.run(command, capture_output=True, text=True,
                              timeout=float(timeout),
                              cwd=str(Path(__file__).resolve().parents[2]))
    except subprocess.TimeoutExpired:
        out.report.add("TEACH_RUN_TIMEOUT",
                       "il caricamento non e' finito entro %.0f secondi"
                       % float(timeout),
                       why="un sottoprocesso con timeout e' robustezza, non "
                           "confinamento")
        return out
    except OSError as exc:
        out.report.add("TEACH_RUN_FAILED",
                       "il sottoprocesso non e' partito: %s" % exc)
        return out
    if done.returncode != 0 and not done.stdout.strip():
        out.report.add("TEACH_RUN_FAILED",
                       "il sottoprocesso e' uscito con %d" % done.returncode,
                       why=(done.stderr or "").strip()[-400:])
        return out
    try:
        data = json.loads(done.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        out.report.add("TEACH_RUN_FAILED",
                       "il sottoprocesso non ha restituito un referto leggibile",
                       why=(done.stderr or done.stdout or "").strip()[-400:])
        return out
    out.installed = tuple(data.get("installed", ()))
    out.triangles = int(data.get("triangles", 0) or 0)
    out.built = bool(data.get("built", False))
    out.retrievable = bool(data.get("retrievable", False))
    for row in data.get("diagnostics", ()):
        out.report.add(str(row.get("code", "")), str(row.get("message", "")),
                       where=str(row.get("where", "")),
                       why=str(row.get("why", "")),
                       severity=str(row.get("severity", "error")))
    return out


def discard(artifact: StagedArtifact) -> None:
    """Butta i file di un artefatto. Lo staging non e' un archivio."""
    shutil.rmtree(artifact.container, ignore_errors=True)


def install(artifact: StagedArtifact, session, *, build: bool = True,
            style: str = "low_poly", detail_level: int = 2,
            container=None) -> StagedValidation:
    """Installa l'artefatto nella sessione vera, e misura cosa e' cambiato.

    E' §35: `reload_plugins`, invalidazione dell'indice, e la verifica che il
    componente ci sia davvero. Per il codice serve `trusted`, come sopra.

    `container` e' la cartella da registrare, e di norma **non** e' lo staging:
    chi accetta un artefatto lo copia dove la libreria vive e registra quella.
    Registrare anche lo staging darebbe lo stesso plugin da due percorsi, e il
    registry lo scarta con `DUPLICATE_PLUGIN` — correttamente, perche' due
    copie dello stesso id sono ambigue.
    """
    if artifact.code and not artifact.trusted:
        raise TeachError(errors.TRUST_REQUIRED,
                         "l'artefatto %s contiene Python e non e' fidato: non "
                         "si installa" % artifact.id)
    out = StagedValidation()
    previous = session.component_index()
    out.report.extend(session.reload_plugins(container or artifact.container))
    registry = session.catalog()
    out.installed = tuple(sorted(c.id for c in registry.components()
                                 if c.plugin == artifact.plugin_id))
    component_id = artifact.component_id
    if component_id and registry.component(component_id) is None:
        out.report.add("TEACH_COMPONENT_NOT_INSTALLED",
                       "'%s' non risulta installato" % component_id,
                       where=str(artifact.container))
        return out
    if not previous.is_current(registry):
        out.report.note("TEACH_INDEX_INVALIDATED",
                        "il SemanticIndex non e' piu' quello di prima: si "
                        "ricostruira' alla prossima ricerca",
                        where=artifact.plugin_id)
    if component_id:
        name = component_id.partition(":")[2].replace("_", " ")
        hits = {i for i, _ in session.component_index().search(name, limit=12)}
        out.retrievable = component_id in hits
    if build and component_id:
        from app.core.session import Options

        plan = {"version": "1.3", "style": style,
                "detail_level": int(detail_level), "seed": 0,
                "root": {"id": "subject", "ref": component_id}}
        result = session.build(plan, Options(style=style,
                                             detail_level=int(detail_level),
                                             check=True))
        if result is not None:
            out.triangles = int(result.triangles)
            out.built = bool(result.ok)
            if result.report is not None and not result.report.ok:
                out.report.extend(result.report)
    else:
        out.built = bool(out.installed)
    return out


__all__ = ["ALLOWED_API", "ALLOWED_EXTENSIONS", "FLAGGED_CALLS",
           "FLAGGED_MODULES", "MANIFEST", "MAX_FILES", "MAX_FILE_BYTES",
           "MAX_TOTAL_BYTES", "PythonInspection", "StagedArtifact",
           "StagedFile", "StagedValidation", "discard", "inspect_python",
           "install", "kind_of", "parse_envelope", "safe_relative", "stage",
           "validate_artifact"]
