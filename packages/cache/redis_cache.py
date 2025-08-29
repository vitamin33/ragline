import json
import os
import random
from contextlib import asynccontextmanager
from typing import Any, Optional

import redis.asyncio as redis
import structlog

logger = structlog.get_logger(__name__)


class RedisCache:
    """Redis caching implementation with cache-aside pattern and stampede protection."""

    def __init__(
        self,
        redis_url: Optional[str] = None,
        default_ttl: int = 300,  # 5 minutes
        jitter_range: int = 60,  # 0-60 seconds jitter
        lock_timeout: int = 30,  # Lock timeout in seconds
        key_prefix: str = "ragline",
    ):
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self.default_ttl = default_ttl
        self.jitter_range = jitter_range
        self.lock_timeout = lock_timeout
        self.key_prefix = key_prefix
        self._client: Optional[redis.Redis] = None

    async def get_client(self) -> redis.Redis:
        """Get Redis client with connection pooling."""
        if self._client is None:
            self._client = redis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True,
                socket_keepalive=True,
                socket_keepalive_options={},
                health_check_interval=30,
            )
        return self._client

    def _build_key(self, tenant_id: int, cache_type: str, identifier: str) -> str:
        """Build cache key with tenant isolation."""
        return f"{self.key_prefix}:{tenant_id}:cache:{cache_type}:{identifier}"

    def _build_lock_key(self, tenant_id: int, resource_type: str, identifier: str) -> str:
        """Build distributed lock key."""
        return f"{self.key_prefix}:{tenant_id}:lock:{resource_type}:{identifier}"

    def _calculate_ttl_with_jitter(self, base_ttl: Optional[int] = None) -> int:
        """Calculate TTL with jitter to prevent thundering herd."""
        ttl = base_ttl or self.default_ttl
        jitter = random.randint(0, self.jitter_range)
        return ttl + jitter

    async def get(self, tenant_id: int, cache_type: str, identifier: str) -> Optional[Any]:
        """Get value from cache."""
        try:
            client = await self.get_client()
            key = self._build_key(tenant_id, cache_type, identifier)

            value = await client.get(key)
            if value is None:
                logger.debug("Cache miss", key=key)
                return None

            logger.debug("Cache hit", key=key)
            return json.loads(value)

        except Exception as e:
            logger.error("Cache get failed", key=key, error=str(e))
            return None

    async def set(
        self,
        tenant_id: int,
        cache_type: str,
        identifier: str,
        value: Any,
        ttl: Optional[int] = None,
    ) -> bool:
        """Set value in cache with TTL and jitter."""
        try:
            client = await self.get_client()
            key = self._build_key(tenant_id, cache_type, identifier)

            # Serialize value
            serialized_value = json.dumps(value, default=str)

            # Calculate TTL with jitter
            cache_ttl = self._calculate_ttl_with_jitter(ttl)

            # Set value with expiration
            await client.setex(key, cache_ttl, serialized_value)

            logger.debug("Cache set", key=key, ttl=cache_ttl)
            return True

        except Exception as e:
            logger.error("Cache set failed", key=key, error=str(e))
            return False

    async def delete(self, tenant_id: int, cache_type: str, identifier: str) -> bool:
        """Delete value from cache."""
        try:
            client = await self.get_client()
            key = self._build_key(tenant_id, cache_type, identifier)

            result = await client.delete(key)
            logger.debug("Cache delete", key=key, existed=bool(result))
            return bool(result)

        except Exception as e:
            logger.error("Cache delete failed", key=key, error=str(e))
            return False

    async def delete_pattern(self, tenant_id: int, cache_type: str, pattern: str = "*") -> int:
        """Delete multiple keys matching a pattern."""
        try:
            client = await self.get_client()
            search_pattern = self._build_key(tenant_id, cache_type, pattern)

            keys = await client.keys(search_pattern)
            if keys:
                deleted = await client.delete(*keys)
                logger.debug("Cache pattern delete", pattern=search_pattern, deleted=deleted)
                return deleted
            return 0

        except Exception as e:
            logger.error("Cache pattern delete failed", pattern=pattern, error=str(e))
            return 0

    @asynccontextmanager
    async def distributed_lock(
        self,
        tenant_id: int,
        resource_type: str,
        identifier: str,
        timeout: Optional[int] = None,
    ):
        """Distributed lock to prevent cache stampede."""
        lock_key = self._build_lock_key(tenant_id, resource_type, identifier)
        lock_timeout = timeout or self.lock_timeout
        client = await self.get_client()

        # Try to acquire lock
        lock_acquired = await client.set(
            lock_key,
            "locked",
            nx=True,  # Only set if not exists
            ex=lock_timeout,  # Expiration
        )

        if not lock_acquired:
            logger.debug("Lock acquisition failed", lock_key=lock_key)
            raise RuntimeError(f"Could not acquire lock: {lock_key}")

        logger.debug("Lock acquired", lock_key=lock_key)

        try:
            yield
        finally:
            # Release lock
            try:
                await client.delete(lock_key)
                logger.debug("Lock released", lock_key=lock_key)
            except Exception as e:
                logger.error("Lock release failed", lock_key=lock_key, error=str(e))

    async def get_or_set(
        self,
        tenant_id: int,
        cache_type: str,
        identifier: str,
        fetch_func,
        ttl: Optional[int] = None,
        use_lock: bool = True,
    ) -> Optional[Any]:
        """
        Cache-aside pattern with optional stampede protection.

        Args:
            tenant_id: Tenant identifier
            cache_type: Type of cached data (e.g., 'product')
            identifier: Unique identifier for the cached item
            fetch_func: Async function to fetch data if not in cache
            ttl: Cache TTL in seconds
            use_lock: Whether to use distributed lock for stampede protection
        """
        # Try to get from cache first
        cached_value = await self.get(tenant_id, cache_type, identifier)
        if cached_value is not None:
            return cached_value

        # Cache miss - need to fetch and cache
        if use_lock:
            try:
                async with self.distributed_lock(tenant_id, cache_type, identifier):
                    # Double-check cache after acquiring lock
                    cached_value = await self.get(tenant_id, cache_type, identifier)
                    if cached_value is not None:
                        return cached_value

                    # Fetch fresh data
                    fresh_value = await fetch_func()
                    if fresh_value is not None:
                        await self.set(tenant_id, cache_type, identifier, fresh_value, ttl)

                    return fresh_value
            except RuntimeError:
                # Lock acquisition failed - proceed without lock to avoid blocking
                logger.warning("Lock failed, proceeding without stampede protection")
                fresh_value = await fetch_func()
                if fresh_value is not None:
                    # Try to cache (might race with other instances)
                    await self.set(tenant_id, cache_type, identifier, fresh_value, ttl)
                return fresh_value
        else:
            # No lock protection
            fresh_value = await fetch_func()
            if fresh_value is not None:
                await self.set(tenant_id, cache_type, identifier, fresh_value, ttl)
            return fresh_value

    async def invalidate_product_cache(self, tenant_id: int, product_id: Optional[int] = None):
        """Invalidate product cache for a tenant."""
        if product_id:
            # Invalidate specific product
            await self.delete(tenant_id, "product", str(product_id))
        else:
            # Invalidate all products for tenant
            await self.delete_pattern(tenant_id, "product", "*")

        # Also invalidate product lists
        await self.delete_pattern(tenant_id, "products", "*")

        logger.info("Product cache invalidated", tenant_id=tenant_id, product_id=product_id)

    async def close(self):
        """Close Redis connection."""
        if self._client:
            await self._client.close()
            self._client = None


# Global cache instance
cache = RedisCache()


async def get_cache() -> RedisCache:
    """Dependency to get Redis cache instance."""
    return cache
