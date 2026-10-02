import { useEffect, useState } from "react";
import type { CSSProperties } from "react";
import { GitBranch, GitCommitHorizontal, LoaderCircle, RefreshCw } from "lucide-react";
import { api } from "../lib/api";
import { timeAgo } from "../lib/format";
import { MODE_META } from "../lib/modes";
import { useProjectMemory } from "../lib/projectMemory";
import type { Mode, Note } from "../lib/types";
import styles from "./EmptyState.module.css";

interface Starter {
  mode: Mode;
  text: string;
}

const PROJECT_STARTERS: Starter[] = [
  { mode: "ask", text: "How is this project structured, and where does a request go first?" },
  { mode: "review", text: "Review my uncommitted changes." },
  { mode: "debug", text: "This fails with the error below. Find the cause:\n\n" },
  { mode: "test", text: "Write tests for the least-tested module and run them." },
];

const SCRATCH_STARTERS: Starter[] = [
  { mode: "debug", text: "Explain this stack trace and what causes it:\n\n" },
  { mode: "review", text: "Review this function for bugs and edge cases:\n\n" },
  { mode: "test", text: "Write property-based tests for this function:\n\n" },
  { mode: "write", text: "Write a function that " },
];

const FIELD_SIZE = 4; // facts shown on the welcome screen; the memory panel lists them all

export function EmptyState({ onStart, onAddProject }: { onStart: (s: Starter) => void; onAddProject?: () => void }) {
  const { project, scope, status, learned, learning, learnError, learn } = useProjectMemory();
  const starters = project ? PROJECT_STARTERS : SCRATCH_STARTERS;
  const count = status?.notes ?? null;
  const [facts, setFacts] = useState<Note[]>([]);

  // The welcome screen shows what memory actually holds, refreshed as Hindsight files new facts.
  useEffect(() => {
    let alive = true;
    api
      .memories(scope)
      .then((found) => alive && setFacts(found.memories.slice(0, FIELD_SIZE)))
      .catch(() => alive && setFacts([]));
    return () => {
      alive = false;
    };
  }, [scope, count]);

  return (
    <section className={styles.empty}>
      <h2 className={styles.name}>{project ? project.name : "Scratchpad"}</h2>

      {project?.head && (
        <p className={styles.git}>
          <span className={styles.gitItem}>
            <GitBranch size={14} aria-hidden="true" />
            <span className="ident">{project.branch}</span>
          </span>
          <span className={styles.gitItem}>
            <GitCommitHorizontal size={14} aria-hidden="true" />
            <span className="ident">{project.head}</span>
          </span>
          {project.subject && <span className={styles.subject}>{project.subject}</span>}
          {project.committed_at && <span>{timeAgo(project.committed_at)}</span>}
        </p>
      )}

      {!project && (
        <p className={styles.lede}>
          Paste code, an error or a question. Without a project CodeLoop can't read files, but it still remembers your
          preferences from one chat to the next.
          {onAddProject && (
            <>
              {" "}
              <button type="button" className={styles.link} onClick={onAddProject}>
                Add a project
              </button>{" "}
              to let it read, edit and test real code.
            </>
          )}
        </p>
      )}

      {project && (
        <div className={styles.field} data-state={facts.length ? "known" : "empty"}>
          {facts.length > 0 ? (
            <>
              <p className={styles.fieldIntro}>
                CodeLoop remembers <strong>{count ?? facts.length} facts</strong> about {project.name}. Questions start
                here instead of re-reading the code.
              </p>
              <FactList facts={facts} />
              {learned && status?.commits_since ? (
                <p className={styles.stale}>
                  {status.commits_since} new {status.commits_since === 1 ? "commit" : "commits"} since the last scan.
                  <button type="button" className={styles.link} onClick={learn} disabled={learning}>
                    <RefreshCw size={13} aria-hidden="true" /> Scan again
                  </button>
                </p>
              ) : null}
            </>
          ) : learned ? (
            <p className={styles.fieldIntro}>
              <span className={styles.filing} aria-hidden="true" />
              Hindsight is turning the scan into facts. They appear here and in the memory panel over the next few
              minutes.
            </p>
          ) : (
            <>
              <p className={styles.fieldIntro}>
                CodeLoop hasn't learned this project yet. One scan maps its layout, commands and conventions into
                memory, so later questions don't re-read the code.
              </p>
              <button type="button" className="btn btn-memory" onClick={learn} disabled={learning}>
                {learning && <LoaderCircle size={16} className="spin" />}
                {learning ? "Scanning…" : "Learn this project"}
              </button>
            </>
          )}
          {learnError && <p className={styles.error}>{learnError}</p>}
        </div>
      )}

      {!project && facts.length > 0 && (
        <div className={styles.field} data-state="known">
          <p className={styles.fieldIntro}>What CodeLoop remembers about you:</p>
          <FactList facts={facts} />
        </div>
      )}

      <ul className={styles.starters} aria-label="Ways to start">
        {starters.map((starter) => {
          const meta = MODE_META[starter.mode];
          const Icon = meta.icon;
          return (
            <li key={starter.text}>
              <button type="button" onClick={() => onStart(starter)}>
                <span className={styles.mode}>
                  <Icon size={15} />
                  {meta.label}
                </span>
                <span className={styles.prompt}>{starter.text.trim()}</span>
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/** Facts surface one after another, like a recall: the amber mark lights, then the words come into focus. */
function FactList({ facts }: { facts: Note[] }) {
  return (
    <ol className={styles.facts}>
      {facts.map((fact, i) => (
        <li key={fact.text} style={{ "--i": i } as CSSProperties}>
          <span className={styles.mark} aria-hidden="true" />
          <span className={styles.fact}>{fact.text}</span>
        </li>
      ))}
    </ol>
  );
}
