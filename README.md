# myRAG

**myRAG** is a universal, evidence-grounded Retrieval-Augmented Generation (RAG) platform.

## What it solves

Most LLM chatbots hallucinate. myRAG grounds every answer in your documents, returning cited, verifiable responses backed by real retrieved evidence.

## Two-stage roadmap

| Stage | Focus | Status |
|-------|-------|--------|
| **Step 1** | High-quality RAG product with a clean chatbot UI | 🟡 In progress |
| **Step 2** | Developer platform — API, SDKs, npm package, integrations | ⬜ Future |

## Current status

> **Bootstrapping phase.** Repository structure and frontend shell are being established. The RAG engine is intentionally not yet implemented.

## Repository structure

```
myRAG/
├── frontend/     React + TypeScript + Vite — chatbot UI shell
├── backend/      Future FastAPI/Node backend (placeholder)
├── agent/        Future RAG intelligence layer (placeholder)
├── benchmark/    Evaluation dataset and regression suite (placeholder)
└── docs/         Architecture decisions and experiment notes
```

## Running the frontend

```bash
cd frontend
cp .env.example .env          # configure environment
npm install
npm run dev                   # starts at http://localhost:5173
```

## Environment setup

Copy `frontend/.env.example` to `frontend/.env` and configure:

```env
VITE_API_BASE_URL=http://localhost:8000
```

See `frontend/.env.example` for all available variables.

## What is intentionally unimplemented

- RAG engine (retrieval, embeddings, reranking, grounding)
- Backend API
- Database / vector database
- LLM integration
- Authentication
- Document ingestion pipeline

These will be developed incrementally in Step 1.
