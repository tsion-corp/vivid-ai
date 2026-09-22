"use client";

import { ScrollText, TriangleAlert, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Disclosure } from "@/components/ui/disclosure";
import { getLogs } from "@/lib/api/endpoints";
import type { PreviewInfo } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import type { PreviewDevice } from "@/lib/preview/render";
import { DevLog } from "./dev-log";
import { PreviewSurface } from "./preview-surface";

type RuntimeError = { message: string; stack?: string };

const MAX_ERRORS = 10;

/**
 * The preview, plus the two things that make a blank page diagnosable.
 *
 * The iframe is on another origin so its console is unreadable from here; the
 * app template posts uncaught errors to the parent instead, and the dev
 * server's own output comes from the logs endpoint.
 */
export function PreviewPane({
  projectId,
  device,
  preset,
  nonce,
  onSend,
  onReload,
}: {
  projectId: string;
  device: PreviewDevice;
  preset: string;
  nonce: number;
  onSend: (text: string) => void;
  onReload: () => void;
}) {
  const [errors, setErrors] = useState<RuntimeError[]>([]);
  const [logs, setLogs] = useState<string[] | null>(null);
  const originRef = useRef<string | null>(null);

  const onPreview = useCallback((info: PreviewInfo) => {
    try {
      originRef.current = new URL(info.url).origin;
    } catch {
      originRef.current = null;
    }
    // A fresh sandbox starts clean; old errors belonged to the old one.
    setErrors([]);
  }, []);

  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      // The guide's snippet omits this check. Without it any page — including
      // the preview's own content if it were hostile — could fake an error and
      // get its text put in front of the user, and into the next chat turn.
      if (!originRef.current || event.origin !== originRef.current) return;

      const payload = event.data as { type?: string; message?: string; stack?: string } | null;
      if (payload?.type !== "vivid:error" || typeof payload.message !== "string") return;

      setErrors((current) =>
        current.some((error) => error.message === payload.message)
          ? current
          : [...current, { message: payload.message!, stack: payload.stack }].slice(-MAX_ERRORS),
      );
    };

    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, []);

  const fixIt = (error: RuntimeError) => {
    const stack = (error.stack ?? "").split("\n").slice(0, 4).join("\n");
    onSend(`Fix this runtime error: ${error.message}${stack ? `\n${stack}` : ""}`);
  };

  const showLogs = async () => {
    try {
      const result = await getLogs(projectId);
      setLogs(result.lines.length ? result.lines : ["The dev server has not printed anything."]);
    } catch (error) {
      setLogs([error instanceof Error ? error.message : "Could not read the logs."]);
    }
  };

  return (
    // `min-h-0` rather than a pixel floor: the floor was what stopped the
    // preview growing into the space it had.
    <div className="flex h-full min-h-0 flex-col gap-2 sm:gap-3">
      {/* Full-bleed on a phone. A 12px inset and a rounded border around a
          390px viewport is a frame around a frame, and the pane edge already
          separates it from the chrome. */}
      <div className="flex min-h-0 flex-1 justify-center overflow-hidden border-line-2 bg-surface sm:rounded-2xl sm:border sm:p-3">
        <PreviewSurface
          projectId={projectId}
          device={device}
          preset={preset}
          nonce={nonce}
          onPreview={onPreview}
          className="rounded-xl"
        />
      </div>

      {errors.length > 0 && (
        <div className="flex-none rounded-2xl border border-line-2 bg-surface p-3">
          <Disclosure
            defaultOpen
            summary={
              <span className="flex items-center gap-2 text-fg">
                <TriangleAlert aria-hidden className="size-3.5 flex-none text-warn" />
                {errors.length} runtime error{errors.length === 1 ? "" : "s"} in the preview
              </span>
            }
          >
            <ul className="mt-2 flex flex-col gap-2">
              {errors.map((error) => (
                <li key={error.message} className="rounded-lg bg-surface-2 p-2.5">
                  <p className="text-[12.5px] leading-[1.5] break-words text-fg-2">{error.message}</p>
                  <button
                    type="button"
                    onClick={() => fixIt(error)}
                    className="mt-1.5 cursor-pointer rounded-full bg-btn px-3 py-1 text-[11px] font-bold text-btn-fg"
                  >
                    Fix this
                  </button>
                </li>
              ))}
            </ul>
          </Disclosure>
        </div>
      )}

      <div className="flex flex-none items-center gap-3 px-2 pb-1 sm:px-0 sm:pb-0">
        <button
          type="button"
          onClick={() => void showLogs()}
          className="flex cursor-pointer items-center gap-1.5 text-[12px] font-semibold text-muted-3 transition-colors hover:text-fg"
        >
          <ScrollText aria-hidden className="size-3.5 flex-none" />
          {/* The full sentence does not fit beside Reload on a phone, and
              truncating it mid-question reads worse than saying less. */}
          <span className="hidden sm:inline">Preview blank? See the dev server output</span>
          <span className="sm:hidden">Dev server output</span>
        </button>
        <button
          type="button"
          onClick={onReload}
          className="ml-auto cursor-pointer text-[12px] font-semibold text-muted-3 transition-colors hover:text-fg"
        >
          Reload
        </button>
      </div>

      {logs && (
        <div className={cn("flex-none overflow-hidden rounded-2xl border border-line-2 bg-surface")}>
          <div className="flex items-center gap-2 border-b border-line px-3 py-2">
            <p className="flex-1 text-[11px] font-bold tracking-[0.08em] text-muted-3 uppercase">Dev server</p>
            <button
              type="button"
              onClick={() => setLogs(null)}
              aria-label="Hide logs"
              className="cursor-pointer text-muted-2 transition-colors hover:text-fg"
            >
              <X aria-hidden className="size-3.5" />
            </button>
          </div>
          <DevLog lines={logs} className="max-h-52" />
        </div>
      )}
    </div>
  );
}
