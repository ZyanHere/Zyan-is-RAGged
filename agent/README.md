# Agent

This directory will contain the OmniRAG RAG intelligence layer.

## Planned structure

```
agent/
├── ingestion/    Document ingestion pipeline
├── document/     Document parsing and normalisation
├── embeddings/   Embedding model integrations
├── chunking/     Text chunking strategies
├── indexing/     Vector index management
├── retrieval/    Retrieval strategies (dense, sparse, hybrid)
├── reranking/    Cross-encoder reranking
├── context/      Context assembly and compression
├── grounding/    Evidence grounding and attribution
├── guardrails/   Input/output safety filters
├── generation/   LLM call orchestration
└── evaluation/   Automated quality evaluation
```

## Not yet implemented

The RAG agent layer is intentionally empty. It will be developed incrementally in Step 1, driven by the benchmark evaluation suite in `../benchmark/`.

## Design principles

- Every answer must be grounded in retrieved evidence.
- No hallucination tolerance.
- Benchmark-driven: every RAG component change must pass regression evaluation before merging.
