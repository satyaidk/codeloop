import { useRef, useState } from "react";
import type { ComponentPropsWithoutRef, ReactElement } from "react";
import ReactMarkdown from "react-markdown";
import type { ExtraProps } from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import remarkGfm from "remark-gfm";
import { Check, Copy } from "lucide-react";
import { CODE_LANGUAGES } from "../lib/highlight";
import styles from "./Markdown.module.css";

/**
 * Renders the tutor's reply. react-markdown never injects raw HTML from the text, so a reply
 * can't smuggle scripts into the page.
 */
export function Markdown({ text }: { text: string }) {
  return (
    <div className={styles.prose}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[[rehypeHighlight, { detect: true, languages: CODE_LANGUAGES }]]}
        components={{ pre: CodeBlock, a: ExternalLink }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}

// `node` is react-markdown's syntax tree for the element; it must not reach the DOM.
function CodeBlock({ children, node: _node, ...props }: ComponentPropsWithoutRef<"pre"> & ExtraProps) {
  const preRef = useRef<HTMLPreElement>(null);
  const [copied, setCopied] = useState(false);

  // The <code> child carries "language-python" style classes; show that name in the header.
  const codeClass = ((children as ReactElement<{ className?: string }>)?.props?.className ?? "") as string;
  const language = /language-([\w+#-]+)/.exec(codeClass)?.[1] ?? "code";

  const copy = async () => {
    await navigator.clipboard?.writeText(preRef.current?.textContent ?? "");
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className={styles.code}>
      <div className={styles.codeBar}>
        <span>{language}</span>
        <button type="button" className={styles.copy} onClick={copy} aria-label="Copy code">
          {copied ? <Check size={15} /> : <Copy size={15} />}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre ref={preRef} {...props}>
        {children}
      </pre>
    </div>
  );
}

function ExternalLink({ node: _node, ...props }: ComponentPropsWithoutRef<"a"> & ExtraProps) {
  return <a {...props} target="_blank" rel="noreferrer noopener" />;
}
