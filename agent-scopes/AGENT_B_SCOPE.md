# Agent B: Reliability & Events

## Ownership

- **Exclusive**: services/worker/, packages/orchestrator/, contracts/events/order_v1.json
- **Read-only**: packages/db/, services/api/

## Deliverables

1. Celery workers with IO pool and ProcessPool
2. Outbox pattern: writer post-commit, consumer to Redis Streams
3. Redis Streams producer/consumer for "orders" topic
4. Notifier fan-out to SSE and WS with backpressure handling
5. Retry mechanism with jitter, circuit breaker for external adapter
6. Dead Letter Queue implementation with requeue capability
7. Prometheus metrics: stream lag, consumer lag, retries, DLQ size

## Restrictions

- MUST NOT modify: contracts/openapi.yaml, packages/db/migrations/, services/llm/
- MUST NOT add co-author to commits
- Must coordinate with Agent A for DB read operations
- Must use existing outbox table structure

## Success Metrics

- Stream lag < 100ms p95
- DLQ recovery rate > 99%
- 5k concurrent SSE connections stable
- Circuit breaker tested with failure scenarios
