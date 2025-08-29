"""
Enhanced Streaming Module for RAGline LLM Service

Provides optimized SSE streaming with buffering, connection management,
and conversation memory for improved performance and user experience.
"""

import json
import logging
import time
import uuid
from collections import deque
from datetime import datetime, timedelta
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class StreamBuffer:
    """Buffer for managing streaming data with automatic flushing."""

    def __init__(
        self,
        buffer_size: int = 8192,
        flush_interval: float = 0.1,
        max_hold_time: float = 1.0,
    ):
        self.buffer_size = buffer_size
        self.flush_interval = flush_interval
        self.max_hold_time = max_hold_time

        self._buffer = []
        self._buffer_bytes = 0
        self._last_flush = time.time()
        self._first_item_time = None

    def add_item(self, data: str) -> bool:
        """
        Add data to buffer. Returns True if should flush immediately.

        Args:
            data: SSE formatted data string

        Returns:
            bool: True if buffer should be flushed
        """
        if not self._first_item_time:
            self._first_item_time = time.time()

        self._buffer.append(data)
        self._buffer_bytes += len(data.encode("utf-8"))

        # Check if should flush
        current_time = time.time()

        # Flush conditions
        buffer_full = self._buffer_bytes >= self.buffer_size
        interval_elapsed = (current_time - self._last_flush) >= self.flush_interval
        max_time_exceeded = (
            self._first_item_time
            and (current_time - self._first_item_time) >= self.max_hold_time
        )

        return buffer_full or interval_elapsed or max_time_exceeded

    def flush(self) -> str:
        """Flush buffer and return concatenated data."""
        if not self._buffer:
            return ""

        flushed_data = "".join(self._buffer)
        self._buffer.clear()
        self._buffer_bytes = 0
        self._last_flush = time.time()
        self._first_item_time = None

        return flushed_data

    def has_data(self) -> bool:
        """Check if buffer has data."""
        return len(self._buffer) > 0


class ConversationMessage(BaseModel):
    """Enhanced message model with metadata."""

    role: str
    content: str
    timestamp: datetime = Field(default_factory=datetime.now)
    token_count: Optional[int] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ConversationMemory:
    """Manages conversation history and context windows."""

    def __init__(
        self,
        max_messages: int = 50,
        max_tokens: int = 4000,
        context_window: int = 3000,
        cleanup_interval: int = 300,  # 5 minutes
    ):
        self.max_messages = max_messages
        self.max_tokens = max_tokens
        self.context_window = context_window
        self.cleanup_interval = cleanup_interval

        # Session storage
        self._conversations: Dict[str, deque] = {}
        self._last_cleanup = time.time()

        # Token counting
        try:
            import tiktoken

            self.tokenizer = tiktoken.get_encoding("cl100k_base")
        except ImportError:
            logger.warning("tiktoken not available, using word-based estimation")
            self.tokenizer = None

    def count_tokens(self, text: str) -> int:
        """Count tokens in text."""
        if self.tokenizer:
            try:
                return len(self.tokenizer.encode(text))
            except Exception:
                pass

        # Fallback to word-based estimation
        return int(len(text.split()) * 1.3)

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """Add message to conversation history."""

        if session_id not in self._conversations:
            self._conversations[session_id] = deque(maxlen=self.max_messages)

        token_count = self.count_tokens(content)

        message = ConversationMessage(
            role=role, content=content, token_count=token_count, metadata=metadata or {}
        )

        self._conversations[session_id].append(message)

        # Cleanup old conversations periodically
        current_time = time.time()
        if current_time - self._last_cleanup > self.cleanup_interval:
            self._cleanup_old_conversations()
            self._last_cleanup = current_time

    def get_conversation_context(
        self, session_id: str, max_context_tokens: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Get conversation context within token limits.

        Args:
            session_id: Session identifier
            max_context_tokens: Override default context window

        Returns:
            List of messages within token limit
        """

        if session_id not in self._conversations:
            return []

        messages = list(self._conversations[session_id])
        context_limit = max_context_tokens or self.context_window

        # Build context from most recent messages
        context_messages = []
        total_tokens = 0

        for message in reversed(messages):
            message_tokens = message.token_count or self.count_tokens(message.content)

            if total_tokens + message_tokens > context_limit:
                break

            context_messages.append(
                {
                    "role": message.role,
                    "content": message.content,
                    "timestamp": message.timestamp.isoformat(),
                    "token_count": message_tokens,
                }
            )

            total_tokens += message_tokens

        # Reverse to get chronological order
        context_messages.reverse()

        logger.info(
            f"Retrieved {len(context_messages)} messages "
            f"({total_tokens} tokens) for session {session_id}"
        )

        return context_messages

    def get_session_stats(self, session_id: str) -> Dict[str, Any]:
        """Get statistics for a conversation session."""

        if session_id not in self._conversations:
            return {"exists": False}

        messages = list(self._conversations[session_id])

        total_tokens = sum(
            msg.token_count or self.count_tokens(msg.content) for msg in messages
        )

        user_messages = [msg for msg in messages if msg.role == "user"]
        assistant_messages = [msg for msg in messages if msg.role == "assistant"]

        return {
            "exists": True,
            "total_messages": len(messages),
            "user_messages": len(user_messages),
            "assistant_messages": len(assistant_messages),
            "total_tokens": total_tokens,
            "session_start": messages[0].timestamp.isoformat() if messages else None,
            "last_activity": messages[-1].timestamp.isoformat() if messages else None,
        }

    def _cleanup_old_conversations(self):
        """Remove conversations older than 1 hour."""

        cutoff_time = datetime.now() - timedelta(hours=1)
        sessions_to_remove = []

        for session_id, messages in self._conversations.items():
            if messages and messages[-1].timestamp < cutoff_time:
                sessions_to_remove.append(session_id)

        for session_id in sessions_to_remove:
            del self._conversations[session_id]

        if sessions_to_remove:
            logger.info(
                f"Cleaned up {len(sessions_to_remove)} old conversation sessions"
            )


class StreamingManager:
    """Manages multiple streaming connections with optimized delivery."""

    def __init__(self):
        self.active_streams: Dict[str, Dict[str, Any]] = {}
        self.conversation_memory = ConversationMemory()

    def register_stream(
        self,
        stream_id: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ):
        """Register a new streaming connection."""

        self.active_streams[stream_id] = {
            "session_id": session_id or str(uuid.uuid4()),
            "user_id": user_id,
            "tenant_id": tenant_id,
            "created_at": datetime.now(),
            "buffer": StreamBuffer(),
            "message_count": 0,
            "bytes_sent": 0,
        }

        logger.info(f"Registered stream {stream_id} for session {session_id}")

    def unregister_stream(self, stream_id: str):
        """Unregister streaming connection."""

        if stream_id in self.active_streams:
            stream_info = self.active_streams[stream_id]
            session_id = stream_info["session_id"]

            logger.info(
                f"Unregistered stream {stream_id} "
                f"(session: {session_id}, messages: {stream_info['message_count']})"
            )

            del self.active_streams[stream_id]

    def get_stream_info(self, stream_id: str) -> Optional[Dict[str, Any]]:
        """Get information about a streaming connection."""
        return self.active_streams.get(stream_id)

    async def stream_with_buffering(
        self,
        stream_id: str,
        data_generator: AsyncGenerator[str, None],
        session_id: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """
        Stream data with intelligent buffering and conversation memory.

        Args:
            stream_id: Unique stream identifier
            data_generator: Source of SSE data
            session_id: Optional session ID for conversation tracking

        Yields:
            Buffered SSE data
        """

        # Register stream if not already registered
        if stream_id not in self.active_streams:
            self.register_stream(stream_id, session_id)

        stream_info = self.active_streams[stream_id]
        buffer = stream_info["buffer"]

        try:
            # Track conversation context
            current_response = ""

            async for data_chunk in data_generator:
                # Track response content for conversation memory
                if '"type": "text"' in data_chunk and '"content"' in data_chunk:
                    try:
                        # Extract content for conversation tracking
                        import re

                        content_match = re.search(r'"content":\s*"([^"]*)"', data_chunk)
                        if content_match:
                            current_response += content_match.group(1)
                    except Exception:
                        pass  # Continue streaming even if tracking fails

                # Add to buffer
                should_flush = buffer.add_item(data_chunk)
                stream_info["message_count"] += 1

                if should_flush:
                    # Flush buffer
                    buffered_data = buffer.flush()
                    if buffered_data:
                        stream_info["bytes_sent"] += len(buffered_data.encode("utf-8"))
                        yield buffered_data

                # Yield immediately for certain event types (errors, completion)
                if any(
                    event_type in data_chunk
                    for event_type in ['"type": "error"', '"type": "done"']
                ):
                    # Flush remaining buffer
                    remaining_data = buffer.flush()
                    if remaining_data:
                        yield remaining_data
                    break

            # Final flush
            remaining_data = buffer.flush()
            if remaining_data:
                yield remaining_data

            # Store conversation in memory
            if current_response and session_id:
                self.conversation_memory.add_message(
                    session_id=session_id,
                    role="assistant",
                    content=current_response,
                    metadata={
                        "stream_id": stream_id,
                        "message_count": stream_info["message_count"],
                        "bytes_sent": stream_info["bytes_sent"],
                    },
                )

        except Exception as e:
            logger.error(f"Streaming error for {stream_id}: {e}")

            # Send error event
            error_data = f'data: {json.dumps({"type": "error", "error": str(e)})}\n\n'
            yield error_data

        finally:
            # Unregister stream
            self.unregister_stream(stream_id)


# Global streaming manager instance
_streaming_manager: Optional[StreamingManager] = None


def get_streaming_manager() -> StreamingManager:
    """Get or create global streaming manager."""
    global _streaming_manager

    if _streaming_manager is None:
        _streaming_manager = StreamingManager()

    return _streaming_manager


# Enhanced SSE response with buffering
class BufferedEventSourceResponse:
    """Enhanced EventSource response with intelligent buffering."""

    def __init__(
        self,
        data_generator: AsyncGenerator[str, None],
        session_id: Optional[str] = None,
        media_type: str = "text/plain",
        headers: Optional[Dict[str, str]] = None,
    ):
        self.data_generator = data_generator
        self.session_id = session_id
        self.media_type = media_type
        self.headers = headers or {}

        # Add SSE headers
        self.headers.update(
            {
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Content-Type": "text/event-stream",
                "X-Accel-Buffering": "no",  # Disable nginx buffering
            }
        )

    async def __call__(self, scope, receive, send):
        """ASGI callable for streaming response."""

        # Send response start
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (key.encode(), value.encode())
                    for key, value in self.headers.items()
                ],
            }
        )

        # Generate stream ID and use buffered streaming
        stream_id = str(uuid.uuid4())
        streaming_manager = get_streaming_manager()

        try:
            buffered_generator = streaming_manager.stream_with_buffering(
                stream_id=stream_id,
                data_generator=self.data_generator,
                session_id=self.session_id,
            )

            async for chunk in buffered_generator:
                if chunk:
                    await send(
                        {"type": "http.response.body", "body": chunk.encode("utf-8")}
                    )

        except Exception as e:
            logger.error(f"Streaming response error: {e}")

            # Send error and close
            error_chunk = f'data: {json.dumps({"type": "error", "error": str(e)})}\n\n'
            await send(
                {"type": "http.response.body", "body": error_chunk.encode("utf-8")}
            )

        finally:
            # End response
            await send({"type": "http.response.body", "body": b""})


class TokenLimitManager:
    """Manages token counting and limits for requests and responses."""

    def __init__(
        self,
        max_input_tokens: int = 8000,
        max_output_tokens: int = 2000,
        context_window: int = 4000,
    ):
        self.max_input_tokens = max_input_tokens
        self.max_output_tokens = max_output_tokens
        self.context_window = context_window

        # Initialize tokenizer
        try:
            import tiktoken

            self.tokenizer = tiktoken.get_encoding("cl100k_base")
        except ImportError:
            logger.warning("tiktoken not available, using estimation")
            self.tokenizer = None

    def count_tokens(self, text: str) -> int:
        """Count tokens in text."""
        if self.tokenizer:
            try:
                return len(self.tokenizer.encode(text))
            except Exception:
                pass

        # Fallback estimation
        return int(len(text.split()) * 1.3)

    def validate_input_tokens(self, messages: List[Dict[str, str]]) -> Tuple[bool, int]:
        """
        Validate input doesn't exceed token limits.

        Returns:
            (is_valid, total_tokens)
        """

        total_tokens = 0
        for message in messages:
            content = message.get("content", "")
            total_tokens += self.count_tokens(content)

        is_valid = total_tokens <= self.max_input_tokens
        return is_valid, total_tokens

    def truncate_context(
        self, messages: List[Dict[str, str]], target_tokens: Optional[int] = None
    ) -> List[Dict[str, str]]:
        """Truncate conversation context to fit within limits."""

        target = target_tokens or self.context_window

        # Keep system message if present
        system_msgs = [msg for msg in messages if msg.get("role") == "system"]
        other_msgs = [msg for msg in messages if msg.get("role") != "system"]

        # Calculate system message tokens
        system_tokens = sum(
            self.count_tokens(msg.get("content", "")) for msg in system_msgs
        )

        # Remaining tokens for conversation
        available_tokens = target - system_tokens

        # Build context from most recent messages
        context_messages = []
        current_tokens = 0

        for message in reversed(other_msgs):
            content = message.get("content", "")
            msg_tokens = self.count_tokens(content)

            if current_tokens + msg_tokens > available_tokens:
                break

            context_messages.append(message)
            current_tokens += msg_tokens

        # Combine system + truncated conversation (reverse to get chronological order)
        final_messages = system_msgs + list(reversed(context_messages))

        logger.info(
            f"Context truncated: {len(messages)} -> {len(final_messages)} messages "
            f"({current_tokens + system_tokens} tokens)"
        )

        return final_messages

    def create_response_limiter(
        self, max_tokens: Optional[int] = None
    ) -> Dict[str, Any]:
        """Create configuration for limiting response tokens."""

        limit = max_tokens or self.max_output_tokens

        return {
            "max_tokens": limit,
            "stream": True,  # Enable streaming for better UX with limits
            "stop": None,  # Let model finish naturally within limit
        }
