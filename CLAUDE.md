# RAGline - Multi-Agent Development Guide

## Critical Rules

1. **NEVER add co-author tags to commits**
2. **Stay within ownership boundaries**
3. **Commit format**: `feat(scope): description`

## Agent Ownership

- **Agent A (feat/core-api)**: services/api/, packages/db/, packages/security/, packages/cache/, contracts/openapi.yaml
- **Agent B (feat/reliability)**: services/worker/, packages/orchestrator/, contracts/events/order_v1.json
- **Agent C (feat/llm)**: services/llm/, packages/rag/, contracts/events/chat_tool_v1.json

## Daily Workflow

```bash
# Morning sync (use the script!)
./scripts/merge_workflow.sh sync

# Track progress
./scripts/track_progress.sh complete [A|B|C] "task"

# Commit (NO CO-AUTHORS!)
git add . && git commit -m "feat(scope): description"

# Push changes
git push origin feat/[branch-name]

# Evening merge (if ready)
./scripts/merge_workflow.sh merge [a|b|c]
Quick References

Architecture: See docs/ARCHITECTURE.md for full system design
Daily Tasks: See docs/DAILY_STATUS.md for current sprint
API Ports: API=8000, LLM=8001, Prometheus=9090, Grafana=3000
Metrics Prefix: All metrics use ragline_ prefix
Redis Keys: Format ragline:{tenant_id}:{type}:{id}

Integration Points

Agent A → B: Outbox table for event sourcing
Agent B → All: Event streaming via Redis
Agent C → A: API calls for tool execution

Commands
bashjust up      # Start infrastructure
just dev     # Run all services
just test    # Run tests
./scripts/daily_workflow.sh morning   # Morning checks
./scripts/track_progress.sh show      # Check progress
./scripts/merge_workflow.sh sync      # Sync all agents with main
```
