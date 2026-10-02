// The selected project's memory: how many facts it holds, how stale it is, and "learn this project".
// Shared by the welcome screen and the memory panel so they always agree.

import { createContext, useCallback, useContext, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { api } from "./api";
import { useAppState } from "./AppState";
import { useServer } from "./server";
import { useProjectStatus } from "../hooks/useProjectStatus";
import type { Learned, Project, ProjectStatus } from "./types";

interface ProjectMemoryValue {
  project: Project | null; // null: the scratchpad
  scope: string; // memory scope: the project id, or "scratch"
  status: ProjectStatus | null;
  learned: Learned | null;
  learning: boolean;
  learnError: string | null;
  learn: () => Promise<void>;
  refresh: (keepPolling?: boolean) => void;
}

const ProjectMemoryContext = createContext<ProjectMemoryValue | null>(null);

export function ProjectMemoryProvider({ children }: { children: ReactNode }) {
  const { state, dispatch } = useAppState();
  const { projects } = useServer();
  const project = projects.find((p) => p.id === state.projectId) ?? null;
  const learned = (project && state.learned[project.id]) || null;
  const { status, refresh } = useProjectStatus(project?.id ?? null, learned?.head);
  const [learning, setLearning] = useState(false);
  const [learnError, setLearnError] = useState<string | null>(null);

  const learn = useCallback(async () => {
    if (!project) return;
    setLearning(true);
    setLearnError(null);
    try {
      const result = await api.learn(project.id);
      dispatch({ type: "learned", projectId: project.id, learned: { at: result.learned_at, head: result.head } });
      refresh(true);
    } catch (error) {
      setLearnError(error instanceof Error ? error.message : String(error));
    } finally {
      setLearning(false);
    }
  }, [project, dispatch, refresh]);

  const value = useMemo(
    () => ({ project, scope: project?.id ?? "scratch", status, learned, learning, learnError, learn, refresh }),
    [project, status, learned, learning, learnError, learn, refresh],
  );
  return <ProjectMemoryContext.Provider value={value}>{children}</ProjectMemoryContext.Provider>;
}

// oxlint-disable-next-line react/only-export-components -- the hook belongs with its provider
export function useProjectMemory(): ProjectMemoryValue {
  const value = useContext(ProjectMemoryContext);
  if (!value) throw new Error("useProjectMemory must be used inside <ProjectMemoryProvider>");
  return value;
}
