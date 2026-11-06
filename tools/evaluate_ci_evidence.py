"""Evaluate coverage.py and pytest-benchmark JSON evidence for CI."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path


class EvidenceError(ValueError):
    """Evidence is missing, malformed, or fails a CI requirement."""


def read_json(path: Path, label: str) -> object:
    try:
        with path.open(encoding="utf-8") as stream:
            return json.load(stream)
    except (OSError, UnicodeError, ValueError) as error:
        raise EvidenceError(f"{label} {path}: {error}") from error


def require_object(value: object, label: str) -> dict:
    if not isinstance(value, dict):
        raise EvidenceError(f"{label} must be an object")
    return value


def coverage_results(data: object) -> tuple[list[str], bool]:
    totals = require_object(
        require_object(data, "coverage").get("totals"), "coverage totals"
    )
    messages = []
    passed = True
    for label, covered_key, total_key, threshold in (
        ("statement", "covered_lines", "num_statements", 95),
        ("branch", "covered_branches", "num_branches", 91),
    ):
        covered, total = totals.get(covered_key), totals.get(total_key)
        if type(covered) is not int or covered < 0:
            raise EvidenceError(
                f"coverage totals.{covered_key} must be a nonnegative integer"
            )
        if type(total) is not int or total <= 0:
            raise EvidenceError(
                f"coverage totals.{total_key} must be a positive integer"
            )
        if covered > total:
            raise EvidenceError(f"coverage totals.{covered_key} exceeds {total_key}")
        meets_threshold = covered * 100 >= total * threshold
        passed &= meets_threshold
        # The counts and threshold preserve the exact result even when the displayed rate rounds.
        rate = covered / total * 100
        messages.append(
            f"{label} coverage: {covered}/{total} ({rate:.6f}%); "
            f"required >= {threshold}%: {'PASS' if meets_threshold else 'FAIL'}"
        )
    return messages, passed


def benchmark_results(data: object) -> list[str]:
    benchmarks = require_object(data, "benchmark").get("benchmarks")
    if not isinstance(benchmarks, list) or len(benchmarks) != 5:
        raise EvidenceError("benchmark benchmarks must be a list of exactly 5 results")
    messages = []
    for index, result in enumerate(benchmarks, 1):
        label = f"benchmark result {index}"
        stats = require_object(
            require_object(result, label).get("stats"), f"{label} stats"
        )
        rounds, mean = stats.get("rounds"), stats.get("mean")
        if type(rounds) is not int or rounds <= 0:
            raise EvidenceError(f"{label} stats.rounds must be a positive integer")
        if (
            type(mean) not in (int, float)
            or mean < 0
            or (isinstance(mean, float) and not math.isfinite(mean))
        ):
            raise EvidenceError(f"{label} stats.mean must be finite and nonnegative")
        messages.append(f"{label}: {rounds} rounds, mean {mean}")
    return messages


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coverage", type=Path, required=True)
    parser.add_argument("--benchmark", type=Path, required=True)
    args = parser.parse_args()
    try:
        coverage_messages, passed = coverage_results(
            read_json(args.coverage, "coverage")
        )
        benchmark_messages = benchmark_results(read_json(args.benchmark, "benchmark"))
    except EvidenceError as error:
        print(f"CI evidence invalid: {error}", file=sys.stderr)
        return 1
    print("\n".join(coverage_messages + benchmark_messages))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
