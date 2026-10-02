// Reads a stream of newline-delimited JSON (one event per line) as the chunks arrive.
// A chunk can end in the middle of a line, so the unfinished tail waits for the next chunk.

export async function readNdjson<T>(body: ReadableStream<Uint8Array>, onItem: (item: T) => void): Promise<void> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    buffer += done ? decoder.decode() : decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = done ? "" : (lines.pop() ?? "");
    for (const line of lines) {
      if (line.trim()) onItem(JSON.parse(line) as T);
    }
    if (done) return;
  }
}
