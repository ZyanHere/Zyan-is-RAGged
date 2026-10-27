"""Does a log line actually reach a handler? Stage 2.4.

**The only question in this file**, and the reason it is hard to ask honestly:
a log statement that goes nowhere looks identical to one that works. Nothing
raises, nothing warns, and the absence is only visible if you go looking for a
line you know the code emits.

── Why `caplog` cannot be used here ────────────────────────────────────────────

pytest's `caplog` fixture attaches **its own handler** to the root logger. Any
assertion written against it passes whether or not the application configured
logging at all — so a test using it would have gone green throughout the two
stages during which every API `logger.info` was being discarded.

That is the exact failure this stage exists to fix, and a test that cannot
detect it is decoration.

So these tests ask the question the `logging` module itself asks when it
dispatches a record: **walking up from the logger, respecting `propagate`, is
there a handler, and does the level admit INFO?** See `reachable_handlers`.

── And the first version of that walk was compromised the same way ────────────

`reachable_handlers` alone is not enough, which was found by mutation rather
than by reading: configuring the root logger with **no handler at all** — the
original bug, exactly — left `test_an_info_line_reaches_a_handler` green.

pytest's own logging plugin attaches a handler to the root logger for every
test. The walk found *that* and reported success, in a file whose docstring
warns about precisely this interference.

So the assertion is narrower now: among the reachable handlers, is one of
**ours**? `RequestIdFilter` is the marker — nothing but `configure_logging`
installs it, so its presence on a reachable handler means the application's
configuration is on the path, not the test runner's.

── These tests mutate global state ────────────────────────────────────────────

Logging configuration is process-wide, so `restore_logging` snapshots and
restores it. Without that, a test here that left the root logger with a
StringIO handler would quietly swallow every other test's output and, worse,
leave the next test asserting against this one's configuration.
"""

import io
import json
import logging
import sys

import pytest

from app.core.logging import (
    JsonFormatter,
    RequestIdFilter,
    configure_logging,
    request_id_var,
)

# The logger that matters: it emits the accept, the dedupe decision and the
# retry request, and every one of those was being lost in the API process.
SUBJECT = "app.services.ingestion"


def reachable_handlers(name: str) -> list[logging.Handler]:
    """Every handler a record from `name` would actually reach.

    This is `logging.Logger.callHandlers` written out: start at the logger,
    collect its handlers, and keep walking to the parent while `propagate` is
    set. A logger with no handlers of its own is fine — what is not fine is
    reaching the root and finding nothing, because then `lastResort` takes the
    record and silently drops anything below WARNING.

    **Includes pytest's handlers**, which is why callers ask
    `our_handlers_reaching` instead.
    """
    found: list[logging.Handler] = []
    current: logging.Logger | None = logging.getLogger(name)

    while current:
        found.extend(current.handlers)
        if not current.propagate:
            break
        current = current.parent

    return found


def our_handlers_reaching(name: str) -> list[logging.Handler]:
    """The reachable handlers that *this application* installed.

    Identified by `RequestIdFilter`, which only `configure_logging` attaches.
    pytest's handlers do not have it, so this answers the question the
    unqualified walk could not: is the application's own logging on the path
    from this logger, or is the test runner propping it up?
    """
    return [
        handler
        for handler in reachable_handlers(name)
        if any(isinstance(f, RequestIdFilter) for f in handler.filters)
    ]


@pytest.fixture(autouse=True)
def restore_logging():
    """Put the logging configuration back exactly as it was."""
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level
    saved_disabled = logging.root.manager.disable

    yield

    root.handlers[:] = saved_handlers
    root.setLevel(saved_level)
    logging.root.manager.disable = saved_disabled


# ── The question ─────────────────────────────────────────────────────────────


def test_an_info_line_reaches_a_handler() -> None:
    """The whole stage, as one assertion.

    Before `configure_logging` existed this was false in the API process and
    nothing said so.

    **Asks about our handler specifically.** The first version asked only
    whether *any* handler was reachable, and stayed green when the root was
    configured with none — because pytest had attached one. Mutation found it;
    reading did not.
    """
    configure_logging(json_output=True)

    assert our_handlers_reaching(SUBJECT), (
        f"no handler installed by configure_logging is on the path from "
        f"{SUBJECT} — records from it reach only logging.lastResort, which "
        f"drops everything below WARNING"
    )
    assert logging.getLogger(SUBJECT).isEnabledFor(logging.INFO), (
        "the logger has a handler, but INFO does not pass"
    )


def test_without_configuration_an_info_line_reaches_nothing() -> None:
    """The bug, pinned, so the test above cannot pass for the wrong reason.

    A test that only asserts the good state would stay green if the helper
    were broken and always returned something. This is the other half: strip
    the root handlers the way an unconfigured process has them, and the helper
    must report the hole.

    It is also the clearest statement of what uvicorn leaves behind — it
    configures its own loggers and never touches the root.
    """
    logging.getLogger().handlers.clear()

    assert our_handlers_reaching(SUBJECT) == [], (
        "with no configured handler there is nothing of ours to reach — if "
        "this passes, the helper is not measuring what it claims"
    )


def test_configuring_twice_leaves_one_handler() -> None:
    """Idempotence, and why it is not a nicety.

    Both processes may configure logging more than once — the API at import
    and a test afterwards, a worker restarted in-process. A second handler
    means every line printed twice, which is the kind of defect that gets
    diagnosed as "the worker is doing the work twice".

    `dictConfig` replaces the handlers it names, so this holds without a
    `_configured` flag — and without a flag the configuration stays changeable,
    which is what lets the tests in this file exist.
    """
    configure_logging(json_output=True)
    first = len(logging.getLogger().handlers)

    configure_logging(json_output=True)

    assert first == 1
    assert len(logging.getLogger().handlers) == 1


def test_uvicorn_loggers_are_left_alone() -> None:
    """The tempting mistake, refused.

    uvicorn attaches its own handlers and sets `propagate = False`. Adding ours
    to its loggers — an obvious-looking fix for "why can't I see uvicorn's
    output through my config?" — gives every access line two handlers and
    prints the whole request log twice.
    """
    uvicorn_access = logging.getLogger("uvicorn.access")
    before = uvicorn_access.handlers[:]

    configure_logging(json_output=True)

    assert uvicorn_access.handlers == before


# ── What a line looks like ───────────────────────────────────────────────────


def capture(json_output: bool) -> tuple[io.StringIO, logging.Logger]:
    """Point a freshly configured root handler at a buffer we can read."""
    buffer = io.StringIO()
    configure_logging(json_output=json_output)
    handler = logging.getLogger().handlers[0]
    handler.setStream(buffer)  # type: ignore[attr-defined]
    return buffer, logging.getLogger(SUBJECT)


def test_json_output_is_one_parseable_object_per_line() -> None:
    """A collector reads these. "Mostly JSON" is not a format."""
    buffer, logger = capture(json_output=True)

    logger.info("ingestion queued document_id=%s", "abc")

    line = buffer.getvalue().strip()
    payload = json.loads(line)

    assert payload["level"] == "INFO"
    assert payload["logger"] == SUBJECT
    assert payload["message"] == "ingestion queued document_id=abc"
    assert payload["request_id"] is None
    assert "ts" in payload


def test_the_request_id_rides_along_without_the_call_site_knowing() -> None:
    """The point of the `ContextVar`: no signature mentions it.

    `logger.info` here is written exactly as it is in `services/ingestion.py` —
    no extra argument, no adapter. If this required a call-site change, every
    line that someone forgot to update would be the one missing from the
    incident you are trying to reconstruct.
    """
    buffer, logger = capture(json_output=True)
    token = request_id_var.set("req-abc123")

    try:
        logger.info("ingestion done")
    finally:
        request_id_var.reset(token)

    assert json.loads(buffer.getvalue().strip())["request_id"] == "req-abc123"


def test_a_line_with_no_request_id_reads_as_it_always_did() -> None:
    """The human format must not pay for a feature it is not using.

    `request_tag` is a *prefix*, empty when there is no id, so a worker
    heartbeat looks exactly as it did before this stage rather than carrying a
    dash that means nothing.
    """
    buffer, logger = capture(json_output=False)

    logger.info("worker started")

    line = buffer.getvalue().strip()
    assert line.endswith(f"{SUBJECT}: worker started"), line
    assert "[" not in line.split(f"{SUBJECT}: ")[1]


def test_a_line_with_a_request_id_is_prefixed_for_humans() -> None:
    buffer, logger = capture(json_output=False)
    token = request_id_var.set("req-xyz")

    try:
        logger.info("claimed job")
    finally:
        request_id_var.reset(token)

    assert buffer.getvalue().strip().endswith(f"{SUBJECT}: [req-xyz] claimed job")


def test_an_unserialisable_value_does_not_break_the_logger() -> None:
    """A logging system that throws while reporting a problem is the worst case.

    `default=str` on the dump is what prevents it: the original error survives,
    rather than being replaced by a `TypeError` about JSON serialisation raised
    from inside the handler.
    """
    import uuid

    buffer, logger = capture(json_output=True)

    logger.info("document_id=%s", uuid.uuid4())

    assert json.loads(buffer.getvalue().strip())["message"].startswith("document_id=")


def test_an_exception_is_carried_on_the_same_record() -> None:
    """Not on lines of its own that a collector will split apart."""
    buffer, logger = capture(json_output=True)

    try:
        raise ValueError("the agent did not respond")
    except ValueError:
        logger.exception("ingestion failed")

    payload = json.loads(buffer.getvalue().strip())
    assert payload["level"] == "ERROR"
    assert "ValueError: the agent did not respond" in payload["exception"]


# ── The format decision ──────────────────────────────────────────────────────


def test_the_format_follows_the_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    """JSON when something will parse it; human-readable when someone reads it.

    `isatty` is the honest proxy. Piped to a file, shipped to a collector, or
    running under Docker without a TTY all mean the same thing.
    """

    class FakeStderr(io.StringIO):
        def __init__(self, tty: bool) -> None:
            super().__init__()
            self._tty = tty

        def isatty(self) -> bool:
            return self._tty

    monkeypatch.setattr(sys, "stderr", FakeStderr(tty=True))
    configure_logging()
    assert not isinstance(
        logging.getLogger().handlers[0].formatter, JsonFormatter
    ), "a terminal should get the human format"

    monkeypatch.setattr(sys, "stderr", FakeStderr(tty=False))
    configure_logging()
    assert isinstance(logging.getLogger().handlers[0].formatter, JsonFormatter)


def test_the_filter_is_on_the_handler_not_the_logger() -> None:
    """So it applies to every record, whoever emitted it.

    A filter on a logger only sees that logger's records. On the handler it
    sees everything that reaches the handler — including records from
    `sqlalchemy`, `httpx` or anything else that propagates to root, which is
    what makes a request id usable for correlation rather than only visible on
    the lines we remembered to decorate.
    """
    configure_logging(json_output=True)

    handler = logging.getLogger().handlers[0]

    assert any(isinstance(f, RequestIdFilter) for f in handler.filters)
