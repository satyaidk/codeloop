import { useEffect, useRef, useState } from "react";
import { ChevronDown, Cloud, Laptop, RefreshCw } from "lucide-react";
import { useAppState } from "../lib/AppState";
import { useServer } from "../lib/server";
import type { Provider } from "../lib/types";
import styles from "./ModelPicker.module.css";

/** Status of a provider in plain words: can questions go to it right now? */
function providerState(provider: Provider): { ready: boolean; text: string } {
  if (!provider.configured) return { ready: false, text: "Not set up" };
  if (provider.installed === false) return { ready: false, text: provider.id === "ollama" ? "Not running" : "Not answering" };
  return { ready: true, text: provider.local ? "On this computer" : "Ready" };
}

export function ModelPicker() {
  const { state, dispatch, provider, model } = useAppState();
  const { providers, refreshProviders } = useServer();
  const [open, setOpen] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onClick = (event: MouseEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const current = provider ? providerState(provider) : { ready: false, text: "Loading" };
  const choose = (id: string) => dispatch({ type: "setSettings", patch: { provider: id } });
  const setModel = (value: string) =>
    provider && dispatch({ type: "setSettings", patch: { models: { ...state.settings.models, [provider.id]: value } } });

  return (
    <div className={styles.picker} ref={root}>
      <button
        type="button"
        className={`btn ${styles.trigger}`}
        aria-expanded={open}
        aria-haspopup="dialog"
        onClick={() => setOpen((o) => !o)}
        title="Choose the model"
      >
        <span className={styles.dot} data-ready={current.ready} aria-hidden="true" />
        <span className={styles.triggerText}>
          <span className={styles.providerName}>{provider?.label ?? "Model"}</span>
          <span className={styles.modelName}>{model || "…"}</span>
        </span>
        <ChevronDown size={15} />
      </button>

      {open && (
        <div className={styles.popover} role="dialog" aria-label="Choose a model">
          <div className={styles.head}>
            <h2>Model provider</h2>
            <button
              type="button"
              className="icon-btn"
              aria-label="Check providers again"
              onClick={async () => {
                setRefreshing(true);
                await refreshProviders().finally(() => setRefreshing(false));
              }}
            >
              <RefreshCw size={15} className={refreshing ? "spin" : undefined} />
            </button>
          </div>
          <ul className={styles.providers}>
            {providers.map((p) => {
              const s = providerState(p);
              return (
                <li key={p.id}>
                  <button
                    type="button"
                    className={styles.provider}
                    aria-pressed={p.id === provider?.id}
                    onClick={() => choose(p.id)}
                  >
                    {p.local ? <Laptop size={15} /> : <Cloud size={15} />}
                    <span className={styles.providerLabel}>{p.label}</span>
                    <span className={styles.state} data-ready={s.ready}>
                      {s.text}
                    </span>
                  </button>
                  {p.id === provider?.id && !s.ready && <p className={styles.hint}>{p.hint}</p>}
                </li>
              );
            })}
          </ul>

          {provider && (
            <div className={styles.modelBox}>
              <label htmlFor="model-input">Model</label>
              <input
                id="model-input"
                className="input"
                list="model-options"
                value={model}
                spellCheck={false}
                onChange={(e) => setModel(e.target.value)}
              />
              <datalist id="model-options">
                {provider.models.map((m) => (
                  <option key={m} value={m} />
                ))}
              </datalist>
              <div className={styles.chips}>
                {provider.models.slice(0, 8).map((m) => (
                  <button
                    key={m}
                    type="button"
                    className={styles.chip}
                    aria-pressed={m === model}
                    onClick={() => setModel(m)}
                  >
                    {m}
                  </button>
                ))}
              </div>
              <p className={styles.note}>
                {provider.local
                  ? "Runs on this computer: your code never leaves it."
                  : "Hosted: the code the agent reads is sent to this provider."}
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
