"""
Chat endpoint with streaming support via SSE and WebSocket.
Supports tool calling and RAG-enhanced responses.
"""

import asyncio
import json
import logging
import sys
import uuid
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Add packages to path for LLM client
sys.path.insert(0, "../../packages")

try:
    from rag.llm_client import ChatMessage as LLMChatMessage
    from rag.llm_client import get_llm_client

    LLM_CLIENT_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Could not import LLM client: {e}")
    LLM_CLIENT_AVAILABLE = False

# Import tool system
try:
    from tools.manager import get_tool_manager

    TOOLS_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Could not import tools: {e}")
    TOOLS_AVAILABLE = False

# Import enhanced streaming
try:
    from streaming import (
        BufferedEventSourceResponse,
        TokenLimitManager,
        get_streaming_manager,
    )

    ENHANCED_STREAMING_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Could not import enhanced streaming: {e}")
    ENHANCED_STREAMING_AVAILABLE = False

# Use StreamingResponse instead of EventSourceResponse for now
try:
    from sse_starlette.sse import EventSourceResponse
except ImportError:
    # Fallback to StreamingResponse if sse-starlette not available
    EventSourceResponse = StreamingResponse


class ChatMessage(BaseModel):
    """Chat message model."""

    role: str = Field(..., description="Message role: user, assistant, system")
    content: str = Field(..., description="Message content")
    timestamp: Optional[datetime] = None


class ChatRequest(BaseModel):
    """Chat request payload."""

    messages: List[ChatMessage] = Field(..., description="Conversation messages")
    stream: bool = Field(default=True, description="Enable streaming response")
    tools_enabled: bool = Field(default=True, description="Enable tool calling")
    tenant_id: Optional[str] = Field(None, description="Tenant ID for multi-tenancy")
    user_id: Optional[str] = Field(None, description="User ID for context")
    session_id: Optional[str] = Field(None, description="Session ID for conversation memory")
    max_tokens: Optional[int] = Field(None, description="Override max response tokens")
    use_conversation_memory: bool = Field(default=True, description="Use conversation history")


class ChatResponse(BaseModel):
    """Chat response payload."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    choices: List[Dict[str, Any]] = Field(default_factory=list)
    usage: Optional[Dict[str, Any]] = None  # Changed from int to Any to handle complex usage objects
    created: int = Field(default_factory=lambda: int(datetime.now().timestamp()))


class ToolCall(BaseModel):
    """Tool call event model."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: str = Field(default="function")
    function: Dict[str, Any] = Field(..., description="Function details")


router = APIRouter()


# Connection manager for WebSocket connections
class ConnectionManager:
    """Manages WebSocket connections for real-time chat."""

    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, client_id: str):
        await websocket.accept()
        self.active_connections[client_id] = websocket

    def disconnect(self, client_id: str):
        if client_id in self.active_connections:
            del self.active_connections[client_id]

    async def send_personal_message(self, message: str, client_id: str):
        if client_id in self.active_connections:
            await self.active_connections[client_id].send_text(message)


manager = ConnectionManager()


async def generate_chat_stream(
    request: ChatRequest,
    messages: Optional[List[ChatMessage]] = None,
    token_manager: Optional[Any] = None,
    app_state: Optional[Any] = None,
) -> AsyncGenerator[str, None]:
    """Generate streaming chat response with tool calling support."""

    try:
        # Get LLM client from app state or fallback
        client = None
        if app_state and hasattr(app_state, "llm_client"):
            client = app_state.llm_client
        elif LLM_CLIENT_AVAILABLE:
            client = get_llm_client()

        if not client:
            yield f"data: {json.dumps({'type': 'error', 'message': 'LLM client not available'})}\n\n"
            return

        # Use enhanced messages if provided, otherwise use request messages
        source_messages = messages or request.messages

        # Convert messages to LLM format
        llm_messages = [LLMChatMessage(role=msg.role, content=msg.content) for msg in source_messages]

        # Define tools if enabled
        tools = None
        tool_manager = None
        if request.tools_enabled and TOOLS_AVAILABLE:
            try:
                # Get tool manager from app state or create new one
                if app_state and hasattr(app_state, "tool_manager"):
                    tool_manager = app_state.tool_manager
                else:
                    tool_manager = get_tool_manager(tenant_id=request.tenant_id, user_id=request.user_id)

                tools = tool_manager.get_openai_functions()
            except Exception as e:
                print(f"Warning: Failed to load tools for streaming: {e}")
                tools = None

        # Configure response parameters with token limits
        response_config = {
            "messages": llm_messages,
            "tools": tools,
            "stream": True,
            "temperature": 0.7,
            "max_tokens": request.max_tokens or 1000,
        }

        # Apply token manager limits if available
        if token_manager:
            limiter_config = token_manager.create_response_limiter(request.max_tokens)
            response_config.update(limiter_config)

        # Stream response from LLM
        stream = await client.chat_completion(**response_config)

        async for chunk in stream:
            # Handle different chunk types
            if chunk.get("type") == "content":
                # Text content chunk
                chunk_data = {
                    "type": "text",
                    "delta": chunk.get("delta", {}),
                    "finish_reason": chunk.get("finish_reason"),
                }
                yield f"data: {json.dumps(chunk_data)}\n\n"

            elif chunk.get("type") == "tool_calls":
                # Tool call chunk - execute real tools with RAG
                tool_calls = chunk.get("delta", {}).get("tool_calls", [])
                for tool_call in tool_calls:
                    tool_call_data = {
                        "type": "tool_call",
                        "tool_call": {
                            "id": tool_call.get("id"),
                            "type": "function",
                            "function": tool_call.get("function", {}),
                        },
                    }
                    yield f"data: {json.dumps(tool_call_data)}\n\n"

                    # Execute real tool with RAG integration
                    if tool_manager and tool_call.get("function"):
                        try:
                            function_name = tool_call["function"].get("name")
                            function_args = tool_call["function"].get("arguments", "{}")

                            # Execute tool via tool manager (which uses RAG for retrieve_menu)
                            tool_result = await tool_manager.execute_tool(
                                tool_name=function_name, arguments=function_args, tool_call_id=tool_call.get("id")
                            )

                            # Emit real tool result
                            tool_result_data = {
                                "type": "tool_result",
                                "tool_call_id": tool_call.get("id"),
                                "result": tool_result.data
                                if tool_result.success
                                else f"Tool error: {tool_result.error}",
                                "success": tool_result.success,
                                "latency_ms": tool_result.latency_ms,
                            }
                            yield f"data: {json.dumps(tool_result_data)}\n\n"

                        except Exception as e:
                            # Emit error result
                            error_result = {
                                "type": "tool_result",
                                "tool_call_id": tool_call.get("id"),
                                "result": f"Tool execution error: {str(e)}",
                                "success": False,
                                "latency_ms": 0,
                            }
                            yield f"data: {json.dumps(error_result)}\n\n"
                    else:
                        # Fallback mock result
                        mock_result = {
                            "type": "tool_result",
                            "tool_call_id": tool_call.get("id"),
                            "result": f"Tool manager not available for {tool_call.get('function', {}).get('name', 'unknown')}",
                            "success": False,
                        }
                        yield f"data: {json.dumps(mock_result)}\n\n"

            elif chunk.get("type") == "error":
                # Error chunk
                error_data = {
                    "type": "error",
                    "error": chunk.get("error", "Unknown error"),
                }
                yield f"data: {json.dumps(error_data)}\n\n"
                return

        # Final done event
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    except Exception as e:
        # Handle any errors during streaming
        error_data = {"type": "error", "error": str(e)}
        yield f"data: {json.dumps(error_data)}\n\n"


def get_app_state(request: Request):
    """Get FastAPI app state."""
    return request.app.state


@router.post("/completions", response_model=ChatResponse)
async def chat_completions(request: ChatRequest, app_state=Depends(get_app_state)):
    """
    Create chat completion with optional streaming.

    Supports:
    - Tool calling (retrieve_menu, apply_promos, confirm)
    - RAG-enhanced responses
    - Multi-tenant context isolation
    - Conversation memory management
    - Enhanced streaming with buffering
    """

    # Initialize token limit manager
    token_manager = None
    if ENHANCED_STREAMING_AVAILABLE:
        token_manager = TokenLimitManager()

        # Validate input token count
        message_dicts = [{"role": msg.role, "content": msg.content} for msg in request.messages]
        is_valid, token_count = token_manager.validate_input_tokens(message_dicts)

        if not is_valid:
            raise HTTPException(
                status_code=413,
                detail=f"Input too long: {token_count} tokens exceeds {token_manager.max_input_tokens} limit",
            )

        logger.info(f"Input validated: {token_count} tokens")

    # Add conversation memory if available
    enhanced_messages = request.messages
    if ENHANCED_STREAMING_AVAILABLE and request.use_conversation_memory and request.session_id:
        streaming_manager = get_streaming_manager()

        # Get conversation context
        conversation_context = streaming_manager.conversation_memory.get_conversation_context(request.session_id)

        if conversation_context:
            # Add conversation history before current messages
            history_messages = [
                ChatMessage(
                    role=ctx_msg["role"],
                    content=ctx_msg["content"],
                    timestamp=datetime.fromisoformat(ctx_msg["timestamp"]),
                )
                for ctx_msg in conversation_context
            ]

            # Combine with current messages (avoid duplicates)
            all_messages = history_messages + list(request.messages)

            # Apply token limits
            if token_manager:
                truncated_dicts = token_manager.truncate_context(
                    [{"role": msg.role, "content": msg.content} for msg in all_messages]
                )
                enhanced_messages = [ChatMessage(role=msg["role"], content=msg["content"]) for msg in truncated_dicts]
            else:
                enhanced_messages = all_messages

            logger.info(f"Added conversation context: {len(conversation_context)} previous messages")

    # Store user message in conversation memory
    if ENHANCED_STREAMING_AVAILABLE and request.session_id and request.use_conversation_memory:
        streaming_manager = get_streaming_manager()
        for msg in request.messages:
            if msg.role == "user":
                streaming_manager.conversation_memory.add_message(
                    session_id=request.session_id, role=msg.role, content=msg.content
                )

    if request.stream:
        # Use enhanced streaming if available
        if ENHANCED_STREAMING_AVAILABLE:
            return BufferedEventSourceResponse(
                generate_chat_stream(request, enhanced_messages, token_manager, app_state),
                session_id=request.session_id,
            )
        else:
            return StreamingResponse(
                generate_chat_stream(request, enhanced_messages, None, app_state),
                media_type="text/plain",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "Content-Type": "text/event-stream",
                },
            )
    else:
        # Non-streaming response with tool execution
        try:
            # Get LLM client from app state
            client = None
            if hasattr(app_state, "llm_client"):
                client = app_state.llm_client
            elif LLM_CLIENT_AVAILABLE:
                client = get_llm_client()

            if not client:
                raise HTTPException(status_code=503, detail="LLM client not available")

            # Convert messages to LLM format
            llm_messages = [LLMChatMessage(role=msg.role, content=msg.content) for msg in enhanced_messages]

            # Define tools if enabled
            tools = None
            tool_manager = None
            if request.tools_enabled and TOOLS_AVAILABLE:
                try:
                    # Get tool manager from app state
                    if hasattr(app_state, "tool_manager"):
                        tool_manager = app_state.tool_manager
                    else:
                        tool_manager = get_tool_manager(tenant_id=request.tenant_id, user_id=request.user_id)

                    tools = tool_manager.get_openai_functions()
                except Exception as e:
                    print(f"Warning: Failed to load tools for non-streaming: {e}")
                    tools = None

            # Get initial response from LLM
            response = await client.chat_completion(
                messages=llm_messages,
                tools=tools,
                stream=False,
                temperature=0.7,
                max_tokens=request.max_tokens or 1000,
            )

            # Handle tool calls if present
            final_response = response
            if response.tool_calls and tool_manager:
                try:
                    # Execute tool calls
                    tool_results = await tool_manager.execute_tool_calls(response.tool_calls)

                    # Add tool results to conversation and get final response
                    extended_messages = (
                        llm_messages
                        + [LLMChatMessage(role="assistant", content=response.content, tool_calls=response.tool_calls)]
                        + [
                            LLMChatMessage(role="tool", content=tool_result["content"], name=tool_result["name"])
                            for tool_result in tool_results
                        ]
                    )

                    # Get final response after tool execution
                    final_response = await client.chat_completion(
                        messages=extended_messages,
                        stream=False,
                        temperature=0.7,
                        max_tokens=request.max_tokens or 1000,
                    )

                except Exception as e:
                    print(f"Warning: Tool execution failed: {e}")

            return ChatResponse(
                choices=[
                    {
                        "message": {
                            "role": "assistant",
                            "content": final_response.content,
                            "tool_calls": getattr(final_response, "tool_calls", None),
                        },
                        "finish_reason": final_response.finish_reason,
                    }
                ],
                usage=getattr(final_response, "usage", None),
            )

        except Exception as e:
            raise HTTPException(status_code=500, detail=f"LLM error: {str(e)}")


@router.get("/stream")
async def chat_stream_sse(messages: str, tools_enabled: bool = True):
    """
    Server-Sent Events endpoint for chat streaming.
    Alternative to WebSocket for simpler clients.
    """

    try:
        parsed_messages = json.loads(messages)
        request = ChatRequest(
            messages=[ChatMessage(**msg) for msg in parsed_messages],
            stream=True,
            tools_enabled=tools_enabled,
        )

        return EventSourceResponse(generate_chat_stream(request))

    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid messages format")


@router.websocket("/ws/{client_id}")
async def websocket_chat(websocket: WebSocket, client_id: str):
    """
    WebSocket endpoint for real-time chat.
    Supports bidirectional communication and tool calling.
    """

    await manager.connect(websocket, client_id)

    try:
        while True:
            # Receive message from client
            data = await websocket.receive_text()

            try:
                request_data = json.loads(data)
                request = ChatRequest(**request_data)

                # Generate and stream response
                async for chunk in generate_chat_stream(request):
                    # Extract data part from SSE format
                    if chunk.startswith("data: "):
                        message_data = chunk[6:].strip()
                        if message_data:
                            await manager.send_personal_message(message_data, client_id)

            except (json.JSONDecodeError, ValueError) as e:
                error_msg = json.dumps({"type": "error", "message": f"Invalid request: {str(e)}"})
                await manager.send_personal_message(error_msg, client_id)

    except WebSocketDisconnect:
        manager.disconnect(client_id)


@router.get("/tools")
async def list_available_tools():
    """List available tools for LLM function calling."""

    if not TOOLS_AVAILABLE:
        return {"error": "Tools system not available", "tools": []}

    try:
        # Get tool manager
        tool_manager = get_tool_manager()

        # Get tools schema
        schema = tool_manager.get_tools_schema()

        # Format for API response
        tools_list = []
        for tool_name, tool_info in schema["tools"].items():
            if "error" not in tool_info:
                tools_list.append(
                    {
                        "name": tool_info["name"],
                        "description": tool_info["description"],
                        "parameters": tool_info["schema"],
                    }
                )

        return {
            "tools": tools_list,
            "total_count": len(tools_list),
            "openai_functions": tool_manager.get_openai_functions(),
        }

    except Exception as e:
        return {"error": f"Failed to load tools: {str(e)}", "tools": []}


@router.get("/sessions/{session_id}/stats")
async def get_session_stats(session_id: str):
    """Get conversation statistics for a session."""

    if not ENHANCED_STREAMING_AVAILABLE:
        raise HTTPException(status_code=503, detail="Enhanced streaming not available")

    try:
        streaming_manager = get_streaming_manager()
        stats = streaming_manager.conversation_memory.get_session_stats(session_id)

        return {
            "session_id": session_id,
            "stats": stats,
            "timestamp": datetime.now().isoformat(),
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get session stats: {str(e)}")


@router.get("/sessions/{session_id}/context")
async def get_session_context(session_id: str, max_tokens: Optional[int] = None):
    """Get conversation context for a session."""

    if not ENHANCED_STREAMING_AVAILABLE:
        raise HTTPException(status_code=503, detail="Enhanced streaming not available")

    try:
        streaming_manager = get_streaming_manager()
        context = streaming_manager.conversation_memory.get_conversation_context(session_id, max_tokens)

        return {
            "session_id": session_id,
            "context": context,
            "message_count": len(context),
            "total_tokens": sum(msg.get("token_count", 0) for msg in context),
            "timestamp": datetime.now().isoformat(),
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get session context: {str(e)}")
