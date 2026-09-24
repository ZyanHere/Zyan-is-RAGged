# 0002 — Embedding provider: Gemini `gemini-embedding-001` at 768 dimensions

**Status:** accepted
**Date:** 2026-09-04

## Context

M2 needs embeddings — the model that turns text into vectors so chunks can be
found by meaning rather than by keyword. Two facts forced a decision:

1. **OpenRouter does not offer embedding models at all.** Verified against
   `https://openrouter.ai/api/v1/models`: zero models matching "embed". It is a
   chat-completions gateway. So a second provider was unavoidable.
2. **Embeddings are needed at both ends** — once per chunk at ingestion, and
   once per question at query time. This is not an offline batch concern.

## Options considered

| Option | Cost | Rate limits | Setup | Privacy |
|---|---|---|---|---|
| `sentence-transformers` locally | free forever | none | ~2GB PyTorch download | documents never leave the machine |
| **Gemini API** | free tier | yes | one API key | text sent to Google |
| OpenAI embeddings | ~$0.02/1M tokens | yes | paid key | text sent to OpenAI |

## Decision

**`gemini-embedding-001`, truncated to 768 dimensions**, via a free Google AI
Studio key.

### Why Gemini over local

Chosen for setup cost: a free API key versus a 2GB PyTorch install, on a project
where the interesting work is retrieval quality, not model hosting.

This overrides the earlier lean toward local. The local argument — unlimited
re-embedding during M3 benchmark runs — is real and may yet win; see "When to
revisit".

### Why 768 and not 3072

The model supports truncating its output vector. 768 keeps nearly all retrieval
quality while making the index **4x smaller and 4x faster to search**. At the
scale this project targets (10M+ chunks) that difference dominates; at current
scale the quality gap is unobservable.

## Consequences

**This is the stickiest decision in the system.** Changing either the model or
the dimension invalidates every stored vector and forces a full re-ingest of
every document. It is a migration, not a config change.

Two mitigations, both required:

1. **Record `embedding_model` and `embedding_dim` in the Qdrant collection
   metadata and on every chunk payload**, so a mismatch is detectable instead of
   silently returning nonsense.
2. **Keep it behind the provider seam** (`agent/app/providers/`), exactly as the
   chat model is. Nothing outside `providers/` imports a vendor SDK.

**Two providers, two keys.** `OPENROUTER_API_KEY` for answering,
`GOOGLE_API_KEY` for embedding. Normal for production systems; each provider is
used for what it is best at.

**A second free tier to be throttled by.** OpenRouter's shared-pool throttling
already bit once. Gemini's embedding quota is generous but finite.

## When to revisit

- **M3 benchmark runs become painful.** Every chunking experiment re-embeds the
  whole corpus. If quota or latency makes that miserable, switch to local
  `sentence-transformers` — the seam makes it one new file.
- Documents become sensitive enough that sending them to Google is unacceptable.
- Benchmark evidence shows a different model retrieves measurably better on this
  corpus (this is Research Question 1 in the product bible).

## Related

- `docs/architecture/system-design.md` section 8.4 — embeddings
- `agent/app/providers/base.py` — the seam this plugs into
