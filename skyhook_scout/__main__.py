import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import time


def main():
    parser = argparse.ArgumentParser(description="Skyhook Scout desktop app")
    parser.add_argument("--smoke-test", metavar="PNG", help="Render deterministic demo UI offscreen, verify filters, then exit")
    args = parser.parse_args()
    if args.smoke_test:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtCore import QStandardPaths, QTimer, Qt
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QFont, QFontDatabase
    from .ui import MainWindow
    app = QApplication(sys.argv[:1])
    app.setApplicationName("Skyhook Scout")
    app.setOrganizationName("SkyhookScout")
    app.setStyle("Fusion")
    font_path = Path(__file__).parent / "assets/Inter.ttf"
    if font_path.exists():
        QFontDatabase.addApplicationFont(str(font_path))
        app.setFont(QFont("Inter", 10))
    scratch = tempfile.TemporaryDirectory() if args.smoke_test else None
    cache = scratch.name if scratch else QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation)
    window = MainWindow(cache, demo=bool(args.smoke_test))
    window.show()
    if args.smoke_test:
        from .api import Snapshot
        from .core import describe_route
        from datetime import datetime, timezone
        def iso(delta):
            return datetime.fromtimestamp(time.time() + delta, timezone.utc).isoformat()
        def h(pid, sid, system, planet, kind, region, start=-1800):
            return {"planet_id": pid, "solar_system_id": sid, "system": system, "planet": planet,
                    "planet_type": kind, "region": region,
                    "theft_vulnerability": {"start": iso(start), "end": iso(4200)}}
        rows = [h(4001, 30000001, "XW-JHT", "XW-JHT I", "Lava", "Branch"),
                h(4002, 30000002, "EIDI-N", "EIDI-N VII", "Ice", "Branch"),
                h(4003, 30000003, "HED-GP", "HED-GP III", "Lava", "Catch", 1200)]
        hole = {"id":"demo", "completed": True, "signature_type": "wormhole", "expires_at": iso(10000),
                "out_system_id":31000005, "in_system_id":30000002, "out_signature":"ABC-123",
                "in_signature":"XYZ-456", "wh_type":"V898", "max_ship_size":"xlarge"}
        now = time.time()
        window.accept_snapshot({"rows":rows,"hooks":Snapshot({},now),"scout":Snapshot([hole],now),"errors":[],"complete":True})
        def check():
            try:
                assert window.proxy.rowCount() == 3
                window.region.setCurrentIndex(window.region.findData("Branch"))
                assert window.proxy.rowCount() == 2
                window.types.setCurrentIndex(window.types.findData("Ice"))
                assert window.proxy.rowCount() == 1
                window.planets.setCurrentIndex(window.planets.findData("XW-JHT I"))
                assert window.proxy.rowCount() == 0
                window.planets.setCurrentIndex(window.planets.findData("EIDI-N VII"))
                assert window.proxy.rowCount() == 1
                window.time_mode.setCurrentIndex(1)
                assert not window.model.system_time
                assert "UTC" in window.model.headerData(4, Qt.Orientation.Horizontal)
                window.time_mode.setCurrentIndex(0)
                assert window.model.system_time
                window.search.setText("no matching system")
                assert window.proxy.rowCount() == 0
                window.search.clear()
                assert window.proxy.rowCount() == 1
                window.region.setCurrentIndex(0)
                window.types.setCurrentIndex(0)
                window.planets.setCurrentIndex(0)
                original_size = window.size()
                for cycle in range(4):
                    for width, height in ((1114, 830), (1510, 800), (1050, 720), (1600, 900)):
                        window.resize(width, height)
                        for _ in range(4):
                            app.processEvents()
                        if window.compact_layout:
                            window.compact_tabs.setCurrentIndex(0)
                            app.processEvents()
                        assert window.targets_panel.isVisible(), "Targets hidden after resize"
                        assert window.table.isVisible() and not window.table.visibleRegion().isEmpty()
                        if window.compact_layout:
                            window.compact_tabs.setCurrentIndex(1)
                            app.processEvents()
                        else:
                            assert window.route_scroll.isVisible(), "Route hidden after resize"
                            assert all(size > 300 for size in window.splitter.sizes())
                window.resize(original_size)
                for _ in range(4):
                    app.processEvents()
                window.selected = rows[1]
                window.route = describe_route([31000005,30000002],[hole])
                window.route["names"] = {31000005:"Thera",30000002:"EIDI-N"}
                window.route_title.setText("EIDI-N")
                window.route_location.setText("EIDI-N VII · Ice · Branch")
                window.render_route()
                window.statusBar().showMessage("DEMO PREVIEW — synthetic test data; not live intel")
                target = Path(args.smoke_test).resolve()
                target.parent.mkdir(parents=True,exist_ok=True)
                window.grab().save(str(target))
                target.with_suffix(".json").write_text(json.dumps({"ok":True,"rows":3,"region_filter":True,"type_filter":True,"planet_filter":True,"system_time":True,"utc_toggle":True,"search":True,"route":True,"resize_round_trips":4}))
                app.exit(0)
            except Exception as exc:
                Path(args.smoke_test).with_suffix(".json").write_text(json.dumps({"ok":False,"error":str(exc)}))
                app.exit(1)
        QTimer.singleShot(500, check)
    code = app.exec()
    if scratch:
        scratch.cleanup()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
