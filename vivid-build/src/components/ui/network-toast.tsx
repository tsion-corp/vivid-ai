"use client";

import { CloudOff, SignalLow } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/cn";
import { useNetworkStatus } from "@/lib/network";

const COPY = {
  offline: {
    Icon: CloudOff,
    title: "You're offline",
    body: "Nothing will save until the connection is back. A build already running keeps going on the server.",
  },
  unstable: {
    Icon: SignalLow,
    title: "Your connection is unstable",
    body: "Requests are failing or timing out. Things may be slow to load.",
  },
} as const;

/**
 * A connection warning, bottom-right, above the regular toasts.
 *
 * Not routed through `useToast` on purpose: those dismiss themselves after a
 * few seconds, and a warning about a condition that is still true should not
 * disappear while it is still true. This one is bound to the condition — it
 * leaves when the network comes back, and says so on the way out.
 *
 * Mounted once at the root so it covers the marketing pages, the app and the
 * standalone preview route alike.
 */
export function NetworkToast() {
  const status = useNetworkStatus();
  const [recovered, setRecovered] = useState(false);
  // Whether a warning has been shown that a recovery would answer. A ref, not
  // state: it changes nothing on screen by itself, and reading it during render
  // is never needed.
  const warned = useRef(false);

  // "Back online" is worth saying — otherwise the warning simply vanishes and
  // the user is left unsure whether it is safe to retry. Nothing is said on a
  // first load that was fine all along.
  useEffect(() => {
    if (status !== "online") {
      warned.current = true;
      return;
    }
    if (!warned.current) return;
    warned.current = false;

    // Both writes are asynchronous by design: React 19 rejects a setState made
    // synchronously in an effect body.
    //
    // Timers rather than requestAnimationFrame — rAF does not run in a hidden
    // tab, so a connection that came back while the user was elsewhere would
    // hide the message before it had shown, then show it for good when they
    // returned.
    const show = window.setTimeout(() => setRecovered(true), 0);
    const hide = window.setTimeout(() => setRecovered(false), 3000);
    return () => {
      window.clearTimeout(show);
      window.clearTimeout(hide);
    };
  }, [status]);

  if (status === "online" && !recovered) return null;

  const warning = status === "online" ? null : COPY[status];
  const Icon = warning?.Icon;

  return (
    <div
      // `polite`, not `assertive`: a connection blip should not interrupt a
      // screen reader mid-sentence.
      aria-live="polite"
      className="pointer-events-none fixed right-4 bottom-4 z-400 flex max-w-[min(340px,calc(100vw-32px))] flex-col gap-2"
    >
      <div
        className={cn(
          "pointer-events-auto flex items-start gap-2.5 rounded-xl border bg-surface px-4 py-3 text-left shadow-[0_24px_60px_-30px_rgba(0,0,0,0.9)]",
          warning ? "border-warn/50" : "border-line-2",
        )}
      >
        {Icon ? (
          <Icon aria-hidden className="mt-px size-4 flex-none text-warn" />
        ) : (
          <span aria-hidden className="mt-1.5 size-2 flex-none rounded-full bg-code-string" />
        )}
        <div className="min-w-0">
          <p className="text-[13px] font-bold text-fg">{warning ? warning.title : "Back online"}</p>
          {warning && <p className="mt-0.5 text-[12px] leading-[1.45] text-muted">{warning.body}</p>}
        </div>
      </div>
    </div>
  );
}
