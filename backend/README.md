# myRAG Backend

Minimal FastAPI backend scaffold for the myRAG project. It provides the local API boundary that the frontend will call while the RAG engine is built separately later.

## Setup

From `backend/`:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

On macOS/Linux, activate with:

```bash
source .venv/bin/activate
```

## Configuration

Create a local environment file from the example:

```bash
copy .env.example .env
```

Set `FRONTEND_ORIGIN` to the frontend dev origin, for example:

```env
FRONTEND_ORIGIN=http://localhost:3000
```

`.env` is ignored by git. Commit `.env.example`, not `.env`.

## Run

```bash
uvicorn app.main:app --reload --port 8000
```

Local API: `http://localhost:8000`

Swagger docs: `http://localhost:8000/docs`

ReDoc: `http://localhost:8000/redoc`

Health check: `GET http://localhost:8000/health`

Expected health response:

```json
{
  "status": "ok"
}
```

## Tests

```bash
pytest
```

## RAG Status

RAG functionality is intentionally not implemented yet. This backend does not perform ingestion, OCR, embeddings, retrieval, reranking, LLM calls, or agent orchestration.
