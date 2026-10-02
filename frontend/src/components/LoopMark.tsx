/** CodeLoop's mark: a loop that comes back around (memory) around a prompt caret (code). */
export function LoopMark({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      <rect width="32" height="32" rx="8" fill="var(--teal)" />
      <path d="M24.5 16a8.5 8.5 0 1 1-2.5-6" fill="none" stroke="var(--on-teal)" strokeWidth="2.6" strokeLinecap="round" />
      <path
        d="M23.6 5.6v4.9h-4.9"
        fill="none"
        stroke="var(--amber-mark)"
        strokeWidth="2.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M13.5 12.5 17 16l-3.5 3.5"
        fill="none"
        stroke="var(--on-teal)"
        strokeWidth="2.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
