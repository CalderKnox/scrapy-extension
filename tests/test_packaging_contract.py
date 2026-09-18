"""Executable contracts for source-distribution completeness and hygiene."""

from __future__ import annotations

import re
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 compatibility
    import tomli as tomllib


_REQUIRED_SOURCE_ENTRIES = {
    ".github/audit-fixtures/**",
    ".github/audit-waivers.toml",
    ".github/workflows/**",
    "conftest.py",
    "tests/**",
    "tools/**",
    "uv.lock",
}
_REQUIRED_EXCLUDES = {
    "**/.claude/**",
    "**/.claude-flow/**",
    "**/.coverage.*",
    "./.cache/**",
    "**/.pytest_cache/**",
    "**/*.log",
    "**/*.sqlite3",
    "**/local_settings.py",
    "**/generated-canary*/**",
    "docs/08-archive/**",
}


def _pyproject() -> dict[str, object]:
    root = Path(__file__).resolve().parents[1]
    with (root / "pyproject.toml").open("rb") as stream:
        return tomllib.load(stream)


def test_isolated_build_backend_is_exactly_pinned() -> None:
    """The build backend must stay exactly version-pinned (never a range).

    The concrete version is dependency policy owned by pyproject.toml (and its
    dependabot updates); this contract only guarantees the pin SHAPE, so an
    isolated reproducible build can never drift onto a floating backend.
    """
    build_system = _pyproject()["build-system"]
    assert isinstance(build_system, dict)
    requires = build_system["requires"]
    assert isinstance(requires, list)
    assert len(requires) == 1
    assert isinstance(requires[0], str)
    assert re.fullmatch(r"uv_build==\d+\.\d+\.\d+", requires[0]), requires


def test_sdist_configuration_keeps_tests_self_contained_and_clean() -> None:
    tool = _pyproject()["tool"]
    assert isinstance(tool, dict)
    uv = tool["uv"]
    assert isinstance(uv, dict)
    build = uv["build-backend"]
    assert isinstance(build, dict)

    includes = set(build["source-include"])
    excludes = set(build["source-exclude"])
    assert _REQUIRED_SOURCE_ENTRIES <= includes
    assert _REQUIRED_EXCLUDES <= excludes
