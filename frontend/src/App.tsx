import { useEffect, useState } from "react";
import { ChatView } from "./components/ChatView";
import { MemoryPanel } from "./components/MemoryPanel";
import { AddProjectDialog } from "./components/AddProjectDialog";
import { SettingsDialog } from "./components/SettingsDialog";
import { Sidebar } from "./components/Sidebar";
import { TopBar } from "./components/TopBar";
import { useMediaQuery } from "./hooks/useMediaQuery";
import { useTheme } from "./hooks/useTheme";
import { useAppState } from "./lib/AppState";
import { ProjectMemoryProvider } from "./lib/projectMemory";
import { useServer } from "./lib/server";
import styles from "./App.module.css";

export default function App() {
  const { state, dispatch, storageError } = useAppState();
  const { loadError } = useServer();
  useTheme(state.settings.theme);

  const wide = useMediaQuery("(min-width: 1180px)");
  const [navOpen, setNavOpen] = useState(false);
  const [memoryDrawer, setMemoryDrawer] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [addOpen, setAddOpen] = useState(false);

  // On wide screens the memory panel is a column you can hide; on narrow ones it's a drawer.
  const memoryOpen = wide ? state.settings.memoryPanel : memoryDrawer;
  const toggleMemory = () =>
    wide ? dispatch({ type: "setSettings", patch: { memoryPanel: !state.settings.memoryPanel } }) : setMemoryDrawer((o) => !o);

  // Ctrl/Cmd + Shift + O starts a new chat, like most chat apps.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.shiftKey && event.key.toLowerCase() === "o") {
        event.preventDefault();
        dispatch({ type: "selectChat", id: null });
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [dispatch]);

  return (
    <ProjectMemoryProvider>
    <div className={styles.app} data-memory={memoryOpen && wide ? "column" : "hidden"}>
      <div className={styles.nav} data-open={navOpen}>
        <Sidebar
          onNavigate={() => setNavOpen(false)}
          onOpenSettings={() => setSettingsOpen(true)}
          onAddProject={() => setAddOpen(true)}
        />
      </div>
      {navOpen && <button type="button" className={styles.scrim} aria-label="Close menu" onClick={() => setNavOpen(false)} />}

      <main className={styles.main}>
        <TopBar onOpenNav={() => setNavOpen(true)} memoryOpen={memoryOpen} onToggleMemory={toggleMemory} />
        {(loadError || storageError) && (
          <p className={styles.banner} role="alert">
            {loadError ?? storageError}
          </p>
        )}
        <ChatView onAddProject={() => setAddOpen(true)} />
      </main>

      {memoryOpen && (
        <aside className={styles.memory} data-drawer={!wide} aria-label="Project memory">
          <MemoryPanel key={state.projectId ?? "scratch"} onClose={toggleMemory} />
        </aside>
      )}
      {memoryOpen && !wide && (
        <button type="button" className={styles.scrim} aria-label="Close memory" onClick={() => setMemoryDrawer(false)} />
      )}

      <SettingsDialog open={settingsOpen} onClose={() => setSettingsOpen(false)} />
      <AddProjectDialog open={addOpen} onClose={() => setAddOpen(false)} />
    </div>
    </ProjectMemoryProvider>
  );
}
