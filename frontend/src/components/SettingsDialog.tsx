import { useState } from "react";
import { Monitor, Moon, Sun } from "lucide-react";
import { Dialog } from "./Dialog";
import { useAppState } from "../lib/AppState";
import { useServer } from "../lib/server";
import type { Theme } from "../lib/types";
import styles from "./Forms.module.css";

const THEMES: { value: Theme; label: string; icon: typeof Sun }[] = [
  { value: "system", label: "Match system", icon: Monitor },
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
];

export function SettingsDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { state, dispatch } = useAppState();
  const { info } = useServer();
  const [cleared, setCleared] = useState(false);
  const { settings } = state;
  const maxHistory = info?.max_history_messages ?? 40;

  return (
    <Dialog open={open} onClose={onClose} title="Settings">
      <div className={styles.form}>
        <fieldset className={styles.field}>
          <legend>Theme</legend>
          <div className={styles.segmented}>
            {THEMES.map(({ value, label, icon: Icon }) => (
              <button
                key={value}
                type="button"
                aria-pressed={settings.theme === value}
                onClick={() => dispatch({ type: "setSettings", patch: { theme: value } })}
              >
                <Icon size={15} /> {label}
              </button>
            ))}
          </div>
        </fieldset>

        <div className={styles.field}>
          <label htmlFor="history-length">Recent messages sent with each question</label>
          <div className={styles.range}>
            <input
              id="history-length"
              type="range"
              min={0}
              max={maxHistory}
              step={2}
              value={Math.min(settings.historyLength, maxHistory)}
              onChange={(e) => dispatch({ type: "setSettings", patch: { historyLength: Number(e.target.value) } })}
            />
            <output htmlFor="history-length">{Math.min(settings.historyLength, maxHistory)}</output>
          </div>
          <p className={styles.note}>
            This is the chat's short-term memory. Fewer messages use fewer tokens; long-term memory covers the rest.
          </p>
        </div>

        {info && (
          <div className={styles.aside}>
            <h3>Server</h3>
            <dl className={styles.facts}>
              <dt>Workspace</dt>
              <dd>
                <code className={styles.path}>{info.workspace_root}</code>
              </dd>
              <dt>Tool steps per question</dt>
              <dd>{info.max_steps}</dd>
              <dt>Programs the agent may run</dt>
              <dd>{info.commands_enabled ? info.command_allowlist.join(", ") : "Running commands is switched off"}</dd>
              <dt>Version</dt>
              <dd>{info.version}</dd>
            </dl>
            <p className={styles.note}>Change these in the server's .env file.</p>
          </div>
        )}

        <div className={styles.aside}>
          <h3>Chats</h3>
          <p className={styles.note}>
            Chats are stored in this browser only. Deleting them doesn't touch project memory; use “Forget” in the memory
            panel for that.
          </p>
          <button
            type="button"
            className="btn btn-danger"
            disabled={!state.conversations.length}
            onClick={() => {
              dispatch({ type: "clearChats" });
              setCleared(true);
            }}
          >
            Delete all chats
          </button>
          {cleared && <p className={styles.note}>All chats deleted.</p>}
        </div>
      </div>
    </Dialog>
  );
}
