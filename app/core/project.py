"""Formato di progetto `.my3d`.

Un archivio zip che contiene tutto il lavoro: la cronologia completa, non solo
l'ultimo modello. Dentro ci sono i **piani**, non le mesh — la geometria si
ricostruisce da sola, e' deterministica a parita' di seme e di plugin, e un
piano pesa qualche kilobyte contro i megabyte di un GLB.

    progetto.my3d
        project.json          nome, date, versione del formato, plugin usati
        history/0001.json     un piano per versione, con etichetta e opzioni
        preview.png           anteprima dell'ultima versione

## Perche' il piano e non la mesh

Perche' un progetto deve poter essere **ripreso**, non solo riaperto. Con il
piano si puo' cambiare un parametro, alzare il dettaglio, aggiungere un pezzo e
ricostruire; con una mesh si puo' solo guardarla. La mesh e' un risultato, e i
risultati si rigenerano.

Il prezzo e' che un progetto dipende dai plugin installati. Per questo il
formato scrive **quali plugin, e in che versione**, erano presenti: se domani ne
manca uno, chi riapre il progetto lo sa e legge il nome di cio' che manca invece
di un modello con dei buchi. Non e' un gestore di pacchetti e non vuole
diventarlo: e' l'informazione minima per capire perche' due aperture dello
stesso file danno due modelli diversi.

## Le versioni del formato

`FORMAT_VERSION = 2`. La versione 1 conteneva `GenerationPlan`, il piano della
pipeline storica, e non e' piu' leggibile perche' quella pipeline non esiste
piu': un progetto v1 viene rifiutato con un messaggio che lo dice, invece di
essere aperto a meta'. Il caricatore non si fida mai di cio' che trova, e un
progetto salvato da una versione futura non deve far esplodere niente.
"""
from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.logging_setup import get

log = get("core.project")

SUFFIX = ".my3d"
FORMAT_VERSION = 2
PRIMA_VERSIONE_LEGGIBILE = 2
PROJECT_FILE = "project.json"
HISTORY_DIR = "history"
PREVIEW_FILE = "preview.png"
PLUGIN_VERSION_CHANGED = "PLUGIN_VERSION_CHANGED"
PLUGIN_CONTENT_CHANGED = "PLUGIN_CONTENT_CHANGED"


class ProjectError(ValueError):
    pass


@dataclass
class ProjectInfo:
    """Metadati di un progetto, leggibili senza ricostruire niente."""

    name: str = "Senza titolo"
    created: str = ""
    modified: str = ""
    format_version: int = FORMAT_VERSION
    app_version: str = "0.3"
    cursor: int = 0
    versions: int = 0
    labels: list[str] = field(default_factory=list)
    # plugin presenti quando il progetto e' stato salvato: id -> versione.
    # Serve alla riproducibilita', non a installare niente.
    plugins: dict[str, str] = field(default_factory=dict)
    # id -> impronta del **contenuto**, per i plugin che ne dichiarano una.
    # Un plugin di codice non la dichiara (importare un modulo non e' leggere
    # un file dichiarato), un plugin dati si': cambiare un GLB senza alzare la
    # versione e' esattamente il caso che la versione non racconta. Campo
    # aggiunto: un progetto salvato prima non ne ha, e si legge come prima.
    fingerprints: dict[str, str] = field(default_factory=dict)

    @classmethod
    def now(cls, name: str) -> "ProjectInfo":
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        return cls(name=name, created=stamp, modified=stamp)

    def missing_plugins(self, registry) -> list[str]:
        """I plugin che il progetto usava e che adesso non ci sono."""
        presenti = {p.id: p.version for p in registry.plugins()}
        return sorted("%s@%s" % (id, versione)
                      for id, versione in sorted(self.plugins.items())
                      if id not in presenti)

    def changed_plugins(self, registry) -> list[dict[str, str]]:
        """I plugin che ci sono ancora ma non sono piu' gli stessi.

        Il complemento di `missing_plugins`, e la stessa ragione: un progetto
        riaperto viene **ricostruito**, quindi se la libreria e' cambiata il
        modello puo' essere diverso da quello salvato. Due casi distinti,
        perche' dicono due cose diverse: la versione e' cambiata (l'autore lo
        ha dichiarato) oppure il contenuto e' cambiato a versione ferma
        (nessuno lo ha dichiarato). Nessun giudizio: il formato dice che cosa
        e' cambiato, chi legge decide.
        """
        cambiati = []
        for id, versione in sorted(self.plugins.items()):
            info = registry.plugin(id)
            if info is None:
                continue                      # lo dice gia' missing_plugins
            attuale = getattr(info, "version", "")
            if attuale != versione:
                cambiati.append({"plugin": id, "code": PLUGIN_VERSION_CHANGED,
                                 "was": versione, "now": attuale})
                continue
            impronta = self.fingerprints.get(id, "")
            adesso = getattr(info, "fingerprint", "") or ""
            if impronta and adesso and impronta != adesso:
                cambiati.append({"plugin": id, "code": PLUGIN_CONTENT_CHANGED,
                                 "was": impronta[:12], "now": adesso[:12]})
        return cambiati


def _entry_name(index: int) -> str:
    return "%s/%04d.json" % (HISTORY_DIR, index + 1)


def plugins_of(registry) -> dict[str, str]:
    """id -> versione, per tutti i plugin installati. Ordinato e stabile."""
    return {p.id: p.version for p in sorted(registry.plugins(), key=lambda p: p.id)}


def fingerprints_of(registry) -> dict[str, str]:
    """id -> impronta del contenuto, solo per i plugin che ne dichiarano una."""
    return {p.id: p.fingerprint
            for p in sorted(registry.plugins(), key=lambda p: p.id)
            if getattr(p, "fingerprint", "")}


# --------------------------------------------------------------------------- #
# Salvataggio
# --------------------------------------------------------------------------- #
def save(session, path: str | Path, name: str = "",
         preview: bytes | Path | None = None) -> Path:
    """Scrive l'intera sessione: ogni versione, non solo quella corrente."""
    out = Path(path)
    if out.suffix.lower() != SUFFIX:
        out = out.with_suffix(SUFFIX)
    out.parent.mkdir(parents=True, exist_ok=True)

    if not session.history:
        raise ProjectError("non c'e' niente da salvare: la sessione e' vuota")

    info = ProjectInfo.now(name or out.stem)
    info.cursor = max(0, min(session.cursor, len(session.history) - 1))
    info.versions = len(session.history)
    info.labels = [v.label for v in session.history]
    info.plugins = plugins_of(session.catalog())
    info.fingerprints = fingerprints_of(session.catalog())

    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(PROJECT_FILE,
                         json.dumps(info.__dict__, indent=2, ensure_ascii=False))
        for index, version in enumerate(session.history):
            archive.writestr(_entry_name(index),
                             json.dumps(_versione(version), indent=2,
                                        ensure_ascii=False))
        data = _preview_bytes(preview)
        if data:
            archive.writestr(PREVIEW_FILE, data)

    log.info("progetto salvato: %s (%d versioni, %d plugin)",
             out, info.versions, len(info.plugins))
    return out


def _versione(version) -> dict[str, Any]:
    """Una versione della cronologia, in JSON.

    Il piano e le **opzioni**: lo stile, il dettaglio e il seme stanno nel
    piano, il budget no — e' una decisione di chi genera, non del piano. Senza
    di quello un progetto riaperto potrebbe costruire piu' pezzi di quanti ne
    aveva, e nessuno capirebbe perche'.
    """
    piano = getattr(version, "plan", None)
    return {
        "label": version.label,
        "message": getattr(version, "message", ""),
        "seconds": float(getattr(version, "seconds", 0.0) or 0.0),
        "prompt": getattr(version, "prompt", ""),
        "graph": piano.to_dict() if piano is not None else {},
        "options": dict(getattr(version, "options", {}) or {}),
    }


def _preview_bytes(preview: bytes | Path | None) -> bytes | None:
    if isinstance(preview, (bytes, bytearray)):
        return bytes(preview)
    if preview is not None:
        source = Path(preview)
        if source.is_file():
            return source.read_bytes()
    return None


# --------------------------------------------------------------------------- #
# Lettura
# --------------------------------------------------------------------------- #
def read_info(path: str | Path) -> ProjectInfo:
    """Metadati senza ricostruire nulla: serve a elencare i progetti."""
    with zipfile.ZipFile(Path(path)) as archive:
        try:
            raw = json.loads(archive.read(PROJECT_FILE).decode("utf-8"))
        except KeyError as exc:
            raise ProjectError("non e' un progetto 3DGen: manca %s"
                               % PROJECT_FILE) from exc
    return migrate(raw)


def migrate(raw: dict[str, Any]) -> ProjectInfo:
    """Porta i metadati alla versione corrente del formato.

    Un progetto piu' vecchio della prima versione leggibile viene rifiutato con
    un messaggio che dice cosa e': conteneva i piani di una pipeline che non
    esiste piu', e aprirlo a meta' sarebbe peggio che non aprirlo.
    """
    versione = int(raw.get("format_version", 0) or 0)
    if versione < PRIMA_VERSIONE_LEGGIBILE:
        raise ProjectError(
            "progetto in formato %d: conteneva i piani della pipeline storica, "
            "che non esiste piu'. Va rigenerato dal prompt." % versione)
    if versione > FORMAT_VERSION:
        log.warning("progetto in formato %d, piu' recente di quello noto (%d): "
                    "provo a leggerlo lo stesso", versione, FORMAT_VERSION)
    known = {f for f in ProjectInfo.__dataclass_fields__}
    info = ProjectInfo(**{k: v for k, v in raw.items() if k in known})
    info.format_version = FORMAT_VERSION
    return info


def load(path: str | Path, session=None, provider=None, library=None):
    """Ricostruisce una sessione completa dal file di progetto.

    Ogni versione viene **ricostruita**, non riletta: e' il senso di salvare i
    piani. Una versione che non si ricostruisce non fa cadere il progetto —
    viene saltata con una diagnosi, e le altre si aprono.
    """
    from app.core.session import Session

    source = Path(path)
    if not source.is_file():
        raise ProjectError("progetto inesistente: %s" % source)

    with zipfile.ZipFile(source) as archive:
        info = migrate(json.loads(archive.read(PROJECT_FILE).decode("utf-8")))
        entries = sorted(n for n in archive.namelist()
                         if n.startswith(HISTORY_DIR + "/") and n.endswith(".json"))
        payloads = [json.loads(archive.read(name).decode("utf-8"))
                    for name in entries]

    target = session if session is not None \
        else Session(provider=provider, library=library)
    target.history = []
    target.cursor = -1

    mancanti = info.missing_plugins(target.catalog())
    if mancanti:
        log.warning("plugin non installati: %s", ", ".join(mancanti))
    cambiati = info.changed_plugins(target.catalog())
    if cambiati:
        log.warning("plugin cambiati dal salvataggio: %s",
                    ", ".join(v["plugin"] for v in cambiati))

    for payload in payloads:
        grafo = payload.get("graph") or {}
        if not grafo:
            log.warning("versione saltata: non contiene un piano")
            continue
        try:
            target.restore(payload)
        except Exception as exc:                      # noqa: BLE001
            log.warning("versione saltata, piano non ricostruibile: %s", exc)

    if not target.history:
        raise ProjectError("il progetto non contiene versioni ricostruibili")
    target.cursor = max(0, min(int(info.cursor), len(target.history) - 1))
    target.missing_plugins = mancanti
    target.changed_plugins = cambiati
    # La diagnosi sta sul **risultato ricostruito**, non accanto ad esso: chi
    # riapre un progetto legge `result.diagnostics` come dopo una generazione
    # qualunque, e non deve sapere che esiste un secondo elenco.
    for versione in target.history:
        risultato = getattr(versione, "result", None)
        report = getattr(risultato, "report", None)
        if report is None:
            continue
        for voce in cambiati:
            report.warn(voce["code"],
                        "plugin '%s' cambiato dal salvataggio: %s -> %s"
                        % (voce["plugin"], voce["was"] or "-", voce["now"] or "-"),
                        where=voce["plugin"],
                        why="il progetto conserva il piano, non la mesh: la "
                            "geometria viene ricostruita con la libreria di adesso")
    log.info("progetto aperto: %s (%d versioni, corrente %d)",
             source.name, len(target.history), target.cursor + 1)
    return target


def preview_bytes(path: str | Path) -> bytes | None:
    try:
        with zipfile.ZipFile(Path(path)) as archive:
            return archive.read(PREVIEW_FILE)
    except (KeyError, zipfile.BadZipFile, FileNotFoundError):
        return None
