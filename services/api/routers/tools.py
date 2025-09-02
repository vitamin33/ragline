from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from packages.cache.redis_cache import RedisCache, get_cache
from packages.security.auth import get_current_user_token
from packages.security.jwt import TokenData

router = APIRouter()
logger = structlog.get_logger(__name__)

# Configuration for LLM service integration
LLM_SERVICE_URL = "http://localhost:8001"


class ToolExecuteRequest(BaseModel):
    tool_name: str = Field(..., description="Name of the tool to execute")
    parameters: Dict[str, Any] = Field(..., description="Tool parameters")
    context: Optional[Dict[str, Any]] = Field(default=None, description="Additional context for tool execution")


class ToolExecuteResponse(BaseModel):
    tool_name: str
    success: bool
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    execution_time_ms: float
    cached: bool = False
    request_id: Optional[str] = None


class ToolInfo(BaseModel):
    name: str
    description: str
    parameters: Dict[str, Any]
    category: str = "general"
    version: str = "1.0"


class ToolValidationRequest(BaseModel):
    parameters: Dict[str, Any] = Field(..., description="Parameters to validate")


class ToolValidationResponse(BaseModel):
    valid: bool
    errors: List[str] = []
    warnings: List[str] = []


@router.get("/", response_model=List[ToolInfo])
async def list_tools(
    token_data: TokenData = Depends(get_current_user_token),
    cache: RedisCache = Depends(get_cache),
):
    """List all available tools and their schemas."""
    tenant_id = token_data.tenant_id
    cache_key = "available_tools"

    # Try cache first
    cached_tools = await cache.get(tenant_id, "tools", cache_key)
    if cached_tools is not None:
        logger.info("Tool list cache hit", tenant_id=tenant_id)
        return [ToolInfo(**tool) for tool in cached_tools]

    # Fetch from LLM service
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{LLM_SERVICE_URL}/v1/tools")

            if response.status_code == 200:
                tools_data = response.json()

                # Cache the result
                await cache.set(tenant_id, "tools", cache_key, tools_data, ttl=300)  # 5 minutes

                logger.info("Tool list fetched from LLM service", tenant_id=tenant_id, count=len(tools_data))
                return [ToolInfo(**tool) for tool in tools_data]
            else:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY, detail=f"LLM service error: {response.status_code}"
                )

    except httpx.RequestError as e:
        logger.error("Failed to fetch tools from LLM service", tenant_id=tenant_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Tool service temporarily unavailable"
        )


@router.get("/{tool_name}/schema", response_model=Dict[str, Any])
async def get_tool_schema(
    tool_name: str,
    token_data: TokenData = Depends(get_current_user_token),
    cache: RedisCache = Depends(get_cache),
):
    """Get the parameter schema for a specific tool."""
    tenant_id = token_data.tenant_id
    cache_key = f"schema:{tool_name}"

    # Try cache first
    cached_schema = await cache.get(tenant_id, "tools", cache_key)
    if cached_schema is not None:
        logger.info("Tool schema cache hit", tenant_id=tenant_id, tool_name=tool_name)
        return cached_schema

    # Fetch from LLM service
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{LLM_SERVICE_URL}/v1/tools/{tool_name}/schema")

            if response.status_code == 200:
                schema_data = response.json()

                # Cache the result
                await cache.set(tenant_id, "tools", cache_key, schema_data, ttl=600)  # 10 minutes

                logger.info("Tool schema fetched", tenant_id=tenant_id, tool_name=tool_name)
                return schema_data
            elif response.status_code == 404:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Tool '{tool_name}' not found")
            else:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY, detail=f"LLM service error: {response.status_code}"
                )

    except httpx.RequestError as e:
        logger.error("Failed to fetch tool schema", tenant_id=tenant_id, tool_name=tool_name, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Tool service temporarily unavailable"
        )


@router.post("/{tool_name}/validate", response_model=ToolValidationResponse)
async def validate_tool_parameters(
    tool_name: str,
    request: ToolValidationRequest,
    token_data: TokenData = Depends(get_current_user_token),
):
    """Validate tool parameters against the tool schema."""
    tenant_id = token_data.tenant_id

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                f"{LLM_SERVICE_URL}/v1/tools/{tool_name}/validate",
                json=request.parameters,
                headers={"Content-Type": "application/json"},
            )

            if response.status_code == 200:
                validation_result = response.json()
                logger.info("Tool validation completed", tenant_id=tenant_id, tool_name=tool_name)
                return ToolValidationResponse(**validation_result)
            elif response.status_code == 404:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Tool '{tool_name}' not found")
            else:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Validation service error: {response.status_code}"
                )

    except httpx.RequestError as e:
        logger.error("Tool validation failed", tenant_id=tenant_id, tool_name=tool_name, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Validation service temporarily unavailable"
        )


@router.post("/execute", response_model=ToolExecuteResponse)
async def execute_tool(
    request: ToolExecuteRequest,
    token_data: TokenData = Depends(get_current_user_token),
    cache: RedisCache = Depends(get_cache),
):
    """Execute a tool with given parameters."""
    tenant_id = token_data.tenant_id
    user_id = token_data.user_id
    start_time = datetime.now(timezone.utc)

    # Generate request ID for tracking
    import uuid

    request_id = str(uuid.uuid4())

    # Check cache for repeated queries
    cache_key = f"exec:{request.tool_name}:{hash(str(sorted(request.parameters.items())))}"
    cached_result = await cache.get(tenant_id, "tool_results", cache_key)

    if cached_result is not None:
        execution_time = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
        logger.info("Tool execution cache hit", tenant_id=tenant_id, tool_name=request.tool_name, request_id=request_id)

        return ToolExecuteResponse(
            tool_name=request.tool_name,
            success=True,
            result=cached_result,
            execution_time_ms=execution_time,
            cached=True,
            request_id=request_id,
        )

    # Execute tool via LLM service
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            payload = {
                "tool_name": request.tool_name,
                "parameters": request.parameters,
                "context": {
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "request_id": request_id,
                    **(request.context or {}),
                },
            }

            response = await client.post(
                f"{LLM_SERVICE_URL}/v1/tools/execute", json=payload, headers={"Content-Type": "application/json"}
            )

            execution_time = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000

            if response.status_code == 200:
                result_data = response.json()

                # Cache successful results
                if result_data.get("success", False):
                    await cache.set(tenant_id, "tool_results", cache_key, result_data.get("result"), ttl=300)

                logger.info(
                    "Tool executed successfully",
                    tenant_id=tenant_id,
                    tool_name=request.tool_name,
                    execution_time_ms=execution_time,
                    request_id=request_id,
                )

                return ToolExecuteResponse(
                    tool_name=request.tool_name,
                    success=result_data.get("success", False),
                    result=result_data.get("result"),
                    error=result_data.get("error"),
                    execution_time_ms=execution_time,
                    cached=False,
                    request_id=request_id,
                )
            elif response.status_code == 404:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail=f"Tool '{request.tool_name}' not found"
                )
            elif response.status_code == 400:
                error_detail = response.json().get("detail", "Invalid tool parameters")
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error_detail)
            else:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Tool execution service error: {response.status_code}",
                )

    except httpx.TimeoutException:
        execution_time = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
        logger.error(
            "Tool execution timeout",
            tenant_id=tenant_id,
            tool_name=request.tool_name,
            execution_time_ms=execution_time,
            request_id=request_id,
        )

        return ToolExecuteResponse(
            tool_name=request.tool_name,
            success=False,
            error="Tool execution timed out",
            execution_time_ms=execution_time,
            cached=False,
            request_id=request_id,
        )
    except httpx.RequestError as e:
        execution_time = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
        logger.error(
            "Tool execution failed",
            tenant_id=tenant_id,
            tool_name=request.tool_name,
            error=str(e),
            execution_time_ms=execution_time,
            request_id=request_id,
        )

        return ToolExecuteResponse(
            tool_name=request.tool_name,
            success=False,
            error=f"Tool service unavailable: {str(e)}",
            execution_time_ms=execution_time,
            cached=False,
            request_id=request_id,
        )
    except Exception as e:
        execution_time = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
        logger.error(
            "Unexpected tool execution error",
            tenant_id=tenant_id,
            tool_name=request.tool_name,
            error=str(e),
            execution_time_ms=execution_time,
            request_id=request_id,
        )

        return ToolExecuteResponse(
            tool_name=request.tool_name,
            success=False,
            error="Internal tool execution error",
            execution_time_ms=execution_time,
            cached=False,
            request_id=request_id,
        )


@router.get("/stats")
async def get_tool_stats(
    token_data: TokenData = Depends(get_current_user_token),
    cache: RedisCache = Depends(get_cache),
):
    """Get tool usage statistics for the current tenant."""
    tenant_id = token_data.tenant_id

    # This would typically come from Agent B's metrics system
    # For now, return basic cache stats
    try:
        cache_stats = {
            "tenant_id": tenant_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "cache_info": {
                "tools_cached": "N/A - would come from Agent B metrics",
                "cache_hit_rate": "N/A - would come from Agent B metrics",
                "total_executions": "N/A - would come from Agent B metrics",
            },
        }

        return cache_stats

    except Exception as e:
        logger.error("Failed to get tool stats", tenant_id=tenant_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to retrieve tool statistics"
        )
