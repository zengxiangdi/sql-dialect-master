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
        """Create a deterministic cache key; MD5 is explicitly non-security use."""
        content = str(args) + str(sorted(kwargs.items()))
        return hashlib.md5(content.encode(), usedforsecurity=False).hexdigest()

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
            Cached value or None
        """
        with self._lock:
            _, value = self._get_value(key)
            return value
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Set cache value."""
        with self._lock:
            effective_ttl = self._ttl if ttl is None else ttl
            self._cache[key] = CacheEntry(value=value, created_at=time.time(), ttl=effective_ttl)
            self._cache.move_to_end(key)
            while len(self._cache) > self._max_size:
                self._cache.popitem(last=False)
                self._evictions += 1

    def delete(self, key: str) -> bool:
        """Delete a cache entry."""
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False

    def clear(self) -> None:
        """Clear all cache entries."""
        with self._lock:
            self._cache.clear()

    def stats(self) -> Dict[str, Any]:
        """Return cache statistics."""
        with self._lock:
            return {
                "size": len(self._cache),
                "max_size": self._max_size,
                "ttl": self._ttl,
                "hits": self._hits,
                "misses": self._misses,
                "evictions": self._evictions,
            }
