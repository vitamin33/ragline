"""
RAGline Outbox Consumer Tasks

Celery tasks for consuming and processing outbox events.
Implements polling mechanism with 100ms interval and retry logic.
"""

import asyncio
from datetime import datetime
from typing import Dict, Any

from celery import Task
from celery.utils.log import get_task_logger

from ..celery_app import app
from ..config import WorkerConfig
from packages.orchestrator.outbox import OutboxConsumer, get_outbox_consumer, OutboxReprocessor

logger = get_task_logger(__name__)


class OutboxConsumerTask(Task):
    """Base outbox consumer task with error handling"""
    
    def on_failure(self, exc, task_id, args, kwargs, einfo):
        logger.error(f"Outbox consumer task failed: {exc}", exc_info=einfo)
    
    def on_success(self, retval, task_id, args, kwargs):
        logger.info(f"Outbox consumer task completed: {retval}")


@app.task(bind=True, base=OutboxConsumerTask, name="services.worker.tasks.outbox.consume_outbox")
def consume_outbox(self) -> Dict[str, Any]:
    """
    Main outbox consumer task that polls for unprocessed events.
    This task is scheduled to run every 100ms via Celery Beat.
    """
    async def _consume():
        try:
            consumer = await get_outbox_consumer()
            
            # Start consumer if not already running
            if not consumer.is_running:
                logger.info("Starting outbox consumer...")
                # Run for a single poll cycle in this task
                await consumer._init_connections()
                
                # Fetch and process events once
                events = await consumer._fetch_unprocessed_events()
                if events:
                    logger.info(f"Processing {len(events)} outbox events")
                    await consumer._process_events(events)
                
                # Get metrics for reporting
                metrics = await consumer.get_metrics()
                return metrics
            else:
                logger.debug("Outbox consumer already running")
                return {"status": "already_running"}
                
        except Exception as e:
            logger.error(f"Outbox consumption failed: {e}", exc_info=True)
            return {"status": "error", "error": str(e)}
    
    # Run the async function in the event loop
    try:
        result = asyncio.run(_consume())
        return result
    except Exception as e:
        logger.error(f"Failed to run outbox consumer: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}


@app.task(bind=True, name="services.worker.tasks.outbox.start_outbox_consumer")
def start_outbox_consumer(self) -> Dict[str, Any]:
    """
    Long-running task to start the outbox consumer daemon.
    This runs the consumer in a continuous loop.
    """
    async def _start_consumer():
        try:
            config = WorkerConfig()
            consumer = OutboxConsumer(config)
            
            logger.info("Starting outbox consumer daemon...")
            await consumer.start()
            
            return {"status": "completed", "message": "Outbox consumer stopped"}
            
        except Exception as e:
            logger.error(f"Outbox consumer daemon failed: {e}", exc_info=True)
            return {"status": "error", "error": str(e)}
    
    try:
        result = asyncio.run(_start_consumer())
        return result
    except Exception as e:
        logger.error(f"Failed to start outbox consumer daemon: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}


@app.task(bind=True, name="services.worker.tasks.outbox.get_outbox_metrics")
def get_outbox_metrics(self) -> Dict[str, Any]:
    """Get outbox consumer metrics"""
    async def _get_metrics():
        try:
            consumer = await get_outbox_consumer()
            metrics = await consumer.get_metrics()
            
            # Add timestamp
            metrics['timestamp'] = datetime.utcnow().isoformat()
            
            return metrics
            
        except Exception as e:
            logger.error(f"Failed to get outbox metrics: {e}", exc_info=True)
            return {"error": str(e)}
    
    try:
        result = asyncio.run(_get_metrics())
        return result
    except Exception as e:
        logger.error(f"Failed to get outbox metrics: {e}", exc_info=True)
        return {"error": str(e)}


@app.task(bind=True, name="services.worker.tasks.outbox.reprocess_dlq")
def reprocess_dlq(self, aggregate_type: str = "order", limit: int = 10) -> Dict[str, Any]:
    """
    Reprocess events from Dead Letter Queue.
    
    Args:
        aggregate_type: Type of aggregate to reprocess (order, user, product, etc.)
        limit: Maximum number of events to reprocess
    """
    async def _reprocess():
        try:
            config = WorkerConfig()
            reprocessor = OutboxReprocessor(config)
            
            reprocessed_count = await reprocessor.reprocess_dlq_events(aggregate_type, limit)
            
            logger.info(f"Reprocessed {reprocessed_count} events from DLQ for {aggregate_type}")
            
            return {
                "status": "success",
                "reprocessed_count": reprocessed_count,
                "aggregate_type": aggregate_type,
                "limit": limit
            }
            
        except Exception as e:
            logger.error(f"DLQ reprocessing failed: {e}", exc_info=True)
            return {"status": "error", "error": str(e)}
    
    try:
        result = asyncio.run(_reprocess())
        return result
    except Exception as e:
        logger.error(f"Failed to reprocess DLQ: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}


@app.task(bind=True, name="services.worker.tasks.outbox.health_check_outbox")
def health_check_outbox(self) -> Dict[str, Any]:
    """Health check specifically for outbox processing"""
    async def _health_check():
        try:
            from packages.db.models import Outbox
            from packages.db.database import AsyncSessionLocal
            from sqlalchemy import select, func
            import redis.asyncio as redis
            
            config = WorkerConfig()
            health_data = {
                "timestamp": datetime.utcnow().isoformat(),
                "status": "healthy",
                "checks": {}
            }
            
            # Check database connectivity and outbox table
            try:
                async with AsyncSessionLocal() as session:
                    # Count unprocessed events
                    unprocessed_query = select(func.count()).select_from(Outbox).where(Outbox.processed == False)
                    unprocessed_result = await session.execute(unprocessed_query)
                    unprocessed_count = unprocessed_result.scalar()
                    
                    # Count total events
                    total_query = select(func.count()).select_from(Outbox)
                    total_result = await session.execute(total_query)
                    total_count = total_result.scalar()
                    
                    health_data["checks"]["database"] = {
                        "status": "healthy",
                        "total_events": total_count,
                        "unprocessed_events": unprocessed_count
                    }
                    
            except Exception as e:
                health_data["checks"]["database"] = {
                    "status": "unhealthy",
                    "error": str(e)
                }
                health_data["status"] = "degraded"
            
            # Check Redis connectivity
            try:
                redis_client = redis.from_url(config.redis_url)
                await redis_client.ping()
                
                # Check stream lengths
                stream_lengths = {}
                streams = ["ragline:stream:orders", "ragline:stream:notifications"]
                for stream in streams:
                    try:
                        length = await redis_client.xlen(stream)
                        stream_lengths[stream] = length
                    except:
                        stream_lengths[stream] = 0
                
                await redis_client.close()
                
                health_data["checks"]["redis"] = {
                    "status": "healthy",
                    "stream_lengths": stream_lengths
                }
                
            except Exception as e:
                health_data["checks"]["redis"] = {
                    "status": "unhealthy", 
                    "error": str(e)
                }
                health_data["status"] = "degraded"
            
            # Get consumer metrics if available
            try:
                consumer = await get_outbox_consumer()
                metrics = await consumer.get_metrics()
                health_data["consumer_metrics"] = metrics
            except:
                health_data["consumer_metrics"] = {"status": "not_initialized"}
            
            return health_data
            
        except Exception as e:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "status": "unhealthy",
                "error": str(e)
            }
    
    try:
        result = asyncio.run(_health_check())
        return result
    except Exception as e:
        logger.error(f"Outbox health check failed: {e}", exc_info=True)
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "status": "unhealthy",
            "error": str(e)
        }