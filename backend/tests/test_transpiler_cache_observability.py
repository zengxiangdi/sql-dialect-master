from backend.core.transpiler import SQLTranspiler


def test_transpiler_cache_stats_track_miss_and_hit() -> None:
    transpiler = SQLTranspiler()
    transpiler.clear_cache()

    before = transpiler.get_stats()["cache"]
    assert before["size"] == 0
    assert before["hits"] == 0
    assert before["misses"] == 0
    assert before["evictions"] == 0

    first = transpiler.transpile("SELECT 1", "postgres", "mysql")
    assert first.success is True

    after_first = transpiler.get_stats()["cache"]
    assert after_first["misses"] == 1
    assert after_first["hits"] == 0
    assert after_first["size"] == 1

    second = transpiler.transpile("SELECT 1", "postgres", "mysql")
    assert second.success is True
    assert second.target_sql == first.target_sql

    after_second = transpiler.get_stats()["cache"]
    assert after_second["misses"] == 1
    assert after_second["hits"] == 1
    assert after_second["size"] == 1
    assert after_second["hit_rate"] == "50.0%"
