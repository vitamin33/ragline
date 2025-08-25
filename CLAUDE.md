# RAGline - Multi-Agent Development Guide

## Critical Rules

1. **NEVER add co-author tags to commits**
2. **Stay within ownership boundaries**
3. **Commit format**: `feat(scope): description`

## Agent Ownership

- **Agent A (feat/core-api)**: services/api/, packages/db/, contracts/openapi.yaml
- **Agent B (feat/reliability)**: services/worker/, packages/orchestrator/, contracts/events/order_v1.json
- **Agent C (feat/llm)**: services/llm/, packages/rag/, contracts/events/chat_tool_v1.json

## Daily Workflow

```bash
# Morning sync
git fetch origin && git rebase origin/main

# Track progress
./scripts/track_progress.sh complete [A|B|C] "task"

# Commit (NO CO-AUTHORS!)
git add . && git commit -m "feat(scope): description"

Project Structure

FastAPI for APIs (port 8000 for API, 8001 for LLM)
Celery for workers
Redis for caching/streams
PostgreSQL with pgvector
Prometheus metrics (prefix: ragline_)

Today's Critical Path

Agent A: SQLAlchemy models (BLOCKS Agent B at 14:00)
Agent B: Waiting for Outbox table schema
Agent C: Independent LLM service setup

See docs/DAILY_STATUS.md for detailed tasks.
```
