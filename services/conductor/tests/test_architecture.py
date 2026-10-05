"""Layering rules, enforced: domain is pure, application never imports adapters/infrastructure."""

import ast
import sys
from pathlib import Path

SRC = Path(__file__).parents[1] / "src" / "conductor"


def _imports(path: Path) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            out |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            out.add(node.module)
    return out


def test_domain_imports_only_stdlib_and_itself() -> None:
    for f in (SRC / "domain").rglob("*.py"):
        for mod in _imports(f):
            root = mod.split(".")[0]
            assert root in sys.stdlib_module_names or mod.startswith("conductor.domain"), (f, mod)


# structlog is the logging facade (configured in infrastructure/logging.py); it does
# no I/O of its own choosing and is the one third-party import use cases may have.
APPLICATION_ALLOWED_THIRD_PARTY = {"structlog"}


def test_application_depends_only_on_domain_and_stdlib() -> None:
    for f in (SRC / "application").rglob("*.py"):
        for mod in _imports(f):
            root = mod.split(".")[0]
            ok = (
                root in sys.stdlib_module_names
                or root in APPLICATION_ALLOWED_THIRD_PARTY
                or mod.startswith(("conductor.domain", "conductor.application"))
            )
            assert ok, (f, mod)
