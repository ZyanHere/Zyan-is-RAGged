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
 * What ingestion reported about one uploaded file.
 *
 * Numbers rather than a success boolean, because the dangerous outcome at this
 * stage is not a crash — it is a scanned PDF that indexes nothing and reports
 * success. The gap between `pageCount` and `pagesWithText` is the tell, and
 * surfacing it is the whole reason these fields cross the wire.
 *
 * No derived `isProbablyScanned` flag: deciding what counts as suspicious is a
 * policy, and policy belongs in the component that renders the warning.
 *
 * Purely the server's view of one ingest. When the upload *happened* is not on
 * this type: that is a fact about this browser session, not about the
 * document, and it belongs on the `SessionUpload` wrapper in the uploads slice
 * (layer 3). Keeping them apart is what makes stage 1.2 additive — a real
 * `GET /documents` returns exactly this shape, and the session record stays
 * where it is.
 */
export interface IngestedDocument {
  documentId: string;
  filename: string;

  /** Pages in the PDF. */
  pageCount: number;

  /** Pages that yielded any text. Less than `pageCount` means pages were lost. */
  pagesWithText: number;

  charactersExtracted: number;
  chunkCount: number;
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

// ── Session activity ─────────────────────────────────────────────────────────

/**
 * One upload made by *this browser session*.
 *
 * Distinct from `IngestedDocument`, and the distinction is the point.
 * `IngestedDocument` is the server's view of one ingest — exactly what
 * `GET /documents` will return at stage 1.2. A `SessionUpload` is a record of
 * something *you did here*: which attempt it was, and when.
 *
 * Today they look like the same thing because the server list does not exist.
 * Keeping them apart means stage 1.2 is purely additive — a query endpoint
 * appears and this type does not move. Had the document list itself been
 * modelled as client state, 1.2 would force a migration.
 *
 * The analogy worth holding: an upload tray is not a file browser. One is a
 * log of your activity, the other is the contents of the server, and they stay
 * separate concepts even once both exist.
 */
export interface SessionUpload {
  /**
   * The RTK Query `requestId` — unique per upload *attempt*.
   *
   * Deliberately not `document.documentId`. At stage 2.2 content-addressed
   * idempotency makes re-uploading the same file return the *same* document
   * id, so two entries in this list would collide on a React key. The request
   * id has no such problem and needs no change then.
   */
  id: string;

  document: IngestedDocument;

  /** Epoch milliseconds, from the fulfilled action's `fulfilledTimeStamp`. */
  uploadedAt: number;
}
