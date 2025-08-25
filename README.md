# RAGline

> Streaming-first, multi-tenant Python backend with idempotency, outbox + Redis Streams, Prometheus/Grafana, OpenTelemetry, and toggleable LLM/RAG module (local-model ready)

## 🚀 Quick Start

```bash
# Clone with worktrees
git clone https://github.com/vitamin33/ragline.git
cd ragline
git worktree add ../ragline-a feat/core-api
git worktree add ../ragline-b feat/reliability
git worktree add ../ragline-c feat/llm

# Start infrastructure
just up

# Run development servers
just dev

# Run demo
just demo-order  # Test idempotency
just demo-chat   # Test LLM with RAG
```
