// The app's state (chats, settings), the actions that talk to the agent, and saving to the browser.

import { createContext, useCallback, useContext, useEffect, useMemo, useReducer, useRef, useState } from "react";
import type { Dispatch, ReactNode } from "react";
import { api } from "./api";
import { reducer, newId, shortTermHistory, titleFrom } from "./state";
import type { Action } from "./state";
import { loadState, saveState } from "./storage";
import { useServer } from "./server";
import type { AgentEvent, AppData, Conversation, Message, Provider } from "./types";

interface AppStateValue {
  state: AppData;
  dispatch: Dispatch<Action>;
  activeConversation: Conversation | null;
  provider: Provider | null; // the provider new questions go to
  model: string;
  storageError: string | null;
  send: (text: string) => void;
  retry: (replyId: string) => void;
  stop: (replyId: string) => void;
}

const AppStateContext = createContext<AppStateValue | null>(null);

export function AppStateProvider({ children, initial }: { children: ReactNode; initial?: AppData }) {
  const [state, dispatch] = useReducer(reducer, initial, (init) => init ?? loadState());
  const [storageError, setStorageError] = useState<string | null>(null);
  const { info, providers } = useServer();
  const stateRef = useRef(state);
  const controllers = useRef(new Map<string, AbortController>());

  const providerId = state.settings.provider || info?.default_provider || "ollama";
  const provider = providers.find((p) => p.id === providerId) ?? null;
  const model = state.settings.models[providerId] || provider?.default_model || "";
  const target = useRef({ providerId, model });
  useEffect(() => {
    target.current = { providerId, model };
  }, [providerId, model]);

  // Save to the browser shortly after each change (a streaming reply changes the state many times).
  useEffect(() => {
    stateRef.current = state;
    const timer = window.setTimeout(() => setStorageError(saveState(state)), 250);
    return () => window.clearTimeout(timer);
  }, [state]);
  useEffect(() => {
    const flush = () => saveState(stateRef.current);
    window.addEventListener("beforeunload", flush);
    return () => window.removeEventListener("beforeunload", flush);
  }, []);

  /** Runs the agent for one question and fills in the pending reply as events stream in. */
  const ask = useCallback(
    async (conversation: Conversation | undefined, conversationId: string, reply: Message, question: Message) => {
      const { settings } = stateRef.current;
      const controller = new AbortController();
      controllers.current.set(reply.id, controller);
      const before = conversation ? conversation.messages.slice(0, conversation.messages.indexOf(question)) : [];
      let finished = false;
      const onEvent = (event: AgentEvent) => {
        if (event.type === "answer" || event.type === "error") finished = true;
        dispatch({ type: "agentEvent", conversationId, messageId: reply.id, event });
      };
      try {
        await api.runAgent(
          {
            project_id: (conversation?.projectId ?? stateRef.current.projectId) || null,
            message: question.content,
            history: shortTermHistory(before, settings.historyLength),
            mode: question.mode ?? "ask",
            test_methods: question.testMethods ?? [],
            provider: target.current.providerId,
            model: target.current.model || null,
            use_memory: settings.useMemory,
            allow_edits: settings.allowEdits,
            allow_commands: settings.allowCommands,
          },
          onEvent,
          controller.signal,
        );
        if (!finished) {
          onEvent({ type: "error", message: "The connection closed before the answer arrived. Try again." });
        }
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") {
          dispatch({ type: "updateMessage", conversationId, messageId: reply.id, patch: { status: "stopped" } });
        } else {
          onEvent({ type: "error", message: error instanceof Error ? error.message : String(error) });
        }
      } finally {
        controllers.current.delete(reply.id);
      }
    },
    [],
  );

  const send = useCallback(
    (text: string) => {
      const content = text.trim();
      if (!content) return;
      const { activeId, conversations, projectId, settings } = stateRef.current;
      const conversation = conversations.find((c) => c.id === activeId);
      const conversationId = conversation?.id ?? newId();
      const now = Date.now();
      const question: Message = {
        id: newId(),
        role: "user",
        content,
        createdAt: now,
        mode: settings.mode,
        testMethods: settings.mode === "test" ? settings.testMethods : undefined,
      };
      const reply: Message = { id: newId(), role: "assistant", content: "", createdAt: now, status: "pending", steps: [] };
      dispatch({
        type: "sendMessage",
        conversationId,
        projectId: conversation?.projectId ?? projectId,
        title: titleFrom(content),
        userMessage: question,
        pendingReply: reply,
        now,
      });
      const withQuestion = conversation
        ? { ...conversation, messages: [...conversation.messages, question] }
        : { id: conversationId, title: "", projectId, messages: [question], createdAt: now, updatedAt: now };
      void ask(withQuestion, conversationId, reply, question);
    },
    [ask],
  );

  const retry = useCallback(
    (replyId: string) => {
      const conversation = stateRef.current.conversations.find((c) => c.messages.some((m) => m.id === replyId));
      if (!conversation) return;
      const index = conversation.messages.findIndex((m) => m.id === replyId);
      const question = conversation.messages[index - 1];
      if (!question || question.role !== "user") return;
      const reset: Partial<Message> = {
        status: "pending",
        content: "",
        error: undefined,
        steps: [],
        usage: undefined,
        filesRead: undefined,
        filesChanged: undefined,
        createdAt: Date.now(),
      };
      dispatch({ type: "updateMessage", conversationId: conversation.id, messageId: replyId, patch: reset });
      void ask(conversation, conversation.id, { ...conversation.messages[index], ...reset } as Message, question);
    },
    [ask],
  );

  const stop = useCallback((replyId: string) => controllers.current.get(replyId)?.abort(), []);

  const activeConversation = state.conversations.find((c) => c.id === state.activeId) ?? null;
  const value = useMemo<AppStateValue>(
    () => ({ state, dispatch, activeConversation, provider, model, storageError, send, retry, stop }),
    [state, activeConversation, provider, model, storageError, send, retry, stop],
  );
  return <AppStateContext.Provider value={value}>{children}</AppStateContext.Provider>;
}

// oxlint-disable-next-line react/only-export-components -- the hook belongs with its provider
export function useAppState(): AppStateValue {
  const value = useContext(AppStateContext);
  if (!value) throw new Error("useAppState must be used inside <AppStateProvider>");
  return value;
}
