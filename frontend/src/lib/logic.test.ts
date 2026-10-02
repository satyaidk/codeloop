import { describe, expect, it } from "vitest";
import { MAX_DETAIL_CHARS, applyAgentEvent } from "./events";
import { readNdjson } from "./ndjson";
import { reducer, shortTermHistory, titleFrom } from "./state";
import { emptyState, loadState, saveState, STORAGE_KEY } from "./storage";
import { dayGroup, duration, tokens } from "./format";
import type { AgentEvent, AppData, Message } from "./types";

const pending: Message = { id: "r1", role: "assistant", content: "", createdAt: 0, status: "pending", steps: [] };

function play(events: AgentEvent[], start: Message = pending): Message {
  return events.reduce(applyAgentEvent, start);
}

describe("applyAgentEvent", () => {
  it("builds the trace step by step and finishes with the answer", () => {
    const message = play([
      { type: "start", provider: "ollama", model: "qwen3:4b-instruct", project: "shop", mode: "ask" },
      { type: "memory", available: true, notes: [{ text: "Tests use pytest" }] },
      { type: "tool_start", id: "c1", name: "read_file", label: "Reading src/cart.py" },
      { type: "tool_end", id: "c1", name: "read_file", ok: true, summary: "Read src/cart.py", detail: null, kind: "text" },
      {
        type: "answer",
        text: "It sums price × qty.",
        steps: 1,
        usage: { input: 900, output: 80, cached: 400 },
        files_read: ["src/cart.py"],
        files_changed: [],
        notes_saved: 0,
        elapsed_ms: 2100,
      },
    ]);

    expect(message.status).toBe("done");
    expect(message.model).toBe("qwen3:4b-instruct");
    expect(message.content).toBe("It sums price × qty.");
    expect(message.steps?.map((s) => s.kind)).toEqual(["memory", "tool"]);
    expect(message.steps?.[1]).toMatchObject({ status: "done", summary: "Read src/cart.py" });
    expect(message.usage?.cached).toBe(400);
  });

  it("marks tools still running when an error ends the run as failed", () => {
    const message = play([
      { type: "tool_start", id: "c1", name: "run_command", label: "Running pytest" },
      { type: "error", message: "Can't reach Ollama." },
    ]);
    expect(message.status).toBe("error");
    expect(message.error).toBe("Can't reach Ollama.");
    expect(message.steps?.[0]).toMatchObject({ status: "failed" });
  });

  it("clips very long tool output so it doesn't fill the browser's storage", () => {
    const message = play([
      { type: "tool_start", id: "c1", name: "run_command", label: "Running" },
      { type: "tool_end", id: "c1", name: "run_command", ok: true, summary: "ok", detail: "x".repeat(20_000), kind: "output" },
    ]);
    const step = message.steps?.[0];
    expect(step?.kind === "tool" && step.detail!.length).toBeLessThan(MAX_DETAIL_CHARS + 100);
  });
});

describe("readNdjson", () => {
  it("handles lines split across chunks", async () => {
    const encoder = new TextEncoder();
    const parts = ['{"type":"st', 'art"}\n{"type":"answ', 'er"}\n', '{"type":"done"}'];
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        parts.forEach((p) => controller.enqueue(encoder.encode(p)));
        controller.close();
      },
    });
    const seen: { type: string }[] = [];
    await readNdjson<{ type: string }>(stream, (item) => seen.push(item));
    expect(seen.map((s) => s.type)).toEqual(["start", "answer", "done"]);
  });
});

describe("reducer", () => {
  const user: Message = { id: "u1", role: "user", content: "Why?", createdAt: 1, mode: "debug" };

  it("starts a conversation in the selected project and puts it first", () => {
    let state = reducer(emptyState(), { type: "selectProject", projectId: "shop" });
    state = reducer(state, {
      type: "sendMessage",
      conversationId: "c1",
      projectId: "shop",
      title: "Why?",
      userMessage: user,
      pendingReply: pending,
      now: 5,
    });
    expect(state.activeId).toBe("c1");
    expect(state.conversations[0]).toMatchObject({ id: "c1", projectId: "shop", title: "Why?" });
    expect(state.conversations[0].messages).toHaveLength(2);
  });

  it("opening a chat switches to its project; deleting the open chat closes it", () => {
    let state: AppData = { ...emptyState(), conversations: [{ id: "c1", title: "t", projectId: "api", messages: [], createdAt: 0, updatedAt: 0 }] };
    state = reducer(state, { type: "selectChat", id: "c1" });
    expect(state.projectId).toBe("api");
    state = reducer(state, { type: "deleteChat", id: "c1" });
    expect(state.activeId).toBeNull();
    expect(state.conversations).toEqual([]);
  });

  it("remembers and forgets when a project was learned", () => {
    let state = reducer(emptyState(), { type: "learned", projectId: "shop", learned: { at: "2026-10-01", head: "abc123" } });
    expect(state.learned.shop.head).toBe("abc123");
    state = reducer(state, { type: "forgotProject", projectId: "shop" });
    expect(state.learned.shop).toBeUndefined();
  });
});

describe("shortTermHistory", () => {
  it("sends finished turns only, starting with a question", () => {
    const messages: Message[] = [
      { id: "1", role: "assistant", content: "orphan", createdAt: 0, status: "done" },
      { id: "2", role: "user", content: "q1", createdAt: 0 },
      { id: "3", role: "assistant", content: "", createdAt: 0, status: "error" },
      { id: "4", role: "user", content: "q2", createdAt: 0 },
      { id: "5", role: "assistant", content: "a2", createdAt: 0, status: "done" },
    ];
    expect(shortTermHistory(messages, 10)).toEqual([
      { role: "user", content: "q1" },
      { role: "user", content: "q2" },
      { role: "assistant", content: "a2" },
    ]);
    expect(shortTermHistory(messages, 0)).toEqual([]);
  });
});

describe("storage", () => {
  it("round-trips, and turns replies left pending into stopped ones", () => {
    const state = {
      ...emptyState(),
      conversations: [{ id: "c", title: "t", projectId: null, messages: [pending], createdAt: 0, updatedAt: 0 }],
    };
    saveState(state);
    const loaded = loadState();
    expect(loaded.conversations[0].messages[0].status).toBe("stopped");
  });

  it("falls back to a fresh state for unknown or broken data", () => {
    localStorage.setItem(STORAGE_KEY, "{not json");
    expect(loadState()).toEqual(emptyState());
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ version: 99 }));
    expect(loadState()).toEqual(emptyState());
  });
});

describe("format", () => {
  it("formats titles, durations and token counts", () => {
    expect(titleFrom("  fix   the\nlogin bug ")).toBe("fix the login bug");
    expect(titleFrom("x".repeat(80))).toHaveLength(58);
    expect(duration(850)).toBe("850 ms");
    expect(duration(4200)).toBe("4.2 s");
    expect(duration(95_000)).toBe("1 min 35 s");
    expect(tokens(950)).toBe("950");
    expect(tokens(4210)).toBe("4.2k");
    expect(tokens(48_000)).toBe("48k");
  });

  it("groups chats by day", () => {
    const now = new Date("2026-10-01T15:00:00").getTime();
    expect(dayGroup(now - 60_000, now)).toBe("Today");
    expect(dayGroup(now - 86_400_000, now)).toBe("Yesterday");
    expect(dayGroup(now - 3 * 86_400_000, now)).toBe("This week");
    expect(dayGroup(now - 30 * 86_400_000, now)).toBe("Older");
  });
});
