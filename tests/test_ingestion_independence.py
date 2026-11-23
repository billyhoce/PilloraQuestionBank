"""ingestion/ is a library the webapp builds on, never the reverse: nothing under it may
import ``app``. Checked on the AST so it needs no ingestion dependency installed."""

import ast
from pathlib import Path

INGESTION = Path(__file__).resolve().parent.parent / "ingestion"


def _imports_app(path: Path) -> list[int]:
    lines = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            names = [node.module or ""]
        else:
            continue
        if any(n == "app" or n.startswith("app.") for n in names):
            lines.append(node.lineno)
    return lines


def test_ingestion_has_python_modules():
    assert list(INGESTION.glob("*/__init__.py")), "ingestion/ packages not found"


def test_ingestion_never_imports_app():
    offenders = [
        f"{p.relative_to(INGESTION)}:{n}"
        for p in INGESTION.rglob("*.py")
        if ".venv" not in p.parts
        for n in _imports_app(p)
    ]
    assert not offenders, f"ingestion/ must not import app: {offenders}"
