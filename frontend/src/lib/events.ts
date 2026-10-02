// How each event from the agent's stream changes the reply being built. Pure, so it's easy to test.

import type { AgentEvent, Message, Step } from "./types";

/** Long outputs stay readable in the trace without filling the browser's storage. */
export const MAX_DETAIL_CHARS = 8000;

export function applyAgentEvent(message: Message, event: AgentEvent): Message {
  const steps = message.steps ?? [];
  switch (event.type) {
    case "start":
      return { ...message, provider: event.provider, model: event.model };
    case "memory":
      return {
        ...message,
        steps: [...steps, { id: `memory-${steps.length}`, kind: "memory", available: event.available, notes: event.notes }],
      };
    case "thought":
      return { ...message, steps: [...steps, { id: `thought-${steps.length}`, kind: "thought", text: event.text }] };
    case "notice":
      return { ...message, steps: [...steps, { id: `notice-${steps.length}`, kind: "notice", text: event.message }] };
    case "tool_start":
      return {
        ...message,
        steps: [...steps, { id: event.id, kind: "tool", name: event.name, label: event.label, status: "running" }],
      };
    case "tool_end":
      return {
        ...message,
        steps: steps.map((step): Step =>
          step.kind === "tool" && step.id === event.id && step.status === "running"
            ? {
                ...step,
                status: event.ok ? "done" : "failed",
                summary: event.summary,
                detail: clip(event.detail),
                detailKind: event.kind,
              }
            : step,
        ),
      };
    case "answer":
      return {
        ...message,
        status: "done",
        content: event.text,
        usage: event.usage,
        stepCount: event.steps,
        filesRead: event.files_read,
        filesChanged: event.files_changed,
        notesSaved: event.notes_saved,
        elapsedMs: event.elapsed_ms,
        error: undefined,
        steps: finishRunning(steps),
      };
    case "error":
      return { ...message, status: "error", error: event.message, steps: finishRunning(steps) };
    default:
      return message;
  }
}

function clip(detail: string | null): string | null {
  if (!detail || detail.length <= MAX_DETAIL_CHARS) return detail;
  return `${detail.slice(0, MAX_DETAIL_CHARS)}\n… (${(detail.length - MAX_DETAIL_CHARS).toLocaleString()} characters not kept)`;
}

/** A tool still "running" when the run ends was cut off; don't leave a spinner behind. */
export function finishRunning(steps: Step[]): Step[] {
  return steps.map((step) => (step.kind === "tool" && step.status === "running" ? { ...step, status: "failed" } : step));
}
