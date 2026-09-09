"""Costruisce la distribuzione Windows di 3DGen.

    python packaging/build.py            cartella + zip
    python packaging/build.py --clean    ricostruisce da zero
    python packaging/build.py --check    dice solo cosa manca, non costruisce

Il risultato e' `dist/3DGen/`, che contiene l'eseguibile e tutto il necessario,
piu' un `.zip` accanto. **Non e' un installer**: per generare un vero
`3DGen-setup.exe` serve Inno Setup (`iscc.exe`), che su questa macchina non e'
installato. Lo script `.iss` e' scritto e pronto in questa cartella; quando
`iscc` c'e', questo script lo usa da solo.

Perche' una cartella e non un file unico: PySide6, trimesh, scikit-image e
numpy fanno un eseguibile monolitico da centinaia di megabyte che si scompatta
in una cartella temporanea a **ogni** avvio, con secondi di attesa. La cartella
parte subito, e per l'utente finale la differenza sparisce dentro l'installer.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGING = ROOT / "packaging"
DIST = ROOT / "dist"
BUILD = ROOT / "build"
NAME = "3DGen"

# Cio' che l'applicazione legge da file a runtime e che PyInstaller non puo'
# indovinare: sono dati, non moduli importati.
DATA = [
    ("app/geometry/parts", "app/geometry/parts"),
    ("app/materials/finishes.json", "app/materials"),
]

# Moduli caricati per nome e mai importati staticamente: senza questi
# l'eseguibile parte e poi fallisce al primo uso, che e' il peggiore dei casi.
HIDDEN = [
    "app.geometry.templates.basic", "app.geometry.templates.building",
    "app.geometry.templates.character", "app.geometry.templates.furniture",
    "app.geometry.templates.nature", "app.geometry.templates.vehicle",
    "app.geometry.templates.weapon", "app.geometry.templates.humanoid_body",
    "skimage.measure", "skimage.morphology", "trimesh.exchange.gltf",
]

# Pesano e non servono: la UI non apre notebook e non traccia grafici.
EXCLUDE = ["matplotlib", "IPython", "notebook", "pytest", "tkinter"]


def have(command: str) -> str:
    return shutil.which(command) or ""


def check() -> list[str]:
    """Cosa manca per arrivare fino in fondo. Elenco onesto, non ottimista."""
    problemi: list[str] = []
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        problemi.append("PyInstaller non installato: pip install pyinstaller")
    if not have("iscc"):
        problemi.append("Inno Setup (iscc.exe) non trovato: si produce la "
                        "cartella e lo zip, non l'installer .exe")
    if sys.platform != "win32":
        problemi.append("questa distribuzione e' per Windows")
    return problemi


def build_folder(clean: bool = False) -> Path:
    """Esegue PyInstaller e restituisce la cartella prodotta."""
    if clean:
        for cartella in (DIST / NAME, BUILD / NAME):
            shutil.rmtree(cartella, ignore_errors=True)

    comando = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--windowed",
               "--name", NAME, "--distpath", str(DIST), "--workpath", str(BUILD),
               "--specpath", str(BUILD)]
    for sorgente, destinazione in DATA:
        comando += ["--add-data", "%s%s%s" % (ROOT / sorgente, ";" if
                                              sys.platform == "win32" else ":",
                                              destinazione)]
    for modulo in HIDDEN:
        comando += ["--hidden-import", modulo]
    for modulo in EXCLUDE:
        comando += ["--exclude-module", modulo]
    icona = PACKAGING / "3dgen.ico"
    if icona.is_file():
        comando += ["--icon", str(icona)]
    comando.append(str(ROOT / "main.py"))

    print("$ " + " ".join(comando[:6]) + " ...")
    subprocess.run(comando, check=True, cwd=ROOT)
    return DIST / NAME


def make_zip(folder: Path) -> Path:
    archivio = DIST / ("%s-windows.zip" % NAME)
    archivio.unlink(missing_ok=True)
    with zipfile.ZipFile(archivio, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for file in folder.rglob("*"):
            if file.is_file():
                zip_file.write(file, Path(NAME) / file.relative_to(folder))
    return archivio


def make_installer() -> Path | None:
    """Compila l'installer, se Inno Setup e' installato."""
    iscc = have("iscc")
    if not iscc:
        return None
    script = PACKAGING / "3dgen.iss"
    subprocess.run([iscc, str(script)], check=True, cwd=ROOT)
    prodotti = sorted(DIST.glob("%s-setup*.exe" % NAME))
    return prodotti[-1] if prodotti else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Costruisce la distribuzione Windows")
    parser.add_argument("--clean", action="store_true", help="ricostruisce da zero")
    parser.add_argument("--check", action="store_true",
                        help="controlla i prerequisiti e esce")
    args = parser.parse_args()

    problemi = check()
    for problema in problemi:
        print("  !!", problema)
    if args.check:
        return 0 if not problemi else 1
    if any("PyInstaller non installato" in p for p in problemi):
        return 1

    cartella = build_folder(clean=args.clean)
    print("cartella:", cartella)
    print("zip:     ", make_zip(cartella))
    installer = make_installer()
    print("installer:", installer or "non prodotto (manca Inno Setup)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
