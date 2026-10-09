"""Step 2 audit report integrity — prevent duplicate/concatenated PoC rows."""
from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "audits" / "step2-poc-coverage.json"
REPORT = ROOT / "audits" / "step2-poc-audit.md"


def test_step2_poc_audit_exact_one_row_per_frozen_case():
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    report = REPORT.read_text(encoding="utf-8")
    ids = [e["id"] for e in data["entries"]]
    expected = [f"R{i}" for i in range(16, 27)] + [f"R{i}" for i in range(75, 129)]
    assert ids == expected, "Frozen PoC inventory must remain canonical and complete"
    assert len(set(ids)) == 65
    assert data["counts"] == {
        k: sum(e["status"] == k for e in data["entries"])
        for k in ("PASS", "PARTIAL", "GAP")
    }
    lines = report.splitlines()
    assert lines[0].startswith("# Coding Step 2"), "No leading concatenated table rows"
    rows = [re.match(r"^\| POC-(R\d+) \| (PASS|PARTIAL|GAP) \| `([^|]+)` \|", line)
            for line in lines if line.startswith("| POC-")]
    assert len(rows) == 65
    assert all(rows), "Every table row must be correctly separated"
    assert [m.group(1) for m in rows] == ids, "No duplicate/out-of-order rows"
    for match, entry in zip(rows, data["entries"]):
        assert match.group(2) == entry["status"]
        assert match.group(3) == entry["test"].removeprefix("tests/unit/")
        file_name, symbol = entry["test"].split("::", 1)
        source = ROOT / file_name
        assert source.is_file(), f"Missing test source: {source}"
        assert re.search(rf"(?:async )?def {re.escape(symbol)}\(", source.read_text(encoding="utf-8")), (
            f"Missing executable test: {symbol}"
        )
