"""Qt desktop UI; all API work runs outside the event thread."""
from datetime import datetime, timezone
from html import escape
from pathlib import Path
import time

from PySide6.QtCore import (QAbstractTableModel, QModelIndex, QObject, QRunnable,
    QSettings, QSortFilterProxyModel, Qt, QThreadPool, QTimer, QUrl, Signal, Slot)
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QPainter, QPixmap, QPen, QFont
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QButtonGroup, QComboBox,
    QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow, QMessageBox,
    QPushButton, QSizePolicy, QSpinBox, QSplitter, QTableView, QTextBrowser, QVBoxLayout, QWidget,
    QLayout, QScrollArea, QStackedWidget, QTabWidget)

from . import __version__
from .api import Client, Snapshot
from .core import (HUBS, active_connections, duration, estimate_raid, matches,
                   status, timestamp, display_time, time_zone_label)


def make_icon():
    image = QPixmap(128, 128)
    image.fill(QColor("#0b171c"))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor("#69e4bf"), 5))
    painter.drawEllipse(27, 27, 74, 74)
    for a, b, c, d in [(64, 12, 64, 45), (64, 83, 64, 116), (12, 64, 45, 64), (83, 64, 116, 64)]:
        painter.drawLine(a, b, c, d)
    painter.setBrush(QColor("#69e4bf"))
    painter.drawEllipse(58, 58, 12, 12)
    painter.end()
    return QIcon(image)


class WorkerSignals(QObject):
    result = Signal(object)
    failed = Signal(str)
    progress = Signal(object, str)
    finished = Signal()


class Worker(QRunnable):
    def __init__(self, function):
        super().__init__()
        self.function, self.signals = function, WorkerSignals()

    @Slot()
    def run(self):
        try:
            self.signals.result.emit(self.function(self.signals.progress.emit))
        except Exception as exc:
            self.signals.failed.emit(str(exc))
        finally:
            self.signals.finished.emit()


class TargetsModel(QAbstractTableModel):
    headers = ["SYSTEM", "PLANET", "TYPE", "REGION", "OPENS · UTC", "CLOSES · UTC", "STATUS", "TIME LEFT"]

    def __init__(self):
        super().__init__()
        self.rows = []
        self.system_time = True

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.headers)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            if section in (4, 5):
                zone = "LOCAL" if self.system_time else "UTC"
                return ("OPENS" if section == 4 else "CLOSES") + " · " + zone
            return self.headers[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        h, c = self.rows[index.row()], index.column()
        start, end = timestamp(h["theft_vulnerability"]["start"]), timestamp(h["theft_vulnerability"]["end"])
        state, now = status(h), time.time()
        if role == Qt.ItemDataRole.DisplayRole:
            return [h.get("system", str(h["solar_system_id"])), h.get("planet", f"Planet {h['planet_id']}"),
                    h.get("planet_type", "—"), h.get("region", "—"), display_time(start, self.system_time, False),
                    display_time(end, self.system_time, False), "● " + state,
                    ("in " + duration(start - now)) if state == "Upcoming" else duration(end - now)][c]
        if role == Qt.ItemDataRole.UserRole:
            if c in (4, 5):
                return start if c == 4 else end
            if c == 7:
                return (start if state == "Upcoming" else end) - now
            return str(self.data(index)).casefold()
        if role == Qt.ItemDataRole.ForegroundRole:
            if c == 6:
                return QColor("#69e4bf" if state == "Open now" else "#ffb375")
            if c == 2:
                return QColor("#90d6fb" if h.get("planet_type") == "Ice" else "#ffb375")
            if c in (3, 4, 5):
                return QColor("#a0b4bd")
        if role == Qt.ItemDataRole.ToolTipRole:
            location = " · ".join(h.get(key, "—") for key in ("system", "planet", "planet_type", "region"))
            return (f"{location}\nSystem ID: {h['solar_system_id']}\nPlanet ID: {h['planet_id']}\n"
                    f"Opens: {h['theft_vulnerability']['start']}\nCloses: {h['theft_vulnerability']['end']}\n"
                    "Click to calculate a route. Source timestamps above are UTC; columns follow your time setting.")
        return None

    def replace(self, rows):
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def tick(self):
        if self.rows:
            self.dataChanged.emit(self.index(0, 6), self.index(len(self.rows) - 1, 7))


class TargetsProxy(QSortFilterProxyModel):
    def __init__(self):
        super().__init__()
        self.query = self.region = self.planet_type = self.planet = ""
        self.window = "All windows"
        self.setSortRole(Qt.ItemDataRole.UserRole)
        self.setDynamicSortFilter(True)

    def filterAcceptsRow(self, row, parent):
        return matches(self.sourceModel().rows[row], self.query, self.region, self.planet_type, self.window, planet=self.planet)


class MainWindow(QMainWindow):
    def __init__(self, cache_dir, demo=False):
        super().__init__()
        self.demo = demo
        self.client = Client(cache_dir)
        self.settings = QSettings("SkyhookScout", "SkyhookScout")
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(3)
        self.tasks = set()
        self.refreshing = False
        self.scout = Snapshot([], 0)
        self.hook_snapshot = Snapshot({}, 0)
        self.selected = None
        self.route = None
        self.route_generation = 0
        self.last_errors = []
        self.compact_layout = None
        self.setWindowTitle(f"Skyhook Scout {__version__}")
        self.setWindowIcon(make_icon())
        self.resize(1510, 940)
        self.setMinimumSize(1050, 720)
        assets = Path(__file__).parent / "assets"
        self.setStyleSheet((assets / "theme.qss").read_text(encoding="utf-8").replace("@ASSET_DIR@", assets.as_posix()))
        self.build_ui()
        self.update_responsive_layout()
        self.tick_timer = QTimer(self)
        self.tick_timer.timeout.connect(self.tick)
        self.tick_timer.start(1000)
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self.refresh)
        if not demo:
            self.refresh_timer.start(300000)
            QTimer.singleShot(100, self.refresh)
        self.tick()

    def label(self, text, name=None):
        label = QLabel(text)
        if name:
            label.setObjectName(name)
        return label

    def button(self, text, callback, primary=False):
        button = QPushButton(text)
        button.clicked.connect(callback)
        if primary:
            button.setObjectName("Primary")
        return button

    def stat(self, title, subtitle, layout):
        panel = QFrame()
        panel.setObjectName("Stat")
        panel.setMinimumHeight(108 if subtitle else 86)
        box = QVBoxLayout(panel)
        box.setContentsMargins(18, 15, 18, 15) if subtitle else box.setContentsMargins(12, 9, 12, 9)
        box.addWidget(self.label(title, "StatTitle"))
        value = self.label("—", "StatValue")
        value.setMinimumHeight(40)
        box.addWidget(value)
        if subtitle:
            box.addWidget(self.label(subtitle, "Muted"))
        layout.addWidget(panel, 1)
        return value

    def build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(28, 22, 28, 16)
        root.setSpacing(16)
        header = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(make_icon().pixmap(28, 28))
        header.addWidget(logo)
        header.addWidget(self.label("SKYHOOK SCOUT", "Brand"))
        header.addStretch()
        header.addWidget(self.button("EVE Scout ↗", lambda: QDesktopServices.openUrl(QUrl("https://www.eve-scout.com/#/map"))))
        header.addWidget(self.button("About", self.about))
        self.time_mode = QComboBox()
        self.time_mode.addItem("System time (" + time_zone_label() + ")", True)
        self.time_mode.addItem("EVE time (UTC)", False)
        self.time_mode.setToolTip("Time display: follow your computer's timezone or EVE time (UTC).")
        self.time_mode.setCurrentIndex(0 if self.settings.value("system_time", True, type=bool) else 1)
        header.addWidget(self.time_mode)
        self.clock = self.label("", "Muted")
        header.addWidget(self.clock)
        root.addLayout(header)
        hero = QHBoxLayout()
        titles = QVBoxLayout()
        titles.addWidget(self.label("NEW EDEN / RAID INTELLIGENCE", "Eyebrow"))
        self.hero_heading = self.label("Find your next way in.", "Heading")
        self.hero_description = self.label("Live theft windows. Reported wormholes. A route to the target.", "Muted")
        titles.addWidget(self.hero_heading)
        titles.addWidget(self.hero_description)
        hero.addLayout(titles)
        hero.addStretch()
        self.refresh_button = self.button("↻  Refresh intel", self.refresh, True)
        hero.addWidget(self.refresh_button)
        root.addLayout(hero)
        stats = QHBoxLayout()
        self.stat_open = self.stat("RAIDABLE NOW", "Active theft windows", stats)
        self.stat_soon = self.stat("OPENING SOON", "Published upcoming windows", stats)
        self.stat_holes = self.stat("SCOUT CONNECTIONS", "Unexpired known-space exits", stats)
        self.stat_shown = self.stat("MATCHING TARGETS", "Your current filters", stats)
        root.addLayout(stats)
        self.warning = self.label("", "Warning")
        self.warning.setWordWrap(True)
        self.warning.hide()
        root.addWidget(self.warning)
        departure = QHBoxLayout()
        departure.addWidget(self.label("DEPARTURE", "Muted"))
        self.origin = QComboBox()
        self.origin.setEditable(True)
        self.origin.addItems(["Thera", "Turnur"])
        self.origin.setCurrentText(self.settings.value("origin", "Thera"))
        self.origin.setMinimumWidth(160)
        self.origin.setToolTip("Thera, Turnur, or type any solar system name (e.g. Jita).")
        departure.addWidget(self.origin)
        departure.addSpacing(14)
        departure.addWidget(self.label("MIN. HOLE SIZE", "Muted"))
        self.ship = QComboBox()
        for text, size in [("Any / inspect route", 0), ("Small or larger", 1), ("Medium or larger", 2),
                           ("Large or larger", 3), ("Extra-large or larger", 4), ("Capital", 5)]:
            self.ship.addItem(text, size)
        departure.addWidget(self.ship)
        departure.addWidget(self.button("Recalculate route", self.plot_selected))
        departure.addStretch()
        departure.addWidget(self.label("Shortest routes · includes lowsec & nullsec", "Muted"))
        root.addLayout(departure)
        self.workspace = QStackedWidget()
        splitter = self.splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        self.compact_tabs = QTabWidget()
        self.workspace.addWidget(splitter)
        self.workspace.addWidget(self.compact_tabs)
        root.addWidget(self.workspace, 1)
        targets = QFrame()
        self.targets_panel = targets
        targets.setObjectName("Panel")
        target_box = QVBoxLayout(targets)
        target_box.setContentsMargins(15, 15, 15, 5)
        target_box.setSpacing(12)
        target_header = QHBoxLayout()
        target_header.addWidget(self.label("Target windows", "Section"))
        target_header.addStretch()
        self.target_hint = self.label("CLICK A TARGET TO PLOT A ROUTE  ↗", "Muted")
        target_header.addWidget(self.target_hint)
        target_box.addLayout(target_header)
        filters = QHBoxLayout()
        self.tabs = QButtonGroup(self)
        for i, text in enumerate(["All windows", "Open now", "Upcoming"]):
            b = QPushButton(text)
            b.setObjectName("Tab")
            b.setCheckable(True)
            b.setChecked(i == 0)
            self.tabs.addButton(b)
            b.clicked.connect(self.apply_filters)
            filters.addWidget(b)
        filters.addStretch()
        target_box.addLayout(filters)
        filters2 = QHBoxLayout()
        self.region = QComboBox()
        self.region.addItem("All regions", "")
        self.region.setMinimumWidth(150)
        self.region.setToolTip("Filter by region")
        self.types = QComboBox()
        self.types.addItem("All planet types", "")
        self.types.setToolTip("Filter by planet type")
        self.planets = QComboBox()
        self.planets.addItem("All planets", "")
        self.planets.setToolTip("Filter by a specific planet")
        self.planets.setMinimumWidth(165)
        self.planets.setMaximumWidth(240)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search system, planet, region…")
        self.search.setClearButtonEnabled(True)
        filters2.addWidget(self.region)
        filters2.addWidget(self.types)
        filters2.addWidget(self.planets)
        filters2.addWidget(self.search, 1)
        target_box.addLayout(filters2)
        for combo in (self.region, self.types, self.planets):
            combo.currentIndexChanged.connect(self.apply_filters)
        self.search.textChanged.connect(self.apply_filters)
        self.model = TargetsModel()
        self.proxy = TargetsProxy()
        self.proxy.setSourceModel(self.model)
        self.model.system_time = self.time_mode.currentData()
        self.time_mode.currentIndexChanged.connect(self.time_setting_changed)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(4, Qt.SortOrder.AscendingOrder)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(46)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for i, width in enumerate([100, 145, 80, 140, 115, 115, 115, 100]):
            self.table.setColumnWidth(i, width)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.selectionModel().currentRowChanged.connect(self.select_row)
        target_box.addWidget(self.table, 1)
        self.empty = self.label("Connecting to public APIs…", "Muted")
        self.empty.setWordWrap(True)
        target_box.addWidget(self.empty)
        splitter.addWidget(targets)
        panel = QFrame()
        self.route_panel = panel
        panel.setObjectName("Panel")
        panel_box = QVBoxLayout(panel)
        panel_box.setContentsMargins(16, 18, 16, 18)
        panel_box.setSpacing(12)
        panel_box.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        panel_box.addWidget(self.label("ROUTE PLANNER / SCOUT LINK", "Eyebrow"))
        self.route_title = self.label("A target. A way in.", "RouteTitle")
        panel_box.addWidget(self.route_title)
        self.route_location = self.label("Select a skyhook to calculate its route.", "Muted")
        self.route_location.setWordWrap(True)
        panel_box.addWidget(self.route_location)
        metric_line = QHBoxLayout()
        self.metric_total = self.stat("TOTAL JUMPS", "", metric_line)
        self.metric_gates = self.stat("GATES", "", metric_line)
        self.metric_wh = self.stat("WORMHOLES", "", metric_line)
        panel_box.addLayout(metric_line)
        self.itinerary = QTextBrowser()
        self.itinerary.setMinimumHeight(180)
        self.itinerary.setHtml('<p style="color:#91a6af;line-height:1.7">Your route will appear here, with separate gate and wormhole counts, signatures, reported size limits and expiry.</p>')
        panel_box.addWidget(self.itinerary, 1)
        actions = QHBoxLayout()
        self.copy_button = self.button("Copy route", self.copy_route)
        self.copy_button.setEnabled(False)
        actions.addWidget(self.copy_button)
        actions.addWidget(self.button("Scout map ↗", lambda: QDesktopServices.openUrl(QUrl("https://www.eve-scout.com/#/map"))))
        panel_box.addLayout(actions)
        panel_box.addWidget(self.label("RAID FEASIBILITY / ESTIMATE", "Eyebrow"))
        estimate_controls = QHBoxLayout()
        self.seconds, self.raid, self.buffer = QSpinBox(), QSpinBox(), QSpinBox()
        for control, label, default, low, high in [(self.seconds, "SEC / JUMP", 45, 1, 600),
                                                  (self.raid, "RAID MIN", 10, 1, 120),
                                                  (self.buffer, "BUFFER MIN", 3, 0, 120)]:
            column = QVBoxLayout()
            column.addWidget(self.label(label, "Muted"))
            control.setRange(low, high)
            control.setValue(default)
            control.valueChanged.connect(self.update_estimate)
            column.addWidget(control)
            estimate_controls.addLayout(column)
        panel_box.addLayout(estimate_controls)
        self.estimate = self.label("Select a target to estimate arrival.", "Estimate")
        self.estimate.setWordWrap(True)
        panel_box.addWidget(self.estimate)
        foot = self.label("Confirm hole mass, signatures and ship eligibility in game.\nA theft window does not indicate available loot.", "Footer")
        foot.setWordWrap(True)
        panel_box.addWidget(foot)
        self.route_scroll = QScrollArea()
        self.route_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.route_scroll.setWidgetResizable(True)
        self.route_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.route_scroll.setMinimumWidth(380)
        self.route_scroll.setMaximumWidth(510)
        self.route_scroll.setWidget(panel)
        splitter.addWidget(self.route_scroll)
        splitter.setSizes([1000, 395])
        self.footer = self.label("", "Footer")
        root.addWidget(self.footer)
        self.statusBar().showMessage("Ready")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "workspace"):
            self.update_responsive_layout()

    def update_responsive_layout(self):
        compact = self.width() < 1380
        if compact == self.compact_layout:
            return
        self.compact_layout = compact
        self.hero_heading.setVisible(not compact)
        self.hero_description.setVisible(not compact)
        self.target_hint.setText("SELECT A TARGET, THEN VIEW ITS ROUTE" if compact else "CLICK A TARGET TO PLOT A ROUTE  ↗")
        if compact:
            self.route_scroll.setMaximumWidth(16777215)
            self.compact_tabs.addTab(self.targets_panel, "Targets")
            self.compact_tabs.addTab(self.route_scroll, "Route")
            self.workspace.setCurrentWidget(self.compact_tabs)
            self.compact_tabs.setCurrentIndex(0)
        else:
            while self.compact_tabs.count():
                self.compact_tabs.removeTab(0)
            self.splitter.addWidget(self.targets_panel)
            self.splitter.addWidget(self.route_scroll)
            self.route_scroll.setMaximumWidth(510)
            self.workspace.setCurrentWidget(self.splitter)
            # Removing a page from QTabWidget hides it. Reparenting into the
            # splitter does not undo that explicit hidden state.
            self.targets_panel.show()
            self.route_scroll.show()
            self.splitter.setSizes([1000, 395])

    def run_task(self, function, success, failed, progress=None):
        worker = Worker(function)
        self.tasks.add(worker)
        worker.signals.result.connect(success)
        worker.signals.failed.connect(failed)
        if progress:
            worker.signals.progress.connect(progress)
        worker.signals.finished.connect(lambda: self.tasks.discard(worker))
        self.pool.start(worker)

    def refresh(self):
        if self.refreshing or self.demo:
            return
        self.refreshing = True
        self.refresh_button.setEnabled(False)
        self.refresh_button.setText("Fetching intel…")
        self.statusBar().showMessage("Fetching public ESI and Scout data…")
        self.run_task(lambda progress: self.client.refresh(progress), self.refreshed,
                      self.refresh_failed, self.refresh_progress)

    def refresh_progress(self, data, message):
        self.accept_snapshot(data)
        self.statusBar().showMessage(message)

    def refreshed(self, data):
        self.accept_snapshot(data)
        self.refreshing = False
        self.refresh_button.setEnabled(True)
        self.refresh_button.setText("↻  Refresh intel")
        self.statusBar().showMessage("Intel updated. Select a target to calculate its route.")

    def refresh_failed(self, message):
        self.refreshing = False
        self.refresh_button.setEnabled(True)
        self.refresh_button.setText("↻  Refresh intel")
        self.warning.setText("Refresh failed: " + message + ". Previous data may be stale.")
        self.warning.show()
        self.statusBar().showMessage("Refresh failed")

    def accept_snapshot(self, data):
        selected_id = self.selected["planet_id"] if self.selected else None
        self.scout, self.hook_snapshot = data["scout"], data["hooks"]
        self.last_errors = data["errors"]
        self.table.selectionModel().blockSignals(True)
        self.model.replace(data["rows"])
        self.populate(self.region, "All regions", "region")
        self.populate(self.types, "All planet types", "planet_type")
        self.populate(self.planets, "All planets", "planet")
        self.apply_filters()
        if selected_id:
            self.selected = next((h for h in self.model.rows if h["planet_id"] == selected_id), self.selected)
            for row in range(self.proxy.rowCount()):
                source = self.proxy.mapToSource(self.proxy.index(row, 0))
                if self.model.rows[source.row()]["planet_id"] == selected_id:
                    self.table.setCurrentIndex(self.proxy.index(row, 0))
                    break
        self.table.selectionModel().blockSignals(False)
        self.warning.setText("\n".join(self.last_errors))
        self.warning.setVisible(bool(self.last_errors))
        self.tick()

    def populate(self, combo, default, key):
        value = combo.currentData() or ""
        names = sorted({h[key] for h in self.model.rows if h.get(key)})
        if value and value not in names:
            names.append(value)
            names.sort()
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(default, "")
        for name in names:
            combo.addItem(name, name)
        combo.setCurrentIndex(max(0, combo.findData(value)))
        combo.blockSignals(False)

    def apply_filters(self, *_):
        if not hasattr(self, "proxy"):
            return
        self.proxy.query = self.search.text().strip()
        self.proxy.region = self.region.currentData() or ""
        self.proxy.planet_type = self.types.currentData() or ""
        self.proxy.planet = self.planets.currentData() or ""
        self.proxy.window = self.tabs.checkedButton().text()
        self.proxy.invalidateFilter()
        count = self.proxy.rowCount()
        self.stat_shown.setText(str(count))
        self.empty.setText("No targets match these filters." if not count else f"{count} targets · Click a row to plot a route · Click a column heading to sort")

    def select_row(self, current, previous):
        if current.isValid():
            source = self.proxy.mapToSource(current)
            self.selected = self.model.rows[source.row()]
            self.plot_selected()
            if self.compact_layout:
                self.compact_tabs.setCurrentIndex(1)

    def plot_selected(self):
        if not self.selected:
            return
        self.route_generation += 1
        generation = self.route_generation
        self.route = None
        self.copy_button.setEnabled(False)
        self.metric_total.setText("—")
        self.metric_gates.setText("—")
        self.metric_wh.setText("—")
        target = dict(self.selected)
        origin = self.origin.currentText().strip()
        if not self.demo:
            self.settings.setValue("origin", origin)
        self.route_title.setText(target.get("system", str(target["solar_system_id"])))
        self.route_location.setText(" · ".join(target.get(key, "Loading…") for key in ("planet", "planet_type", "region")))
        self.itinerary.setHtml('<p style="color:#69e4bf">Calculating the shortest route…</p>')
        self.estimate.setText("Calculating route…")
        def success(result):
            if generation == self.route_generation:
                self.route = result
                self.render_route()
        def failure(message):
            if generation == self.route_generation:
                self.itinerary.setHtml('<p style="color:#ffb375">' + escape(message) + '</p><p style="color:#93a8b2">Try another departure system or hole-size filter.</p>')
                self.estimate.setText("No route available.")
        if self.demo:
            return
        self.run_task(lambda _: self.client.plan(origin, target["solar_system_id"], self.scout, self.ship.currentData()), success, failure)

    def render_route(self):
        r = self.route
        if not r:
            return
        self.metric_total.setText(str(len(r["hops"])))
        self.metric_gates.setText(str(r["gates"]))
        self.metric_wh.setText(str(r["wormholes"]))
        names = r["names"]
        html = []
        for i, system in enumerate(r["systems"]):
            hole = r["hops"][i - 1]["hole"] if i else None
            color = "#69e4bf" if hole else "#91a8b2"
            if hole:
                # Show signatures in the actual direction of travel.
                forward = r["hops"][i - 1]["from"] == int(hole["out_system_id"])
                source_sig, dest_sig = (hole.get("out_signature", "?"), hole.get("in_signature", "?"))
                if not forward:
                    source_sig, dest_sig = dest_sig, source_sig
                text = (f"WORMHOLE · {source_sig} → {dest_sig}<br>"
                        f"{hole.get('wh_type', '?')} · max {hole.get('max_ship_size', '?')}<br>"
                        f"Reported expiry {self.format_time(timestamp(hole['expires_at']))}")
                text = escape(text).replace("&lt;br&gt;", "<br>")
            else:
                text = "DEPARTURE" if i == 0 else "STARGATE"
            if i == len(r["systems"]) - 1:
                text += " · TARGET SYSTEM"
            html.append(f'<div style="margin:0 0 18px 2px"><span style="color:{color}">●</span> '
                        f'<b style="color:#e1edf1">{escape(names.get(system, str(system)))}</b><br>'
                        f'<span style="font-size:10px;color:{color}">{text}</span></div>')
        self.itinerary.setHtml("".join(html))
        self.copy_button.setEnabled(True)
        self.update_estimate()

    def update_estimate(self, *_):
        if not self.route or not self.selected:
            return
        if any(h["hole"] and timestamp(h["hole"]["expires_at"]) <= time.time() for h in self.route["hops"]):
            self.estimate.setText("A wormhole on this route has passed its reported expiry. Recalculate the route.")
            self.estimate.setStyleSheet("color:#ffb375")
            return
        travel, feasible = estimate_raid(len(self.route["hops"]), self.selected,
                                        self.seconds.value(), self.raid.value(), self.buffer.value())
        if time.time() - self.scout.checked > 900:
            text = "Scout intel is over 15 minutes old. Refresh before using this route."
            feasible = False
        elif not any(h["planet_id"] == self.selected["planet_id"] for h in self.model.rows):
            text = "This target is no longer in the current published list. Refresh before travelling."
            feasible = False
        else:
            text = (f"Estimated travel {duration(travel)}. " + ("Enough time with these assumptions." if feasible else "Too late with these assumptions.")
                    + f" Closes {self.format_time(timestamp(self.selected['theft_vulnerability']['end']))}.")
        self.estimate.setText(text)
        self.estimate.setStyleSheet("color:" + ("#69e4bf" if feasible else "#ffb375"))

    def copy_route(self):
        if self.route:
            QApplication.clipboard().setText(" → ".join(self.route["names"].get(s, str(s)) for s in self.route["systems"]))
            self.statusBar().showMessage("Route copied to clipboard", 5000)

    def tick(self):
        now = time.time()
        system_time = self.time_mode.currentData()
        moment = datetime.now().astimezone() if system_time else datetime.now(timezone.utc)
        self.clock.setText(moment.strftime("%H:%M:%S ") + time_zone_label(system_time))
        self.time_mode.setItemText(0, "System time (" + time_zone_label() + ")")
        self.footer.setText("Official EVE ESI · Wormhole intel: EVE Scout / Signal Cartel · Auto-refresh 5 min · Times: "
                            + ("system timezone (" + time_zone_label() + ")" if system_time else "EVE / UTC"))
        self.model.tick()
        self.proxy.invalidateFilter()
        self.stat_open.setText(str(sum(status(h, now) == "Open now" for h in self.model.rows)))
        self.stat_soon.setText(str(sum(status(h, now) == "Upcoming" for h in self.model.rows)))
        self.stat_holes.setText(str(len(active_connections(self.scout.data, now=now))))
        self.stat_shown.setText(str(self.proxy.rowCount()))
        self.update_estimate()
        if self.hook_snapshot.checked:
            source = "CACHED / STALE" if self.hook_snapshot.stale else "ESI"
            self.statusBar().showMessage(f"{source} checked {self.format_time(self.hook_snapshot.checked)} · Scout checked "
                + (self.format_time(self.scout.checked) if self.scout.checked else "unavailable")
                + (" · Loading location names…" if self.refreshing else " · Auto-refresh every 5 minutes"))

    def format_time(self, value):
        return display_time(value, self.time_mode.currentData())

    def time_setting_changed(self, *_):
        system_time = self.time_mode.currentData()
        if not self.demo:
            self.settings.setValue("system_time", system_time)
        self.model.system_time = system_time
        self.model.headerDataChanged.emit(Qt.Orientation.Horizontal, 4, 5)
        if self.model.rows:
            self.model.dataChanged.emit(self.model.index(0, 4), self.model.index(len(self.model.rows) - 1, 5))
        self.render_route()
        self.tick()

    def about(self):
        QMessageBox.about(self, "About Skyhook Scout", f"<b>Skyhook Scout {__version__}</b><p>MIT-licensed source. No login, tracking or app server.</p>"
            "<p>Official EVE ESI data; wormhole reports by EVE Scout / Signal Cartel. Independent fan tool, not endorsed by the game publisher.</p>"
            "<p>Routes use standard gates and completed, unexpired known-space Scout connections. Unreported wormhole chains and private bridges are excluded. "
            "Size filters use reported limits; confirm your ship and remaining mass in game. Loot quantities are not provided.</p>"
            "<p>PySide6 / Qt are distributed under their own licenses; see THIRD_PARTY_NOTICES.md and licenses/ in the Windows package.</p>")

    def closeEvent(self, event):
        if self.tasks:
            self.client.cancelled.set()
            self.statusBar().showMessage("Finishing background requests before closing…")
            self.hide()
            # Keep QObjects alive until their tasks finish; never destroy a running pool.
            self.pool.waitForDone()
        event.accept()
