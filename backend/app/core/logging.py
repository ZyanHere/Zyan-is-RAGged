"""Logging that actually reaches a handler. Stage 2.4.

── The bug this file exists to fix ────────────────────────────────────────────

Python's root logger has no handler by default. When a record finds none,
`logging.lastResort` takes it — and `lastResort` is set to WARNING. So every
`logger.info` in a process that never configured logging is **silently
discarded**, with no error, no warning, and no hint that anything is missing.

Measured before this stage:

    worker          31 app INFO lines observed   (it called basicConfig at 1.3)
    API (uvicorn)    0

uvicorn configures its *own* loggers and leaves the root alone, so everything
the API emitted at INFO was lost — including every line stages 2.2 and 2.3
added. A duplicate upload, a lost race, an operator clicking Retry: all
invisible, in the one process a user talks to.

── Why `dictConfig` and not `basicConfig` ─────────────────────────────────────

`basicConfig` is a no-op if the root logger already has a handler, which makes
it unreliable in a process somebody else has configured — exactly the uvicorn
case. `dictConfig` is declarative and replaces what it names, so calling it
twice leaves one handler rather than two.

`disable_existing_loggers` is **False** and must be: every `logging.getLogger`
in this codebase runs at import, so the loggers already exist by the time this
is called, and the default `True` would switch them all off.

── Why uvicorn's own loggers are left alone ───────────────────────────────────

They set `propagate = False` and attach their own handlers. Naming them here
would give each access line two handlers and print it twice — a tempting fix
for "why don't I see uvicorn logs?" that produces a worse problem than the one
it solves.

── Why two formatters ─────────────────────────────────────────────────────────

JSON for anything a machine reads; the human format for a terminal. A stage
about visibility that makes logs *less* legible has failed at its own premise,
and a developer who cannot read their own logs stops reading them.
"""

import json
import logging
import logging.config
import sys
from contextvars import ContextVar

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
"""The id of the request this work belongs to. Stage 2.4.

A `ContextVar` rather than a parameter, so no call site has to carry it. In
the API an `asyncio` task per request keeps these isolated; in the worker it is
set once per claimed job.

**It is read by a logging filter, not by application code.** Nothing in
`services/` or `repositories/` mentions a request id, which is the point — the
correlation is infrastructure, and threading it by hand through every signature
is how it ends up missing from the one line that mattered.
"""


class RequestIdFilter(logging.Filter):
    """Put the current request id on every record.

    A `Filter` rather than a `LoggerAdapter` or a custom `Logger` subclass: a
    filter attaches to the *handler*, so it applies to every record that
    reaches it no matter which logger produced it or who called it. An adapter
    has to be used at the call site to do anything.

    Two fields, deliberately:

    `request_id` is the value or `None`, and goes into the JSON output as-is —
    a machine should see `null`, not a dash it has to know about.

    `request_tag` is a **prefix for humans**: `"[abc123] "` or the empty
    string. That keeps a line with no request id looking exactly as it did
    before this stage, instead of padding every worker heartbeat with a dash.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        request_id = request_id_var.get()
        record.request_id = request_id
        record.request_tag = f"[{request_id}] " if request_id else ""
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line.

    Hand-written rather than a dependency. The fields are fixed, the output is
    one `json.dumps`, and a logging library that pulls in its own configuration
    system is a larger thing to understand than twenty lines.

    **`default=str` on the dump is load-bearing.** A log call that interpolates
    a `UUID` or a `datetime` into `extra` would otherwise raise *inside the
    logging handler*, and a logging system that throws while reporting a
    problem is the worst possible failure mode — the original error is lost and
    replaced by one about serialisation.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", None),
        }

        if record.exc_info:
            # The traceback belongs in the record that reported the failure,
            # not on lines of its own that a log aggregator will split up.
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


HUMAN_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(request_tag)s%(message)s"
"""The worker's format since 1.3, plus the request tag.

The tag is empty when there is no request id, so a line that had no correlation
to show looks exactly as it did before.
"""


def configure_logging(*, level: int = logging.INFO, json_output: bool | None = None) -> None:
    """Give the root logger a handler. Safe to call more than once.

    Called from `app/main.py` at import and from `worker.py`'s `main()`. Both
    processes get the same configuration, which is what makes a request id
    greppable across them.

    Args:
        level: the root level. INFO, because the lines this stage exists to
            surface are INFO lines.
        json_output: `None` decides from the terminal — JSON when stderr is not
            a TTY, human-readable when it is. Passed explicitly only by tests
            and by anyone who wants to override the guess.

    **Idempotent through `dictConfig`, not through a flag.** `dictConfig`
    replaces the handlers it names, so a second call leaves one handler rather
    than two. A module-level `_configured` guard would be cheaper and would
    also make the configuration impossible to change in a test.
    """
    if json_output is None:
        # `isatty` is the honest proxy for "a person is reading this". Piped to
        # a file, shipped to a collector, or running under Docker without a
        # TTY all mean the same thing: something is going to parse it.
        json_output = not sys.stderr.isatty()

    logging.config.dictConfig(
        {
            "version": 1,
            # Every `getLogger` in this codebase has already run by the time
            # this is called. The default `True` would disable all of them.
            "disable_existing_loggers": False,
            "filters": {
                "request_id": {"()": RequestIdFilter},
            },
            "formatters": {
                "human": {"format": HUMAN_FORMAT},
                "json": {"()": JsonFormatter},
            },
            "handlers": {
                "default": {
                    "class": "logging.StreamHandler",
                    # stderr, not stdout: logs are diagnostics, and a process
                    # whose stdout is a pipe to something else should not have
                    # them mixed into its output.
                    "stream": "ext://sys.stderr",
                    "formatter": "json" if json_output else "human",
                    "filters": ["request_id"],
                },
            },
            # Root only. uvicorn's loggers configure themselves and set
            # `propagate = False`; naming them here prints every access line
            # twice.
            "root": {"handlers": ["default"], "level": level},
        }
    )
