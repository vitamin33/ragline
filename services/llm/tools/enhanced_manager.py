"""
Enhanced Tool Manager

Bridges the existing tool system with the new dynamic registry.
Provides backward compatibility while adding advanced features.
"""

import logging
import os
import sys
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))

from services.llm.registry.dynamic_registry import (
    DynamicToolRegistry,
    ToolMetadata,
    ToolStatus,
    ToolVersion,
    get_dynamic_registry,
)

from .base import BaseTool, ToolResult
from .manager import ToolManager

logger = logging.getLogger(__name__)


class EnhancedToolManager(ToolManager):
    """
    Enhanced tool manager with dynamic registry integration.

    Extends the base ToolManager with:
    - Dynamic tool registration
    - Tool versioning
    - Dependency management
    - Performance tracking
    - Hot-swapping capabilities
    """

    def __init__(self, tenant_id: Optional[str] = None, user_id: Optional[str] = None):
        """Initialize enhanced tool manager."""
        super().__init__(tenant_id, user_id)
        self.dynamic_registry: Optional[DynamicToolRegistry] = None

    async def _ensure_dynamic_registry(self):
        """Ensure dynamic registry is initialized."""
        if self.dynamic_registry is None:
            self.dynamic_registry = await get_dynamic_registry(tenant_id=self.tenant_id, user_id=self.user_id)

    async def register_tool_runtime(
        self,
        tool_class: type,
        name: str,
        description: str,
        category: str = "custom",
        version: Optional[ToolVersion] = None,
        dependencies: Optional[List[str]] = None,
        **metadata_kwargs,
    ) -> bool:
        """
        Register a new tool at runtime.

        Args:
            tool_class: Tool class to register
            name: Tool name
            description: Tool description
            category: Tool category
            version: Tool version (defaults to 1.0.0)
            dependencies: List of dependency tool names
            **metadata_kwargs: Additional metadata

        Returns:
            True if registration successful
        """
        await self._ensure_dynamic_registry()

        try:
            # Create tool metadata
            metadata = ToolMetadata(
                name=name,
                version=version or ToolVersion(major=1, minor=0, patch=0),
                description=description,
                category=category,
                status=ToolStatus.ACTIVE,
                **metadata_kwargs,
            )

            # Add dependencies if specified
            if dependencies:
                from ..registry.dynamic_registry import ToolDependency

                metadata.dependencies = [
                    ToolDependency(tool_name=dep_name, optional=False) for dep_name in dependencies
                ]

            # Register with dynamic registry
            success = await self.dynamic_registry.register_tool(tool_class=tool_class, metadata=metadata, force=True)

            if success:
                # Add to legacy tools dict for backward compatibility
                self.tools[name] = tool_class(tenant_id=self.tenant_id, user_id=self.user_id)
                logger.info(f"Runtime tool registered: {name} v{metadata.version}")

            return success

        except Exception as e:
            logger.error(f"Failed to register runtime tool {name}: {e}")
            return False

    async def unregister_tool_runtime(self, tool_name: str) -> bool:
        """
        Unregister a tool at runtime.

        Args:
            tool_name: Name of tool to unregister

        Returns:
            True if unregistration successful
        """
        await self._ensure_dynamic_registry()

        success = await self.dynamic_registry.unregister_tool(tool_name)

        if success and tool_name in self.tools:
            del self.tools[tool_name]
            logger.info(f"Runtime tool unregistered: {tool_name}")

        return success

    async def execute_tool_enhanced(
        self,
        tool_name: str,
        arguments: str | Dict[str, Any],
        tool_call_id: Optional[str] = None,
        version: Optional[ToolVersion] = None,
        use_cache: bool = True,
    ) -> ToolResult:
        """
        Execute tool with enhanced tracking and validation.

        Args:
            tool_name: Name of tool to execute
            arguments: Tool arguments
            tool_call_id: Optional call ID for tracking
            version: Specific version to use
            use_cache: Whether to use result caching

        Returns:
            Enhanced ToolResult with registry metadata
        """
        await self._ensure_dynamic_registry()

        # Use dynamic registry if available, fallback to legacy
        if self.dynamic_registry and tool_name in self.dynamic_registry.tools:
            return await self.dynamic_registry.execute_tool(
                tool_name=tool_name, arguments=arguments, tool_call_id=tool_call_id, version=version
            )
        else:
            # Fallback to legacy execution
            return await self.execute_tool(tool_name, arguments, tool_call_id)

    async def get_enhanced_tools_schema(self) -> Dict[str, Any]:
        """Get enhanced tools schema with dynamic registry information."""
        await self._ensure_dynamic_registry()

        # Get legacy schema as base
        base_schema = self.get_tools_schema()

        # Enhance with dynamic registry data
        if self.dynamic_registry:
            registry_stats = await self.dynamic_registry.get_registry_stats()

            enhanced_schema = {
                **base_schema,
                "registry_type": "enhanced_dynamic",
                "registry_stats": registry_stats,
                "tools_enhanced": {},
            }

            # Add enhanced metadata for each tool
            for tool_name in self.dynamic_registry.tools:
                metadata = await self.dynamic_registry.get_tool_metadata(tool_name)
                if metadata:
                    enhanced_schema["tools_enhanced"][tool_name] = {
                        "version": str(metadata.version),
                        "category": metadata.category,
                        "status": metadata.status,
                        "dependencies": [dep.tool_name for dep in metadata.dependencies],
                        "performance": {
                            "execution_count": metadata.execution_count,
                            "success_count": metadata.success_count,
                            "error_count": metadata.error_count,
                            "estimated_latency_ms": metadata.estimated_latency_ms,
                        },
                    }

            return enhanced_schema

        return base_schema

    async def get_tool_dependencies(self, tool_name: str) -> List[str]:
        """Get tool dependencies."""
        await self._ensure_dynamic_registry()

        if self.dynamic_registry and tool_name in self.dynamic_registry.tools:
            metadata = await self.dynamic_registry.get_tool_metadata(tool_name)
            if metadata:
                return [dep.tool_name for dep in metadata.dependencies]

        return []

    async def validate_tool_chain(self, tool_names: List[str]) -> Dict[str, Any]:
        """
        Validate a chain of tool executions for dependencies.

        Args:
            tool_names: List of tools to validate as a chain

        Returns:
            Validation result with dependency analysis
        """
        await self._ensure_dynamic_registry()

        validation_result = {
            "valid": True,
            "tool_chain": tool_names,
            "dependency_issues": [],
            "execution_order": [],
            "estimated_total_latency_ms": 0,
        }

        if not self.dynamic_registry:
            validation_result["valid"] = False
            validation_result["dependency_issues"].append("Dynamic registry not available")
            return validation_result

        # Check each tool and build dependency order
        available_tools = set()

        for tool_name in tool_names:
            if tool_name not in self.dynamic_registry.tools:
                validation_result["valid"] = False
                validation_result["dependency_issues"].append(f"Tool '{tool_name}' not found")
                continue

            # Check dependencies
            metadata = await self.dynamic_registry.get_tool_metadata(tool_name)
            if metadata:
                for dependency in metadata.dependencies:
                    if not dependency.optional and dependency.tool_name not in available_tools:
                        if dependency.tool_name not in tool_names:
                            validation_result["valid"] = False
                            validation_result["dependency_issues"].append(
                                f"Tool '{tool_name}' requires '{dependency.tool_name}' which is not in chain"
                            )

                # Add to execution order
                validation_result["execution_order"].append(tool_name)
                validation_result["estimated_total_latency_ms"] += metadata.estimated_latency_ms or 100

                available_tools.add(tool_name)

        return validation_result


# Global enhanced tool manager instance
_enhanced_manager: Optional[EnhancedToolManager] = None


async def get_enhanced_tool_manager(
    tenant_id: Optional[str] = None, user_id: Optional[str] = None
) -> EnhancedToolManager:
    """Get or create global enhanced tool manager instance."""
    global _enhanced_manager

    if _enhanced_manager is None or _enhanced_manager.tenant_id != tenant_id or _enhanced_manager.user_id != user_id:
        _enhanced_manager = EnhancedToolManager(tenant_id=tenant_id, user_id=user_id)

    return _enhanced_manager
