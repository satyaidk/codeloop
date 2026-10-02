import { forwardRef, useLayoutEffect, useRef } from "react";
import type { ForwardedRef } from "react";
import { ArrowUp, FilePen, NotebookPen, Square, SquareTerminal } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useAppState } from "../lib/AppState";
import { MODE_META } from "../lib/modes";
import { useServer } from "../lib/server";
import type { Mode, Settings, TestMethod } from "../lib/types";
import styles from "./Composer.module.css";

interface ComposerProps {
  draft: string;
  setDraft: (text: string) => void;
  running: boolean;
  runningId?: string;
}

const MODES: Mode[] = ["ask", "write", "debug", "review", "test"];

const PLACEHOLDERS: Record<Mode, string> = {
  ask: "Ask about this project, or paste code…",
  write: "Describe what to build or change…",
  debug: "Paste the error or describe the bug…",
  review: "What to review: “my uncommitted changes”, a file, or pasted code…",
  test: "What to test: a file, a module, or pasted code…",
};

export const Composer = forwardRef(function Composer(
  { draft, setDraft, running, runningId }: ComposerProps,
  forwarded: ForwardedRef<HTMLTextAreaElement>,
) {
  const { state, dispatch, send, stop } = useAppState();
  const { info } = useServer();
  const local = useRef<HTMLTextAreaElement | null>(null);
  const { settings } = state;
  const hasProject = state.projectId !== null;
  const set = (patch: Partial<Settings>) => dispatch({ type: "setSettings", patch });

  // Grow with the text, up to a limit; then scroll.
  useLayoutEffect(() => {
    const el = local.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, window.innerHeight * 0.4)}px`;
  }, [draft]);

  const submit = () => {
    if (running || !draft.trim()) return;
    send(draft);
    setDraft("");
  };

  const methods = info?.test_methods ?? ({} as Record<TestMethod, string>);
  const toggleMethod = (method: TestMethod) => {
    const chosen = settings.testMethods.includes(method)
      ? settings.testMethods.filter((m) => m !== method)
      : [...settings.testMethods, method];
    set({ testMethods: chosen.length ? chosen : [method] });
  };

  return (
    <form
      className={styles.composer}
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      <div className={styles.inner}>
        <div className={styles.tabs} role="radiogroup" aria-label="Mode">
          {MODES.map((mode) => {
            const meta = MODE_META[mode];
            const Icon = meta.icon;
            return (
              <button
                key={mode}
                type="button"
                role="radio"
                aria-checked={settings.mode === mode}
                className={styles.tab}
                title={meta.hint}
                onClick={() => set({ mode })}
              >
                <Icon size={15} />
                {meta.label}
              </button>
            );
          })}
        </div>

        <div className={styles.box} data-mode={settings.mode}>
          {settings.mode === "test" && (
            <div className={styles.methods} role="group" aria-label="Testing methods">
              {(Object.keys(methods) as TestMethod[]).map((method) => (
                <button
                  key={method}
                  type="button"
                  className={styles.method}
                  aria-pressed={settings.testMethods.includes(method)}
                  onClick={() => toggleMethod(method)}
                >
                  {methods[method]}
                </button>
              ))}
            </div>
          )}
          <label htmlFor="composer-input" className="visually-hidden">
            Message
          </label>
          <textarea
            id="composer-input"
            ref={(el) => {
              local.current = el;
              if (typeof forwarded === "function") forwarded(el);
              else if (forwarded) forwarded.current = el;
            }}
            className={styles.input}
            rows={2}
            value={draft}
            placeholder={hasProject ? PLACEHOLDERS[settings.mode] : "Paste code, an error, or a question…"}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                submit();
              }
            }}
          />
          <div className={styles.row}>
            <Switch
              icon={NotebookPen}
              label="Memory"
              on={settings.useMemory}
              tone="memory"
              title="Recall what CodeLoop knows about this project, and save what it learns"
              onToggle={() => set({ useMemory: !settings.useMemory })}
            />
            <Switch
              icon={FilePen}
              label="Edit files"
              on={hasProject && settings.allowEdits}
              disabled={!hasProject}
              title={hasProject ? "Let the agent change files in this project" : "Open a project to allow edits"}
              onToggle={() => set({ allowEdits: !settings.allowEdits })}
            />
            <Switch
              icon={SquareTerminal}
              label="Run commands"
              on={hasProject && settings.allowCommands && info?.commands_enabled !== false}
              disabled={!hasProject || info?.commands_enabled === false}
              title={
                !hasProject
                  ? "Open a project to allow commands"
                  : info?.commands_enabled === false
                    ? "Commands are switched off on the server"
                    : `Let the agent run tests and tools on your computer (${info?.command_allowlist.slice(0, 8).join(", ")}…)`
              }
              onToggle={() => set({ allowCommands: !settings.allowCommands })}
            />
            <span className={styles.spacer} />
            <span className={styles.keys} aria-hidden="true">
              <kbd>Enter</kbd> sends, <kbd>Shift</kbd>+<kbd>Enter</kbd> adds a line
            </span>
            {running ? (
              <button
                type="button"
                className={`btn ${styles.send}`}
                onClick={() => runningId && stop(runningId)}
                aria-label="Stop"
              >
                <Square size={14} fill="currentColor" /> Stop
              </button>
            ) : (
              <button type="submit" className={`btn btn-primary ${styles.send}`} disabled={!draft.trim()} aria-label="Send">
                <ArrowUp size={16} /> Send
              </button>
            )}
          </div>
        </div>
      </div>
    </form>
  );
});

interface SwitchProps {
  icon: LucideIcon;
  label: string;
  on: boolean;
  onToggle: () => void;
  title: string;
  disabled?: boolean;
  tone?: "memory";
}

function Switch({ icon: Icon, label, on, onToggle, title, disabled, tone }: SwitchProps) {
  return (
    <button
      type="button"
      className={styles.switch}
      data-tone={tone}
      aria-pressed={on}
      disabled={disabled}
      title={title}
      onClick={onToggle}
    >
      <Icon size={14} />
      <span>{label}</span>
    </button>
  );
}
