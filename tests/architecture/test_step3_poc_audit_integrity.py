"""Step-3 frozen PoC audit honesty, identity, and traceability."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]


def test_step3_audit_22_cases_and_statuses_match_source():
    data=json.loads((ROOT/"audits/step3-poc-coverage.json").read_text(encoding="utf-8"))
    cases=data["entries"]
    expected=[f"P3-{i:02}" for i in range(1,13)]+[f"C{i:02}" for i in range(1,11)]
    assert [x["id"] for x in cases]==expected
    assert len(set(x["id"] for x in cases))==22
    assert data["counts"]=={
        status:sum(x["status"]==status for x in cases)
        for status in ("PASS","PARTIAL","GAP")
    }
    for case in cases:
        assert case["status"] in ("PASS","PARTIAL","GAP")
        assert case["assessment"]
        if case["status"] in ("PASS","PARTIAL"):
            assert case["test"] and "::" in case["test"]
            source,symbol=case["test"].split("::",1)
            path=ROOT/source
            assert path.is_file(), str(path)
            assert re.search(rf"(?:async )?def {re.escape(symbol)}\(", path.read_text(encoding="utf-8")), symbol
        else:
            assert case["test"] is None
