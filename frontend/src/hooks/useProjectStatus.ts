import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";
import type { ProjectStatus } from "../lib/types";

/**
 * A project's memory size and how far its code has moved since it was learned.
 * Hindsight extracts facts in the background, so the count grows for a while after learning or chatting;
 * `refresh(true)` keeps polling for a minute to show that.
 */
export function useProjectStatus(projectId: string | null, learnedHead: string | null | undefined) {
  const [status, setStatus] = useState<ProjectStatus | null>(null);
  const [polls, setPolls] = useState(0);

  const load = useCallback(async () => {
    if (!projectId) return;
    try {
      setStatus(await api.projectStatus(projectId, learnedHead));
    } catch {
      setStatus(null);
    }
  }, [projectId, learnedHead]);

  useEffect(() => {
    // oxlint-disable-next-line react/set-state-in-effect -- load() sets state when the request resolves
    void load();
  }, [load]);

  useEffect(() => {
    if (polls <= 0) return;
    const timer = window.setTimeout(() => {
      void load();
      setPolls((n) => n - 1);
    }, 6000);
    return () => window.clearTimeout(timer);
  }, [polls, load]);

  const refresh = useCallback(
    (keepPolling = false) => {
      void load();
      if (keepPolling) setPolls(10);
    },
    [load],
  );
  // A status loaded for another project is stale the moment the selection changes.
  return { status: status && status.project.id === projectId ? status : null, refresh };
}
