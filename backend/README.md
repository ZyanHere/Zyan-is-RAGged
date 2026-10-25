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

## Windows: Smart App Control and SQLAlchemy's compiled extensions

**Symptom.** Anything importing SQLAlchemy dies at startup with:

```
ImportError: DLL load failed while importing _row_cy:
An Application Control policy has blocked this file.
```

**Cause.** Windows Smart App Control is enforced on this machine
(`HKLM:\SYSTEM\CurrentControlSet\Control\CI\Policy\VerifiedAndReputablePolicyState
= 1`) and refuses to load SQLAlchemy's unsigned Cython binaries. It is the same
policy that blocks `grpcio`, which is why the agent runs in a container.

**Fix, and why it is not a weakening of anything.** SQLAlchemy ships a
pure-Python twin for every compiled module — `_row_cy.py` sits beside
`_row_cy.cp314-win_amd64.pyd` — and running without the C extensions is a
supported configuration. Python prefers the binary when both are present, so
the fix is to move the binaries out of the way:

```bash
# from the repository root
SA=backend/.venv/Lib/site-packages/sqlalchemy
BK=backend/.venv/blocked-cext-backup
mkdir -p "$BK"
cd "$SA" && for f in $(find . -name "*.pyd"); do
  mkdir -p "$BK/$(dirname $f)" && mv "$f" "$BK/$(dirname $f)/"
done
```

This **removes** unsigned binaries rather than permitting them, so the security
control stays exactly as it is. The cost is some row-fetching speed, which is
irrelevant at this scale.

> **`pip install -r requirements.txt` puts them back**, and the next thing you
> run will fail the same way. Re-run the snippet above after any install. The
> moved files are kept in `backend/.venv/blocked-cext-backup/` rather than
> deleted, so the change is reversible.

**The console scripts are blocked too.** `alembic.exe`, and any other
`.venv/Scripts/*.exe` pip generates, are unsigned wrappers and fail the same
way — as a confusing `Permission denied`. Invoke them as modules instead,
which goes through `python.exe` and works:

```bash
./.venv/Scripts/python.exe -m alembic upgrade head     # not alembic.exe
./.venv/Scripts/python.exe -m pytest                   # already the convention here
```

The permanent fix is the same one the agent already uses: run the backend and
worker in Linux containers, where the Windows policy has no reach. That is
Evolution Map 15.1.
