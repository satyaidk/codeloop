// Drives the whole web app the way a developer would, against a fake CodeLoop server.

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { AppStateProvider } from "./lib/AppState";
import { ServerProvider } from "./lib/server";
import type { AgentEvent } from "./lib/types";

const PROJECT = {
  id: "shop-api",
  name: "shop-api",
  is_git: true,
  branch: "main",
  head: "a1b2c3d",
  subject: "Add cart",
  committed_at: "2026-09-30T10:00:00Z",
};

const INFO = {
  version: "0.1.0",
  default_provider: "ollama",
  workspace_root: "/home/dev/workspace",
  max_steps: 12,
  max_history_messages: 12,
  commands_enabled: true,
  command_allowlist: ["pytest", "npm"],
  test_methods: { unit: "Unit", property: "Property-based", mutation: "Mutation" },
};

const PROVIDERS = [
  {
    id: "ollama",
    label: "Ollama",
    kind: "openai",
    configured: true,
    local: true,
    default_model: "qwen3:4b-instruct",
    models: ["qwen3:4b-instruct"],
    installed: true,
    hint: "",
  },
  {
    id: "anthropic",
    label: "Anthropic",
    kind: "anthropic",
    configured: false,
    local: false,
    default_model: "claude-opus-5-5",
    models: ["claude-opus-5-5"],
    installed: null,
    hint: "Add ANTHROPIC_API_KEY to .env",
  },
];

let agentEvents: AgentEvent[] = [];
let notes = 3;
const calls: { url: string; body?: unknown }[] = [];

function ndjson(events: AgentEvent[]): Response {
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      const encoder = new TextEncoder();
      for (const event of events) controller.enqueue(encoder.encode(JSON.stringify(event) + "\n"));
      controller.close();
    },
  });
  return new Response(body, { headers: { "Content-Type": "application/x-ndjson" } });
}

const json = (data: unknown) => new Response(JSON.stringify(data), { headers: { "Content-Type": "application/json" } });

beforeEach(() => {
  calls.length = 0;
  notes = 3;
  agentEvents = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      calls.push({ url, body: init?.body ? JSON.parse(String(init.body)) : undefined });
      if (url === "/api/info") return json(INFO);
      if (url === "/api/projects") return json([PROJECT]);
      if (url === "/api/providers") return json(PROVIDERS);
      if (url === "/healthz") return json({ status: "ok", memory: true });
      if (url.startsWith("/api/projects/shop-api/status")) return json({ project: PROJECT, notes, commits_since: null });
      if (url === "/api/projects/shop-api/learn")
        return json({ files_scanned: 12, characters: 4000, head: "a1b2c3d", branch: "main", learned_at: "2026-10-01T10:00:00Z" });
      if (url.startsWith("/api/memory/")) return json({ memories: [{ text: "Tests run with pytest -q" }], total: 1 });
      if (url === "/api/agent") return ndjson(agentEvents);
      return new Response("not found", { status: 404 });
    }),
  );
});

function renderApp() {
  return render(
    <ServerProvider>
      <AppStateProvider>
        <App />
      </AppStateProvider>
    </ServerProvider>,
  );
}

async function openProject(user: ReturnType<typeof userEvent.setup>) {
  renderApp();
  await user.click(await screen.findByRole("button", { name: /shop-api/ }));
  await screen.findByRole("heading", { level: 2, name: "shop-api" });
}

const ANSWER: AgentEvent[] = [
  { type: "start", provider: "ollama", model: "qwen3:4b-instruct", project: "shop-api", mode: "debug" },
  { type: "memory", available: true, notes: [{ text: "Cart totals live in src/cart.py" }, { text: "Uses pytest" }] },
  { type: "tool_start", id: "c1", name: "edit_file", label: "Editing src/cart.py" },
  {
    type: "tool_end",
    id: "c1",
    name: "edit_file",
    ok: true,
    summary: "Edited src/cart.py · +1 −1",
    detail: "--- a/src/cart.py\n+++ b/src/cart.py\n@@ -1 +1 @@\n-    return []\n+    return list()",
    kind: "diff",
  },
  {
    type: "answer",
    text: "The total ignored **quantity**. Fixed in `src/cart.py`.",
    steps: 1,
    usage: { input: 4200, output: 310, cached: 1800 },
    files_read: ["src/cart.py"],
    files_changed: ["src/cart.py"],
    notes_saved: 1,
    elapsed_ms: 14_000,
  },
];

describe("CodeLoop", () => {
  it("shows the project with what memory knows about it", async () => {
    const user = userEvent.setup();
    await openProject(user);

    expect(await screen.findByText(/3 facts/)).toBeInTheDocument();
    expect(screen.getByText("a1b2c3d")).toBeInTheDocument();
  });

  it("offers to learn a project memory doesn't know yet", async () => {
    notes = 0;
    const user = userEvent.setup();
    await openProject(user);

    await user.click(await screen.findByRole("button", { name: "Learn this project" }));

    await waitFor(() => expect(calls.some((c) => c.url === "/api/projects/shop-api/learn")).toBe(true));
    expect(await screen.findByText(/Hindsight is turning the scan into facts/)).toBeInTheDocument();
  });

  it("sends a question in the chosen mode and shows the agent's steps and answer", async () => {
    agentEvents = ANSWER;
    const user = userEvent.setup();
    await openProject(user);

    await user.click(screen.getByRole("radio", { name: /Debug/ }));
    await user.click(screen.getByRole("button", { name: /Edit files/ }));
    await user.type(screen.getByRole("textbox", { name: "Message" }), "The cart total is wrong{Enter}");

    // The answer is rendered as Markdown once the renderer has loaded.
    expect(await screen.findByText("quantity", { selector: "strong" })).toBeInTheDocument();
    expect(screen.getByText("2 notes recalled · 1 tool call · read 1 file · changed 1 · saved 1 note")).toBeInTheDocument();
    expect(screen.getByText(/Edited src\/cart.py/)).toBeInTheDocument(); // the trace stays open when files changed
    expect(screen.getByText(/4.2k in/)).toHaveTextContent("4.2k in (1.8k cached) · 310 out");

    const sent = calls.find((c) => c.url === "/api/agent")?.body as Record<string, unknown>;
    expect(sent).toMatchObject({
      project_id: "shop-api",
      message: "The cart total is wrong",
      mode: "debug",
      provider: "ollama",
      model: "qwen3:4b-instruct",
      allow_edits: true,
      allow_commands: false,
      use_memory: true,
    });
  });

  it("shows the diff of an edit on request", async () => {
    agentEvents = ANSWER;
    const user = userEvent.setup();
    await openProject(user);
    await user.type(screen.getByRole("textbox", { name: "Message" }), "fix it{Enter}");

    await user.click(await screen.findByText("Show diff"));

    expect(screen.getByText(/^\+\s+return list\(\)/)).toBeInTheDocument();
  });

  it("sends the chosen testing methods in Test mode", async () => {
    agentEvents = [ANSWER[4]];
    const user = userEvent.setup();
    await openProject(user);

    await user.click(screen.getByRole("radio", { name: /Test/ }));
    await user.click(screen.getByRole("button", { name: "Property-based" }));
    await user.type(screen.getByRole("textbox", { name: "Message" }), "test the cart{Enter}");

    await screen.findByText(/ignored/);
    const sent = calls.find((c) => c.url === "/api/agent")?.body as Record<string, unknown>;
    expect(sent.mode).toBe("test");
    expect(sent.test_methods).toEqual(["unit", "property"]);
  });

  it("shows the server's reason when the model fails, with a retry", async () => {
    agentEvents = [{ type: "error", message: "Can't reach Ollama at http://localhost:11434/v1." }];
    const user = userEvent.setup();
    await openProject(user);

    await user.type(screen.getByRole("textbox", { name: "Message" }), "hello{Enter}");

    expect(await screen.findByRole("alert")).toHaveTextContent("Can't reach Ollama");
    agentEvents = ANSWER;
    await user.click(screen.getByRole("button", { name: /Try again/ }));
    expect(await screen.findByText(/ignored/)).toBeInTheDocument();
  });

  it("explains a provider that isn't set up", async () => {
    const user = userEvent.setup();
    renderApp();

    await user.click(await screen.findByRole("button", { name: /Choose the model|Ollama/ }));
    await user.click(screen.getByRole("button", { name: /Anthropic/ }));

    expect(screen.getByText("Add ANTHROPIC_API_KEY to .env")).toBeInTheDocument();
  });

  it("keeps edits and commands off in the scratchpad", async () => {
    renderApp();
    await screen.findByRole("heading", { level: 2, name: "Scratchpad" });

    expect(screen.getByRole("button", { name: /Edit files/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Run commands/ })).toBeDisabled();
  });
});
