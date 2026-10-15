"""Finestra principale dell'applicazione."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QListWidget, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar,
    QInputDialog, QLineEdit, QListWidgetItem, QPushButton, QSplitter, QStatusBar,
    QTabWidget, QTextBrowser, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from app.assets.library import AssetRecord
from app.core.config import PROVIDERS, SETTINGS
from app.core.logging_setup import get, tail
from app.core.session import Session, Version
from app.ui.viewport import Viewport
from app.ui.workers import ExportWorker, GenerationWorker, run_in_thread

log = get("ui.window")

STYLESHEET = """
QWidget { background: #16181d; color: #d6dae0; font-size: 13px; }
QGroupBox { border: 1px solid #262a32; border-radius: 6px; margin-top: 10px; padding-top: 8px; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; color: #8e97a5; }
QPlainTextEdit, QTextBrowser, QTreeWidget, QListWidget, QComboBox, QDoubleSpinBox {
    background: #1c1f26; border: 1px solid #2b303a; border-radius: 5px; padding: 4px;
    selection-background-color: #3a6ea8;
}
QPushButton {
    background: #262b35; border: 1px solid #333945; border-radius: 5px; padding: 7px 12px;
}
QPushButton:hover { background: #2f3542; }
QPushButton:disabled { color: #5a6069; background: #1d2027; }
QPushButton#primary { background: #2f6f4f; border-color: #3d8a63; font-weight: 600; }
QPushButton#primary:hover { background: #38845e; }
QProgressBar { background: #1c1f26; border: 1px solid #2b303a; border-radius: 5px; height: 8px;
               text-align: center; }
QProgressBar::chunk { background: #3d8a63; border-radius: 4px; }
QTabBar::tab { background: #1c1f26; padding: 6px 12px; border: 1px solid #2b303a; }
QTabBar::tab:selected { background: #262b35; }
QSplitter::handle { background: #22262e; }
"""

EXAMPLES = [
    "Crea una Jeep militare 4x4 verde con ruote grandi e senza tetto",
    "Un'auto sportiva rossa a due porte con alettone",
    "Una casa a due piani con tetto a capanna e portico",
    "Un robot umanoide con armatura futuristica e zaino a reattori",
    "Una spada medievale a due mani con gemma sul pomolo",
    "Un tavolo rotondo in legno da 1.2 metri",
    "Un pino alto 8 metri",
]


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.session = Session(autosave=True)
        self._ai_settings = QSettings("3DGen", "3DGen")
        self.busy = False
        self.last_mode = "generate"
        self.setWindowTitle("3DGen - generatore 3D controllato dall'AI")
        self.resize(1500, 900)
        self.setStyleSheet(STYLESHEET)
        self._build_ui()
        self._populate_ai_controls()
        self._refresh_provider_label()
        self.refresh_library()
        self._log_ai("Pronto. Descrivi l'oggetto che vuoi creare e premi Genera.")
        self._announce_quality()
        self._offer_recovery()

    # --------------------------------------------------------------- UI #
    def _build_ui(self) -> None:
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._left_panel())
        self.viewport = Viewport()
        splitter.addWidget(self.viewport)
        splitter.addWidget(self._right_panel())
        splitter.setSizes([360, 720, 420])
        self.setCentralWidget(splitter)

        self.setStatusBar(QStatusBar())
        self.status = QLabel("Nessun modello")
        self.statusBar().addWidget(self.status)

        tb = self.addToolBar("Azioni")
        tb.setMovable(False)
        self.act_undo = QAction("Annulla", self)
        self.act_undo.setShortcut(QKeySequence.StandardKey.Undo)
        self.act_undo.triggered.connect(self.on_undo)
        self.act_redo = QAction("Ripeti", self)
        self.act_redo.setShortcut(QKeySequence.StandardKey.Redo)
        self.act_redo.triggered.connect(self.on_redo)
        act_open_prj = QAction("Apri progetto", self)
        act_open_prj.setShortcut(QKeySequence.StandardKey.Open)
        act_open_prj.triggered.connect(self.on_open_project)
        act_save_prj = QAction("Salva progetto", self)
        act_save_prj.triggered.connect(self.on_save_project)
        act_save_lib = QAction("Salva in libreria", self)
        act_save_lib.triggered.connect(self.on_library_save)
        act_export = QAction("Esporta...", self)
        act_export.setShortcut(QKeySequence.StandardKey.Save)
        act_export.triggered.connect(self.on_export)
        act_view = QAction("Reimposta vista", self)
        act_view.triggered.connect(lambda: self.viewport.reset_view())
        act_tex = QAction("Texture", self)
        act_tex.setCheckable(True)
        act_tex.setChecked(True)
        act_tex.triggered.connect(self._toggle_textures)
        act_grid = QAction("Griglia", self)
        act_grid.setCheckable(True)
        act_grid.setChecked(True)
        act_grid.triggered.connect(self._toggle_grid)
        # [V6] Le due porte dell'authoring. Condividono la `Session` di questa
        # finestra, cosi' un plugin installato dall'authoring e' subito
        # generabile da qui — senza riavviare, che e' il punto.
        act_authoring = QAction("Authoring", self)
        act_authoring.triggered.connect(self.on_open_authoring)
        act_lab = QAction("Component Lab", self)
        act_lab.triggered.connect(self.on_open_component_lab)
        # [V7] La terza porta: insegnare un concetto. Condivide la stessa
        # `Session`, cosi' un componente imparato e' subito generabile da qui.
        act_teach = QAction("Teach", self)
        act_teach.triggered.connect(self.on_open_teach)
        for a in (act_open_prj, act_save_prj, self.act_undo, self.act_redo,
                  act_save_lib, act_export, act_view, act_tex, act_grid,
                  act_authoring, act_lab, act_teach):
            tb.addAction(a)
        self._authoring_window = None
        self._teach_window = None
        self._sync_actions()

    # ------------------------------------------------------------ authoring #
    def on_open_authoring(self):
        """Apre la finestra di authoring sulla stessa sessione."""
        from app.ui.authoring_window import AuthoringWindow

        if self._authoring_window is None:
            self._authoring_window = AuthoringWindow(session=self.session,
                                                     parent=self)
        self._authoring_window.show()
        self._authoring_window.raise_()
        return self._authoring_window

    def on_open_teach(self):
        """Apre Teach 3DGen sulla stessa sessione.

        La stessa, non una nuova: un concetto imparato installa componenti, e
        chi li ha imparati deve poterli generare subito dalla finestra
        principale senza riavviare. E' la ragione per cui
        `Session.reload_plugins` sta su `Session` e non nei livelli sopra.
        """
        from app.ui.teach_window import TeachWindow

        if self._teach_window is None:
            self._teach_window = TeachWindow(session=self.session, parent=self)
        self._teach_window.show()
        self._teach_window.raise_()
        return self._teach_window

    def on_open_component_lab(self, component_id: str = ""):
        """Il Component Lab su un componente installato, scelto da un elenco.

        L'elenco e' il registry: la scheda «Libreria» mostra gli asset salvati
        e non cio' che i plugin forniscono, che era il divario annotato in
        `VISION-GAP` §6. Qui si sfoglia il vocabolario installato.
        """
        from app.authoring import ComponentLab
        from app.ui.authoring_window import ComponentLabDialog

        if not component_id:
            ids = [c.id for c in self.session.catalog().components()]
            if not ids:
                return None
            component_id, ok = QInputDialog.getItem(self, "Component Lab",
                                                    "componente installato",
                                                    ids, 0, False)
            if not ok or not component_id:
                return None
        try:
            lab = ComponentLab(self.session, component_id)
        except ValueError as exc:
            QMessageBox.warning(self, "Component Lab", str(exc))
            return None
        dialog = ComponentLabDialog(lab, parent=self)
        dialog.show()
        return dialog

    # ------------------------------------------------- qualita e recupero #
    def _announce_quality(self) -> None:
        """Dice all'utente su che profilo sta lavorando e perche'."""
        from app.core.hardware import current, detect

        profilo = current()
        self._log_ai("Hardware: %s.<br>Qualita': <b>%s</b> — %s."
                     % (detect().describe(), profilo.name, profilo.reason))

    def _offer_recovery(self) -> None:
        """Se l'ultima sessione non e' stata chiusa, propone di riprenderla.

        Si propone, non si ripristina d'ufficio: riaprire da soli il lavoro di
        ieri sopra quello di adesso sarebbe peggio del crash.
        """
        from app.core import recovery

        try:
            trovate = recovery.pending()
        except Exception as exc:
            log.warning("recuperi non leggibili: %s", exc)
            return
        if not trovate:
            return

        ultima = trovate[0]
        risposta = QMessageBox.question(
            self, "Sessione da recuperare",
            "L'ultima sessione non e' stata chiusa correttamente.\n\n%s\n\n"
            "Vuoi riprenderla?" % ultima.describe(),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if risposta != QMessageBox.StandardButton.Yes:
            recovery.discard(ultima)
            self._log_ai("Recupero rifiutato. Il file resta in %s finche' non "
                         "viene sostituito da sessioni piu' recenti."
                         % ultima.path.parent)
            return
        try:
            recovery.restore(ultima, self.session)
        except Exception as exc:
            self._log_ai("<span style='color:#d9776a'>Recupero fallito: %s</span>" % exc)
            return
        self._log_ai("Sessione recuperata: %d versioni." % len(self.session.history))
        self.refresh_all()

    def closeEvent(self, event) -> None:
        """Chiusura regolare: niente da recuperare la prossima volta."""
        try:
            self.session.stop_autosave()
        except Exception as exc:
            log.warning("chiusura dell'autosalvataggio: %s", exc)
        super().closeEvent(event)

    def _left_panel(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)

        lay.addWidget(QLabel("<b>Descrizione</b>"))
        self.prompt = QPlainTextEdit()
        self.prompt.setPlaceholderText("Es. Crea una Jeep militare 4x4 verde con ruote grandi")
        self.prompt.setMaximumHeight(90)
        lay.addWidget(self.prompt)

        self.examples = QComboBox()
        self.examples.addItem("Esempi...")
        self.examples.addItems(EXAMPLES)
        self.examples.currentIndexChanged.connect(self._use_example)
        lay.addWidget(self.examples)

        row = QHBoxLayout()
        row.addWidget(QLabel("Dettaglio"))
        # Lo stile e' uno solo — cartoon low poly — quindi non c'e' niente da
        # scegliere. Resta la densita': lo stesso modello, piu' o meno fitto.
        self.density_box = QComboBox()
        self.density_box.addItems(["normale", "essenziale", "dettagliato"])
        self.density_box.setToolTip("Quante parti costruire. Non cambia lo "
                                    "triangoli servono a ottenerlo.")
        row.addWidget(self.density_box, 1)
        lay.addLayout(row)

        ai_box = QGroupBox("Provider AI")
        ai_form = QFormLayout(ai_box)
        self.provider_box = QComboBox()
        self.provider_box.currentIndexChanged.connect(self._on_provider_changed)
        self.failover_box = QCheckBox("Failover automatico")
        self.failover_box.setToolTip(
            "Se disattivato, il provider selezionato fallisce "
            "senza passare a un altro provider.")
        self.failover_box.stateChanged.connect(self._persist_ai_selection)
        ai_form.addRow("Provider", self.provider_box)
        ai_form.addRow("", self.failover_box)
        lay.addWidget(ai_box)

        self.btn_generate = QPushButton("Genera")
        self.btn_generate.setObjectName("primary")
        self.btn_generate.clicked.connect(lambda: self.on_run("generate"))
        lay.addWidget(self.btn_generate)

        self.btn_regenerate = QPushButton("Ricostruisci dal piano")
        self.btn_regenerate.setToolTip(
            "Ricostruisce la geometria dal piano corrente, senza chiedere "
            "niente a un modello: serve dopo aver cambiato un parametro.")
        self.btn_regenerate.clicked.connect(self.on_regenerate)
        lay.addWidget(self.btn_regenerate)

        self.btn_image = QPushButton("Genera da un'immagine...")
        self.btn_image.setVisible(False)   # la lettura di un'immagine e' da rifare
        self.btn_image.setToolTip("Da una foto si ricavano colore e proporzioni. "
                                  "La descrizione qui sopra, se c'e', vale comunque.")
        self.btn_image.clicked.connect(self.on_reference_image)
        lay.addWidget(self.btn_image)

        self.btn_modify = QPushButton("Modifica il modello attuale")
        self.btn_modify.setVisible(False)   # si modifica il piano, non il modello
        self.btn_modify.setEnabled(False)
        lay.addWidget(self.btn_modify)

        self.btn_variant = QPushButton("Un'altra variante  (F5)")
        self.btn_variant.setToolTip("Stesso oggetto, proporzioni e dettagli diversi. "
                                    "Non consuma chiamate all'AI.")
        self.btn_variant.setShortcut("F5")
        self.btn_variant.clicked.connect(lambda: self.on_run("variant"))
        self.btn_variant.setEnabled(False)
        lay.addWidget(self.btn_variant)

        self.btn_save_lib = QPushButton("Salva nella libreria")
        self.btn_save_lib.setToolTip("Conserva l'oggetto con il suo piano: "
                                     "ricaricandolo resta modificabile a voce.")
        self.btn_save_lib.clicked.connect(self.on_library_save)
        self.btn_save_lib.setEnabled(False)
        lay.addWidget(self.btn_save_lib)

        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        lay.addWidget(self.progress)

        box = QGroupBox("Conversazione")
        bl = QVBoxLayout(box)
        self.chat = QTextBrowser()
        bl.addWidget(self.chat)
        lay.addWidget(box, 1)

        self.provider_label = QLabel()
        self.provider_label.setWordWrap(True)
        self.provider_label.setStyleSheet("color:#8e97a5; font-size:11px;")
        lay.addWidget(self.provider_label)
        return w

    def _right_panel(self) -> QWidget:
        tabs = QTabWidget()

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Parte", "Triangoli"])
        self.tree.setColumnWidth(0, 200)
        tabs.addTab(self.tree, "Scena")

        params_page = QWidget()
        pl = QVBoxLayout(params_page)
        self.params_form_host = QWidget()
        self.params_form = QFormLayout(self.params_form_host)
        pl.addWidget(self.params_form_host)
        self.btn_apply = QPushButton("Applica parametri")
        self.btn_apply.clicked.connect(self.on_apply_params)
        self.btn_apply.setEnabled(False)
        pl.addWidget(self.btn_apply)
        pl.addStretch(1)
        tabs.addTab(params_page, "Parametri")

        self.checks = QListWidget()
        tabs.addTab(self.checks, "Qualita")

        self.history_list = QListWidget()
        self.history_list.itemClicked.connect(self.on_history_click)
        tabs.addTab(self.history_list, "Versioni")

        tabs.addTab(self._animation_page(), "Animazione")
        tabs.addTab(self._library_page(), "Libreria")

        self.log_view = QTextBrowser()
        tabs.addTab(self.log_view, "Log")
        tabs.currentChanged.connect(self._maybe_refresh_log)
        self.tabs = tabs
        return tabs

    def _animation_page(self) -> QWidget:
        """Riproduzione delle animazioni e export glTF animato.

        Le animazioni esistono solo per i modelli composti di parti: un oggetto
        da template non ha giunti, e la scheda lo dice invece di restare vuota.
        """
        page = QWidget()
        lay = QVBoxLayout(page)

        self.anim_note = QLabel()
        self.anim_note.setWordWrap(True)
        self.anim_note.setStyleSheet("color:#8e97a5; font-size:11px;")
        lay.addWidget(self.anim_note)

        row = QHBoxLayout()
        row.addWidget(QLabel("Animazione"))
        self.anim_box = QComboBox()
        self.anim_box.currentIndexChanged.connect(self._on_animation_changed)
        row.addWidget(self.anim_box, 1)
        lay.addLayout(row)

        self.btn_play = QPushButton("Riproduci")
        self.btn_play.setCheckable(True)
        self.btn_play.toggled.connect(self.on_play)
        self.btn_play.setEnabled(False)
        lay.addWidget(self.btn_play)

        self.btn_export_anim = QPushButton("Esporta glTF animato...")
        self.btn_export_anim.clicked.connect(self.on_export_animated)
        self.btn_export_anim.setEnabled(False)
        lay.addWidget(self.btn_export_anim)

        self.anim_joints = QListWidget()
        lay.addWidget(self.anim_joints, 1)

        # Un timer, non un thread: posare uno scheletro e' qualche moltiplicazione
        # di matrici, non blocca nulla.
        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(40)                 # 25 fotogrammi al secondo
        self._anim_timer.timeout.connect(self._advance_animation)
        self._anim_time = 0.0
        self._anim_clip = None
        self._anim_skeleton = None
        return page

    def _on_animation_changed(self, index: int) -> None:
        self._anim_clip = None
        self._anim_time = 0.0
        if self.btn_play.isChecked():
            self.btn_play.setChecked(False)

    def _current_clip(self):
        from app.anim import clip as clip_module

        nome = self.anim_box.currentText()
        if not nome or self._anim_skeleton is None:
            return None
        if self._anim_clip is None or self._anim_clip.name != nome:
            self._anim_clip = clip_module.make(nome, self._anim_skeleton)
        return self._anim_clip

    def on_play(self, playing: bool) -> None:
        self.btn_play.setText("Ferma" if playing else "Riproduci")
        if playing and self._current_clip() is not None:
            self._anim_timer.start()
        else:
            self._anim_timer.stop()
            self._anim_time = 0.0
            self.viewport.set_scene(self.session.scene)

    def _advance_animation(self) -> None:
        from app.anim import pose as pose_module

        animazione = self._current_clip()
        scene = self.session.scene
        if animazione is None or scene is None:
            self.btn_play.setChecked(False)
            return
        self._anim_time = (self._anim_time + 0.04) % max(animazione.duration, 1e-3)
        self.viewport.set_scene(pose_module.posed_scene(
            scene, self._anim_skeleton, animazione, self._anim_time))

    def on_export_animated(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Esporta glTF animato",
            str(SETTINGS.output_dir / "modello_animato.glb"), "glTF binario (*.glb)")
        if not path:
            return
        try:
            scritto = self.session.export_animated(path)
        except Exception as exc:
            self._log_ai("<span style='color:#d9776a'>Export animato fallito: %s</span>"
                         % exc)
            return
        self._log_ai("glTF animato esportato: %s" % scritto)
        self.statusBar().showMessage("Esportato %s" % scritto, 6000)

    def _fill_animations(self) -> None:
        from app.anim import skeleton as skeleton_module

        if self.btn_play.isChecked():
            self.btn_play.setChecked(False)
        self._anim_clip = None
        scene = self.session.scene
        self._anim_skeleton = (skeleton_module.from_scene(scene)
                               if scene is not None else None)

        self.anim_box.blockSignals(True)
        self.anim_box.clear()
        self.anim_joints.clear()
        disponibili = self.session.animations() if scene is not None else []
        self.anim_box.addItems(disponibili)
        self.anim_box.blockSignals(False)

        self.btn_play.setEnabled(bool(disponibili))
        self.btn_export_anim.setEnabled(bool(disponibili))
        if not disponibili:
            self.anim_note.setText(
                "Questo modello non ha giunti da animare: le animazioni "
                "esistono per i modelli composti di parti (creature, oggetti "
                "assemblati), non per quelli generati da un template.")
            return

        giunti = self._anim_skeleton.joints if self._anim_skeleton else []
        self.anim_note.setText(
            "%d giunti, uno per ogni attacco fra le parti. Le parti ruotano "
            "rigidamente attorno ai propri socket: sulle andature ampie la "
            "cucitura fra due parti fuse si vede." % len(giunti))
        for giunto in giunti:
            self.anim_joints.addItem("%s  <-  %s" % (giunto.name, giunto.parent or "-"))

    def _library_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)

        row = QHBoxLayout()
        self.lib_search = QLineEdit()
        self.lib_search.setPlaceholderText("Cerca per significato: una vettura, un arbusto...")
        self.lib_search.textChanged.connect(self.refresh_library)
        row.addWidget(self.lib_search, 1)
        self.lib_category = QComboBox()
        self.lib_category.addItem("tutte")
        self.lib_category.currentIndexChanged.connect(self.refresh_library)
        row.addWidget(self.lib_category)
        lay.addLayout(row)

        self.lib_list = QListWidget()
        self.lib_list.setViewMode(QListWidget.ViewMode.IconMode)
        self.lib_list.setIconSize(QSize(150, 100))
        self.lib_list.setGridSize(QSize(168, 146))
        self.lib_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.lib_list.setMovement(QListWidget.Movement.Static)
        self.lib_list.setWordWrap(True)
        self.lib_list.setSpacing(4)
        self.lib_list.itemDoubleClicked.connect(self.on_library_load)
        lay.addWidget(self.lib_list, 1)

        buttons = QHBoxLayout()
        for label, slot in (("Carica", self.on_library_load),
                            ("Rinomina", self.on_library_rename),
                            ("Elimina", self.on_library_delete)):
            b = QPushButton(label)
            b.clicked.connect(slot)
            buttons.addWidget(b)
        lay.addLayout(buttons)
        return page

    # ---------------------------------------------------------- libreria #
    def refresh_library(self) -> None:
        selected = self.lib_category.currentText()
        category = "" if selected == "tutte" else selected
        query = self.lib_search.text().strip()
        if query:
            # per significato: "una vettura" trova la jeep
            records = self.session.library.semantic_search(query, limit=60)
            if category:
                records = [r for r in records if r.category == category]
        else:
            records = self.session.library.search("", category)

        self.lib_list.clear()
        for record in records:
            item = QListWidgetItem(record.name)
            item.setData(Qt.ItemDataRole.UserRole, record.id)
            item.setToolTip("\n".join([record.name, record.summary(),
                                       "tag: " + ", ".join(record.tags[:12])]))
            preview = self.session.library.preview_path(record.id)
            if preview.is_file():
                item.setIcon(QIcon(str(preview)))
            self.lib_list.addItem(item)

        # aggiorna il filtro categorie senza perdere la scelta corrente
        categories = ["tutte"] + self.session.library.categories()
        if [self.lib_category.itemText(i) for i in range(self.lib_category.count())] != categories:
            self.lib_category.blockSignals(True)
            self.lib_category.clear()
            self.lib_category.addItems(categories)
            index = self.lib_category.findText(selected)
            self.lib_category.setCurrentIndex(max(index, 0))
            self.lib_category.blockSignals(False)

    def _selected_asset(self) -> str:
        item = self.lib_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else ""

    def on_library_save(self) -> None:
        if self.session.scene is None:
            self.statusBar().showMessage("Genera prima un modello", 4000)
            return
        versione = self.session.current
        suggested = (versione.prompt or versione.label)[:60] if versione else ""
        name, ok = QInputDialog.getText(self, "Salva nella libreria", "Nome:",
                                        QLineEdit.EchoMode.Normal, suggested)
        if not ok:
            return
        # l'anteprima e' cio' che sta gia' nel viewport: niente secondo contesto OpenGL
        preview = None
        try:
            shot = SETTINGS.output_dir / "_preview_tmp.png"
            self.viewport.grabFramebuffer().save(str(shot))
            preview = shot
        except Exception as exc:
            log.warning("anteprima dal viewport non riuscita: %s", exc)
        record = self.session.save_to_library(name.strip(), preview=preview)
        self._log_ai("Salvato nella libreria: <b>%s</b> (%s)" % (record.name, record.summary()))
        self.refresh_library()
        self.tabs.setCurrentIndex(self.tabs.count() - 2)

    def on_library_load(self) -> None:
        asset_id = self._selected_asset()
        if not asset_id:
            return
        try:
            version = self.session.load_from_library(asset_id)
        except (KeyError, ValueError) as exc:
            QMessageBox.warning(self, "Caricamento fallito", str(exc))
            return
        self._log_ai(version.message)
        self.refresh_all()

    def on_library_rename(self) -> None:
        asset_id = self._selected_asset()
        if not asset_id:
            return
        record = self.session.library.get(asset_id)
        name, ok = QInputDialog.getText(self, "Rinomina", "Nuovo nome:",
                                        QLineEdit.EchoMode.Normal, record.name if record else "")
        if ok and name.strip():
            self.session.library.rename(asset_id, name.strip())
            self.refresh_library()

    def on_library_delete(self) -> None:
        asset_id = self._selected_asset()
        if not asset_id:
            return
        record = self.session.library.get(asset_id)
        answer = QMessageBox.question(
            self, "Elimina asset",
            "Eliminare definitivamente \"%s\"?" % (record.name if record else asset_id))
        if answer == QMessageBox.StandardButton.Yes:
            self.session.library.delete(asset_id)
            self.refresh_library()

    # ----------------------------------------------------------- azioni #
    def _use_example(self, index: int) -> None:
        if index > 0:
            self.prompt.setPlainText(self.examples.itemText(index))
            self.examples.setCurrentIndex(0)

    def _toggle_grid(self, checked: bool) -> None:
        self.viewport.show_grid = checked
        self.viewport.update()

    def _toggle_textures(self, checked: bool) -> None:
        self.viewport.show_textures = checked
        self.viewport.update()

    def on_run(self, mode: str) -> None:
        text = self.prompt.toPlainText().strip()
        if mode != "variant" and not text:
            self.statusBar().showMessage("Scrivi prima una descrizione", 4000)
            return
        if self.busy or (mode == "variant" and self.session.current_plan is None):
            return
        self._apply_ai_selection()
        self._set_busy(True, "Generazione in corso...")
        if mode == "variant":
            self._log_user("un'altra variante")
        else:
            self._log_user(text)

        self.last_mode = mode
        worker = GenerationWorker(self.session, text, mode,
                                  detail=self.dettaglio())
        worker.progress.connect(lambda m: self.statusBar().showMessage(m))
        worker.finished.connect(self.on_result)
        worker.failed.connect(self.on_error)
        run_in_thread(self, worker)

    def on_regenerate(self) -> None:
        """Ricostruisce la geometria dal piano corrente."""
        if self.busy or self.session.current is None:
            return
        self.session.regenerate()
        self._log_ai("Ricostruito dal piano.")
        self.refresh_all()

    def on_reference_image(self) -> None:
        """Genera partendo da un'immagine. Da rifare sulla strada nuova.

        La lettura di un'immagine produceva un `GenerationPlan`, che non esiste
        piu'. Il pulsante resta nascosto finche' non produrra' un piano di
        composizione: lasciarlo visibile e rotto sarebbe peggio che toglierlo.
        """
        self.statusBar().showMessage(
            "La generazione da immagine e' in attesa di essere rifatta sul "
            "nuovo piano di composizione", 6000)
        return
        image, _ = QFileDialog.getOpenFileName(
            self, "Immagine di riferimento (vista laterale)", "",
            "Immagini (*.png *.jpg *.jpeg *.bmp *.webp)")
        if not image:
            return
        # La seconda vista e' facoltativa: con una sola resta ignota la larghezza.
        front, _ = QFileDialog.getOpenFileName(
            self, "Seconda vista, frontale (facoltativa)", "",
            "Immagini (*.png *.jpg *.jpeg *.bmp *.webp)")

        text = self.prompt.toPlainText().strip()
        self._set_busy(True, "Analizzo l'immagine...")
        self._log_user("immagine: %s%s" % (Path(image).name,
                                           " + " + Path(front).name if front else ""))
        self.last_mode = "image"
        worker = GenerationWorker(self.session, text, "image", image=image, front=front)
        worker.progress.connect(lambda m: self.statusBar().showMessage(m))
        worker.finished.connect(self.on_result)
        worker.failed.connect(self.on_error)
        run_in_thread(self, worker)

    DETTAGLIO = {"essenziale": 1, "normale": 2, "dettagliato": 3}

    def dettaglio(self) -> int:
        """Il livello di dettaglio scelto nella barra."""
        return self.DETTAGLIO.get(self.density_box.currentText(), 2)

    def on_result(self, version: Version) -> None:
        self._set_busy(False)
        self._log_ai("%s  <span style='color:#6d7482'>(%.1fs)</span>"
                     % (version.message, version.seconds))
        self.refresh_all()
        risultato = getattr(version, "result", None)
        if risultato is not None and risultato.actual_provider:
            richiesto = PROVIDERS.get(risultato.requested_provider)
            usato = PROVIDERS.get(risultato.actual_provider)
            richiesto = richiesto.label if richiesto else risultato.requested_provider
            usato = usato.label if usato else risultato.actual_provider
            extra = (" dopo failover" if risultato.failover_count else "")
            self.provider_label.setText(
                "Requested: %s | AI used: %s%s" % (richiesto, usato, extra))
        if self.last_mode != "variant":
            self.prompt.clear()

    def on_error(self, message: str) -> None:
        self._set_busy(False)
        self._log_ai("<span style='color:#d9776a'>Errore: %s</span>" % message)
        self.statusBar().showMessage("Generazione fallita", 5000)

    def on_undo(self) -> None:
        if self.session.undo():
            self.refresh_all()

    def on_redo(self) -> None:
        if self.session.redo():
            self.refresh_all()

    def on_history_click(self, item) -> None:
        self.session.goto(self.history_list.row(item))
        self.refresh_all()

    def on_apply_params(self) -> None:
        """Cambia i parametri della radice **nel piano**, poi ricostruisce.

        E' la differenza fra correggere un modello e correggerne la
        descrizione: la mesh non si tocca, si rifa'.
        """
        plan = self.session.current_plan
        if plan is None or not plan.root_id:
            return
        radice = plan.nodes[plan.root_id]
        for name, widget in getattr(self, "_param_widgets", {}).items():
            if isinstance(widget, QDoubleSpinBox):
                radice.overrides[name] = widget.value()
            elif isinstance(widget, QComboBox):
                radice.overrides[name] = widget.currentText()
        self.session.regenerate()
        self._log_ai("Parametri aggiornati manualmente.")
        self.refresh_all()

    def on_save_project(self) -> None:
        """Salva l'intera cronologia, non solo il modello corrente."""
        if not self.session.history:
            self.statusBar().showMessage("Non c'e' ancora niente da salvare", 4000)
            return
        default = str(SETTINGS.output_dir / "progetto.my3d")
        path, _ = QFileDialog.getSaveFileName(self, "Salva progetto", default,
                                              "Progetto 3DGen (*.my3d)")
        if not path:
            return
        preview = None
        try:
            shot = SETTINGS.output_dir / "_progetto_tmp.png"
            self.viewport.grabFramebuffer().save(str(shot))
            preview = shot
        except Exception as exc:
            log.warning("anteprima del progetto non riuscita: %s", exc)
        try:
            saved = self.session.save_project(path, name=Path(path).stem, preview=preview)
        except Exception as exc:
            QMessageBox.warning(self, "Salvataggio fallito", str(exc))
            return
        self._log_ai("Progetto salvato in <code>%s</code> (%d versioni)"
                     % (saved, len(self.session.history)))

    def on_open_project(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Apri progetto",
                                              str(SETTINGS.output_dir),
                                              "Progetto 3DGen (*.my3d)")
        if not path:
            return
        try:
            self.session.open_project(path)
        except Exception as exc:
            QMessageBox.warning(self, "Apertura fallita", str(exc))
            return
        self._log_ai("Progetto aperto: <b>%s</b> (%d versioni)"
                     % (Path(path).name, len(self.session.history)))
        self.refresh_all()

    def on_export(self) -> None:
        if self.session.scene is None:
            self.statusBar().showMessage("Genera prima un modello", 4000)
            return
        default = str(SETTINGS.output_dir / "modello.glb")
        path, _ = QFileDialog.getSaveFileName(
            self, "Esporta modello", default,
            "glTF binario (*.glb);;Wavefront (*.obj);;STL (*.stl);;PLY (*.ply)")
        if not path:
            return
        worker = ExportWorker(self.session, path)
        worker.finished.connect(
            lambda p: (self._log_ai("Esportato in <code>%s</code>" % p),
                       self.statusBar().showMessage("Esportato: %s" % p, 6000)))
        worker.failed.connect(lambda m: QMessageBox.warning(self, "Export fallito", m))
        run_in_thread(self, worker)

    # -------------------------------------------------------- refresh UI #
    def refresh_all(self) -> None:
        version = self.session.current
        scene = self.session.scene
        self.viewport.set_scene(scene)
        self._fill_tree(scene)
        self._fill_params()
        self._fill_checks()
        self._fill_animations()
        self._fill_history()
        self._sync_actions()
        if scene is not None:
            radice = version.plan.resolved_ref(version.plan.root_id) \
                if version.plan is not None else "-"
            self.status.setText("%s  |  %s  |  dettaglio %d  |  seme %d"
                                % (scene.summary(), radice,
                                   getattr(version.plan, "detail_level", 2),
                                   getattr(version.plan, "seed", 0)))
        self.btn_regenerate.setEnabled(scene is not None)
        self.btn_variant.setEnabled(scene is not None)
        self.btn_save_lib.setEnabled(scene is not None)
        self.btn_apply.setEnabled(scene is not None)

    def _fill_tree(self, scene) -> None:
        self.tree.clear()
        if scene is None:
            return
        groups: dict[str, list] = {}
        for node in scene.nodes:
            key = next((t for t in node.tags if t not in ("main",)), "altro")
            groups.setdefault(key, []).append(node)
        for key in sorted(groups):
            parent = QTreeWidgetItem([key, str(sum(n.triangles for n in groups[key]))])
            for node in groups[key]:
                child = QTreeWidgetItem([node.name, str(node.triangles)])
                r, g, b, _ = node.material.rgba()
                # schiarisci: i materiali scuri sarebbero illeggibili su fondo scuro
                r, g, b = (0.45 + 0.55 * v for v in (r, g, b))
                child.setForeground(0, QColor(int(r * 255), int(g * 255), int(b * 255)))
                parent.addChild(child)
            self.tree.addTopLevelItem(parent)
        self.tree.expandToDepth(0)

    def _fill_params(self) -> None:
        while self.params_form.count():
            item = self.params_form.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._param_widgets: dict[str, QWidget] = {}
        # I parametri sono quelli che il **componente radice** dichiara, letti
        # dal registry: non c'e' piu' un elenco di template da tenere allineato,
        # e un plugin installato ieri compare qui senza che nessuno lo sappia.
        plan = self.session.current_plan
        if plan is None or not plan.root_id:
            return
        componente = self.session.catalog().component(
            plan.resolved_ref(plan.root_id))
        if componente is None:
            return
        radice = plan.nodes[plan.root_id]
        for name, spec in sorted(componente.params.items()):
            if spec.is_derived:
                continue          # lo decide una formula: mostrarlo illuderebbe
            value = radice.overrides.get(name, spec.default)
            if isinstance(spec.default, bool):
                w = QComboBox()
                w.addItems(["true", "false"])
                w.setCurrentText("true" if value else "false")
            elif spec.choices:
                w = QComboBox()
                w.addItems([str(c) for c in spec.choices])
                w.setCurrentText(str(value))
            else:
                w = QDoubleSpinBox()
                w.setDecimals(0 if isinstance(spec.default, int) else 3)
                w.setRange(float(spec.min if spec.min is not None else -1e6),
                           float(spec.max if spec.max is not None else 1e6))
                w.setSingleStep(1.0 if isinstance(spec.default, int) else 0.05)
                w.setValue(float(value))
            w.setToolTip(spec.description or "")
            self._param_widgets[name] = w
            self.params_form.addRow(name, w)

    def _fill_checks(self) -> None:
        self.checks.clear()
        for c in self.session.checks():
            self.checks.addItem("%s %s  -  %s" % (c.icon(), c.label, c.detail))
        for warn in (self.session.scene.warnings if self.session.scene else []):
            self.checks.addItem("!! " + warn)

    def _fill_history(self) -> None:
        self.history_list.clear()
        for i, v in enumerate(self.session.history):
            self.history_list.addItem("%d. %s" % (i + 1, v.label))
        self.history_list.setCurrentRow(self.session.cursor)

    def _sync_actions(self) -> None:
        self.act_undo.setEnabled(self.session.can_undo())
        self.act_redo.setEnabled(self.session.can_redo())

    def _maybe_refresh_log(self, index: int) -> None:
        if self.tabs.tabText(index) == "Log":
            self.log_view.setPlainText("\n".join(tail(300)))
            self.log_view.verticalScrollBar().setValue(
                self.log_view.verticalScrollBar().maximum())

    def _refresh_provider_label(self) -> None:
        if not hasattr(self, "provider_box"):
            return
        provider = self.provider_box.currentData() or "offline"
        label = PROVIDERS[provider].label if provider in PROVIDERS else "Locale"
        fallback = [PROVIDERS[c].label for c in SETTINGS.available_chain()
                    if c != provider]
        suffix = " > ".join(fallback) if fallback else "regole locali"
        failover = "failover automatico" if self.failover_box.isChecked() else "failover disattivato"
        text = "AI primaria: %s  |  %s  |  dopo: %s" % (
            label, failover, suffix)
        self.provider_label.setText(text)

    def _populate_ai_controls(self) -> None:
        """Carica provider e stato senza fare discovery di modelli."""
        saved_provider = str(self._ai_settings.value("ai/provider", "") or "")
        chain = SETTINGS.available_chain()
        default_provider = saved_provider if saved_provider in PROVIDERS else (
            chain[0] if chain else "offline")

        self.provider_box.blockSignals(True)
        self.provider_box.clear()
        for key, spec in PROVIDERS.items():
            configured = SETTINGS.configured(key)
            label = spec.label if configured else "%s [non configurato]" % spec.label
            self.provider_box.addItem(label, key)
            index = self.provider_box.count() - 1
            item = self.provider_box.model().item(index)
            if item is not None:
                item.setEnabled(configured)
            missing = SETTINGS.missing_requirements(key)
            tooltip = spec.note or ""
            if missing:
                tooltip += ("; manca: " + ", ".join(missing))
            self.provider_box.setItemData(index, tooltip, Qt.ItemDataRole.ToolTipRole)
        self.provider_box.addItem("Locale (regole)", "offline")
        self.provider_box.setCurrentIndex(max(0, self.provider_box.findData(default_provider)))
        self.provider_box.blockSignals(False)

        self.failover_box.setChecked(bool(self._ai_settings.value("ai/failover", True, type=bool)))
        self._on_provider_changed(self.provider_box.currentIndex())

    def _on_provider_changed(self, index: int) -> None:
        del index
        self._persist_ai_selection()
        self._refresh_provider_label()

    def _persist_ai_selection(self, *_args) -> None:
        if not hasattr(self, "provider_box") or self.provider_box.currentData() is None:
            return
        key = str(self.provider_box.currentData())
        self._ai_settings.setValue("ai/provider", key)
        self._ai_settings.setValue("ai/failover", self.failover_box.isChecked())
        self._refresh_provider_label()

    def _apply_ai_selection(self) -> None:
        key = str(self.provider_box.currentData() or "offline")
        self.session.configure_ai(key, failover=self.failover_box.isChecked())

    def _set_busy(self, busy: bool, message: str = "") -> None:
        self.busy = busy
        self.progress.setRange(0, 0 if busy else 1)
        if not busy:
            self.progress.setValue(0)
        self.btn_generate.setEnabled(not busy)
        self.btn_image.setEnabled(not busy)
        self.btn_regenerate.setEnabled(not busy and self.session.scene is not None)
        self.btn_variant.setEnabled(not busy and self.session.scene is not None)
        self.btn_save_lib.setEnabled(not busy and self.session.scene is not None)
        if message:
            self.statusBar().showMessage(message)

    # ------------------------------------------------------------- chat #
    def _log_user(self, text: str) -> None:
        self.chat.append("<div style='margin-top:6px'><b style='color:#7fb2e5'>Tu:</b> %s</div>"
                         % text)

    def _log_ai(self, text: str) -> None:
        self.chat.append("<div style='margin-top:2px'><b style='color:#7fc9a0'>AI:</b> %s</div>"
                         % text)
        self.chat.verticalScrollBar().setValue(self.chat.verticalScrollBar().maximum())
