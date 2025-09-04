"""
Dynamic Tool Registry

Advanced tool management system supporting:
- Runtime tool registration/removal
- Tool schema validation
- Dependency management
- Tool versioning
- Hot-swapping without service restart
"""

import asyncio
import json
import logging
import time
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Type

from pydantic import BaseModel, Field, ValidationError

from ..tools.base import BaseTool, ToolError, ToolResult

logger = logging.getLogger(__name__)


class ToolStatus(str, Enum):
    """Tool status enumeration."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    DEPRECATED = "deprecated"
    DISABLED = "disabled"


class ToolVersion(BaseModel):
    """Tool version information."""

    major: int = Field(..., description="Major version number")
    minor: int = Field(..., description="Minor version number")
    patch: int = Field(..., description="Patch version number")
    label: Optional[str] = Field(None, description="Version label (alpha, beta, rc)")

    def __str__(self) -> str:
        """String representation of version."""
        base = f"{self.major}.{self.minor}.{self.patch}"
        return f"{base}-{self.label}" if self.label else base

    def __lt__(self, other: "ToolVersion") -> bool:
        """Version comparison for sorting."""
        return (self.major, self.minor, self.patch) < (other.major, other.minor, other.patch)


class ToolDependency(BaseModel):
    """Tool dependency specification."""

    tool_name: str = Field(..., description="Name of dependency tool")
    min_version: Optional[ToolVersion] = Field(None, description="Minimum required version")
    max_version: Optional[ToolVersion] = Field(None, description="Maximum supported version")
    optional: bool = Field(False, description="Whether dependency is optional")
    description: str = Field("", description="Dependency description")


class ToolMetadata(BaseModel):
    """Comprehensive tool metadata."""

    name: str = Field(..., description="Tool name")
    version: ToolVersion = Field(..., description="Tool version")
    description: str = Field(..., description="Tool description")
    category: str = Field("general", description="Tool category")
    author: str = Field("", description="Tool author")
    status: ToolStatus = Field(ToolStatus.ACTIVE, description="Tool status")

    # Dependencies and requirements
    dependencies: List[ToolDependency] = Field(default_factory=list, description="Tool dependencies")
    requires_auth: bool = Field(False, description="Whether tool requires authentication")
    requires_database: bool = Field(False, description="Whether tool requires database access")
    requires_external_api: bool = Field(False, description="Whether tool calls external APIs")

    # Performance characteristics
    estimated_latency_ms: Optional[int] = Field(None, description="Estimated execution latency")
    cache_ttl_seconds: Optional[int] = Field(None, description="Default cache TTL")
    max_concurrent_executions: Optional[int] = Field(None, description="Max concurrent executions")

    # Schema and validation
    parameter_schema: Dict[str, Any] = Field(default_factory=dict, description="Tool parameter schema")
    response_schema: Dict[str, Any] = Field(default_factory=dict, description="Tool response schema")

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    last_used_at: Optional[datetime] = Field(None, description="Last execution timestamp")

    # Usage statistics
    execution_count: int = Field(0, description="Total execution count")
    success_count: int = Field(0, description="Successful execution count")
    error_count: int = Field(0, description="Failed execution count")


class RegisteredTool(BaseModel):
    """Registered tool container."""

    metadata: ToolMetadata = Field(..., description="Tool metadata")
    tool_class: Type[BaseTool] = Field(..., description="Tool class")
    tool_instance: Optional[BaseTool] = Field(None, description="Tool instance")

    class Config:
        arbitrary_types_allowed = True


class DynamicToolRegistry:
    """
    Advanced dynamic tool registry with versioning and dependency management.

    Features:
    - Runtime tool registration/removal
    - Tool schema validation
    - Dependency resolution
    - Version management
    - Performance monitoring
    - Hot-swapping capabilities
    """

    def __init__(self, tenant_id: Optional[str] = None, user_id: Optional[str] = None):
        """Initialize dynamic tool registry."""
        self.tenant_id = tenant_id
        self.user_id = user_id

        # Core registry storage
        self.tools: Dict[str, RegisteredTool] = {}
        self.tool_versions: Dict[str, List[ToolVersion]] = {}
        self.active_versions: Dict[str, ToolVersion] = {}

        # Dependency graph
        self.dependency_graph: Dict[str, Set[str]] = {}
        self.reverse_dependencies: Dict[str, Set[str]] = {}

        # Performance tracking
        self.execution_stats: Dict[str, Dict[str, Any]] = {}

        # Locks for thread safety
        self._registry_lock = asyncio.Lock()
        self._stats_lock = asyncio.Lock()

        # Load default tools
        asyncio.create_task(self._load_default_tools())

    async def _load_default_tools(self):
        """Load default tools from the existing tool system."""
        try:
            from ..tools import TOOLS

            for tool_name, tool_class in TOOLS.items():
                # Set appropriate metadata for each tool type
                if tool_name == "search_knowledge_base":
                    estimated_latency = 100
                    cache_ttl = 600
                    requires_db = True
                elif tool_name == "retrieve_menu":
                    estimated_latency = 50
                    cache_ttl = 300
                    requires_db = True
                else:
                    estimated_latency = 10
                    cache_ttl = 60
                    requires_db = False

                await self.register_tool(
                    tool_class=tool_class,
                    metadata=ToolMetadata(
                        name=tool_name,
                        version=ToolVersion(major=1, minor=0, patch=0),
                        description=tool_class().description,
                        category="core",
                        status=ToolStatus.ACTIVE,
                        parameter_schema=tool_class().get_schema(),
                        requires_database=requires_db,
                        requires_external_api=False,
                        estimated_latency_ms=estimated_latency,
                        cache_ttl_seconds=cache_ttl,
                    ),
                )

            logger.info(f"Loaded {len(TOOLS)} default tools into dynamic registry")

        except Exception as e:
            logger.error(f"Failed to load default tools: {e}")

    async def register_tool(self, tool_class: Type[BaseTool], metadata: ToolMetadata, force: bool = False) -> bool:
        """
        Register a new tool or update existing tool.

        Args:
            tool_class: Tool class to register
            metadata: Tool metadata and configuration
            force: Whether to force registration over existing tool

        Returns:
            True if registration successful
        """
        async with self._registry_lock:
            try:
                tool_name = metadata.name

                # Check if tool already exists
                if tool_name in self.tools and not force:
                    existing_version = self.tools[tool_name].metadata.version
                    if metadata.version <= existing_version:
                        logger.warning(
                            f"Tool {tool_name} version {metadata.version} not newer than existing {existing_version}"
                        )
                        return False

                # Validate tool class
                if not issubclass(tool_class, BaseTool):
                    raise ValueError("Tool class must inherit from BaseTool")

                # Create tool instance for validation
                tool_instance = tool_class(tenant_id=self.tenant_id, user_id=self.user_id)

                # Validate metadata consistency
                if tool_instance.name != metadata.name:
                    raise ValueError(f"Tool name mismatch: {tool_instance.name} != {metadata.name}")

                if tool_instance.description != metadata.description:
                    logger.warning(f"Description mismatch for {tool_name}")
                    metadata.description = tool_instance.description

                # Validate dependencies
                await self._validate_dependencies(metadata.dependencies)

                # Register the tool
                registered_tool = RegisteredTool(metadata=metadata, tool_class=tool_class, tool_instance=tool_instance)

                # Update registry
                old_tool = self.tools.get(tool_name)
                self.tools[tool_name] = registered_tool

                # Update version tracking
                if tool_name not in self.tool_versions:
                    self.tool_versions[tool_name] = []

                if metadata.version not in self.tool_versions[tool_name]:
                    self.tool_versions[tool_name].append(metadata.version)
                    self.tool_versions[tool_name].sort()

                self.active_versions[tool_name] = metadata.version

                # Update dependency graph
                await self._update_dependency_graph(tool_name, metadata.dependencies)

                # Initialize performance tracking
                if tool_name not in self.execution_stats:
                    self.execution_stats[tool_name] = {
                        "total_executions": 0,
                        "total_successes": 0,
                        "total_errors": 0,
                        "total_latency_ms": 0,
                        "last_execution": None,
                        "avg_latency_ms": 0,
                    }

                action = "Updated" if old_tool else "Registered"
                logger.info(f"{action} tool: {tool_name} v{metadata.version}")

                return True

            except Exception as e:
                logger.error(f"Failed to register tool {metadata.name}: {e}")
                return False

    async def unregister_tool(self, tool_name: str) -> bool:
        """
        Unregister a tool and handle dependencies.

        Args:
            tool_name: Name of tool to unregister

        Returns:
            True if unregistration successful
        """
        async with self._registry_lock:
            try:
                if tool_name not in self.tools:
                    logger.warning(f"Tool {tool_name} not found for unregistration")
                    return False

                # Check for dependent tools
                dependents = self.reverse_dependencies.get(tool_name, set())
                if dependents:
                    active_dependents = [
                        dep
                        for dep in dependents
                        if dep in self.tools and self.tools[dep].metadata.status == ToolStatus.ACTIVE
                    ]

                    if active_dependents:
                        logger.error(f"Cannot unregister {tool_name}: active dependents {active_dependents}")
                        return False

                # Remove from registry
                del self.tools[tool_name]

                # Clean up dependency graph
                if tool_name in self.dependency_graph:
                    del self.dependency_graph[tool_name]

                for deps in self.reverse_dependencies.values():
                    deps.discard(tool_name)

                if tool_name in self.reverse_dependencies:
                    del self.reverse_dependencies[tool_name]

                logger.info(f"Unregistered tool: {tool_name}")
                return True

            except Exception as e:
                logger.error(f"Failed to unregister tool {tool_name}: {e}")
                return False

    async def get_tool(self, tool_name: str, version: Optional[ToolVersion] = None) -> Optional[BaseTool]:
        """
        Get tool instance by name and optional version.

        Args:
            tool_name: Name of tool
            version: Specific version (uses active version if not specified)

        Returns:
            Tool instance or None if not found
        """
        if tool_name not in self.tools:
            return None

        registered_tool = self.tools[tool_name]

        # Check version compatibility if specified
        if version and registered_tool.metadata.version != version:
            logger.warning(
                f"Version mismatch for {tool_name}: requested {version}, active {registered_tool.metadata.version}"
            )
            return None

        # Check tool status
        if registered_tool.metadata.status not in [ToolStatus.ACTIVE, ToolStatus.DEPRECATED]:
            logger.warning(f"Tool {tool_name} is {registered_tool.metadata.status}, not available")
            return None

        return registered_tool.tool_instance

    async def execute_tool(
        self,
        tool_name: str,
        arguments: str | Dict[str, Any],
        tool_call_id: Optional[str] = None,
        version: Optional[ToolVersion] = None,
    ) -> ToolResult:
        """
        Execute tool with enhanced tracking and validation.

        Args:
            tool_name: Name of tool to execute
            arguments: Tool arguments
            tool_call_id: Optional call ID for tracking
            version: Specific version to use

        Returns:
            ToolResult with execution details
        """
        start_time = time.time()

        try:
            # Get tool instance
            tool = await self.get_tool(tool_name, version)
            if not tool:
                return ToolResult(success=False, error=f"Tool '{tool_name}' not found or unavailable", latency_ms=0)

            # Parse arguments if string
            if isinstance(arguments, str):
                try:
                    parsed_args = json.loads(arguments)
                except json.JSONDecodeError as e:
                    return ToolResult(
                        success=False,
                        error=f"Invalid JSON arguments: {e}",
                        latency_ms=(time.time() - start_time) * 1000,
                    )
            else:
                parsed_args = arguments

            # Validate arguments against schema
            validation_result = await self._validate_tool_arguments(tool_name, parsed_args)
            if not validation_result.valid:
                return ToolResult(
                    success=False,
                    error=f"Argument validation failed: {validation_result.error}",
                    latency_ms=(time.time() - start_time) * 1000,
                )

            # Check dependencies
            dependency_check = await self._check_dependencies(tool_name)
            if not dependency_check.satisfied:
                return ToolResult(
                    success=False,
                    error=f"Dependencies not satisfied: {dependency_check.missing}",
                    latency_ms=(time.time() - start_time) * 1000,
                )

            # Execute tool
            result = await tool.run(**parsed_args)

            # Update performance statistics
            await self._update_execution_stats(tool_name, result)

            # Update tool metadata
            registered_tool = self.tools[tool_name]
            registered_tool.metadata.last_used_at = datetime.now()
            registered_tool.metadata.execution_count += 1

            if result.success:
                registered_tool.metadata.success_count += 1
            else:
                registered_tool.metadata.error_count += 1

            # Add registry metadata to result
            if hasattr(result, "data") and isinstance(result.data, dict):
                result.data.update(
                    {
                        "tool_registry": {
                            "tool_name": tool_name,
                            "version": str(registered_tool.metadata.version),
                            "category": registered_tool.metadata.category,
                            "execution_id": tool_call_id,
                            "registry_type": "dynamic",
                        }
                    }
                )

            logger.debug(
                f"Tool executed: {tool_name} v{registered_tool.metadata.version}, success: {result.success}, latency: {result.latency_ms:.1f}ms"
            )

            return result

        except Exception as e:
            latency = (time.time() - start_time) * 1000
            logger.error(f"Tool execution error for {tool_name}: {e}")

            # Update error stats
            await self._update_execution_stats(tool_name, ToolResult(success=False, error=str(e), latency_ms=latency))

            return ToolResult(success=False, error=f"Tool execution failed: {e}", latency_ms=latency)

    async def get_available_tools(
        self, category: Optional[str] = None, status: Optional[ToolStatus] = None
    ) -> List[str]:
        """
        Get list of available tool names with optional filtering.

        Args:
            category: Filter by tool category
            status: Filter by tool status

        Returns:
            List of available tool names
        """
        tools = []

        for tool_name, registered_tool in self.tools.items():
            # Apply category filter
            if category and registered_tool.metadata.category != category:
                continue

            # Apply status filter
            if status and registered_tool.metadata.status != status:
                continue

            # Only include active and deprecated tools
            if registered_tool.metadata.status in [ToolStatus.ACTIVE, ToolStatus.DEPRECATED]:
                tools.append(tool_name)

        return sorted(tools)

    async def get_tool_metadata(self, tool_name: str) -> Optional[ToolMetadata]:
        """Get comprehensive tool metadata."""
        if tool_name not in self.tools:
            return None

        return self.tools[tool_name].metadata

    async def get_tool_schema(self, tool_name: str) -> Dict[str, Any]:
        """Get tool parameter schema for validation."""
        if tool_name not in self.tools:
            return {}

        return self.tools[tool_name].metadata.parameter_schema

    async def get_openai_functions(self, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get OpenAI function definitions for available tools."""
        functions = []

        for tool_name in await self.get_available_tools(category=category):
            tool = await self.get_tool(tool_name)
            if tool:
                try:
                    function_def = tool.to_openai_function()

                    # Add registry metadata
                    metadata = self.tools[tool_name].metadata
                    function_def["metadata"] = {
                        "version": str(metadata.version),
                        "category": metadata.category,
                        "estimated_latency_ms": metadata.estimated_latency_ms,
                        "requires_auth": metadata.requires_auth,
                    }

                    functions.append(function_def)
                except Exception as e:
                    logger.error(f"Failed to get function definition for {tool_name}: {e}")

        return functions

    async def get_registry_stats(self) -> Dict[str, Any]:
        """Get comprehensive registry statistics."""
        async with self._stats_lock:
            total_tools = len(self.tools)
            active_tools = len([t for t in self.tools.values() if t.metadata.status == ToolStatus.ACTIVE])

            # Aggregate execution statistics
            total_executions = sum(t.metadata.execution_count for t in self.tools.values())
            total_successes = sum(t.metadata.success_count for t in self.tools.values())
            total_errors = sum(t.metadata.error_count for t in self.tools.values())

            # Calculate success rate
            success_rate = (total_successes / total_executions * 100) if total_executions > 0 else 0

            # Get categories
            categories = list(set(t.metadata.category for t in self.tools.values()))

            # Get most used tools
            most_used = sorted(
                [(name, tool.metadata.execution_count) for name, tool in self.tools.items()],
                key=lambda x: x[1],
                reverse=True,
            )[:5]

            return {
                "total_tools": total_tools,
                "active_tools": active_tools,
                "total_executions": total_executions,
                "success_rate": round(success_rate, 2),
                "categories": categories,
                "most_used_tools": most_used,
                "registry_type": "dynamic",
                "tenant_id": self.tenant_id,
                "user_id": self.user_id,
                "last_updated": datetime.now().isoformat(),
            }

    async def _validate_dependencies(self, dependencies: List[ToolDependency]) -> None:
        """Validate tool dependencies."""
        for dependency in dependencies:
            if dependency.tool_name not in self.tools and not dependency.optional:
                raise ValueError(f"Required dependency '{dependency.tool_name}' not available")

            if dependency.tool_name in self.tools:
                dep_version = self.tools[dependency.tool_name].metadata.version

                if dependency.min_version and dep_version < dependency.min_version:
                    raise ValueError(
                        f"Dependency {dependency.tool_name} version {dep_version} < required {dependency.min_version}"
                    )

                if dependency.max_version and dep_version > dependency.max_version:
                    raise ValueError(
                        f"Dependency {dependency.tool_name} version {dep_version} > maximum {dependency.max_version}"
                    )

    async def _validate_tool_arguments(self, tool_name: str, arguments: Dict[str, Any]) -> "ValidationResult":
        """Validate tool arguments against schema."""
        try:
            tool = await self.get_tool(tool_name)
            if not tool:
                return ValidationResult(valid=False, error=f"Tool {tool_name} not found")

            # Use tool's built-in validation
            validated_args = tool.validate_args(**arguments)
            return ValidationResult(valid=True, validated_args=validated_args)

        except Exception as e:
            return ValidationResult(valid=False, error=str(e))

    async def _check_dependencies(self, tool_name: str) -> "DependencyCheckResult":
        """Check if tool dependencies are satisfied."""
        if tool_name not in self.tools:
            return DependencyCheckResult(satisfied=False, missing=[tool_name])

        dependencies = self.tools[tool_name].metadata.dependencies
        missing = []

        for dependency in dependencies:
            if dependency.tool_name not in self.tools:
                if not dependency.optional:
                    missing.append(dependency.tool_name)
                continue

            # Check if dependency is active
            dep_tool = self.tools[dependency.tool_name]
            if dep_tool.metadata.status not in [ToolStatus.ACTIVE, ToolStatus.DEPRECATED]:
                if not dependency.optional:
                    missing.append(f"{dependency.tool_name} (inactive)")

        return DependencyCheckResult(satisfied=len(missing) == 0, missing=missing)

    async def _update_dependency_graph(self, tool_name: str, dependencies: List[ToolDependency]) -> None:
        """Update internal dependency graph."""
        # Clear existing dependencies
        if tool_name in self.dependency_graph:
            for dep in self.dependency_graph[tool_name]:
                self.reverse_dependencies[dep].discard(tool_name)

        # Add new dependencies
        self.dependency_graph[tool_name] = set()

        for dependency in dependencies:
            dep_name = dependency.tool_name
            self.dependency_graph[tool_name].add(dep_name)

            if dep_name not in self.reverse_dependencies:
                self.reverse_dependencies[dep_name] = set()
            self.reverse_dependencies[dep_name].add(tool_name)

    async def _update_execution_stats(self, tool_name: str, result: ToolResult) -> None:
        """Update tool execution statistics."""
        async with self._stats_lock:
            if tool_name not in self.execution_stats:
                self.execution_stats[tool_name] = {
                    "total_executions": 0,
                    "total_successes": 0,
                    "total_errors": 0,
                    "total_latency_ms": 0,
                    "last_execution": None,
                    "avg_latency_ms": 0,
                }

            stats = self.execution_stats[tool_name]
            stats["total_executions"] += 1
            stats["total_latency_ms"] += result.latency_ms
            stats["last_execution"] = time.time()

            if result.success:
                stats["total_successes"] += 1
            else:
                stats["total_errors"] += 1

            # Update average latency
            stats["avg_latency_ms"] = stats["total_latency_ms"] / stats["total_executions"]


class ValidationResult(BaseModel):
    """Tool argument validation result."""

    valid: bool = Field(..., description="Whether validation passed")
    error: Optional[str] = Field(None, description="Validation error message")
    validated_args: Optional[Dict[str, Any]] = Field(None, description="Validated arguments")


class DependencyCheckResult(BaseModel):
    """Tool dependency check result."""

    satisfied: bool = Field(..., description="Whether all dependencies satisfied")
    missing: List[str] = Field(default_factory=list, description="List of missing dependencies")


# Global dynamic registry instance
_dynamic_registry: Optional[DynamicToolRegistry] = None


async def get_dynamic_registry(tenant_id: Optional[str] = None, user_id: Optional[str] = None) -> DynamicToolRegistry:
    """Get or create global dynamic tool registry instance."""
    global _dynamic_registry

    if _dynamic_registry is None or _dynamic_registry.tenant_id != tenant_id or _dynamic_registry.user_id != user_id:
        _dynamic_registry = DynamicToolRegistry(tenant_id=tenant_id, user_id=user_id)

        # Allow time for default tools to load
        await asyncio.sleep(0.1)

    return _dynamic_registry
