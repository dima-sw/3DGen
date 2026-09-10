"""Che macchina e' questa, e quanta qualita' puo' reggere.

Il progetto nasce su una GTX 1660 Ti da 6 GB, ma non deve *assumere* quella
macchina: su un portatile con grafica integrata le risoluzioni predefinite
fanno aspettare, e su una scheda seria fanno sprecare. Qui si guarda cosa c'e'
e si sceglie un profilo, una volta sola all'avvio.

Niente dipendenze nuove: la memoria si legge con `GlobalMemoryStatusEx`
attraverso `ctypes`, i core con `os.cpu_count()`, la scheda con `nvidia-smi` se
c'e' e altrimenti con una query WMI. Ognuna di queste puo' fallire, e ognuna
fallisce restituendo "non lo so" invece di un numero inventato: un profilo
scelto su un dato sbagliato sarebbe peggio del profilo prudente.
"""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from dataclasses import dataclass

from app.core.logging_setup import get

log = get("core.hardware")

TIMEOUT = 4.0           # secondi: all'avvio non si aspetta una scheda pigra


@dataclass(frozen=True)
class Hardware:
    """Cio' che si e' riusciti a sapere. `None` vuol dire ignoto, non zero."""

    cpu_cores: int = 1
    ram_gb: float | None = None
    gpu_name: str = ""
    vram_gb: float | None = None

    def describe(self) -> str:
        ram = "%.0f GB RAM" % self.ram_gb if self.ram_gb else "RAM ignota"
        gpu = self.gpu_name or "GPU ignota"
        if self.vram_gb:
            gpu += " (%.0f GB)" % self.vram_gb
        return "%d core, %s, %s" % (self.cpu_cores, ram, gpu)


@dataclass(frozen=True)
class Quality:
    """Un profilo di qualita': quanto puo' costare un modello su questa macchina.

    Il numero che conta e' il **budget di triangoli**: il tetto oltre il quale
    si smette di aggiungere pezzi facoltativi. `detail_level` e' il livello che
    questo profilo **suggerisce** a chi non ne chiede uno — la riga di comando,
    l'interfaccia — e non e' un tetto: quante parti costruire lo dice il piano,
    e due tetti sulla stessa cosa vorrebbero dire non sapere mai quale ha
    tagliato.

    Erano tarati per il marching cubes, dove il costo dominante era la
    risoluzione della griglia. Quella pipeline non esiste piu': un modello
    composto costa quanto le parti che ha, e i numeri sono stati **rimisurati**
    su cio' che il sistema produce adesso — qualche centinaio di triangoli per
    un modello semplice, qualche migliaio per uno dettagliato.
    """

    name: str
    texture_size: int
    triangle_budget: int
    detail_level: int = 2
    reason: str = ""

    def describe(self) -> str:
        return ("%s: dettaglio %d, texture %dpx, budget %d triangoli"
                % (self.name, self.detail_level, self.texture_size,
                   self.triangle_budget))

    @property
    def factor(self) -> float:
        """Quanto questa macchina puo' spingere, rispetto a quella di riferimento.

        Lo stile e' una scelta di chi genera e va rispettata; il profilo dice
        solo quanto quella macchina regge. Moltiplicare invece di sostituire
        tiene separate le due cose.
        """
        return self.triangle_budget / PROFILES[FALLBACK].triangle_budget

    def budget(self):
        """Il budget di costruzione che questa macchina si puo' permettere."""
        from app.core.budget import Budget, standard

        base = standard()
        base.triangles = self.triangle_budget
        return base


PROFILES: dict[str, Quality] = {
    "basso": Quality("basso", texture_size=128, triangle_budget=500,
                     detail_level=1),
    "medio": Quality("medio", texture_size=256, triangle_budget=3_000,
                     detail_level=2),
    "alto": Quality("alto", texture_size=512, triangle_budget=12_000,
                    detail_level=3),
}
FALLBACK = "medio"


# --------------------------------------------------------------------------- #
# Rilevamento
# --------------------------------------------------------------------------- #
class _MemoryStatus(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


def total_ram_gb() -> float | None:
    """Memoria di sistema in GB, o None se non si riesce a leggerla."""
    try:
        if sys.platform == "win32":
            stato = _MemoryStatus()
            stato.dwLength = ctypes.sizeof(_MemoryStatus)
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stato)):
                return None
            return stato.ullTotalPhys / (1024 ** 3)
        pagine = os.sysconf("SC_PHYS_PAGES")        # POSIX
        return pagine * os.sysconf("SC_PAGE_SIZE") / (1024 ** 3)
    except Exception as exc:
        log.info("memoria di sistema non rilevata: %s", exc)
        return None


def _run(comando: list[str]) -> str:
    try:
        esito = subprocess.run(comando, capture_output=True, text=True,
                               timeout=TIMEOUT,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return esito.stdout.strip() if esito.returncode == 0 else ""
    except Exception:
        return ""


def detect_gpu() -> tuple[str, float | None]:
    """Nome della scheda e VRAM in GB. Prima NVIDIA, poi WMI, poi si rinuncia."""
    riga = _run(["nvidia-smi", "--query-gpu=name,memory.total",
                 "--format=csv,noheader,nounits"])
    if riga:
        prima = riga.splitlines()[0]
        nome, _, memoria = prima.partition(",")
        try:
            return nome.strip(), float(memoria.strip()) / 1024.0
        except ValueError:
            return nome.strip(), None

    if sys.platform == "win32":
        # WMI non riporta piu' di 4 GB di VRAM (il campo e' a 32 bit con segno),
        # quindi si prende solo il nome: un numero sbagliato sarebbe peggio.
        nome = _run(["powershell", "-NoProfile", "-Command",
                     "(Get-CimInstance Win32_VideoController | "
                     "Select-Object -First 1 -ExpandProperty Name)"])
        if nome:
            return nome.strip(), None
    return "", None


_CACHE: Hardware | None = None


def detect(refresh: bool = False) -> Hardware:
    """Rileva l'hardware una volta per processo: non cambia mentre si lavora."""
    global _CACHE
    if _CACHE is not None and not refresh:
        return _CACHE
    nome, vram = detect_gpu()
    _CACHE = Hardware(cpu_cores=os.cpu_count() or 1, ram_gb=total_ram_gb(),
                      gpu_name=nome, vram_gb=vram)
    log.info("hardware: %s", _CACHE.describe())
    return _CACHE


# --------------------------------------------------------------------------- #
# Scelta del profilo
# --------------------------------------------------------------------------- #
def choose(hardware: Hardware | None = None) -> Quality:
    """Il profilo di qualita' adatto a questa macchina.

    Il criterio e' la CPU e la memoria di sistema, non la GPU: la generazione e'
    marching cubes e numpy, cioe' lavoro di processore. La scheda conta per
    l'anteprima, non per il tempo che l'utente aspetta.
    """
    hardware = hardware or detect()
    ram = hardware.ram_gb
    core = hardware.cpu_cores

    if ram is None:
        return _con_motivo(PROFILES[FALLBACK],
                           "memoria non rilevata: profilo prudente")
    if ram < 8.0 or core <= 2:
        return _con_motivo(PROFILES["basso"],
                           "%d core e %.0f GB: meglio veloce che bello"
                           % (core, ram))
    if ram >= 24.0 and core >= 12:
        return _con_motivo(PROFILES["alto"],
                           "%d core e %.0f GB: c'e' margine per la qualita'"
                           % (core, ram))
    return _con_motivo(PROFILES["medio"],
                       "%d core e %.0f GB: profilo equilibrato" % (core, ram))


def _con_motivo(base: Quality, motivo: str) -> Quality:
    return Quality(base.name, base.texture_size, base.triangle_budget,
                   base.detail_level, reason=motivo)


def resolve(name: str = "auto") -> Quality:
    """Profilo per nome, o quello automatico. Un nome ignoto non fa fallire."""
    chiave = (name or "auto").strip().lower()
    if chiave in ("auto", ""):
        return choose()
    if chiave in PROFILES:
        return _con_motivo(PROFILES[chiave], "scelto a mano")
    log.warning("profilo di qualita' sconosciuto '%s': uso automatico", name)
    return choose()


# --------------------------------------------------------------------------- #
# Profilo in uso
# --------------------------------------------------------------------------- #
_CURRENT: Quality | None = None


def current() -> Quality:
    """Il profilo attivo: dall'ambiente se dichiarato, altrimenti automatico.

    Si decide una volta e si tiene: cambiarlo a meta' sessione renderebbe due
    versioni dello stesso modello non confrontabili.
    """
    global _CURRENT
    if _CURRENT is None:
        from app.core.config import SETTINGS

        _CURRENT = resolve(SETTINGS.quality)
        log.info("qualita': %s (%s)", _CURRENT.describe(), _CURRENT.reason)
    return _CURRENT


def use(name: str) -> Quality:
    """Cambia il profilo attivo. I modelli gia' costruiti non cambiano."""
    global _CURRENT
    _CURRENT = resolve(name)
    log.info("qualita' cambiata: %s (%s)", _CURRENT.describe(), _CURRENT.reason)
    return _CURRENT


def scaled(value: int, low: int = 24, high: int = 20_000) -> int:
    """Un numero di stile riportato alle possibilita' della macchina.

    Serve a chi ha un tetto proprio — un budget, una dimensione di texture — e
    vuole rispettarlo senza ignorare la macchina su cui gira.
    """
    return int(min(max(round(value * current().factor), low), high))
