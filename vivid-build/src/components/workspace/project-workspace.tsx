"use client";

import type { UIMessage } from "ai";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useState } from "react";
import { parseTab } from "@/components/app/data";
import { Dialog } from "@/components/ui/dialog";
import { inputClass } from "@/components/settings/field";
import { useToast } from "@/components/ui/toast";
import { deleteProject, getPublish, key, publish, updateProject } from "@/lib/api/endpoints";
import { invalidate } from "@/lib/api/cache";
import type { Project } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { DEFAULT_PRESET, type PreviewDevice } from "@/lib/preview/render";
import { buttonClass } from "@/lib/ui";
import { ChatPanel } from "./chat/chat-panel";
import { WorkPanel } from "./work-panel";
import { WorkspaceTopBar } from "./workspace-top-bar";

/** The phone's whole workspace navigation. History lives in the project menu. */
const MOBILE_NAV = [
  { key: "chat", label: "Chat" },
  { key: "preview", label: "Preview" },
  { key: "code", label: "Code" },
  { key: "more", label: "More" },
] as const;

type Pane = "chat" | "work";

const POLL_MS = 4000;

export function ProjectWorkspace({
  project,
  initialMessages,
}: {
  project: Project;
  initialMessages: UIMessage[];
}) {
  const searchParams = useSearchParams();
  const router = useRouter();
  const { toast } = useToast();

  const tab = parseTab(searchParams.get("tab"));
  const selectedFile = searchParams.get("file");

  const [pane, setPane] = useState<Pane>("chat");
  const [chatOpen, setChatOpen] = useState(true);
  const [device, setDevice] = useState<PreviewDevice>("desktop");
  const [preset, setPreset] = useState(DEFAULT_PRESET.desktop);
  const [nonce, setNonce] = useState(0);
  const [copied, setCopied] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [draftName, setDraftName] = useState(project.name);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [chatRequest, setChatRequest] = useState<{ text: string; at: number } | null>(null);

  const updateQuery = useCallback(
    (updates: Record<string, string>) => {
      const params = new URLSearchParams(searchParams.toString());
      for (const [key, value] of Object.entries(updates)) params.set(key, value);
      window.history.replaceState(null, "", `?${params.toString()}`);
    },
    [searchParams],
  );

  const reloadPreview = useCallback(() => setNonce((n) => n + 1), []);

  const share = () => {
    navigator.clipboard
      ?.writeText(window.location.href)
      .then(() => {
        setCopied(true);
        window.setTimeout(() => setCopied(false), 2000);
      })
      .catch(() => {});
  };

  /**
   * Publishing is a background job: the POST returns "pending" and the row has
   * to be polled until it goes live or fails.
   */
  const startPublish = async () => {
    setPublishing(true);
    try {
      const created = await publish(project.id);
      toast("Publishing — this takes a minute or two");

      for (let attempt = 0; attempt < 60; attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, POLL_MS));
        const current = await getPublish(project.id, created.id);
        if (current.status === "live") {
          toast(`Live at ${current.url?.replace(/^https?:\/\//, "") ?? "your URL"}`);
          // published_url lives on the project row, and the workspace is
          // rendering a cached copy of it — without this the live link never
          // appears until a reload.
          invalidate(key.project(project.id));
          invalidate(key.projects);
          return;
        }
        if (current.status === "failed") {
          toast(current.error ? `Publish failed: ${current.error.slice(0, 120)}` : "Publish failed", "warn");
          return;
        }
      }
      toast("Still publishing. Check the project settings for the link.");
    } catch (error) {
      toast(error instanceof Error ? error.message : "Could not publish", "warn");
    } finally {
      setPublishing(false);
    }
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <WorkspaceTopBar
        project={project}
        tab={tab}
        onTabChange={(next) => updateQuery({ tab: next })}
        device={device}
        preset={preset}
        onDeviceChange={(nextDevice, nextPreset) => {
          setDevice(nextDevice);
          setPreset(nextPreset);
        }}
        onReload={reloadPreview}
        chatOpen={chatOpen}
        onToggleChat={() => setChatOpen((open) => !open)}
        publishing={publishing}
        onPublish={() => void startPublish()}
        copied={copied}
        onShare={share}
        onRename={() => {
          setDraftName(project.name);
          setRenaming(true);
        }}
        onDelete={() => setConfirmDelete(true)}
      />

      {/*
        One control, not two. A phone had a "Chat | Preview & tools" switcher
        stacked on top of a "Preview / Code / More" tab row — two rows of
        navigation choosing between four destinations. Merged, they cost one row
        and the preview gets the difference.
      */}
      <div
        role="tablist"
        aria-label="Workspace"
        className="flex gap-1 border-b border-line bg-bg-2 px-2 py-1.5 lg:hidden"
      >
        {MOBILE_NAV.map((item) => {
          const active = item.key === "chat" ? pane === "chat" : pane === "work" && tab === item.key;
          return (
            <button
              key={item.key}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => {
                if (item.key === "chat") {
                  setPane("chat");
                  return;
                }
                setPane("work");
                updateQuery({ tab: item.key });
              }}
              className={cn(
                "flex-1 cursor-pointer rounded-full px-2 py-1.5 text-[13px] font-semibold transition-colors",
                active ? "bg-surface-2 text-fg" : "text-muted",
              )}
            >
              {item.label}
            </button>
          );
        })}
      </div>

      <div className="flex min-h-0 flex-1">
        <ChatPanel
          className={cn(pane === "chat" ? "flex" : "hidden", chatOpen ? "lg:flex" : "lg:hidden")}
          project={project}
          initialMessages={initialMessages}
          onSnapshot={reloadPreview}
          request={chatRequest}
        />
        <WorkPanel
          className={cn(pane === "work" ? "flex" : "hidden", "lg:flex")}
          project={project}
          tab={tab}
          device={device}
          preset={preset}
          nonce={nonce}
          selectedFile={selectedFile}
          onFileSelect={(path) => updateQuery({ tab: "code", file: path })}
          onReloadPreview={reloadPreview}
          // "Fix this" is a chat turn, but it is raised from the preview pane —
          // the timestamp makes two identical errors two separate requests.
          onSend={(text) => {
            setChatRequest({ text, at: Date.now() });
            setPane("chat");
          }}
        />
      </div>

      {renaming && (
        <Dialog title="Rename project" size="sm" onClose={() => setRenaming(false)}>
          <div className="flex flex-col gap-4 px-5 py-4">
            <input
              autoFocus
              value={draftName}
              onChange={(event) => setDraftName(event.target.value)}
              className={inputClass}
            />
            <div className="flex justify-end gap-2.5">
              <button
                type="button"
                onClick={() => setRenaming(false)}
                className={buttonClass({ variant: "secondary", size: "sm" })}
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => {
                  setRenaming(false);
                  void updateProject(project.id, { name: draftName.trim() || project.name })
                    .then(() => toast("Project renamed"))
                    .catch((error: unknown) =>
                      toast(error instanceof Error ? error.message : "Could not rename", "warn"),
                    );
                }}
                className={buttonClass({ size: "sm" })}
              >
                Rename
              </button>
            </div>
          </div>
        </Dialog>
      )}

      {confirmDelete && (
        <Dialog
          title={`Delete ${project.name}?`}
          description="This kills the sandbox and removes every file and version. It cannot be undone."
          size="sm"
          onClose={() => setConfirmDelete(false)}
        >
          <div className="flex justify-end gap-2.5 px-5 py-4">
            <button
              type="button"
              onClick={() => setConfirmDelete(false)}
              className={buttonClass({ variant: "secondary", size: "sm" })}
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={() => {
                setConfirmDelete(false);
                void deleteProject(project.id)
                  .then(() => {
                    toast(`${project.name} deleted`, "warn");
                    router.push("/projects");
                  })
                  .catch((error: unknown) =>
                    toast(error instanceof Error ? error.message : "Could not delete", "warn"),
                  );
              }}
              className={buttonClass({ size: "sm" })}
            >
              Delete
            </button>
          </div>
        </Dialog>
      )}
    </div>
  );
}
