"""
Chat endpoint with streaming support via SSE and WebSocket.
Supports tool calling and RAG-enhanced responses.
"""

import asyncio
import json
import sys
import uuid
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, List, Optional
from dotenv import load_dotenv

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

# Load environment variables
load_dotenv()

# Add packages to path for LLM client
sys.path.insert(0, '../../packages')

try:
    from rag.llm_client import get_llm_client, ChatMessage as LLMChatMessage
    LLM_CLIENT_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Could not import LLM client: {e}")
    LLM_CLIENT_AVAILABLE = False

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


async def generate_chat_stream(request: ChatRequest) -> AsyncGenerator[str, None]:
    """Generate streaming chat response with tool calling support."""
    
    if not LLM_CLIENT_AVAILABLE:
        # Fallback to mock response if LLM client not available
        yield f"data: {json.dumps({'type': 'error', 'message': 'LLM client not available'})}\n\n"
        return
    
    try:
        # Get LLM client
        client = get_llm_client()
        
        # Convert messages to LLM format
        llm_messages = [
            LLMChatMessage(
                role=msg.role,
                content=msg.content
            )
            for msg in request.messages
        ]
        
        # Define tools if enabled
        tools = None
        if request.tools_enabled:
            tools = [
                {
                    "type": "function",
                    "function": {
                        "name": "retrieve_menu",
                        "description": "Retrieve menu items based on query or filters",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "query": {"type": "string", "description": "Search query"},
                                "category": {"type": "string", "description": "Menu category filter"}
                            }
                        }
                    }
                },
                {
                    "type": "function",
                    "function": {
                        "name": "apply_promos",
                        "description": "Apply promotional codes or discounts",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "promo_code": {"type": "string", "description": "Promotional code"},
                                "order_id": {"type": "string", "description": "Order ID to apply promo to"}
                            }
                        }
                    }
                },
                {
                    "type": "function",
                    "function": {
                        "name": "confirm",
                        "description": "Confirm order or action with user",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "action": {"type": "string", "description": "Action to confirm"},
                                "details": {"type": "object", "description": "Action details"}
                            }
                        }
                    }
                }
            ]
        
        # Stream response from LLM
        stream = await client.chat_completion(
            messages=llm_messages,
            tools=tools,
            stream=True,
            temperature=0.7,
            max_tokens=1000
        )
        
        async for chunk in stream:
            # Handle different chunk types
            if chunk.get("type") == "content":
                # Text content chunk
                chunk_data = {
                    "type": "text",
                    "delta": chunk.get("delta", {}),
                    "finish_reason": chunk.get("finish_reason")
                }
                yield f"data: {json.dumps(chunk_data)}\n\n"
                
            elif chunk.get("type") == "tool_calls":
                # Tool call chunk
                tool_calls = chunk.get("delta", {}).get("tool_calls", [])
                for tool_call in tool_calls:
                    tool_call_data = {
                        "type": "tool_call",
                        "tool_call": {
                            "id": tool_call.get("id"),
                            "type": "function",
                            "function": tool_call.get("function", {})
                        }
                    }
                    yield f"data: {json.dumps(tool_call_data)}\n\n"
                    
                    # Simulate tool execution (mock for now)
                    await asyncio.sleep(0.1)
                    
                    # Emit mock tool result
                    tool_result = {
                        "type": "tool_result",
                        "tool_call_id": tool_call.get("id"),
                        "result": f"Mock result for {tool_call.get('function', {}).get('name', 'unknown')}"
                    }
                    yield f"data: {json.dumps(tool_result)}\n\n"
                    
            elif chunk.get("type") == "error":
                # Error chunk
                error_data = {
                    "type": "error",
                    "error": chunk.get("error", "Unknown error")
                }
                yield f"data: {json.dumps(error_data)}\n\n"
                return
        
        # Final done event
        yield f"data: {json.dumps({'type': 'done'})}\n\n"
        
    except Exception as e:
        # Handle any errors during streaming
        error_data = {
            "type": "error",
            "error": str(e)
        }
        yield f"data: {json.dumps(error_data)}\n\n"


@router.post("/completions", response_model=ChatResponse)
async def chat_completions(request: ChatRequest):
    """
    Create chat completion with optional streaming.
    
    Supports:
    - Tool calling (retrieve_menu, apply_promos, confirm)
    - RAG-enhanced responses
    - Multi-tenant context isolation
    """
    
    if request.stream:
        return StreamingResponse(
            generate_chat_stream(request),
            media_type="text/plain",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Content-Type": "text/event-stream"
            }
        )
    else:
        # Non-streaming response
        if not LLM_CLIENT_AVAILABLE:
            raise HTTPException(status_code=503, detail="LLM client not available")
        
        try:
            client = get_llm_client()
            
            # Convert messages to LLM format
            llm_messages = [
                LLMChatMessage(role=msg.role, content=msg.content)
                for msg in request.messages
            ]
            
            # Define tools if enabled
            tools = None
            if request.tools_enabled:
                tools = [
                    {
                        "type": "function",
                        "function": {
                            "name": "retrieve_menu",
                            "description": "Retrieve menu items based on query or filters",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "query": {"type": "string", "description": "Search query"},
                                    "category": {"type": "string", "description": "Menu category filter"}
                                }
                            }
                        }
                    }
                ]
            
            # Get response from LLM
            response = await client.chat_completion(
                messages=llm_messages,
                tools=tools,
                stream=False,
                temperature=0.7,
                max_tokens=1000
            )
            
            return ChatResponse(
                choices=[{
                    "message": {
                        "role": "assistant",
                        "content": response.content,
                        "tool_calls": response.tool_calls
                    },
                    "finish_reason": response.finish_reason
                }],
                usage=response.usage
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
            tools_enabled=tools_enabled
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
    
    return {
        "tools": [
            {
                "name": "retrieve_menu",
                "description": "Retrieve menu items based on query or filters",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                        "category": {"type": "string", "description": "Menu category filter"}
                    }
                }
            },
            {
                "name": "apply_promos", 
                "description": "Apply promotional codes or discounts",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "promo_code": {"type": "string", "description": "Promotional code"},
                        "order_id": {"type": "string", "description": "Order ID to apply promo to"}
                    }
                }
            },
            {
                "name": "confirm",
                "description": "Confirm order or action with user",
                "parameters": {
                    "type": "object", 
                    "properties": {
                        "action": {"type": "string", "description": "Action to confirm"},
                        "details": {"type": "object", "description": "Action details"}
                    }
                }
            }
        ]
    }