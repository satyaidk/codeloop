// Shapes shared across the web app. Server shapes mirror app/schemas.py; the rest is browser-only state.

export type Mode = "ask" | "write" | "debug" | "review" | "test";
export type TestMethod =
  | "unit"
  | "integration"
  | "e2e"
  | "property"
  | "fuzz"
  | "mutation"
  | "snapshot"
  | "contract"
  | "performance"
  | "security"
  | "accessibility"
  | "regression"
  | "smoke";
export type Theme = "system" | "light" | "dark";

// ---- from the server ----

export interface Note {
  text: string;
  type?: string | null;
  occurred_at?: string | null;
}

export interface Provider {
  id: string;
  label: string;
  kind: string;
  configured: boolean;
  local: boolean;
  default_model: string;
  models: string[];
  installed: boolean | null;
  hint: string;
}

export interface Project {
  id: string;
  name: string;
  is_git: boolean;
  branch: string | null;
  head: string | null;
  subject: string | null;
  committed_at: string | null;
}

export interface ProjectStatus {
  project: Project;
  notes: number | null;
  commits_since: number | null;
}

export interface LearnResult {
  files_scanned: number;
  characters: number;
  head: string | null;
  branch: string | null;
  learned_at: string;
}

export interface Brief {
  summary: string;
  stack: string[];
  structure: string[];
  commands: string[];
  conventions: string[];
  open_issues: string[];
}

export interface AppInfo {
  version: string;
  default_provider: string;
  workspace_root: string;
  max_steps: number;
  max_history_messages: number;
  commands_enabled: boolean;
  command_allowlist: string[];
  test_methods: Record<TestMethod, string>;
}

export interface Usage {
  input: number;
  output: number;
  cached: number;
}

/** One line of the agent's NDJSON stream (see app/agent.py). */
export type AgentEvent =
  | { type: "start"; provider: string; model: string; project: string; mode: Mode }
  | { type: "memory"; available: boolean; notes: Note[] }
  | { type: "thought"; text: string }
  | { type: "tool_start"; id: string; name: string; label: string }
  | {
      type: "tool_end";
      id: string;
      name: string;
      ok: boolean;
      summary: string;
      detail: string | null;
      kind: "diff" | "output" | "notes" | "text";
    }
  | { type: "notice"; message: string }
  | {
      type: "answer";
      text: string;
      steps: number;
      usage: Usage;
      files_read: string[];
      files_changed: string[];
      notes_saved: number;
      elapsed_ms: number;
    }
  | { type: "error"; message: string };

// ---- in the browser ----

/** One entry in the trace of what the agent did for a reply. */
export type Step =
  | { id: string; kind: "memory"; available: boolean; notes: Note[] }
  | { id: string; kind: "thought"; text: string }
  | { id: string; kind: "notice"; text: string }
  | {
      id: string;
      kind: "tool";
      name: string;
      label: string;
      status: "running" | "done" | "failed";
      summary?: string;
      detail?: string | null;
      detailKind?: "diff" | "output" | "notes" | "text";
    };

export type MessageStatus = "pending" | "done" | "error" | "stopped";

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  createdAt: number;
  mode?: Mode;
  testMethods?: TestMethod[];
  status?: MessageStatus;
  error?: string;
  steps?: Step[];
  provider?: string;
  model?: string;
  usage?: Usage;
  stepCount?: number;
  filesRead?: string[];
  filesChanged?: string[];
  notesSaved?: number;
  elapsedMs?: number;
}

export interface Conversation {
  id: string;
  title: string;
  projectId: string | null;
  messages: Message[];
  createdAt: number;
  updatedAt: number;
}

export interface Settings {
  theme: Theme;
  provider: string; // "" until the server's default is known
  models: Record<string, string>; // chosen model per provider
  mode: Mode;
  testMethods: TestMethod[];
  useMemory: boolean;
  allowEdits: boolean;
  allowCommands: boolean;
  historyLength: number;
  memoryPanel: boolean;
}

export interface Learned {
  at: string;
  head: string | null;
}

export interface AppData {
  version: 1;
  settings: Settings;
  conversations: Conversation[];
  activeId: string | null;
  projectId: string | null; // null: the scratchpad (no project)
  learned: Record<string, Learned>;
}
