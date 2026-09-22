"use client";

import type { UIMessage } from "ai";
import { useEffect, useRef } from "react";
import { cn } from "@/lib/cn";
import { AnswerSummary, parseAnswers } from "./answer-summary";
import { MessagePart, type PartContext } from "./message-parts";

/**
 * The transcript.
 *
 * Every message is a list of parts, live or hydrated — §5 guarantees the stored
 * shape matches what `useChat` holds — so one renderer serves both and a reload
 * looks exactly like the stream that produced it.
 */
export function ChatThread({
  messages,
  context,
  className,
}: {
  messages: UIMessage[];
  context: PartContext;
  className?: string;
}) {
  const endRef = useRef<HTMLDivElement>(null);
  const lastIndex = messages.length - 1;

  // Follows the stream. Keyed on the part count as well as the message count,
  // or a 20-minute turn would scroll once and then sit still.
  const partCount = messages.reduce((total, message) => total + message.parts.length, 0);
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end", behavior: "smooth" });
  }, [messages.length, partCount]);

  return (
    <div className={cn("flex flex-col gap-[18px]", className)}>
      {messages.map((message, index) => {
        const isUser = message.role === "user";
        const isLast = index === lastIndex;
        // Question cards go read-only once the user has replied to them, which
        // is a property of where the message sits, not of the thread as a whole.
        const answeredHere = messages.slice(index + 1).some((later) => later.role === "user");

        if (isUser) {
          const text = message.parts
            .filter((part) => part.type === "text")
            .map((part) => (part as { text: string }).text)
            .join("\n");
          const images = message.parts.filter(
            (part) => part.type === "file" && (part as { mediaType?: string }).mediaType?.startsWith("image/"),
          );

          const answers = text ? parseAnswers(text) : null;

          return (
            <div key={message.id} className="flex flex-col items-end gap-1.5">
              {text &&
                (answers ? (
                  <AnswerSummary
                    pairs={answers}
                    className="max-w-[85%] rounded-2xl bg-surface-2 px-3.5 py-3 text-left"
                  />
                ) : (
                  <p className="max-w-[85%] rounded-2xl bg-surface-2 px-3.5 py-2.5 text-[14px] leading-[1.55] whitespace-pre-wrap text-fg">
                    {text}
                  </p>
                ))}
              {images.length > 0 && (
                <div className="flex flex-wrap justify-end gap-2">
                  {images.map((part, imageIndex) => (
                    <MessagePart
                      key={`${message.id}-img-${imageIndex}`}
                      part={part}
                      last={false}
                      context={context}
                    />
                  ))}
                </div>
              )}
            </div>
          );
        }

        return (
          <div
            key={message.id}
            className="flex flex-col gap-2.5"
            aria-live={isLast && context.streaming ? "polite" : undefined}
          >
            {message.parts.map((part, partIndex) => (
              <MessagePart
                key={`${message.id}-${partIndex}`}
                part={part}
                last={isLast && partIndex === message.parts.length - 1}
                context={{ ...context, answered: answeredHere }}
              />
            ))}
          </div>
        );
      })}
      <div ref={endRef} />
    </div>
  );
}
