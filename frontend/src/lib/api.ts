// Every call the web app makes to the CodeLoop server lives here, so components never build URLs
// or parse errors themselves.

import { readNdjson } from "./ndjson";
import type {
  AgentEvent,
  AppInfo,
  Brief,
  LearnResult,
  Mode,
  Note,
  Project,
  ProjectStatus,
  Provider,
  TestMethod,
} from "./types";

export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export interface AgentRunBody {
  project_id: string | null;
  message: string;
  history: { role: "user" | "assistant"; content: string }[];
  mode: Mode;
  test_methods: TestMethod[];
  provider: string;
  model: string | null;
  use_memory: boolean;
  allow_edits: boolean;
  allow_commands: boolean;
}

const scopePath = (scope: string) => `/api/memory/${encodeURIComponent(scope)}`;

export const api = {
  health: () => request<{ status: "ok" | "degraded"; memory: boolean }>("/healthz"),
  info: () => request<AppInfo>("/api/info"),
  providers: () => request<Provider[]>("/api/providers"),
  projects: () => request<Project[]>("/api/projects"),
  clone: (gitUrl: string, name?: string) =>
    request<Project>("/api/projects", { method: "POST", body: JSON.stringify({ git_url: gitUrl, name: name || null }) }),
  projectStatus: (id: string, since?: string | null) =>
    request<ProjectStatus>(
      `/api/projects/${encodeURIComponent(id)}/status${since ? `?since=${encodeURIComponent(since)}` : ""}`,
    ),
  learn: (id: string) => request<LearnResult>(`/api/projects/${encodeURIComponent(id)}/learn`, { method: "POST" }),
  memories: (scope: string, query?: string) =>
    request<{ memories: Note[]; total: number }>(
      `${scopePath(scope)}${query ? `?q=${encodeURIComponent(query)}` : ""}`,
    ),
  brief: (scope: string) => request<Brief>(`${scopePath(scope)}/brief`),
  forget: (scope: string) => request<void>(scopePath(scope), { method: "DELETE" }),

  /** Runs the agent, calling onEvent for each step as it streams in. */
  async runAgent(body: AgentRunBody, onEvent: (event: AgentEvent) => void, signal?: AbortSignal): Promise<void> {
    const response = await send("/api/agent", { method: "POST", body: JSON.stringify(body), signal });
    if (!response.ok) throw new ApiError(await errorMessage(response), response.status);
    if (!response.body) throw new ApiError("The server sent an empty reply.", response.status);
    await readNdjson<AgentEvent>(response.body, onEvent);
  },
};

async function send(path: string, init: RequestInit = {}): Promise<Response> {
  try {
    return await fetch(path, {
      ...init,
      headers: init.body ? { "Content-Type": "application/json", ...init.headers } : init.headers,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError("Can't reach the CodeLoop server. Check that it's running, then try again.", 0);
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await send(path, init);
  if (!response.ok) throw new ApiError(await errorMessage(response), response.status);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/** Turns a failed response into one readable sentence, whatever shape the body has. */
export async function errorMessage(response: Response): Promise<string> {
  const body = await response.text();
  try {
    const detail = (JSON.parse(body) as { detail?: unknown }).detail;
    if (typeof detail === "string") return detail;
    // FastAPI validation errors: [{ loc: [...], msg: "..." }, ...]
    if (Array.isArray(detail) && typeof detail[0]?.msg === "string") return detail[0].msg;
  } catch {
    // not JSON: fall through
  }
  if (body.trim()) return body.trim().slice(0, 200);
  return `The server returned an empty reply (HTTP ${response.status}). It may still be starting up.`;
}
