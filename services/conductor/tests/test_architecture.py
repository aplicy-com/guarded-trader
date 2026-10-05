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


# The Freqtrade WRITE client may only be constructed in the composition path. In
# particular nothing in the LLM / research code can reach it (ADR-0003, ADR-0014).
CONTROL_CLIENT_IMPORTERS = {
    "adapters/freqtrade/__init__.py",
    "infrastructure/freqtrade_instances.py",
}


def test_control_client_is_imported_only_by_the_composition_path() -> None:
    for f in SRC.rglob("*.py"):
        rel = f.relative_to(SRC).as_posix()
        if rel == "adapters/freqtrade/control_client.py" or rel in CONTROL_CLIENT_IMPORTERS:
            continue
        text = f.read_text()
        assert "control_client" not in text, rel
        assert "FreqtradeControlClient" not in text, rel


def test_llm_adapter_has_no_freqtrade_dependency() -> None:
    llm = (SRC / "adapters" / "llm.py").read_text()
    assert "freqtrade" not in llm.lower()
    assert "FreqtradeController" not in llm
