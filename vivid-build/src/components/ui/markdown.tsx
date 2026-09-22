import { Fragment, type ReactNode } from "react";
import { cn } from "@/lib/cn";

/**
 * A small markdown renderer.
 *
 * The agent's text, briefs and specs are all markdown. This covers what they
 * actually use — headings, lists, emphasis, code, links — and renders anything
 * else as plain text, which is the right failure mode for text that arrives a
 * token at a time. No dependency, and no `dangerouslySetInnerHTML`: every node
 * below is a React element, so a stray `<script>` in generated text is inert.
 */

const INLINE = /(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`|\[[^\]]+\]\([^)\s]+\))/g;

function inline(text: string, keyPrefix: string): ReactNode[] {
  return text.split(INLINE).map((chunk, index) => {
    const key = `${keyPrefix}-${index}`;
    if (!chunk) return null;

    if (chunk.startsWith("**") && chunk.endsWith("**")) {
      return (
        <strong key={key} className="font-bold text-fg">
          {chunk.slice(2, -2)}
        </strong>
      );
    }
    if (chunk.startsWith("`") && chunk.endsWith("`")) {
      return (
        <code key={key} className="rounded bg-surface-2 px-1 py-0.5 font-mono text-[0.9em] text-fg">
          {chunk.slice(1, -1)}
        </code>
      );
    }
    if (chunk.startsWith("*") && chunk.endsWith("*")) {
      return (
        <em key={key} className="italic">
          {chunk.slice(1, -1)}
        </em>
      );
    }
    const link = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(chunk);
    if (link) {
      const href = link[2];
      // Only http(s) — a javascript: or data: href in model output would be a
      // script injection with a friendly label on it.
      if (/^https?:\/\//i.test(href)) {
        return (
          <a
            key={key}
            href={href}
            target="_blank"
            rel="noreferrer noopener"
            className="underline underline-offset-2 hover:text-fg"
          >
            {link[1]}
          </a>
        );
      }
      return <Fragment key={key}>{link[1]}</Fragment>;
    }
    return <Fragment key={key}>{chunk}</Fragment>;
  });
}

type Block =
  | { kind: "p" | "h1" | "h2" | "h3" | "quote"; text: string }
  | { kind: "ul" | "ol"; items: string[] }
  | { kind: "code"; text: string }
  | { kind: "hr" };

function parse(markdown: string): Block[] {
  const lines = markdown.replace(/\r\n/g, "\n").split("\n");
  const blocks: Block[] = [];
  let paragraph: string[] = [];
  let list: { kind: "ul" | "ol"; items: string[] } | null = null;

  const flush = () => {
    if (paragraph.length) {
      blocks.push({ kind: "p", text: paragraph.join(" ") });
      paragraph = [];
    }
    if (list) {
      blocks.push(list);
      list = null;
    }
  };

  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i];

    if (line.trimStart().startsWith("```")) {
      flush();
      const body: string[] = [];
      i += 1;
      while (i < lines.length && !lines[i].trimStart().startsWith("```")) {
        body.push(lines[i]);
        i += 1;
      }
      blocks.push({ kind: "code", text: body.join("\n") });
      continue;
    }

    if (!line.trim()) {
      flush();
      continue;
    }

    if (/^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) {
      flush();
      blocks.push({ kind: "hr" });
      continue;
    }

    const heading = /^(#{1,6})\s+(.*)$/.exec(line);
    if (heading) {
      flush();
      const level = heading[1].length;
      blocks.push({ kind: level === 1 ? "h1" : level === 2 ? "h2" : "h3", text: heading[2] });
      continue;
    }

    if (line.trimStart().startsWith("> ")) {
      flush();
      blocks.push({ kind: "quote", text: line.trimStart().slice(2) });
      continue;
    }

    const bullet = /^\s*[-*+]\s+(.*)$/.exec(line);
    const numbered = /^\s*\d+[.)]\s+(.*)$/.exec(line);
    if (bullet || numbered) {
      if (paragraph.length) flush();
      const kind = bullet ? "ul" : "ol";
      if (!list || list.kind !== kind) {
        if (list) blocks.push(list);
        list = { kind, items: [] };
      }
      list.items.push((bullet ?? numbered)![1]);
      continue;
    }

    if (list) {
      blocks.push(list);
      list = null;
    }
    paragraph.push(line.trim());
  }

  flush();
  return blocks;
}

export function Markdown({ children, className }: { children: string; className?: string }) {
  const blocks = parse(children);

  return (
    <div className={cn("flex flex-col gap-2.5 text-[14px] leading-[1.65] text-fg-2", className)}>
      {blocks.map((block, index) => {
        const key = `b-${index}`;
        switch (block.kind) {
          case "h1":
            return (
              <h3 key={key} className="text-base font-extrabold tracking-[-0.02em] text-fg">
                {inline(block.text, key)}
              </h3>
            );
          case "h2":
            return (
              <h4 key={key} className="text-[14px] font-bold text-fg">
                {inline(block.text, key)}
              </h4>
            );
          case "h3":
            return (
              <h5 key={key} className="text-sm font-bold text-fg">
                {inline(block.text, key)}
              </h5>
            );
          case "quote":
            return (
              <p key={key} className="border-l-2 border-line-3 pl-3 text-muted">
                {inline(block.text, key)}
              </p>
            );
          case "code":
            return (
              <pre
                key={key}
                className="overflow-x-auto rounded-xl border border-line-2 bg-surface-2 p-3 font-mono text-[12px] leading-[1.6] text-fg-2"
              >
                <code>{block.text}</code>
              </pre>
            );
          case "hr":
            return <hr key={key} className="border-line" />;
          case "ul":
          case "ol": {
            const List = block.kind === "ul" ? "ul" : "ol";
            return (
              <List
                key={key}
                className={cn("flex flex-col gap-1 pl-5", block.kind === "ul" ? "list-disc" : "list-decimal")}
              >
                {block.items.map((item, itemIndex) => (
                  <li key={`${key}-${itemIndex}`} className="marker:text-muted-3">
                    {inline(item, `${key}-${itemIndex}`)}
                  </li>
                ))}
              </List>
            );
          }
          default:
            return <p key={key}>{inline(block.text, key)}</p>;
        }
      })}
    </div>
  );
}
