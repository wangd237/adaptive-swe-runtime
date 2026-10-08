from pathlib import Path

FORBIDDEN_TOKENS=("langchain","openai","anthropic","invoke(","ainvoke(")

def test_runtime_control_has_no_model_dependency()->None:
    runtime=Path(__file__).resolve().parents[2]/"src"/"aswe"/"runtime"
    violations:list[str]=[]
    if runtime.exists():
        for path in runtime.rglob("*.py"):
            text=path.read_text(encoding="utf-8").lower()
            for token in FORBIDDEN_TOKENS:
                if token in text: violations.append(f"{path}: {token}")
    assert violations==[]
