"use client";

import { Check, CircleAlert, FileText, History, TriangleAlert } from "lucide-react";
import type { UIMessage } from "ai";
import type { ReactNode } from "react";
import { Disclosure } from "@/components/ui/disclosure";
import { Markdown } from "@/components/ui/markdown";
import { Spinner } from "@/components/ui/spinner";
import { StreamingCaret } from "@/components/ui/streaming-caret";
import { cn } from "@/lib/cn";
import { modelLabel } from "@/lib/model-name";
import { buttonClass } from "@/lib/ui";
import { parseQuestions, QuestionCards } from "./question-cards";
import { toolLabel } from "./tool-labels";

type Part = UIMessage["parts"][number];

/**
 * Why a turn ended badly, in words the person waiting for it can act on.
 *
 * `data-usage` now carries an explicit `ok`, so this map no longer has to double
 * as the definition of "went wrong". That matters: guessing from `reason` alone
 * flagged `asked` and `spec_written` — the two most common *successful* endings
 * in plan mode — as failures. Branching on `ok` means a reason we have never
 * seen is still reported honestly rather than mislabelled either way.
 */
const STOP_REASON: Record<string, string> = {
  typecheck_strikes:
    "The agent could not get the code to compile this turn, so the preview may be blank or broken.",
  step_limit: "The agent hit its step limit before finishing.",
  no_changes: "This turn wrote no files, so the app is as it was.",
  cancelled: "This turn was cancelled.",
  error: "This turn failed part-way through.",
};

const FIX_REQUEST: Record<string, string> = {
  typecheck_strikes: "The app does not compile. Fix the type errors and make the preview work.",
  step_limit: "You ran out of steps. Carry on from where you stopped.",
  no_changes: "That turn wrote no files. Please build the app now, following the spec.",
  error: "That turn failed part-way through. Please pick it up and finish.",
};

/** Narrow the loose wire shapes without scattering `as` through the renderers. */
const data = <T,>(part: Part): T => (part as unknown as { data: T }).data;

export type PartContext = {
  /** The last message is the only one whose text can still be streaming. */
  streaming: boolean;
  /** A later user message exists, so question cards are historical. */
  answered: boolean;
  onSend: (text: string) => void;
  onEditSpec: (markdown: string) => void;
  onBuild: () => void;
  /** Plan mode: only then do "Edit spec" and "Build" mean anything. */
  planning: boolean;
};

export function MessagePart({ part, last, context }: { part: Part; last: boolean; context: PartContext }) {
  const type = part.type;

  if (type === "text") {
    const text = (part as { text: string }).text;
    if (!text.trim()) return null;
    return (
      <div>
        <Markdown>{text}</Markdown>
        {last && context.streaming && <StreamingCaret />}
      </div>
    );
  }

  // Counted for the step line, never drawn.
  if (type === "step-start") return null;

  // Deliberately not rendered. §4: the brief arrives as streamed text parts
  // *and* again in data-brief — drawing both shows the same paragraphs twice,
  // and the streamed copy is the one that appears word by word.
  if (type === "data-brief") return null;

  if (type === "data-spec") {
    const markdown = data<{ markdown: string }>(part).markdown;
    return (
      <Card title="The spec">
        {/* Passed as JSX, not a bare string: the buttons below make children an
            array, and the Card only auto-renders markdown for a lone string. */}
        <Markdown>{markdown}</Markdown>
        {context.planning && (
          <div className="mt-3.5 flex flex-wrap gap-2.5">
            <button type="button" onClick={context.onBuild} className={buttonClass({ size: "sm" })}>
              Build it
            </button>
            <button
              type="button"
              onClick={() => context.onEditSpec(markdown)}
              className={buttonClass({ variant: "secondary", size: "sm" })}
            >
              Edit spec
            </button>
          </div>
        )}
      </Card>
    );
  }

  if (type === "data-notice") {
    const notice = data<{ text: string; reason?: string }>(part);
    return (
      <p className="flex items-start gap-2 text-[13px] leading-[1.5] text-muted">
        <CircleAlert aria-hidden className="mt-px size-3.5 flex-none text-muted-3" />
        {notice.text}
      </p>
    );
  }

  if (type === "data-critique") {
    const critique = data<{
      round: number;
      broken?: boolean;
      screenshots?: { name: string; width: number; url: string }[];
    }>(part);
    return (
      <div className="flex flex-col gap-2">
        <p className={cn("text-[13px] font-semibold", critique.broken ? "text-fg" : "text-muted")}>
          {critique.broken
            ? "The page crashed — fixing it first"
            : `Looking at the page on desktop and phone (round ${critique.round})`}
        </p>
        {critique.screenshots && critique.screenshots.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {critique.screenshots.map((shot) => (
              // Signed, time-limited URLs on a host that is not known at build
              // time, so next/image's remotePatterns cannot cover them.
              // eslint-disable-next-line @next/next/no-img-element
              <img
                key={shot.url}
                src={shot.url}
                alt={`${shot.name} preview`}
                loading="lazy"
                className="h-28 rounded-lg border border-line-2 bg-surface object-cover object-top"
              />
            ))}
          </div>
        )}
      </div>
    );
  }

  if (type === "data-snapshot") {
    const snapshot = data<{ seq: number }>(part);
    return (
      <p className="flex items-center gap-2 text-[13px] text-muted">
        <History aria-hidden className="size-3.5 text-muted-3" />
        Saved as version {snapshot.seq}
      </p>
    );
  }

  if (type === "data-usage") {
    const usage = data<{
      model?: string;
      steps?: number;
      reason?: string;
      ok?: boolean;
      failed_tools?: string[];
    }>(part);

    const footer = (
      <p className="text-[11px] font-semibold text-muted-3">
        {usage.steps ?? 0} step{usage.steps === 1 ? "" : "s"} · {modelLabel(usage.model)}
      </p>
    );

    // A tool call whose arguments came back malformed. The backend retries each
    // one, so a name still here at the end means that file was never written —
    // and saying which file is the difference between a user who can ask for it
    // and one staring at a half-built app wondering what is missing.
    const failed = usage.failed_tools ?? [];

    // `ok` is authoritative. Older turns in a hydrated thread predate it, so
    // fall back to the failure list we know about rather than assuming success.
    const wentWrong = usage.ok === false || (usage.ok === undefined && !!usage.reason && usage.reason in STOP_REASON);

    if (!wentWrong && failed.length === 0) return footer;

    const reason = usage.reason ?? "";
    const note = wentWrong
      ? (STOP_REASON[reason] ?? `This turn stopped early (${reason.replace(/_/g, " ")}).`)
      : `Some files were never written: ${failed.join(", ")}.`;
    const retry = wentWrong
      ? (FIX_REQUEST[reason] ?? "That turn stopped early. Please finish it.")
      : `These were never written: ${failed.join(", ")}. Please write them.`;

    // A turn that ran out of typecheck attempts or steps has left the app in a
    // state that may not even compile. Burying that in grey 11px text is how
    // someone ends up staring at a blank preview wondering what broke.
    return (
      <div className="flex flex-col gap-2 rounded-xl bg-warn/20 px-3 py-2.5">
        <p className="flex items-start gap-2 text-[13px] leading-[1.5] text-fg-2">
          <TriangleAlert aria-hidden className="mt-px size-3.5 flex-none" />
          {note}
        </p>
        {wentWrong && failed.length > 0 && (
          <ul className="flex flex-col gap-0.5 pl-5.5 text-[12px] text-muted">
            {failed.map((tool) => (
              <li key={tool}>{tool} — never written</li>
            ))}
          </ul>
        )}
        <button
          type="button"
          onClick={() => context.onSend(retry)}
          className="cursor-pointer self-start rounded-full bg-btn px-3 py-1 text-[11px] font-bold text-btn-fg"
        >
          {wentWrong ? "Ask it to finish" : "Ask for the missing files"}
        </button>
        {footer}
      </div>
    );
  }

  // Hydrated failures. Live ones arrive as chat.error instead.
  if (type === "data-error" || type === "data-abort") {
    const detail = data<{ errorText?: string; reason?: string }>(part);
    return (
      <p className="flex items-start gap-2 rounded-lg bg-warn/20 px-3 py-2 text-[13px] leading-[1.5] text-fg-2">
        <TriangleAlert aria-hidden className="mt-px size-3.5 flex-none" />
        {type === "data-abort" ? (detail.reason ?? "Cancelled.") : (detail.errorText ?? "That turn failed.")}
      </p>
    );
  }

  // data-status and data-review are hoisted into the status bar, not drawn here.
  if (type === "data-status" || type === "data-review") return null;

  if (type === "file") {
    const file = part as { url: string; mediaType?: string };
    if (!file.mediaType?.startsWith("image/")) return null;
    // eslint-disable-next-line @next/next/no-img-element
    return <img src={file.url} alt="" className="max-h-40 rounded-lg border border-line-2" />;
  }

  if (type.startsWith("tool-")) {
    const tool = part as unknown as {
      type: string;
      state?: string;
      input?: Record<string, unknown>;
      output?: unknown;
      errorText?: string;
    };
    const name = tool.type.slice("tool-".length);

    if (name === "ask_user") {
      const questions = parseQuestions(tool.input);
      if (!questions.length) return null;
      return <QuestionCards questions={questions} answered={context.answered} onSend={context.onSend} />;
    }

    // write_spec's markdown also arrives as data-spec, which carries the buttons.
    if (name === "write_spec") return null;

    return <ToolActivity name={name} state={tool.state} input={tool.input} output={tool.output} error={tool.errorText} />;
  }

  return null;
}

function Card({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="overflow-hidden rounded-2xl border border-line-2 bg-surface">
      <h3 className="flex items-center gap-2 border-b border-line px-4 py-3 text-sm font-bold text-fg">
        <FileText aria-hidden className="size-4 text-muted-2" />
        {title}
      </h3>
      <div className="px-4 py-3.5">
        {typeof children === "string" ? <Markdown>{children}</Markdown> : children}
      </div>
    </div>
  );
}

/** One compact row in the activity list. */
export function ToolActivity({
  name,
  state,
  input,
  output,
  error,
}: {
  name: string;
  state?: string;
  input?: Record<string, unknown>;
  output?: unknown;
  error?: string;
}) {
  const running = state === "input-available" || state === "input-streaming";
  const failed = state === "output-error";
  const detail = failed ? error : typeof output === "string" ? output : null;

  const row = (
    <span className="flex items-center gap-2 text-[12px]">
      {running ? (
        <Spinner className="size-3" />
      ) : failed ? (
        <TriangleAlert aria-hidden className="size-3.5 flex-none text-warn" />
      ) : (
        <Check aria-hidden className="size-3.5 flex-none text-muted-3" />
      )}
      <span className={cn("min-w-0 truncate", failed ? "font-semibold text-fg-2" : "text-muted-2")}>
        {toolLabel(name, input)}
      </span>
    </span>
  );

  if (!detail) return row;

  return (
    <Disclosure summary={row} defaultOpen={failed}>
      <pre
        className={cn(
          "mt-1 ml-5 overflow-x-auto rounded-lg border p-2.5 font-mono text-[11px] leading-[1.6]",
          failed ? "border-transparent bg-warn/20 text-fg-2" : "border-line-2 bg-surface-2 text-muted",
        )}
      >
        {detail}
      </pre>
    </Disclosure>
  );
}
