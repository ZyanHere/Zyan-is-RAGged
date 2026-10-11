# The agent service.
#
# Built from the repository root, not from `agent/`, because the agent depends
# on the sibling `rag` package via `-e ../rag`. A build context of `agent/`
# cannot see `../rag` at all — Docker refuses to read anything above the
# context root, by design.
#
#   docker compose build agent      (compose sets context: . for this reason)
#
# ── Why this container exists at all ─────────────────────────────────────────
#
# Partly stage 15.1, arrived at early. The immediate reason is narrower:
# Windows Smart App Control refuses to load `grpcio`'s unsigned compiled
# binary, which `qdrant-client` imports. That policy governs the Windows host
# and has no bearing on code running inside a Linux container, so the agent
# runs here and the policy stays on.

FROM python:3.14-slim

# Fail fast and log immediately.
#   PYTHONUNBUFFERED       without it, stdout is block-buffered when not a TTY
#                          and `docker compose logs` shows nothing until the
#                          buffer fills — which looks exactly like a hang.
#   PYTHONDONTWRITEBYTECODE  .pyc files in a layer that is rebuilt anyway.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app/agent

# `-e ../rag` in requirements.txt is resolved against the *working directory*
# at the moment pip runs, not against the requirements file's location. So
# `rag` must already be here, and WORKDIR must already be `/app/agent`, before
# the install. Getting either wrong produces a confusing "file not found".
COPY rag/ /app/rag/

# Requirements before application code, so editing a route does not reinstall
# every dependency. The `rag` copy above does invalidate this layer whenever
# the engine changes — accepted, because the editable install needs the package
# present and splitting it further would be more machinery than it saves.
COPY agent/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt

COPY agent/app/ ./app/

# A non-root user, and the storage directory created with the right owner
# before the volume is mounted over it.
#
# Docker copies the ownership of an existing directory onto a fresh named
# volume mounted at that path. Create it root-owned and the volume is
# root-owned, and the agent — running as `agent` — cannot write its index. The
# failure is a permission error deep inside Qdrant that says nothing about
# Docker.
RUN useradd --create-home --uid 1000 agent \
    && mkdir -p /app/agent/qdrant_data \
    && chown -R agent:agent /app
USER agent

EXPOSE 8001

# No `--reload`.
#
# The reloader briefly runs two processes, and embedded Qdrant holds an
# exclusive lock on its storage folder — the second process fails to start with
# a lock error. Source is bind-mounted in compose instead, so
# `docker compose restart agent` picks up changes without a rebuild.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
