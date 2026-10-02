import { useState } from "react";
import {
  BookmarkPlus,
  ChevronRight,
  CircleAlert,
  FilePen,
  FilePlus,
  FileText,
  FolderTree,
  GitCompare,
  History,
  Info,
  LoaderCircle,
  NotebookPen,
  Search,
  SquareTerminal,
  Wrench,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { duration } from "../lib/format";
import type { Message, Step } from "../lib/types";
import styles from "./Trace.module.css";

const TOOL_ICONS: Record<string, LucideIcon> = {
  recall_memory: History,
  save_note: BookmarkPlus,
  list_files: FolderTree,
  read_file: FileText,
  search_code: Search,
  git_changes: GitCompare,
  edit_file: FilePen,
  write_file: FilePlus,
  run_command: SquareTerminal,
};
const MEMORY_TOOLS = new Set(["recall_memory", "save_note"]);

/** The agent's work for one reply, as a timeline: what it recalled, read, ran and changed. */
export function Trace({ message, now }: { message: Message; now: number }) {
  const steps = message.steps ?? [];
  const running = message.status === "pending";
  const changed = (message.filesChanged?.length ?? 0) > 0;
  const [open, setOpen] = useState<boolean | null>(null);
  const expanded = open ?? (running || changed || message.status === "error");
  if (!steps.length && !running) return null;

  return (
    <div className={styles.trace}>
      {!running && (
        <button type="button" className={styles.summary} aria-expanded={expanded} onClick={() => setOpen(!expanded)}>
          <ChevronRight size={15} className={styles.chevron} />
          {summarize(message)}
        </button>
      )}
      {expanded && (
        <ol className={styles.rail}>
          {steps.map((step) => (
            <StepRow key={step.id} step={step} />
          ))}
          {running && !steps.some((s) => s.kind === "tool" && s.status === "running") && (
            <li className={styles.step} data-kind="working">
              <span className={styles.marker}>
                <LoaderCircle size={13} className="spin" />
              </span>
              <span className={styles.text}>
                {steps.length ? "Thinking" : "Starting"} ({duration(Math.max(0, now - message.createdAt))})
              </span>
            </li>
          )}
        </ol>
      )}
    </div>
  );
}

function StepRow({ step }: { step: Step }) {
  const [showDetail, setShowDetail] = useState(false);

  if (step.kind === "memory") {
    return (
      <li className={styles.step} data-kind="memory">
        <span className={styles.marker}>
          <NotebookPen size={13} />
        </span>
        <div className={styles.body}>
          <button
            type="button"
            className={styles.line}
            aria-expanded={showDetail}
            disabled={!step.notes.length}
            onClick={() => setShowDetail((s) => !s)}
          >
            {!step.available
              ? "Memory unreachable: answering without project notes"
              : step.notes.length
                ? `Recalled ${step.notes.length} ${step.notes.length === 1 ? "note" : "notes"} from project memory`
                : "No relevant notes in memory yet"}
          </button>
          {showDetail && (
            <ul className={styles.notes}>
              {step.notes.map((note) => (
                <li key={note.text}>{note.text}</li>
              ))}
            </ul>
          )}
        </div>
      </li>
    );
  }

  if (step.kind === "thought") {
    return (
      <li className={styles.step} data-kind="thought">
        <span className={styles.marker} />
        <p className={styles.thought}>{step.text}</p>
      </li>
    );
  }

  if (step.kind === "notice") {
    return (
      <li className={styles.step} data-kind="notice">
        <span className={styles.marker}>
          <Info size={13} />
        </span>
        <span className={styles.text}>{step.text}</span>
      </li>
    );
  }

  const Icon = step.status === "failed" ? CircleAlert : (TOOL_ICONS[step.name] ?? Wrench);
  const memoryTool = MEMORY_TOOLS.has(step.name);
  return (
    <li className={styles.step} data-kind={memoryTool ? "memory" : "tool"} data-status={step.status}>
      <span className={styles.marker}>
        {step.status === "running" ? <LoaderCircle size={13} className="spin" /> : <Icon size={13} />}
      </span>
      <div className={styles.body}>
        {step.detail ? (
          <button
            type="button"
            className={styles.line}
            aria-expanded={showDetail}
            onClick={() => setShowDetail((s) => !s)}
          >
            {step.summary ?? step.label}
            <span className={styles.more}>{showDetail ? "Hide" : detailLabel(step.detailKind)}</span>
          </button>
        ) : (
          <span className={styles.text}>{step.status === "running" ? `${step.label}…` : (step.summary ?? step.label)}</span>
        )}
        {showDetail && step.detail && <Detail text={step.detail} kind={step.detailKind} />}
      </div>
    </li>
  );
}

function detailLabel(kind?: string): string {
  if (kind === "diff") return "Show diff";
  if (kind === "notes") return "Show";
  return "Show output";
}

function Detail({ text, kind }: { text: string; kind?: string }) {
  if (kind === "diff") {
    return (
      <pre className={styles.diff}>
        {text.split("\n").map((line, i) => (
          <span key={i} className={styles[lineClass(line)]}>
            {line || " "}
            {"\n"}
          </span>
        ))}
      </pre>
    );
  }
  if (kind === "notes") return <p className={styles.noteDetail}>{text}</p>;
  return <pre className={styles.output}>{text}</pre>;
}

function lineClass(line: string): string {
  if (line.startsWith("+++") || line.startsWith("---")) return "meta";
  if (line.startsWith("@@")) return "hunk";
  if (line.startsWith("+")) return "add";
  if (line.startsWith("-")) return "del";
  return "ctx";
}

/** One sentence for a finished run, e.g. "Recalled 7 notes, used 2 tools and read 1 file". */
function summarize(message: Message): string {
  const steps = message.steps ?? [];
  const memory = steps.find((s) => s.kind === "memory");
  const tools = steps.filter((s) => s.kind === "tool").length;
  const count = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;
  const parts: string[] = [];
  if (memory?.kind === "memory" && memory.notes.length) parts.push(`recalled ${count(memory.notes.length, "note", "notes")}`);
  parts.push(tools ? `used ${count(tools, "tool", "tools")}` : "answered from context");
  if (message.filesRead?.length) parts.push(`read ${count(message.filesRead.length, "file", "files")}`);
  if (message.filesChanged?.length) parts.push(`changed ${count(message.filesChanged.length, "file", "files")}`);
  if (message.notesSaved) parts.push(`saved ${count(message.notesSaved, "note", "notes")}`);
  const sentence = parts.length > 1 ? `${parts.slice(0, -1).join(", ")} and ${parts.at(-1)}` : parts[0];
  return sentence.charAt(0).toUpperCase() + sentence.slice(1);
}
