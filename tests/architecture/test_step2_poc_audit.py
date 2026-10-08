"""PoC coverage manifest completeness and honest test-symbol traceability."""
import json
import re
from pathlib import Path


def test_step2_poc_audit_enumerates_every_frozen_poc_and_real_test_symbol():
    root = Path(__file__).resolve().parents[2]
    manifest = json.loads((root / "audits" / "step2-poc-coverage.json").read_text(encoding="utf-8"))
    expected = {f"R{i}" for i in (*range(16, 27), *range(75, 129))}
    entries = manifest["entries"]
    assert len(entries) == len(expected) == 65
    assert {entry["id"] for entry in entries} == expected
    assert set(manifest["counts"]) == {"PASS", "PARTIAL", "GAP"}
    for entry in entries:
        assert entry["status"] in ("PASS", "PARTIAL", "GAP")
        if entry["status"] == "PASS":
            assert entry["test"], f"PASS without evidence: {entry['id']}"
        if entry["status"] in ("PASS", "PARTIAL") and entry["test"]:
            name, symbol = entry["test"].split("::", 1)
            target = root / name
            assert target.is_file(), entry["id"]
            assert re.search(r"\b(?:async )?def\s+" + re.escape(symbol) + r"\s*\(", target.read_text(encoding="utf-8")), entry["id"]
        if entry["status"] == "GAP":
            assert entry["assessment"], entry["id"]
    assert {name: sum(e["status"] == name for e in entries) for name in ("PASS", "PARTIAL", "GAP")} == manifest["counts"]
