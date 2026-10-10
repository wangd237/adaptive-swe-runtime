"""Paid E2E scenario is an actual broken repository, never a scripted patch."""
from pathlib import Path
import subprocess
import sys

from scripts.live_adaptive_acceptance import FILES, TASK, seed_repository


def test_live_fixture_has_two_real_regressions_and_clean_git_baseline(tmp_path):
    repo=tmp_path/"repo"
    seed_repository(repo)
    run=subprocess.run(
        [sys.executable,"-B","-m","unittest","discover","-s","tests","-q"],
        cwd=repo,capture_output=True,text=True,timeout=15)
    assert run.returncode != 0
    # Two independent user-visible behavioral regressions, no fake outputs.
    assert "FAIL" in run.stderr
    assert "test_paid_cancellation_restores_stock_and_refunds_once" in run.stderr
    assert "test_cancellation_is_idempotent" in run.stderr
    assert (repo/"shop/orders.py").read_text()==FILES["shop/orders.py"]
    assert (repo/"shop/inventory.py").read_text()==FILES["shop/inventory.py"]
    status=subprocess.run(["git","-C",str(repo),"status","--porcelain"],
                          capture_output=True,text=True,check=True)
    assert status.stdout == ""
    assert "cross-module" in TASK


def test_live_workflow_is_explicitly_armed_not_unconditional():
    yml=Path(".github/workflows/swe-adaptive-real-e2e.yml").read_text()
    assert "workflow_dispatch:" in yml
    assert "authorization == 'RUN'" in yml
    assert "  push:" not in yml
    assert "  pull_request:" not in yml
    assert "if: ${{ github.event_name == 'workflow_dispatch' && inputs.authorization == 'RUN' }}" in yml
    assert "secrets.SWE_LLM_API_KEY" in yml
    assert "secrets.SWE_LLM_MODEL" in yml
    assert "secrets.SWE_LLM_BASE_URL" in yml
    assert "pull_request:" not in yml
    assert "LANGSMITH_TRACING: 'false'" in yml
