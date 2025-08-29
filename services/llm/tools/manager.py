"""
Tool Manager for RAGline LLM Tools

Manages tool registry, execution, and integration with the chat service.
"""

import json
import logging
from typing import Any, Dict, List, Optional

from . import TOOLS
from .base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class ToolManager:
    """
    Manages LLM tool registration, validation, and execution.

    Provides a unified interface for the chat service to interact with tools.
    """

    def __init__(self, tenant_id: Optional[str] = None, user_id: Optional[str] = None):
        """Initialize tool manager with context."""
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.tools: Dict[str, BaseTool] = {}

        # Initialize available tools
        self._register_tools()

    def _register_tools(self):
        """Register all available tools."""
        for tool_name, tool_class in TOOLS.items():
            try:
                tool_instance = tool_class(tenant_id=self.tenant_id, user_id=self.user_id)
                self.tools[tool_name] = tool_instance
                logger.info(f"Registered tool: {tool_name}")
            except Exception as e:
                logger.error(f"Failed to register tool {tool_name}: {e}")

    def get_available_tools(self) -> List[str]:
        """Get list of available tool names."""
        return list(self.tools.keys())

    def get_tool(self, tool_name: str) -> Optional[BaseTool]:
        """Get tool instance by name."""
        return self.tools.get(tool_name)

    def get_openai_functions(self) -> List[Dict[str, Any]]:
        """Get OpenAI function definitions for all tools."""
        functions = []
        for tool in self.tools.values():
            try:
                functions.append(tool.to_openai_function())
            except Exception as e:
                logger.error(f"Failed to get function definition for {tool.name}: {e}")
        return functions

    def get_tools_schema(self) -> Dict[str, Any]:
        """Get complete tools schema for API documentation."""
        schema = {"tools": {}, "total_count": len(self.tools)}

        for tool_name, tool in self.tools.items():
            try:
                schema["tools"][tool_name] = {
                    "name": tool.name,
                    "description": tool.description,
                    "schema": tool.get_schema(),
                    "openai_function": tool.to_openai_function(),
                }
            except Exception as e:
                logger.error(f"Failed to get schema for {tool_name}: {e}")
                schema["tools"][tool_name] = {"error": f"Schema generation failed: {e}"}

        return schema

    async def execute_tool(
        self,
        tool_name: str,
        arguments: str | Dict[str, Any],
        tool_call_id: Optional[str] = None,
    ) -> ToolResult:
        """
        Execute a tool with given arguments.

        Args:
            tool_name: Name of tool to execute
            arguments: Tool arguments (JSON string or dict)
            tool_call_id: Optional tool call ID for tracking

        Returns:
            ToolResult with execution details
        """
        # Get tool instance
        tool = self.get_tool(tool_name)
        if not tool:
            return ToolResult(success=False, error=f"Tool '{tool_name}' not found", latency_ms=0)

        # Parse arguments if they're a JSON string
        if isinstance(arguments, str):
            try:
                parsed_args = json.loads(arguments)
            except json.JSONDecodeError as e:
                return ToolResult(success=False, error=f"Invalid JSON arguments: {e}", latency_ms=0)
        else:
            parsed_args = arguments

        # Execute tool
        try:
            result = await tool.run(**parsed_args)

            # Add tool call tracking info
            if hasattr(result, "data") and isinstance(result.data, dict):
                result.data.update(
                    {
                        "tool_name": tool_name,
                        "tool_call_id": tool_call_id,
                        "tenant_id": self.tenant_id,
                        "user_id": self.user_id,
                    }
                )

            logger.info(f"Tool executed: {tool_name}, success: {result.success}, latency: {result.latency_ms:.1f}ms")

            return result

        except Exception as e:
            logger.error(f"Tool execution error for {tool_name}: {e}")
            return ToolResult(success=False, error=f"Tool execution failed: {e}", latency_ms=0)

    async def execute_tool_calls(self, tool_calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Execute multiple tool calls from OpenAI response.

        Args:
            tool_calls: List of OpenAI tool call objects

        Returns:
            List of tool results for chat completion
        """
        results = []

        for tool_call in tool_calls:
            try:
                tool_call_id = tool_call.get("id")
                function_info = tool_call.get("function", {})
                function_name = function_info.get("name")
                function_args = function_info.get("arguments", "{}")

                # Execute tool
                result = await self.execute_tool(
                    tool_name=function_name,
                    arguments=function_args,
                    tool_call_id=tool_call_id,
                )

                # Format result for OpenAI
                tool_response = {
                    "tool_call_id": tool_call_id,
                    "role": "tool",
                    "name": function_name,
                    "content": json.dumps(
                        {
                            "success": result.success,
                            "data": result.data,
                            "error": result.error,
                            "latency_ms": result.latency_ms,
                        }
                    ),
                }

                results.append(tool_response)

            except Exception as e:
                logger.error(f"Failed to execute tool call: {e}")
                # Add error response
                error_response = {
                    "tool_call_id": tool_call.get("id"),
                    "role": "tool",
                    "name": tool_call.get("function", {}).get("name", "unknown"),
                    "content": json.dumps(
                        {
                            "success": False,
                            "error": f"Tool call execution failed: {e}",
                            "latency_ms": 0,
                        }
                    ),
                }
                results.append(error_response)

        return results

    def validate_tool_call(self, tool_name: str, arguments: Dict[str, Any]) -> bool:
        """
        Validate a tool call before execution.

        Args:
            tool_name: Name of tool
            arguments: Tool arguments

        Returns:
            True if valid, False otherwise
        """
        tool = self.get_tool(tool_name)
        if not tool:
            return False

        try:
            tool.validate_args(**arguments)
            return True
        except Exception:
            return False


# Global tool manager instance
_tool_manager: Optional[ToolManager] = None


def get_tool_manager(tenant_id: Optional[str] = None, user_id: Optional[str] = None) -> ToolManager:
    """Get or create global tool manager instance."""
    global _tool_manager

    if _tool_manager is None or _tool_manager.tenant_id != tenant_id or _tool_manager.user_id != user_id:
        _tool_manager = ToolManager(tenant_id=tenant_id, user_id=user_id)

    return _tool_manager
