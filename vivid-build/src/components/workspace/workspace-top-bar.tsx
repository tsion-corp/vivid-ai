"use client";

import {
  ChevronDown,
  ExternalLink,
  FolderOpen,
  History,
  Link2,
  Maximize2,
  PanelLeftClose,
  PanelLeftOpen,
  Pencil,
  RotateCw,
  Settings,
  Trash2,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { WORKSPACE_TABS, type WorkspaceTab } from "@/components/app/data";
import { Menu } from "@/components/ui/menu";
import type { Project } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import type { PreviewDevice } from "@/lib/preview/render";
import { DeviceControls } from "./device-controls";

const iconButton =
  "flex cursor-pointer items-center rounded-lg px-2 py-1.5 text-muted transition-colors hover:bg-surface hover:text-fg";

type Props = {
  project: Project;
  tab: WorkspaceTab;
  onTabChange: (tab: WorkspaceTab) => void;
  device: PreviewDevice;
  preset: string;
  onDeviceChange: (device: PreviewDevice, preset: string) => void;
  onReload: () => void;
  chatOpen: boolean;
  onToggleChat: () => void;
  publishing: boolean;
  onPublish: () => void;
  copied: boolean;
  onShare: () => void;
  onRename: () => void;
  onDelete: () => void;
};

/** One bar across the whole workspace — project, tabs and preview controls. */
export function WorkspaceTopBar({
  project,
  tab,
  onTabChange,
  device,
  preset,
  onDeviceChange,
  onReload,
  chatOpen,
  onToggleChat,
  publishing,
  onPublish,
  copied,
  onShare,
  onRename,
  onDelete,
}: Props) {
  const router = useRouter();
  const built = project.mode === "build";

  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5 border-b border-line bg-bg-2 px-3 py-2">
      <Menu
        ariaLabel="Project menu"
        className="min-w-0"
        label={
          <span className="flex min-w-0 items-center gap-1.5 rounded-lg px-2 py-1.5 text-sm font-bold text-fg transition-colors hover:bg-surface">
            <span className="truncate">{project.name}</span>
            <ChevronDown aria-hidden className="size-3.5 flex-none text-muted-2" />
          </span>
        }
        items={[
          // The first four exist for the phone, where the icon row and the
          // History button are hidden. On a wider screen they duplicate visible
          // controls, which costs nothing and keeps one menu rather than two.
          ...(built
            ? [
                {
                  label: "Open preview full screen",
                  icon: <Maximize2 className="size-4" />,
                  onSelect: () => router.push(`/preview/${project.id}`),
                },
                { label: "Reload preview", icon: <RotateCw className="size-4" />, onSelect: onReload },
              ]
            : []),
          { label: "History", icon: <History className="size-4" />, onSelect: () => onTabChange("history") },
          { label: copied ? "Link copied" : "Share", icon: <Link2 className="size-4" />, onSelect: onShare },
          { type: "divider" as const },
          { label: "Rename", icon: <Pencil className="size-4" />, onSelect: onRename },
          {
            label: "Project settings",
            icon: <Settings className="size-4" />,
            onSelect: () => router.push(`/settings/project/general?project=${project.id}`),
          },
          { label: "All projects", icon: <FolderOpen className="size-4" />, onSelect: () => router.push("/projects") },
          ...(project.published_url
            ? [
                {
                  label: "View published site",
                  icon: <ExternalLink className="size-4" />,
                  onSelect: () => window.open(project.published_url!, "_blank", "noopener"),
                },
              ]
            : []),
          { type: "divider" as const },
          { label: "Delete project", icon: <Trash2 className="size-4" />, danger: true, onSelect: onDelete },
        ]}
      />

      <button
        type="button"
        onClick={onToggleChat}
        aria-label={chatOpen ? "Hide chat" : "Show chat"}
        className={cn(iconButton, "hidden lg:flex")}
      >
        {chatOpen ? (
          <PanelLeftClose aria-hidden className="size-4" />
        ) : (
          <PanelLeftOpen aria-hidden className="size-4" />
        )}
      </button>

      <button
        type="button"
        onClick={() => onTabChange("history")}
        aria-label="History"
        className={cn(iconButton, "hidden lg:flex", tab === "history" && "bg-surface text-fg")}
      >
        <History aria-hidden className="size-4" />
      </button>

      {/* Hidden on mobile: the pane switcher below merges these with Chat into
          one control, because two rows of navigation doing one job is most of a
          phone screen spent on chrome. */}
      <div
        role="tablist"
        aria-label="Workspace tools"
        className="hidden gap-1 rounded-full border border-line-2 p-1 lg:flex"
      >
        {WORKSPACE_TABS.filter((item) => item.key !== "history").map((item) => (
          <button
            key={item.key}
            type="button"
            role="tab"
            aria-selected={tab === item.key}
            onClick={() => onTabChange(item.key)}
            className={cn(
              "cursor-pointer rounded-full px-3 py-1 text-[13px] font-semibold whitespace-nowrap transition-colors",
              tab === item.key ? "bg-surface-2 text-fg" : "text-muted hover:text-fg",
            )}
          >
            {item.label}
          </button>
        ))}
      </div>

      <div className="ml-auto flex min-w-0 items-center gap-2">
        {tab === "preview" && built && (
          <div className="hidden items-center gap-2 sm:flex">
            <DeviceControls
              device={device}
              preset={preset}
              onChange={onDeviceChange}
              className="hidden sm:flex"
            />

            <button type="button" onClick={onReload} aria-label="Reload preview" className={iconButton}>
              <RotateCw aria-hidden className="size-4" />
            </button>

            <Link
              href={`/preview/${project.id}`}
              aria-label="Open preview full screen"
              title="Open full screen"
              className={iconButton}
            >
              <Maximize2 aria-hidden className="size-4" />
            </Link>
          </div>
        )}

        {project.published_url && (
          <a
            href={project.published_url}
            data-desktop-only
            target="_blank"
            rel="noreferrer noopener"
            title={project.published_url}
            className="hidden max-w-[220px] items-center gap-1.5 rounded-lg border border-line-2 bg-surface px-2.5 py-1.5 text-[13px] font-semibold text-fg-2 transition-colors hover:text-fg sm:flex"
          >
            <span aria-hidden className="size-1.5 flex-none rounded-full bg-[#4ade80]" />
            <span className="truncate">{project.published_url.replace(/^https?:\/\//, "")}</span>
            <ExternalLink aria-hidden className="size-3.5 flex-none text-muted-2" />
          </a>
        )}

        <button
          type="button"
          onClick={onShare}
          className="hidden cursor-pointer rounded-lg border border-line-2 px-3 py-1.5 text-[13px] font-semibold whitespace-nowrap text-fg-2 transition-colors hover:text-fg sm:block"
        >
          {copied ? "Copied" : "Share"}
        </button>
        <button
          type="button"
          onClick={onPublish}
          disabled={!built || publishing}
          title={built ? undefined : "Approve the spec first"}
          className="cursor-pointer rounded-lg bg-btn px-3.5 py-1.5 text-[13px] font-bold whitespace-nowrap text-btn-fg disabled:cursor-not-allowed disabled:opacity-60"
        >
          {publishing ? "Publishing…" : project.published_url ? "Republish" : "Publish"}
        </button>
      </div>
    </div>
  );
}
