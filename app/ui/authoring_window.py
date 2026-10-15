"""La finestra di authoring: un cliente sottile di `AuthoringService`.

Nessuna logica di authoring vive qui. Ogni bottone chiama un metodo del
servizio e ridisegna cio' che il servizio dice: e' la stessa regola che tiene
`app/ui/main_window.py` sottile rispetto a `Session`, e serve alla stessa cosa
— un domani che costruisce un plugin senza interfaccia (Teach 3DGen) non deve
trovare qui comportamenti che altrove non esistono. Se un test di questa
finestra passasse e il test del servizio no, la finestra starebbe mentendo.

## Il flusso, e perche' e' una fila di schede

    IMPORT → COMPONENTS → HIERARCHY → SOCKETS → VARIABILITY → VALIDATE → SAVE

Le schede sono in quest'ordine perche' e' l'ordine in cui le cose diventano
possibili: non si crea un componente senza una selezione, non si fa una
gerarchia senza componenti, non si innesta senza sapere su che cosa. Non c'e'
un wizard che obbliga: le schede restano tutte raggiungibili, perche' tornare
indietro a sistemare un socket e' normale.

## La barra che non cambia mai

Sotto le schede c'e' sempre la stessa riga, e risponde alle quattro domande
del punto 24 della milestone: **quale** componente si sta modificando, **quale
geometria** gli appartiene, **dove** verra' salvato, **se e' valido**. Sono le
quattro cose che si perdono dopo dieci minuti di lavoro.

## Il gizmo

Il viewport disegna una `Scene`, quindi un gizmo e' geometria in piu' con il
tag `gizmo` (`app/authoring/gizmo.py`): disco, freccia, barretta. Si sposta e
si orienta con gli snap e con i campi numerici, non trascinandolo con il mouse
— il picking nel viewport non c'e' in V6, ed e' scritto fra i limiti invece di
essere simulato con un gizmo che non si puo' afferrare.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout,
    QGroupBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton,
    QSlider, QSpinBox, QSplitter, QStatusBar, QTabWidget, QTableWidget,
    QTableWidgetItem, QTextBrowser, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
    QWidget,
)

from app.authoring import AuthoringService, VariantRecipe
from app.authoring.errors import AuthoringError
from app.authoring.gizmo import AXES
from app.authoring.model import COVERAGE
from app.core.logging_setup import get
from app.core.session import Session
from app.ui.viewport import Viewport

log = get("ui.authoring")

SEVERITY_COLORS = {"error": "#ff6b6b", "warning": "#ffc357", "info": "#8e97a5"}


def _rows(table: QTableWidget, headers: list[str]) -> None:
    table.setColumnCount(len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setRowCount(0)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)


class AuthoringWindow(QMainWindow):
    """Import → componenti → gerarchia → innesti → variabilita' → salva."""

    def __init__(self, session: Session | None = None, parent=None) -> None:
        super().__init__(parent)
        self.service = AuthoringService(session=session or Session())
        self.service.create_authoring_project("my_plugin")
        self.setWindowTitle("3DGen - Component Authoring")
        self.resize(1480, 920)
        self._build_ui()
        self.refresh_all()

    # ------------------------------------------------------------------ UI #
    def _build_ui(self) -> None:
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._import_page(), "1. Import")
        self.tabs.addTab(self._components_page(), "2. Components")
        self.tabs.addTab(self._hierarchy_page(), "3. Hierarchy")
        self.tabs.addTab(self._sockets_page(), "4. Sockets")
        self.tabs.addTab(self._variability_page(), "5. Variability")
        self.tabs.addTab(self._validate_page(), "6. Validate")
        self.tabs.addTab(self._save_page(), "7. Save / Install")
        splitter.addWidget(self.tabs)

        right = QWidget()
        layout = QVBoxLayout(right)
        self.viewport = Viewport()
        layout.addWidget(self.viewport, 1)
        preview_bar = QHBoxLayout()
        self.chk_sockets = QCheckBox("Gizmo innesti")
        self.chk_sockets.setChecked(True)
        self.chk_frame = QCheckBox("Assi del frame")
        self.spin_detail = QSpinBox()
        self.spin_detail.setRange(1, 5)
        self.spin_detail.setValue(2)
        self.spin_detail.setPrefix("detail ")
        btn_preview = QPushButton("Aggiorna preview")
        btn_preview.clicked.connect(self.refresh_preview)
        for widget in (self.chk_sockets, self.chk_frame, self.spin_detail,
                       btn_preview):
            preview_bar.addWidget(widget)
        preview_bar.addStretch(1)
        layout.addLayout(preview_bar)
        splitter.addWidget(right)
        splitter.setSizes([740, 740])

        container = QWidget()
        outer = QVBoxLayout(container)
        outer.addWidget(splitter, 1)
        outer.addWidget(self._context_bar())
        self.setCentralWidget(container)
        self.setStatusBar(QStatusBar())
        self.status = QLabel("Progetto nuovo")
        self.statusBar().addWidget(self.status)

    def _context_bar(self) -> QWidget:
        """Le quattro domande del punto 24, sempre sotto gli occhi."""
        box = QGroupBox("Contesto")
        layout = QHBoxLayout(box)
        self.lbl_component = QLabel("componente: -")
        self.lbl_geometry = QLabel("geometria: -")
        self.lbl_destination = QLabel("destinazione: -")
        self.lbl_valid = QLabel("validita': da verificare")
        for label in (self.lbl_component, self.lbl_geometry,
                      self.lbl_destination, self.lbl_valid):
            layout.addWidget(label)
        layout.addStretch(1)
        return box

    # ------------------------------------------------------------- import #
    def _import_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        bar = QHBoxLayout()
        btn_import = QPushButton("Import Model")
        btn_import.setObjectName("primary")
        btn_import.clicked.connect(self.on_import)
        btn_all = QPushButton("Seleziona tutto")
        btn_all.clicked.connect(self.on_select_all)
        btn_none = QPushButton("Deseleziona")
        btn_none.clicked.connect(self.on_clear_selection)
        btn_isolate = QPushButton("Isola")
        btn_isolate.clicked.connect(self.on_isolate)
        btn_show = QPushButton("Mostra tutto")
        btn_show.clicked.connect(self.on_show_all)
        for widget in (btn_import, btn_all, btn_none, btn_isolate, btn_show):
            bar.addWidget(widget)
        bar.addStretch(1)
        layout.addLayout(bar)

        self.objects_table = QTableWidget()
        _rows(self.objects_table, ["Oggetto", "Triangoli", "Dimensioni",
                                   "Colore", "Visibile", "Componente"])
        self.objects_table.setSelectionMode(
            QTableWidget.SelectionMode.ExtendedSelection)
        self.objects_table.itemSelectionChanged.connect(self.on_objects_selected)
        layout.addWidget(self.objects_table, 1)
        return page

    def on_import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import Model", "",
                                              "Modelli (*.glb *.gltf)")
        if not path:
            return
        self._guard(lambda: self.service.import_model(path))
        self.refresh_all()

    def on_select_all(self) -> None:
        self._guard(self.service.select_all)
        self.refresh_objects()

    def on_clear_selection(self) -> None:
        self._guard(self.service.clear_selection)
        self.refresh_objects()

    def on_isolate(self) -> None:
        self._guard(self.service.isolate)
        self.refresh_objects()

    def on_show_all(self) -> None:
        self._guard(self.service.show_all)
        self.refresh_objects()

    def on_objects_selected(self) -> None:
        keys = [self.objects_table.item(index.row(), 0).data(Qt.ItemDataRole.UserRole)
                for index in self.objects_table.selectionModel().selectedRows()]
        if keys:
            self._guard(lambda: self.service.select(keys))
        self.refresh_context()

    # --------------------------------------------------------- componenti #
    def _components_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        form_host = QWidget()
        form = QFormLayout(form_host)
        self.in_name = QLineEdit("body")
        self.in_description = QLineEdit()
        self.in_role = QLineEdit()
        self.in_tags = QLineEdit()
        self.in_provides = QLineEdit()
        self.in_styles = QLineEdit()
        self.in_requires = QLineEdit()
        self.in_synonyms = QLineEdit()
        self.cmb_coverage = QComboBox()
        self.cmb_coverage.addItems(list(COVERAGE))
        form.addRow("id (plugin:nome)", self.in_name)
        form.addRow("descrizione", self.in_description)
        form.addRow("role", self.in_role)
        form.addRow("tags", self.in_tags)
        form.addRow("provides", self.in_provides)
        form.addRow("styles", self.in_styles)
        form.addRow("requires", self.in_requires)
        form.addRow("synonyms", self.in_synonyms)
        form.addRow("copertura", self.cmb_coverage)
        layout.addWidget(form_host)

        bar = QHBoxLayout()
        btn_create = QPushButton("Create Component")
        btn_create.setObjectName("primary")
        btn_create.clicked.connect(self.on_create_component)
        btn_composite = QPushButton("Create Composite (senza mesh)")
        btn_composite.clicked.connect(self.on_create_composite)
        btn_apply = QPushButton("Applica metadata")
        btn_apply.clicked.connect(self.on_apply_metadata)
        btn_remove = QPushButton("Rimuovi")
        btn_remove.clicked.connect(self.on_remove_component)
        for widget in (btn_create, btn_composite, btn_apply, btn_remove):
            bar.addWidget(widget)
        bar.addStretch(1)
        layout.addLayout(bar)

        self.components_list = QListWidget()
        self.components_list.currentItemChanged.connect(self.on_component_chosen)
        layout.addWidget(self.components_list, 1)

        mount_box = QGroupBox("Capabilities: provides e accepts")
        mount_layout = QVBoxLayout(mount_box)
        search = QHBoxLayout()
        self.in_capability_search = QLineEdit()
        self.in_capability_search.setPlaceholderText("cerca una capability...")
        self.in_capability_search.textChanged.connect(self.refresh_capabilities)
        btn_mount = QPushButton("Aggiungi innesto (socket + mount)")
        btn_mount.clicked.connect(self.on_add_mount)
        btn_provides = QPushButton("Aggiungi a provides")
        btn_provides.clicked.connect(self.on_add_provides)
        search.addWidget(self.in_capability_search, 1)
        search.addWidget(btn_mount)
        search.addWidget(btn_provides)
        mount_layout.addLayout(search)
        self.capabilities_table = QTableWidget()
        _rows(self.capabilities_table, ["Capability", "Provides", "Accepts",
                                        "Dichiarata"])
        mount_layout.addWidget(self.capabilities_table)
        layout.addWidget(mount_box, 1)

        planner_box = QGroupBox("What the planner will see")
        planner_layout = QVBoxLayout(planner_box)
        self.planner_view = QPlainTextEdit()
        self.planner_view.setReadOnly(True)
        self.planner_view.setMaximumHeight(110)
        planner_layout.addWidget(self.planner_view)
        search_bar = QHBoxLayout()
        self.in_test_search = QLineEdit()
        self.in_test_search.setPlaceholderText("Test Search: dragon eye")
        btn_search = QPushButton("Cerca")
        btn_search.clicked.connect(self.on_test_search)
        self.in_test_search.returnPressed.connect(self.on_test_search)
        search_bar.addWidget(self.in_test_search, 1)
        search_bar.addWidget(btn_search)
        planner_layout.addLayout(search_bar)
        self.search_results = QListWidget()
        self.search_results.setMaximumHeight(130)
        planner_layout.addWidget(self.search_results)
        layout.addWidget(planner_box, 1)
        return page

    def on_create_component(self) -> None:
        self._create_component(from_selection=True)

    def on_create_composite(self) -> None:
        self._create_component(from_selection=False)

    def _create_component(self, *, from_selection: bool) -> None:
        def run():
            return self.service.create_component(
                self.in_name.text().strip(),
                objects=None if from_selection else (),
                from_selection=from_selection,
                role=self.in_role.text().strip(),
                description=self.in_description.text().strip(),
                tags=_words(self.in_tags.text()),
                provides=_words(self.in_provides.text()),
                styles=_words(self.in_styles.text()),
                requires=_words(self.in_requires.text()),
                synonyms=_words(self.in_synonyms.text()),
                coverage=self.cmb_coverage.currentText())

        if self._guard(run) is not None:
            self.refresh_all()

    def on_apply_metadata(self) -> None:
        key = self.current_key()
        if not key:
            return
        self._guard(lambda: self.service.set_metadata(
            key, name=self.in_name.text().strip(),
            description=self.in_description.text().strip(),
            role=self.in_role.text().strip(),
            tags=_words(self.in_tags.text()),
            provides=_words(self.in_provides.text()),
            styles=_words(self.in_styles.text()),
            requires=_words(self.in_requires.text()),
            synonyms=_words(self.in_synonyms.text()),
            coverage=self.cmb_coverage.currentText()))
        self.refresh_all()

    def on_remove_component(self) -> None:
        key = self.current_key()
        if not key:
            return
        self._guard(lambda: self.service.remove_component(key))
        self.refresh_all()

    def on_component_chosen(self, current, _previous=None) -> None:
        if current is None:
            return
        key = current.data(Qt.ItemDataRole.UserRole)
        draft = self._guard(lambda: self.service.set_current(key))
        if draft is None:
            return
        self.in_name.setText(draft.name)
        self.in_description.setText(draft.description)
        self.in_role.setText(draft.role)
        self.in_tags.setText(" ".join(draft.tags))
        self.in_provides.setText(" ".join(draft.provides))
        self.in_styles.setText(" ".join(draft.styles))
        self.in_requires.setText(" ".join(draft.requires))
        self.in_synonyms.setText(" ".join(draft.synonyms))
        self.cmb_coverage.setCurrentText(draft.coverage)
        self.refresh_sockets()
        self.refresh_params()
        self.refresh_frame()
        self.refresh_context()
        self.refresh_planner()

    def on_add_mount(self) -> None:
        key = self.current_key()
        capability = self._chosen_capability()
        if not key or not capability:
            return
        self._guard(lambda: self.service.add_mount(key, capability))
        self.refresh_all()

    def on_add_provides(self) -> None:
        key = self.current_key()
        capability = self._chosen_capability()
        if not key or not capability:
            return
        draft = self.service._draft(key)
        self._guard(lambda: self.service.set_metadata(
            key, provides=tuple(dict.fromkeys([*draft.provides, capability]))))
        self.refresh_all()

    def _chosen_capability(self) -> str:
        row = self.capabilities_table.currentRow()
        if row < 0:
            return self.in_capability_search.text().strip()
        item = self.capabilities_table.item(row, 0)
        return item.text() if item else ""

    def on_test_search(self) -> None:
        query = self.in_test_search.text().strip()
        self.search_results.clear()
        if not query:
            return
        hits = self._guard(lambda: self.service.search_staged(query, 10)) or []
        for index, (component_id, score) in enumerate(hits, start=1):
            self.search_results.addItem("%d. %-34s %.2f" % (index, component_id, score))

    # ---------------------------------------------------------- gerarchia #
    def _hierarchy_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.hierarchy_tree = QTreeWidget()
        self.hierarchy_tree.setHeaderLabels(["Parte", "id", "level", "stato"])
        self.hierarchy_tree.setColumnWidth(0, 230)
        layout.addWidget(self.hierarchy_tree, 1)

        attach = QGroupBox("Aggancia")
        attach_layout = QFormLayout(attach)
        self.cmb_parent = QComboBox()
        self.cmb_child = QComboBox()
        self.cmb_child.setEditable(True)
        self.in_child_id = QLineEdit()
        self.spin_level = QSpinBox()
        self.spin_level.setRange(1, 5)
        self.spin_level.setValue(2)
        self.in_requirement = QLineEdit()
        self.in_requirement.setPlaceholderText("capability richiesta (opzionale)")
        self.chk_optional = QCheckBox("optional")
        self.chk_on_request = QCheckBox("on_request")
        self.chk_replaces_parent = QCheckBox("replaces_parent")
        self.in_replaces = QLineEdit()
        self.in_replaces.setPlaceholderText("id del fratello che sostituisce")
        attach_layout.addRow("padre", self.cmb_parent)
        attach_layout.addRow("figlio", self.cmb_child)
        attach_layout.addRow("id dell'arco", self.in_child_id)
        attach_layout.addRow("detail level", self.spin_level)
        attach_layout.addRow("requirement", self.in_requirement)
        attach_layout.addRow("replaces", self.in_replaces)
        flags = QHBoxLayout()
        for widget in (self.chk_optional, self.chk_on_request,
                       self.chk_replaces_parent):
            flags.addWidget(widget)
        host = QWidget()
        host.setLayout(flags)
        attach_layout.addRow("", host)
        layout.addWidget(attach)

        bar = QHBoxLayout()
        for text, slot in (("Set parent", self.on_set_parent),
                           ("Unparent", self.on_unparent),
                           ("Duplica riferimento", self.on_duplicate_reference),
                           ("Su", lambda: self.on_reorder(-1)),
                           ("Giu", lambda: self.on_reorder(1)),
                           ("Applica opzioni", self.on_child_options)):
            button = QPushButton(text)
            button.clicked.connect(slot)
            bar.addWidget(button)
        bar.addStretch(1)
        layout.addLayout(bar)

        detail = QGroupBox("Detail level preview")
        detail_layout = QVBoxLayout(detail)
        detail_bar = QHBoxLayout()
        for level in range(1, 6):
            button = QPushButton(str(level))
            button.clicked.connect(lambda _checked=False, value=level:
                                   self.on_detail_preview(value))
            detail_bar.addWidget(button)
        detail_bar.addStretch(1)
        detail_layout.addLayout(detail_bar)
        self.detail_list = QListWidget()
        detail_layout.addWidget(self.detail_list)
        layout.addWidget(detail, 1)
        return page

    def _child_options(self) -> dict:
        options: dict = {"level": self.spin_level.value(),
                         "optional": self.chk_optional.isChecked(),
                         "on_request": self.chk_on_request.isChecked(),
                         "replaces_parent": self.chk_replaces_parent.isChecked(),
                         "replaces": self.in_replaces.text().strip()}
        capability = self.in_requirement.text().strip()
        if capability:
            options["requirement"] = {"capability": capability}
        return options

    def on_set_parent(self) -> None:
        parent = self.cmb_parent.currentData() or self.cmb_parent.currentText()
        child = self.cmb_child.currentData() or self.cmb_child.currentText().strip()
        if not parent or not child:
            return
        self._guard(lambda: self.service.set_parent(
            child, parent, child_id=self.in_child_id.text().strip(),
            **self._child_options()))
        self.refresh_all()

    def on_unparent(self) -> None:
        row = self._selected_hierarchy_row()
        if row is None or not row.get("ref"):
            return
        parent = self._parent_of_row(row)
        if parent:
            self._guard(lambda: self.service.unparent(parent, row["id"]))
            self.refresh_all()

    def on_duplicate_reference(self) -> None:
        row = self._selected_hierarchy_row()
        if row is None or not row.get("ref"):
            return
        parent = self._parent_of_row(row)
        if parent:
            self._guard(lambda: self.service.duplicate_reference(parent, row["id"]))
            self.refresh_all()

    def on_reorder(self, delta: int) -> None:
        row = self._selected_hierarchy_row()
        if row is None or not row.get("ref"):
            return
        parent = self._parent_of_row(row)
        if not parent:
            return
        draft = self.service._draft(parent)
        current = [c.id for c in draft.children].index(row["id"])
        self._guard(lambda: self.service.reorder(parent, row["id"], current + delta))
        self.refresh_all()

    def on_child_options(self) -> None:
        row = self._selected_hierarchy_row()
        if row is None or not row.get("ref"):
            return
        parent = self._parent_of_row(row)
        if parent:
            self._guard(lambda: self.service.set_child_options(
                parent, row["id"], **self._child_options()))
            self.refresh_all()

    def on_detail_preview(self, level: int) -> None:
        key = self.current_key()
        self.detail_list.clear()
        if not key:
            return
        nodes = self._guard(lambda: self.service.detail_preview(key, level)) or []
        self.detail_list.addItem("detail %d: %d nodi" % (level, len(nodes)))
        for node in nodes:
            self.detail_list.addItem("  " + node)

    def _selected_hierarchy_row(self) -> dict | None:
        item = self.hierarchy_tree.currentItem()
        return None if item is None else item.data(0, Qt.ItemDataRole.UserRole)

    def _parent_of_row(self, row: dict) -> str:
        item = self.hierarchy_tree.currentItem()
        parent_item = None if item is None else item.parent()
        if parent_item is None:
            return ""
        data = parent_item.data(0, Qt.ItemDataRole.UserRole) or {}
        return data.get("key", "")

    # ------------------------------------------------------------- socket #
    def _sockets_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.sockets_table = QTableWidget()
        _rows(self.sockets_table, ["Nome", "Posizione", "Direction", "Up",
                                   "Raggio", "Capabilities", "Lato"])
        self.sockets_table.itemSelectionChanged.connect(self.on_socket_chosen)
        layout.addWidget(self.sockets_table, 1)

        form_host = QWidget()
        form = QFormLayout(form_host)
        self.in_socket_name = QLineEdit("base")
        self.spin_pos = [self._spin(-100.0, 100.0) for _ in range(3)]
        self.spin_dir = [self._spin(-1.0, 1.0) for _ in range(3)]
        self.spin_up = [self._spin(-1.0, 1.0) for _ in range(3)]
        self.spin_radius = self._spin(0.001, 100.0, value=0.1)
        self.in_socket_caps = QLineEdit()
        self.cmb_side = QComboBox()
        self.cmb_side.addItems(["", "l", "r", "center", "top", "bottom",
                                "front", "back"])
        self.in_socket_tags = QLineEdit()
        form.addRow("name", self.in_socket_name)
        form.addRow("position", _triple(self.spin_pos))
        form.addRow("direction", _triple(self.spin_dir))
        form.addRow("up", _triple(self.spin_up))
        form.addRow("radius", self.spin_radius)
        form.addRow("capabilities", self.in_socket_caps)
        form.addRow("side", self.cmb_side)
        form.addRow("tags", self.in_socket_tags)
        layout.addWidget(form_host)

        bar = QHBoxLayout()
        for text, slot in (("+ Add", self.on_add_socket),
                           ("Applica", self.on_update_socket),
                           ("Rimuovi", self.on_remove_socket),
                           ("Mirror L<->R", self.on_mirror_socket)):
            button = QPushButton(text)
            button.clicked.connect(slot)
            bar.addWidget(button)
        bar.addStretch(1)
        layout.addLayout(bar)

        snap = QGroupBox("Snap helpers (deterministici)")
        snap_layout = QVBoxLayout(snap)
        center = QPushButton("Centro dell'oggetto")
        center.clicked.connect(self.on_snap_center)
        snap_layout.addWidget(center)
        faces = QHBoxLayout()
        faces.addWidget(QLabel("faccia del bounding box:"))
        for axis in AXES:
            button = QPushButton(axis)
            button.clicked.connect(lambda _checked=False, value=axis:
                                   self.on_snap_face(value))
            faces.addWidget(button)
        snap_layout.addLayout(faces)
        aligns = QHBoxLayout()
        aligns.addWidget(QLabel("allinea direction:"))
        for axis in AXES:
            button = QPushButton(axis)
            button.clicked.connect(lambda _checked=False, value=axis:
                                   self.on_align_direction(value))
            aligns.addWidget(button)
        snap_layout.addLayout(aligns)
        ups = QHBoxLayout()
        ups.addWidget(QLabel("allinea up:"))
        for axis in AXES:
            button = QPushButton(axis)
            button.clicked.connect(lambda _checked=False, value=axis:
                                   self.on_align_up(value))
            ups.addWidget(button)
        snap_layout.addLayout(ups)
        layout.addWidget(snap)

        frame_box = QGroupBox("Frame: up, front, growth axis")
        frame_layout = QFormLayout(frame_box)
        self.cmb_growth = QComboBox()
        self.cmb_front = QComboBox()
        self.cmb_up = QComboBox()
        for combo in (self.cmb_growth, self.cmb_front, self.cmb_up):
            combo.addItem("")
            combo.addItems(AXES)
        frame_layout.addRow("growth_axis", self.cmb_growth)
        frame_layout.addRow("front", self.cmb_front)
        frame_layout.addRow("up", self.cmb_up)
        frame_bar = QHBoxLayout()
        btn_frame_component = QPushButton("Applica al componente")
        btn_frame_component.clicked.connect(lambda: self.on_set_frame(False))
        btn_frame_plugin = QPushButton("Applica al plugin")
        btn_frame_plugin.clicked.connect(lambda: self.on_set_frame(True))
        btn_verify = QPushButton("verify_frame")
        btn_verify.clicked.connect(self.on_verify_frame)
        for widget in (btn_frame_component, btn_frame_plugin, btn_verify):
            frame_bar.addWidget(widget)
        host = QWidget()
        host.setLayout(frame_bar)
        frame_layout.addRow("", host)
        self.frame_table = QTableWidget()
        _rows(self.frame_table, ["Arco", "Figlio", "Esito", "Mossa"])
        frame_layout.addRow(self.frame_table)
        layout.addWidget(frame_box, 1)

        material_box = QGroupBox("Materiale")
        material_layout = QHBoxLayout(material_box)
        self.cmb_material = QComboBox()
        self.cmb_material.setEditable(True)
        btn_assign = QPushButton("Assegna")
        btn_assign.clicked.connect(self.on_assign_material)
        btn_new_material = QPushButton("Nuovo MaterialSpec")
        btn_new_material.clicked.connect(self.on_new_material)
        self.lbl_material = QLabel("-")
        for widget in (self.cmb_material, btn_assign, btn_new_material,
                       self.lbl_material):
            material_layout.addWidget(widget)
        layout.addWidget(material_box)
        return page

    @staticmethod
    def _spin(low: float, high: float, *, value: float = 0.0) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(low, high)
        spin.setDecimals(4)
        spin.setSingleStep(0.01)
        spin.setValue(value)
        return spin

    def _socket_fields(self) -> dict:
        return {"position": tuple(s.value() for s in self.spin_pos),
                "direction": tuple(s.value() for s in self.spin_dir),
                "up": tuple(s.value() for s in self.spin_up),
                "radius": self.spin_radius.value(),
                "capabilities": _words(self.in_socket_caps.text()),
                "side": self.cmb_side.currentText(),
                "tags": _words(self.in_socket_tags.text())}

    def on_add_socket(self) -> None:
        key = self.current_key()
        if not key:
            return
        fields = self._socket_fields()
        if tuple(fields["direction"]) == (0.0, 0.0, 0.0):
            fields["direction"] = (0.0, 1.0, 0.0)
        if tuple(fields["up"]) == (0.0, 0.0, 0.0):
            fields["up"] = (0.0, 0.0, 1.0)
        self._guard(lambda: self.service.add_socket(
            key, self.in_socket_name.text().strip(), **fields))
        self.refresh_all()

    def on_update_socket(self) -> None:
        key, name = self.current_key(), self._selected_socket()
        if not key or not name:
            return
        fields = dict(self._socket_fields(),
                      name=self.in_socket_name.text().strip())
        self._guard(lambda: self.service.update_socket(key, name, **fields))
        self.refresh_all()

    def on_remove_socket(self) -> None:
        key, name = self.current_key(), self._selected_socket()
        if key and name:
            self._guard(lambda: self.service.remove_socket(key, name))
            self.refresh_all()

    def on_mirror_socket(self) -> None:
        key, name = self.current_key(), self._selected_socket()
        if key and name:
            self._guard(lambda: self.service.mirror_socket(key, name))
            self.refresh_all()

    def on_snap_center(self) -> None:
        key, name = self.current_key(), self._selected_socket()
        if key and name:
            self._guard(lambda: self.service.snap_socket_to_center(key, name))
            self.refresh_all()

    def on_snap_face(self, axis: str) -> None:
        key, name = self.current_key(), self._selected_socket()
        if key and name:
            self._guard(lambda: self.service.snap_socket_to_face(key, name, axis))
            self.refresh_all()

    def on_align_direction(self, axis: str) -> None:
        key, name = self.current_key(), self._selected_socket()
        if key and name:
            self._guard(lambda: self.service.align_socket_direction(key, name, axis))
            self.refresh_all()

    def on_align_up(self, axis: str) -> None:
        key, name = self.current_key(), self._selected_socket()
        if key and name:
            self._guard(lambda: self.service.align_socket_up(key, name, axis))
            self.refresh_all()

    def on_socket_chosen(self) -> None:
        name = self._selected_socket()
        key = self.current_key()
        if not name or not key:
            return
        socket = self.service._draft(key).socket(name)
        if socket is None:
            return
        self.in_socket_name.setText(socket.name)
        for spin, value in zip(self.spin_pos, socket.position):
            spin.setValue(float(value))
        for spin, value in zip(self.spin_dir, socket.direction):
            spin.setValue(float(value))
        for spin, value in zip(self.spin_up, socket.up):
            spin.setValue(float(value))
        self.spin_radius.setValue(float(socket.radius))
        self.in_socket_caps.setText(" ".join(socket.capabilities))
        self.cmb_side.setCurrentText(socket.side)
        self.in_socket_tags.setText(" ".join(socket.tags))

    def _selected_socket(self) -> str:
        row = self.sockets_table.currentRow()
        if row < 0:
            return ""
        item = self.sockets_table.item(row, 0)
        return item.text() if item else ""

    def on_set_frame(self, plugin_level: bool) -> None:
        key = "" if plugin_level else self.current_key()
        if not plugin_level and not key:
            return
        self._guard(lambda: self.service.set_frame(
            key, growth_axis=self.cmb_growth.currentText(),
            front=self.cmb_front.currentText(), up=self.cmb_up.currentText()))
        self.refresh_all()

    def on_verify_frame(self) -> None:
        key = self.current_key()
        if not key:
            return
        report = self._guard(lambda: self.service.verify_frame(key))
        if report is None:
            return
        text = report.describe() or "nessuna diagnostica: la geometria rispetta "\
                                    "la convenzione dichiarata"
        QMessageBox.information(self, "verify_frame", text)

    def on_assign_material(self) -> None:
        key = self.current_key()
        if not key:
            return
        self._guard(lambda: self.service.assign_material(
            key, self.cmb_material.currentText().strip()))
        self.refresh_all()

    def on_new_material(self) -> None:
        name, ok = QInputDialog.getText(self, "Nuovo materiale", "nome")
        if not ok or not name.strip():
            return
        color, ok = QInputDialog.getText(self, "Nuovo materiale",
                                         "base_color", text="#9aa0a6")
        if not ok:
            return
        self._guard(lambda: self.service.add_material(name.strip(),
                                                       base_color=color.strip()))
        self.refresh_all()

    # -------------------------------------------------------- variabilita' #
    def _variability_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.params_table = QTableWidget()
        _rows(self.params_table, ["Parametro", "tipo", "default", "min", "max",
                                  "semantic role", "implementazione"])
        self.params_table.itemSelectionChanged.connect(self.on_param_chosen)
        layout.addWidget(self.params_table, 1)

        form_host = QWidget()
        form = QFormLayout(form_host)
        self.in_param_name = QLineEdit("width")
        self.cmb_param_type = QComboBox()
        self.cmb_param_type.addItems(["float", "ratio", "int"])
        self.spin_param_default = self._spin(-1000.0, 1000.0, value=1.0)
        self.spin_param_min = self._spin(-1000.0, 1000.0, value=0.5)
        self.spin_param_max = self._spin(-1000.0, 1000.0, value=2.0)
        self.cmb_param_role = QComboBox()
        self.cmb_param_role.setEditable(True)
        self.cmb_strategy = QComboBox()
        self.cmb_strategy.addItems(["transform", "effect"])
        self.cmb_strategy.currentTextChanged.connect(self.refresh_strategy)
        self.cmb_transform = QComboBox()
        self.cmb_effect = QComboBox()
        self.cmb_effect.currentTextChanged.connect(self.refresh_effect_knobs)
        self.cmb_effect_knob = QComboBox()
        self.cmb_effect_scope = QComboBox()
        self.spin_neutral = self._spin(-1000.0, 1000.0, value=0.0)
        form.addRow("name", self.in_param_name)
        form.addRow("type", self.cmb_param_type)
        form.addRow("default", self.spin_param_default)
        form.addRow("min", self.spin_param_min)
        form.addRow("max", self.spin_param_max)
        form.addRow("semantic role", self.cmb_param_role)
        form.addRow("implementazione", self.cmb_strategy)
        form.addRow("transform", self.cmb_transform)
        form.addRow("effect", self.cmb_effect)
        form.addRow("knob", self.cmb_effect_knob)
        form.addRow("scope", self.cmb_effect_scope)
        form.addRow("neutral", self.spin_neutral)
        layout.addWidget(form_host)

        bar = QHBoxLayout()
        for text, slot in (("+ Add param", self.on_add_param),
                           ("Applica", self.on_update_param),
                           ("Rimuovi", self.on_remove_param),
                           ("Component Lab", self.on_open_lab)):
            button = QPushButton(text)
            button.clicked.connect(slot)
            bar.addWidget(button)
        bar.addStretch(1)
        layout.addLayout(bar)

        variants = QGroupBox("Variant recipes del progetto")
        variants_layout = QVBoxLayout(variants)
        self.variants_list = QListWidget()
        variants_layout.addWidget(self.variants_list)
        layout.addWidget(variants, 1)
        return page

    def refresh_strategy(self, *_args) -> None:
        effect = self.cmb_strategy.currentText() == "effect"
        self.cmb_transform.setEnabled(not effect)
        for widget in (self.cmb_effect, self.cmb_effect_knob,
                       self.cmb_effect_scope, self.spin_neutral):
            widget.setEnabled(effect)

    def refresh_effect_knobs(self, *_args) -> None:
        strategies = self.service.param_strategies()
        chosen = self.cmb_effect.currentText()
        entry = next((e for e in strategies["effects"] if e["type"] == chosen), None)
        self.cmb_effect_knob.clear()
        self.cmb_effect_scope.clear()
        if entry is None:
            return
        self.cmb_effect_knob.addItems(entry["knobs"])
        self.cmb_effect_scope.addItems(entry["scopes"])

    def _param_fields(self) -> dict:
        fields: dict = {"type": self.cmb_param_type.currentText(),
                        "default": self.spin_param_default.value(),
                        "min": self.spin_param_min.value(),
                        "max": self.spin_param_max.value(),
                        "semantic_role": self.cmb_param_role.currentText().strip()}
        if self.cmb_strategy.currentText() == "transform":
            fields["transform"] = self.cmb_transform.currentText()
            fields["effect"] = None
        else:
            fields["transform"] = ""
            fields["effect"] = {"type": self.cmb_effect.currentText(),
                                "parameter": self.cmb_effect_knob.currentText(),
                                "scope": self.cmb_effect_scope.currentText(),
                                "neutral": self.spin_neutral.value()}
        return fields

    def on_add_param(self) -> None:
        key = self.current_key()
        if not key:
            return
        fields = self._param_fields()
        fields.pop("effect") if fields.get("effect") is None else None
        self._guard(lambda: self.service.add_param(
            key, self.in_param_name.text().strip(), **fields))
        self.refresh_all()

    def on_update_param(self) -> None:
        key, name = self.current_key(), self._selected_param()
        if not key or not name:
            return
        fields = dict(self._param_fields(),
                      name=self.in_param_name.text().strip())
        self._guard(lambda: self.service.update_param(key, name, **fields))
        self.refresh_all()

    def on_remove_param(self) -> None:
        key, name = self.current_key(), self._selected_param()
        if key and name:
            self._guard(lambda: self.service.remove_param(key, name))
            self.refresh_all()

    def on_param_chosen(self) -> None:
        key, name = self.current_key(), self._selected_param()
        if not key or not name:
            return
        param = self.service._draft(key).param(name)
        if param is None:
            return
        self.in_param_name.setText(param.name)
        self.cmb_param_type.setCurrentText(param.type)
        self.spin_param_default.setValue(float(param.default))
        if param.min is not None:
            self.spin_param_min.setValue(float(param.min))
        if param.max is not None:
            self.spin_param_max.setValue(float(param.max))
        self.cmb_param_role.setCurrentText(param.semantic_role)
        if param.effect:
            self.cmb_strategy.setCurrentText("effect")
            self.cmb_effect.setCurrentText(str(param.effect.get("type", "")))
            self.refresh_effect_knobs()
            self.cmb_effect_knob.setCurrentText(str(param.effect.get("parameter", "")))
            self.cmb_effect_scope.setCurrentText(str(param.effect.get("scope", "")))
            self.spin_neutral.setValue(float(param.effect.get("neutral", 0.0)))
        else:
            self.cmb_strategy.setCurrentText("transform")
            self.cmb_transform.setCurrentText(param.transform)

    def _selected_param(self) -> str:
        row = self.params_table.currentRow()
        if row < 0:
            return ""
        item = self.params_table.item(row, 0)
        return item.text() if item else ""

    def on_open_lab(self) -> None:
        key = self.current_key()
        if not key:
            return
        lab = self._guard(lambda: self.service.draft_lab(key))
        if lab is None:
            return
        dialog = ComponentLabDialog(lab, service=self.service, parent=self)
        dialog.exec()
        self.refresh_variants()

    # --------------------------------------------------------- validazione #
    def _validate_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        bar = QHBoxLayout()
        btn_validate = QPushButton("Validate")
        btn_validate.setObjectName("primary")
        btn_validate.clicked.connect(self.on_validate)
        btn_build = QPushButton("Build Component")
        btn_build.clicked.connect(self.on_build)
        for widget in (btn_validate, btn_build):
            bar.addWidget(widget)
        bar.addStretch(1)
        layout.addLayout(bar)
        self.validation_table = QTableWidget()
        _rows(self.validation_table, ["Gravita'", "Codice", "Dove", "Messaggio",
                                      "Perche'"])
        layout.addWidget(self.validation_table, 1)
        self.build_view = QTextBrowser()
        layout.addWidget(self.build_view, 1)
        return page

    def on_validate(self) -> None:
        report = self._guard(self.service.validate)
        if report is None:
            return
        rows = report.rows()
        self.validation_table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            for column, value in enumerate((row["severity"], row["code"],
                                            row["where"], row["message"],
                                            row["why"])):
                item = QTableWidgetItem(str(value))
                item.setForeground(Qt.GlobalColor.white if column else
                                   Qt.GlobalColor.white)
                self.validation_table.setItem(index, column, item)
        self.lbl_valid.setText("validita': %s (%s)"
                               % ("ok" if report.ok else "NON valido",
                                  report.describe()))

    def on_build(self) -> None:
        key = self.current_key()
        if not key:
            return
        result = self._guard(lambda: self.service.build_component(
            key, detail_level=self.spin_detail.value()))
        if result is None:
            return
        lines = ["<b>%s</b>: %d triangoli, ok=%s"
                 % (key, result.triangles, result.ok)]
        if result.resolved is not None:
            lines.append("nodi: " + ", ".join(n.path for n in result.resolved.walk()))
        if result.report is not None:
            for entry in result.report.sorted():
                lines.append('<span style="color:%s">%s %s</span> %s'
                             % (SEVERITY_COLORS.get(entry.severity, "#d6dae0"),
                                entry.severity, entry.code, entry.message))
        self.build_view.setHtml("<br>".join(lines))
        self.refresh_preview()

    # ------------------------------------------------------- salva/installa #
    def _save_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        form_host = QWidget()
        form = QFormLayout(form_host)
        self.in_plugin_id = QLineEdit("my_plugin")
        self.in_plugin_version = QLineEdit("1.0.0")
        self.in_plugin_name = QLineEdit()
        self.in_plugin_description = QLineEdit()
        self.in_destination = QLineEdit()
        form.addRow("plugin id", self.in_plugin_id)
        form.addRow("version", self.in_plugin_version)
        form.addRow("name", self.in_plugin_name)
        form.addRow("description", self.in_plugin_description)
        form.addRow("destinazione", self.in_destination)
        layout.addWidget(form_host)

        bar = QHBoxLayout()
        for text, slot in (("Scegli cartella...", self.on_choose_destination),
                           ("Applica", self.on_apply_plugin_meta),
                           ("Save Plugin", self.on_save_plugin),
                           ("Install and test", self.on_install_plugin)):
            button = QPushButton(text)
            button.clicked.connect(slot)
            bar.addWidget(button)
        bar.addStretch(1)
        layout.addLayout(bar)

        project_bar = QHBoxLayout()
        for text, slot in (("Salva progetto authoring", self.on_save_project),
                           ("Apri progetto authoring", self.on_load_project),
                           ("Open Existing Data Plugin", self.on_open_plugin)):
            button = QPushButton(text)
            button.clicked.connect(slot)
            project_bar.addWidget(button)
        project_bar.addStretch(1)
        layout.addLayout(project_bar)

        self.install_view = QTextBrowser()
        layout.addWidget(self.install_view, 1)
        return page

    def on_choose_destination(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Dove salvare il plugin")
        if folder:
            self.in_destination.setText(folder)

    def on_apply_plugin_meta(self) -> None:
        project = self.service.project
        if project is None:
            return

        def run():
            from app.authoring.model import check_name

            project.plugin_id = check_name(self.in_plugin_id.text().strip(),
                                           "plugin_id")
            project.version = self.in_plugin_version.text().strip() or "1.0.0"
            project.name = self.in_plugin_name.text().strip()
            project.description = self.in_plugin_description.text().strip()
            project.destination = self.in_destination.text().strip()
            return project

        self._guard(run)
        self.refresh_context()

    def on_save_plugin(self) -> None:
        destination = self.in_destination.text().strip() or None
        path = self._guard(lambda: self.service.save_plugin(destination))
        if path is None:
            return
        self.install_view.setHtml("Plugin scritto in <b>%s</b>" % path)
        self.refresh_context()

    def on_install_plugin(self) -> None:
        destination = self.in_destination.text().strip() or None
        result = self._guard(lambda: self.service.install_plugin(destination))
        if result is None:
            return
        lines = [result.describe()]
        for component_id, found in sorted(result.found.items()):
            lines.append("%s: %s" % (component_id,
                                     "trovabile" if found else "NON trovabile"))
        for key, built in sorted(result.built.items()):
            lines.append("build %s: ok=%s, %d triangoli"
                         % (key, built["ok"], built["triangles"]))
        for entry in result.report.sorted():
            lines.append('<span style="color:%s">%s %s</span> %s'
                         % (SEVERITY_COLORS.get(entry.severity, "#d6dae0"),
                            entry.severity, entry.code, entry.message))
        self.install_view.setHtml("<br>".join(lines))
        self.refresh_all()

    def on_save_project(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Salva il progetto", "",
                                              "Progetti di authoring (*.3dgenproj)")
        if path:
            self._guard(lambda: self.service.save_project(path))

    def on_load_project(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Apri un progetto", "",
                                              "Progetti di authoring (*.3dgenproj)")
        if path:
            self._guard(lambda: self.service.load_project(path))
            self.refresh_all()

    def on_open_plugin(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Apri un plugin dati")
        if folder:
            self._guard(lambda: self.service.open_data_plugin(folder))
            self.refresh_all()

    # ------------------------------------------------------------ refresh #
    def refresh_all(self) -> None:
        self.refresh_objects()
        self.refresh_components()
        self.refresh_capabilities()
        self.refresh_hierarchy()
        self.refresh_sockets()
        self.refresh_params()
        self.refresh_frame()
        self.refresh_variants()
        self.refresh_strategies()
        self.refresh_context()

    def refresh_objects(self) -> None:
        project = self.service.project
        objects = project.objects() if project else []
        table = self.objects_table
        table.setRowCount(len(objects))
        for index, obj in enumerate(objects):
            owner = project.owner_of(obj.key) if project else None
            values = [obj.name, str(obj.triangles),
                      "%.3f x %.3f x %.3f" % obj.extents, obj.color,
                      "no" if obj.key in (project.hidden if project else ()) else "si",
                      owner.name if owner else ""]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, obj.key)
                table.setItem(index, column, item)

    def refresh_components(self) -> None:
        project = self.service.project
        self.components_list.blockSignals(True)
        self.components_list.clear()
        for draft in (project.components if project else []):
            label = "%s%s  [%s]" % (draft.name,
                                    "  (composite)" if draft.composite else "",
                                    draft.coverage)
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, draft.key)
            self.components_list.addItem(item)
            if project and draft.key == project.current:
                self.components_list.setCurrentItem(item)
        self.components_list.blockSignals(False)
        self.cmb_parent.clear()
        self.cmb_child.clear()
        for draft in (project.components if project else []):
            self.cmb_parent.addItem(draft.name, draft.key)
            self.cmb_child.addItem(draft.name, draft.key)
        for recipe in (project.variants if project else []):
            self.cmb_child.addItem("variant: " + recipe.name, "variant:" + recipe.name)

    def refresh_capabilities(self) -> None:
        views = self.service.search_capabilities(
            self.in_capability_search.text().strip())
        table = self.capabilities_table
        table.setRowCount(len(views))
        for index, view in enumerate(views):
            values = [view.name, str(len(view.providers)), str(len(view.mounts)),
                      "si" if view.declared else "no"]
            for column, value in enumerate(values):
                table.setItem(index, column, QTableWidgetItem(str(value)))

    def refresh_hierarchy(self) -> None:
        self.hierarchy_tree.clear()
        rows = self.service.hierarchy() if self.service.project else []
        stack: list[tuple[int, QTreeWidgetItem]] = []
        for row in rows:
            flags = []
            if row["optional"]:
                flags.append("optional")
            if row["on_request"]:
                flags.append("on_request")
            if row["composite"]:
                flags.append("composite")
            if row["installed"]:
                flags.append("installato")
            if row["coverage"]:
                flags.append(row["coverage"])
            item = QTreeWidgetItem([row["name"], row["id"], str(row["level"]),
                                    ", ".join(flags)])
            item.setData(0, Qt.ItemDataRole.UserRole, row)
            while stack and stack[-1][0] >= row["depth"]:
                stack.pop()
            if stack:
                stack[-1][1].addChild(item)
            else:
                self.hierarchy_tree.addTopLevelItem(item)
            stack.append((row["depth"], item))
        self.hierarchy_tree.expandAll()

    def refresh_sockets(self) -> None:
        key = self.current_key()
        draft = self.service.project.component(key) if key else None
        sockets = draft.sockets if draft else []
        table = self.sockets_table
        table.setRowCount(len(sockets))
        for index, socket in enumerate(sockets):
            values = [socket.name,
                      "%.3f %.3f %.3f" % socket.position,
                      "%.2f %.2f %.2f" % socket.direction,
                      "%.2f %.2f %.2f" % socket.up,
                      "%.3f" % socket.radius,
                      " ".join(socket.capabilities), socket.side]
            for column, value in enumerate(values):
                table.setItem(index, column, QTableWidgetItem(str(value)))

    def refresh_params(self) -> None:
        key = self.current_key()
        draft = self.service.project.component(key) if key else None
        params = draft.params if draft else []
        table = self.params_table
        table.setRowCount(len(params))
        for index, param in enumerate(params):
            implementation = param.transform or (
                "%s.%s (%s)" % (param.effect.get("type"),
                                param.effect.get("parameter"),
                                param.effect.get("scope"))
                if param.effect else "— da dichiarare")
            values = [param.name, param.type, str(param.default),
                      "" if param.min is None else str(param.min),
                      "" if param.max is None else str(param.max),
                      param.semantic_role, implementation]
            for column, value in enumerate(values):
                table.setItem(index, column, QTableWidgetItem(str(value)))

    def refresh_strategies(self) -> None:
        strategies = self.service.param_strategies()
        self.cmb_transform.clear()
        self.cmb_transform.addItems(strategies["transforms"])
        self.cmb_effect.clear()
        self.cmb_effect.addItems([e["type"] for e in strategies["effects"]])
        self.refresh_effect_knobs()
        self.refresh_strategy()
        self.cmb_param_role.clear()
        self.cmb_param_role.addItem("")
        self.cmb_param_role.addItems(self.service.semantic_roles())
        self.cmb_material.clear()
        key = self.current_key()
        if key:
            preview = self.service.material_preview(key)
            self.cmb_material.addItems(preview["available"])
            self.lbl_material.setText("%s (%s)" % (preview["effective"]["base_color"],
                                                   preview["effective"]["source"]))

    def refresh_frame(self) -> None:
        key = self.current_key()
        if key:
            frame = self.service.frame_of(key)
            self.cmb_growth.setCurrentText(frame.growth_axis)
            self.cmb_front.setCurrentText(frame.front)
            self.cmb_up.setCurrentText(frame.up)
        rows = self.service.frame_report() if self.service.project else []
        table = self.frame_table
        table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            move = row.get("move") or {}
            params = move.get("params", {})
            values = ["%s/%s" % (row["parent"], row["edge"]), row["child"],
                      row["result"],
                      "" if not params else "fx:rotate %s %s" % (params.get("axis"),
                                                                 params.get("angle"))]
            for column, value in enumerate(values):
                table.setItem(index, column, QTableWidgetItem(str(value)))

    def refresh_variants(self) -> None:
        self.variants_list.clear()
        for recipe in (self.service.project.variants if self.service.project else []):
            self.variants_list.addItem("%s  [%s]%s" % (
                recipe.describe(), recipe.coverage,
                "" if recipe.embeddable else "  (non incorporabile)"))

    def refresh_context(self) -> None:
        project = self.service.project
        draft = self.service.current()
        self.lbl_component.setText("componente: %s" % (draft.name if draft else "-"))
        if draft is None:
            geometry = "-"
        elif draft.composite:
            geometry = "nessuna (composite)"
        elif draft.mesh_source:
            geometry = "GLB: " + Path(draft.mesh_source).name
        else:
            geometry = "%d oggetti: %s" % (len(draft.objects),
                                           ", ".join(draft.objects))
        self.lbl_geometry.setText("geometria: " + geometry)
        destination = (project.destination if project else "") or "non scelta"
        plugin = project.plugin_id if project else "-"
        self.lbl_destination.setText("destinazione: %s/%s" % (destination, plugin))
        if project:
            self.in_plugin_id.setText(project.plugin_id)
            self.in_plugin_version.setText(project.version)
            self.in_plugin_name.setText(project.name)
            self.in_plugin_description.setText(project.description)
            self.in_destination.setText(project.destination)
        self.status.setText("%d sorgenti | %d componenti | %d variant"
                            % (len(project.sources) if project else 0,
                               len(project.components) if project else 0,
                               len(project.variants) if project else 0))

    def refresh_planner(self) -> None:
        key = self.current_key()
        if not key:
            self.planner_view.setPlainText("")
            return
        text = self._guard(lambda: self.service.planner_preview(key))
        self.planner_view.setPlainText(text or "")

    def refresh_preview(self) -> None:
        key = self.current_key()
        if not key:
            return
        scene = self._guard(lambda: self.service.preview_scene(
            key, detail_level=self.spin_detail.value(),
            sockets=self.chk_sockets.isChecked(),
            frame=self.chk_frame.isChecked()))
        if scene is not None:
            self.viewport.set_scene(scene)

    # ------------------------------------------------------------- utilita' #
    def current_key(self) -> str:
        project = self.service.project
        return project.current if project else ""

    def _guard(self, run):
        """Un errore di authoring e' un messaggio, non un traceback."""
        try:
            return run()
        except AuthoringError as exc:
            self.status.setText("%s: %s" % (exc.code, exc.message))
            log.info("authoring: %s %s", exc.code, exc.message)
            return None
        except (ValueError, OSError) as exc:
            self.status.setText(str(exc))
            log.warning("authoring: %s", exc)
            return None

    def closeEvent(self, event) -> None:
        self.service.close()
        super().closeEvent(event)


class ComponentLabDialog(QDialog):
    """Component Lab: slider, trait, effetti, livelli, referto, variant.

    Funziona identico su un componente procedurale e su uno mesh-backed, e non
    tocca l'originale: costruisce piani. Finche' non si premi «Save Variant»
    non resta niente.
    """

    def __init__(self, lab, *, service: AuthoringService | None = None,
                 parent=None) -> None:
        super().__init__(parent)
        self.lab = lab
        self.service = service
        self.setWindowTitle("Component Lab - %s" % lab.component_id)
        self.resize(1180, 760)
        self.sliders: dict[str, QSlider] = {}
        self.labels: dict[str, QLabel] = {}
        self._build_ui()
        self.rebuild()

    def _build_ui(self) -> None:
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.viewport = Viewport()
        splitter.addWidget(self.viewport)

        right = QWidget()
        layout = QVBoxLayout(right)
        params_box = QGroupBox("Parametri")
        form = QFormLayout(params_box)
        for knob in self.lab.params():
            if not knob.adjustable or not knob.bounded:
                form.addRow(knob.name, QLabel(knob.describe()))
                continue
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(0, 1000)
            slider.setValue(self._to_slider(knob, float(knob.default)))
            slider.valueChanged.connect(self.on_slider)
            label = QLabel("%.3f" % float(knob.default))
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.addWidget(slider, 1)
            row_layout.addWidget(label)
            caption = knob.name + (" [%s]" % knob.semantic_role
                                   if knob.semantic_role else "")
            form.addRow(caption, row)
            self.sliders[knob.name] = slider
            self.labels[knob.name] = label
        layout.addWidget(params_box)

        bar = QHBoxLayout()
        self.spin_detail = QSpinBox()
        self.spin_detail.setRange(1, 5)
        self.spin_detail.setValue(self.lab.detail_level)
        self.spin_detail.setPrefix("detail ")
        self.spin_detail.valueChanged.connect(lambda _v: self.rebuild())
        bar.addWidget(self.spin_detail)
        for text, slot in (("Reset", self.on_reset),
                           ("Randomize", self.on_randomize),
                           ("Save as defaults", self.on_save_defaults),
                           ("Save Variant", self.on_save_variant)):
            button = QPushButton(text)
            button.clicked.connect(slot)
            bar.addWidget(button)
        bar.addStretch(1)
        layout.addLayout(bar)

        traits_box = QGroupBox("Trait e effetti compatibili")
        traits_layout = QHBoxLayout(traits_box)
        self.traits_list = QListWidget()
        self.traits_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        for spec in self.lab.traits():
            item = QListWidgetItem("%s  %s" % (spec.id, spec.description[:60]))
            item.setData(Qt.ItemDataRole.UserRole, spec)
            self.traits_list.addItem(item)
        self.effects_list = QListWidget()
        self.effects_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        for spec in self.lab.effects():
            item = QListWidgetItem("%s  (%s)" % (spec.id, spec.stage))
            item.setData(Qt.ItemDataRole.UserRole, spec)
            self.effects_list.addItem(item)
        self.traits_list.itemSelectionChanged.connect(self.rebuild)
        self.effects_list.itemSelectionChanged.connect(self.rebuild)
        traits_layout.addWidget(self.traits_list)
        traits_layout.addWidget(self.effects_list)
        layout.addWidget(traits_box, 1)

        self.diagnostics = QTableWidget()
        _rows(self.diagnostics, ["Gravita'", "Codice", "Dove", "Messaggio"])
        layout.addWidget(self.diagnostics, 1)
        self.summary = QLabel("-")
        layout.addWidget(self.summary)
        splitter.addWidget(right)
        splitter.setSizes([620, 560])
        outer = QVBoxLayout(self)
        outer.addWidget(splitter)

    @staticmethod
    def _to_slider(knob, value: float) -> int:
        span = float(knob.max) - float(knob.min)
        if span <= 0:
            return 0
        return int(round((value - float(knob.min)) / span * 1000))

    @staticmethod
    def _from_slider(knob, position: int) -> float:
        span = float(knob.max) - float(knob.min)
        return float(knob.min) + span * (position / 1000.0)

    def values(self) -> dict:
        values = {}
        for knob in self.lab.params():
            slider = self.sliders.get(knob.name)
            if slider is not None:
                values[knob.name] = self._from_slider(knob, slider.value())
        return values

    def chosen_traits(self) -> list[dict]:
        out = []
        for item in self.traits_list.selectedItems():
            spec = item.data(Qt.ItemDataRole.UserRole)
            out.append({"trait": spec.id, "value": spec.value.default})
        return out

    def chosen_effects(self) -> list[dict]:
        out = []
        for item in self.effects_list.selectedItems():
            spec = item.data(Qt.ItemDataRole.UserRole)
            scope = (spec.scopes[0] if spec.scopes else "part")
            out.append({"type": spec.id, "scope": scope,
                        "amount": float(spec.amount.default)})
        return out

    def _sync_labels(self) -> None:
        """I numeri accanto agli slider seguono gli slider, sempre.

        Sta qui e non dentro `on_slider` perche' gli slider si muovono anche
        da `Reset` e da `Randomize`, e un'etichetta che resta al valore di
        prima e' il genere di bugia che si scopre tardi.
        """
        for knob in self.lab.params():
            slider = self.sliders.get(knob.name)
            if slider is not None:
                self.labels[knob.name].setText(
                    "%.3f" % self._from_slider(knob, slider.value()))

    def on_slider(self, *_args) -> None:
        self._sync_labels()
        self.rebuild()

    def rebuild(self) -> None:
        self._sync_labels()
        built = self.lab.build(self.values(), traits=self.chosen_traits(),
                               effects=self.chosen_effects(),
                               detail_level=self.spin_detail.value(), check=True)
        self.summary.setText(built.describe())
        scene = built.result.scene() if built.result is not None else None
        if scene is not None:
            self.viewport.set_scene(scene)
        rows = built.diagnostics()
        self.diagnostics.setRowCount(len(rows))
        for index, row in enumerate(rows):
            for column, value in enumerate((row["severity"], row["code"],
                                            row["where"], row["message"])):
                self.diagnostics.setItem(index, column, QTableWidgetItem(str(value)))

    def on_reset(self) -> None:
        self.lab.reset()
        for knob in self.lab.params():
            slider = self.sliders.get(knob.name)
            if slider is not None:
                slider.blockSignals(True)
                slider.setValue(self._to_slider(knob, float(knob.default)))
                slider.blockSignals(False)
        self.traits_list.clearSelection()
        self.effects_list.clearSelection()
        self.rebuild()

    def on_randomize(self) -> None:
        import random

        built = self.lab.randomize(random.randint(0, 10_000))
        for knob in self.lab.params():
            slider = self.sliders.get(knob.name)
            if slider is not None and knob.name in built.values:
                slider.blockSignals(True)
                slider.setValue(self._to_slider(knob,
                                                float(built.values[knob.name])))
                slider.blockSignals(False)
        self.rebuild()

    def on_save_defaults(self) -> None:
        """I valori correnti diventano i predefiniti del **draft**, se c'e'.

        Su un componente installato non si scrive: il registry e' congelato e
        un laboratorio che modificasse la libreria non sarebbe un laboratorio.
        Per quello c'e' «Save Variant».
        """
        if self.service is None or self.service.project is None:
            self.summary.setText("i predefiniti si salvano su un componente in "
                                 "lavorazione; su uno installato usa Save Variant")
            return
        name = self.lab.component_id.partition(":")[2]
        draft = self.service.project.component_by_name(name)
        if draft is None:
            self.summary.setText("'%s' non e' un componente di questo progetto: "
                                 "usa Save Variant" % name)
            return
        for param, value in self.values().items():
            if draft.param(param) is not None:
                self.service.update_param(draft.key, param, default=float(value))
        self.summary.setText("predefiniti aggiornati su '%s'" % draft.name)

    def on_save_variant(self) -> None:
        name, ok = QInputDialog.getText(self, "Save Variant",
                                        "nome (minuscole, cifre, _ e -)")
        if not ok or not name.strip():
            return
        try:
            recipe = self.lab.save_variant(name.strip())
        except AuthoringError as exc:
            self.summary.setText("%s: %s" % (exc.code, exc.message))
            return
        if self.service is not None and self.service.project is not None:
            self.service.save_variant(recipe)
            self.summary.setText("variant salvata nel progetto: " + recipe.describe())
        else:
            path, _ = QFileDialog.getSaveFileName(self, "Salva la variant", "",
                                                  "Variant (*.json)")
            if path:
                VariantRecipe.save(recipe, path)
                self.summary.setText("variant salvata in " + path)


def _words(text: str) -> tuple[str, ...]:
    """Una riga di testo come elenco. Virgole e spazi valgono uguale."""
    return tuple(w for w in str(text or "").replace(",", " ").split() if w)


def _triple(spins) -> QWidget:
    host = QWidget()
    layout = QHBoxLayout(host)
    layout.setContentsMargins(0, 0, 0, 0)
    for spin in spins:
        layout.addWidget(spin)
    return host
