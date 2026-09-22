"use client";

import { Check, Copy, MoreHorizontal, Star } from "lucide-react";
import Link from "next/link";
import { Avatar } from "@/components/ui/avatar";
import { Menu } from "@/components/ui/menu";
import { cn } from "@/lib/cn";
import type { Project } from "@/lib/api/types";
import { formatRelative } from "@/lib/time";
import { ProjectThumbnail } from "./project-thumbnail";

export type ProjectActions = {
  onStar: (project: Project) => void;
  onCopyLink: (project: Project) => void;
  onRename: (project: Project) => void;
  onSettings: (project: Project) => void;
  onDelete: (project: Project) => void;
};

export function projectMenuItems(project: Project, starred: boolean, actions: ProjectActions) {
  return [
    {
      label: "Open in new tab",
      onSelect: () => window.open(`/projects/${project.id}`, "_blank", "noopener"),
    },
    { label: "Copy link", onSelect: () => actions.onCopyLink(project) },
    { label: starred ? "Remove from starred" : "Star", onSelect: () => actions.onStar(project) },
    { type: "divider" as const },
    { label: "Rename", onSelect: () => actions.onRename(project) },
    { label: "Project settings", onSelect: () => actions.onSettings(project) },
    { type: "divider" as const },
    { label: "Delete", danger: true, onSelect: () => actions.onDelete(project) },
  ];
}

type Props = {
  project: Project;
  /** Favourites are a per-device flag, so they arrive alongside rather than on the project. */
  starred: boolean;
  actions: ProjectActions;
  selecting: boolean;
  selected: boolean;
  onToggleSelect: (id: string) => void;
  /** Null until hydrated, so the clock is never read during SSR. */
  now: number | null;
};

export function ProjectCard({ project, starred, actions, selecting, selected, onToggleSelect, now }: Props) {
  return (
    <li className="group/card relative">
      <Link
        href={`/projects/${project.id}`}
        onClick={(event) => {
          if (!selecting) return;
          event.preventDefault();
          onToggleSelect(project.id);
        }}
        className="block rounded-xl outline-none focus-visible:ring-2 focus-visible:ring-accent"
      >
        <ProjectThumbnail
          name={project.name}
          screenshotUrl={project.thumbnail_url}
          badge={
            project.turn_status === "running"
              ? "Building"
              : project.mode === "plan"
                ? "Planning"
                : project.published_url
                  ? "Live"
                  : "Built"
          }
          className={cn("w-full transition-colors", selected && "ring-2 ring-accent")}
        />
      </Link>

      {selecting ? (
        <button
          type="button"
          role="checkbox"
          aria-checked={selected}
          aria-label={`Select ${project.name}`}
          onClick={() => onToggleSelect(project.id)}
          className={cn(
            "absolute top-3 left-3 flex size-5 cursor-pointer items-center justify-center rounded-md border text-[11px] font-bold",
            selected ? "border-transparent bg-accent text-bg" : "border-line-3 bg-surface/80 backdrop-blur-sm",
          )}
        >
          {selected && <Check className="size-3" />}
        </button>
      ) : (
        <button
          type="button"
          aria-pressed={starred}
          aria-label={starred ? `Unstar ${project.name}` : `Star ${project.name}`}
          onClick={() => actions.onStar(project)}
          className={cn(
            "absolute top-3 right-3 cursor-pointer rounded-lg border border-line-2 bg-surface/85 px-2 py-1 text-xs backdrop-blur-sm transition-opacity",
            // Starred stays visible; the rest appear on hover or keyboard focus.
            starred
              ? "text-fg opacity-100"
              : "text-muted-2 opacity-0 group-hover/card:opacity-100 focus-visible:opacity-100 hover:text-fg",
          )}
        >
          <Star aria-hidden className={cn("size-3.5", starred && "fill-current")} />
        </button>
      )}

      <div className="mt-3 flex items-center gap-2.5">
        <Avatar name={project.name} size="sm" />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold text-fg">{project.name}</p>
          <p className="truncate text-xs text-muted">
            {now === null ? " " : `Edited ${formatRelative(Date.parse(project.updated_at), now)}`}
          </p>
        </div>

        {!selecting && (
          <div className="flex flex-none items-center opacity-0 transition-opacity group-hover/card:opacity-100 focus-within:opacity-100">
            <button
              type="button"
              onClick={() => actions.onCopyLink(project)}
              aria-label={`Copy link to ${project.name}`}
              className="cursor-pointer px-1.5 py-1 text-muted-2 transition-colors hover:text-fg"
            >
              <Copy aria-hidden className="size-4" />
            </button>
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
          </div>
        )}
      </div>
    </li>
  );
}
