"use client";

import { ArrowRight } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Skeleton } from "@/components/ui/skeleton";
import { useProjects } from "@/lib/api/hooks";
import { formatRelative } from "@/lib/time";
import { ProjectThumbnail } from "./project-thumbnail";

/** Enough to recognise the work, few enough to stay one glance. */
const SHOWN = 3;

/**
 * The three projects you touched last.
 *
 * The dashboard used to greet a returning user with three generic starters and
 * nothing of their own, which is backwards once they have any work: the most
 * likely reason to be here is to carry on with something. Now that the API
 * exposes a screenshot per project, the strip is recognisable at a glance
 * rather than a list of names.
 *
 * Renders nothing at all for a new account, so the empty state stays the one
 * the composer already gives.
 */
export function DashboardRecents() {
  const projects = useProjects({ sort: "updated", order: "desc" });

  // `formatRelative` reads the clock, so rendering it on the server would bake
  // a timestamp into the HTML that is already wrong when it arrives. Held null
  // until after hydration, and set in a frame callback rather than the effect
  // body, exactly as the projects list does it.
  const [now, setNow] = useState<number | null>(null);
  useEffect(() => {
    const id = requestAnimationFrame(() => setNow(Date.now()));
    return () => cancelAnimationFrame(id);
  }, []);

  if (projects.status === "loading") {
    return (
      <section className="mt-10 text-left">
        <Skeleton className="h-4 w-28" />
        <div className="mt-3 grid grid-cols-[repeat(auto-fit,minmax(min(200px,100%),1fr))] gap-3">
          {Array.from({ length: SHOWN }, (_, index) => (
            <Skeleton key={index} className="h-[148px] rounded-2xl" />
          ))}
        </div>
      </section>
    );
  }

  // An error here is not worth a panel: the composer above still works, and the
  // sidebar and /projects both report the same failure properly.
  if (projects.status === "error" || projects.data.length === 0) return null;

  const recent = projects.data.slice(0, SHOWN);

  return (
    <section className="mt-10 text-left">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-[13px] font-bold tracking-[0.06em] text-muted-3 uppercase">Jump back in</h2>
        <Link
          href="/projects"
          className="group flex items-center gap-1 text-[13px] font-semibold text-muted transition-colors hover:text-fg"
        >
          All projects
          <ArrowRight aria-hidden className="size-3.5 transition-transform group-hover:translate-x-0.5" />
        </Link>
      </div>

      <ul className="mt-3 grid grid-cols-[repeat(auto-fit,minmax(min(200px,100%),1fr))] gap-3">
        {recent.map((project) => (
          <li key={project.id}>
            <Link
              href={`/projects/${project.id}`}
              className="group block overflow-hidden rounded-2xl border border-line-2 bg-surface transition-colors hover:border-line-3"
            >
              <ProjectThumbnail
                name={project.name}
                screenshotUrl={project.thumbnail_url}
                badge={
                  project.turn_status === "running"
                    ? "Building"
                    : project.mode === "plan"
                      ? "Planning"
                      : undefined
                }
                className="w-full rounded-none border-0 border-b border-line"
              />
              <span className="block px-3.5 py-2.5">
                <span className="block truncate text-sm font-semibold text-fg">{project.name}</span>
                <span className="mt-px block truncate text-xs text-muted-3">
                  {now === null ? " " : `Edited ${formatRelative(Date.parse(project.updated_at), now)}`}
                </span>
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
