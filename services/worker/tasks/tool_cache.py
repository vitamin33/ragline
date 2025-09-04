"""
RAGline Tool Cache Management Tasks

Celery tasks for managing tool result caching, cache cleanup, and performance monitoring.
"""

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional

from celery import Task
from celery.utils.log import get_task_logger

from packages.orchestrator.tool_cache import (
    get_tool_cache,
    get_tool_cache_stats,
    invalidate_tool_cache,
)

from ..celery_app import app
from ..config import WorkerConfig

logger = get_task_logger(__name__)


class ToolCacheTask(Task):
    """Base tool cache task with error handling"""

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        logger.error(f"Tool cache task failed: {exc}", exc_info=einfo)

    def on_success(self, retval, task_id, args, kwargs):
        logger.debug(f"Tool cache task completed: {task_id}")


@app.task(
    bind=True,
    base=ToolCacheTask,
    name="services.worker.tasks.tool_cache.cleanup_expired_cache",
)
def cleanup_expired_cache(self, tool_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Clean up expired cache entries and enforce size limits.

    Args:
        tool_name: Specific tool to clean up or None for all tools

    Returns:
        Dict with cleanup statistics
    """

    async def _cleanup():
        try:
            cache = await get_tool_cache()
            cleanup_stats = await cache.cleanup_expired_cache(tool_name=tool_name)

            return {
                "status": "success",
                "tool_name": tool_name,
                "cleanup_stats": cleanup_stats,
                "timestamp": datetime.utcnow().isoformat(),
            }

        except Exception as e:
            logger.error(f"Cache cleanup failed: {e}", exc_info=True)
            return {"status": "error", "error": str(e)}

    try:
        result = asyncio.run(_cleanup())
        return result
    except Exception as e:
        logger.error(f"Failed to run cache cleanup: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}


@app.task(
    bind=True,
    base=ToolCacheTask,
    name="services.worker.tasks.tool_cache.invalidate_cache",
)
def invalidate_cache(
    self,
    tool_name: str,
    tenant_id: Optional[str] = None,
    pattern: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Invalidate tool cache for specific tool/tenant/pattern.

    Args:
        tool_name: Tool to invalidate
        tenant_id: Specific tenant or None for all tenants
        pattern: Specific cache pattern to invalidate

    Returns:
        Dict with invalidation result
    """

    async def _invalidate():
        try:
            invalidated_count = await invalidate_tool_cache(
                tool_name=tool_name,
                tenant_id=tenant_id,
                pattern=pattern,
            )

            return {
                "status": "success",
                "tool_name": tool_name,
                "tenant_id": tenant_id,
                "pattern": pattern,
                "invalidated_count": invalidated_count,
                "timestamp": datetime.utcnow().isoformat(),
            }

        except Exception as e:
            logger.error(f"Cache invalidation failed: {e}", exc_info=True)
            return {"status": "error", "error": str(e)}

    try:
        result = asyncio.run(_invalidate())
        return result
    except Exception as e:
        logger.error(f"Failed to run cache invalidation: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}


@app.task(
    bind=True,
    base=ToolCacheTask,
    name="services.worker.tasks.tool_cache.get_cache_statistics",
)
def get_cache_statistics(self, tool_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Get cache statistics for monitoring and optimization.

    Args:
        tool_name: Specific tool or None for all tools

    Returns:
        Dict with cache statistics
    """

    async def _get_stats():
        try:
            stats = await get_tool_cache_stats(tool_name=tool_name)
            return stats

        except Exception as e:
            logger.error(f"Failed to get cache statistics: {e}", exc_info=True)
            return {"error": str(e)}

    try:
        result = asyncio.run(_get_stats())
        return result
    except Exception as e:
        logger.error(f"Failed to get cache statistics: {e}", exc_info=True)
        return {"error": str(e)}


@app.task(
    bind=True,
    base=ToolCacheTask,
    name="services.worker.tasks.tool_cache.optimize_cache_configuration",
)
def optimize_cache_configuration(self) -> Dict[str, Any]:
    """
    Analyze cache performance and suggest configuration optimizations.

    Returns:
        Dict with optimization recommendations
    """

    async def _optimize():
        try:
            cache = await get_tool_cache()
            efficiency_report = await cache.get_cache_efficiency_report()

            # Add optimization recommendations
            recommendations = []

            overall_eff = efficiency_report.get("overall_efficiency", {})
            hit_rate = overall_eff.get("hit_rate_percent", 0)

            if hit_rate < 50:
                recommendations.append(
                    {
                        "type": "ttl_increase",
                        "description": "Low hit rate suggests TTL is too short",
                        "suggested_action": "Increase TTL by 50% for stable tools",
                        "priority": "high",
                    }
                )

            if hit_rate > 90:
                recommendations.append(
                    {
                        "type": "ttl_optimization",
                        "description": "Very high hit rate suggests over-caching",
                        "suggested_action": "Consider shorter TTL to free memory",
                        "priority": "low",
                    }
                )

            semantic_rate = overall_eff.get("semantic_hit_ratio", 0)
            if semantic_rate > 40:
                recommendations.append(
                    {
                        "type": "semantic_threshold",
                        "description": "High semantic hit rate suggests loose matching",
                        "suggested_action": "Consider tightening semantic similarity threshold",
                        "priority": "medium",
                    }
                )

            return {
                "status": "success",
                "efficiency_report": efficiency_report,
                "recommendations": recommendations,
                "timestamp": datetime.utcnow().isoformat(),
            }

        except Exception as e:
            logger.error(f"Cache optimization analysis failed: {e}", exc_info=True)
            return {"status": "error", "error": str(e)}

    try:
        result = asyncio.run(_optimize())
        return result
    except Exception as e:
        logger.error(f"Failed to run cache optimization: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}


@app.task(
    bind=True,
    base=ToolCacheTask,
    name="services.worker.tasks.tool_cache.warm_cache_for_tool",
)
def warm_cache_for_tool(
    self,
    tool_name: str,
    tenant_id: str,
    common_queries: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Pre-warm cache with common queries for a tool.

    Args:
        tool_name: Tool to warm cache for
        tenant_id: Tenant identifier
        common_queries: List of common parameter sets to pre-execute

    Returns:
        Dict with warm-up results
    """

    async def _warm_cache():
        try:
            # This would integrate with actual tool execution
            # For now, we'll track the request for future implementation

            warmed_count = 0
            failed_count = 0

            for query_params in common_queries:
                try:
                    # TODO: Integrate with tool execution system
                    # This would execute the tool and cache the result
                    logger.info(f"Would warm cache for {tool_name} with params: {query_params}")
                    warmed_count += 1

                except Exception as e:
                    logger.warning(f"Failed to warm cache entry: {e}")
                    failed_count += 1

            return {
                "status": "success",
                "tool_name": tool_name,
                "tenant_id": tenant_id,
                "warmed_count": warmed_count,
                "failed_count": failed_count,
                "total_queries": len(common_queries),
                "timestamp": datetime.utcnow().isoformat(),
            }

        except Exception as e:
            logger.error(f"Cache warming failed: {e}", exc_info=True)
            return {"status": "error", "error": str(e)}

    try:
        result = asyncio.run(_warm_cache())
        return result
    except Exception as e:
        logger.error(f"Failed to warm cache: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}
