"""
RAGline DLQ Management API

FastAPI endpoints for Dead Letter Queue management, monitoring, and manual intervention.
These endpoints can be included in the main API service.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from celery import Celery
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from packages.security.auth import UserClaims, get_current_user


# Pydantic models for API responses
class DLQEventResponse(BaseModel):
    """Response model for DLQ event data"""

    event_id: str
    aggregate_id: str
    aggregate_type: str
    event_type: str
    failed_at: str
    retry_count: int
    failure_reason: str
    status: str


class DLQStatsResponse(BaseModel):
    """Response model for DLQ statistics"""

    total_events: int
    by_aggregate_type: Dict[str, Dict[str, Any]]
    status_counts: Dict[str, int]
    oldest_event_hours: float
    reprocessed_count: int
    failed_reprocess_count: int
    expired_count: int
    failure_rate: float


class DLQAlertResponse(BaseModel):
    """Response model for DLQ alerts"""

    type: str
    severity: str
    message: str
    timestamp: str
    count: Optional[int] = None
    age_hours: Optional[float] = None
    failure_rate: Optional[float] = None


class BatchReprocessResponse(BaseModel):
    """Response model for batch reprocessing results"""

    status: str
    aggregate_type: str
    attempted: int
    succeeded: int
    failed: int
    timestamp: str


class ManualResolutionRequest(BaseModel):
    """Request model for manual event resolution"""

    event_id: str = Field(..., description="ID of the event to resolve")
    aggregate_type: str = Field(..., description="Aggregate type (order, user, etc.)")
    reason: Optional[str] = Field(None, description="Reason for manual resolution")


# Create API router
dlq_router = APIRouter(prefix="/dlq", tags=["Dead Letter Queue"])


def get_celery_app() -> Celery:
    """Get Celery app instance for task execution"""
    from services.worker.celery_app import app

    return app


@dlq_router.get("/stats", response_model=Dict[str, Any])
async def get_dlq_statistics(user: UserClaims = Depends(get_current_user)):
    """
    Get comprehensive Dead Letter Queue statistics.

    Requires authentication and returns detailed metrics about DLQ state.
    """
    try:
        celery_app = get_celery_app()

        # Execute DLQ stats task
        task_result = celery_app.send_task("services.worker.tasks.dlq.get_dlq_stats")

        # Wait for result (with timeout)
        result = task_result.get(timeout=30)

        if result.get("status") == "error":
            raise HTTPException(status_code=500, detail=f"Failed to get DLQ stats: {result.get('error')}")

        return {"success": True, "data": result.get("stats", {}), "timestamp": result.get("timestamp")}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@dlq_router.get("/alerts", response_model=Dict[str, Any])
async def get_dlq_alerts(user: UserClaims = Depends(get_current_user)):
    """
    Get current Dead Letter Queue alerts.

    Returns active alerts based on configured thresholds.
    """
    try:
        celery_app = get_celery_app()

        task_result = celery_app.send_task("services.worker.tasks.dlq.get_dlq_alerts")

        result = task_result.get(timeout=30)

        if result.get("status") == "error":
            raise HTTPException(status_code=500, detail=f"Failed to get DLQ alerts: {result.get('error')}")

        return {
            "success": True,
            "alerts": result.get("alerts", []),
            "alert_count": result.get("alert_count", 0),
            "timestamp": result.get("timestamp"),
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@dlq_router.get("/events/manual-intervention", response_model=Dict[str, Any])
async def get_manual_intervention_events(user: UserClaims = Depends(get_current_user)):
    """
    Get events requiring manual intervention.

    Returns events that have failed multiple reprocessing attempts.
    """
    try:
        celery_app = get_celery_app()

        task_result = celery_app.send_task("services.worker.tasks.dlq.get_manual_intervention_events")

        result = task_result.get(timeout=30)

        if result.get("status") == "error":
            raise HTTPException(
                status_code=500, detail=f"Failed to get manual intervention events: {result.get('error')}"
            )

        return {
            "success": True,
            "events": result.get("events", []),
            "event_count": result.get("event_count", 0),
            "timestamp": result.get("timestamp"),
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@dlq_router.post("/reprocess", response_model=Dict[str, Any])
async def batch_reprocess_dlq_events(
    aggregate_type: str = Query("order", description="Aggregate type to reprocess"),
    limit: int = Query(10, ge=1, le=50, description="Maximum events to reprocess"),
    user: UserClaims = Depends(get_current_user),
):
    """
    Batch reprocess events from Dead Letter Queue.

    Attempts to reprocess failed events with exponential backoff logic.
    """
    try:
        celery_app = get_celery_app()

        # Execute batch reprocessing task
        task_result = celery_app.send_task(
            "services.worker.tasks.dlq.batch_reprocess_dlq", args=[aggregate_type, limit]
        )

        result = task_result.get(timeout=120)  # Longer timeout for reprocessing

        if result.get("status") == "error":
            raise HTTPException(status_code=500, detail=f"Batch reprocessing failed: {result.get('error')}")

        return {
            "success": True,
            "results": result.get("results", {}),
            "aggregate_type": aggregate_type,
            "timestamp": result.get("timestamp"),
            "message": f"Processed {result.get('results', {}).get('attempted', 0)} events",
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@dlq_router.post("/events/resolve", response_model=Dict[str, Any])
async def manually_resolve_event(request: ManualResolutionRequest, user: UserClaims = Depends(get_current_user)):
    """
    Manually mark an event as resolved.

    Use this for events that cannot be automatically reprocessed.
    """
    try:
        celery_app = get_celery_app()

        task_result = celery_app.send_task(
            "services.worker.tasks.dlq.mark_event_resolved", args=[request.event_id, request.aggregate_type]
        )

        result = task_result.get(timeout=30)

        if result.get("status") == "error":
            raise HTTPException(status_code=500, detail=f"Failed to resolve event: {result.get('error')}")

        return {
            "success": True,
            "resolved": result.get("resolved", False),
            "event_id": request.event_id,
            "aggregate_type": request.aggregate_type,
            "message": result.get("message", "Event processed"),
            "timestamp": result.get("timestamp"),
            "resolved_by": user.email,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@dlq_router.post("/cleanup", response_model=Dict[str, Any])
async def cleanup_expired_events(
    days_to_keep: int = Query(30, ge=1, le=365, description="Days to keep expired events"),
    user: UserClaims = Depends(get_current_user),
):
    """
    Clean up old expired and resolved DLQ events.

    Removes events older than the specified number of days.
    """
    try:
        celery_app = get_celery_app()

        task_result = celery_app.send_task("services.worker.tasks.dlq.cleanup_expired_events", args=[days_to_keep])

        result = task_result.get(timeout=60)

        if result.get("status") == "error":
            raise HTTPException(status_code=500, detail=f"Cleanup failed: {result.get('error')}")

        return {
            "success": True,
            "cleaned_count": result.get("cleaned_count", 0),
            "days_to_keep": days_to_keep,
            "timestamp": result.get("timestamp"),
            "cleaned_by": user.email,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@dlq_router.get("/health", response_model=Dict[str, Any])
async def dlq_health_check(user: UserClaims = Depends(get_current_user)):
    """
    Health check for DLQ system.

    Returns status of DLQ manager and associated services.
    """
    try:
        celery_app = get_celery_app()

        task_result = celery_app.send_task("services.worker.tasks.dlq.health_check_dlq")

        result = task_result.get(timeout=30)

        # Always return 200 for health checks, include status in response
        return {"success": True, "health": result, "overall_status": result.get("status", "unknown")}

    except Exception as e:
        # Return degraded status instead of error for health checks
        return {
            "success": True,
            "health": {"status": "unhealthy", "error": str(e), "timestamp": datetime.utcnow().isoformat()},
            "overall_status": "unhealthy",
        }


@dlq_router.get("/monitoring/dashboard", response_model=Dict[str, Any])
async def get_dlq_dashboard_data(user: UserClaims = Depends(get_current_user)):
    """
    Get comprehensive dashboard data for DLQ monitoring.

    Combines stats, alerts, and manual intervention events.
    """
    try:
        celery_app = get_celery_app()

        # Execute multiple tasks in parallel
        stats_task = celery_app.send_task("services.worker.tasks.dlq.get_dlq_stats")
        alerts_task = celery_app.send_task("services.worker.tasks.dlq.get_dlq_alerts")
        manual_task = celery_app.send_task("services.worker.tasks.dlq.get_manual_intervention_events")
        health_task = celery_app.send_task("services.worker.tasks.dlq.health_check_dlq")

        # Wait for all results
        stats_result = stats_task.get(timeout=30)
        alerts_result = alerts_task.get(timeout=30)
        manual_result = manual_task.get(timeout=30)
        health_result = health_task.get(timeout=30)

        # Check for errors
        errors = []
        if stats_result.get("status") == "error":
            errors.append(f"Stats: {stats_result.get('error')}")
        if alerts_result.get("status") == "error":
            errors.append(f"Alerts: {alerts_result.get('error')}")
        if manual_result.get("status") == "error":
            errors.append(f"Manual events: {manual_result.get('error')}")

        if errors:
            raise HTTPException(status_code=500, detail=f"Dashboard data errors: {'; '.join(errors)}")

        return {
            "success": True,
            "dashboard": {
                "stats": stats_result.get("stats", {}),
                "alerts": alerts_result.get("alerts", []),
                "manual_intervention_events": manual_result.get("events", []),
                "health": health_result,
                "summary": {
                    "total_events": stats_result.get("stats", {}).get("total_events", 0),
                    "active_alerts": len(alerts_result.get("alerts", [])),
                    "manual_events": len(manual_result.get("events", [])),
                    "system_status": health_result.get("status", "unknown"),
                },
            },
            "timestamp": datetime.utcnow().isoformat(),
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
