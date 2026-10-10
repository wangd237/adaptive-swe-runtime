import ast
from pathlib import Path

FORBIDDEN_ROOTS={"deerflow"}
FORBIDDEN_PREFIXES=("aswe.integrations.deerflow",)
PROTECTED=("core","runtime","workspace","repository","evidence","planning","evaluation")

def test_no_deerflow_imports_in_core_layers()->None:
    src=Path(__file__).resolve().parents[2]/"src"/"aswe"
    violations:list[str]=[]
    for name in PROTECTED:
        root=src/name
        if not root.exists(): continue
        for path in root.rglob("*.py"):
            tree=ast.parse(path.read_text(encoding="utf-8"),filename=str(path))
            for node in ast.walk(tree):
                module=None
                if isinstance(node,ast.ImportFrom): module=node.module
                elif isinstance(node,ast.Import):
                    for alias in node.names:
                        if alias.name.split(".")[0] in FORBIDDEN_ROOTS or alias.name.startswith(FORBIDDEN_PREFIXES):
                            violations.append(f"{path}: import {alias.name}")
                if module and (module.split(".")[0] in FORBIDDEN_ROOTS or module.startswith(FORBIDDEN_PREFIXES)):
                    violations.append(f"{path}: from {module} import ...")
    assert violations==[]
