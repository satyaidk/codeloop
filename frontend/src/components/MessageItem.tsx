import { Suspense, lazy, useState } from "react";
import { Check, Coins, Copy, Cpu, RotateCcw, Timer } from "lucide-react";
import { Trace } from "./Trace";
import { useNow } from "../hooks/useNow";
import { useAppState } from "../lib/AppState";
import { duration, tokens } from "../lib/format";
import { MODE_META } from "../lib/modes";
import type { Message } from "../lib/types";
import styles from "./MessageItem.module.css";

// The Markdown renderer and code highlighter are the biggest part of the app; load them on first use.
const Markdown = lazy(() => import("./Markdown").then((m) => ({ default: m.Markdown })));

export function MessageItem({ message }: { message: Message }) {
  return message.role === "user" ? <Question message={message} /> : <Reply message={message} />;
}

function Question({ message }: { message: Message }) {
  const mode = message.mode && message.mode !== "ask" ? MODE_META[message.mode] : null;
  return (
    <li className={styles.question}>
      {mode && (
        <span className={styles.modeTag}>
          <mode.icon size={13} />
          {mode.label}
        </span>
      )}
      <div className={styles.bubble}>{message.content}</div>
    </li>
  );
}

function Reply({ message }: { message: Message }) {
  const { retry } = useAppState();
  const running = message.status === "pending";
  const now = useNow(running);
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    await navigator.clipboard?.writeText(message.content);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  };

  return (
    <li className={styles.reply} aria-busy={running}>
      <Trace message={message} now={now} />

      {message.content && (
        <Suspense fallback={<p className={styles.plain}>{message.content}</p>}>
          <Markdown text={message.content} />
        </Suspense>
      )}

      {message.status === "error" && (
        <div className={styles.problem} role="alert">
          <p>{message.error}</p>
          <button type="button" className="btn" onClick={() => retry(message.id)}>
            <RotateCcw size={15} /> Try again
          </button>
        </div>
      )}

      {message.status === "stopped" && (
        <div className={styles.stopped}>
          <p>Stopped before the answer was finished.</p>
          <button type="button" className="btn" onClick={() => retry(message.id)}>
            <RotateCcw size={15} /> Try again
          </button>
        </div>
      )}

      {message.status === "done" && (
        <footer className={styles.footer}>
          <span className={styles.stats}>
            {message.model && (
              <span className={styles.stat}>
                <Cpu size={13} aria-hidden="true" />
                <span className="ident">{message.model}</span>
              </span>
            )}
            {message.usage && (
              <span className={styles.stat} title="Tokens sent to and received from the model, across every step">
                <Coins size={13} aria-hidden="true" />
                {tokens(message.usage.input)} in
                {message.usage.cached > 0 && <> ({tokens(message.usage.cached)} cached)</>}, {tokens(message.usage.output)} out
              </span>
            )}
            {message.elapsedMs !== undefined && (
              <span className={styles.stat}>
                <Timer size={13} aria-hidden="true" />
                {duration(message.elapsedMs)}
              </span>
            )}
          </span>
          <span className={styles.actions}>
            <button type="button" className="icon-btn" onClick={copy} aria-label="Copy answer">
              {copied ? <Check size={15} /> : <Copy size={15} />}
            </button>
            <button type="button" className="icon-btn" onClick={() => retry(message.id)} aria-label="Regenerate answer">
              <RotateCcw size={15} />
            </button>
          </span>
        </footer>
      )}
    </li>
  );
}
