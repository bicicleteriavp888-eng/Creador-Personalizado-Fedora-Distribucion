"""Selector de software Fedora para proyectos personalizados.

La consulta a DNF es de solo lectura y se ejecuta en un hilo para no bloquear
la interfaz. La validación de paquetes, grupos y búsquedas vive en
``core.software.policy`` y la ejecución de DNF en
``core.repositories.dnf_query``.
"""
import html

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.projects.catalog import get_project_template, list_project_types, merge_packages
from core.repositories.dnf_query import DnfQuery, DnfQueryError
from core.software.policy import (
    SoftwareSelectionError,
    normalize_group_entry,
    normalize_search_query,
    validate_package_names,
)
from gui.components import FlowLayout, prepare_combo
from gui.layouts import add_page


class DnfWorker(QThread):
    """Ejecuta una consulta DNF y devuelve datos ya parseados."""

    results = Signal(str, object)
    failed = Signal(str, str)

    def __init__(self, operation, query="", packages=(), groups=()):
        super().__init__()
        self.operation = operation
        self.query = query
        self.packages = tuple(packages)
        self.groups = tuple(groups)

    def run(self):
        try:
            dnf = DnfQuery()
            if self.operation == "repositories":
                payload = dnf.list_enabled_repositories()
            elif self.operation == "groups":
                payload = dnf.list_groups()
            elif self.operation == "group_info":
                payload = dnf.group_info(self.query)
            elif self.operation == "packages":
                payload = dnf.search_packages(self.query)
            elif self.operation == "preview":
                payload = dnf.preview_installation(self.packages, self.groups)
            else:
                raise ValueError(f"Operación DNF desconocida: {self.operation}")
            self.results.emit(self.operation, payload)
        except (DnfQueryError, SoftwareSelectionError) as exc:
            self.failed.emit(self.operation, str(exc))
        except Exception:  # noqa: BLE001 - el hilo debe informar, no morir
            self.failed.emit(
                self.operation,
                "No se pudo completar la consulta DNF por un error inesperado.",
            )


class CustomDistroTabMixin:

    def adapt_software_manager_layout(self, available_width=None):
        """Adapta el catálogo/cesta al ancho disponible de la ventana."""
        splitter = getattr(self, "software_manager_splitter", None)
        if splitter is None:
            return
        if available_width is None:
            available_width = self.width()
        target = (
            Qt.Orientation.Horizontal
            if int(available_width) >= 1440
            else Qt.Orientation.Vertical
        )
        if splitter.orientation() != target:
            splitter.setOrientation(target)
            if target == Qt.Orientation.Horizontal:
                splitter.setSizes([max(420, available_width * 0.58),
                                   max(320, available_width * 0.42)])
            else:
                splitter.setSizes([560, 340])

    def init_custom_distro(self):
        """Construye el gestor visual de software estilo Synaptic."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(18, 14, 18, 16)
        layout.setSpacing(10)

        self.lbl_manager_status = QLabel("Catálogo sin cargar.")
        self.lbl_manager_status.setObjectName("managerStatus")
        self.lbl_manager_status.setWordWrap(True)
        self.lbl_manager_status.setMaximumHeight(42)
        self.lbl_manager_status.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        layout.addWidget(self.lbl_manager_status)

        def _card(title, subtitle=""):
            frame = QFrame()
            frame.setObjectName("settingRowCard")
            card_layout = QVBoxLayout(frame)
            card_layout.setContentsMargins(16, 14, 16, 14)
            card_layout.setSpacing(10)
            t = QLabel(title)
            t.setObjectName("settingTitle")
            card_layout.addWidget(t)
            if subtitle:
                d = QLabel(subtitle)
                d.setObjectName("settingDescription")
                d.setWordWrap(True)
                card_layout.addWidget(d)
            return frame, card_layout

        # Objetivo del proyecto y perfiles sugeridos. Este combo es propio del
        # gestor: el selector del paso 1 permanece en su formulario y ambos se
        # sincronizan por estado, sin reparentar widgets entre páginas.
        profile, profile_layout = _card(
            "Perfil de distribución",
            "Define el objetivo del proyecto y carga paquetes sugeridos.",
        )
        profile_row = QHBoxLayout()
        self.combo_manager_project_type = QComboBox()
        prepare_combo(self.combo_manager_project_type, 20)
        for key, name, tagline in list_project_types():
            self.combo_manager_project_type.addItem(f"{name} — {tagline}", key)
        self.combo_manager_project_type.setToolTip(
            "El perfil define el motor de la imagen. Kiosco y los perfiles "
            "Desktop usan motores independientes."
        )
        profile_row.addWidget(self.combo_manager_project_type, 2)
        self.lbl_project_description = QLabel()
        self.lbl_project_description.setWordWrap(True)
        self.lbl_project_description.setMaximumHeight(62)
        profile_row.addWidget(self.lbl_project_description, 4)
        self.btn_apply_project_template = QPushButton("Cargar perfil sugerido")
        self.btn_apply_project_template.clicked.connect(self.apply_project_template)
        profile_row.addWidget(self.btn_apply_project_template)
        profile_layout.addLayout(profile_row)
        # El perfil se agrega más abajo, después de la tabla, para que el
        # catálogo quede visible al abrir el gestor en 1080x720.
        self.combo_manager_project_type.currentIndexChanged.connect(
            self._on_manager_project_changed
        )
        self.combo_project_type.currentIndexChanged.connect(
            self._sync_manager_project_type
        )
        self._sync_manager_project_type()
        self._update_project_description()

        # Barra de búsqueda y filtros del catálogo.
        search_box, search_layout = _card(
            "Catálogo de software Fedora",
            "Buscá paquetes por nombre o descripción y filtrá por repositorio.",
        )
        search_row = QHBoxLayout()
        self.custom_pkg_search = QLineEdit()
        self.custom_pkg_search.setPlaceholderText("Buscar por nombre o descripción: firefox, gimp, servidor web…")
        self.custom_pkg_search.returnPressed.connect(self.search_fedora_packages)
        search_row.addWidget(self.custom_pkg_search, 1)
        self.btn_pkg_search = QPushButton("Buscar")
        self.btn_pkg_search.clicked.connect(self.search_fedora_packages)
        search_row.addWidget(self.btn_pkg_search)
        self.btn_pkg_refresh = QPushButton("Cargar catálogo")
        self.btn_pkg_refresh.clicked.connect(lambda: self._query_fedora_packages(""))
        search_row.addWidget(self.btn_pkg_refresh)
        search_layout.addLayout(search_row)

        filters = QVBoxLayout()
        filters.setSpacing(6)
        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        filter_row.addWidget(QLabel("Repositorio:"))
        self.combo_repo_filter = QComboBox()
        prepare_combo(self.combo_repo_filter, 12)
        self.combo_repo_filter.addItem("Todos los repositorios", "")
        self.combo_repo_filter.currentIndexChanged.connect(self._filter_package_table)
        filter_row.addWidget(self.combo_repo_filter, 2)
        filter_row.addWidget(QLabel("Nombre:"))
        self.combo_package_type = QComboBox()
        prepare_combo(self.combo_package_type, 10)
        self.combo_package_type.addItem("Todos", "all")
        self.combo_package_type.addItem("Bibliotecas (lib/devel)", "libs")
        self.combo_package_type.addItem("Aplicaciones y herramientas", "apps")
        self.combo_package_type.currentIndexChanged.connect(self._filter_package_table)
        filter_row.addWidget(self.combo_package_type, 1)
        filters.addLayout(filter_row)
        self.lbl_catalog_status = QLabel("Catálogo sin cargar")
        self.lbl_catalog_status.setObjectName("wizardStatus")
        filters.addWidget(self.lbl_catalog_status)
        search_layout.addLayout(filters)
        layout.addWidget(search_box)

        # Catálogo y cesta de cambios pendientes.
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setObjectName("softwareManagerSplitter")
        self.software_manager_splitter = splitter
        splitter.setChildrenCollapsible(True)
        available_box, available_layout = _card("Paquetes disponibles")
        self.table_fedora_available = QTableWidget(0, 6)
        self.table_fedora_available.setObjectName("managerTable")
        self.table_fedora_available.setHorizontalHeaderLabels(
            ["Paquete", "Descripción", "Versión", "Arquitectura", "Repositorio", "Tipo"]
        )
        self.table_fedora_available.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table_fedora_available.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table_fedora_available.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table_fedora_available.itemSelectionChanged.connect(self._show_package_detail)
        self.table_fedora_available.setAlternatingRowColors(True)
        self.table_fedora_available.setWordWrap(False)
        self.table_fedora_available.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.table_fedora_available.verticalHeader().setVisible(False)
        self.table_fedora_available.verticalHeader().setDefaultSectionSize(28)
        header = self.table_fedora_available.horizontalHeader()
        header.setMinimumSectionSize(52)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.table_fedora_available.setMinimumHeight(120)
        self.table_fedora_available.setMinimumWidth(0)
        self.table_fedora_available.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        available_layout.addWidget(self.table_fedora_available, 1)
        self.lbl_package_detail = QLabel("Seleccioná un paquete para consultar sus datos.")
        self.lbl_package_detail.setWordWrap(True)
        available_layout.addWidget(self.lbl_package_detail)
        available_box.setMinimumWidth(0)
        available_box.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        splitter.addWidget(available_box)

        pending_box, pending_layout = _card("Cambios pendientes")
        self.table_fedora_pending = QTableWidget(0, 2)
        self.table_fedora_pending.setObjectName("pendingTable")
        self.table_fedora_pending.setHorizontalHeaderLabels(["Acción", "Paquete / grupo"])
        self.table_fedora_pending.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table_fedora_pending.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table_fedora_pending.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table_fedora_pending.setAlternatingRowColors(True)
        self.table_fedora_pending.verticalHeader().setVisible(False)
        self.table_fedora_pending.verticalHeader().setDefaultSectionSize(28)
        self.table_fedora_pending.horizontalHeader().setMinimumSectionSize(52)
        self.table_fedora_pending.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table_fedora_pending.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table_fedora_pending.setMinimumHeight(110)
        self.table_fedora_pending.setMinimumWidth(0)
        self.table_fedora_pending.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        pending_layout.addWidget(self.table_fedora_pending, 1)
        self.lbl_custom_pkg_count = QLabel("0 paquetes · 0 grupos seleccionados")
        pending_layout.addWidget(self.lbl_custom_pkg_count)
        self.lbl_pending_scope = QLabel(
            "Alcance actual: instalar paquetes y grupos Comps. DNF5 simula la "
            "transacción; quitar, actualizar o mantener paquetes todavía no "
            "está habilitado en esta versión."
        )
        self.lbl_pending_scope.setObjectName("scopeNote")
        self.lbl_pending_scope.setWordWrap(True)
        pending_layout.addWidget(self.lbl_pending_scope)
        pending_box.setMinimumWidth(0)
        pending_box.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        splitter.addWidget(pending_box)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setChildrenCollapsible(True)
        splitter.setSizes([620, 360])
        layout.addWidget(splitter, 1)

        action_row = FlowLayout(h_spacing=10, v_spacing=8)
        add = QPushButton("Marcar para instalar →")
        add.clicked.connect(self._add_custom_packages)
        remove = QPushButton("Desmarcar selección")
        remove.clicked.connect(self._remove_custom_packages)
        action_row.addWidget(add)
        action_row.addWidget(remove)
        self.btn_dependency_preview = QPushButton("Simular cambios y dependencias")
        self.btn_dependency_preview.setObjectName("primaryAction")
        self.btn_dependency_preview.setToolTip("DNF5 resolverá dependencias y conflictos sin instalar nada en el equipo anfitrión.")
        self.btn_dependency_preview.clicked.connect(self.preview_custom_transaction)
        action_row.addWidget(self.btn_dependency_preview)
        layout.addLayout(action_row)

        # Grupos Comps y repositorios en panel secundario, sin competir con el catálogo.
        lower = QHBoxLayout()
        groups_box, groups_layout = _card("Grupos Comps")
        self.combo_dnf_group = QComboBox()
        prepare_combo(self.combo_dnf_group, 22)
        self.combo_dnf_group.setEnabled(False)
        self.combo_dnf_group.setToolTip(
            "Los grupos Comps no son metapaquetes RPM: DNF los expande a los "
            "paquetes que el repositorio declare."
        )
        groups_layout.addWidget(self.combo_dnf_group)
        group_actions = FlowLayout(h_spacing=8, v_spacing=6)
        self.btn_groups_load = QPushButton("Cargar grupos")
        self.btn_groups_load.clicked.connect(self.load_fedora_groups)
        group_actions.addWidget(self.btn_groups_load)
        self.btn_group_info = QPushButton("Ver contenido")
        self.btn_group_info.clicked.connect(self._show_selected_group_info)
        self.btn_group_info.setEnabled(False)
        group_actions.addWidget(self.btn_group_info)
        self.btn_group_add = QPushButton("Agregar grupo")
        self.btn_group_add.clicked.connect(self._add_custom_group)
        self.btn_group_add.setEnabled(False)
        group_actions.addWidget(self.btn_group_add)
        groups_layout.addLayout(group_actions)
        lower.addWidget(groups_box, 3)

        repos_box, repos_layout = _card("Repositorios")
        self.btn_repos_query = QPushButton("Actualizar repositorios")
        self.btn_repos_query.clicked.connect(self.load_enabled_repositories)
        repos_layout.addWidget(self.btn_repos_query)
        self.lbl_repos_status = QLabel("Repositorios todavía no consultados")
        self.lbl_repos_status.setWordWrap(True)
        repos_layout.addWidget(self.lbl_repos_status)
        lower.addWidget(repos_box, 2)

        rpm_box, rpm_layout = _card("RPM locales · software adicional")
        self.list_local_rpms = QListWidget()
        self.list_local_rpms.setMinimumHeight(74)
        self.list_local_rpms.setToolTip(
            "Los RPM se inspeccionan y verifican antes de compilar. En Desktop "
            "se instalan como paquetes del sistema; en Kiosco se agregan al "
            "sistema sin reemplazar el selector de aplicación de inicio."
        )
        rpm_layout.addWidget(self.list_local_rpms)
        rpm_actions = QHBoxLayout()
        self.btn_add_local_rpm = QPushButton("Agregar RPM local…")
        self.btn_add_local_rpm.clicked.connect(self._add_local_rpms)
        self.btn_remove_local_rpm = QPushButton("Quitar seleccionado")
        self.btn_remove_local_rpm.clicked.connect(self._remove_local_rpm)
        rpm_actions.addWidget(self.btn_add_local_rpm)
        rpm_actions.addWidget(self.btn_remove_local_rpm)
        rpm_layout.addLayout(rpm_actions)
        lower.addWidget(rpm_box, 3)
        layout.addLayout(lower)
        layout.addWidget(profile)

        self.list_fedora_available = QListWidget()  # compatibilidad con pruebas/integraciones 2.x
        self.list_fedora_selected = QListWidget()
        self.list_fedora_available.hide()
        self.list_fedora_selected.hide()
        self.list_groups_selected = QListWidget()
        self.list_groups_selected.hide()
        self.lbl_groups_status = QLabel("Los grupos Comps se resolverán junto con los paquetes seleccionados.")
        footer = FlowLayout(h_spacing=10, v_spacing=8)
        back = QPushButton("Volver al panel")
        back.clicked.connect(lambda: self._navigate("dashboard", validate=False))
        use = QPushButton("Aplicar selección al proyecto")
        use.setObjectName("primaryAction")
        use.clicked.connect(self.apply_custom_distro_selection)
        footer.addWidget(back)
        footer.addWidget(use)
        layout.addLayout(footer)

        add_page(
            self, "custom_distro", page,
            "Gestor de software", "Explorá, seleccioná y revisá el software de tu distribución.",
            "La disponibilidad y las dependencias se verifican con DNF5 y los repositorios habilitados.",
        )
        self._custom_pkg_worker = None
        self._custom_pkg_names = set()
        self._custom_groups = set()
        self._custom_local_rpm_paths = []
        self._custom_repositories = []
        self._custom_group_names = {}
        self._package_catalog = []
        self._project_type = str(
            getattr(self, "_project_type", "")
            or self.combo_project_type.currentData()
            or "kiosk"
        )
        self._catalog_requested = False
        self._dnf_available = DnfQuery().available()
        if not self._dnf_available:
            self.lbl_repos_status.setText(
                "No se encontró DNF5. Instalá dnf5 para consultar el catálogo de Fedora."
            )
            self._set_manager_status(
                "El gestor necesita DNF5 y repositorios configurados en el "
                "equipo anfitrión."
            )
            self.btn_pkg_search.setEnabled(False)
            self.btn_pkg_refresh.setEnabled(False)
            self.btn_dependency_preview.setEnabled(False)
        else:
            self._set_manager_status(
                "Catálogo sin cargar. Al abrir el gestor por primera vez se "
                "consulta DNF en segundo plano."
            )

    def _ensure_catalog_loaded(self):
        """Carga el catálogo la primera vez que se abre el gestor."""
        if not self._dnf_available or self._catalog_requested:
            return
        if self._custom_pkg_worker is not None and self._custom_pkg_worker.isRunning():
            return
        self._query_fedora_packages("")

    def _set_manager_status(self, text):
        """Mensajes propios del gestor; no reutiliza el estado global del asistente."""
        if hasattr(self, "lbl_manager_status"):
            self.lbl_manager_status.setText(text)
            self.lbl_manager_status.setToolTip(text)

    def _sync_manager_project_type(self, *_args):
        """Refleja en el gestor el perfil elegido en el paso 1."""
        if not hasattr(self, "combo_manager_project_type"):
            return
        key = self.combo_project_type.currentData()
        index = self.combo_manager_project_type.findData(key)
        if index >= 0 and self.combo_manager_project_type.currentIndex() != index:
            self.combo_manager_project_type.blockSignals(True)
            self.combo_manager_project_type.setCurrentIndex(index)
            self.combo_manager_project_type.blockSignals(False)
        self._update_project_description()

    def _on_manager_project_changed(self, *_args):
        """Aplica el perfil elegido en el gestor y lo refleja en el paso 1."""
        key = self.combo_manager_project_type.currentData() or "custom"
        self._project_type = key
        self._build_engine = get_project_template(key)["engine"]
        self._update_project_description()
        index = self.combo_project_type.findData(key)
        if index >= 0 and self.combo_project_type.currentIndex() != index:
            self.combo_project_type.setCurrentIndex(index)
        self._set_manager_status(
            "Perfil del proyecto actualizado. La modalidad se aplica también "
            "en el paso 1; podés revisarla antes de compilar."
        )

    def _update_project_description(self, *_args):
        key = self.combo_manager_project_type.currentData()
        try:
            template = get_project_template(key)
        except ValueError:
            self.lbl_project_description.setText("Seleccioná un tipo de proyecto.")
            return
        self.lbl_project_description.setText(
            f"{template['icon']}  {template['description']}\n"
            f"Categorías sugeridas: {', '.join(template['groups'])}."
        )
        self.lbl_project_description.setToolTip(
            f"{template['name']}: {template['description']}\n"
            f"Categorías sugeridas: {', '.join(template['groups'])}."
        )

    def apply_project_template(self):
        key = self.combo_manager_project_type.currentData() or "custom"
        template = get_project_template(key)
        merged = merge_packages(template["packages"], sorted(self._custom_pkg_names))
        self._custom_pkg_names = set(merged)
        self.list_fedora_selected.clear()
        self.list_fedora_selected.addItems(merged)
        self._project_type = key
        index = self.combo_project_type.findData(key)
        if index >= 0 and self.combo_project_type.currentIndex() != index:
            self.combo_project_type.setCurrentIndex(index)
        self._refresh_pending_table()
        self._set_manager_status(
            f"Perfil {template['name']} cargado: {len(merged)} paquetes sugeridos. "
            "Podés agregar o quitar paquetes antes de continuar."
        )

    # -- Consultas DNF -------------------------------------------------------

    def load_enabled_repositories(self):
        self._start_dnf("repositories")

    def load_fedora_groups(self):
        self._start_dnf("groups")

    def search_fedora_packages(self):
        try:
            query = normalize_search_query(self.custom_pkg_search.text())
        except SoftwareSelectionError as exc:
            QMessageBox.warning(self, "Búsqueda no válida", str(exc))
            self.custom_pkg_search.setFocus()
            return
        self._query_fedora_packages(query)

    def _query_fedora_packages(self, query):
        if self._start_dnf("packages", query):
            self._catalog_requested = True

    def _start_dnf(self, operation, query=""):
        if not self._dnf_available:
            QMessageBox.warning(
                self,
                "DNF no disponible",
                "No se encontró dnf. Instalá DNF en el equipo Fedora para "
                "consultar repositorios, grupos y paquetes.",
            )
            return False
        if self._custom_pkg_worker and self._custom_pkg_worker.isRunning():
            self._set_manager_status("Ya hay una consulta DNF en curso.")
            return False
        messages = {
            "repositories": "Consultando repositorios DNF habilitados…",
            "groups": "Consultando grupos comps disponibles…",
            "group_info": "Consultando el contenido del grupo…",
            "packages": "Buscando paquetes en los repositorios Fedora…",
            "preview": "DNF5 está resolviendo dependencias y simulando la transacción…",
        }
        self._set_manager_status(messages.get(operation, "Consultando DNF…"))
        self._set_dnf_busy(True)
        worker = DnfWorker(
            operation, query,
            packages=tuple(sorted(self._custom_pkg_names)) if operation == "preview" else (),
            groups=tuple(sorted(self._custom_groups)) if operation == "preview" else (),
        )
        self._custom_pkg_worker = worker
        worker.results.connect(self._dnf_results)
        worker.failed.connect(self._dnf_failed)
        worker.finished.connect(self._dnf_finished)
        worker.start()
        return True

    def _set_dnf_busy(self, busy):
        enabled = self._dnf_available and not busy
        for button in (
            self.btn_repos_query,
            self.btn_groups_load,
            self.btn_pkg_search,
            self.btn_pkg_refresh,
            self.btn_dependency_preview,
            self.btn_group_info,
        ):
            button.setEnabled(enabled)
        self.btn_group_add.setEnabled(
            enabled and self.combo_dnf_group.isEnabled() and self.combo_dnf_group.count() > 0
        )
        if not self._dnf_available:
            self.combo_dnf_group.setEnabled(False)

    def _dnf_finished(self):
        # Se conserva la referencia al hilo terminado; el próximo inicio la
        # reemplaza. Destruir el QThread dentro de su propia señal ``finished``
        # puede ser inseguro.
        self._set_dnf_busy(False)

    def _dnf_results(self, operation, payload):
        if operation == "repositories":
            self._show_repositories(payload)
        elif operation == "groups":
            self._show_groups(payload)
        elif operation == "group_info":
            self._display_group_info(payload)
        elif operation == "packages":
            self._show_fedora_packages(payload)
        elif operation == "preview":
            self._show_transaction_preview(payload)

    def _dnf_failed(self, operation, message):
        titles = {
            "repositories": "Repositorios DNF",
            "groups": "Grupos de paquetes",
            "group_info": "Contenido del grupo",
            "packages": "Consulta de paquetes",
            "preview": "Resolución de dependencias",
        }
        QMessageBox.warning(self, titles.get(operation, "Consulta DNF"), message)
        self._set_manager_status("No se pudo completar la consulta DNF.")

    def _show_repositories(self, repositories):
        self._custom_repositories = list(repositories)
        current = self.combo_repo_filter.currentData()
        self.combo_repo_filter.blockSignals(True)
        self.combo_repo_filter.clear()
        self.combo_repo_filter.addItem("Todos los repositorios", "")
        for repo in repositories:
            self.combo_repo_filter.addItem(f"{repo.id} — {repo.name}", repo.id)
        index = self.combo_repo_filter.findData(current)
        if index >= 0:
            self.combo_repo_filter.setCurrentIndex(index)
        self.combo_repo_filter.blockSignals(False)
        if not repositories:
            self.lbl_repos_status.setText(
                "DNF no informó repositorios habilitados. Revisá la configuración "
                "de repositorios del equipo."
            )
            self.lbl_repos_status.setToolTip("")
            return
        shown = ", ".join(repo.id for repo in repositories[:8])
        if len(repositories) > 8:
            shown += f" y {len(repositories) - 8} más"
        self.lbl_repos_status.setText(
            f"{len(repositories)} repositorios habilitados: {shown}."
        )
        self.lbl_repos_status.setToolTip(
            "\n".join(f"{repo.id} — {repo.name}" for repo in repositories)
        )
        self._set_manager_status(
            f"Repositorios habilitados consultados: {len(repositories)}."
        )

    def _show_groups(self, groups):
        self.combo_dnf_group.blockSignals(True)
        self.combo_dnf_group.clear()
        self._custom_group_names = {}
        for group in groups:
            label = f"{group.name} ({group.id})"
            if group.installed:
                label += " · instalado"
            self.combo_dnf_group.addItem(label, f"@{group.id}")
            self._custom_group_names[f"@{group.id}"] = group.name
        self.combo_dnf_group.blockSignals(False)
        has_groups = bool(groups) and self._dnf_available
        self.combo_dnf_group.setEnabled(has_groups)
        self.btn_group_add.setEnabled(has_groups)
        self.btn_group_info.setEnabled(has_groups)
        if groups:
            self._set_manager_status(
                f"DNF devolvió {len(groups)} grupos comps. Elegí uno y agregalo "
                "a tu distribución."
            )
        else:
            self._set_manager_status(
                "DNF no devolvió grupos comps. La lista de paquetes sigue disponible."
            )

    def _show_fedora_packages(self, packages):
        """Actualiza el catálogo tabular y conserva los datos completos para filtros."""
        self._package_catalog = list(packages)
        repositories = sorted({p.repository for p in packages if p.repository})
        current_repo = self.combo_repo_filter.currentData()
        self.combo_repo_filter.blockSignals(True)
        self.combo_repo_filter.clear()
        self.combo_repo_filter.addItem("Todos los repositorios", "")
        for repo in repositories:
            self.combo_repo_filter.addItem(repo, repo)
        idx = self.combo_repo_filter.findData(current_repo)
        if idx >= 0:
            self.combo_repo_filter.setCurrentIndex(idx)
        self.combo_repo_filter.blockSignals(False)
        self._filter_package_table()
        self.lbl_catalog_status.setText(f"{len(packages)} paquetes cargados")
        self._set_manager_status(
            f"Catálogo actualizado: {len(packages)} paquetes disponibles. "
            "Seleccioná filas y marcá los paquetes para instalar."
            + (" Refiná la búsqueda para consultar más resultados." if len(packages) >= 500 else "")
        )

    def _filter_package_table(self, *_args):
        """Aplica filtros locales sin volver a consultar repositorios."""
        if not hasattr(self, "table_fedora_available"):
            return
        query = self.custom_pkg_search.text().strip().casefold()
        repo = self.combo_repo_filter.currentData() or ""
        kind = self.combo_package_type.currentData() or "all"
        rows = []
        for package in self._package_catalog:
            searchable = f"{package.name} {package.summary}".casefold()
            if query and query not in searchable:
                continue
            if repo and package.repository != repo:
                continue
            name = package.name.casefold()
            if kind == "libs" and not any(
                token in name for token in ("lib", "-devel", "-libs")
            ):
                continue
            if kind == "apps" and any(
                token in name for token in ("lib", "-devel", "-libs")
            ):
                continue
            rows.append(package)
        self.table_fedora_available.setRowCount(len(rows))
        for row, package in enumerate(rows):
            values = (
                package.name,
                package.summary,
                package.version,
                getattr(package, "architecture", ""),
                package.repository,
                "Paquete RPM",
            )
            for col, value in enumerate(values):
                item = QTableWidgetItem(value or "")
                item.setData(Qt.ItemDataRole.UserRole, package.name)
                if col == 1:
                    item.setToolTip(value or "")
                self.table_fedora_available.setItem(row, col, item)
        self.lbl_catalog_status.setText(
            f"{len(rows)} de {len(self._package_catalog)} paquetes visibles"
        )
        if not rows and self._package_catalog:
            self.lbl_catalog_status.setToolTip(
                "Ningún paquete coincide con la búsqueda y los filtros actuales."
            )
        else:
            self.lbl_catalog_status.setToolTip("")

    def _show_package_detail(self):
        rows = self.table_fedora_available.selectionModel().selectedRows()
        if not rows:
            self.lbl_package_detail.setText("Seleccioná un paquete para consultar sus datos.")
            return
        item = self.table_fedora_available.item(rows[0].row(), 0)
        name = item.data(Qt.ItemDataRole.UserRole) if item else ""
        package = next((p for p in self._package_catalog if p.name == name), None)
        if package:
            self.lbl_package_detail.setText(
                f"<b>{html.escape(package.name)}</b> — "
                f"{html.escape(package.summary or 'Sin descripción')}<br>"
                f"Versión: {html.escape(package.version or 'No informada')} · "
                f"Arquitectura: "
                f"{html.escape(getattr(package, 'architecture', '') or 'No informada')} · "
                f"Repositorio: {html.escape(package.repository or 'No informado')} · "
                "Tipo: paquete RPM"
            )

    def _refresh_pending_table(self):
        self.table_fedora_pending.setRowCount(0)
        entries = [("Instalar", name) for name in sorted(self._custom_pkg_names)]
        entries += [("Grupo Comps", name) for name in sorted(self._custom_groups)]
        self.table_fedora_pending.setRowCount(len(entries))
        for row, (action, name) in enumerate(entries):
            self.table_fedora_pending.setItem(row, 0, QTableWidgetItem(action))
            self.table_fedora_pending.setItem(row, 1, QTableWidgetItem(name))
        self._update_custom_pkg_count()

    def preview_custom_transaction(self):
        """Pide al solver DNF5 una simulación sin aplicar cambios al anfitrión."""
        if not self._custom_pkg_names and not self._custom_groups:
            QMessageBox.information(
                self, "Selección vacía",
                "Agregá paquetes o grupos antes de resolver dependencias.",
            )
            return
        self._start_dnf("preview")

    def _show_transaction_preview(self, output):
        message = QMessageBox(self)
        message.setIcon(QMessageBox.Icon.Information)
        message.setWindowTitle("Simulación de transacción DNF5")
        message.setText(
            "DNF5 completó la simulación. Revisá la salida del solver antes "
            "de aplicar esta selección al proyecto."
        )
        message.setInformativeText(
            "La simulación usa los repositorios y el estado de paquetes del "
            "equipo anfitrión. No instala ni elimina paquetes. La construcción "
            "volverá a resolver dependencias dentro del entorno Fedora destino."
        )
        message.setDetailedText(str(output).strip() or "DNF5 no informó cambios.")
        message.setStandardButtons(QMessageBox.StandardButton.Ok)
        message.exec()
        self._set_manager_status(
            "Simulación DNF5 terminada. Los metapaquetes RPM se seleccionan "
            "como paquetes normales: sus Requires y dependencias transitivas "
            "los calcula DNF. La compilación volverá a resolver en el entorno destino."
        )

    def _show_selected_group_info(self):
        group = self.combo_dnf_group.currentData()
        if group:
            self._start_dnf("group_info", group)

    def _display_group_info(self, details):
        if details is None:
            QMessageBox.information(self, "Grupo Comps", "DNF no devolvió detalles para este grupo.")
            return
        sections = (
            ("Obligatorios", details.mandatory),
            ("Predeterminados", details.default),
            ("Opcionales", details.optional),
            ("Condicionales", details.conditional),
        )
        body = [details.name, details.description or "Sin descripción.", ""]
        for label, packages in sections:
            body.append(f"{label} ({len(packages)}):")
            body.extend(f"  • {name}" for name in packages)
            body.append("")
        QMessageBox.information(self, "Contenido del grupo Comps", "\n".join(body))

    # -- RPM locales ---------------------------------------------------------

    def _add_local_rpms(self):
        from core.software.local_rpm import LocalRPMError, inspect_local_rpm

        paths, _ = QFileDialog.getOpenFileNames(
            self, "Seleccionar paquetes RPM", "", "Paquetes RPM (*.rpm)"
        )
        if not paths:
            return
        allow_unsigned = bool(
            getattr(self, "check_allow_unsigned_rpms", None)
            and self.check_allow_unsigned_rpms.isChecked()
        )
        added, errors = [], []
        for path in paths:
            if path in self._custom_local_rpm_paths:
                continue
            try:
                info = inspect_local_rpm(path, allow_unsigned=allow_unsigned)
                self._custom_local_rpm_paths.append(info["path"])
                trust = "firma confiable" if info["trusted"] else "sin firma · digest OK"
                self.list_local_rpms.addItem(
                    f"{info['name']} {info['version']}-{info['release']} · {info['arch']} · {trust}"
                )
                added.append(info["name"])
            except LocalRPMError as exc:
                errors.append(f"{path}: {exc}")
        self._set_manager_status(
            "RPM agregados y verificados: " + (", ".join(added) if added else "ninguno")
        )
        if errors:
            QMessageBox.warning(self, "RPM rechazados", "\n\n".join(errors))

    def _remove_local_rpm(self):
        row = self.list_local_rpms.currentRow()
        if row < 0:
            return
        self.list_local_rpms.takeItem(row)
        if 0 <= row < len(self._custom_local_rpm_paths):
            self._custom_local_rpm_paths.pop(row)

    def _restore_local_rpm_selection(self, paths):
        """Restaura rutas guardadas y vuelve a inspeccionarlas para la GUI."""
        from core.software.local_rpm import LocalRPMError, inspect_local_rpm

        self._custom_local_rpm_paths = []
        self.list_local_rpms.clear()
        allow_unsigned = bool(
            getattr(self, "check_allow_unsigned_rpms", None)
            and self.check_allow_unsigned_rpms.isChecked()
        )
        for raw_path in paths or []:
            path = str(raw_path)
            self._custom_local_rpm_paths.append(path)
            try:
                info = inspect_local_rpm(path, allow_unsigned=allow_unsigned)
                trust = "firma confiable" if info["trusted"] else "sin firma · digest OK"
                label = f"{info['name']} {info['version']}-{info['release']} · {info['arch']} · {trust}"
            except (LocalRPMError, OSError):
                label = f"{path} · pendiente de verificación"
            self.list_local_rpms.addItem(label)

    # -- Selección -----------------------------------------------------------

    def _add_custom_packages(self):
        skipped = []
        rows = sorted({index.row() for index in self.table_fedora_available.selectionModel().selectedRows()})
        for row in rows:
            item = self.table_fedora_available.item(row, 0)
            name = item.data(Qt.ItemDataRole.UserRole) if item else None
            result = validate_package_names([name])
            if not result["allowed"]:
                skipped.append(str(name))
                continue
            self._custom_pkg_names.add(result["allowed"][0])
        self._refresh_pending_table()
        if rows:
            self._set_manager_status(
                f"{len(self._custom_pkg_names)} paquetes en la lista de cambios "
                "pendientes. La simulación DNF5 todavía no se ejecutó."
            )
        else:
            self._set_manager_status(
                "Seleccioná una o más filas del catálogo antes de marcar paquetes."
            )
        if skipped:
            QMessageBox.warning(self, "Paquetes omitidos", "No se agregaron paquetes inválidos o bloqueados: " + ", ".join(skipped))

    def _remove_custom_packages(self):
        rows = sorted({index.row() for index in self.table_fedora_pending.selectionModel().selectedRows()}, reverse=True)
        for row in rows:
            action = self.table_fedora_pending.item(row, 0)
            name = self.table_fedora_pending.item(row, 1)
            if action and name and action.text() == "Instalar":
                self._custom_pkg_names.discard(name.text())
            elif action and name and action.text().startswith("Grupo"):
                self._custom_groups.discard(name.text())
        self._refresh_pending_table()

    def _add_custom_group(self):
        entry = self.combo_dnf_group.currentData()
        if not entry:
            return
        try:
            normalized = normalize_group_entry(entry)
        except SoftwareSelectionError as exc:
            QMessageBox.warning(self, "Grupo no válido", str(exc))
            return
        if normalized not in self._custom_groups:
            self._custom_groups.add(normalized)
            self.list_groups_selected.addItem(normalized)
        self._refresh_pending_table()
        self._set_manager_status(
            f"Grupo {normalized} agregado a cambios pendientes. DNF5 resolverá "
            "sus paquetes al simular la transacción."
        )

    def _remove_custom_groups(self):
        for item in self.list_groups_selected.selectedItems():
            self._custom_groups.discard(item.text())
            self.list_groups_selected.takeItem(self.list_groups_selected.row(item))
        self._refresh_pending_table()

    def _update_custom_pkg_count(self):
        self.lbl_custom_pkg_count.setText(
            f"{len(self._custom_pkg_names)} paquetes · {len(self._custom_groups)} grupos seleccionados"
        )
        self.lbl_groups_status.setText(
            f"{len(self._custom_groups)} grupos Comps seleccionados. DNF5 resolverá sus paquetes y dependencias."
        )

    def apply_custom_distro_selection(self):
        self.txt_extra_packages.setText(" ".join(sorted(self._custom_pkg_names)))
        if hasattr(self, "txt_extra_groups"):
            self.txt_extra_groups.setText(" ".join(sorted(self._custom_groups)))
        key = self.combo_manager_project_type.currentData() or "custom"
        index = self.combo_project_type.findData(key)
        if index >= 0 and self.combo_project_type.currentIndex() != index:
            self.combo_project_type.setCurrentIndex(index)
        self._project_type = key
        self._custom_distro_mode = True
        # El gestor y el asistente comparten la selección. Volvemos al paso 3
        # para que el usuario continúe el flujo sin saltos inesperados al paso 1.
        self._navigate("step3", validate=False)
        if self._custom_groups:
            self._set_manager_status(
                "Selección aplicada. Los grupos Comps se instalarán con el "
                "motor Fedora Desktop; el motor Kiosco no los aplica."
            )
        else:
            self._set_manager_status(
                "Selección Fedora aplicada al paso 3. El perfil elegido define "
                "el motor de imagen; continuá con la configuración del asistente."
            )
        if key == "kiosk" and self._custom_groups:
            QMessageBox.warning(
                self,
                "Grupos no aplicables al motor Kiosco",
                "La selección incluye grupos Comps, pero el motor Kiosco no "
                "los aplica. Elegí un perfil Fedora Desktop en el gestor o en "
                "el paso 1 si querés incorporarlos.",
            )
