// ─── The vocabulary the frontend thinks in ───────────────────────────────────
//
// Pure types. No runtime code — this file compiles to nothing.
//
// These are *domain* shapes, in camelCase. The API's own snake_case shapes
// (`document_id`, `chunk_index`) are declared inside the service that owns each
// endpoint and are never exported from it, so the wire format cannot leak into
// a component. Same separation as `rag.models` vs `agent.schemas` on the Python
// side: internal shapes and boundary shapes are different things.

// ── Retrieval ────────────────────────────────────────────────────────────────

/**
 * One chunk that was put in front of the model, cited or not.
 *
 * The API returns two arrays — `citations` (what the answer referenced) and
 * `sources` (everything supplied, with scores). They are merged into this one
 * type at the service boundary, because `citations` is always a subset of
 * `sources`: the agent drops any marker the model invented outside the supplied
 * range. One list means one render path and no cross-referencing in the UI.
 */
export interface Source {
  /**
   * The number the model writes in its answer, as in `[1]`. 1-based, assigned
   * by the agent in retrieval order. This is the key that ties a bracket in the
   * answer text to a page in a document — if it is wrong, every citation in the
   * system is wrong and looks entirely plausible.
   */
  marker: number;

  documentId: string;
  filename: string;

  /** 1-based, matching what you see when you open the PDF to that page. */
  page: number;

  /**
   * Cosine similarity, roughly 0..1, higher is better.
   *
   * Only comparable *within one answer*. It is not a confidence value and must
   * not be presented as one — a top score of 0.4 across the board means
   * retrieval found nothing good, but 0.4 on its own means very little.
   */
  score: number;

  /** The chunk's text, exactly as it was shown to the model. */
  text: string;

  /**
   * True when the model actually referenced this marker in its answer.
   *
   * The difference between cited and merely retrieved is the most useful
   * diagnostic this UI can show. When an answer is wrong, the question is
   * almost always "did retrieval miss the right chunk, or did the model ignore
   * it?" — and only an uncited high-scoring source answers that.
   */
  cited: boolean;
}

/** A generated answer together with the evidence behind it. */
export interface Answer {
  text: string;
  sources: Source[];
}

// ── Documents ────────────────────────────────────────────────────────────────

/**
 * Where an ingestion attempt is. Mirrors the backend's `IngestionStatus`.
 *
 * `"queued"` arrived at stage 1.3, when upload stopped doing the work. The two
 * non-terminal states are **not** interchangeable and the UI must not treat
 * them as one:
 *
 *   queued      recorded, nobody has picked it up. A deep queue is normal.
 *               Since stage 2.1 it also covers a job *waiting to retry* after
 *               a failure, which `attempts` is what distinguishes.
 *   processing   a worker holds a lease on it and is renewing it. Since 2.1 a
 *                worker that stops renewing loses the job to a reaper, so this
 *                no longer silently means "or died holding it".
 *
 * Collapsing them into one "in progress" badge would hide the only signal a
 * user has that nothing is draining the queue.
 */
export type IngestionStatus = "queued" | "processing" | "done" | "failed";

/**
 * Whether a failure could ever have succeeded. Mirrors the backend's
 * `FailureKind`. Stage 2.3.
 *
 *   permanent   the file is the problem, and will still be the problem
 *   transient   the system was the problem; the same bytes would likely work
 *
 * ── Why the UI needs it ─────────────────────────────────────────────────────
 *
 * The error message is written for a human and is not parseable. "is not a
 * valid PDF" and "could not reach the agent" are both just strings, and only
 * one of them is worth offering a retry for.
 *
 * Offering a Retry button on a permanent failure would be the interface
 * lying: the button would queue an attempt that is guaranteed to fail the
 * same way, and the user would be left thinking the system is flaky rather
 * than that their file is unreadable.
 */
export type FailureKind = "permanent" | "transient";

/**
 * A document the server knows about, with the state of its latest attempt.
 *
 * **Server state.** It lives in the RTK Query cache, not in a slice — it is a
 * view of rows in Postgres, and the browser's copy can go stale the moment
 * anything else writes one.
 *
 * ── What used to be here, and why it is gone ────────────────────────────────
 *
 * Until stage 1.2 this type was `IngestedDocument`, paired with a
 * `SessionUpload` wrapper in an `uploads` slice that recorded what *this tab*
 * had uploaded. The argument for keeping them separate was that an upload tray
 * is not a file browser: one is a log of your activity, the other is the
 * contents of the server.
 *
 * That argument assumed the server's list would hold only successes. It does
 * not — stage 1.2 records a failed ingestion as a document with a failed job,
 * so a rejected PDF appears here with its reason. The server list turned out
 * to cover everything the session log tracked, and to survive a refresh as
 * well.
 *
 * So the slice is gone. Keeping it would have meant a client-side mirror of
 * server data, which is the duplication the client/server split exists to
 * prevent.
 */
/**
 * What one upload request did — the document, and whether work was queued.
 *
 * ── Why this exists at all ──────────────────────────────────────────────────
 *
 * Until stage 2.2 an upload always queued work, so the mutation's result was
 * just the new record. Deduplication added an outcome where **nothing was
 * written**: these exact bytes were already indexed, and the server answers
 * `200 OK` instead of `202 Accepted`.
 *
 * Without that bit the dedupe is invisible and looks like a bug. A user drops
 * a file they have uploaded before, no new row appears, and the only
 * reasonable conclusion is that the upload failed.
 *
 * ── Why it is not a field on `DocumentRecord` ───────────────────────────────
 *
 * `alreadyIndexed` is a fact about *this response*, not about the document.
 * The same document is "already indexed" to a second uploader and "newly
 * queued" to the first, and it is neither when it simply appears in the list.
 * Putting it on the record would make every list row carry a field it cannot
 * answer.
 */
/**
 * A snapshot of the ingestion pipeline. Mirrors the backend's
 * `IngestionStatsResponse`. Stage 2.4.
 *
 * ── Why the client needs any of this ────────────────────────────────────────
 *
 * Stage 2.3 built a dead-letter list and told nobody to open it. Both of that
 * stage's defects were found by going and looking, and a page you have to
 * remember to visit is a page you visit after someone complains.
 *
 * A count in the header is the cheapest possible fix: the number is either
 * zero and invisible, or it is not and you can see it without having asked.
 */
export interface IngestionStats {
  /** Queued and claimable now — the real backlog. */
  claimable: number;

  /**
   * Queued, but held back by stage 2.1's backoff.
   *
   * Kept apart from `claimable` because these are waiting *on purpose*.
   * Together they would report a backlog when nothing is stuck.
   */
  waitingForRetry: number;

  /**
   * How long the longest-waiting queued job has waited. `null` when empty.
   *
   * **The number that says whether the queue is draining.** Depth alone
   * cannot: 300 jobs moving steadily is healthy, 3 that have not moved in an
   * hour is an outage, and depth reports the first as worse.
   */
  oldestQueuedAgeSeconds: number | null;

  inFlight: number;
  done: number;

  /** What has given up, split by whether a retry could change anything. */
  deadLetter: {
    total: number;
    permanent: number;
    transient: number;
  };

  /** `null` until something has succeeded — not `0`, which reads as instant. */
  durationP50Seconds: number | null;
  durationP95Seconds: number | null;
}

export interface UploadResult {
  document: DocumentRecord;

  /**
   * True when the server recognised the bytes and queued nothing — HTTP `200`
   * rather than `202`.
   *
   * It comes from the status code because both responses carry an identical
   * body. That is deliberate on the server's side: the shape of "what is the
   * state of this document?" should not depend on how you came to ask.
   *
   * Note what this does *not* distinguish: a brand-new document from a new
   * attempt at one whose last attempt failed. Both queued work, both are
   * `202`, and the user watches the same row for the same reason — so the
   * distinction would be a difference the UI has no use for.
   */
  alreadyIndexed: boolean;
}

export interface DocumentRecord {
  documentId: string;
  filename: string;

  /** ISO 8601, from the database clock. */
  createdAt: string;

  /**
   * `null` means the document exists with no ingestion attempt recorded.
   *
   * That should be impossible — both rows are written in one transaction — and
   * it is representable because the server's query uses an outer join. Hiding
   * such a row would conceal exactly the inconsistency the record exists to
   * expose.
   */
  status: IngestionStatus | null;

  pageCount: number | null;
  pagesWithText: number | null;
  charactersExtracted: number | null;
  chunkCount: number | null;

  /**
   * Why it failed, in the engine's words.
   *
   * Durable now. Before stage 1.2 these messages lived only in the response to
   * the upload request, so a failure you scrolled past was gone.
   */
  error: string | null;

  /**
   * Whether `error` could ever have succeeded on a retry. Stage 2.3.
   *
   * `null` exactly when `error` is `null` — the two move together, which a
   * database CHECK constraint guarantees rather than a convention.
   *
   * Present on a *waiting* job too, not only a dead one. A document retrying
   * after an outage and one retrying a file that will never parse are both
   * `status: "queued"` with an error, and without this they read identically.
   */
  failureKind: FailureKind | null;

  /**
   * How many times this document has been claimed for ingestion.
   *
   * Added at stage 2.1, because without it two very different situations are
   * both `status: "queued"` and look identical:
   *
   *     attempts === 0   nobody has tried this yet
   *     attempts  >  0   it has failed and is waiting to try again
   *
   * Showing the same badge for both would hide a repeated failure behind a
   * patient-looking label.
   */
  attempts: number;

  /**
   * When a waiting job becomes claimable again. `null` means "now".
   *
   * The backoff, which lives in the database row rather than in a worker's
   * sleep. Because the list is already polled every two seconds while
   * anything is unfinished, rendering this as a countdown costs no timer —
   * each poll re-renders it.
   */
  nextAttemptAt: string | null;

  /**
   * `null` until the attempt reaches a terminal state.
   *
   * The database guarantees that reading: a CHECK constraint forbids a
   * terminal job without a finish time and a non-terminal one with one.
   *
   * Since stage 1.3 there is a companion guarantee worth knowing, because it
   * is what lets the UI tell waiting from working: a second constraint ties
   * `started_at` to the status, so `queued` always has no start time and
   * `processing` always has one. A `processing` job with no finish time is
   * therefore precisely *claimed by a worker, not yet finished* — which is
   * either normal or a dead worker, and nothing here can tell the difference
   * until stage 2.1.
   */
  finishedAt: string | null;
}

// ── Transcript ───────────────────────────────────────────────────────────────

export type MessageRole = "user" | "assistant";

/**
 * One turn in the local transcript.
 *
 * "Local" is the important word. The server has no idea a conversation is
 * happening — stage 1.1 is stateless and single-turn, and every question is
 * answered from the documents alone with no history attached. This array exists
 * purely so you can see what you asked a moment ago.
 *
 * That is also why there is no `Conversation` type any more, and no
 * `isStreaming`: nothing streams, and nothing is persisted.
 */
export interface Message {
  id: string;
  role: MessageRole;
  content: string;

  /** Assistant turns only. Absent on user turns and when nothing was retrieved. */
  sources?: Source[];

  /**
   * Epoch milliseconds, not an ISO string and not a `Date`.
   *
   * Redux state must be serializable — `configureStore` ships a development
   * check that warns on anything else, because a `Date` in the store breaks
   * time-travel debugging, state persistence and replay. A number is the
   * simplest thing that round-trips through JSON unchanged.
   *
   * It also comes free: RTK Query puts `fulfilledTimeStamp` on every fulfilled
   * action, so the assistant turn's timestamp is read from the action rather
   * than generated inside a reducer, which must stay pure.
   */
  createdAt: number;
}
