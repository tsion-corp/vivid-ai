"use client";

import type { UIMessage } from "ai";
import { useCallback, useEffect, useRef, useState } from "react";
import { Dialog } from "@/components/ui/dialog";
import { Spinner } from "@/components/ui/spinner";
import { useToast } from "@/components/ui/toast";
import { inputClass } from "@/components/settings/field";
import { cancelTurn, key, listMessages, startBuild, updateProject, uploadAsset } from "@/lib/api/endpoints";
import { invalidate } from "@/lib/api/cache";
import { takeFirstMessage } from "@/lib/api/first-message";
import { toUIMessages } from "./use-project-chat";
import type { Asset, Project } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { buttonClass } from "@/lib/ui";
import { ChatComposer } from "../chat-composer";
import { ChatThread } from "./chat-thread";
import type { PartContext } from "./message-parts";
import { TurnStatus } from "./turn-status";
import { useProjectChat } from "./use-project-chat";

/**
 * A turn can take 25 minutes, so whoever started it is almost certainly looking
 * at something else by now: the toast covers another page in the app, the title
 * covers another tab entirely.
 *
 * The restore listener is the point. Without it the tab keeps saying "Done"
 * long after it has been read, and the next turn's "Done" says nothing new.
 */
function flagDoneInTitle(projectName: string) {
  if (!document.hidden) return;
  document.title = `✓ Done · ${projectName}`;
  const restore = () => {
    if (document.hidden) return;
    document.title = `${projectName} · VividBuild`;
    document.removeEventListener("visibilitychange", restore);
  };
  document.addEventListener("visibilitychange", restore);
}

/** In plan mode nothing was built, so saying "your app is ready" is a lie. */
function doneMessage(mode: Project["mode"]) {
  return mode === "build" ? "Your app is ready" : "Ready for you";
}

/** "for 6 minutes" — nothing under a minute, where a spinner already says it. */
function sinceLabel(startedAt: string | null): string | null {
  if (!startedAt) return null;
  const started = Date.parse(startedAt);
  if (Number.isNaN(started)) return null;
  const minutes = Math.floor((Date.now() - started) / 60_000);
  if (minutes < 1) return null;
  return `for ${minutes} minute${minutes === 1 ? "" : "s"}`;
}

type Props = {
  className?: string;
  project: Project;
  initialMessages: UIMessage[];
  onSnapshot?: () => void;
  /** A turn raised from elsewhere — "Fix this" on a preview error. */
  request?: { text: string; at: number } | null;
};

/**
 * The left pane: the conversation with the builder.
 *
 * Mounted only once the stored thread has loaded — `useChat` reads `messages`
 * as an initial value and ignores later changes, so hydrating after mount would
 * silently show an empty thread.
 */
export function ChatPanel({ className, project, initialMessages, onSnapshot, request }: Props) {
  const { toast } = useToast();
  const [draft, setDraft] = useState("");
  const [specDraft, setSpecDraft] = useState<string | null>(null);
  const [building, setBuilding] = useState(false);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Captured once, at mount: if a turn was already running when this page
  // loaded, attach to its stream instead of showing a thread that looks
  // finished. State rather than a ref because it is read during render, and
  // never set again because `useChat` reads `resume` on mount only.
  const [resumeOnMount] = useState(() => project.turn_status === "running");

  const { messages, sendMessage, setMessages, status, stop, error, clearError, resumeStream } = useProjectChat({
    projectId: project.id,
    initialMessages,
    resume: resumeOnMount,
    onSnapshot,
    onDone: () => {
      toast(doneMessage(project.mode));
      flagDoneInTitle(project.name);
    },
  });

  const streaming = status === "submitted" || status === "streaming";

  const send = useCallback(
    (text: string, attachments: Asset[] = []) => {
      const request = text.trim();
      if (!request) return;
      clearError();

      // Reference screenshots only ride along in plan mode (§3 caps them at
      // four); in build mode the upload itself is how the agent sees a file.
      const images =
        project.mode === "plan"
          ? attachments.filter((asset) => asset.mime.startsWith("image/")).slice(0, 4)
          : [];

      void sendMessage({
        text: request,
        files: images.map((asset) => ({ type: "file" as const, mediaType: asset.mime, url: asset.url })),
      });
      // The composer is controlled from here, so emptying it is this function's
      // job — the send itself is fire-and-forget.
      setDraft("");
    },
    [sendMessage, clearError, project.mode],
  );

  // The dashboard creates the project, then hands the prompt over for the first
  // turn — creating and describing are two API calls now.
  //
  // The text is claimed from storage synchronously but sent on a timeout, so it
  // does not start a request during the mounting render. Holding it in a ref
  // matters: React double-invokes effects in development, and the first run's
  // cleanup cancels the timeout, so a guard that only remembered "I started"
  // would drop the message entirely.
  const pending = useRef<string | null | undefined>(undefined);
  useEffect(() => {
    if (messages.length > 0) return;
    if (pending.current === undefined) pending.current = takeFirstMessage(project.id);
    const text = pending.current;
    if (!text) return;

    const id = window.setTimeout(() => {
      pending.current = null;
      send(text);
    }, 0);
    return () => window.clearTimeout(id);
  }, [project.id, messages.length, send]);

  // Raised by the preview pane. Keyed on the timestamp so the same error text
  // twice is two turns, not one.
  const lastRequest = useRef(0);
  useEffect(() => {
    if (!request || request.at === lastRequest.current) return;
    lastRequest.current = request.at;
    const id = window.setTimeout(() => send(request.text), 0);
    return () => window.clearTimeout(id);
  }, [request, send]);

  /**
   * A turn still running on the backend, with no stream attached here.
   *
   * `turn_status` replaces what used to be an inference — "the last message is
   * the user's, so a reply must be coming" — which was wrong in exactly the case
   * that mattered: a turn that ended without leaving a message pinned the banner
   * up forever with no way to clear it.
   *
   * The project row is polled while a turn runs, both to notice it finish and to
   * keep "building for N minutes" honest.
   */
  const turnRunning = project.turn_status === "running";
  const waitingForReply = turnRunning && !streaming;

  // Recomputed on each project poll, which is what moves the counter along.
  const elapsed = turnRunning ? sinceLabel(project.turn_started_at) : null;

  /**
   * The stream died while the turn is still going: reattach to it.
   *
   * This is the normal case on a serverless host, not an edge one. A build turn
   * runs 15-25 minutes and Vercel caps a function response at 300s (Hobby), so
   * the relay is *guaranteed* to be cut part-way through a first build. The turn
   * itself is unaffected — it belongs to the backend — so `GET /chat/stream`
   * replays what it has produced and follows the rest live.
   *
   * Capped, because a stream that fails instantly every time would otherwise
   * spin: past that the "Still working on this" banner takes over, and the
   * finished turn is picked up when `turn_status` goes idle.
   */
  const reattempts = useRef(0);
  useEffect(() => {
    if (!error || !turnRunning) {
      reattempts.current = 0;
      return;
    }
    if (reattempts.current >= 5) return;

    const wait = Math.min(1000 * 2 ** reattempts.current, 15_000);
    const id = window.setTimeout(() => {
      reattempts.current += 1;
      clearError();
      void resumeStream();
    }, wait);
    return () => window.clearTimeout(id);
  }, [error, turnRunning, clearError, resumeStream]);

  useEffect(() => {
    if (!turnRunning) return;

    // Cheap: one project row, not the whole thread. The stream is the live
    // channel; this is only here to catch the end of a turn we are not attached
    // to, and to move the "building for N minutes" counter along.
    const id = window.setInterval(() => {
      if (!document.hidden) invalidate(key.project(project.id));
    }, 10_000);
    return () => window.clearInterval(id);
  }, [turnRunning, project.id]);

  // The edge from running to idle is the end of a turn nobody was watching.
  const wasRunning = useRef(turnRunning);
  useEffect(() => {
    if (wasRunning.current && !turnRunning) {
      void (async () => {
        try {
          setMessages(toUIMessages(await listMessages(project.id)));
        } catch {
          // The banner is already gone; the thread will catch up on next load.
        }
        toast(doneMessage(project.mode));
        flagDoneInTitle(project.name);
        // The turn wrote files and may have published; nothing derived from the
        // old state is still true.
        invalidate(key.files(project.id));
        invalidate(key.snapshots(project.id));
        onSnapshot?.();
      })();
    }
    wasRunning.current = turnRunning;
  }, [turnRunning, project.id, project.name, project.mode, setMessages, toast, onSnapshot]);

  /**
   * Stop, and mean it.
   *
   * Two things happen here that used to be one. `stop()` aborts the local
   * stream — but after a reload there is no local stream, so on its own it does
   * nothing at all. `POST /cancel` stops the turn server-side, which matters
   * because aborting only the fetch would leave a 25-minute turn running and
   * still burning credits.
   *
   * A cancelled turn still stores what it produced, so the thread is refreshed
   * either way rather than assuming the work was thrown away.
   */
  const halt = async () => {
    stop();

    let running = true;
    try {
      const result = await cancelTurn(project.id);
      running = result.cancelled;
    } catch {
      // Could not ask. Treat it as finished rather than trapping the user.
      running = false;
    }

    // `turn_status` decides whether the banner shows, so this is what clears it.
    invalidate(key.project(project.id));

    if (!running) toast("That turn had already finished");

    // A cancelled turn keeps what it produced, so pull it in either way.
    try {
      setMessages(toUIMessages(await listMessages(project.id)));
    } catch {
      // The refresh is a courtesy; the banner clears from turn_status anyway.
    }
    invalidate(key.files(project.id));
    invalidate(key.snapshots(project.id));
    onSnapshot?.();
  };

  /**
   * POST /build only flips the project from plan mode to build mode — it does
   * not start a turn. The button says "Build it", so it sends the first build
   * turn too rather than leaving the user to guess that they must now type.
   */
  const build = async () => {
    setBuilding(true);
    try {
      await startBuild(project.id);
      toast("Building — the first run takes 15 to 25 minutes");
      send("Build it.");
    } catch (caught) {
      toast(caught instanceof Error ? caught.message : "Could not start the build", "warn");
    } finally {
      setBuilding(false);
    }
  };

  const saveSpec = async (markdown: string) => {
    setSpecDraft(null);
    try {
      await updateProject(project.id, { spec_md: markdown });
      toast("Spec updated");
    } catch (caught) {
      toast(caught instanceof Error ? caught.message : "Could not save the spec", "warn");
    }
  };

  const context: PartContext = {
    streaming,
    answered: false,
    onSend: send,
    onEditSpec: setSpecDraft,
    onBuild: () => void build(),
    planning: project.mode === "plan" && !building,
  };

  const last = messages.at(-1) ?? null;

  return (
    <section aria-label="Chat" className={cn("min-w-0 flex-1 flex-col border-line lg:border-r", className)}>
      <div className="no-scrollbar flex min-h-0 flex-1 flex-col overflow-y-auto px-[18px] py-5">
        {messages.length === 0 ? (
          <p className="m-auto max-w-[320px] text-center text-sm text-muted">
            Describe what you want to build. The agent will ask a few questions, write a spec, and then build it.
          </p>
        ) : (
          <ChatThread messages={messages} context={context} />
        )}

        {error && (
          <div className="mt-4 rounded-lg bg-warn/20 px-3 py-2.5">
            <p className="text-[13px] leading-[1.5] text-fg-2">{error.message}</p>
            <p className="mt-1 text-[11px] text-muted">
              The turn&apos;s output is saved before the stream ends, so reloading may show it anyway.
            </p>
          </div>
        )}
      </div>

      {waitingForReply && (
        <div className="flex items-center gap-2.5 border-t border-line bg-surface px-[18px] py-2.5">
          <Spinner />
          <p className="min-w-0 flex-1 text-[13px] font-semibold text-fg-2">
            Still working on this — it keeps going even if you leave.
            {/* "Building for 6 minutes" is reassuring in a way a bare spinner is
                not, when a first build honestly takes 15 to 25. */}
            {elapsed && <span className="ml-1.5 font-medium text-muted">{elapsed}</span>}
          </p>
          <button
            type="button"
            onClick={() => void halt()}
            className="flex-none cursor-pointer rounded-full border border-line-2 px-3 py-1 text-[11px] font-bold text-muted transition-colors hover:text-fg"
          >
            Stop
          </button>
        </div>
      )}

      <TurnStatus message={last?.role === "assistant" ? last : null} streaming={streaming} onStop={() => void halt()} />

      <ChatComposer
        draft={draft}
        onDraftChange={setDraft}
        onSend={send}
        onUpload={(file) => uploadAsset(project.id, file)}
        inputRef={inputRef}
        // A turn started in another tab counts too: while one runs, every new
        // POST /chat answers 409 busy, so offering to send is a promise we
        // cannot keep.
        busy={streaming || turnRunning}
        mode={project.mode}
      />

      {specDraft !== null && (
        <Dialog title="Edit the spec" size="lg" onClose={() => setSpecDraft(null)}>
          <div className="flex flex-col gap-4 px-5 py-4">
            <textarea
              autoFocus
              rows={18}
              value={specDraft}
              onChange={(event) => setSpecDraft(event.target.value)}
              className={cn(inputClass, "resize-y font-mono text-[12.5px] leading-[1.6]")}
            />
            <div className="flex justify-end gap-2.5">
              <button
                type="button"
                onClick={() => setSpecDraft(null)}
                className={buttonClass({ variant: "secondary", size: "sm" })}
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => void saveSpec(specDraft)}
                className={buttonClass({ size: "sm" })}
              >
                Save spec
              </button>
            </div>
          </div>
        </Dialog>
      )}
    </section>
  );
}
