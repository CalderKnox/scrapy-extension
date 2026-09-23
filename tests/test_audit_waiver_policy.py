"""Regression tests for the temporary dependency-audit waiver policy."""

from __future__ import annotations

import re
import shutil
from datetime import date
from pathlib import Path

import pytest
from tools.check_audit_waiver import WaiverPolicyError, validate_waivers

_ROOT = Path(__file__).resolve().parents[1]


def _policy_checkout(tmp_path: Path) -> Path:
    (tmp_path / ".github").mkdir()
    shutil.copy2(_ROOT / "uv.lock", tmp_path / "uv.lock")
    shutil.copy2(
        _ROOT / ".github" / "audit-waivers.toml",
        tmp_path / ".github" / "audit-waivers.toml",
    )
    shutil.copytree(
        _ROOT / ".github" / "audit-fixtures",
        tmp_path / ".github" / "audit-fixtures",
    )
    return tmp_path


def test_checked_in_waiver_matches_lock_and_fixture_before_expiry() -> None:
    assert validate_waivers(_ROOT, today=date(2026, 12, 30)) == ["PYSEC-2017-83"]


def test_waiver_fails_on_expiry_date() -> None:
    with pytest.raises(WaiverPolicyError, match="expired on 2026-12-31"):
        validate_waivers(_ROOT, today=date(2026, 12, 31))


def test_waiver_fails_when_locked_package_leaves_justified_range(
    tmp_path: Path,
) -> None:
    checkout = _policy_checkout(tmp_path)
    lock_path = checkout / "uv.lock"
    original = lock_path.read_text(encoding="utf-8")
    # Mutation must track whatever version is currently locked so the
    # negative test keeps exercising the "left waiver range" branch across
    # routine lock updates instead of silently no-op'ing on a stale literal.
    mutated = re.sub(
        r'(name = "scrapy"\nversion = ")[^"]+(")',
        r"\g<1>3.0.0\g<2>",
        original,
        count=1,
    )
    assert mutated != original, "scrapy lock entry not found; mutation no-op"
    lock_path.write_text(mutated, encoding="utf-8")

    with pytest.raises(WaiverPolicyError, match="left waiver range"):
        validate_waivers(checkout, today=date(2026, 8, 18))


def test_waiver_fails_when_advisory_disappears_from_locked_fixture(
    tmp_path: Path,
) -> None:
    checkout = _policy_checkout(tmp_path)
    fixture_path = checkout / ".github" / "audit-fixtures" / "PYSEC-2017-83.json"
    fixture_path.write_text(
        fixture_path.read_text(encoding="utf-8").replace(
            '"advisory": "PYSEC-2017-83"',
            '"advisory": "REMOVED"',
        ),
        encoding="utf-8",
    )

    with pytest.raises(WaiverPolicyError, match="fixture does not match"):
        validate_waivers(checkout, today=date(2026, 8, 18))


def test_ci_applies_only_the_machine_checked_waiver() -> None:
    workflow = (_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "python tools/check_audit_waiver.py" in workflow
    assert 'uv audit --locked --ignore "$waiver_id"' in workflow
    assert "uv audit --locked --ignore PYSEC-2017-83" not in workflow
