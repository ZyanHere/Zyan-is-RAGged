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

/** Where an ingestion attempt is. Mirrors the backend's `IngestionStatus`. */
export type IngestionStatus = "processing" | "done" | "failed";

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
   * `null` while an attempt is still running.
   *
   * The database guarantees that reading: a CHECK constraint forbids a
   * terminal job without a finish time and a running one with one. So
   * `status: "processing"` with `finishedAt: null` means precisely *started,
   * never finished* — a document whose ingestion was interrupted.
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
