"use client";

import { Check, MoreHorizontal, Star } from "lucide-react";
import Link from "next/link";
import { Avatar } from "@/components/ui/avatar";
import { Menu } from "@/components/ui/menu";
import { cn } from "@/lib/cn";
import { DEFAULT_ACCOUNT } from "./data";
import type { Project } from "@/lib/api/types";
import { formatRelative } from "@/lib/time";
import { ProjectThumbnail } from "./project-thumbnail";
import { projectMenuItems, type ProjectActions } from "./project-card";

const dateFormat = new Intl.DateTimeFormat("en", { dateStyle: "medium" });

export const LIST_GRID = "grid grid-cols-[1fr_auto] md:grid-cols-[1fr_150px_190px_auto] items-center gap-4";

export function ProjectRowHeader() {
  return (
    <div
      className={cn(
        LIST_GRID,
        "border-b border-line px-3 pb-2 text-[11px] font-semibold tracking-[0.08em] text-muted-3 uppercase",
      )}
    >
      <span>Name</span>
      <span className="hidden md:block">Created</span>
      <span className="hidden md:block">Owner</span>
      <span />
    </div>
  );
}

type Props = {
  project: Project;
  starred: boolean;
  actions: ProjectActions;
  selecting: boolean;
  selected: boolean;
  onToggleSelect: (id: string) => void;
  now: number | null;
};

export function ProjectRow({ project, starred, actions, selecting, selected, onToggleSelect, now }: Props) {
  return (
    <li
      className={cn(
        LIST_GRID,
        "group/row rounded-xl border border-transparent px-3 py-2.5 transition-colors hover:border-line-2 hover:bg-surface",
        selected && "border-accent/50 bg-surface",
      )}
    >
      <div className="flex min-w-0 items-center gap-3">
        {selecting && (
          <button
            type="button"
            role="checkbox"
            aria-checked={selected}
            aria-label={`Select ${project.name}`}
            onClick={() => onToggleSelect(project.id)}
            className={cn(
              "flex size-5 flex-none cursor-pointer items-center justify-center rounded-md border text-[11px] font-bold",
              selected ? "border-transparent bg-accent text-bg" : "border-line-3",
            )}
          >
            {selected && <Check className="size-3" />}
          </button>
        )}
        <Link
          href={`/projects/${project.id}`}
          onClick={(event) => {
            if (!selecting) return;
            event.preventDefault();
            onToggleSelect(project.id);
          }}
          className="flex min-w-0 items-center gap-3 outline-none focus-visible:underline"
        >
          <ProjectThumbnail name={project.name} screenshotUrl={project.thumbnail_url} className="w-16 flex-none" />
          <span className="min-w-0">
            <span className="block truncate text-sm font-semibold text-fg">{project.name}</span>
            <span className="block truncate text-xs text-muted">
              {now === null ? " " : `Edited ${formatRelative(Date.parse(project.updated_at), now)}`}
            </span>
          </span>
        </Link>
      </div>

      <span className="hidden text-[13px] text-muted md:block">
        {now === null ? " " : dateFormat.format(Date.parse(project.created_at))}
      </span>

      <span className="hidden items-center gap-2 md:flex">
        <Avatar name={DEFAULT_ACCOUNT.firstName} size="sm" />
        <span className="truncate text-[13px] text-muted">{DEFAULT_ACCOUNT.firstName}</span>
      </span>

      <span className="flex flex-none items-center">
        <button
          type="button"
          aria-pressed={starred}
          aria-label={starred ? `Unstar ${project.name}` : `Star ${project.name}`}
          onClick={() => actions.onStar(project)}
          className={cn(
            "cursor-pointer px-1.5 py-1 text-xs transition-colors",
            starred ? "text-fg" : "text-muted-3 hover:text-fg",
          )}
        >
          <Star aria-hidden className={cn("size-3.5", starred && "fill-current")} />
        </button>
        {!selecting && (
          <Menu
            ariaLabel={`Actions for ${project.name}`}
            align="end"
            label={
              <span className="block px-1.5 py-1 text-muted-2 hover:text-fg">
                <MoreHorizontal aria-hidden className="size-4" />
              </span>
            }
            items={projectMenuItems(project, starred, actions)}
          />
        )}
      </span>
    </li>
  );
}
