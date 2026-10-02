import { useMemo, useState } from "react";
import { FolderGit2, FolderOpen, MessageSquare, Pencil, Plus, Settings, Trash2 } from "lucide-react";
import { LoopMark } from "./LoopMark";
import { useAppState } from "../lib/AppState";
import { dayGroup } from "../lib/format";
import { useServer } from "../lib/server";
import type { Conversation } from "../lib/types";
import styles from "./Sidebar.module.css";

interface SidebarProps {
  onNavigate: () => void;
  onOpenSettings: () => void;
  onAddProject: () => void;
}

const HEALTH_TEXT = {
  checking: "Connecting…",
  ok: "Memory connected",
  "no-memory": "Memory offline: answers won't be personal",
  offline: "Server offline",
} as const;

export function Sidebar({ onNavigate, onOpenSettings, onAddProject }: SidebarProps) {
  const { state, dispatch } = useAppState();
  const { projects, health } = useServer();
  const current = projects.find((p) => p.id === state.projectId);

  const chats = useMemo(() => {
    const mine = state.conversations
      .filter((c) => c.projectId === state.projectId)
      .sort((a, b) => b.updatedAt - a.updatedAt);
    const groups = new Map<string, Conversation[]>();
    for (const chat of mine) {
      const group = dayGroup(chat.updatedAt);
      groups.set(group, [...(groups.get(group) ?? []), chat]);
    }
    return [...groups.entries()];
  }, [state.conversations, state.projectId]);

  const pick = (projectId: string | null) => {
    dispatch({ type: "selectProject", projectId });
    onNavigate();
  };

  return (
    <nav className={styles.sidebar} aria-label="Projects and chats">
      <div className={styles.brand}>
        <LoopMark size={26} />
        <span>CodeLoop</span>
      </div>

      <button
        type="button"
        className={`btn ${styles.newChat}`}
        onClick={() => {
          dispatch({ type: "selectChat", id: null });
          onNavigate();
        }}
      >
        <Plus size={16} /> New chat
      </button>

      <section className={styles.section}>
        <div className={styles.sectionHead}>
          <h2>Projects</h2>
          <button type="button" className="icon-btn" onClick={onAddProject} aria-label="Add a project">
            <Plus size={16} />
          </button>
        </div>
        <ul className={styles.list}>
          <li>
            <button
              type="button"
              className={styles.project}
              aria-current={state.projectId === null ? "true" : undefined}
              onClick={() => pick(null)}
            >
              <MessageSquare size={16} />
              <span className={styles.projectName}>Scratchpad</span>
              <span className={styles.meta}>no project</span>
            </button>
          </li>
          {projects.map((project) => (
            <li key={project.id}>
              <button
                type="button"
                className={styles.project}
                aria-current={state.projectId === project.id ? "true" : undefined}
                onClick={() => pick(project.id)}
                title={project.name}
              >
                {project.is_git ? <FolderGit2 size={16} /> : <FolderOpen size={16} />}
                <span className={styles.projectName}>{project.name}</span>
                {project.branch && <span className={`${styles.meta} ${styles.branch}`}>{project.branch}</span>}
              </button>
            </li>
          ))}
        </ul>
        {projects.length === 0 && (
          <p className={styles.hint}>
            No projects yet.{" "}
            <button type="button" onClick={onAddProject}>
              Add one
            </button>{" "}
            so CodeLoop can read its code.
          </p>
        )}
      </section>

      <section className={`${styles.section} ${styles.chats}`}>
        <div className={styles.sectionHead}>
          <h2>{current ? `Chats in ${current.name}` : "Scratchpad chats"}</h2>
        </div>
        {chats.length === 0 && <p className={styles.hint}>Your chats appear here. They're saved in this browser.</p>}
        {chats.map(([group, list]) => (
          <div key={group}>
            <h3 className={styles.group}>{group}</h3>
            <ul className={styles.list}>
              {list.map((chat) => (
                <ChatRow
                  key={chat.id}
                  chat={chat}
                  active={chat.id === state.activeId}
                  onOpen={() => {
                    dispatch({ type: "selectChat", id: chat.id });
                    onNavigate();
                  }}
                />
              ))}
            </ul>
          </div>
        ))}
      </section>

      <footer className={styles.footer}>
        <span className={styles.health} data-health={health}>
          <span className={styles.dot} aria-hidden="true" />
          {HEALTH_TEXT[health]}
        </span>
        <button type="button" className="icon-btn" onClick={onOpenSettings} aria-label="Settings">
          <Settings size={18} />
        </button>
      </footer>
    </nav>
  );
}

function ChatRow({ chat, active, onOpen }: { chat: Conversation; active: boolean; onOpen: () => void }) {
  const { dispatch } = useAppState();
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(chat.title);

  if (editing) {
    const save = () => {
      dispatch({ type: "renameChat", id: chat.id, title });
      setEditing(false);
    };
    return (
      <li>
        <input
          className={`input ${styles.rename}`}
          value={title}
          aria-label="Chat name"
          autoFocus
          onChange={(e) => setTitle(e.target.value)}
          onBlur={save}
          onKeyDown={(e) => {
            if (e.key === "Enter") save();
            if (e.key === "Escape") setEditing(false);
          }}
        />
      </li>
    );
  }

  return (
    <li className={styles.chatRow}>
      <button
        type="button"
        className={styles.chat}
        aria-current={active ? "true" : undefined}
        onClick={onOpen}
        title={chat.title}
      >
        {chat.title}
      </button>
      <span className={styles.rowActions}>
        <button
          type="button"
          className="icon-btn"
          aria-label={`Rename ${chat.title}`}
          onClick={() => {
            setTitle(chat.title);
            setEditing(true);
          }}
        >
          <Pencil size={14} />
        </button>
        <button
          type="button"
          className="icon-btn"
          aria-label={`Delete ${chat.title}`}
          onClick={() => dispatch({ type: "deleteChat", id: chat.id })}
        >
          <Trash2 size={14} />
        </button>
      </span>
    </li>
  );
}
