from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


def test_downstream_pyrefly_understands_lazy_public_exports() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    fixture = repo_root / "tests" / "typecheck" / "public_api.py"
    pyrefly = Path(sys.executable).with_name("pyrefly")
    if not pyrefly.exists():
        discovered = shutil.which("pyrefly")
        assert discovered is not None, (
            "pyrefly is not installed in the test environment"
        )
        pyrefly = Path(discovered)

    result = subprocess.run(
        [str(pyrefly), "check", str(fixture)],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )

    output = "\n".join(part for part in (result.stdout, result.stderr) if part)
    assert result.returncode == 0, output
