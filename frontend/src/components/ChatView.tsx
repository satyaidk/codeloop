import { useEffect, useRef, useState } from "react";
import { Composer } from "./Composer";
import { EmptyState } from "./EmptyState";
import { MessageItem } from "./MessageItem";
import { useAppState } from "../lib/AppState";
import { useProjectMemory } from "../lib/projectMemory";
import styles from "./ChatView.module.css";

export function ChatView({ onAddProject }: { onAddProject?: () => void }) {
  const { activeConversation, dispatch } = useAppState();
  const { refresh } = useProjectMemory();
  const [draft, setDraft] = useState("");
  const input = useRef<HTMLTextAreaElement>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const stick = useRef(true); // follow new output unless the reader scrolled up

  const messages = activeConversation?.messages ?? [];
  const last = messages.at(-1);
  const running = last?.status === "pending";

  useEffect(() => {
    const el = scroller.current;
    if (el && stick.current) el.scrollTo({ top: el.scrollHeight });
  }, [activeConversation]);

  useEffect(() => {
    stick.current = true;
  }, [activeConversation?.id]);

  // Each finished answer is filed into memory in the background; watch the fact count grow.
  const lastStatus = last?.role === "assistant" ? last.status : undefined;
  useEffect(() => {
    if (lastStatus === "done") refresh(true);
  }, [lastStatus, refresh]);

  return (
    <div className={styles.view}>
      <div
        className={styles.scroll}
        ref={scroller}
        onScroll={(e) => {
          const el = e.currentTarget;
          stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
        }}
      >
        <div className={styles.column}>
          {activeConversation ? (
            <ol className={styles.messages} aria-label="Conversation">
              {messages.map((message) => (
                <MessageItem key={message.id} message={message} />
              ))}
            </ol>
          ) : (
            <EmptyState
              onAddProject={onAddProject}
              onStart={(starter) => {
                dispatch({ type: "setSettings", patch: { mode: starter.mode } });
                setDraft(starter.text);
                window.setTimeout(() => {
                  const el = input.current;
                  el?.focus();
                  el?.setSelectionRange(el.value.length, el.value.length);
                }, 0);
              }}
            />
          )}
        </div>
      </div>
      <Composer ref={input} draft={draft} setDraft={setDraft} running={running} runningId={running ? last?.id : undefined} />
    </div>
  );
}
