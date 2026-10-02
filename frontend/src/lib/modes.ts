import { Bug, FlaskConical, MessageCircleQuestion, PenLine, ScanSearch } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { Mode } from "./types";

/** The agent's modes as the developer sees them. Each one changes the agent's instructions on the server. */
export const MODE_META: Record<Mode, { label: string; icon: LucideIcon; hint: string }> = {
  ask: { label: "Ask", icon: MessageCircleQuestion, hint: "Questions about the code or programming" },
  write: { label: "Write", icon: PenLine, hint: "Implement features and changes" },
  debug: { label: "Debug", icon: Bug, hint: "Find the root cause of a bug, then fix it" },
  review: { label: "Review", icon: ScanSearch, hint: "Find bugs, security and performance problems" },
  test: { label: "Test", icon: FlaskConical, hint: "Write and run tests, by any testing method" },
};
