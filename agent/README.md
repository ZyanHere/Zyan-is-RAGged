# Agent

The AI service for myRAG. Everything LLM-related lives here — model keys,
prompts, and (later) the RAG engine. The backend never calls a model directly;
it calls this service over HTTP.

Runs on **port 8001**.

```text
frontend :3000  →  backend :8000  →  agent :8001  →  OpenRouter
```

## Current state — M0

A stateless single-turn chat service. **No RAG yet**: no ingestion, no
retrieval, no embeddings, no vector store. It takes a conversation and returns
the model's reply.

```text
app/
├── main.py              FastAPI app
├── core/config.py       settings (model, key, prompt, generation params)
├── api/routes/
│   ├── generate.py      POST /generate  — the only real endpoint
│   └── health.py        GET  /health
├── schemas/generate.py  request/response models
├── providers/           ← the model seam
│   ├── base.py          ChatModel protocol + get_chat_model() factory
│   └── openrouter.py    the only file that imports a vendor SDK
└── services/llm.py      applies generation settings, delegates to the provider
```

### The provider seam

`providers/base.py` defines what a chat model must be able to do;
`providers/openrouter.py` is the one implementation. Nothing else in the
codebase imports `openai` — so moving from OpenRouter's free tier to a paid
provider is a new module here plus a config change, and no caller is touched.

Vendor exceptions are translated to `ProviderError` inside `openrouter.py`, so
callers never import an SDK's error classes.

## Setup

From `agent/`:

```bash
python -m pip install -r requirements.txt
```

Create the environment file and add your key from
[openrouter.ai/keys](https://openrouter.ai/keys):

```bash
copy .env.example .env
```

Free model ids rotate — verify `OPENROUTER_MODEL` is still listed at
[openrouter.ai/models](https://openrouter.ai/models) (filter to free). A dead id
fails at request time, not at startup.

`.env` is gitignored. Commit `.env.example`, never `.env`.

## Run

```bash
uvicorn app.main:app --reload --port 8001
```

Swagger: `http://localhost:8001/docs` · Health: `GET http://localhost:8001/health`

To test the agent alone, without the backend or frontend, POST to `/generate`:

```json
{ "messages": [{ "role": "user", "content": "hello" }] }
```

If that returns text, the agent is working and any remaining problem is
upstream.

## What comes next

Per `docs/architecture/system-design.md`, this service grows into two
subsystems with a hard boundary between them:

- **`rag_engine/`** — stateless and conversation-blind. Documents in, grounded
  answers out. Exposes exactly `retrieve()` and `answer()`.
- **`chat_orchestrator/`** — owns the conversation: memory, routing,
  clarification, human-in-the-loop.

The rule that keeps them apart: **the RAG engine never sees conversation
history.** It receives a standalone question and an access context, nothing
else.

Neither exists yet. LangGraph, memory, and retrieval are gated on named
benchmark failures — see the milestone table in the design doc.
