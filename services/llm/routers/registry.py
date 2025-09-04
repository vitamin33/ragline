"""
Tool Registry API Router

Exposes dynamic tool registry functionality via REST API.
Supports tool management, validation, and dependency checking.
"""

import json
import logging
import os
import sys
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))

from services.llm.registry.dynamic_registry import (
    DependencyCheckResult,
    ToolMetadata,
    ToolStatus,
    ToolVersion,
    ValidationResult,
    get_dynamic_registry,
)
from services.llm.tools.enhanced_manager import get_enhanced_tool_manager

logger = logging.getLogger(__name__)
router = APIRouter()


class ToolRegistrationRequest(BaseModel):
    """Tool registration request payload."""

    name: str = Field(..., description="Tool name")
    description: str = Field(..., description="Tool description")
    category: str = Field("custom", description="Tool category")
    version: Optional[Dict[str, int]] = Field(None, description="Tool version (major, minor, patch)")
    dependencies: Optional[List[str]] = Field(None, description="Tool dependencies")
    parameter_schema: Dict[str, Any] = Field(..., description="Tool parameter schema")
    estimated_latency_ms: Optional[int] = Field(None, description="Estimated execution latency")


class ToolValidationRequest(BaseModel):
    """Tool validation request payload."""

    tool_name: str = Field(..., description="Tool name to validate")
    arguments: Dict[str, Any] = Field(..., description="Arguments to validate")


class ToolExecutionRequest(BaseModel):
    """Tool execution request payload."""

    tool_name: str = Field(..., description="Tool name to execute")
    arguments: Dict[str, Any] = Field(..., description="Tool arguments")
    version: Optional[Dict[str, int]] = Field(None, description="Specific tool version")
    use_cache: bool = Field(True, description="Whether to use result caching")


class ToolChainValidationRequest(BaseModel):
    """Tool chain validation request."""

    tool_chain: List[str] = Field(..., description="List of tools to validate as chain")


def get_registry_from_request(request: Request):
    """Get dynamic registry from app state or create new one."""
    if hasattr(request.app.state, "dynamic_registry"):
        return request.app.state.dynamic_registry
    return None


@router.get("/")
async def list_tools(category: Optional[str] = None, status: Optional[str] = None, request: Request = None):
    """List all available tools with optional filtering."""
    try:
        registry = await get_dynamic_registry()

        # Convert status string to enum if provided
        status_filter = None
        if status:
            try:
                status_filter = ToolStatus(status)
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid status: {status}. Valid values: {[s.value for s in ToolStatus]}",
                )

        tools = await registry.get_available_tools(category=category, status=status_filter)
        registry_stats = await registry.get_registry_stats()

        return {
            "tools": tools,
            "total_count": len(tools),
            "registry_stats": registry_stats,
            "filters": {"category": category, "status": status},
        }

    except Exception as e:
        logger.error(f"Failed to list tools: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to retrieve tools")


@router.get("/{tool_name}")
async def get_tool_details(tool_name: str):
    """Get detailed information about a specific tool."""
    try:
        registry = await get_dynamic_registry()
        metadata = await registry.get_tool_metadata(tool_name)

        if not metadata:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Tool '{tool_name}' not found")

        # Get tool schema
        tool_schema = await registry.get_tool_schema(tool_name)

        return {
            "name": tool_name,
            "metadata": metadata.dict(),
            "schema": tool_schema,
            "openai_function": (await registry.get_openai_functions())[0]
            if tool_name in await registry.get_available_tools()
            else None,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get tool details for {tool_name}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to retrieve tool details")


@router.get("/{tool_name}/dependencies")
async def get_tool_dependencies(tool_name: str):
    """Get tool dependencies and dependency status."""
    try:
        registry = await get_dynamic_registry()
        metadata = await registry.get_tool_metadata(tool_name)

        if not metadata:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Tool '{tool_name}' not found")

        # Check dependency status
        dependency_check = await registry._check_dependencies(tool_name)

        dependencies_info = []
        for dep in metadata.dependencies:
            dep_metadata = await registry.get_tool_metadata(dep.tool_name)
            dependencies_info.append(
                {
                    "tool_name": dep.tool_name,
                    "optional": dep.optional,
                    "min_version": str(dep.min_version) if dep.min_version else None,
                    "max_version": str(dep.max_version) if dep.max_version else None,
                    "available": dep.tool_name in registry.tools,
                    "current_version": str(dep_metadata.version) if dep_metadata else None,
                    "status": dep_metadata.status.value if dep_metadata else "not_found",
                }
            )

        return {
            "tool_name": tool_name,
            "dependencies": dependencies_info,
            "dependency_check": {"satisfied": dependency_check.satisfied, "missing": dependency_check.missing},
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get dependencies for {tool_name}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to retrieve dependencies")


@router.post("/{tool_name}/validate")
async def validate_tool_arguments(tool_name: str, request: ToolValidationRequest):
    """Validate tool arguments against schema."""
    try:
        registry = await get_dynamic_registry()

        if tool_name not in registry.tools:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Tool '{tool_name}' not found")

        # Validate arguments
        validation_result = await registry._validate_tool_arguments(tool_name, request.arguments)

        return {
            "tool_name": tool_name,
            "validation": {
                "valid": validation_result.valid,
                "error": validation_result.error,
                "validated_args": validation_result.validated_args,
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Tool validation failed for {tool_name}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Tool validation failed")


@router.post("/{tool_name}/execute")
async def execute_tool_via_api(tool_name: str, request: ToolExecutionRequest):
    """Execute tool via API with enhanced tracking."""
    try:
        enhanced_manager = await get_enhanced_tool_manager()

        # Convert version dict to ToolVersion if provided
        version = None
        if request.version:
            version = ToolVersion(**request.version)

        # Execute tool with enhanced tracking
        result = await enhanced_manager.execute_tool_enhanced(
            tool_name=tool_name,
            arguments=request.arguments,
            tool_call_id=None,
            version=version,
            use_cache=request.use_cache,
        )

        return {
            "tool_name": tool_name,
            "execution": {
                "success": result.success,
                "data": result.data,
                "error": result.error,
                "latency_ms": result.latency_ms,
            },
            "version": str(version) if version else None,
            "cached": request.use_cache,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Tool execution failed for {tool_name}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Tool execution failed")


@router.post("/validate-chain")
async def validate_tool_chain(request: ToolChainValidationRequest):
    """Validate a chain of tool executions."""
    try:
        enhanced_manager = await get_enhanced_tool_manager()

        validation_result = await enhanced_manager.validate_tool_chain(request.tool_chain)

        return {"tool_chain": request.tool_chain, "validation": validation_result}

    except Exception as e:
        logger.error(f"Tool chain validation failed: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Tool chain validation failed")


@router.get("/stats/registry")
async def get_registry_statistics():
    """Get comprehensive registry statistics."""
    try:
        registry = await get_dynamic_registry()
        stats = await registry.get_registry_stats()

        # Add execution statistics
        execution_stats = {}
        for tool_name, tool_stats in registry.execution_stats.items():
            execution_stats[tool_name] = {
                **tool_stats,
                "success_rate": (tool_stats["total_successes"] / max(tool_stats["total_executions"], 1)) * 100,
            }

        return {"registry_stats": stats, "execution_stats": execution_stats, "timestamp": datetime.now().isoformat()}

    except Exception as e:
        logger.error(f"Failed to get registry statistics: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to retrieve statistics")


@router.get("/openai/functions")
async def get_openai_functions(category: Optional[str] = None):
    """Get OpenAI function definitions for available tools."""
    try:
        registry = await get_dynamic_registry()
        functions = await registry.get_openai_functions(category=category)

        return {"functions": functions, "total_count": len(functions), "category": category, "registry_type": "dynamic"}

    except Exception as e:
        logger.error(f"Failed to get OpenAI functions: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to retrieve OpenAI functions"
        )
