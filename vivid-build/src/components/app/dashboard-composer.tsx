"use client";

import { ArrowUp, CalendarCheck, ShoppingBag, UserRoundCog } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { useToast } from "@/components/ui/toast";
import { createProject } from "@/lib/api/endpoints";
import { setFirstMessage } from "@/lib/api/first-message";
import { cn } from "@/lib/cn";
import { takePendingPrompt } from "@/lib/pending-prompt";
import { DASHBOARD_CHIPS, PROJECT_TEMPLATES, type ProjectTemplate } from "./data";

/**
 * The panel above each starter used to be a gradient from --surface2 to --bg:
 * on the dark theme that is two near-blacks, so all three read as empty boxes.
 * An icon says what the starter is before the label does.
 */
const TEMPLATE_ICONS: Record<ProjectTemplate["icon"], typeof ShoppingBag> = {
  store: ShoppingBag,
  portal: UserRoundCog,
  booking: CalendarCheck,
};

const MAX_INPUT_HEIGHT = 220;

export function DashboardComposer() {
  const router = useRouter();
  const { toast } = useToast();
  const [prompt, setPrompt] = useState("");
  const [isPending, setPending] = useState(false);
  /** §2: build mode straight away, for people who already know what they want. */
  const [skipPlan, setSkipPlan] = useState(false);
  const promptId = useId();
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Picks up a prompt typed on the landing page before signing in. Deferred
  // rather than read during render: /dashboard is prerendered, so touching
  // sessionStorage that early would desync the hydrated markup.
  useEffect(() => {
    const id = window.setTimeout(() => {
      const pending = takePendingPrompt();
      if (pending) setPrompt(pending);
    }, 0);
    return () => window.clearTimeout(id);
  }, []);

  /**
   * Grow with the text rather than reserving three rows up front.
   *
   * The box used to be a fixed three rows tall, so the empty state was a wall
   * of nothing between the placeholder and the chips. Measured in a layout
   * effect so the height is right on the frame the text changes, never a frame
   * late.
   */
  useLayoutEffect(() => {
    const input = inputRef.current;
    if (!input) return;
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, MAX_INPUT_HEIGHT)}px`;
  }, [prompt]);

  /**
   * Creating a project and describing it are two steps now: the API takes a
   * name, and the prompt is the first chat turn. The prompt is parked for the
   * workspace to send on arrival, so the one-box flow still feels like one step.
   */
  const build = async (text: string) => {
    const request = text.trim();
    if (!request || isPending) return;
    setPending(true);
    try {
      // No name: the plan writes the app's own name once it has the spec, and
      // the published URL slug follows it. Sending the first six words of the
      // prompt is what produced projects called "A delivery tracking page for a".
      const project = await createProject(null, skipPlan);
      setFirstMessage(project.id, request);
      router.push(`/projects/${project.id}`);
    } catch (error) {
      setPending(false);
      toast(error instanceof Error ? error.message : "Could not start that project", "warn");
    }
  };

  const skipId = `${promptId}-skip`;
  const ready = prompt.trim().length > 0;

  return (
    <>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void build(prompt);
        }}
        className="mt-7 overflow-hidden rounded-[20px] border border-line-2 bg-surface text-left shadow-[0_1px_0_0_var(--line)_inset] transition-colors focus-within:border-line-3"
      >
        <label htmlFor={promptId} className="sr-only">
          Describe what to build
        </label>
        <textarea
          ref={inputRef}
          id={promptId}
          rows={2}
          value={prompt}
          onChange={(event) => setPrompt(event.target.value)}
          onKeyDown={(event) => {
            // Enter builds, Shift+Enter adds a line.
            if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              event.currentTarget.form?.requestSubmit();
            }
          }}
          placeholder="Ask VividBuild to build a storefront for your shoe brand"
          className="block w-full resize-none bg-transparent px-[18px] pt-[18px] pb-2 text-base leading-[1.5] text-fg outline-none placeholder:text-muted-3"
        />

        {/* Suggestions sit with the input they fill in, above the controls that
            act on it. Mixing all three into one wrapping row is what pushed the
            Build button onto a line of its own. */}
        <div className="flex flex-wrap gap-2 px-[18px] pb-3.5">
          {DASHBOARD_CHIPS.map((chip) => (
            <button
              key={chip}
              type="button"
              onClick={() => {
                setPrompt(chip);
                inputRef.current?.focus();
              }}
              className="cursor-pointer rounded-full border border-line-2 px-3 py-[7px] text-[13px] font-medium text-muted transition-colors hover:border-line-3 hover:text-fg"
            >
              {chip}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-3 border-t border-line bg-surface-2 px-[18px] py-2.5">
          <label
            htmlFor={skipId}
            title="Create straight into build mode, with no planning questions"
            className="flex cursor-pointer items-center gap-2 text-[13px] font-medium text-muted-3 transition-colors hover:text-fg-2"
          >
            <input
              id={skipId}
              type="checkbox"
              checked={skipPlan}
              onChange={(event) => setSkipPlan(event.target.checked)}
              className="size-[15px] flex-none accent-accent"
            />
            Skip planning
          </label>

          <span className="ml-auto hidden text-[12px] text-muted-3 sm:block">
            {/* A keyboard hint earns its place here: Enter is the fast path and
                nothing else on the page says so. */}
            Enter to build
          </span>

          <button
            type="submit"
            disabled={isPending || !ready}
            aria-label={isPending ? "Starting" : "Build"}
            className={cn(
              "flex size-9 flex-none cursor-pointer items-center justify-center rounded-full bg-btn text-btn-fg shadow-sheen transition-opacity",
              "disabled:cursor-not-allowed disabled:opacity-35",
              isPending && "disabled:cursor-wait",
            )}
          >
            <ArrowUp aria-hidden className="size-[18px]" strokeWidth={2.5} />
          </button>
        </div>
      </form>

      <ul className="mt-3.5 grid grid-cols-[repeat(auto-fit,minmax(min(200px,100%),1fr))] gap-2.5 text-left">
        {PROJECT_TEMPLATES.map((template) => {
          const Icon = TEMPLATE_ICONS[template.icon];
          return (
            <li key={template.name}>
              <button
                type="button"
                disabled={isPending}
                onClick={() => void build(template.prompt)}
                // The icon used to sit alone in a 96px panel above the label,
                // which on this palette read as an empty rectangle with some
                // text under it. Inline, the card is half the height and says
                // what it is at a glance.
                className="flex w-full cursor-pointer items-center gap-3 rounded-2xl border border-line-2 bg-surface px-3.5 py-3 text-left transition-colors hover:border-line-3 hover:bg-surface-2 disabled:cursor-wait disabled:opacity-70"
              >
                <span
                  aria-hidden
                  className="flex size-9 flex-none items-center justify-center rounded-xl bg-tint text-fg-2"
                >
                  <Icon className="size-[18px]" strokeWidth={1.75} />
                </span>
                <span className="min-w-0">
                  <span className="block truncate text-sm font-bold text-fg">{template.name}</span>
                  <span className="mt-px block truncate text-xs text-muted">{template.body}</span>
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </>
  );
}
