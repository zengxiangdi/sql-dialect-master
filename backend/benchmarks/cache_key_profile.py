#!/usr/bin/env python3
"""Profile SQL transpiler cache-key construction without changing production code."""

import argparse
import hashlib
import json
import platform
import time
from statistics import mean, median
from typing import Callable, Dict, List

from backend.core.config import settings
from backend.core.transpiler import SQLTranspiler


def measure(capture: Callable[[], object], repeats: int) -> List[float]:
    """Capture repeated wall-clock measurements."""
    timings: List[float] = []
    for _ in range(repeats):
        start = time.perf_counter()
        capture()
        timings.append(time.perf_counter() - start)
    return timings


def build_rule_payload(transpiler: SQLTranspiler) -> str:
    """Reproduce the rule-payload portion of `_cache_key()` in benchmark code."""
    return "\n".join(
        "|".join(
            [
                rule.name,
                rule.source,
                rule.target,
                rule.pattern,
                rule.replacement,
                rule.note,
                rule.category.value,
                str(rule.priority),
                str(rule.enabled),
            ]
        )
        for rule in transpiler.post_processor.engine.rules
    )


def hash_rule_payload(payload: str) -> str:
    """Reproduce the rule-version hash used by `_cache_key()`."""
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def measure_direct_key(
    transpiler: SQLTranspiler,
    sql: str,
    source: str,
    target: str,
    pretty: bool,
    validate: bool,
    repeats: int,
) -> List[float]:
    """Measure the production `_cache_key()` end-to-end."""
    return measure(
        lambda: transpiler._cache_key(sql, source, target, pretty, validate), repeats
    )


def measure_payload(transpiler: SQLTranspiler, repeats: int) -> List[float]:
    """Measure rule payload construction alone."""
    return measure(lambda: build_rule_payload(transpiler), repeats)


def measure_hash(transpiler: SQLTranspiler, repeats: int) -> List[float]:
    """Measure rule payload hashing alone."""
    payload = build_rule_payload(transpiler)
    return measure(lambda: hash_rule_payload(payload), repeats)


def run(repeats: int) -> Dict[str, object]:
    """Run the cache-key profile for one representative request."""
    transpiler = SQLTranspiler()
    sql = "SELECT id, name FROM users WHERE id > 100"
    source = "mysql"
    target = "postgres"
    pretty = False
    validate = False

    previous_security = settings.security_check_enabled
    try:
        settings.security_check_enabled = False
        direct = measure_direct_key(
            transpiler, sql, source, target, pretty, validate, repeats
        )
        payload = measure_payload(transpiler, repeats)
        hashing = measure_hash(transpiler, repeats)
    finally:
        settings.security_check_enabled = previous_security

    direct_mean = mean(direct)
    payload_mean = mean(payload)
    hash_mean = mean(hashing)

    return {
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
        "workload": {
            "repeats": repeats,
            "source": source,
            "target": target,
            "pretty": pretty,
            "validate": validate,
            "rule_count": len(transpiler.post_processor.engine.rules),
            "rule_payload_bytes": len(build_rule_payload(transpiler).encode("utf-8")),
        },
        "measurements": {
            "cache_key": {
                "mean_seconds": direct_mean,
                "median_seconds": median(direct),
                "per_call_us": direct_mean * 1_000_000,
                "timings_seconds": direct,
            },
            "rule_payload_build": {
                "mean_seconds": payload_mean,
                "median_seconds": median(payload),
                "per_call_us": payload_mean * 1_000_000,
                "timings_seconds": payload,
            },
            "rule_version_hash": {
                "mean_seconds": hash_mean,
                "median_seconds": median(hashing),
                "per_call_us": hash_mean * 1_000_000,
                "timings_seconds": hashing,
            },
        },
        "analysis": {
            "payload_share_of_cache_key_percent": (
                payload_mean / direct_mean * 100.0 if direct_mean else 0.0
            ),
            "hash_share_of_cache_key_percent": (
                hash_mean / direct_mean * 100.0 if direct_mean else 0.0
            ),
        },
        "mutation_constraints": [
            "RuleEngine.add_rule() changes the rule list and sorts it.",
            "RuleEngine.enable_rule() and disable_rule() mutate rule.enabled in place.",
            "Therefore a cached rule-version snapshot is only safe when these mutations also refresh the snapshot/invalidation token.",
        ],
        "notes": [
            "This profiler reproduces the production cache-key calculation in benchmark code.",
            "No production implementation is modified by this profiler.",
            "Timing results are observational and do not define a pass/fail latency threshold.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=1000)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("repeats must be >= 1")
    print(json.dumps(run(args.repeats), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
