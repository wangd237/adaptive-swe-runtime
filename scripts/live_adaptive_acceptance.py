"""One explicitly authorized real-model Adaptive Workflow acceptance run.

Never runs in normal pytest / CI. No scripted model, model factory, fake
planner, or artificial failing step. The fixture has genuine cross-module
regressions. Report exports bounded status metadata, never provider secrets,
raw model responses, prompts, trace or code diff.
"""
from __future__ import annotations

import asyncio
from collections import Counter
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from aswe.integrations.deerflow.dev_workflow import execute_dev_workflow
from aswe.integrations.deerflow.controlled_swe import DockerCommandBackend
from aswe.integrations.deerflow.live_smoke_config import LiveModelSettings


TASK = (
    "Investigate the cross-module order cancellation regression in "
    "shop/orders.py and shop/inventory.py. When a paid order is cancelled, "
    "reserved inventory must be restored and the payment must be refunded "
    "exactly once. Repeating the cancellation must be a no-op, not another "
    "refund. Locate root causes, repair the implementation, and make all "
    "existing unittest regression tests pass. Do not modify tests or configs."
)
FILES = {
    "shop/__init__.py": "",
    "shop/orders.py": '''"""Order lifecycle operations."""
from dataclasses import dataclass


@dataclass
class Order:
    order_id: str
    sku: str
    quantity: int
    status: str = "paid"


def cancel_order(order, inventory, billing):
    if order.status == "cancelled":
        billing.refund(order.order_id)
        return True
    if order.status != "paid":
        return False
    inventory.release(order.sku, order.quantity)
    billing.refund(order.order_id)
    order.status = "cancelled"
    return True
''',
    "shop/inventory.py": '''"""Reserved inventory accounting."""


class Inventory:
    def __init__(self, available):
        self.available = dict(available)

    def release(self, sku, quantity):
        self.available[sku] = self.available.get(sku, 0) - quantity
''',
    "shop/billing.py": '''"""Small in-memory billing record used by order services."""


class Billing:
    def __init__(self):
        self.refunds = []

    def refund(self, order_id):
        self.refunds.append(order_id)
''',
    "tests/__init__.py": "",
    "tests/test_cancellation.py": '''import unittest

from shop.orders import Order, cancel_order
from shop.inventory import Inventory
from shop.billing import Billing


class CancellationRegressionTests(unittest.TestCase):
    def test_paid_cancellation_restores_stock_and_refunds_once(self):
        order = Order("order-100", "widget", 3)
        inventory = Inventory({"widget": 6})
        billing = Billing()
        self.assertTrue(cancel_order(order, inventory, billing))
        self.assertEqual(order.status, "cancelled")
        self.assertEqual(inventory.available["widget"], 9)
        self.assertEqual(billing.refunds, ["order-100"])

    def test_cancellation_is_idempotent(self):
        order = Order("order-200", "widget", 2)
        inventory = Inventory({"widget": 3})
        billing = Billing()
        self.assertTrue(cancel_order(order, inventory, billing))
        self.assertFalse(cancel_order(order, inventory, billing))
        self.assertEqual(inventory.available["widget"], 5)
        self.assertEqual(billing.refunds, ["order-200"])

    def test_nonpaid_order_is_untouched(self):
        order = Order("order-300", "widget", 4, status="pending")
        inventory = Inventory({"widget": 8})
        billing = Billing()
        self.assertFalse(cancel_order(order, inventory, billing))
        self.assertEqual(inventory.available["widget"], 8)
        self.assertEqual(billing.refunds, [])
''',
    "README.md": "# Order cancellation regression fixture\n\nRun `python -B -m unittest discover -s tests -q`.\n",
}
CHECK = ("python", "-B", "-m", "unittest", "discover", "-s", "tests", "-q")


class AcceptanceFailed(Exception):
    pass


def require(condition: bool, code: str) -> None:
    if not condition:
        raise AcceptanceFailed(code)


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                   check=True, timeout=20)


def seed_repository(root: Path) -> None:
    root.mkdir(parents=True)
    git(root, "init")
    for name, source in FILES.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
    git(root, "add", "-A")
    git(root, "-c", "user.name=ASWE-Test",
        "-c", "user.email=aswe-test@example.invalid",
        "commit", "-m", "Seed genuine cancellation regression")


def python_image_digest() -> str:
    result = subprocess.run(
        ["docker", "image", "inspect", "--format", "{{index .RepoDigests 0}}",
         "python:3.12-slim"],
        capture_output=True, check=True, text=True, timeout=20)
    digest = result.stdout.strip()
    require(digest.startswith("python@sha256:"), "IMAGE_DIGEST_INVALID")
    return digest


async def acceptance(summary: dict) -> None:
    # No live API invocations outside the explicit paid Actions gate.
    require(os.environ.get("ASWE_LIVE_SMOKE") == "1" and
            os.environ.get("GITHUB_ACTIONS") == "true" and
            os.environ.get("ASWE_ADAPTIVE_LIVE_ONCE") == "1",
            "EXPLICIT_LIVE_ACTIONS_GATE_MISSING")
    LiveModelSettings.from_environment()  # opaque, no credentials logged
    image = python_image_digest()

    with tempfile.TemporaryDirectory(prefix="aswe-live-adaptive-") as temp:
        base = Path(temp)
        original = base / "repository"
        seed_repository(original)
        baseline = DockerCommandBackend(workspace_root=original, image=image)
        observed = await baseline.run(" ".join(CHECK), timeout=40,max_output=1800)
        require(observed.exit_code not in (None,0) and not observed.timed_out,
                "BASELINE_TESTS_NOT_FAILING")
        summary["baseline_tests_failed"] = True
        run = await asyncio.wait_for(execute_dev_workflow(
            repository=original,task=TASK, runtime_dir=base / "runtime",
            check_argv=CHECK,image=image,max_repairs=1,
            adaptive=True,planner="llm",explorer_mode="llm",
            physical_dag=True,
        ),timeout=1050)

        events = [json.loads(s) for s in run.trace_path.read_text(
            encoding="utf-8").splitlines() if s]
        types = Counter(e["event_type"] for e in events)
        nodes = [e["node_id"] for e in events
                 if e["event_type"] == "dag.scheduler.dispatch"]
        team = next((e["payload"]["roles"] for e in events
                     if e["event_type"] == "team.selected"), [])
        dag = next((e["payload"] for e in events
                    if e["event_type"] == "task_dag.compiled"), {})
        checks = [e["payload"].get("status")
                  for e in events if e["event_type"] == "dag.verification.executed"]
        children = [json.loads(p.read_text(encoding="utf-8"))
                    for p in run.round_reports]
        changed = sorted({name for child in children
                          for name in child.get("changed_files",[])})
        final_workspace=run.round_reports[-1].parent / "workspace"
        unchanged_tests = all(
            (original/p).read_bytes() == (final_workspace/p).read_bytes()
            for p in FILES if p.startswith("tests/"))
        corrected_modules = all(
            (original/p).read_bytes() != (final_workspace/p).read_bytes()
            for p in ("shop/orders.py", "shop/inventory.py"))
        summary.update(
            workflow_id=run.workflow_id,
            verdict=run.verification_status,
            round_count=run.round_count,
            selected_roles=team,
            physical_dag_compiled=bool(dag.get("task_dag_fingerprint")),
            dag_topological_order=dag.get("topological_order", []),
            dispatch_nodes=nodes,
            independent_tester_statuses=checks,
            repair_scheduled=types["workflow.repair.scheduled"],
            native_model_turns=types["model.turn.finished"],
            native_tool_calls=types["tool.call.finished"],
            child_native_statuses=[c.get("native_status") for c in children],
            child_canonical_statuses=[c.get("verification_status") for c in children],
            modified_files=changed,
            test_files_unchanged=unchanged_tests,
            both_faulty_modules_changed=corrected_modules,
        )
        require(team == ["explorer","coder","tester"], "PLANNER_DID_NOT_SELECT_MULTIAGENT")
        require(dag.get("topological_order") ==
                ["explorer","coder","__aswe_verify"], "PHYSICAL_DAG_INCORRECT")
        require(nodes.count("explorer") == 1, "EXPLORER_NOT_DISPATCHED")
        require(nodes.count("coder") >= 1, "CODER_NOT_DISPATCHED")
        require(nodes.count("__aswe_verify") >= 1, "TESTER_NOT_DISPATCHED")
        require(types["model.turn.finished"] >= 2,
                "NO_NATIVE_LLM_CODING_TURNS")
        require(types["tool.call.finished"] >= 2,
                "NO_NATIVE_CODING_TOOL_INTERACTION")
        require(all(x == "completed" for x in summary["child_native_statuses"]),
                "CODER_NOT_COMPLETED")
        require(run.verification_status == "passed" and checks[-1] == "passed",
                "FINAL_CANONICAL_TESTS_NOT_PASSED")
        require(unchanged_tests, "TEST_FILES_MODIFIED")
        require(corrected_modules, "MULTIMODULE_REPAIR_NOT_DELIVERED")
        # A repair is only valid if canonical checks first fail. Do not force
        # failure or claim a repair was run if the initial patch already passes.
        summary["repair_outcome"] = ("executed" if
            types["workflow.repair.scheduled"] else
            "not_needed_first_pass_succeeded")


def persist_summary(summary: dict) -> None:
    output = os.environ.get("ASWE_ADAPTIVE_LIVE_REPORT_PATH")
    if output:
        dest = Path(output).resolve()
        runner = Path(os.environ["RUNNER_TEMP"]).resolve()
        require(dest.is_relative_to(runner), "REPORT_OUTSIDE_RUNNER_TEMP")
        dest.write_text(json.dumps(summary, indent=2, sort_keys=True)+"\n",
                        encoding="utf-8")
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        lines = [
            "## Step 6F: Real LLM Adaptive SWE E2E",
            "",
            "| Evidence | Observed |",
            "|---|---|",
            f"| Outcome | `{summary.get('outcome','unavailable')}` |",
            f"| Failure code | `{summary.get('failure_code','none')}` |",
            f"| Live selected roles | `{','.join(summary.get('selected_roles',[]))}` |",
            f"| DAG compiled | `{summary.get('physical_dag_compiled',False)}` |",
            f"| Dispatches | `{','.join(summary.get('dispatch_nodes',[]))}` |",
            f"| Independent tester results | `{summary.get('independent_tester_statuses',[])}` |",
            f"| Repair rounds scheduled | `{summary.get('repair_scheduled',0)}` |",
            f"| Final result | `{summary.get('verdict','unknown')}` |",
            f"| Modified files | `{','.join(summary.get('modified_files',[]))}` |",
            "",
            "The model was not mocked. Repair is conditional on a real failing test, "
            "not artificially forced.",
        ]
        with open(path,"a",encoding="utf-8") as file:
            file.write("\n".join(lines)+"\n")


def main() -> int:
    summary = {"scenario":"cross_module_order_cancellation",
               "paid_model":True,"outcome":"not_started"}
    try:
        asyncio.run(acceptance(summary))
        summary["outcome"]="passed"
        code=0
    except Exception as exc:
        # Do not emit opaque provider messages, endpoints or secrets to CI.
        summary["outcome"]="failed"
        summary["failure_code"]=(
            exc.args[0] if isinstance(exc, AcceptanceFailed)
            else type(exc).__name__)
        code=1
    persist_summary(summary)
    print("ASWE_ADAPTIVE_LIVE_RESULT="+summary["outcome"])
    print("ASWE_ADAPTIVE_LIVE_FAILURE_CODE="+str(summary.get("failure_code","none")))
    return code


if __name__ == "__main__":
    sys.exit(main())
