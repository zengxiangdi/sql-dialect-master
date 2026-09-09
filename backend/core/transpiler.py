"""SQL transpiler core implementation."""

from typing import List, Dict, Any
import asyncio

# ...

    async def batch_transpile_async(self, statements: List[str], source: str, target: str, pretty: bool = True, max_concurrent: int = 10) -> List[TranspileResult]:
        if not isinstance(statements, list):
            raise ValidationError("statements must be a list", field="statements", value=type(statements).__name__)
        if len(statements) > settings.max_batch_size:
            raise ValidationError(f"Batch contains {len(statements)} statements; maximum is {settings.max_batch_size}", field="statements", value=str(len(statements)))
        if isinstance(max_concurrent, bool) or not isinstance(max_concurrent, int) or max_concurrent <= 0:
            raise ValidationError("max_concurrent must be a positive integer", field="max_concurrent", value=str(max_concurrent))
        semaphore = asyncio.Semaphore(max_concurrent)

        async def limited_transpile(sql: str) -> TranspileResult:
            async with semaphore:
                loop = asyncio.get_running_loop()
                return await loop.run_in_executor(None, lambda: self.transpile(sql, source, target, pretty))

        return await asyncio.gather(*(limited_transpile(sql) for sql in statements))

    def get_supported_dialects(self) -> List[str]:
        return SUPPORTED_DIALECTS.copy()

    def get_stats(self) -> Dict[str, Any]:
        return {
            "supported_dialects": len(SUPPORTED_DIALECTS),
            "dialects": SUPPORTED_DIALECTS,
            "post_processor": self.post_processor.get_stats(),
            "cache": self._cache.get_stats() if self._cache_enabled else {"enabled": False},
            "security": {"enabled": self._security_enabled, "block_dangerous": settings.security_block_dangerous},
            "settings": {"cache_enabled": self._cache_enabled, "max_batch_size": settings.max_batch_size, "max_sql_length": settings.transpiler_max_sql_length}
        }

    def clear_cache(self) -> None:
        if self._cache_enabled:
            self._cache.clear()
            logger.info("Transpile cache cleared")
