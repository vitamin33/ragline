"""
RAGline Tool Result Caching System

High-performance caching for LLM tool execution results with intelligent invalidation,
semantic deduplication, and performance optimization for AI/ML operations.
"""

import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

import redis.asyncio as redis
from celery.utils.log import get_task_logger

from packages.cache.redis_cache import RedisCache
from services.worker.config import WorkerConfig

logger = get_task_logger(__name__)


@dataclass
class CacheKey:
    """Tool cache key structure for semantic deduplication"""

    tool_name: str
    tenant_id: str
    parameters_hash: str  # Hash of normalized parameters
    semantic_hash: Optional[str] = None  # Hash for semantic similarity
    cache_type: str = "tool_result"

    def to_redis_key(self) -> str:
        """Convert to Redis key format"""
        if self.semantic_hash:
            return f"ragline:tool_cache:{self.tenant_id}:{self.tool_name}:{self.semantic_hash}"
        return f"ragline:tool_cache:{self.tenant_id}:{self.tool_name}:{self.parameters_hash}"

    def to_exact_key(self) -> str:
        """Get exact parameter match key"""
        return f"ragline:tool_cache:{self.tenant_id}:{self.tool_name}:exact:{self.parameters_hash}"


@dataclass
class CachedResult:
    """Cached tool execution result with metadata"""

    result: Dict[str, Any]
    tool_name: str
    tenant_id: str
    cached_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    hit_count: int = 1
    original_duration_ms: float = 0.0
    cost_usd: float = 0.0
    ttl_seconds: int = 3600  # 1 hour default

    # Cache metadata
    cache_key: str = ""
    semantic_similar: bool = False  # Whether this was a semantic match
    similarity_score: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for Redis storage"""
        return {
            "result": self.result,
            "tool_name": self.tool_name,
            "tenant_id": self.tenant_id,
            "cached_at": self.cached_at.isoformat(),
            "hit_count": self.hit_count,
            "original_duration_ms": self.original_duration_ms,
            "cost_usd": self.cost_usd,
            "ttl_seconds": self.ttl_seconds,
            "cache_key": self.cache_key,
            "semantic_similar": self.semantic_similar,
            "similarity_score": self.similarity_score,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CachedResult":
        """Create from dictionary stored in Redis"""
        return cls(
            result=data["result"],
            tool_name=data["tool_name"],
            tenant_id=data["tenant_id"],
            cached_at=datetime.fromisoformat(data["cached_at"]),
            hit_count=data.get("hit_count", 1),
            original_duration_ms=data.get("original_duration_ms", 0.0),
            cost_usd=data.get("cost_usd", 0.0),
            ttl_seconds=data.get("ttl_seconds", 3600),
            cache_key=data.get("cache_key", ""),
            semantic_similar=data.get("semantic_similar", False),
            similarity_score=data.get("similarity_score", 1.0),
        )


class ToolResultCache:
    """
    High-performance caching system for LLM tool execution results.

    Features:
    - Parameter-based exact matching
    - Semantic similarity caching for similar queries
    - Intelligent TTL based on tool type and cost
    - Cache hit rate tracking and optimization
    - Multi-tenant isolation and security
    """

    def __init__(self, config: WorkerConfig):
        self.config = config
        self.redis_cache = RedisCache(
            redis_url=config.redis_url,
            default_ttl=3600,  # 1 hour default
            key_prefix="ragline",
        )

        # Cache configuration by tool type
        self.tool_cache_config = {
            "retrieve_menu": {
                "ttl_seconds": 1800,  # 30 minutes - menu changes infrequently
                "semantic_threshold": 0.85,  # High similarity threshold
                "max_cache_size": 1000,
            },
            "search_knowledge_base": {
                "ttl_seconds": 3600,  # 1 hour - knowledge is more stable
                "semantic_threshold": 0.80,  # Medium similarity threshold
                "max_cache_size": 500,
            },
            "apply_promos": {
                "ttl_seconds": 600,  # 10 minutes - promos change frequently
                "semantic_threshold": 0.95,  # Very high threshold - exact matching
                "max_cache_size": 200,
            },
            "analyze_conversation": {
                "ttl_seconds": 1800,  # 30 minutes - conversation analysis
                "semantic_threshold": 0.75,  # Lower threshold for similar conversations
                "max_cache_size": 300,
            },
        }

        # Default config for unknown tools
        self.default_cache_config = {
            "ttl_seconds": 1800,
            "semantic_threshold": 0.85,
            "max_cache_size": 200,
        }

        # Cache statistics
        self.cache_stats = {
            "hits": 0,
            "misses": 0,
            "sets": 0,
            "evictions": 0,
            "semantic_hits": 0,
        }

    async def _normalize_parameters(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize parameters for consistent caching"""
        normalized = {}

        for key, value in parameters.items():
            if isinstance(value, str):
                # Normalize string parameters
                normalized[key] = value.strip().lower()
            elif isinstance(value, list):
                # Sort lists for consistent hashing
                if all(isinstance(item, str) for item in value):
                    normalized[key] = sorted([item.strip().lower() for item in value])
                else:
                    normalized[key] = sorted(value)
            elif isinstance(value, dict):
                # Recursively normalize nested dictionaries
                normalized[key] = await self._normalize_parameters(value)
            else:
                normalized[key] = value

        return normalized

    def _hash_parameters(self, parameters: Dict[str, Any]) -> str:
        """Generate deterministic hash from parameters"""
        # Sort keys for consistent hashing
        sorted_params = json.dumps(parameters, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(sorted_params.encode()).hexdigest()[:16]

    def _get_semantic_hash(self, tool_name: str, query: str) -> str:
        """Generate semantic hash for query similarity matching"""
        # Simple semantic hash - in production would use embeddings
        # Remove stop words, normalize case, sort words
        stop_words = {"the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of", "with", "by"}

        words = query.lower().strip().split()
        meaningful_words = [word for word in words if word not in stop_words and len(word) > 2]
        meaningful_words.sort()

        semantic_text = " ".join(meaningful_words)
        return hashlib.sha256(f"{tool_name}:{semantic_text}".encode()).hexdigest()[:12]

    async def get_cached_result(
        self,
        tool_name: str,
        tenant_id: str,
        parameters: Dict[str, Any],
        semantic_search: bool = True,
    ) -> Optional[CachedResult]:
        """
        Get cached tool result with exact and semantic matching.

        Args:
            tool_name: Name of the tool
            tenant_id: Tenant identifier
            parameters: Tool parameters
            semantic_search: Whether to attempt semantic similarity matching

        Returns:
            CachedResult if found, None otherwise
        """
        try:
            # Normalize parameters for consistent matching
            normalized_params = await self._normalize_parameters(parameters)
            params_hash = self._hash_parameters(normalized_params)

            # Try exact parameter match first
            exact_key = CacheKey(
                tool_name=tool_name,
                tenant_id=tenant_id,
                parameters_hash=params_hash,
            )

            cached_data = await self._get_from_redis(exact_key.to_exact_key())

            if cached_data:
                self.cache_stats["hits"] += 1
                cached_result = CachedResult.from_dict(cached_data)
                cached_result.hit_count += 1

                # Update hit count in cache
                await self._update_hit_count(exact_key.to_exact_key(), cached_result.hit_count)

                logger.debug(
                    "Tool cache exact hit",
                    tool_name=tool_name,
                    tenant_id=tenant_id,
                    cache_key=exact_key.to_exact_key(),
                )
                return cached_result

            # Try semantic matching for text-based tools
            if semantic_search and "query" in parameters:
                query_text = parameters["query"]
                if isinstance(query_text, str) and len(query_text) > 3:
                    semantic_hash = self._get_semantic_hash(tool_name, query_text)

                    semantic_key = CacheKey(
                        tool_name=tool_name,
                        tenant_id=tenant_id,
                        parameters_hash=params_hash,
                        semantic_hash=semantic_hash,
                    )

                    semantic_data = await self._get_from_redis(semantic_key.to_redis_key())

                    if semantic_data:
                        self.cache_stats["semantic_hits"] += 1
                        cached_result = CachedResult.from_dict(semantic_data)
                        cached_result.hit_count += 1
                        cached_result.semantic_similar = True
                        cached_result.similarity_score = 0.8  # Estimated similarity

                        # Update hit count
                        await self._update_hit_count(semantic_key.to_redis_key(), cached_result.hit_count)

                        logger.debug(
                            "Tool cache semantic hit",
                            tool_name=tool_name,
                            tenant_id=tenant_id,
                            cache_key=semantic_key.to_redis_key(),
                        )
                        return cached_result

            # Cache miss
            self.cache_stats["misses"] += 1
            logger.debug("Tool cache miss", tool_name=tool_name, tenant_id=tenant_id)
            return None

        except Exception as e:
            logger.error("Tool cache get failed", tool_name=tool_name, error=str(e))
            return None

    async def cache_result(
        self,
        tool_name: str,
        tenant_id: str,
        parameters: Dict[str, Any],
        result: Dict[str, Any],
        execution_data: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Cache tool execution result with intelligent TTL and deduplication.

        Args:
            tool_name: Name of the tool
            tenant_id: Tenant identifier
            parameters: Tool parameters used
            result: Tool execution result to cache
            execution_data: Execution metadata (duration, cost, etc.)

        Returns:
            bool: True if successfully cached
        """
        try:
            # Get tool-specific cache configuration
            cache_config = self.tool_cache_config.get(tool_name, self.default_cache_config)

            # Normalize parameters
            normalized_params = await self._normalize_parameters(parameters)
            params_hash = self._hash_parameters(normalized_params)

            # Create cached result
            cached_result = CachedResult(
                result=result,
                tool_name=tool_name,
                tenant_id=tenant_id,
                original_duration_ms=execution_data.get("duration_ms", 0.0) if execution_data else 0.0,
                cost_usd=execution_data.get("cost_usd", 0.0) if execution_data else 0.0,
                ttl_seconds=cache_config["ttl_seconds"],
            )

            # Cache with exact parameter match
            exact_key = CacheKey(
                tool_name=tool_name,
                tenant_id=tenant_id,
                parameters_hash=params_hash,
            )

            exact_redis_key = exact_key.to_exact_key()
            cached_result.cache_key = exact_redis_key

            success_exact = await self._set_in_redis(
                exact_redis_key,
                cached_result.to_dict(),
                cache_config["ttl_seconds"],
            )

            # Also cache with semantic hash for text queries
            semantic_success = False
            if "query" in parameters:
                query_text = parameters["query"]
                if isinstance(query_text, str) and len(query_text) > 3:
                    semantic_hash = self._get_semantic_hash(tool_name, query_text)

                    semantic_key = CacheKey(
                        tool_name=tool_name,
                        tenant_id=tenant_id,
                        parameters_hash=params_hash,
                        semantic_hash=semantic_hash,
                    )

                    semantic_success = await self._set_in_redis(
                        semantic_key.to_redis_key(),
                        cached_result.to_dict(),
                        cache_config["ttl_seconds"],
                    )

            if success_exact:
                self.cache_stats["sets"] += 1
                logger.debug(
                    "Tool result cached",
                    tool_name=tool_name,
                    tenant_id=tenant_id,
                    cache_key=exact_redis_key,
                    semantic_cached=semantic_success,
                )

            return success_exact

        except Exception as e:
            logger.error("Tool cache set failed", tool_name=tool_name, error=str(e))
            return False

    async def _get_from_redis(self, key: str) -> Optional[Dict[str, Any]]:
        """Get data from Redis with error handling"""
        try:
            client = await self.redis_cache.get_client()
            data = await client.get(key)

            if data:
                return json.loads(data)
            return None

        except Exception as e:
            logger.error("Redis get failed", key=key, error=str(e))
            return None

    async def _set_in_redis(self, key: str, data: Dict[str, Any], ttl: int) -> bool:
        """Set data in Redis with TTL"""
        try:
            client = await self.redis_cache.get_client()
            serialized = json.dumps(data, default=str)

            # Add jitter to TTL to prevent thundering herd
            jitter = min(ttl // 10, 300)  # Max 5 minutes jitter
            actual_ttl = ttl + (hash(key) % jitter)

            await client.setex(key, actual_ttl, serialized)
            return True

        except Exception as e:
            logger.error("Redis set failed", key=key, error=str(e))
            return False

    async def _update_hit_count(self, key: str, new_count: int):
        """Update cache hit count"""
        try:
            client = await self.redis_cache.get_client()

            # Update hit count field in the cached data
            lua_script = """
                local cached_data = redis.call('GET', KEYS[1])
                if cached_data then
                    local data = cjson.decode(cached_data)
                    data.hit_count = tonumber(ARGV[1])
                    redis.call('SET', KEYS[1], cjson.encode(data), 'KEEPTTL')
                    return 1
                end
                return 0
            """

            await client.eval(lua_script, 1, key, new_count)

        except Exception as e:
            logger.debug("Hit count update failed", key=key, error=str(e))

    async def invalidate_tool_cache(
        self,
        tool_name: str,
        tenant_id: Optional[str] = None,
        pattern: Optional[str] = None,
    ) -> int:
        """
        Invalidate cached results for a tool.

        Args:
            tool_name: Tool to invalidate cache for
            tenant_id: Specific tenant or None for all tenants
            pattern: Specific pattern to match or None for all

        Returns:
            int: Number of keys invalidated
        """
        try:
            client = await self.redis_cache.get_client()

            # Build invalidation pattern
            if pattern:
                invalidation_pattern = pattern
            elif tenant_id:
                invalidation_pattern = f"ragline:tool_cache:{tenant_id}:{tool_name}:*"
            else:
                invalidation_pattern = f"ragline:tool_cache:*:{tool_name}:*"

            # Find matching keys
            keys = []
            async for key in client.scan_iter(match=invalidation_pattern):
                keys.append(key)

            # Delete in batches
            deleted_count = 0
            if keys:
                batch_size = 100
                for i in range(0, len(keys), batch_size):
                    batch_keys = keys[i : i + batch_size]
                    deleted_count += await client.delete(*batch_keys)

            self.cache_stats["evictions"] += deleted_count

            logger.info(
                "Tool cache invalidated",
                tool_name=tool_name,
                tenant_id=tenant_id,
                pattern=invalidation_pattern,
                deleted_count=deleted_count,
            )
            return deleted_count

        except Exception as e:
            logger.error("Tool cache invalidation failed", tool_name=tool_name, error=str(e))
            return 0

    async def get_cache_stats(self, tool_name: Optional[str] = None) -> Dict[str, Any]:
        """Get cache statistics for monitoring"""
        try:
            total_operations = self.cache_stats["hits"] + self.cache_stats["misses"]
            hit_rate = (self.cache_stats["hits"] / total_operations * 100) if total_operations > 0 else 0.0

            semantic_hit_rate = (
                (self.cache_stats["semantic_hits"] / self.cache_stats["hits"] * 100)
                if self.cache_stats["hits"] > 0
                else 0.0
            )

            # Get cache size by tool if specified
            cache_size_by_tool = {}
            if tool_name:
                pattern = f"ragline:tool_cache:*:{tool_name}:*"
                client = await self.redis_cache.get_client()
                count = 0
                async for _ in client.scan_iter(match=pattern):
                    count += 1
                cache_size_by_tool[tool_name] = count

            return {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "statistics": {
                    "total_hits": self.cache_stats["hits"],
                    "total_misses": self.cache_stats["misses"],
                    "total_sets": self.cache_stats["sets"],
                    "total_evictions": self.cache_stats["evictions"],
                    "semantic_hits": self.cache_stats["semantic_hits"],
                    "hit_rate_percent": hit_rate,
                    "semantic_hit_rate_percent": semantic_hit_rate,
                },
                "cache_sizes": cache_size_by_tool,
                "tool_configurations": self.tool_cache_config,
            }

        except Exception as e:
            logger.error("Failed to get cache stats", error=str(e))
            return {"error": str(e)}

    async def cleanup_expired_cache(self, tool_name: Optional[str] = None) -> Dict[str, int]:
        """Clean up expired cache entries and enforce size limits"""
        try:
            client = await self.redis_cache.get_client()
            cleanup_stats = {"expired_removed": 0, "size_limit_removed": 0}

            # Get tools to clean up
            tools_to_clean = [tool_name] if tool_name else self.tool_cache_config.keys()

            for tool in tools_to_clean:
                tool_config = self.tool_cache_config.get(tool, self.default_cache_config)
                pattern = f"ragline:tool_cache:*:{tool}:*"

                # Get all cache keys for this tool with creation times
                cache_entries = []
                async for key in client.scan_iter(match=pattern):
                    try:
                        data = await client.get(key)
                        if data:
                            entry_data = json.loads(data)
                            cached_at = datetime.fromisoformat(entry_data["cached_at"])
                            cache_entries.append(
                                {
                                    "key": key,
                                    "cached_at": cached_at,
                                    "hit_count": entry_data.get("hit_count", 1),
                                }
                            )
                    except Exception:
                        # Invalid cache entry - mark for deletion
                        cache_entries.append({"key": key, "cached_at": datetime.min, "hit_count": 0})

                # Sort by hit count and age (LRU with hit count weighting)
                cache_entries.sort(key=lambda x: (x["hit_count"], x["cached_at"]))

                # Enforce size limits
                max_size = tool_config["max_cache_size"]
                if len(cache_entries) > max_size:
                    entries_to_remove = cache_entries[: len(cache_entries) - max_size]

                    keys_to_remove = [entry["key"] for entry in entries_to_remove]
                    if keys_to_remove:
                        removed_count = await client.delete(*keys_to_remove)
                        cleanup_stats["size_limit_removed"] += removed_count

            logger.info("Cache cleanup completed", stats=cleanup_stats)
            return cleanup_stats

        except Exception as e:
            logger.error("Cache cleanup failed", error=str(e))
            return {"error": str(e)}

    async def get_cache_efficiency_report(self) -> Dict[str, Any]:
        """Generate cache efficiency report for optimization"""
        try:
            report = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "overall_efficiency": {},
                "tool_efficiency": {},
                "recommendations": [],
            }

            # Overall efficiency
            total_ops = self.cache_stats["hits"] + self.cache_stats["misses"]
            if total_ops > 0:
                hit_rate = self.cache_stats["hits"] / total_ops * 100
                report["overall_efficiency"] = {
                    "hit_rate_percent": hit_rate,
                    "semantic_hit_ratio": (
                        self.cache_stats["semantic_hits"] / self.cache_stats["hits"] * 100
                        if self.cache_stats["hits"] > 0
                        else 0.0
                    ),
                    "cache_effectiveness": "excellent" if hit_rate > 80 else "good" if hit_rate > 60 else "poor",
                }

                # Generate recommendations
                if hit_rate < 60:
                    report["recommendations"].append("Consider increasing TTL or improving semantic matching")
                if self.cache_stats["semantic_hits"] > self.cache_stats["hits"] * 0.3:
                    report["recommendations"].append("High semantic hit rate - consider lowering similarity threshold")

            # Tool-specific efficiency (would require per-tool tracking)
            for tool_name in self.tool_cache_config.keys():
                # This would be enhanced with per-tool statistics
                report["tool_efficiency"][tool_name] = {
                    "config": self.tool_cache_config[tool_name],
                    "estimated_savings_percent": 25,  # Would calculate from actual data
                }

            return report

        except Exception as e:
            logger.error("Failed to generate efficiency report", error=str(e))
            return {"error": str(e)}

    async def close(self):
        """Close Redis connections"""
        if self.redis_cache._client:
            await self.redis_cache._client.close()


# Global cache instance
_tool_cache: Optional[ToolResultCache] = None


async def get_tool_cache() -> ToolResultCache:
    """Get or create tool result cache instance"""
    global _tool_cache

    if not _tool_cache:
        config = WorkerConfig()
        _tool_cache = ToolResultCache(config)

    return _tool_cache


# Helper functions for tool integration


async def get_cached_tool_result(
    tool_name: str,
    tenant_id: str,
    parameters: Dict[str, Any],
    semantic_search: bool = True,
) -> Optional[Dict[str, Any]]:
    """Helper function to get cached tool result"""
    try:
        cache = await get_tool_cache()
        cached_result = await cache.get_cached_result(
            tool_name=tool_name,
            tenant_id=tenant_id,
            parameters=parameters,
            semantic_search=semantic_search,
        )

        if cached_result:
            # Add cache metadata to result
            result = cached_result.result.copy()
            result["_cache_metadata"] = {
                "cached": True,
                "cache_hit_at": datetime.now(timezone.utc).isoformat(),
                "original_duration_ms": cached_result.original_duration_ms,
                "cache_hit_count": cached_result.hit_count,
                "semantic_match": cached_result.semantic_similar,
                "similarity_score": cached_result.similarity_score,
            }
            return result

        return None

    except Exception as e:
        logger.error("Failed to get cached tool result", tool_name=tool_name, error=str(e))
        return None


async def cache_tool_result(
    tool_name: str,
    tenant_id: str,
    parameters: Dict[str, Any],
    result: Dict[str, Any],
    execution_data: Optional[Dict[str, Any]] = None,
) -> bool:
    """Helper function to cache tool result"""
    try:
        cache = await get_tool_cache()

        # Remove any existing cache metadata from result before caching
        clean_result = {k: v for k, v in result.items() if not k.startswith("_cache")}

        return await cache.cache_result(
            tool_name=tool_name,
            tenant_id=tenant_id,
            parameters=parameters,
            result=clean_result,
            execution_data=execution_data,
        )

    except Exception as e:
        logger.error("Failed to cache tool result", tool_name=tool_name, error=str(e))
        return False


async def invalidate_tool_cache(
    tool_name: str,
    tenant_id: Optional[str] = None,
    pattern: Optional[str] = None,
) -> int:
    """Helper function to invalidate tool cache"""
    try:
        cache = await get_tool_cache()
        return await cache.invalidate_tool_cache(
            tool_name=tool_name,
            tenant_id=tenant_id,
            pattern=pattern,
        )

    except Exception as e:
        logger.error("Failed to invalidate tool cache", tool_name=tool_name, error=str(e))
        return 0


async def get_tool_cache_stats(tool_name: Optional[str] = None) -> Dict[str, Any]:
    """Helper function to get cache statistics"""
    try:
        cache = await get_tool_cache()
        return await cache.get_cache_stats(tool_name=tool_name)

    except Exception as e:
        logger.error("Failed to get tool cache stats", error=str(e))
        return {"error": str(e)}
