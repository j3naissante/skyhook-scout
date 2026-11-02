"""Regression checks for small-window clipping. Offscreen; no network or screenshots."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
import tempfile
import time
from datetime import datetime, timezone
import unittest

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase, QFont
from PySide6.QtWidgets import QApplication
from skyhook_scout.ui import MainWindow
from skyhook_scout.api import Snapshot


class ResponsiveLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        QFontDatabase.addApplicationFont(str(Path(__file__).parents[1] / "skyhook_scout/assets/Inter.ttf"))
        cls.app.setFont(QFont("Inter", 10))
        cls.app.setStyle("Fusion")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.window = MainWindow(self.temp.name, demo=True)
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.close()
        self.app.processEvents()
        self.temp.cleanup()

    def settle(self, width, height):
        self.window.resize(width, height)
        for _ in range(4):
            self.app.processEvents()

    def load_targets(self, count=200):
        now = time.time()
        def iso(delta):
            return datetime.fromtimestamp(now + delta, timezone.utc).isoformat()
        rows = [{"planet_id": 40000000 + i, "solar_system_id": 30000000 + i,
                 "system": f"TEST-{i:03}", "planet": f"TEST-{i:03} XVIII",
                 "planet_type": "Ice" if i % 2 else "Lava",
                 "region": ["The Kalevala Expanse", "Vale of the Silent", "Perrigen Falls"][i % 3],
                 "theft_vulnerability": {"start": iso(-600), "end": iso(7200)}} for i in range(count)]
        self.window.accept_snapshot({"rows": rows, "hooks": Snapshot({}, now), "scout": Snapshot([], now),
                                     "errors": [], "complete": True})
        self.app.processEvents()

    def assert_targets_visible(self):
        self.assertTrue(self.window.targets_panel.isVisible(), "Target panel is hidden after resizing")
        self.assertTrue(self.window.table.isVisible(), "Target table is hidden after resizing")
        self.assertGreater(self.window.table.visibleRegion().boundingRect().width(), 500)
        self.assertGreater(self.window.table.visibleRegion().boundingRect().height(), 70)
        for control in (self.window.region, self.window.types, self.window.planets, self.window.search):
            self.assertTrue(control.isVisible())
            self.assertFalse(control.visibleRegion().isEmpty())
        point = self.window.targets_panel.mapTo(self.window.centralWidget(), self.window.targets_panel.rect().topLeft())
        panel_rect = self.window.targets_panel.rect().translated(point)
        self.assertTrue(self.window.centralWidget().rect().contains(panel_rect), "Targets extend outside the window")

    def test_loaded_targets_remain_visible_after_repeated_tab_and_size_changes(self):
        self.load_targets()
        for cycle in range(4):
            for width, height in [(1510, 940), (1114, 830), (1510, 800), (1050, 720), (1600, 900)]:
                with self.subTest(cycle=cycle, width=width, height=height):
                    self.settle(width, height)
                    if self.window.compact_layout:
                        self.window.compact_tabs.setCurrentIndex(0)
                        self.app.processEvents()
                    self.assert_targets_visible()
                    self.assertEqual(self.window.proxy.rowCount(), 200)
                    self.window.table.scrollToBottom()
                    self.app.processEvents()
                    self.assertGreater(self.window.table.verticalScrollBar().value(), 0)
                    if self.window.compact_layout:
                        self.window.compact_tabs.setCurrentIndex(1)
                        self.app.processEvents()
                        self.assertTrue(self.window.route_scroll.isVisible())
                    else:
                        self.assertTrue(self.window.route_scroll.isVisible(), "Route panel is hidden in wide mode")
                        self.assertTrue(all(size > 300 for size in self.window.splitter.sizes()))

    def test_compact_table_uses_full_width_and_retains_all_columns(self):
        self.settle(1114, 830)
        self.assertTrue(self.window.compact_layout)
        self.assertEqual(self.window.compact_tabs.count(), 2)
        self.assertEqual(self.window.workspace.currentWidget(), self.window.compact_tabs)
        self.assertEqual(self.window.table.model().columnCount(), 8)
        self.assertGreater(self.window.table.viewport().width(), 900)
        self.assertLessEqual(self.window.table.horizontalHeader().length(), self.window.table.viewport().width())

    def test_route_scrolls_instead_of_squeezing_cards_at_minimum_size(self):
        self.settle(1050, 720)
        self.window.compact_tabs.setCurrentIndex(1)
        self.app.processEvents()
        for label in (self.window.metric_total, self.window.metric_gates, self.window.metric_wh):
            self.assertGreaterEqual(label.height(), 40)
            self.assertGreaterEqual(label.parentWidget().height(), 86)
        self.assertGreaterEqual(self.window.itinerary.height(), 180)
        self.assertGreater(self.window.route_scroll.verticalScrollBar().maximum(), 0)
        self.window.route_scroll.verticalScrollBar().setValue(self.window.route_scroll.verticalScrollBar().maximum())
        self.app.processEvents()
        self.assertTrue(self.window.route_scroll.viewport().rect().intersects(
            self.window.estimate.rect().translated(self.window.estimate.mapTo(self.window.route_scroll.viewport(), self.window.estimate.rect().topLeft()))))

    def test_wide_compact_wide_round_trip_preserves_widgets(self):
        for width in (1510, 1114, 1510):
            self.settle(width, 830)
        self.assertFalse(self.window.compact_layout)
        self.assertEqual(self.window.splitter.count(), 2)
        self.assertEqual(self.window.compact_tabs.count(), 0)
        self.assertEqual(self.window.splitter.widget(0), self.window.targets_panel)
        self.assertEqual(self.window.route_scroll.widget(), self.window.route_panel)
        self.assert_targets_visible()
        self.assertTrue(self.window.route_scroll.isVisible())

    def test_boundary_resizes_and_refresh_keep_table_visible(self):
        for cycle in range(3):
            for width in (1379, 1380, 1381, 1378, 1510):
                self.settle(width, 780)
                self.load_targets(200)
                if self.window.compact_layout:
                    self.window.compact_tabs.setCurrentIndex(0)
                    self.app.processEvents()
                self.assert_targets_visible()
                self.assertEqual(self.window.proxy.rowCount(), 200)
                if self.window.compact_layout:
                    self.window.compact_tabs.setCurrentIndex(1)
                    self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
