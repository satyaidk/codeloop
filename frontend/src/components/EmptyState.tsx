import { LoaderCircle } from "lucide-react";
import { timeAgo } from "../lib/format";
import { MODE_META } from "../lib/modes";
import { useProjectMemory } from "../lib/projectMemory";
import type { Mode } from "../lib/types";
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

export function EmptyState({ onStart, onAddProject }: { onStart: (s: Starter) => void; onAddProject?: () => void }) {
  const { project, status, learned, learning, learnError, learn } = useProjectMemory();
  const starters = project ? PROJECT_STARTERS : SCRATCH_STARTERS;
  const notes = status?.notes ?? null;

  return (
    <section className={styles.empty}>
      <h2 className={styles.name}>{project ? project.name : "Scratchpad"}</h2>

      {project ? (
        <>
          {project.head && (
            <p className={styles.git}>
              <span className={styles.mono}>{project.branch}</span> at <span className={styles.mono}>{project.head}</span>
              {project.subject && <> · {project.subject}</>}
              {project.committed_at && <> · {timeAgo(project.committed_at)}</>}
            </p>
          )}
          <div className={styles.memory}>
            {notes && notes > 0 ? (
              <>
                <p>
                  CodeLoop knows <strong>{notes} facts</strong> about this project, so questions start from memory instead of
                  re-reading the code.
                </p>
                {learned && (
                  <p className={styles.learned}>
                    Scanned {timeAgo(learned.at)}
                    {status?.commits_since ? `; ${status.commits_since} new commits since then.` : "."}
                    {status?.commits_since ? (
                      <button type="button" className={styles.link} onClick={learn} disabled={learning}>
                        Scan again
                      </button>
                    ) : null}
                  </p>
                )}
              </>
            ) : (
              <>
                <p>
                  {learned
                    ? "Hindsight is turning the scan into facts. They appear in the memory panel over the next minute or two."
                    : "CodeLoop hasn't learned this project yet. One scan maps its layout, commands and conventions into memory, so later questions don't re-read the code."}
                </p>
                {!learned && (
                  <button type="button" className="btn btn-memory" onClick={learn} disabled={learning}>
                    {learning && <LoaderCircle size={16} className="spin" />}
                    {learning ? "Scanning…" : "Learn this project"}
                  </button>
                )}
              </>
            )}
            {learnError && <p className={styles.error}>{learnError}</p>}
          </div>
        </>
      ) : (
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

      <ul className={styles.starters} aria-label="Ways to start">
        {starters.map((starter) => {
          const meta = MODE_META[starter.mode];
          const Icon = meta.icon;
          return (
            <li key={starter.text}>
              <button type="button" onClick={() => onStart(starter)}>
                <span className={styles.mode} data-mode={starter.mode}>
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
