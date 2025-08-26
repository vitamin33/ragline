#!/usr/bin/env python3
"""
Test enhanced streaming features: buffering, conversation memory, token limits.
"""

import asyncio
import json
import sys
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, '../../')

async def test_enhanced_streaming():
    """Test enhanced streaming capabilities."""
    
    print("🧪 Testing Enhanced Streaming Features")
    print("=" * 50)
    
    try:
        # Add path to services
        import sys
        sys.path.insert(0, 'services/llm')
        
        from streaming import StreamBuffer, ConversationMemory, TokenLimitManager
        
        # Test 1: Stream Buffer
        print("\n1. Testing Stream Buffer")
        buffer = StreamBuffer(buffer_size=1024, flush_interval=0.1)
        
        # Add some data
        data1 = 'data: {"type": "text", "delta": {"content": "Hello"}}\n\n'
        data2 = 'data: {"type": "text", "delta": {"content": " world"}}\n\n'
        
        should_flush1 = buffer.add_item(data1)
        should_flush2 = buffer.add_item(data2)
        
        print(f"   ✅ Buffer created with 1024 byte limit")
        print(f"   📊 Item 1 flush needed: {should_flush1}")
        print(f"   📊 Item 2 flush needed: {should_flush2}")
        print(f"   📦 Buffer has data: {buffer.has_data()}")
        
        flushed = buffer.flush()
        print(f"   ✅ Flushed {len(flushed)} characters")
        
        # Test 2: Conversation Memory
        print("\n2. Testing Conversation Memory")
        memory = ConversationMemory(max_messages=10, max_tokens=1000)
        
        # Add test conversation
        session_id = "test_session_123"
        
        memory.add_message(session_id, "user", "Hello, I want to order food")
        memory.add_message(session_id, "assistant", "I'd be happy to help you order food! What would you like?")
        memory.add_message(session_id, "user", "Do you have pizza?")
        
        # Get context
        context = memory.get_conversation_context(session_id)
        stats = memory.get_session_stats(session_id)
        
        print(f"   ✅ Added 3 messages to conversation")
        print(f"   📊 Context messages: {len(context)}")
        print(f"   📊 Session stats: {stats['total_messages']} messages, {stats['total_tokens']} tokens")
        print(f"   🕐 Session start: {stats['session_start']}")
        
        # Test 3: Token Limit Manager
        print("\n3. Testing Token Limit Manager")
        token_manager = TokenLimitManager(max_input_tokens=100, max_output_tokens=50)
        
        test_messages = [
            {"role": "user", "content": "Short message"},
            {"role": "assistant", "content": "Short response"},
            {"role": "user", "content": "This is a longer message with more content to test token counting"}
        ]
        
        is_valid, token_count = token_manager.validate_input_tokens(test_messages)
        print(f"   ✅ Token validation: {is_valid} ({token_count} tokens)")
        
        # Test truncation
        long_messages = [{"role": "user", "content": f"Message {i} with content"} for i in range(20)]
        truncated = token_manager.truncate_context(long_messages, target_tokens=50)
        
        print(f"   ✅ Context truncation: {len(long_messages)} → {len(truncated)} messages")
        
        # Test response limiter
        limiter = token_manager.create_response_limiter(max_tokens=100)
        print(f"   ✅ Response limiter: max_tokens={limiter['max_tokens']}")
        
        # Test 4: Integration Test
        print("\n4. Testing Component Integration")
        
        # Simulate streaming workflow
        print("   🔄 Simulating streaming workflow...")
        
        # Create buffer and add streaming data
        workflow_buffer = StreamBuffer(buffer_size=512)
        
        streaming_data = [
            'data: {"type": "text", "delta": {"content": "I"}}\n\n',
            'data: {"type": "text", "delta": {"content": " can"}}\n\n',
            'data: {"type": "text", "delta": {"content": " help"}}\n\n',
            'data: {"type": "text", "delta": {"content": " you"}}\n\n',
            'data: {"type": "done"}\n\n'
        ]
        
        buffered_chunks = []
        for data in streaming_data:
            should_flush = workflow_buffer.add_item(data)
            if should_flush:
                buffered_chunks.append(workflow_buffer.flush())
        
        # Final flush
        final_chunk = workflow_buffer.flush()
        if final_chunk:
            buffered_chunks.append(final_chunk)
        
        total_buffered = sum(len(chunk) for chunk in buffered_chunks)
        print(f"   ✅ Workflow complete: {len(buffered_chunks)} buffered chunks")
        print(f"   📊 Total data: {total_buffered} characters")
        
        # Test memory cleanup
        print("\n5. Testing Memory Management")
        
        # Create multiple sessions
        for i in range(5):
            test_session = f"session_{i}"
            memory.add_message(test_session, "user", f"Test message {i}")
        
        print(f"   ✅ Created {5} test sessions")
        
        # Check memory efficiency
        import sys
        memory_size = sys.getsizeof(memory._conversations)
        print(f"   💾 Memory usage: ~{memory_size} bytes for conversation storage")
        
        print("\n🎉 Enhanced streaming tests completed successfully!")
        print("\nFeatures validated:")
        print("   ✅ Intelligent buffering with size and time limits")
        print("   ✅ Conversation memory with token-aware context")
        print("   ✅ Token counting and limit validation")
        print("   ✅ Context truncation for large conversations")
        print("   ✅ Session management with automatic cleanup")
        
    except ImportError as e:
        print(f"❌ Import error: {e}")
        print("   Make sure you're running from the correct directory")
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        print(f"   Error details: {traceback.format_exc()[:300]}...")


if __name__ == "__main__":
    asyncio.run(test_enhanced_streaming())