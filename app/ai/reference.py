"""Generazione a partire da un'immagine di riferimento.

Due livelli, come per tutto il resto del progetto:

  - **locale**, sempre disponibile: dalla sagoma si ricavano proporzioni,
    allungamento, simmetria e colori dominanti. Non capisce *cosa* sia
    l'oggetto, ma sa quanto e' lungo, quanto e' alto e di che colore.
  - **vision**, quando un modello della catena accetta immagini: descrive
    l'oggetto a parole, e da li' riparte la pipeline normale.

I due si sommano: la descrizione dice cosa costruire, la misura dice con quali
proporzioni. Se il modello vision manca restano le proporzioni e il colore, che
sono gia' molto piu' di niente: e' esattamente il criterio della milestone.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from app.core.logging_setup import get

log = get("ai.reference")

# Oltre questa dimensione non si guadagna nulla: si misurano proporzioni e
# colori, non dettagli. Ridurre tiene l'analisi sotto il decimo di secondo.
MAX_SIDE = 320


class ReferenceError(ValueError):
    """L'immagine non e' utilizzabile come riferimento."""


@dataclass
class ImageHints:
    """Cio' che si puo' misurare in un'immagine senza capirla.

    `length_ratio` e `width_ratio` sono rapporti rispetto all'altezza. Con una
    sola vista il rapporto trasversale resta ignoto (`None`): meglio dichiararlo
    che inventarlo.
    """

    aspect: float = 1.0             # larghezza / altezza della sagoma
    elongation: float = 1.0         # lato lungo / lato corto
    coverage: float = 0.0           # quanta immagine occupa l'oggetto
    symmetry: float = 0.0           # quanto e' speculare sull'asse verticale
    colours: list[str] = field(default_factory=list)
    dominant: str = "#9aa0a6"
    length_ratio: float = 1.0
    width_ratio: float | None = None
    views: int = 1
    # Template del catalogo la cui sagoma somiglia di piu': e' un'ipotesi, non
    # un riconoscimento, e vale solo quando manca una descrizione a parole.
    shape: str = ""

    def describe(self) -> str:
        trasversale = ("larghezza %.2f" % self.width_ratio
                       if self.width_ratio else "larghezza ignota")
        forma = ", sagoma da '%s'" % self.shape if self.shape else ""
        return ("lunghezza %.2f, %s, simmetria %.0f%%, colore %s, %d vista/e%s"
                % (self.length_ratio, trasversale, self.symmetry * 100,
                   self.dominant, self.views, forma))


# --------------------------------------------------------------------------- #
# Misura
# --------------------------------------------------------------------------- #
def _load_pixels(path: Path) -> np.ndarray:
    from PIL import Image

    try:
        with Image.open(path) as opened:
            image = opened.convert("RGB")
    except Exception as exc:                     # file rotto, formato ignoto
        raise ReferenceError("immagine illeggibile: %s" % exc) from exc
    scale = MAX_SIDE / max(image.size)
    if scale < 1.0:
        image = image.resize((max(int(image.width * scale), 1),
                              max(int(image.height * scale), 1)))
    return np.asarray(image, dtype=float) / 255.0


def _background_colours(border: np.ndarray, count: int = 3) -> np.ndarray:
    """I colori di sfondo, che in una foto quasi mai sono uno solo.

    Cielo sopra e asfalto sotto sono due sfondi diversi: con un colore medio
    solo, la striscia di asfalto finiva dentro la sagoma dell'auto e la faceva
    misurare larga quanto l'inquadratura.
    """
    rng = np.random.default_rng(0)
    k = min(count, len(border))
    centres = border[rng.choice(len(border), size=k, replace=False)].copy()
    for _ in range(6):
        distances = np.linalg.norm(border[:, None, :] - centres[None, :, :], axis=-1)
        assignment = np.argmin(distances, axis=1)
        for index in range(k):
            chosen = border[assignment == index]
            if len(chosen):
                centres[index] = chosen.mean(axis=0)
    # Uno sfondo che occupa una manciata di pixel del bordo e' probabilmente
    # l'oggetto che tocca il margine, non lo sfondo: non lo si tiene.
    quote = np.array([(assignment == i).mean() for i in range(k)])
    return centres[quote > 0.08]


def silhouette(pixels: np.ndarray, tolerance: float = 0.18) -> np.ndarray:
    """Maschera dell'oggetto, assumendo che lo sfondo tocchi i bordi.

    Non e' segmentazione: e' una soglia sulla distanza dai colori di bordo.
    Basta a misurare proporzioni, e quando non basta lo dice: se la maschera
    prende quasi tutto o quasi niente si considera l'immagine intera, cosi' i
    numeri restano definiti anche su una foto senza sfondo riconoscibile.
    """
    border = np.concatenate([pixels[0], pixels[-1], pixels[:, 0], pixels[:, -1]])
    background = _background_colours(border)
    if len(background) == 0:
        return np.ones(pixels.shape[:2], dtype=bool)
    distances = np.linalg.norm(pixels[:, :, None, :] - background[None, None, :, :],
                               axis=-1)
    mask = distances.min(axis=2) > tolerance
    if not 0.02 < mask.mean() < 0.98:
        return np.ones(pixels.shape[:2], dtype=bool)
    return _largest_blob(_open(mask))


def _open(mask: np.ndarray) -> np.ndarray:
    """Toglie le righe sottili, che non sono oggetti.

    Dove due sfondi si toccano — cielo e asfalto — i pixel di confine sono una
    media dei due e non somigliano a nessuno dei due: entravano nella sagoma
    come una riga larga quanto l'inquadratura. Un'apertura 3x3 le cancella;
    l'immagine e' sempre ridotta a MAX_SIDE pixel di lato, quindi "sottile" ha una
    misura prevedibile.
    """
    from skimage.morphology import opening

    aperta = opening(mask, np.ones((3, 3), dtype=bool))
    return aperta if aperta.any() else mask


def _largest_blob(mask: np.ndarray) -> np.ndarray:
    """Tiene solo la macchia connessa piu' grande: l'oggetto, non i riflessi.

    L'etichettatura e' quella di scikit-image, che il progetto usa gia' per il
    marching cubes: nessuna dipendenza nuova per una funzione sola.
    """
    from skimage.measure import label

    labels = label(mask, connectivity=2)
    if labels.max() <= 1:
        return mask
    conteggi = np.bincount(labels.ravel())
    conteggi[0] = 0
    vincitore = int(np.argmax(conteggi))
    # Una macchia che vale meno di un terzo del totale acceso non e' "l'oggetto":
    # e' un'immagine frammentata, e tenerne un pezzo solo falserebbe le misure.
    if conteggi[vincitore] < mask.sum() * 0.34:
        return mask
    return labels == vincitore


def dominant_colours(pixels: np.ndarray, mask: np.ndarray, count: int = 4,
                     seed: int = 0) -> list[str]:
    """K-medie in poche iterazioni: serve la tinta principale, non una palette.

    Ordinate per numero di pixel, cosi' la prima e' il colore che l'occhio
    chiamerebbe "il colore dell'oggetto".
    """
    points = pixels[mask]
    if len(points) < count:
        points = pixels.reshape(-1, 3)
    if len(points) == 0:
        return []
    rng = np.random.default_rng(seed)
    k = min(count, len(points))
    centres = points[rng.choice(len(points), size=k, replace=False)].copy()
    assignment = np.zeros(len(points), dtype=int)
    for _ in range(8):
        distances = np.linalg.norm(points[:, None, :] - centres[None, :, :], axis=-1)
        assignment = np.argmin(distances, axis=1)
        for index in range(k):
            chosen = points[assignment == index]
            if len(chosen):
                centres[index] = chosen.mean(axis=0)
    order = np.argsort([int((assignment == i).sum()) for i in range(k)])[::-1]
    tinte = ["#" + "".join("%02x" % int(round(float(np.clip(c, 0.0, 1.0)) * 255))
                           for c in centres[i]) for i in order]
    # Su un'immagine con due soli colori le k medie collassano: senza deduplica
    # la "tavolozza" sarebbe lo stesso colore ripetuto quattro volte.
    return list(dict.fromkeys(tinte))


def analyse(path: str | Path, seed: int = 0) -> ImageHints:
    """Misura una singola immagine: proporzioni, simmetria, colori."""
    source = Path(path)
    if not source.is_file():
        raise ReferenceError("immagine inesistente: %s" % source)

    pixels = _load_pixels(source)
    mask = silhouette(pixels)
    rows = np.flatnonzero(mask.any(axis=1))
    cols = np.flatnonzero(mask.any(axis=0))
    if len(rows) == 0 or len(cols) == 0:
        raise ReferenceError("nessun oggetto distinguibile dallo sfondo")
    hints = _measure(pixels, mask, rows, cols, seed)
    hints.shape = guess_shape(mask, hints.aspect)
    log.info("riferimento %s: %s", source.name, hints.describe())
    return hints


def guess_shape(mask: np.ndarray, aspect: float) -> str:
    """Il template del catalogo con la sagoma piu' simile, se la scelta e' netta.

    Non e' un riconoscimento semantico: e' un confronto di forme con cio' che
    sappiamo gia' costruire (vedi `app/ai/shape_match.py`). Serve solo quando
    non c'e' ne' un modello vision ne' una descrizione dell'utente.
    """
    from app.ai import shape_match

    try:
        esito = shape_match.match(mask, aspect)
    except Exception as exc:                     # mai bloccare per un'ipotesi
        log.info("sagoma non confrontata (%s)", exc)
        return ""
    return esito.template if esito is not None and esito.confident else ""


def _measure(pixels, mask, rows, cols, seed: int) -> ImageHints:
    """I numeri veri e propri, una volta isolata la sagoma."""
    height = float(rows[-1] - rows[0] + 1)
    width = float(cols[-1] - cols[0] + 1)
    box = mask[rows[0]:rows[-1] + 1, cols[0]:cols[-1] + 1]

    colours = dominant_colours(pixels, mask, seed=seed)
    aspect = width / max(height, 1.0)
    return ImageHints(
        aspect=aspect,
        elongation=max(width, height) / max(min(width, height), 1.0),
        coverage=float(mask.mean()),
        symmetry=float((box == box[:, ::-1]).mean()),
        colours=colours,
        dominant=colours[0] if colours else "#9aa0a6",
        length_ratio=aspect,
    )


def analyse_views(side: str | Path, front: str | Path | None = None,
                  seed: int = 0) -> ImageHints:
    """Fonde due viste: il fianco da' la lunghezza, il fronte la larghezza.

    Con una vista sola la profondita' resta indeterminata e il template usa il
    proprio valore predefinito. Con due, la scatola e' completa.
    """
    hints = analyse(side, seed=seed)
    if front is None:
        return hints

    davanti = analyse(front, seed=seed)
    hints.width_ratio = davanti.aspect
    hints.views = 2
    # Il colore si decide sulla vista che mostra piu' oggetto: e' quella che
    # ha piu' pixel da cui ricavarlo.
    if davanti.coverage > hints.coverage * 1.25:
        hints.colours, hints.dominant = davanti.colours, davanti.dominant
    log.info("due viste: %s", hints.describe())
    return hints


# --------------------------------------------------------------------------- #
# Descrizione con un modello vision
# --------------------------------------------------------------------------- #
VISION_PROMPT = (
    "Descrivi l'oggetto principale di questa immagine in una frase sola, in "
    "italiano, come una richiesta di modellazione 3D: che cosa e', di che "
    "colore, con quali proporzioni. Niente sfondo, niente contesto, niente "
    'elenchi. Rispondi in JSON: {"descrizione": "..."}'
)


def image_data_url(path: str | Path) -> str:
    source = Path(path)
    suffix = source.suffix.lower().lstrip(".") or "png"
    mime = "jpeg" if suffix in ("jpg", "jpeg") else suffix
    payload = base64.b64encode(source.read_bytes()).decode("ascii")
    return "data:image/%s;base64,%s" % (mime, payload)


def describe_with_vision(path: str | Path, provider) -> str:
    """Chiede a un modello che accetta immagini di dire cosa c'e'.

    **Dipende da un servizio esterno.** Se il provider manca, non accetta
    immagini o risponde male, si restituisce stringa vuota: la generazione
    prosegue con le sole misure, che sono sempre disponibili.
    """
    if provider is None or not hasattr(provider, "complete_json"):
        return ""
    try:
        content = [
            {"type": "text", "text": VISION_PROMPT},
            {"type": "image_url", "image_url": {"url": image_data_url(path)}},
        ]
        payload = provider.complete_json(
            "Sei un assistente che descrive immagini per un modellatore 3D.",
            content, temperature=0.2)
        if not isinstance(payload, dict):
            return ""
        text = payload.get("descrizione") or payload.get("description") or ""
        return str(text).strip()
    except Exception as exc:                     # qualunque guaio: si va avanti
        log.info("nessuna descrizione dall'immagine (%s): uso le sole misure", exc)
        return ""


# --------------------------------------------------------------------------- #
# Dalle misure al piano
# --------------------------------------------------------------------------- #
def prompt_from_image(path: str | Path, extra: str = "", provider=None,
                      front: str | Path | None = None) -> tuple[str, ImageHints]:
    """Costruisce la richiesta testuale da un'immagine, insieme alle misure."""
    hints = analyse_views(path, front)
    described = describe_with_vision(path, provider) if provider is not None else ""
    pieces = [p for p in (described.strip(), extra.strip()) if p]
    if not pieces:
        pieces.append(_words_for(hints))
    return " ".join(pieces), hints


def _words_for(hints: ImageHints) -> str:
    """La richiesta da usare quando nessuno ha detto cosa c'e' nella foto.

    Prima si prova con la sagoma: se somiglia in modo netto a qualcosa che il
    catalogo sa costruire, si usa il nome di quella cosa e il resto della
    pipeline procede come se l'utente l'avesse scritto. Altrimenti resta una
    descrizione puramente geometrica, che e' poco ma e' vera.
    """
    from app.geometry.templates import TEMPLATES, load_all

    if hints.shape:
        load_all()
        template = TEMPLATES.get(hints.shape)
        if template is not None and template.keywords:
            return "%s di colore %s" % (template.keywords[0], hints.dominant)
    forma = "allungato" if hints.elongation > 1.6 else "compatto"
    return "un oggetto %s di colore %s" % (forma, hints.dominant)


def _primary_material(plan) -> str:
    """Il materiale che rappresenta 'il colore dell'oggetto'."""
    from app.geometry.templates import TEMPLATES, load_all

    load_all()
    template = TEMPLATES.get(plan.template)
    if template is not None and template.primary_material:
        return template.primary_material
    if plan.assembly is not None and plan.assembly.parts:
        # nell'assemblaggio vince il materiale usato da piu' parti
        conteggio: dict[str, int] = {}
        for part in plan.assembly.parts:
            if part.material:
                conteggio[part.material] = conteggio.get(part.material, 0) + 1
        if conteggio:
            return max(conteggio, key=lambda k: conteggio[k])
    return plan.materials[0].name if plan.materials else ""


def apply_hints(plan, hints: ImageHints, colour: bool = True,
                proportions: bool = True):
    """Porta nel piano cio' che l'immagine dice con certezza.

    Il colore e le proporzioni misurate valgono piu' di quelli scelti dal
    planner: vengono anche bloccati, cosi' le varianti successive continuano ad
    assomigliare al riferimento invece di allontanarsene.
    """
    from app.core.spec import MaterialSpec
    from app.geometry.templates import TEMPLATES, load_all

    load_all()
    template = TEMPLATES.get(plan.template)
    applied: list[str] = []

    name = _primary_material(plan) if colour else ""
    if name:
        base = next((m for m in plan.materials if m.name == name), None)
        if base is None and template is not None:
            base = template.materials.get(name)
        plan.materials = [m for m in plan.materials if m.name != name]
        plan.materials.append(MaterialSpec(
            name=name, base_color=hints.dominant,
            roughness=base.roughness if base else 0.6,
            metallic=base.metallic if base else 0.0,
            opacity=base.opacity if base else 1.0))
        if name not in plan.locked:
            plan.locked.append(name)
        applied.append("colore %s dall'immagine" % hints.dominant)

    if proportions and template is not None and "height" in template.params:
        altezza = float(plan.params.get("height", template.params["height"].default))
        for chiave, rapporto in (("length", hints.length_ratio),
                                 ("width", hints.width_ratio)):
            if chiave not in template.params or rapporto is None:
                continue
            valore = template.params[chiave].coerce(altezza * max(float(rapporto), 0.05))
            plan.params[chiave] = valore
            if chiave not in plan.locked:
                plan.locked.append(chiave)
            applied.append("%s %.2f m dall'immagine" % (chiave, valore))

    if applied:
        plan.notes = (plan.notes + " | " + "; ".join(applied)).strip(" |")
    log.info("riferimento applicato: %s", ", ".join(applied) or "niente")
    return plan
