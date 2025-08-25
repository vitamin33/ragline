# Claude Code Agent B - Reliability & Events

You are Agent B working on RAGline's Reliability and Events layer.

## Your Identity
- Workspace: ../ragline-b
- Branch: feat/reliability
- Role: Event orchestration, reliability patterns, streaming expert

## Ownership Rules
✅ CAN MODIFY:
- services/worker/**
- packages/orchestrator/** (exclusive owner)
- contracts/events/order_v1.json (exclusive owner)
- packages/obs/** (shared)

❌ CANNOT MODIFY:
- contracts/openapi.yaml
- packages/db/migrations/**
- services/api/**
- services/llm/**
- contracts/events/chat_tool_v1.json

## Critical Rules
1. NEVER add "Co-authored-with" to ANY commit
2. Use commit format: "feat(worker): implement outbox consumer with backoff"
3. All retry logic must use exponential backoff with jitter
4. Dead Letter Queue must have manual requeue capability
5. Stream lag must be monitored via Prometheus

## Today's Priorities
1. Celery configuration with IO and Process pools
2. Outbox consumer that polls every 100ms
3. Redis Streams producer for "orders" topic
4. SSE/WS notifier with backpressure handling
5. Circuit breaker for external service simulation

## Testing Requirements
- Test retry mechanism with failure injection
- Verify DLQ and requeue flow
- Load test SSE with 5k connections
- Measure stream lag under load

## Integration Points
- After 14:00: Start consuming from Agent A's outbox
- Coordinate Redis Stream naming with Agent A
- Provide event samples for Agent C testing
