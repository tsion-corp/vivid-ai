"use client";

import { useChat } from "@ai-sdk/react";
import { DefaultChatTransport, type UIMessage } from "ai";
import { useMemo } from "react";
import { API, authFetch } from "@/lib/api/client";
import { invalidate } from "@/lib/api/cache";
import { key as cacheKey } from "@/lib/api/endpoints";
import type { StoredMessage } from "@/lib/api/types";

/** Turns a stored thread into the shape `useChat` holds. §5 says they already match. */
export function toUIMessages(stored: StoredMessage[]): UIMessage[] {
  return stored.map((message) => ({
    id: message.id,
    role: message.role,
    parts: message.parts as UIMessage["parts"],
    metadata: { createdAt: message.created_at, model: message.model },
  }));
}

/**
 * The project's chat turn.
 *
 * Two seams make the AI SDK fit this backend:
 *
 *  - `prepareSendMessagesRequest`, because the transport posts `{messages}` and
 *    the builder wants `{text, images?}`. It is a pure projection of the last
 *    message, so there is nothing to keep in sync.
 *  - `fetch: authFetch`, so the 15-25 minute stream gets the same bearer token
 *    and refresh-on-401 as every other call, with no second copy of that logic.
 *  - `prepareReconnectToStreamRequest`, because the SDK would otherwise ask for
 *    `{api}/{chatId}/stream` — and our `api` already ends in `/chat`, so the
 *    default would build `.../chat/{id}/stream`. The route is `.../chat/stream`.
 *
 * `initialMessages` is read **once**; the caller must not mount this until the
 * stored thread has loaded.
 */
export function useProjectChat({
  projectId,
  initialMessages,
  resume = false,
  onSnapshot,
  onDone,
}: {
  projectId: string;
  initialMessages: UIMessage[];
  /**
   * Attach to a turn that is already running on the backend.
   *
   * Turns outlive the tab that started them, so reloading mid-build used to
   * show a dead thread for up to 25 minutes. The stream replays every part the
   * turn has produced so far, then follows it live.
   */
  resume?: boolean;
  /** A new version exists: refresh the preview and the versions list. */
  onSnapshot?: () => void;
  /** The turn finished. A build runs for 15-25 minutes, so this needs announcing. */
  onDone?: () => void;
}) {
  const transport = useMemo(
    () =>
      new DefaultChatTransport<UIMessage>({
        // Shares the base with every other call, so the direct/relayed
        // switch cannot apply to the REST calls and miss the stream.
        api: `${API}/builder/projects/${projectId}/chat`,
        fetch: authFetch,
        prepareSendMessagesRequest: ({ messages }) => {
          const last = messages.at(-1);
          const text = (last?.parts ?? [])
            .filter((part) => part.type === "text")
            .map((part) => (part as { text: string }).text)
            .join("\n");
          const images = (last?.parts ?? [])
            .filter((part) => part.type === "file" && part.mediaType?.startsWith("image/"))
            .map((part) => (part as { url: string }).url)
            .slice(0, 4);
          return { body: images.length ? { text, images } : { text } };
        },
        prepareReconnectToStreamRequest: ({ api }) => ({ api: `${api}/stream` }),
      }),
    [projectId],
  );

  return useChat<UIMessage>({
    id: projectId,
    messages: initialMessages,
    transport,
    resume,
    onData: (part) => {
      // A snapshot means the files on the server changed, so anything derived
      // from them is now stale.
      if (part.type === "data-snapshot") {
        invalidate(cacheKey.snapshots(projectId));
        invalidate(cacheKey.files(projectId));
        onSnapshot?.();
      }
    },
    onFinish: () => {
      // The turn may have flipped plan mode to build, renamed things, or
      // published; the project row is the cheapest way to find out.
      invalidate(cacheKey.project(projectId));
      invalidate(cacheKey.projects);
      onDone?.();
    },
  });
}
