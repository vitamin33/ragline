# Agent B Unit Tests

Unit tests for Reliability & Events layer components.

## Scope  
- Celery worker configuration and tasks
- Outbox pattern implementation
- Redis streams producer/consumer
- Event schema validation
- Retry logic and error handling

## Structure
- `test_worker_*.py` - Celery worker tests
- `test_outbox_*.py` - Outbox pattern tests
- `test_streams_*.py` - Redis streams tests
- `test_events_*.py` - Event schema tests
- `test_notifications_*.py` - SSE/WebSocket tests

## Running
```bash
pytest tests/unit/agent_b -m agent_b
```