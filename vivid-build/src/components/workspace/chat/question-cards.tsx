"use client";

import { ArrowLeft, Check, Pencil } from "lucide-react";
import { useState } from "react";
import { cn } from "@/lib/cn";
import { buttonClass } from "@/lib/ui";

export type Question = {
  id: string;
  question: string;
  options?: string[];
  allow_free_text?: boolean;
};

/** The `ask_user` tool's input, defensively — it comes off the wire. */
export function parseQuestions(input: unknown): Question[] {
  const list = (input as { questions?: unknown })?.questions;
  if (!Array.isArray(list)) return [];
  return list.flatMap((raw) => {
    const item = raw as Partial<Question>;
    if (typeof item?.question !== "string") return [];
    return [
      {
        id: typeof item.id === "string" ? item.id : item.question,
        question: item.question,
        options: Array.isArray(item.options) ? item.options.filter((o): o is string => typeof o === "string") : [],
        allow_free_text: item.allow_free_text !== false,
      },
    ];
  });
}

/**
 * The planning questions, asked one at a time.
 *
 * Showing all of them at once turns a conversation into a form — the whole
 * point of the agent asking is that it feels like being asked. Picking an
 * option advances immediately, and the last step is a review of everything
 * before it is sent, because the answers go as a single message that cannot be
 * taken back.
 *
 * The wire format is still §4's "Question -> Answer", one pair per line.
 */
export function QuestionCards({
  questions,
  answered,
  onSend,
}: {
  questions: Question[];
  /** True once a later user message exists, so this is history, not a prompt. */
  answered: boolean;
  onSend: (text: string) => void;
}) {
  const [choices, setChoices] = useState<Record<string, string>>({});
  const [step, setStep] = useState(0);
  const [draft, setDraft] = useState("");

  const reviewing = step >= questions.length;
  const current = questions[step];

  const pairs = questions
    .filter((question) => choices[question.id]?.trim())
    .map((question) => ({ question: question.question, answer: choices[question.id].trim() }));

  const goTo = (index: number) => {
    setStep(index);
    setDraft(index < questions.length ? (choices[questions[index].id] ?? "") : "");
  };

  const answer = (value: string) => {
    if (!current) return;
    setChoices((all) => ({ ...all, [current.id]: value }));
    setStep(step + 1);
    setDraft(step + 1 < questions.length ? (choices[questions[step + 1].id] ?? "") : "");
  };

  const send = () => {
    if (pairs.length) onSend(pairs.map((pair) => `${pair.question} -> ${pair.answer}`).join("\n"));
  };

  // Once the conversation has moved on, the card is a record of what was asked
  // — not something to fill in again.
  //
  // It deliberately does not repeat the answers. The user's own message sits
  // directly below carrying the same "question -> answer" pairs, so rendering
  // them here printed the whole set twice, one bubble apart.
  if (answered) {
    return (
      <div className="rounded-2xl border border-line-2 bg-surface p-4">
        <p className="mb-2 text-[11px] font-bold tracking-[0.08em] text-muted-3 uppercase">
          Answered · {questions.length} question{questions.length === 1 ? "" : "s"}
        </p>
        <ul className="flex flex-col gap-1.5">
          {questions.map((question) => (
            <li key={question.id} className="text-[13px] leading-[1.5] text-muted">
              {question.question}
            </li>
          ))}
        </ul>
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-2xl border border-line-2 bg-surface">
      <div className="flex items-center gap-2 border-b border-line px-4 py-2.5">
        {step > 0 && (
          <button
            type="button"
            onClick={() => goTo(step - 1)}
            aria-label="Previous question"
            className="flex cursor-pointer items-center rounded-md p-0.5 text-muted-2 transition-colors hover:text-fg"
          >
            <ArrowLeft aria-hidden className="size-3.5" />
          </button>
        )}
        <p className="flex-1 text-[11px] font-bold tracking-[0.1em] text-muted-3 uppercase">
          {reviewing ? "Check your answers" : `Question ${step + 1} of ${questions.length}`}
        </p>
        <div aria-hidden className="flex gap-1">
          {questions.map((question, index) => (
            <span
              key={question.id}
              className={cn(
                "block size-1.5 rounded-full transition-colors",
                index < step || reviewing ? "bg-accent" : index === step ? "bg-muted-2" : "bg-line-3",
              )}
            />
          ))}
        </div>
      </div>

      {reviewing ? (
        <div className="flex flex-col gap-4 px-4 py-3.5">
          {pairs.length === 0 ? (
            <p className="text-sm text-muted">You skipped every question. Go back, or just say what you want below.</p>
          ) : (
            <ul className="flex flex-col gap-3">
              {questions.map((question, index) =>
                choices[question.id]?.trim() ? (
                  <li key={question.id} className="flex items-start gap-2.5">
                    <div className="min-w-0 flex-1">
                      <p className="text-[11px] leading-[1.4] font-semibold text-muted-2">{question.question}</p>
                      <p className="text-[14px] leading-[1.5] text-fg">{choices[question.id]}</p>
                    </div>
                    <button
                      type="button"
                      onClick={() => goTo(index)}
                      aria-label={`Change answer to ${question.question}`}
                      className="flex flex-none cursor-pointer items-center gap-1 rounded-lg px-2 py-1 text-[12px] font-semibold text-muted transition-colors hover:bg-surface-2 hover:text-fg"
                    >
                      <Pencil aria-hidden className="size-3" />
                      Change
                    </button>
                  </li>
                ) : null,
              )}
            </ul>
          )}

          <div className="flex flex-wrap gap-2.5">
            <button
              type="button"
              disabled={!pairs.length}
              onClick={send}
              className={buttonClass({ size: "sm", className: "disabled:cursor-not-allowed disabled:opacity-50" })}
            >
              Send answers
            </button>
            <button
              type="button"
              onClick={() => goTo(questions.length - 1)}
              className={buttonClass({ variant: "secondary", size: "sm" })}
            >
              Back
            </button>
          </div>
        </div>
      ) : (
        current && (
          <div className="px-4 py-3.5">
            <p className="text-sm font-semibold text-fg">{current.question}</p>

            {current.options && current.options.length > 0 && (
              <div className="mt-3 flex flex-col gap-2">
                {current.options.map((option) => {
                  const chosen = choices[current.id] === option;
                  return (
                    <button
                      key={option}
                      type="button"
                      onClick={() => answer(option)}
                      className={cn(
                        "flex cursor-pointer items-center gap-2 rounded-xl border px-3.5 py-2.5 text-left text-[13px] font-semibold transition-colors",
                        chosen
                          ? "border-accent bg-surface-2 text-fg"
                          : "border-line-2 text-fg-2 hover:border-line-3 hover:bg-surface-2/60 hover:text-fg",
                      )}
                    >
                      <span
                        aria-hidden
                        className={cn(
                          "flex size-4 flex-none items-center justify-center rounded-full border",
                          chosen ? "border-transparent bg-accent text-bg" : "border-line-3",
                        )}
                      >
                        {chosen && <Check className="size-2.5 stroke-[3]" />}
                      </span>
                      <span className="min-w-0 flex-1">{option}</span>
                    </button>
                  );
                })}
              </div>
            )}

            {current.allow_free_text && (
              <div className="mt-2.5 flex flex-wrap items-center gap-2">
                <input
                  value={draft}
                  onChange={(event) => setDraft(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key !== "Enter" || !draft.trim()) return;
                    event.preventDefault();
                    answer(draft.trim());
                  }}
                  placeholder={current.options?.length ? "Or say it in your own words" : "Your answer"}
                  className="min-w-0 flex-1 rounded-xl border border-line-2 bg-surface-2 px-3 py-2.5 text-sm text-fg outline-none transition-colors focus-visible:border-line-3"
                />
                {draft.trim() && (
                  <button
                    type="button"
                    onClick={() => answer(draft.trim())}
                    className={buttonClass({ size: "sm" })}
                  >
                    Next
                  </button>
                )}
              </div>
            )}

            <button
              type="button"
              onClick={() => setStep(step + 1)}
              className="mt-3 cursor-pointer text-[12px] font-semibold text-muted-3 transition-colors hover:text-fg"
            >
              Skip this one
            </button>
          </div>
        )
      )}
    </div>
  );
}
