// Every change to the web app's data goes through this one reducer, so the rules live in one place.

import { applyAgentEvent } from "./events";
import type { AgentEvent, AppData, Conversation, Learned, Message, Settings } from "./types";

export type Action =
  | { type: "setSettings"; patch: Partial<Settings> }
  | { type: "selectProject"; projectId: string | null }
  | { type: "selectChat"; id: string | null }
  | { type: "renameChat"; id: string; title: string }
  | { type: "deleteChat"; id: string }
  | { type: "clearChats" }
  | {
      type: "sendMessage";
      conversationId: string;
      projectId: string | null;
      title: string;
      userMessage: Message;
      pendingReply: Message;
      now: number;
    }
  | { type: "updateMessage"; conversationId: string; messageId: string; patch: Partial<Message> }
  | { type: "agentEvent"; conversationId: string; messageId: string; event: AgentEvent }
  | { type: "learned"; projectId: string; learned: Learned }
  | { type: "forgotProject"; projectId: string };

export function reducer(state: AppData, action: Action): AppData {
  switch (action.type) {
    case "setSettings":
      return { ...state, settings: { ...state.settings, ...action.patch } };
    case "selectProject":
      return { ...state, projectId: action.projectId, activeId: null };
    case "selectChat": {
      const chat = state.conversations.find((c) => c.id === action.id);
      return { ...state, activeId: action.id, projectId: chat ? chat.projectId : state.projectId };
    }
    case "renameChat":
      return mapChat(state, action.id, (c) => ({ ...c, title: action.title.trim() || c.title }));
    case "deleteChat":
      return {
        ...state,
        conversations: state.conversations.filter((c) => c.id !== action.id),
        activeId: state.activeId === action.id ? null : state.activeId,
      };
    case "clearChats":
      return { ...state, conversations: [], activeId: null };
    case "sendMessage": {
      const existing = state.conversations.find((c) => c.id === action.conversationId);
      const conversation: Conversation = existing
        ? {
            ...existing,
            messages: [...existing.messages, action.userMessage, action.pendingReply],
            updatedAt: action.now,
          }
        : {
            id: action.conversationId,
            title: action.title,
            projectId: action.projectId,
            messages: [action.userMessage, action.pendingReply],
            createdAt: action.now,
            updatedAt: action.now,
          };
      const others = state.conversations.filter((c) => c.id !== action.conversationId);
      return { ...state, conversations: [conversation, ...others], activeId: action.conversationId };
    }
    case "updateMessage":
      return mapMessage(state, action.conversationId, action.messageId, (m) => ({ ...m, ...action.patch }));
    case "agentEvent":
      return mapMessage(state, action.conversationId, action.messageId, (m) => applyAgentEvent(m, action.event));
    case "learned":
      return { ...state, learned: { ...state.learned, [action.projectId]: action.learned } };
    case "forgotProject": {
      const learned = { ...state.learned };
      delete learned[action.projectId];
      return { ...state, learned };
    }
    default:
      return state;
  }
}

function mapChat(state: AppData, id: string, change: (c: Conversation) => Conversation): AppData {
  return { ...state, conversations: state.conversations.map((c) => (c.id === id ? change(c) : c)) };
}

function mapMessage(state: AppData, chatId: string, messageId: string, change: (m: Message) => Message): AppData {
  return mapChat(state, chatId, (c) => ({
    ...c,
    messages: c.messages.map((m) => (m.id === messageId ? change(m) : m)),
  }));
}

/** A chat's title: the start of its first question, on one line. */
export function titleFrom(text: string): string {
  const line = text.replace(/\s+/g, " ").trim();
  return line.length > 60 ? `${line.slice(0, 57)}…` : line || "New chat";
}

export const MAX_TURN_CHARS = 24_000;

/** The recent turns sent as short-term memory: finished replies only, starting with a question. */
export function shortTermHistory(messages: Message[], limit: number): { role: Message["role"]; content: string }[] {
  const turns = messages
    .filter((m) => m.role === "user" || m.status === "done")
    .filter((m) => m.content.trim())
    .map((m) => ({ role: m.role, content: m.content.slice(0, MAX_TURN_CHARS) }));
  const recent = limit > 0 ? turns.slice(-limit) : [];
  while (recent.length && recent[0].role !== "user") recent.shift();
  return recent;
}

export function newId(): string {
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}
