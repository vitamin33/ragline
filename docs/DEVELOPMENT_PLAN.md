# RAGline Development Plan

## Daily Sync Points
- 09:00: Contract review (any changes need approval from all agents)
- 14:00: Integration test sync
- 18:00: Merge coordination

## Merge Strategy
1. Contract changes merge FIRST (blocking for all agents)
2. Package changes merge SECOND (coordinate between affected agents)
3. Service changes merge LAST (independent per agent)

## Communication Protocol
- Use PR comments for cross-agent dependencies
- Tag issues with agent labels: agent-a, agent-b, agent-c
- Daily status updates in docs/DAILY_STATUS.md
- Block work with #BLOCKED tag when waiting for another agent

## Critical Integration Points
- Day 3: API ↔ Worker handoff via outbox table
- Day 4: Worker → Notifier → SSE/WS pipeline
- Day 5: LLM service contract finalization
- Day 6: Full stack integration test with RAG
- Day 7: Load testing with all components

## Naming Conventions
- Prometheus metrics prefix: ragline_
- Redis keys: ragline:{tenant_id}:{resource}:{id}
- Event topics: orders, chat_tools
- Trace spans: ragline.{service}.{operation}
