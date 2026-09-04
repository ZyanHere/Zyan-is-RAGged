/**
 * sse.ts — Server-Sent Events parser
 *
 * SSE looks trivial: named events separated by blank lines.
 *
 *     event: token
 *     data: {"text":"Hello"}
 *     <blank line>
 *
 * The trap is that a network chunk can end **anywhere** — including halfway
 * through `data: {"tex`. Splitting each chunk on "\n\n" as it arrives silently
 * drops the tail of every partial event, which shows up as randomly missing
 * words in the answer. So we keep a buffer across reads and only emit an event
 * once its terminating blank line has actually arrived.
 */

export interface SseEvent {
  /** The `event:` name. Defaults to "message" per the SSE spec. */
  event: string;
  /** Everything from the `data:` line(s), joined with newlines. */
  data: string;
}

/** Parse one complete event block (the text between two blank lines). */
function parseBlock(raw: string): SseEvent | null {
  let event = "message";
  const dataLines: string[] = [];

  for (const line of raw.split("\n")) {
    // Servers may use CRLF; strip the CR so comparisons behave.
    const l = line.endsWith("\r") ? line.slice(0, -1) : line;

    // A line starting with ":" is a comment — used for keep-alive pings.
    if (l === "" || l.startsWith(":")) continue;

    if (l.startsWith("event:")) {
      event = l.slice(6).trim();
    } else if (l.startsWith("data:")) {
      // The spec strips exactly one leading space after the colon.
      const value = l.slice(5);
      dataLines.push(value.startsWith(" ") ? value.slice(1) : value);
    }
  }

  // An event with no data carries nothing actionable.
  if (dataLines.length === 0) return null;

  return { event, data: dataLines.join("\n") };
}

/**
 * Read an SSE response body and yield complete events as they arrive.
 *
 * We use `fetch` + ReadableStream rather than the browser's built-in
 * `EventSource`, because EventSource can only issue GETs and cannot set
 * headers — no POST body, no auth token.
 */
export async function* parseSseStream(
  body: ReadableStream<Uint8Array>
): AsyncGenerator<SseEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      // `stream: true` keeps multi-byte characters intact when one lands
      // across a chunk boundary.
      buffer += decoder.decode(value, { stream: true });

      // Emit every *complete* block; whatever follows the last blank line
      // stays in the buffer until more bytes arrive.
      let separator = buffer.indexOf("\n\n");
      while (separator !== -1) {
        const block = buffer.slice(0, separator);
        buffer = buffer.slice(separator + 2);
        const parsed = parseBlock(block);
        if (parsed) yield parsed;
        separator = buffer.indexOf("\n\n");
      }
    }

    // A well-behaved server ends with a blank line, but if the connection
    // closes on a final event without one, do not lose it.
    const trailing = parseBlock(buffer);
    if (trailing) yield trailing;
  } finally {
    reader.releaseLock();
  }
}
