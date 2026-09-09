"""Salvataggio periodico e recupero dopo un crash.

Il costo di questa funzione e' quasi nullo perche' un progetto `.my3d` contiene
i **piani**, non le mesh: qualche kilobyte. Salvare ogni pochi minuti non si
sente, e in cambio una sessione di un'ora non svanisce per un driver grafico
che cade.

Il meccanismo e' quello classico e volutamente noioso:

  - a ogni intervallo si scrive un progetto in una cartella di recupero, con un
    file di stato accanto che dice che quella sessione e' **aperta**;
  - alla chiusura regolare il file di stato viene tolto;
  - all'avvio, se si trova uno stato ancora aperto, quella sessione non era
    stata chiusa: si propone di riprenderla.

La scrittura passa da un file temporaneo e poi rinomina. Se il programma muore
*durante* il salvataggio automatico, il recupero precedente resta intatto:
sarebbe assurdo che a far perdere il lavoro fosse proprio il salvataggio.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

from app.core.config import SETTINGS
from app.core.logging_setup import get

log = get("core.recovery")

INTERVAL = 180.0            # secondi fra due salvataggi automatici
KEEP = 3                    # quante sessioni di recupero conservare
STATE = "sessione.json"


def recovery_dir() -> Path:
    path = SETTINGS.output_dir / ".recupero"
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class Recovery:
    """Una sessione trovata in cartella di recupero."""

    path: Path
    started: float
    saved: float
    versions: int
    label: str
    clean: bool

    def age_minutes(self) -> float:
        return max(time.time() - self.saved, 0.0) / 60.0

    def describe(self) -> str:
        return ("%s - %d versioni, salvata %d minuti fa"
                % (self.label or "sessione senza nome", self.versions,
                   round(self.age_minutes())))


class AutoSave:
    """Tiene una copia di sicurezza della sessione, senza farsi notare.

    Non ha timer propri: chiede solo di essere interpellato: `maybe_save()` a
    ogni azione dell'utente decide da se' se e' il momento. Cosi' funziona
    identico dalla UI, dalla CLI e dai test, senza thread da spegnere.
    """

    def __init__(self, session, interval: float = INTERVAL, root: Path | None = None):
        self.session = session
        self.interval = float(interval)
        self.root = Path(root) if root is not None else recovery_dir()
        self.root.mkdir(parents=True, exist_ok=True)
        self.slot = self.root / ("sessione_%d" % int(time.time() * 1000))
        self.started = time.time()
        self.last_save = 0.0
        self.saves = 0

    # -------------------------------------------------------------- scrittura #
    @property
    def project_path(self) -> Path:
        return self.slot / "lavoro.my3d"

    @property
    def state_path(self) -> Path:
        return self.slot / STATE

    def due(self, now: float | None = None) -> bool:
        """E' passato abbastanza tempo, e c'e' qualcosa da salvare?"""
        if not self.session.history:
            return False
        adesso = time.time() if now is None else now
        return (adesso - self.last_save) >= self.interval

    def maybe_save(self, force: bool = False) -> Path | None:
        if not force and not self.due():
            return None
        return self.save()

    def save(self) -> Path | None:
        """Scrive il recupero. Un errore qui non deve interrompere il lavoro."""
        if not self.session.history:
            return None
        self.slot.mkdir(parents=True, exist_ok=True)
        # Il nome provvisorio finisce comunque in `.my3d`: project.save
        # normalizza l'estensione, e con `.parziale` in fondo scriverebbe
        # direttamente sul file buono, che e' proprio cio' che si vuole evitare.
        temporaneo = self.slot / "lavoro.parziale.my3d"
        try:
            from app.core import project

            scritto = project.save(self.session, temporaneo, name=self._label())
            os.replace(scritto, self.project_path)
            self._write_state(clean=False)
            self.last_save = time.time()
            self.saves += 1
            log.info("recupero salvato: %s (%d versioni)",
                     self.project_path, len(self.session.history))
            return self.project_path
        except Exception as exc:      # disco pieno, permessi, progetto malformato
            log.warning("salvataggio di recupero non riuscito: %s", exc)
            temporaneo.unlink(missing_ok=True)
            return None

    def close(self) -> None:
        """Chiusura regolare: la sessione non e' piu' da recuperare."""
        if self.state_path.exists():
            self._write_state(clean=True)
            log.info("sessione chiusa regolarmente: %s", self.slot.name)
        prune(self.root)

    def _label(self) -> str:
        corrente = self.session.current
        return corrente.label if corrente is not None else ""

    def _write_state(self, clean: bool) -> None:
        self.state_path.write_text(json.dumps({
            "started": self.started, "saved": time.time(),
            "versions": len(self.session.history),
            "label": self._label(), "clean": bool(clean),
            "pid": os.getpid(),
        }, ensure_ascii=False), encoding="utf-8")


# --------------------------------------------------------------------------- #
# Lettura
# --------------------------------------------------------------------------- #
def pending(root: Path | None = None) -> list[Recovery]:
    """Le sessioni rimaste aperte, dalla piu' recente.

    Uno stato illeggibile viene ignorato e non fa perdere gli altri: e'
    esattamente la situazione in cui il file puo' essere stato troncato.
    """
    cartella = Path(root) if root is not None else recovery_dir()
    trovate: list[Recovery] = []
    for slot in sorted(cartella.glob("sessione_*"), reverse=True):
        stato, progetto = slot / STATE, slot / "lavoro.my3d"
        if not stato.is_file() or not progetto.is_file():
            continue
        try:
            dati = json.loads(stato.read_text(encoding="utf-8"))
        except Exception as exc:
            log.warning("stato di recupero illeggibile in %s: %s", slot.name, exc)
            continue
        if dati.get("clean"):
            continue
        trovate.append(Recovery(
            path=progetto, started=float(dati.get("started", 0.0)),
            saved=float(dati.get("saved", 0.0)),
            versions=int(dati.get("versions", 0)),
            label=str(dati.get("label", "")), clean=False))
    return trovate


def restore(recovery: Recovery, session):
    """Riapre una sessione recuperata dentro la sessione data."""
    session.open_project(recovery.path)
    log.info("sessione recuperata: %s (%d versioni)",
             recovery.path, len(session.history))
    return session.current


def discard(recovery: Recovery) -> None:
    """L'utente non la vuole: si marca chiusa, non si cancella subito.

    Il file resta finche' `prune` non lo elimina per anzianita': se qualcuno
    rifiuta il recupero per errore, il lavoro e' ancora li' fino alla fine.
    """
    stato = recovery.path.parent / STATE
    try:
        dati = json.loads(stato.read_text(encoding="utf-8"))
        dati["clean"] = True
        stato.write_text(json.dumps(dati, ensure_ascii=False), encoding="utf-8")
    except Exception as exc:
        log.warning("recupero non scartabile (%s): %s", recovery.path.parent.name, exc)


def prune(root: Path | None = None, keep: int = KEEP) -> int:
    """Tiene solo le ultime sessioni chiuse: il resto e' zavorra."""
    import shutil

    cartella = Path(root) if root is not None else recovery_dir()
    chiuse = []
    for slot in sorted(cartella.glob("sessione_*"), reverse=True):
        stato = slot / STATE
        try:
            if json.loads(stato.read_text(encoding="utf-8")).get("clean"):
                chiuse.append(slot)
        except Exception:
            chiuse.append(slot)        # illeggibile e vecchia: via
    rimosse = 0
    for slot in chiuse[keep:]:
        try:
            shutil.rmtree(slot)
            rimosse += 1
        except Exception as exc:
            log.info("recupero non rimosso (%s): %s", slot.name, exc)
    return rimosse
