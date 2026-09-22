import { cn } from "@/lib/cn";

/**
 * The "Question -> Answer" message the question cards send.
 *
 * §4 asks for that exact wire format because the model reads it well, but shown
 * raw it looks like a machine transcript. This renders the same text as the
 * pairs it actually is, without changing a byte of what was sent.
 */
const PAIR = /^(.+?)\s*->\s*(.+)$/;

export function parseAnswers(text: string): { question: string; answer: string }[] | null {
  const lines = text.split("\n").filter((line) => line.trim());
  if (lines.length === 0) return null;

  const pairs = lines.map((line) => PAIR.exec(line.trim()));
  // All or nothing: one stray line means this is ordinary prose that happens to
  // contain an arrow.
  if (pairs.some((match) => !match)) return null;

  return pairs.map((match) => ({ question: match![1].trim(), answer: match![2].trim() }));
}

export function AnswerSummary({
  pairs,
  className,
}: {
  pairs: { question: string; answer: string }[];
  className?: string;
}) {
  return (
    <dl className={cn("flex flex-col gap-2.5", className)}>
      {pairs.map((pair) => (
        <div key={pair.question} className="flex flex-col gap-0.5">
          <dt className="text-[11px] leading-[1.4] font-semibold text-muted-2">{pair.question}</dt>
          <dd className="text-[14px] leading-[1.5] text-fg">{pair.answer}</dd>
        </div>
      ))}
    </dl>
  );
}
