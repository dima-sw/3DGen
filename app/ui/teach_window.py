"""La finestra di Teach 3DGen: un cliente sottile di `TeachService`.

Nessuna logica di Teach vive qui. Ogni bottone chiama un metodo del servizio e
ridisegna cio' che il servizio dice — la stessa regola che tiene
`app/ui/authoring_window.py` sottile rispetto ad `AuthoringService` e
`app/ui/main_window.py` sottile rispetto a `Session`. Serve alla stessa cosa:
un tool a riga di comando, un test e un domani che guida il ciclo da solo
devono poter fare tutto quello che si fa qui, e se un test di questa finestra
passasse e il test del servizio no, la finestra starebbe mentendo.

## Il flusso, e perche' e' una fila di schede

    CONCEPT -> HIERARCHY -> CANDIDATES -> GENERATE -> COMPLETE

E' l'ordine in cui le cose **diventano possibili**: non si analizza senza una
gerarchia, non si valuta un candidato senza una copertura, non si genera un
componente prima di sapere che manca, non si chiude il concetto prima che i
mandatory siano verdi. Le schede restano tutte raggiungibili, perche' tornare
indietro a cambiare un `count` dopo aver visto la coda e' il caso normale.

## I quattro colori

    verde   VALIDATED   soluzione confermata
    giallo  CANDIDATE   possibile soluzione da validare
    blu     PROXY       approssimazione consapevole
    rosso   MISSING     serve conoscenza nuova

Il verde non compare perche' un punteggio e' alto: §41 lo vieta, e il servizio
lo rende vero — nessun metodo che importa una risposta di un modello scrive
`VALIDATED`.

## I prompt

Ogni prompt si genera, si copia, e la risposta si incolla: e' la modalita'
esterna di §5, ed e' una feature, non un ripiego. Il bottone «Chiedi al
provider» usa la catena che la `Session` ha gia' — e manda **lo stesso**
prompt, perche' e' lo stesso oggetto.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QSpinBox, QSplitter, QTabWidget, QTableWidget,
    QTableWidgetItem, QTextBrowser, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
    QWidget,
)

from app.core.logging_setup import get
from app.core.session import Session
from app.teach import BACKENDS, COVERAGE, TeachError, TeachService

log = get("ui.teach")

# I quattro colori di §41. Sono presentazione: lo stato lo decide il servizio.
COVERAGE_COLORS = {"VALIDATED": "#4caf78", "CANDIDATE": "#ffc357",
                   "PROXY": "#5aa9e6", "MISSING": "#ff6b6b"}
COVERAGE_MARKS = {"VALIDATED": "green", "CANDIDATE": "yellow",
                  "PROXY": "blue", "MISSING": "red"}
SEVERITY_COLORS = {"error": "#ff6b6b", "warning": "#ffc357", "info": "#8e97a5"}


def _rows(table: QTableWidget, headers: list[str]) -> None:
    table.setColumnCount(len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setRowCount(0)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)


class TeachWindow(QMainWindow):
    """Concept -> gerarchia -> candidati -> generazione -> concetto imparato."""

    def __init__(self, session: Session | None = None, parent=None) -> None:
        super().__init__(parent)
        self.service = TeachService(session=session or Session())
        self.setWindowTitle("3DGen - Teach")
        self.resize(1460, 940)
        self._bundle = None
        self._build_ui()
        self.refresh_all()

    # ------------------------------------------------------------------ UI #
    def _build_ui(self) -> None:
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._concept_page(), "1. Concept")
        self.tabs.addTab(self._hierarchy_page(), "2. Hierarchy")
        self.tabs.addTab(self._candidates_page(), "3. Candidates")
        self.tabs.addTab(self._generate_page(), "4. Generate")
        self.tabs.addTab(self._complete_page(), "5. Complete")
        splitter.addWidget(self.tabs)
        splitter.addWidget(self._prompt_pane())
        splitter.setSizes([780, 680])

        container = QWidget()
        outer = QVBoxLayout(container)
        outer.addWidget(splitter, 1)
        outer.addWidget(self._progress_bar())
        self.setCentralWidget(container)
        self.status = QLabel("pronto")
        outer.addWidget(self.status)

    def _progress_bar(self) -> QWidget:
        """I numeri di §42, sempre sotto gli occhi, con la formula accanto."""
        box = QGroupBox("Progresso")
        layout = QHBoxLayout(box)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.lbl_progress = QLabel("-")
        self.lbl_counts = QLabel("-")
        self.lbl_completion = QLabel("-")
        for widget in (self.bar, self.lbl_progress, self.lbl_counts,
                       self.lbl_completion):
            layout.addWidget(widget)
        layout.addStretch(1)
        return box

    # ----------------------------------------------------------- 1. concept #
    def _concept_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        host = QWidget()
        form = QFormLayout(host)
        self.in_concept = QLineEdit("dragon")
        self.in_description = QLineEdit()
        self.in_style_target = QLineEdit("cartoon low-poly")
        self.spin_detail = QSpinBox()
        self.spin_detail.setRange(1, 5)
        self.spin_detail.setValue(2)
        self.in_destination = QLineEdit()
        form.addRow("Concept", self.in_concept)
        form.addRow("Che cos'e'", self.in_description)
        form.addRow("Stile", self.in_style_target)
        form.addRow("Detail target", self.spin_detail)
        form.addRow("Destinazione", self.in_destination)
        layout.addWidget(host)

        bar = QHBoxLayout()
        btn_new = QPushButton("Nuovo progetto")
        btn_new.setObjectName("primary")
        btn_new.clicked.connect(self.on_new_project)
        btn_dest = QPushButton("Scegli destinazione...")
        btn_dest.clicked.connect(self.on_choose_destination)
        btn_decompose = QPushButton("Genera prompt: decomposizione")
        btn_decompose.clicked.connect(self.on_decomposition_prompt)
        btn_refine = QPushButton("Genera prompt: raffinamento")
        btn_refine.clicked.connect(self.on_refinement_prompt)
        btn_analyze = QPushButton("Analyze")
        btn_analyze.clicked.connect(self.on_analyze)
        for widget in (btn_new, btn_dest, btn_decompose, btn_refine, btn_analyze):
            bar.addWidget(widget)
        bar.addStretch(1)
        layout.addLayout(bar)

        save = QHBoxLayout()
        btn_save = QPushButton("Salva progetto")
        btn_save.clicked.connect(self.on_save_project)
        btn_load = QPushButton("Apri progetto...")
        btn_load.clicked.connect(self.on_load_project)
        for widget in (btn_save, btn_load):
            save.addWidget(widget)
        save.addStretch(1)
        layout.addLayout(save)

        self.exchanges_table = QTableWidget()
        _rows(self.exchanges_table, ["Scambio", "Nodo", "Modalita'", "Stato"])
        layout.addWidget(self.exchanges_table, 1)
        return page

    def on_new_project(self) -> None:
        def run():
            return self.service.create_project(
                self.in_concept.text().strip() or "concept",
                description=self.in_description.text().strip(),
                style_target=self.in_style_target.text().strip(),
                detail_target=int(self.spin_detail.value()),
                destination=self.in_destination.text().strip())

        if self._guard(run) is not None:
            self.refresh_all()

    def on_choose_destination(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Destinazione dei plugin")
        if path:
            self.in_destination.setText(path)

    def on_decomposition_prompt(self) -> None:
        self._show_prompt(self._guard(self.service.decomposition_prompt))

    def on_refinement_prompt(self) -> None:
        self._show_prompt(self._guard(self.service.refinement_prompt))

    def on_analyze(self) -> None:
        report = self._guard(self.service.analyse)
        if report is not None:
            self.status.setText(report.describe().splitlines()[0])
        self.refresh_all()

    def on_save_project(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Salva progetto Teach", "",
                                              "Teach (*.teach3d)")
        if not path:
            return
        saved = self._guard(lambda: self.service.save_project(path))
        if saved is not None:
            self.status.setText("salvato: %s" % saved)

    def on_load_project(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Apri progetto Teach", "",
                                              "Teach (*.teach3d)")
        if not path:
            return
        if self._guard(lambda: self.service.load_project(path)) is not None:
            self.refresh_all()

    # --------------------------------------------------------- 2. hierarchy #
    def _hierarchy_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Parte", "Stato", "Soluzione", "count",
                                   "mandatory", "importanza", "livello"])
        self.tree.currentItemChanged.connect(self.on_node_chosen)
        layout.addWidget(self.tree, 1)

        host = QWidget()
        form = QFormLayout(host)
        self.in_node_name = QLineEdit()
        self.in_node_role = QLineEdit()
        self.chk_mandatory = QCheckBox("mandatory")
        self.spin_count = QSpinBox()
        self.spin_count.setRange(1, 64)
        self.spin_importance = QDoubleSpinBox()
        self.spin_importance.setRange(0.0, 1.0)
        self.spin_importance.setSingleStep(0.05)
        self.spin_node_detail = QSpinBox()
        self.spin_node_detail.setRange(1, 5)
        self.cmb_coverage = QComboBox()
        self.cmb_coverage.addItems(list(COVERAGE))
        form.addRow("Nome", self.in_node_name)
        form.addRow("Ruolo", self.in_node_role)
        form.addRow("", self.chk_mandatory)
        form.addRow("Count", self.spin_count)
        form.addRow("Importanza", self.spin_importance)
        form.addRow("Detail level", self.spin_node_detail)
        form.addRow("Forza stato", self.cmb_coverage)
        layout.addWidget(host)

        bar = QHBoxLayout()
        btn_apply = QPushButton("Applica")
        btn_apply.clicked.connect(self.on_apply_node)
        btn_force = QPushButton("Forza stato")
        btn_force.clicked.connect(self.on_force_coverage)
        btn_add = QPushButton("Aggiungi figlio")
        btn_add.clicked.connect(self.on_add_node)
        btn_remove = QPushButton("Rimuovi nodo")
        btn_remove.clicked.connect(self.on_remove_node)
        for widget in (btn_apply, btn_force, btn_add, btn_remove):
            bar.addWidget(widget)
        bar.addStretch(1)
        layout.addLayout(bar)
        return page

    def on_node_chosen(self, current=None, _previous=None) -> None:
        node_id = self.current_node()
        if not node_id:
            return
        detail = self._guard(lambda: self.service.node_detail(node_id))
        if detail is None:
            return
        self.in_node_name.setText(detail["name"])
        self.in_node_role.setText(detail["role"])
        self.chk_mandatory.setChecked(bool(detail["mandatory"]))
        self.spin_count.setValue(int(detail["count"]))
        self.spin_importance.setValue(float(detail["importance"]))
        self.spin_node_detail.setValue(int(detail["detail_level"]))
        index = self.cmb_coverage.findText(detail["coverage"])
        if index >= 0:
            self.cmb_coverage.setCurrentIndex(index)
        self.refresh_candidates(detail)
        self.refresh_spec(detail)

    def current_node(self) -> str:
        item = self.tree.currentItem()
        return "" if item is None else str(item.data(0, Qt.ItemDataRole.UserRole))

    def on_apply_node(self) -> None:
        node_id = self.current_node()
        if not node_id:
            return
        self._guard(lambda: self.service.set_node(
            node_id, name=self.in_node_name.text().strip() or "part",
            role=self.in_node_role.text().strip(),
            mandatory=self.chk_mandatory.isChecked(),
            count=int(self.spin_count.value()),
            importance=float(self.spin_importance.value()),
            detail_level=int(self.spin_node_detail.value())))
        self.refresh_all()

    def on_force_coverage(self) -> None:
        node_id = self.current_node()
        if not node_id:
            return
        self._guard(lambda: self.service.set_coverage(
            node_id, self.cmb_coverage.currentText()))
        self.refresh_all()

    def on_add_node(self) -> None:
        node_id = self.current_node()
        if not node_id:
            return
        self._guard(lambda: self.service.add_node(
            node_id, self.in_node_name.text().strip() or "part"))
        self.refresh_all()

    def on_remove_node(self) -> None:
        node_id = self.current_node()
        if not node_id:
            return
        self._guard(lambda: self.service.remove_node(node_id))
        self.refresh_all()

    # -------------------------------------------------------- 3. candidates #
    def _candidates_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.candidates_table = QTableWidget()
        _rows(self.candidates_table, ["Componente", "Punteggio", "Stato",
                                      "Evidenze", "Perche'"])
        self.candidates_table.itemSelectionChanged.connect(self.on_candidate_chosen)
        layout.addWidget(self.candidates_table, 1)

        self.dossier_view = QTextBrowser()
        layout.addWidget(self.dossier_view, 1)

        bar = QHBoxLayout()
        btn_choose = QPushButton("Scegli questo")
        btn_choose.clicked.connect(self.on_choose_candidate)
        btn_validate = QPushButton("Validate with AI")
        btn_validate.clicked.connect(self.on_suitability_prompt)
        btn_deep = QPushButton("Deep Validate")
        btn_deep.clicked.connect(self.on_deep_prompt)
        btn_visual = QPushButton("Visual Validation Prompt")
        btn_visual.clicked.connect(self.on_visual_prompt)
        btn_lab = QPushButton("Open in Component Lab")
        btn_lab.clicked.connect(self.on_open_lab)
        for widget in (btn_choose, btn_validate, btn_deep, btn_visual, btn_lab):
            bar.addWidget(widget)
        bar.addStretch(1)
        layout.addLayout(bar)

        decide = QHBoxLayout()
        self.in_variant = QLineEdit("variant_name")
        btn_apply_ai = QPushButton("Apply AI Suggestion")
        btn_apply_ai.clicked.connect(self.on_apply_suggestion)
        btn_variant = QPushButton("Save Variant")
        btn_variant.clicked.connect(self.on_save_variant)
        btn_works = QPushButton("This Works")
        btn_works.setObjectName("primary")
        btn_works.clicked.connect(self.on_accept_candidate)
        btn_reject = QPushButton("Reject Candidate")
        btn_reject.clicked.connect(self.on_reject_candidate)
        decide.addWidget(QLabel("variant:"))
        decide.addWidget(self.in_variant)
        for widget in (btn_apply_ai, btn_variant, btn_works, btn_reject):
            decide.addWidget(widget)
        decide.addStretch(1)
        layout.addLayout(decide)
        return page

    def current_candidate(self) -> str:
        rows = self.candidates_table.selectionModel().selectedRows() \
            if self.candidates_table.selectionModel() is not None else []
        if not rows:
            return ""
        item = self.candidates_table.item(rows[0].row(), 0)
        return "" if item is None else item.text()

    def on_candidate_chosen(self) -> None:
        node_id, component = self.current_node(), self.current_candidate()
        if not node_id or not component:
            return
        text = self._guard(lambda: self.service.dossier(node_id, component))
        if text is not None:
            self.dossier_view.setPlainText(text)

    def on_choose_candidate(self) -> None:
        node_id, component = self.current_node(), self.current_candidate()
        if not node_id or not component:
            return
        self._guard(lambda: self.service.choose_candidate(node_id, component))
        self.refresh_all()

    def on_suitability_prompt(self) -> None:
        node_id, component = self.current_node(), self.current_candidate()
        if not node_id:
            return
        self._show_prompt(self._guard(
            lambda: self.service.suitability_prompt(node_id, component)))

    def on_deep_prompt(self) -> None:
        node_id, component = self.current_node(), self.current_candidate()
        if not node_id:
            return
        self._show_prompt(self._guard(
            lambda: self.service.deep_validation_prompt(node_id, component)))

    def on_visual_prompt(self) -> None:
        node_id, component = self.current_node(), self.current_candidate()
        if not node_id:
            return
        self._show_prompt(self._guard(
            lambda: self.service.visual_validation_prompt(node_id, component)))

    def on_open_lab(self) -> None:
        node_id, component = self.current_node(), self.current_candidate()
        if not node_id:
            return
        lab = self._guard(lambda: self.service.lab(node_id, component))
        if lab is None:
            return
        from app.ui.authoring_window import ComponentLabDialog

        dialog = ComponentLabDialog(lab, parent=self)
        dialog.show()
        return dialog

    def on_apply_suggestion(self) -> None:
        node_id, component = self.current_node(), self.current_candidate()
        if not node_id:
            return
        built = self._guard(
            lambda: self.service.apply_suggestion(node_id, component))
        if built is not None:
            self.status.setText(built.describe())

    def on_save_variant(self) -> None:
        node_id, component = self.current_node(), self.current_candidate()
        if not node_id:
            return
        recipe = self._guard(lambda: self.service.save_variant(
            node_id, self.in_variant.text().strip() or "variant",
            component_id=component))
        if recipe is not None:
            self.status.setText(recipe.describe())
        self.refresh_all()

    def on_accept_candidate(self) -> None:
        node_id, component = self.current_node(), self.current_candidate()
        if not node_id:
            return
        self._guard(lambda: self.service.accept_candidate(node_id, component))
        self.refresh_all()

    def on_reject_candidate(self) -> None:
        node_id, component = self.current_node(), self.current_candidate()
        if not node_id:
            return
        self._guard(lambda: self.service.reject_candidate(node_id, component))
        self.refresh_all()

    # ---------------------------------------------------------- 4. generate #
    def _generate_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.queue_table = QTableWidget()
        _rows(self.queue_table, ["Nodo", "Profondita'", "Importanza", "Backend"])
        layout.addWidget(self.queue_table, 1)

        bar = QHBoxLayout()
        self.cmb_backend = QComboBox()
        self.cmb_backend.addItems(list(BACKENDS))
        btn_backend = QPushButton("Usa questo backend")
        btn_backend.clicked.connect(self.on_set_backend)
        btn_asset = QPushButton("Fornisci GLB...")
        btn_asset.clicked.connect(self.on_supply_asset)
        btn_spec = QPushButton("Generate Implementation Prompt")
        btn_spec.setObjectName("primary")
        btn_spec.clicked.connect(self.on_implementation_prompt)
        bar.addWidget(QLabel("backend:"))
        bar.addWidget(self.cmb_backend)
        for widget in (btn_backend, btn_asset, btn_spec):
            bar.addWidget(widget)
        bar.addStretch(1)
        layout.addLayout(bar)

        self.spec_view = QTextBrowser()
        layout.addWidget(self.spec_view, 1)

        self.artifacts_table = QTableWidget()
        _rows(self.artifacts_table, ["Artefatto", "Nodo", "Specie", "File",
                                     "Fiducia", "Avvisi"])
        self.artifacts_table.itemSelectionChanged.connect(self.on_artifact_chosen)
        layout.addWidget(self.artifacts_table, 1)

        self.inspection_view = QTextBrowser()
        layout.addWidget(self.inspection_view, 1)

        actions = QHBoxLayout()
        self.chk_isolate = QCheckBox("in un sottoprocesso (robustezza, non sandbox)")
        btn_trust = QPushButton("Trust and Test")
        btn_trust.clicked.connect(self.on_trust)
        btn_check = QPushButton("Valida")
        btn_check.clicked.connect(self.on_validate_artifact)
        btn_lab2 = QPushButton("Guarda nel Lab")
        btn_lab2.clicked.connect(self.on_artifact_lab)
        btn_accept = QPushButton("Accept")
        btn_accept.clicked.connect(self.on_accept_artifact)
        btn_reject2 = QPushButton("Reject")
        btn_reject2.clicked.connect(self.on_reject_artifact)
        btn_repair = QPushButton("Generate Repair Prompt")
        btn_repair.clicked.connect(self.on_repair_prompt)
        actions.addWidget(self.chk_isolate)
        for widget in (btn_trust, btn_check, btn_lab2, btn_accept, btn_reject2,
                       btn_repair):
            actions.addWidget(widget)
        actions.addStretch(1)
        layout.addLayout(actions)

        self.validation_table = QTableWidget()
        _rows(self.validation_table, ["Gravita'", "Codice", "Dove", "Messaggio"])
        layout.addWidget(self.validation_table, 1)
        return page

    def current_artifact(self) -> str:
        rows = self.artifacts_table.selectionModel().selectedRows() \
            if self.artifacts_table.selectionModel() is not None else []
        if not rows:
            return ""
        item = self.artifacts_table.item(rows[0].row(), 0)
        return "" if item is None else item.text()

    def on_set_backend(self) -> None:
        node_id = self.current_node()
        if not node_id:
            return
        self._guard(lambda: self.service.set_backend(
            node_id, self.cmb_backend.currentText()))
        self.refresh_all()

    def on_supply_asset(self) -> None:
        node_id = self.current_node()
        if not node_id:
            return
        path, _ = QFileDialog.getOpenFileName(self, "GLB per questa parte", "",
                                              "Modelli (*.glb *.gltf)")
        if not path:
            return
        self._guard(lambda: self.service.supply_asset(node_id, path))
        self.refresh_all()

    def on_implementation_prompt(self) -> None:
        node_id = self.current_node()
        if not node_id:
            return
        self._show_prompt(self._guard(
            lambda: self.service.implementation_prompt(node_id)))

    def on_artifact_chosen(self) -> None:
        artifact_id = self.current_artifact()
        if not artifact_id:
            return
        detail = self._guard(lambda: self.service.inspect_artifact(artifact_id))
        if detail is None:
            return
        righe = ["artefatto: %s" % detail["id"],
                 "nodo: %s" % detail["node"],
                 "specie: %s" % detail["kind"],
                 "componente: %s" % detail["component"],
                 "contiene Python: %s" % ("si" if detail["code"] else "no"),
                 "fidato: %s" % ("si" if detail["trusted"] else "no"),
                 "dimensione: %d byte" % detail["total_size"],
                 "", "SICUREZZA", detail["security"], ""]
        for item in detail["inspections"]:
            righe.append("%s: %d byte, compila: %s" % (
                item["path"], item["size"], "si" if item["syntax_ok"] else "no"))
            if item["error"]:
                righe.append("  errore: %s" % item["error"])
            righe.append("  import: %s" % ", ".join(item["imports"]))
            if item["flagged_imports"]:
                righe.append("  segnalati: %s" % ", ".join(item["flagged_imports"]))
            if item["flagged_calls"]:
                righe.append("  chiamate: %s" % ", ".join(item["flagged_calls"]))
            righe.append("  registra un Component: %s"
                         % ("si" if item["builds_component"] else "no"))
        righe.append("")
        for item in detail["files"]:
            righe += ["--- %s (%d byte) ---" % (item["path"], item["size"]),
                      item["content"]]
        self.inspection_view.setPlainText("\n".join(righe))

    def on_trust(self) -> None:
        artifact_id = self.current_artifact()
        if not artifact_id:
            return
        if QMessageBox.question(
                self, "Trust and Test",
                "Il codice generato verra' importato ed eseguito da questo "
                "processo.\nI controlli statici non sono una sandbox: leggi i "
                "file prima di continuare.\n\nProcedo?") \
                != QMessageBox.StandardButton.Yes:
            return
        self._guard(lambda: self.service.trust_artifact(artifact_id))
        self.on_artifact_chosen()
        self.refresh_all()

    def on_validate_artifact(self) -> None:
        artifact_id = self.current_artifact()
        if not artifact_id:
            return
        out = self._guard(lambda: self.service.validate_artifact(
            artifact_id, isolate=self.chk_isolate.isChecked()))
        if out is None:
            return
        self.status.setText(out.describe())
        self._fill_validation([{"severity": d.severity, "code": d.code,
                                "where": d.where, "message": d.message}
                               for d in out.report.sorted()])

    def on_artifact_lab(self) -> None:
        artifact_id = self.current_artifact()
        if not artifact_id:
            return
        lab = self._guard(lambda: self.service.artifact_lab(artifact_id))
        if lab is None:
            return
        from app.ui.authoring_window import ComponentLabDialog

        dialog = ComponentLabDialog(lab, parent=self)
        dialog.show()
        return dialog

    def on_accept_artifact(self) -> None:
        artifact_id = self.current_artifact()
        if not artifact_id:
            return
        out = self._guard(lambda: self.service.accept_artifact(artifact_id))
        if out is not None:
            self.status.setText(out.describe())
        self.refresh_all()

    def on_reject_artifact(self) -> None:
        artifact_id = self.current_artifact()
        if not artifact_id:
            return
        self._guard(lambda: self.service.reject_artifact(artifact_id))
        self.refresh_all()

    def on_repair_prompt(self) -> None:
        artifact_id = self.current_artifact()
        if not artifact_id:
            return
        self._show_prompt(self._guard(
            lambda: self.service.repair_prompt(artifact_id)))

    # ---------------------------------------------------------- 5. complete #
    def _complete_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        bar = QHBoxLayout()
        btn_composite = QPushButton("Build composite del nodo")
        btn_composite.clicked.connect(self.on_emit_composite)
        btn_root = QPushButton("Build root composite")
        btn_root.setObjectName("primary")
        btn_root.clicked.connect(self.on_emit_root)
        btn_finish = QPushButton("Mark as LEARNED")
        btn_finish.clicked.connect(self.on_finish)
        btn_knowledge = QPushButton("Esporta conoscenza")
        btn_knowledge.clicked.connect(self.on_export_knowledge)
        btn_next = QPushButton("Prossimo passo")
        btn_next.clicked.connect(self.on_advance)
        for widget in (btn_composite, btn_root, btn_finish, btn_knowledge,
                       btn_next):
            bar.addWidget(widget)
        bar.addStretch(1)
        layout.addLayout(bar)

        self.completion_table = QTableWidget()
        _rows(self.completion_table, ["Criterio", "Esito"])
        layout.addWidget(self.completion_table, 1)
        self.changed_table = QTableWidget()
        _rows(self.changed_table, ["Nodo", "Componente", "Plugin", "Cambiamento"])
        layout.addWidget(self.changed_table, 1)
        return page

    def on_emit_composite(self) -> None:
        node_id = self.current_node()
        if not node_id:
            return
        out = self._guard(lambda: self.service.emit_composite(node_id))
        if out is not None:
            self.status.setText("%s: %s" % (out["component"], out["validation"]))
        self.refresh_all()

    def on_emit_root(self) -> None:
        out = self._guard(self.service.emit_composite)
        if out is not None:
            self.status.setText("%s: %s" % (out["component"], out["validation"]))
        self.refresh_all()

    def on_finish(self) -> None:
        out = self._guard(self.service.finish)
        if out is not None:
            self.status.setText(out.describe().splitlines()[-1])
        self.refresh_all()

    def on_export_knowledge(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Esporta conoscenza", "",
                                              "JSON (*.json)")
        saved = self._guard(lambda: self.service.export_knowledge(path or None))
        if saved is not None:
            self.status.setText("conoscenza: %s" % saved)

    def on_advance(self) -> None:
        step = self._guard(self.service.advance)
        if step is not None:
            self.status.setText("%s: %s" % (step.get("action", "?"),
                                            step.get("why", "")))

    # --------------------------------------------------------- il pannello #
    def _prompt_pane(self) -> QWidget:
        box = QGroupBox("Prompt e risposta")
        layout = QVBoxLayout(box)
        mode = QHBoxLayout()
        self.cmb_mode = QComboBox()
        self.cmb_mode.addItems(["External / Manual", "Provider configurato"])
        mode.addWidget(QLabel("Modalita':"))
        mode.addWidget(self.cmb_mode)
        self.lbl_prompt = QLabel("nessun prompt generato")
        mode.addWidget(self.lbl_prompt)
        mode.addStretch(1)
        layout.addLayout(mode)

        self.prompt_view = QPlainTextEdit()
        self.prompt_view.setReadOnly(True)
        layout.addWidget(self.prompt_view, 2)

        bar = QHBoxLayout()
        btn_copy = QPushButton("Copia prompt")
        btn_copy.clicked.connect(self.on_copy_prompt)
        btn_ask = QPushButton("Chiedi al provider")
        btn_ask.clicked.connect(self.on_ask_provider)
        btn_import = QPushButton("Importa risposta")
        btn_import.setObjectName("primary")
        btn_import.clicked.connect(self.on_import_response)
        for widget in (btn_copy, btn_ask, btn_import):
            bar.addWidget(widget)
        bar.addStretch(1)
        layout.addLayout(bar)

        self.response_view = QPlainTextEdit()
        self.response_view.setPlaceholderText(
            "Incolla qui la risposta del modello, poi premi «Importa risposta».")
        layout.addWidget(self.response_view, 2)
        return box

    def _show_prompt(self, bundle) -> None:
        if bundle is None:
            return
        self._bundle = bundle
        self.prompt_view.setPlainText(bundle.text)
        self.lbl_prompt.setText(bundle.describe())
        self.refresh_exchanges()

    def on_copy_prompt(self) -> None:
        from PySide6.QtGui import QGuiApplication

        if self._bundle is None:
            return
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self._bundle.text)
        self.status.setText("prompt copiato (%d caratteri)"
                            % self._bundle.characters)

    def on_ask_provider(self) -> None:
        if self._bundle is None:
            return
        text = self._guard(lambda: self.service.ask(self._bundle))
        if text is not None:
            self.response_view.setPlainText(text)
            self.status.setText("risposta dal provider (%d caratteri)" % len(text))

    def on_import_response(self) -> None:
        """Una risposta sola, instradata dalla specie del prompt che l'ha chiesta.

        La specie non si indovina dal testo: la sa il prompt che l'utente ha
        generato. Un'importazione senza prompt e' un'operazione senza contesto,
        e diventa una riga di stato invece di un tentativo.
        """
        if self._bundle is None:
            self.status.setText("genera prima un prompt: la risposta va letta "
                                "come risposta a qualcosa")
            return
        raw = self.response_view.toPlainText()
        kind, node = self._bundle.kind, self._bundle.node
        actions = {
            "decomposition": lambda: self.service.import_decomposition(raw),
            "refinement": lambda: self.service.import_refinement(raw),
            "suitability": lambda: self.service.import_suitability(node, raw),
            "deep": lambda: self.service.import_suitability(node, raw, deep=True),
            "visual": lambda: self.service.import_visual(node, raw),
            "implementation": lambda: self.service.import_implementation(node, raw),
            "repair": lambda: self.service.import_repair(node, raw),
        }
        run = actions.get(kind)
        if run is None:
            self.status.setText("niente da importare per %r" % kind)
            return
        out = self._guard(run)
        if out is not None:
            self.status.setText("%s importata" % kind)
        self.refresh_all()

    # ------------------------------------------------------------ refresh #
    def refresh_all(self) -> None:
        self.refresh_tree()
        self.refresh_progress()
        self.refresh_queue()
        self.refresh_artifacts()
        self.refresh_completion()
        self.refresh_exchanges()

    def refresh_tree(self) -> None:
        # La selezione si conserva: ridisegnare l'albero dopo ogni passo
        # perderebbe il nodo su cui si stava lavorando, e il passo successivo
        # non avrebbe un bersaglio.
        chosen = self.current_node()
        self.tree.clear()
        rows = self._guard(self.service.tree) or []
        items: dict[str, QTreeWidgetItem] = {}
        for row in rows:
            item = QTreeWidgetItem([
                row["name"] + ("" if row["count"] == 1 else " x%d" % row["count"]),
                "%s %s" % (COVERAGE_MARKS.get(row["coverage"], "?"),
                           row["coverage"]),
                row["solution"] or (row["candidates"][0] if row["candidates"]
                                    else ""),
                str(row["count"]),
                "mandatory" if row["mandatory"] else "optional",
                "%.2f" % row["importance"], str(row["detail_level"])])
            item.setData(0, Qt.ItemDataRole.UserRole, row["id"])
            colour = COVERAGE_COLORS.get(row["coverage"])
            if colour is not None:
                from PySide6.QtGui import QBrush, QColor

                item.setForeground(1, QBrush(QColor(colour)))
            parent_id = row["id"].rpartition(".")[0]
            parent = items.get(parent_id)
            if parent is None:
                self.tree.addTopLevelItem(item)
            else:
                parent.addChild(item)
            items[row["id"]] = item
        self.tree.expandAll()
        again = items.get(chosen)
        if again is not None:
            self.tree.setCurrentItem(again)

    def refresh_progress(self) -> None:
        data = self._guard(self.service.summary)
        if data is None:
            return
        self.bar.setValue(int(data["mandatory_percent"]))
        self.lbl_progress.setText(
            "mandatory %.0f%% (peso), %.0f%% per nodi | optional %.0f%%"
            % (data["mandatory_percent"], data["mandatory_node_percent"],
               data["optional_percent"]))
        counts = data.get("counts", {})
        self.lbl_counts.setText(" | ".join(
            "%s %s %d" % (COVERAGE_MARKS.get(k, "?"), k, counts.get(k, 0))
            for k in COVERAGE))
        self.lbl_completion.setText(data.get("completion", "-"))

    def refresh_candidates(self, detail: dict) -> None:
        rows = detail.get("candidates", [])
        self.candidates_table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            kinds = ", ".join(sorted(e["kind"] for e in row["evidence"]))
            for column, value in enumerate([row["component"],
                                            "%.3f" % row["score"],
                                            row["verdict"], kinds,
                                            row["reason"]]):
                self.candidates_table.setItem(index, column,
                                              QTableWidgetItem(str(value)))

    def refresh_spec(self, detail: dict) -> None:
        node_id = detail.get("id", "")
        if not node_id:
            return
        index = self.cmb_backend.findText(detail.get("backend", ""))
        if index >= 0:
            self.cmb_backend.setCurrentIndex(index)
        if detail.get("coverage") != "MISSING":
            self.spec_view.setPlainText(
                "il nodo non e' MISSING: la specifica tecnica serve a chi deve "
                "generare conoscenza nuova.\nbackend consigliato: %s\n%s"
                % (detail.get("backend", ""), detail.get("backend_reason", "")))
            return
        spec = self._guard(lambda: self.service.spec(node_id))
        if spec is None:
            return
        import pprint

        self.spec_view.setPlainText(pprint.pformat(spec.to_dict(), width=96,
                                                   sort_dicts=True))

    def refresh_queue(self) -> None:
        nodes = self._guard(self.service.queue) or []
        self.queue_table.setRowCount(len(nodes))
        for index, node in enumerate(nodes):
            detail = self._guard(lambda n=node: self.service.node_detail(n.id)) or {}
            for column, value in enumerate([node.id, node.depth,
                                            "%.2f" % node.importance,
                                            detail.get("backend", "")]):
                self.queue_table.setItem(index, column,
                                         QTableWidgetItem(str(value)))

    def refresh_artifacts(self) -> None:
        artifacts = self._guard(self.service.artifacts) or []
        self.artifacts_table.setRowCount(len(artifacts))
        for index, artifact in enumerate(artifacts):
            for column, value in enumerate([artifact.id, artifact.node,
                                            artifact.kind,
                                            len(artifact.files),
                                            "fidato" if artifact.trusted
                                            else "non fidato",
                                            len(artifact.warnings)]):
                self.artifacts_table.setItem(index, column,
                                             QTableWidgetItem(str(value)))

    def refresh_completion(self) -> None:
        report = self._guard(self.service.completion_report)
        if report is None:
            return
        rows = report.rows()
        self.completion_table.setRowCount(len(rows) + 1)
        for index, (what, ok) in enumerate(rows):
            self.completion_table.setItem(index, 0, QTableWidgetItem(what))
            self.completion_table.setItem(index, 1,
                                          QTableWidgetItem("si" if ok else "no"))
        self.completion_table.setItem(len(rows), 0,
                                      QTableWidgetItem("mancano"))
        self.completion_table.setItem(len(rows), 1,
                                      QTableWidgetItem(", ".join(report.missing)))
        changed = self._guard(self.service.changed_components) or []
        self.changed_table.setRowCount(len(changed))
        for index, row in enumerate(changed):
            for column, key in enumerate(("node", "ref", "plugin", "change")):
                self.changed_table.setItem(index, column,
                                           QTableWidgetItem(str(row.get(key, ""))))

    def refresh_exchanges(self) -> None:
        rows = self._guard(self.service.exchanges) or []
        self.exchanges_table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            for column, value in enumerate([row["kind"], row["node"],
                                            row["mode"],
                                            "importata" if row["accepted"]
                                            else "in attesa"]):
                self.exchanges_table.setItem(index, column,
                                             QTableWidgetItem(str(value)))

    def _fill_validation(self, rows) -> None:
        from PySide6.QtGui import QBrush, QColor

        self.validation_table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            for column, key in enumerate(("severity", "code", "where",
                                          "message")):
                item = QTableWidgetItem(str(row.get(key, "")))
                colour = SEVERITY_COLORS.get(row.get("severity", ""))
                if colour is not None:
                    item.setForeground(QBrush(QColor(colour)))
                self.validation_table.setItem(index, column, item)

    # ----------------------------------------------------------- interno #
    def _guard(self, run):
        """Un errore di Teach e' una riga di stato, non un traceback."""
        try:
            return run()
        except TeachError as exc:
            self.status.setText("%s: %s" % (exc.code, exc.message))
            log.info("teach: %s %s", exc.code, exc.message)
            return None
        except (ValueError, OSError) as exc:
            self.status.setText(str(exc))
            log.warning("teach: %s", exc)
            return None

    def closeEvent(self, event) -> None:
        self.service.close()
        super().closeEvent(event)
