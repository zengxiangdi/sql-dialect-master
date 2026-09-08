#!/usr/bin/env python3
"""Unified caching module for SQL Dialect Master.

Provides thread-safe caching with TTL support.
"""
import hashlib
import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Callable

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """A single cache entry with metadata."""
    value: Any
    created_at: float
    ttl: int
    hits: int = 0
    
    def is_expired(self) -> bool:
        """Check if entry has expired."""
        if self.ttl <= 0:
            return False
        return time.time() - self.created_at > self.ttl


class TTLCache:
    """Thread-safe LRU cache with TTL support.
    
    Features:
    - Time-to-live expiration
    - LRU eviction when max size reached
    - Thread-safe operations
    - Hit/miss statistics
    """
    
    def __init__(self, max_size: int = 1000, ttl: int = 300):
        """Initialize cache.
        
        Args:
            max_size: Maximum number of entries
            ttl: Time-to-live in seconds (0 = no expiration)
        """
        if max_size <= 0:
            raise ValueError("max_size must be greater than 0")
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._max_size = max_size
        self._ttl = ttl
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0
        self._evictions = 0
    
    def _make_key(self, *args, **kwargs) -> str:
        """Create cache key from arguments."""
        content = str(args) + str(sorted(kwargs.items()))
        return hashlib.md5(content.encode()).hexdigest()

    def _get_value(self, key: str) -> tuple[bool, Any]:
        """Get a cached value while preserving the distinction between None and a miss."""
        if key not in self._cache:
            self._misses += 1
            return False, None

        entry = self._cache[key]

        if entry.is_expired():
            del self._cache[key]
            self._misses += 1
            logger.debug(f"Cache entry expired: {key[:8]}...")
            return False, None

        self._cache.move_to_end(key)
        entry.hits += 1
        self._hits += 1
        logger.debug(f"Cache hit: {key[:8]}...")
        return True, entry.value
    
    def get(self, key: str) -> Optional[Any]:
        """Get value from cache.
        
        Args:
            key: Cache key
            
        Returns:
            Cached value or None if not found/expired
        """
        with self._lock:
            found, value = self._get_value(key)
            return value if found else None
    
    def set(self, key: str, value: Any, ttl: int = None) -> None:
        """Store value in cache.
        
        Args:
            key: Cache key
            value: Value to cache
            ttl: Optional TTL override
        """
        with self._lock:
            if key in self._cache:
                self._cache[key] = CacheEntry(
                    value=value,
                    created_at=time.time(),
                    ttl=ttl if ttl is not None else self._ttl
                )
                self._cache.move_to_end(key)
                logger.debug(f"Cache updated: {key[:8]}...")
                return

            # Remove oldest if at capacity.
            if len(self._cache) >= self._max_size:
                oldest_key = next(iter(self._cache))
                del self._cache[oldest_key]
                self._evictions += 1
                logger.debug(f"Cache eviction: {oldest_key[:8]}...")
            
            self._cache[key] = CacheEntry(
                value=value,
                created_at=time.time(),
                ttl=ttl if ttl is not None else self._ttl
            )
            logger.debug(f"Cache set: {key[:8]}...")
    
    def delete(self, key: str) -> bool:
        """Delete entry from cache.
        
        Args:
            key: Cache key
            
        Returns:
            True if entry was deleted
        """
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False
    
    def clear(self) -> None:
        """Clear all cached entries."""
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0
            self._evictions = 0
            logger.info("Cache cleared")
    
    def cleanup_expired(self) -> int:
        """Remove all expired entries.
        
        Returns:
            Number of entries removed
        """
        with self._lock:
            expired_keys = [
                key for key, entry in self._cache.items()
                if entry.is_expired()
            ]
            for key in expired_keys:
                del self._cache[key]
            
            if expired_keys:
                logger.debug(f"Cleaned up {len(expired_keys)} expired entries")
            return len(expired_keys)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics.
        
        Returns:
            Dictionary with cache stats
        """
        with self._lock:
            total = self._hits + self._misses
            hit_rate = (self._hits / total * 100) if total > 0 else 0
            
            return {
                "size": len(self._cache),
                "max_size": self._max_size,
                "ttl": self._ttl,
                "hits": self._hits,
                "misses": self._misses,
                "evictions": self._evictions,
                "hit_rate": f"{hit_rate:.1f}%"
            }
    
    def __len__(self) -> int:
        return len(self._cache)
    
    def __contains__(self, key: str) -> bool:
        with self._lock:
            if key not in self._cache:
                return False
            return not self._cache[key].is_expired()
    
    def get_or_set(self, key: str, factory: Callable[[], Any], ttl: int = None) -> Any:
        """Get value from cache, or compute and cache if missing.
        
        This provides atomic get-or-set functionality to avoid race conditions.
        
        Args:
            key: Cache key
            factory: Callable that returns the value if not cached
            ttl: Optional TTL override
            
        Returns:
            Cached or computed value
        """
        with self._lock:
            found, value = self._get_value(key)
            if found:
                return value
            
            # Compute value while holding the reentrant lock so competing
            # callers cannot publish a second value for the same key.
            value = factory()
            self.set(key, value, ttl)
            return value
    
    async def get_async(self, key: str) -> Optional[Any]:
        """Async version of get - runs in thread pool.
        
        Args:
            key: Cache key
            
        Returns:
            Cached value or None
        """
        import asyncio
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.get, key)
    
    async def set_async(self, key: str, value: Any, ttl: int = None) -> None:
        """Async version of set - runs in thread pool.
        
        Args:
            key: Cache key
            value: Value to cache
            ttl: Optional TTL override
        """
        import asyncio
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, lambda: self.set(key, value, ttl))
    
    def start_background_cleanup(self, interval: int = 60) -> threading.Thread:
        """Start a background daemon thread for periodic cache cleanup.
        
        Args:
            interval: Cleanup interval in seconds
            
        Returns:
            The cleanup thread (already started)
        """
        if interval <= 0:
            raise ValueError("interval must be positive")

        def cleanup_loop():
            while True:
                time.sleep(interval)
                try:
                    removed = self.cleanup_expired()
                    if removed > 0:
                        logger.info(f"Background cleanup removed {removed} expired entries")
                except Exception as e:
                    logger.error(f"Background cleanup error: {e}")
        
        thread = threading.Thread(target=cleanup_loop, daemon=True, name="CacheCleanup")
        thread.start()
        logger.info(f"Started background cache cleanup (interval={interval}s)")
        return thread


class CachedFunction:
    """Decorator for caching function results."""
    
    def __init__(self, cache: TTLCache = None, key_func: Callable = None):
        """Initialize decorator.
        
        Args:
            cache: Cache instance to use
            key_func: Optional function to generate cache key
        """
        self._cache = cache if cache is not None else TTLCache()
        self._key_func = key_func
    
    def __call__(self, func: Callable) -> Callable:
        def wrapper(*args, **kwargs):
            if self._key_func:
                key = self._key_func(*args, **kwargs)
            else:
                key = self._cache._make_key(func.__name__, *args, **kwargs)
            
            with self._cache._lock:
                found, value = self._cache._get_value(key)
            if found:
                return value
            
            value = func(*args, **kwargs)
            self._cache.set(key, value)
            return value
        
        wrapper.__name__ = func.__name__
        wrapper.__doc__ = func.__doc__
        wrapper.cache = self._cache
        return wrapper


# Global cache instances
transpile_cache = TTLCache(max_size=1000, ttl=300)
function_cache = TTLCache(max_size=500, ttl=600)
type_cache = TTLCache(max_size=200, ttl=600)
