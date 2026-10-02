// Small formatting helpers for times, durations and token counts.

const relative = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });

export function timeAgo(when: string | number | Date, now: number = Date.now()): string {
  const seconds = Math.round((new Date(when).getTime() - now) / 1000);
  const abs = Math.abs(seconds);
  if (abs < 45) return "just now";
  if (abs < 3600) return relative.format(Math.round(seconds / 60), "minute");
  if (abs < 86_400) return relative.format(Math.round(seconds / 3600), "hour");
  if (abs < 86_400 * 30) return relative.format(Math.round(seconds / 86_400), "day");
  return new Date(when).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

export function duration(ms: number): string {
  if (ms < 1000) return `${ms} ms`;
  const seconds = ms / 1000;
  if (seconds < 60) return `${seconds < 10 ? seconds.toFixed(1) : Math.round(seconds)} s`;
  return `${Math.floor(seconds / 60)} min ${Math.round(seconds % 60)} s`;
}

export function tokens(n: number): string {
  if (n < 1000) return String(n);
  return `${(n / 1000).toFixed(n < 10_000 ? 1 : 0)}k`;
}

/** Groups chats by when they were last used: Today, Yesterday, This week, Older. */
export function dayGroup(when: number, now: number = Date.now()): string {
  const start = new Date(now);
  start.setHours(0, 0, 0, 0);
  const day = 86_400_000;
  if (when >= start.getTime()) return "Today";
  if (when >= start.getTime() - day) return "Yesterday";
  if (when >= start.getTime() - 6 * day) return "This week";
  return "Older";
}
