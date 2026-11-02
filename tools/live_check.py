"""Explicit live integration check; no accounts or game actions."""
from pathlib import Path
import json
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from skyhook_scout.api import Client
from skyhook_scout.core import active_connections

with tempfile.TemporaryDirectory() as folder:
    client = Client(folder)
    hooks = client.request("/skyhooks/raidable").data["skyhooks"]
    scout = client.request("", scout=True)
    assert hooks and active_connections(scout.data), "No active targets or connections; retry later."
    hook = hooks[0]
    metadata = client.metadata(hook)
    assert metadata["planet_type"] and metadata["region"]
    route = client.plan("Thera", hook["solar_system_id"], scout)
    assert route["systems"][-1] == hook["solar_system_id"]
    assert len(route["hops"]) == route["gates"] + route["wormholes"]
    report = {"target": metadata, "targets": len(hooks), "connections": len(active_connections(scout.data)),
              "total_jumps": len(route["hops"]), "gates": route["gates"], "wormholes": route["wormholes"]}
    print(json.dumps(report, indent=2))
    out = Path(__file__).resolve().parents[1] / "build/qa/live-check.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2))
