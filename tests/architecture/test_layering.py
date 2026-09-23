"""The package dependency rules, checked against the source rather than trusted.

Added 2026-09-23. The rules below were stated in ``CONTRIBUTING.md`` and
``docs/architecture.md`` from the start and described
there as enforced by tests -- but no test read the imports. When one finally
did, it found a violation introduced the same day: ``gateway/events.py``
imported ``application.link_monitor`` for two value types, which then moved
to ``core/link_events.py``. A rule nobody checks is a rule that drifts.

Every ``import`` / ``from ... import`` in ``src/`` is read with ``ast``,
including ones inside functions and ``TYPE_CHECKING`` blocks: a type-only
import is still a dependency a reader has to follow.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
PACKAGES = sorted(p.name for p in SRC.iterdir() if (p / "__init__.py").is_file())

# Which other top-level packages each package may import. ``core`` is open to
# everyone and depends on no one. Anything not listed is forbidden.
ALLOWED: dict[str, set[str]] = {
    "core": set(),
    "protocol": {"core"},
    "communication": {"core"},
    "llm": {"core"},
    # SimulatorDevice publishes readings into a DataService.
    "device": {"core", "service"},
    # Channel id constants only. Never llm/storage: their ports are defined
    # here, on the consuming side (LlmClient, HistoryStore).
    "service": {"core", "device"},
    # Implements service.history.HistoryStore.
    "storage": {"core", "service"},
    # The composition root: the one place concrete adapters are created.
    "application": {
        "core", "device", "protocol", "communication", "service", "llm", "storage",
    },
    "api": {"core", "application", "service"},
    # The two presentation ends: api, core, and the shared model types that
    # appear in ApiInterface's signatures -- see _api_model_modules().
    "ui": {"core", "api", "service"},
    "gateway": {"core", "api", "service"},
}


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.append(node.module)
    return names


def _files(package: str) -> list[Path]:
    return sorted((SRC / package).rglob("*.py"))


def _api_model_modules() -> set[str]:
    """The ``service`` modules whose types ApiInterface's signatures expose.

    Read from ``api/interface.py`` itself, plus ``service.data_models``:
    ``DataPoint`` reaches every subscriber through ``DataCallback`` (defined
    in ``service.data_service``) without the interface naming it.
    """
    return {
        name for name in _imports(SRC / "api" / "interface.py")
        if name.split(".")[0] == "service"
    } | {"service.data_models"}


def test_every_package_has_a_rule() -> None:
    assert set(PACKAGES) == set(ALLOWED), set(PACKAGES) ^ set(ALLOWED)


@pytest.mark.parametrize("package", PACKAGES)
def test_package_imports_only_what_it_may(package: str) -> None:
    violations = []
    for path in _files(package):
        for name in _imports(path):
            top = name.split(".")[0]
            if top in ALLOWED and top != package and top not in ALLOWED[package]:
                violations.append(f"{path.relative_to(SRC).as_posix()}: {name}")
    assert not violations, "\n".join(violations)


@pytest.mark.parametrize("package", ["ui", "gateway"])
def test_presentation_ends_take_only_model_types_from_service(package: str) -> None:
    """Not ``service`` at large: only what ApiInterface itself hands out."""
    models = _api_model_modules()
    violations = [
        f"{path.relative_to(SRC).as_posix()}: {name}"
        for path in _files(package)
        for name in _imports(path)
        if name.split(".")[0] == "service" and name not in models
    ]
    assert not violations, "\n".join(violations)


def test_only_the_controller_reaches_outside_ui() -> None:
    """Widgets and the window talk to the controller, never to api directly."""
    violations = [
        f"{path.relative_to(SRC).as_posix()}: {name}"
        for path in _files("ui")
        if path.name != "controller.py"
        for name in _imports(path)
        if name.split(".")[0] in {"api", "service"}
    ]
    assert not violations, "\n".join(violations)


def test_the_gateway_is_a_headless_service() -> None:
    violations = [
        f"{path.relative_to(SRC).as_posix()}: {name}"
        for path in _files("gateway")
        for name in _imports(path)
        if name.split(".")[0] == "PyQt6"
    ]
    assert not violations, "\n".join(violations)


def test_the_checker_sees_a_violation() -> None:
    """Guard the guard: an import it should reject is actually rejected."""
    sample = "from application.runtime import ApplicationRuntime\n"
    names = [
        node.module for node in ast.walk(ast.parse(sample))
        if isinstance(node, ast.ImportFrom)
    ]
    assert names == ["application.runtime"]
    assert "application" not in ALLOWED["gateway"]
