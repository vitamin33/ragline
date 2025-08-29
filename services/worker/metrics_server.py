"""
RAGline Worker Metrics Server

Standalone HTTP server for Prometheus metrics scraping.
Exports comprehensive metrics for worker services.
"""

import asyncio
import logging
import signal
import sys
from datetime import datetime
from typing import Any, Dict

from celery.utils.log import get_task_logger
from prometheus_client import generate_latest, start_http_server

from packages.orchestrator.circuit_breaker import get_registry_metrics
from packages.orchestrator.dlq_manager import get_dlq_manager
from packages.orchestrator.metrics import get_metrics, get_metrics_collector
from packages.orchestrator.outbox import get_outbox_consumer

from .config import WorkerConfig

logger = get_task_logger(__name__)


class MetricsServer:
    """
    Metrics server that collects and exports Prometheus metrics.

    Features:
    - Automatic metrics collection from all components
    - HTTP server for Prometheus scraping
    - Graceful shutdown handling
    - Health monitoring
    """

    def __init__(self, config: Optional[WorkerConfig] = None):
        self.config = config or WorkerConfig()
        self.metrics = get_metrics()
        self.collector = get_metrics_collector()
        self.is_running = False

        # Collection intervals
        self.collection_interval = 30  # Collect metrics every 30 seconds
        self.last_collection = 0

    async def start_server(self):
        """Start the metrics server"""
        if not self.config.metrics_enabled:
            logger.info("Metrics disabled in configuration")
            return

        logger.info(f"Starting metrics server on port {self.config.metrics_port}")

        try:
            # Start Prometheus HTTP server
            metrics_port = self.metrics.start_metrics_server(self.config.metrics_port)

            self.is_running = True
            logger.info(f"✅ Metrics server started on port {metrics_port}")

            # Start metrics collection loop
            await self._collection_loop()

        except Exception as e:
            logger.error(f"Failed to start metrics server: {e}")
            raise

    async def _collection_loop(self):
        """Main metrics collection loop"""
        while self.is_running:
            try:
                await self._collect_all_metrics()
                await asyncio.sleep(self.collection_interval)

            except Exception as e:
                logger.error(f"Error in metrics collection loop: {e}")
                await asyncio.sleep(5)  # Shorter retry interval

    async def _collect_all_metrics(self):
        """Collect metrics from all sources"""
        start_time = time.time()

        try:
            # Collect outbox metrics
            await self._collect_outbox_metrics()

            # Collect DLQ metrics
            await self._collect_dlq_metrics()

            # Collect circuit breaker metrics
            await self._collect_circuit_breaker_metrics()

            # Update collection timestamp
            collection_duration = time.time() - start_time
            self.last_collection = time.time()

            logger.debug(f"Metrics collection completed in {collection_duration:.3f}s")

        except Exception as e:
            logger.error(f"Failed to collect metrics: {e}")

    async def _collect_outbox_metrics(self):
        """Collect outbox consumer metrics"""
        try:
            consumer = await get_outbox_consumer()
            stats = await consumer.get_metrics()

            # Update Prometheus metrics
            await self.collector.collect_outbox_metrics(
                {
                    "processed_count": stats.get("processed_count", 0),
                    "error_count": stats.get("error_count", 0),
                    "processing_duration_ms": stats.get("processing_duration_ms", 0),
                    "unprocessed_events": 0,  # Would need database query
                    "processing_lag_seconds": 0,  # Would need calculation
                }
            )

        except Exception as e:
            logger.error(f"Failed to collect outbox metrics: {e}")
            self.metrics.record_error("metrics_collector", "outbox_collection_error")

    async def _collect_dlq_metrics(self):
        """Collect DLQ metrics"""
        try:
            dlq_manager = await get_dlq_manager()
            stats = await dlq_manager.get_dlq_stats()
            alerts = await dlq_manager.get_alerts()

            # Update DLQ metrics
            await self.collector.collect_dlq_metrics(stats)

            # Update alert counts
            alert_counts = {}
            for alert in alerts:
                alert_type = alert.get("type", "unknown")
                alert_counts[alert_type] = alert_counts.get(alert_type, 0) + 1

            for alert_type, count in alert_counts.items():
                self.metrics.update_dlq_alerts(alert_type, count)

        except Exception as e:
            logger.error(f"Failed to collect DLQ metrics: {e}")
            self.metrics.record_error("metrics_collector", "dlq_collection_error")

    async def _collect_circuit_breaker_metrics(self):
        """Collect circuit breaker metrics"""
        try:
            breaker_metrics = await get_registry_metrics()

            # Convert to list format for collector
            breaker_list = []
            for name, metrics_data in breaker_metrics.items():
                breaker_list.append({"name": name, **metrics_data})

            await self.collector.collect_circuit_breaker_metrics(breaker_list)

        except Exception as e:
            logger.error(f"Failed to collect circuit breaker metrics: {e}")
            self.metrics.record_error("metrics_collector", "circuit_breaker_collection_error")

    async def stop_server(self):
        """Stop the metrics server"""
        logger.info("Stopping metrics server...")
        self.is_running = False

    def get_server_status(self) -> Dict[str, Any]:
        """Get metrics server status"""
        return {
            "running": self.is_running,
            "port": self.config.metrics_port,
            "enabled": self.config.metrics_enabled,
            "last_collection": self.last_collection,
            "collection_interval": self.collection_interval,
        }


# Global server instance
_server_instance: Optional[MetricsServer] = None


async def get_metrics_server() -> MetricsServer:
    """Get or create metrics server instance"""
    global _server_instance

    if not _server_instance:
        config = WorkerConfig()
        _server_instance = MetricsServer(config)

    return _server_instance


async def start_standalone_metrics_server():
    """Start standalone metrics server for worker monitoring"""
    import time

    # Setup signal handlers for graceful shutdown
    server = await get_metrics_server()

    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}, shutting down...")
        asyncio.create_task(server.stop_server())
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        logger.info("🚀 Starting RAGline Worker Metrics Server")
        await server.start_server()

    except KeyboardInterrupt:
        logger.info("Metrics server interrupted")
    except Exception as e:
        logger.error(f"Metrics server failed: {e}")
        raise
    finally:
        await server.stop_server()


if __name__ == "__main__":
    """Run standalone metrics server"""
    asyncio.run(start_standalone_metrics_server())
