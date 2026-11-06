"""Exercise the CI evidence evaluator through its command-line interface."""

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "evaluate_ci_evidence.py"
COVERAGE = {
    "totals": {
        "covered_lines": 95,
        "num_statements": 100,
        "covered_branches": 91,
        "num_branches": 100,
    }
}
BENCHMARK = {"benchmarks": [{"stats": {"rounds": 1, "mean": 0.0}} for _ in range(5)]}


class EvidenceTests(unittest.TestCase):
    def run_evaluator(self, coverage=COVERAGE, benchmark=BENCHMARK):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            coverage_path, benchmark_path = (
                root / "coverage.json",
                root / "benchmark.json",
            )
            coverage_path.write_text(json.dumps(coverage), encoding="utf-8")
            benchmark_path.write_text(json.dumps(benchmark), encoding="utf-8")
            return subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--coverage",
                    str(coverage_path),
                    "--benchmark",
                    str(benchmark_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

    def test_exact_boundaries_and_zero_mean_pass(self):
        result = self.run_evaluator()
        assert result.returncode == 0, result.stderr
        assert "statement coverage: 95/100 (95.000000%)" in result.stdout
        assert "branch coverage: 91/100 (91.000000%)" in result.stdout
        assert "benchmark result 5: 1 rounds, mean 0.0" in result.stdout

    def test_just_below_each_boundary_fails(self):
        for covered, total, value, label in (
            ("covered_lines", "num_statements", 9499, "statement"),
            ("covered_branches", "num_branches", 9099, "branch"),
        ):
            with self.subTest(label=label):
                coverage = copy.deepcopy(COVERAGE)
                coverage["totals"].update({covered: value, total: 10000})
                result = self.run_evaluator(coverage)
                assert result.returncode != 0
                assert f"{label} coverage:" in result.stdout
                assert "FAIL" in result.stdout

    def test_invalid_coverage_counts(self):
        for key, value in (
            ("num_statements", 0),
            ("num_branches", 0),
            ("covered_lines", -1),
            ("covered_branches", 101),
            ("covered_lines", True),
            ("num_branches", 1.5),
            ("covered_lines", float("nan")),
            ("num_statements", float("inf")),
        ):
            with self.subTest(key=key, value=value):
                coverage = copy.deepcopy(COVERAGE)
                coverage["totals"][key] = value
                result = self.run_evaluator(coverage)
                assert result.returncode != 0
                assert key in result.stderr

    def test_missing_or_malformed_coverage(self):
        for coverage in ({}, {"totals": []}, {"totals": {}}, [], None):
            with self.subTest(coverage=coverage):
                result = self.run_evaluator(coverage)
                assert result.returncode != 0
                assert "coverage" in result.stderr

    def test_invalid_benchmarks(self):
        cases = [
            {},
            {"benchmarks": []},
            {"benchmarks": [None] * 5},
            {"benchmarks": [{"stats": {}}] * 5},
            {"benchmarks": BENCHMARK["benchmarks"] + [BENCHMARK["benchmarks"][0]]},
        ]
        for key, value in (
            ("rounds", 0),
            ("rounds", -1),
            ("rounds", 1.5),
            ("rounds", True),
            ("mean", -1),
            ("mean", True),
            ("mean", None),
            ("mean", float("nan")),
            ("mean", float("inf")),
            ("mean", -float("inf")),
        ):
            benchmark = copy.deepcopy(BENCHMARK)
            benchmark["benchmarks"][2]["stats"][key] = value
            cases.append(benchmark)
        for benchmark in cases:
            with self.subTest(benchmark=benchmark):
                result = self.run_evaluator(benchmark=benchmark)
                assert result.returncode != 0
                assert "benchmark" in result.stderr

    def test_missing_file_and_invalid_json(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            missing, invalid = root / "missing.json", root / "invalid.json"
            invalid.write_text("{", encoding="utf-8")
            for coverage in (missing, invalid):
                result = subprocess.run(
                    [
                        sys.executable,
                        str(SCRIPT),
                        "--coverage",
                        str(coverage),
                        "--benchmark",
                        str(missing),
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                assert result.returncode != 0
                assert str(coverage) in result.stderr
                assert "Traceback" not in result.stderr


if __name__ == "__main__":
    unittest.main()
