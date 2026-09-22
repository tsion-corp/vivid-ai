"use client";

import { useSyncExternalStore } from "react";

export type NetworkStatus = "online" | "offline" | "unstable";

/**
 * Whether the network is actually carrying our requests.
 *
 * Deliberately not `navigator.onLine` alone: that reports the link, not the
 * internet, so it stays `true` on a café wifi that has stopped forwarding and
 * on a phone showing one bar of nothing. The signal that matters is whether our
 * own requests are getting through, and `client.ts` already knows — every fetch
 * that throws rather than answering is a network-level failure. So this is fed
 * from real traffic instead of a synthetic ping, which also means no background
 * polling and no extra battery on a phone.
 */

/** Outcomes of the last few requests; true = reached the server. */
const recent: boolean[] = [];
const WINDOW = 4;

const listeners = new Set<() => void>();
let status: NetworkStatus = "online";

function connectionIsSlow(): boolean {
  // Chromium-only, and a hint rather than a measurement — hence the cast and
  // the optional chain. On anything else this is simply absent.
  const connection = (navigator as Navigator & { connection?: { effectiveType?: string } }).connection;
  const type = connection?.effectiveType;
  return type === "2g" || type === "slow-2g";
}

function compute(): NetworkStatus {
  if (typeof navigator !== "undefined" && navigator.onLine === false) return "offline";

  const failures = recent.filter((ok) => !ok).length;
  // Everything in the window failed: the link is up but nothing is getting
  // through, which is the case `navigator.onLine` misses.
  if (recent.length >= 2 && failures === recent.length) return "offline";
  if (failures >= 2 || connectionIsSlow()) return "unstable";
  return "online";
}

function publish() {
  const next = compute();
  if (next === status) return;
  status = next;
  for (const listener of listeners) listener();
}

/** Called by the API client for every request that completes or fails. */
export function reportRequest(reachedServer: boolean) {
  recent.push(reachedServer);
  if (recent.length > WINDOW) recent.shift();
  // One success is enough to stop crying wolf; a stale window would keep the
  // warning up long after the connection came back.
  if (reachedServer) recent.length = 0;
  publish();
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  const onChange = () => {
    // The browser's own events are still worth having: they are instant, where
    // request evidence only arrives when something is being requested.
    if (navigator.onLine) recent.length = 0;
    publish();
  };
  window.addEventListener("online", onChange);
  window.addEventListener("offline", onChange);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("online", onChange);
    window.removeEventListener("offline", onChange);
  };
}

const getSnapshot = () => status;
/** The server has no network to report on, and must not disagree with the first paint. */
const getServerSnapshot = (): NetworkStatus => "online";

export function useNetworkStatus(): NetworkStatus {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}
