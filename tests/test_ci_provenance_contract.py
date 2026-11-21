"""Executable contracts for artifact provenance attestation and release delivery.

Every assertion here is static: the workflow files are parsed with ``yaml`` (or
read as text) and nothing contacts GitHub, runs ``gh``, or needs the network.
Attestations are only minted inside GitHub Actions, so this module pins the
workflow shape and the checks that run there — it does not and cannot prove
that an attestation exists. The CI job ``Verify · artifact provenance`` is what
proves that on a real run.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOWS = _ROOT / ".github" / "workflows"
_ATTEST_ACTION = "actions/attest-build-provenance"
_ATTEST_PIN = "actions/attest-build-provenance@v4.2.2"
_REPOSITORY_GUARD = (
    "github.event.pull_request.head.repo.owner.login == github.repository_owner"
)
_PULL_REQUEST_GUARD = "github.event_name != 'pull_request'"
# Publishing surfaces this repository must never grow back: the delivery
# channel is a GitHub Release, not a package index.
_FORBIDDEN_PUBLISH_TOKENS = (
    "pypa/gh-action-pypi-publish",
    "twine",
    "uv publish",
    "flit publish",
    "--repository pypi",
)


def _workflow_paths() -> list[Path]:
    return sorted(_WORKFLOWS.glob("*.yml")) + sorted(_WORKFLOWS.glob("*.yaml"))


def _load(name: str) -> dict[str, Any]:
    document = yaml.safe_load((_WORKFLOWS / name).read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def _text(name: str) -> str:
    return (_WORKFLOWS / name).read_text(encoding="utf-8")


def _steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    return [step for step in job.get("steps", ()) if isinstance(step, dict)]


def _job_runs(job: dict[str, Any]) -> str:
    return "\n".join(
        str(step["run"]) for step in _steps(job) if isinstance(step.get("run"), str)
    )


def _normalized(value: str) -> str:
    """Collapse folded YAML scalars so a condition reads as one line."""
    return " ".join(value.split())


def _attesting(workflow: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    return [
        (job_name, job)
        for job_name, job in workflow["jobs"].items()
        if any(
            str(step.get("uses", "")).startswith(_ATTEST_ACTION) for step in _steps(job)
        )
    ]


def _triggers(workflow: dict[str, Any]) -> dict[str, Any]:
    # PyYAML resolves the unquoted `on:` key to the boolean True.
    for key in ("on", True):
        value = workflow.get(key)
        if isinstance(value, dict):
            return value
    raise AssertionError("workflow declares no trigger mapping")


def test_ci_attests_with_the_exact_pinned_action() -> None:
    """R1: the attest action is pinned to a release tag, never a major alias."""
    attest_steps = [
        step
        for job in _load("ci.yml")["jobs"].values()
        for step in _steps(job)
        if str(step.get("uses", "")).startswith(_ATTEST_ACTION)
    ]
    assert len(attest_steps) == 1
    assert attest_steps[0]["uses"] == _ATTEST_PIN
    assert attest_steps[0]["with"] == {"subject-path": "dist/*"}

    for name in ("ci.yml", "release.yml"):
        assert _ATTEST_PIN in _text(name)

    for path in _workflow_paths():
        floating = re.search(
            rf"{re.escape(_ATTEST_ACTION)}@v\d+\s*$",
            path.read_text(encoding="utf-8"),
            re.MULTILINE,
        )
        assert floating is None, path


def test_attesting_job_asserts_its_subjects_before_attesting() -> None:
    """R1: the attested glob must be exactly wheel + sdist + SHA256SUMS."""
    job = next(
        job
        for job in _load("ci.yml")["jobs"].values()
        if any(
            str(step.get("uses", "")).startswith(_ATTEST_ACTION) for step in _steps(job)
        )
    )
    steps = _steps(job)
    attest_index = next(
        index
        for index, step in enumerate(steps)
        if str(step.get("uses", "")).startswith(_ATTEST_ACTION)
    )
    assert attest_index > 0
    assertion = str(steps[attest_index - 1]["run"])

    assert "sha256sum --check --strict SHA256SUMS" in assertion
    for expectation in (
        "wheels=(*.whl)",
        "sdists=(*.tar.gz)",
        'test "${#wheels[@]}" -eq 1',
        'test "${#sdists[@]}" -eq 1',
        'test "${#subjects[@]}" -eq 3',
    ):
        assert expectation in assertion


def test_attesting_job_scopes_oidc_and_attestation_write() -> None:
    """R1: job-level least privilege, and never ``write-all`` anywhere."""
    workflow = _load("ci.yml")
    attesting = _attesting(workflow)
    assert len(attesting) == 1
    attesting_job_name, attesting_job = attesting[0]
    assert attesting_job["permissions"] == {
        "contents": "read",
        "id-token": "write",
        "attestations": "write",
    }

    for job_name, job in workflow["jobs"].items():
        permissions = job.get("permissions") or {}
        assert isinstance(permissions, dict)
        if job_name == attesting_job_name:
            continue
        # Only the attesting job may mint: no OIDC token, and at most a
        # read-only attestations scope for the verification job.
        assert "id-token" not in permissions, job_name
        assert permissions.get("attestations") in (None, "read"), job_name

    for path in _workflow_paths():
        text = path.read_text(encoding="utf-8")
        assert "write-all" not in text, path
        parsed = yaml.safe_load(text)
        for job_name, job in parsed["jobs"].items():
            permissions = job.get("permissions") or {}
            assert "write-all" not in permissions, (path.name, job_name)
            assert permissions != "write-all", (path.name, job_name)


def test_attest_step_is_skipped_for_fork_pull_requests() -> None:
    """R1: a read-only fork token must skip attestation, never fail it."""
    attest_step = next(
        step
        for job in _load("ci.yml")["jobs"].values()
        for step in _steps(job)
        if str(step.get("uses", "")).startswith(_ATTEST_ACTION)
    )
    condition = _normalized(str(attest_step["if"]))

    assert _PULL_REQUEST_GUARD in condition
    assert _REPOSITORY_GUARD in condition


def test_provenance_verify_job_proves_the_attestation_inside_ci() -> None:
    """R2: CI verifies what it minted instead of only creating it."""
    workflow = _load("ci.yml")
    job = workflow["jobs"]["provenance-verify"]

    assert job["name"] == "Verify · artifact provenance"
    assert set(job["needs"]) == {"docs", "unit-tests"}
    condition = _normalized(str(job["if"]))
    assert _PULL_REQUEST_GUARD in condition
    assert _REPOSITORY_GUARD in condition

    downloads = [
        step
        for step in _steps(job)
        if str(step.get("uses", "")).startswith("actions/download-artifact")
    ]
    assert len(downloads) == 1
    assert downloads[0]["with"]["name"] == "ci-lifecycle-evidence"

    verification = next(
        step for step in _steps(job) if "gh attestation verify" in str(step.get("run"))
    )
    run = str(verification["run"])
    assert verification["env"]["GH_TOKEN"] == "${{ github.token }}"
    assert 'gh attestation verify "$artifact"' in run
    assert '--repo "${{ github.repository }}"' in run
    assert (
        '--signer-workflow "${{ github.repository }}/.github/workflows/ci.yml"' in run
    )
    assert 'for artifact in "${wheels[0]}" "${sdists[0]}" SHA256SUMS; do' in run
    assert "sha256sum --check --strict SHA256SUMS" in run


def test_lifecycle_confirm_requires_provenance_or_the_documented_fork_skip() -> None:
    """R2: stage 4 rejects a build whose provenance cannot be verified."""
    workflow = _load("ci.yml")
    confirm = workflow["jobs"]["lifecycle-confirm"]
    assert "provenance-verify" in confirm["needs"]

    step = next(
        step for step in _steps(confirm) if "PROVENANCE" in str(step.get("env"))
    )
    assert step["env"]["PROVENANCE"] == "${{ needs.provenance-verify.result }}"
    run = str(step["run"])

    assert 'test "$PROVENANCE" = success' in run
    assert 'test "$PROVENANCE" = skipped' in run
    assert "Fork PR:" in run

    assert "lifecycle-confirm" in workflow["jobs"]["lifecycle-accept"]["needs"]


def test_release_workflow_triggers_only_on_version_tags() -> None:
    """R3: no branch push and no manual dispatch can create a release."""
    workflow = _load("release.yml")
    triggers = _triggers(workflow)

    assert set(triggers) == {"push"}
    assert triggers["push"] == {"tags": ["v*"]}

    text = _text("release.yml")
    assert "branches" not in text
    assert "workflow_dispatch" not in text


def test_release_workflow_attests_verifies_then_creates_the_release() -> None:
    """R3: build + attest, verify, then scope ``contents: write`` to the release."""
    workflow = _load("release.yml")
    jobs = workflow["jobs"]

    attest_steps = [
        step
        for job in jobs.values()
        for step in _steps(job)
        if str(step.get("uses", "")).startswith(_ATTEST_ACTION)
    ]
    assert len(attest_steps) == 1
    assert attest_steps[0]["uses"] == _ATTEST_PIN
    assert attest_steps[0]["with"] == {"subject-path": "dist/*"}

    build = jobs["build"]
    assert build["permissions"] == {
        "contents": "read",
        "id-token": "write",
        "attestations": "write",
    }
    build_runs = _job_runs(build)
    # The same two-pass reproducible-build contract CI runs.
    assert "for pass in 1 2; do" in build_runs
    assert "diff -u .artifact-hashes-1 .artifact-hashes-2" in build_runs
    assert "git archive --format=tar HEAD" in build_runs
    assert "sha256sum --check --strict SHA256SUMS" in build_runs

    verify_runs = _job_runs(jobs["verify"])
    assert 'gh attestation verify "$artifact"' in verify_runs
    assert '--repo "${{ github.repository }}"' in verify_runs
    assert (
        '--signer-workflow "${{ github.repository }}/.github/workflows/release.yml"'
        in verify_runs
    )

    release = jobs["release"]
    assert release["permissions"] == {"contents": "write"}
    assert set(release["needs"]) == {"build", "verify"}
    release_runs = _job_runs(release)
    assert "gh release create" in release_runs
    assert "--verify-tag" in release_runs
    assert "dist/*" in release_runs
    assert "sha256sum --check --strict SHA256SUMS" in release_runs

    for job_name, job in jobs.items():
        permissions = job.get("permissions") or {}
        if job_name != "release":
            assert permissions.get("contents") != "write", job_name


def test_verification_cross_checks_attested_digests_against_the_checksums() -> None:
    """R2/R3: an attestation for different bytes must not pass the gate."""
    for workflow_name, job_name in (
        ("ci.yml", "provenance-verify"),
        ("release.yml", "verify"),
    ):
        run = _job_runs(_load(workflow_name)["jobs"][job_name])
        assert "--format json" in run, workflow_name
        # The expected digest comes from the checksum file the build wrote...
        assert 'Path("SHA256SUMS").read_text(encoding="utf-8")' in run
        # ...and the attested digest comes from the verified statement.
        assert 'digest.get("sha256")' in run
        assert "if expected not in attested:" in run
        assert "sys.exit(1)" in run


def test_no_pypi_publishing_surface_exists_in_the_repository() -> None:
    """R3: nothing anywhere may publish to a package index.

    The frozen ``docs/08-archive/`` record keeps historical text verbatim, so
    only the live documentation and the whole ``.github/`` tree are scanned.
    This test module itself is the one file that names the forbidden tokens on
    purpose, so ``tests/`` is not a scan target.
    """
    scanned = [
        path
        for path in (_ROOT / ".github").rglob("*")
        if path.is_file() and path.suffix in {".yml", ".yaml", ".md", ".toml", ".json"}
    ]
    scanned.append(_ROOT / "pyproject.toml")
    scanned.append(_ROOT / "README.md")
    scanned.extend(
        path
        for path in (_ROOT / "docs").rglob("*.md")
        if "docs/08-archive" not in path.as_posix()
    )
    scanned.extend((_ROOT / "tools").glob("*.py"))
    assert len(scanned) > 10

    offenders = []
    for path in sorted(scanned):
        # Whitespace is collapsed so a command wrapped across two lines (the
        # markdownlint-friendly form) cannot hide a forbidden token.
        normalized = " ".join(path.read_text(encoding="utf-8").lower().split())
        for token in _FORBIDDEN_PUBLISH_TOKENS:
            if token in normalized:
                offenders.append(f"{path.relative_to(_ROOT)}: {token}")

    assert not offenders, "PyPI publishing surfaces are forbidden:\n" + "\n".join(
        offenders
    )
