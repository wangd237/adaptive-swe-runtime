"""Sync frozen design documents from the companion plan repository."""
from __future__ import annotations
from pathlib import Path
from urllib.request import urlopen

PIN="b87c015e302ed51dbc419f883f888f1ff47108ab"
BASE=f"https://raw.githubusercontent.com/wangd237/adaptive_swe_plan/{PIN}"
FILES=(
    "AGENTS.md",
    "specs/01-task-planning.md",
    "specs/02-capability-provider-dag.md",
    "specs/03-execution-runtime.md",
    "specs/04-evidence-evaluation.md",
    "plan/master-plan.md",
    "audits/deerflow-source-audit.md",
    "tests/poc-matrix.md",
)

def main()->None:
    root=Path(__file__).resolve().parents[1]
    for relative in FILES:
        target=root/relative
        target.parent.mkdir(parents=True,exist_ok=True)
        with urlopen(f"{BASE}/{relative}",timeout=30) as response:
            target.write_bytes(response.read())
        print(f"synced {relative}")

if __name__=="__main__":
    main()
