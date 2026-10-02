// What the server knows (its settings, model providers, projects, health), loaded once and refreshable.

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { api } from "./api";
import type { AppInfo, Project, Provider } from "./types";

export type Health = "checking" | "ok" | "no-memory" | "offline";

interface ServerValue {
  info: AppInfo | null;
  providers: Provider[];
  projects: Project[];
  health: Health;
  loadError: string | null;
  refreshProjects: () => Promise<Project[]>;
  refreshProviders: () => Promise<void>;
}

const ServerContext = createContext<ServerValue | null>(null);

export function ServerProvider({ children }: { children: ReactNode }) {
  const [info, setInfo] = useState<AppInfo | null>(null);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [health, setHealth] = useState<Health>("checking");
  const [loadError, setLoadError] = useState<string | null>(null);

  const refreshProjects = useCallback(async () => {
    const list = await api.projects();
    setProjects(list);
    return list;
  }, []);

  const refreshProviders = useCallback(async () => {
    setProviders(await api.providers());
  }, []);

  useEffect(() => {
    let alive = true;
    Promise.all([api.info(), api.projects(), api.providers()])
      .then(([i, p, pr]) => {
        if (!alive) return;
        setInfo(i);
        setProjects(p);
        setProviders(pr);
        setLoadError(null);
      })
      .catch((error: Error) => alive && setLoadError(error.message));

    const check = () =>
      api
        .health()
        .then((h) => alive && setHealth(h.memory ? "ok" : "no-memory"))
        .catch(() => alive && setHealth("offline"));
    void check();
    const timer = window.setInterval(check, 30_000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, []);

  const value = useMemo(
    () => ({ info, providers, projects, health, loadError, refreshProjects, refreshProviders }),
    [info, providers, projects, health, loadError, refreshProjects, refreshProviders],
  );
  return <ServerContext.Provider value={value}>{children}</ServerContext.Provider>;
}

// oxlint-disable-next-line react/only-export-components -- the hook belongs with its provider
export function useServer(): ServerValue {
  const value = useContext(ServerContext);
  if (!value) throw new Error("useServer must be used inside <ServerProvider>");
  return value;
}
