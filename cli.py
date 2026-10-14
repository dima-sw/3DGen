"""Interfaccia a riga di comando: stessa pipeline della UI, senza finestre.

    python cli.py "una persona con la testa di rana"
    python cli.py "un albero con un nido" --out albero.glb --png
    python cli.py "una casa" --detail 3            piu' parti, non piu' triangoli
    python cli.py "una sedia" --save "Sedia buona" salva nella libreria
    python cli.py --library                        elenca la libreria
    python cli.py --find "qualcosa con le ali"     cerca per significato
    python cli.py --load <id> --out out.glb        ricarica un asset salvato
    python cli.py "una casa" --project lavoro.my3d salva la cronologia
    python cli.py --open lavoro.my3d --out finale.glb    riprende un progetto
    python cli.py "un robot" --game-ready unity          LOD e collisione
    python cli.py "un drago" --animate --out drago.glb   glTF animato
    python cli.py "una casa" --plan                il piano JSON che l'LLM ha scritto
    python cli.py "una casa" --explain             perche' e' stato scelto cio' che c'e'
    python cli.py --hardware                             profilo di qualita'
    python cli.py --recover                              riprende dopo un crash
    python cli.py --providers
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.core.config import PROVIDERS, SETTINGS  # noqa: E402
from app.core.logging_setup import setup  # noqa: E402
from app.core.session import Session  # noqa: E402


def show_providers() -> int:
    print("Catena di failover configurata: %s"
          % (" > ".join(SETTINGS.available_chain()) or "nessuna (solo regole locali)"))
    print()
    print("%-12s %-18s %-10s %-8s %s" % ("chiave", "provider", "stato", "costo", "modello"))
    for key, label, configured, free, model in SETTINGS.status_table():
        print("%-12s %-18s %-10s %-8s %s"
              % (key, label, "configurato" if configured else "-",
                 "gratis" if free else "a pagamento", model))
    print()
    for key, spec in PROVIDERS.items():
        if spec.note:
            print("  %-12s %s" % (key, spec.note))
    return 0


def show_hardware() -> int:
    from app.core.hardware import PROFILES, current, detect

    print("Hardware rilevato: %s" % detect().describe())
    profilo = current()
    print("Profilo in uso:    %s" % profilo.describe())
    print("Motivo:            %s" % profilo.reason)
    print()
    print("%-8s %-10s %-10s %s" % ("profilo", "griglia", "texture", "budget"))
    for nome, q in PROFILES.items():
        print("%-8s %-10d %-10d %d" % (nome, q.resolution, q.texture_size,
                                       q.triangle_budget))
    print()
    print("Si forza con --quality o con GEN3D_QUALITY nel .env")
    return 0


def show_library(query: str = "") -> int:
    from app.assets.library import AssetLibrary

    library = AssetLibrary()
    # per significato, non per parole esatte; ricade sul testo se serve
    records = library.semantic_search(query) if query else library.all()
    if not records:
        print("libreria vuota" if not query else "nessun asset per %r" % query)
        return 0
    print("%-40s %-14s %-22s %s" % ("id", "categoria", "nome", "contenuto"))
    for r in records:
        print("%-40s %-14s %-22s %s" % (r.id, r.category, r.name[:22], r.summary()))
    print()
    print("%d asset in %s" % (len(records), library.root))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Generatore 3D controllato dall'AI")
    ap.add_argument("prompt", nargs="?", help="descrizione dell'oggetto")
    ap.add_argument("--out", default="", help="file di output (.glb .obj .stl .ply)")
    ap.add_argument("--png", action="store_true", help="salva anche un'anteprima PNG")
    ap.add_argument("--textures", action="store_true",
                    help="aggiunge le texture procedurali. Il cartoon low poly "
                         "vive di tinte piatte: normalmente non servono")
    ap.add_argument("--provider", default="", help="forza un provider (o 'offline')")
    ap.add_argument("--detail", type=int, default=0, metavar="N", choices=(0, 1, 2, 3),
                    help="livello di dettaglio: 1 le parti principali, 3 i "
                         "dettagli del volto. Non cambia lo stile, cambia "
                         "quante parti vengono costruite")
    ap.add_argument("--style", default="", metavar="STILE",
                    help="stile visivo registrato (predefinito: low_poly)")
    ap.add_argument("--frame-policy", default="diagnose",
                    choices=("diagnose", "strict"), metavar="POLITICA",
                    help="che fare quando due componenti dichiarano convenzioni "
                         "d'asse diverse: 'diagnose' avvisa e costruisce, "
                         "'strict' non fa passare il piano")
    ap.add_argument("--explain", action="store_true",
                    help="spiega perche' sono stati scelti quei componenti")
    ap.add_argument("--seed", type=int, default=None,
                    help="riproduce esattamente una variante gia vista")
    ap.add_argument("--variants", type=int, default=1,
                    help="genera N varianti diverse dello stesso prompt")
    ap.add_argument("--plan", action="store_true", help="stampa il piano JSON")
    ap.add_argument("--providers", action="store_true", help="elenca i provider e esce")
    ap.add_argument("--save", nargs="?", const="", metavar="NOME",
                    help="salva il risultato nella libreria")
    ap.add_argument("--tags", default="", help="tag aggiuntivi, separati da virgola")
    ap.add_argument("--library", action="store_true", help="elenca la libreria e esce")
    ap.add_argument("--find", default="", metavar="TESTO",
                    help="cerca nella libreria e esce")
    ap.add_argument("--load", default="", metavar="ID",
                    help="carica un asset dalla libreria invece di generarlo")
    ap.add_argument("--project", default="", metavar="FILE.my3d",
                    help="salva il lavoro come progetto")
    ap.add_argument("--open", default="", metavar="FILE.my3d",
                    help="riprende un progetto salvato invece di generare")
    ap.add_argument("--game-ready", default="", metavar="MOTORE",
                    help="LOD e collisione per unity | unreal | godot | generic")
    ap.add_argument("--quality", default="", metavar="PROFILO",
                    help="auto | basso | medio | alto")
    ap.add_argument("--hardware", action="store_true",
                    help="mostra hardware e profilo di qualita', poi esce")
    ap.add_argument("--recover", action="store_true",
                    help="riprende l'ultima sessione non chiusa")
    ap.add_argument("--animate", nargs="?", const="auto", metavar="CLIP",
                    help="esporta un glTF animato: idle | walk | wing_beat, "
                         "separati da virgola, oppure nulla per quelle sensate")
    args = ap.parse_args()

    setup(SETTINGS.log_level)
    if args.quality:
        from app.core.hardware import use

        use(args.quality)
    if args.hardware:
        return show_hardware()
    if args.providers:
        return show_providers()
    if args.library or args.find:
        return show_library(args.find)
    if not args.prompt and not args.load and not args.open:
        ap.print_help()
        return 2

    from app.ai.provider import make_provider
    from app.core.session import Options

    session = Session(provider=make_provider(args.provider or None))
    opzioni = Options(style=args.style, detail_level=args.detail,
                      seed=args.seed or 0, frame_policy=args.frame_policy)
    if args.recover:
        from app.core import recovery

        trovate = recovery.pending()
        if not trovate:
            print("nessuna sessione da recuperare")
            return 0
        version = recovery.restore(trovate[0], session)
        print("\n>> sessione recuperata: %s (%d versioni)"
              % (trovate[0].describe(), len(session.history)))
    elif args.open:
        version = session.open_project(args.open)
        print("\n>> progetto aperto: %d versioni" % len(session.history))
    elif args.load:
        version = session.load_from_library(args.load)
    else:
        risultato = session.generate(args.prompt, opzioni)
        version = session.current
        print("\n>> planner: %s%s | %d triangoli"
              % (risultato.planner, " (corretto)" if risultato.repaired else "",
                 risultato.triangles))
        for diagnosi in risultato.diagnostics:
            if diagnosi.fatal:
                print("   !", diagnosi.describe())

    # Varianti: lo stesso prompt con un altro seme. Il piano cambia, e con lui
    # il modello; non e' una perturbazione della mesh, e' un'altra scelta.
    from dataclasses import replace

    for i in range(max(0, args.variants - 1)):
        seme = (args.seed or 0) + i + 1
        session.generate(args.prompt, replace(opzioni, seed=seme))
        print(">> variante %d: seme %d" % (i + 2, seme))

    scene = session.scene
    print("\n%s" % scene.summary())
    for check in session.checks():
        print("  %s %-26s %s" % (check.icon(), check.label, check.detail))

    if args.plan:
        print("\n" + json.dumps(version.plan.to_dict(), indent=2, ensure_ascii=False))

    if args.explain and version.result is not None:
        print()
        for riga in version.result.explain():
            print("  " + riga)
        cambiati = version.result.changes()
        if cambiati:
            print("\n  cambiati:")
            for riga in cambiati[:12]:
                print("    " + riga)

    if args.save is not None:
        tags = [t.strip() for t in args.tags.split(",") if t.strip()]
        record = session.save_to_library(args.save, tags=tags)
        print()
        print("salvato in libreria: %s  (%s)" % (record.id, record.name))
        if not args.out:
            return 0

    if args.game_ready:
        from app.build.optimize import export_game_ready, prepare_for_game

        risultato = prepare_for_game(scene, args.game_ready)
        print()
        print("game ready (%s): %s" % (risultato.preset.name, risultato.summary()))
        for nota in risultato.notes:
            print("  nota:", nota)
        cartella = SETTINGS.output_dir / ("game_" + risultato.preset.name)
        for file in export_game_ready(scene, cartella, args.game_ready,
                                      Path(args.out or "modello").stem):
            print("  ->", file)
        if not args.out:
            return 0

    if args.project:
        saved = session.save_project(args.project)
        print()
        print("progetto salvato: %s (%d versioni)" % (saved, len(session.history)))
        if not args.out:
            return 0

    if args.animate:
        nomi = ([n.strip() for n in args.animate.split(",") if n.strip()]
                if args.animate != "auto" else None)
        disponibili = session.animations()
        if not disponibili:
            print()
            print("questo modello non ha giunti da animare: serve un modello "
                  "fatto di piu' parti attaccate fra loro")
            return 1
        # Nome distinto: con lo stesso nome dell'export normale, il file statico
        # scritto poco piu' sotto sovrascriveva proprio l'animato.
        base = Path(args.out).stem if args.out else "modello"
        percorso = session.export_animated(
            SETTINGS.output_dir / ("%s_animato.glb" % base), nomi)
        print()
        print("glTF animato: %s" % percorso)
        print("  animazioni: %s" % ", ".join(nomi or disponibili))
        if not args.out:
            return 0

    out = args.out or "modello.glb"

    if args.variants > 1:
        from app.build.exporter import export as export_scene
        name = Path(out)
        for i, v in enumerate(session.history):
            target = name.with_name("%s_%d%s" % (name.stem, i + 1, name.suffix))
            path = export_scene(v.scene, target)
            print("variante %d -> %s  (seme %d)" % (i + 1, path, v.plan.seed))
            if args.png:
                from app.ui.offscreen import render
                render(v.scene, Path(path).with_suffix(".png"))
        return 0

    path = session.export(out, textured=True if args.textures else None)
    print("\nesportato: %s" % path)

    if args.png:
        from app.ui.offscreen import render
        png = render(scene, Path(path).with_suffix(".png"))
        print("anteprima: %s" % png)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
