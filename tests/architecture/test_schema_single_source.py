import ast
from collections import defaultdict
from pathlib import Path

def test_project_class_names_are_single_sourced_in_src()->None:
    src=Path(__file__).resolve().parents[2]/"src"/"aswe"
    owners:dict[str,list[Path]]=defaultdict(list)
    for path in src.rglob("*.py"):
        tree=ast.parse(path.read_text(encoding="utf-8"),filename=str(path))
        for node in tree.body:
            if isinstance(node,ast.ClassDef): owners[node.name].append(path)
    duplicates={name:paths for name,paths in owners.items() if len(paths)>1}
    assert duplicates=={}
