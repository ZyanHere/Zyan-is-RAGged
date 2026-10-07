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

  /**
   * Set by the client, not the server.
   *
   * There is no `GET /documents` yet — with no database, the backend has
   * nothing to list from. So the document list is whatever *this browser tab*
   * has uploaded, and it vanishes on refresh. That is honest rather than
   * broken, and stage 1.2 is where it becomes a real server-side list.
   */
  uploadedAt: string;
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

  createdAt: string;
}
