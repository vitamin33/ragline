# LLM Service Examples

These scripts demonstrate how to use the RAGline LLM service components.

## Examples

### `llm_client_example.py`
Shows how to:
- Configure OpenAI API integration
- Set up local model support (Ollama, LM Studio)
- Test streaming and non-streaming chat
- Handle tool calling with OpenAI functions

### `rag_system_demo.py`
Demonstrates:
- Complete RAG workflow from documents to context
- Vector embedding generation and similarity search
- Business rule re-ranking with user preferences
- Performance metrics and benchmarking
- LLM context generation

## Usage

These are standalone examples that can be run independently to understand how each component works.

```bash
# Activate environment
source .venv/bin/activate

# Run examples
python tests/examples/llm_client_example.py
python tests/examples/rag_system_demo.py
```
