#!/usr/bin/env python3
"""Validate the cache-key profiling output contract."""

from backend.benchmarks.cache_key_profile import run


def test_cache_key_profile_shape() -> None:
    payload = run(repeats=2)

    for key in ("environment", "workload", "measurements", "analysis", "mutation_constraints", "notes"):
        if key not in payload:
            raise RuntimeError(f"missing profiling key: {key}")

    measurements = payload["measurements"]
    for key in ("cache_key", "rule_payload_build", "rule_version_hash"):
        if key not in measurements:
            raise RuntimeError(f"missing measurement: {key}")
        if measurements[key]["mean_seconds"] < 0:
            raise RuntimeError(f"negative timing for {key}")

    if payload["workload"]["rule_count"] < 1:
        raise RuntimeError("expected at least one rule")
    if payload["workload"]["rule_payload_bytes"] <= 0:
        raise RuntimeError("expected non-empty rule payload")
