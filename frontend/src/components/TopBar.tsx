import { Menu, NotebookPen } from "lucide-react";
import { ModelPicker } from "./ModelPicker";
import { useAppState } from "../lib/AppState";
import { useServer } from "../lib/server";
import styles from "./TopBar.module.css";

interface TopBarProps {
  onOpenNav: () => void;
  memoryOpen: boolean;
  onToggleMemory: () => void;
}

export function TopBar({ onOpenNav, memoryOpen, onToggleMemory }: TopBarProps) {
  const { state, activeConversation } = useAppState();
  const { projects } = useServer();
  const project = projects.find((p) => p.id === state.projectId);
  const place = project ? project.name : "Scratchpad";

  return (
    <header className={styles.bar}>
      <button type="button" className={`icon-btn ${styles.menu}`} onClick={onOpenNav} aria-label="Open projects and chats">
        <Menu size={20} />
      </button>
      <div className={styles.title}>
        <h1>{activeConversation ? activeConversation.title : place}</h1>
        {activeConversation && (
          <p>
            {place}
            {project?.branch && <span className={styles.branch}> · {project.branch}</span>}
          </p>
        )}
      </div>
      <div className={styles.actions}>
        <ModelPicker />
        <button
          type="button"
          className={`btn ${styles.memory}`}
          aria-pressed={memoryOpen}
          onClick={onToggleMemory}
          title={memoryOpen ? "Hide project memory" : "Show project memory"}
        >
          <NotebookPen size={16} />
          <span className={styles.memoryLabel}>Memory</span>
        </button>
      </div>
    </header>
  );
}
