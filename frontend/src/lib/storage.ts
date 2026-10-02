// Chats and settings live in this browser's localStorage. There is no chat database on purpose: chats
// stay on the developer's machine, and the server only keeps what Hindsight learns.

import type { AppData, Settings } from "./types";

export const STORAGE_KEY = "codeloop.state.v1";

export const DEFAULT_SETTINGS: Settings = {
  theme: "system",
  provider: "",
  models: {},
  mode: "ask",
  testMethods: ["unit"],
  useMemory: true,
  allowEdits: false,
  allowCommands: false,
  historyLength: 12,
  memoryPanel: true,
};

export function emptyState(): AppData {
  return { version: 1, settings: { ...DEFAULT_SETTINGS }, conversations: [], activeId: null, projectId: null, learned: {} };
}

export function loadState(storage: Storage | undefined = globalThis.localStorage): AppData {
  try {
    const raw = storage?.getItem(STORAGE_KEY);
    if (!raw) return emptyState();
    const parsed = JSON.parse(raw) as Partial<AppData>;
    if (parsed.version !== 1 || !Array.isArray(parsed.conversations)) return emptyState();
    return {
      ...emptyState(),
      ...parsed,
      settings: { ...DEFAULT_SETTINGS, ...parsed.settings },
      learned: parsed.learned ?? {},
      // A reply still "pending" in storage was cut off when the page closed.
      conversations: parsed.conversations.map((c) => ({
        ...c,
        messages: c.messages.map((m) =>
          m.status === "pending" ? { ...m, status: "stopped" as const, steps: m.steps ?? [] } : m,
        ),
      })),
    };
  } catch {
    return emptyState();
  }
}

/** Saves the state. Returns an error message when the browser refuses (storage full or blocked). */
export function saveState(state: AppData, storage: Storage | undefined = globalThis.localStorage): string | null {
  try {
    storage?.setItem(STORAGE_KEY, JSON.stringify(state));
    return null;
  } catch {
    return "This browser's storage is full, so new messages aren't being saved. Delete some old chats.";
  }
}
