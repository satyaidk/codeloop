import { useCallback, useEffect, useState } from "react";
import { LoaderCircle, RefreshCw, ScrollText, Search, X } from "lucide-react";
import { Dialog } from "./Dialog";
import { api } from "../lib/api";
import { useAppState } from "../lib/AppState";
import { timeAgo } from "../lib/format";
import { useProjectMemory } from "../lib/projectMemory";
import type { Brief, Note } from "../lib/types";
import styles from "./MemoryPanel.module.css";

const TYPE_LABEL: Record<string, string> = { world: "Fact", experience: "Session", observation: "Pattern" };

export function MemoryPanel({ onClose }: { onClose: () => void }) {
  const { dispatch } = useAppState();
  const { project, scope, status, learned, learning, learnError, learn, refresh } = useProjectMemory();
  const [query, setQuery] = useState("");
  const [notes, setNotes] = useState<Note[] | null>(null);
  const [total, setTotal] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [brief, setBrief] = useState<Brief | null>(null);
  const [briefing, setBriefing] = useState(false);
  const [briefError, setBriefError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);

  const load = useCallback(
    async (q: string) => {
      setLoading(true);
      try {
        const found = await api.memories(scope, q || undefined);
        setNotes(found.memories);
        setTotal(found.total);
        setError(null);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setLoading(false);
      }
    },
    [scope],
  );

  // Search as you type, after a short pause. The list also reloads when the fact count changes,
  // because Hindsight files new facts in the background.
  const count = status?.notes;
  useEffect(() => {
    const timer = window.setTimeout(() => void load(query.trim()), query ? 400 : 0);
    return () => window.clearTimeout(timer);
  }, [query, load, count]);

  const getBrief = async () => {
    setBriefing(true);
    setBriefError(null);
    try {
      setBrief(await api.brief(scope));
    } catch (e) {
      setBriefError(e instanceof Error ? e.message : String(e));
    } finally {
      setBriefing(false);
    }
  };

  const forget = async () => {
    await api.forget(scope);
    if (project) dispatch({ type: "forgotProject", projectId: project.id });
    setConfirming(false);
    setBrief(null);
    refresh();
    void load("");
  };

  const shown = status?.notes ?? total;
  return (
    <div className={styles.panel}>
      <header className={styles.header}>
        <h2>{project ? "Project memory" : "Scratchpad memory"}</h2>
        <button type="button" className="icon-btn" onClick={onClose} aria-label="Close memory">
          <X size={18} />
        </button>
      </header>

      <div className={styles.scroll}>
        <section className={styles.status}>
          <p className={styles.count}>
            {shown === null || shown === undefined ? (
              "Memory is unreachable right now."
            ) : (
              <>
                <strong>{shown}</strong> {shown === 1 ? "fact" : "facts"} about {project ? project.name : "you"}
              </>
            )}
          </p>
          {project && (
            <>
              <p className={styles.sub}>
                {learned
                  ? `Scanned ${timeAgo(learned.at)}${learned.head ? ` at ${learned.head}` : ""}${
                      status?.commits_since ? `, ${status.commits_since} commits ago` : ""
                    }.`
                  : "Not scanned yet. A scan maps the layout, commands and conventions in one go."}
              </p>
              <button type="button" className="btn btn-memory" onClick={learn} disabled={learning}>
                {learning ? <LoaderCircle size={15} className="spin" /> : <RefreshCw size={15} />}
                {learning ? "Scanning…" : learned ? "Scan again" : "Learn this project"}
              </button>
              {learnError && <p className={styles.error}>{learnError}</p>}
            </>
          )}
          <p className={styles.sub}>New facts appear a minute or so after each chat, while Hindsight files them.</p>
        </section>

        <section className={styles.section}>
          <div className={styles.sectionHead}>
            <h3>Brief</h3>
            <button type="button" className="btn" onClick={getBrief} disabled={briefing}>
              {briefing ? <LoaderCircle size={15} className="spin" /> : <ScrollText size={15} />}
              {brief ? "Refresh" : "Brief me"}
            </button>
          </div>
          {briefError && <p className={styles.error}>{briefError}</p>}
          {!brief && !briefError && (
            <p className={styles.sub}>A summary of everything memory holds: stack, structure, commands and open issues.</p>
          )}
          {brief && <BriefView brief={brief} />}
        </section>

        <section className={styles.section}>
          <div className={styles.sectionHead}>
            <h3>Notes</h3>
            <button type="button" className="icon-btn" onClick={() => void load(query.trim())} aria-label="Reload notes">
              <RefreshCw size={15} className={loading ? "spin" : undefined} />
            </button>
          </div>
          <label className={styles.search}>
            <Search size={15} aria-hidden="true" />
            <span className="visually-hidden">Search notes</span>
            <input
              className="input"
              type="search"
              placeholder="Search by meaning, e.g. how tests run"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </label>
          {error && <p className={styles.error}>{error}</p>}
          {notes && notes.length === 0 && !error && (
            <p className={styles.sub}>{query ? "No notes match that." : "Nothing stored yet."}</p>
          )}
          <ul className={styles.notes}>
            {notes?.map((note) => (
              <li key={note.text}>
                <p>{note.text}</p>
                <span className={styles.noteMeta}>
                  {note.type && TYPE_LABEL[note.type] ? TYPE_LABEL[note.type] : "Note"}
                  {note.occurred_at && ` · ${timeAgo(note.occurred_at)}`}
                </span>
              </li>
            ))}
          </ul>
        </section>

        <section className={styles.danger}>
          <button type="button" className="btn btn-danger" onClick={() => setConfirming(true)}>
            {project ? "Forget this project" : "Forget scratchpad notes"}
          </button>
        </section>
      </div>

      <Dialog open={confirming} onClose={() => setConfirming(false)} title="Forget everything?">
        <p className={styles.confirmText}>
          This deletes every fact CodeLoop has stored about {project ? project.name : "your scratchpad chats"}. Your chats
          and code aren't touched, and you can scan the project again later.
        </p>
        <div className={styles.confirmActions}>
          <button type="button" className="btn" onClick={() => setConfirming(false)}>
            Keep memory
          </button>
          <button type="button" className="btn btn-danger" onClick={forget}>
            Forget everything
          </button>
        </div>
      </Dialog>
    </div>
  );
}

function BriefView({ brief }: { brief: Brief }) {
  const lists: [string, string[], boolean][] = [
    ["Stack", brief.stack, false],
    ["Structure", brief.structure, false],
    ["Commands", brief.commands, true],
    ["Conventions", brief.conventions, false],
    ["Open issues", brief.open_issues, false],
  ];
  return (
    <div className={styles.brief}>
      <p>{brief.summary}</p>
      {lists
        .filter(([, items]) => items.length)
        .map(([title, items, code]) => (
          <div key={title}>
            <h4>{title}</h4>
            <ul>
              {items.map((item) => (
                <li key={item}>{code ? <code>{item}</code> : item}</li>
              ))}
            </ul>
          </div>
        ))}
    </div>
  );
}
