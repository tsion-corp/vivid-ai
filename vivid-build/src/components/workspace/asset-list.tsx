"use client";

import { Trash2, Upload } from "lucide-react";
import { useRef, useState } from "react";
import { Dialog } from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { useToast } from "@/components/ui/toast";
import { deleteAsset, key, listAssets, uploadAsset } from "@/lib/api/endpoints";
import type { Asset } from "@/lib/api/types";
import { useResource } from "@/lib/api/use-resource";
import { formatSize } from "@/lib/files";
import { buttonClass } from "@/lib/ui";

/** 48 MB per project, per §7. Worth showing before someone hits it. */
const PROJECT_LIMIT = 48 * 1024 * 1024;

/**
 * Everything the project holds: what was uploaded and what the agent generated.
 *
 * §7 says generated images land here too, which is what makes this the place to
 * see "the pictures in this project" — and the only way to free space, since
 * the per-project cap is real.
 */
export function AssetList({ projectId }: { projectId: string }) {
  const { toast } = useToast();
  const assets = useResource(key.assets(projectId), () => listAssets(projectId));
  const fileRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(0);
  const [confirming, setConfirming] = useState<Asset | null>(null);

  const upload = async (files: File[]) => {
    setUploading((count) => count + files.length);
    for (const file of files) {
      try {
        await uploadAsset(projectId, file);
      } catch (error) {
        toast(error instanceof Error ? error.message : `Could not upload ${file.name}`, "warn");
      } finally {
        setUploading((count) => count - 1);
      }
    }
  };

  const remove = async (asset: Asset) => {
    setConfirming(null);
    try {
      await deleteAsset(projectId, asset.id);
      toast(`${asset.name} deleted`, "warn");
    } catch (error) {
      toast(error instanceof Error ? error.message : "Could not delete", "warn");
    }
  };

  const used = assets.status === "ready" ? assets.data.reduce((total, asset) => total + asset.size_bytes, 0) : 0;

  return (
    <>
      <div className="flex flex-wrap items-center gap-3 pb-3.5">
        <p className="flex-1 text-[13px] text-muted">
          {assets.status === "ready"
            ? `${assets.data.length} file${assets.data.length === 1 ? "" : "s"} · ${formatSize(used)} of ${formatSize(PROJECT_LIMIT)}`
            : "Uploads and generated images"}
        </p>
        <input
          ref={fileRef}
          type="file"
          multiple
          className="hidden"
          onChange={(event) => {
            const files = Array.from(event.target.files ?? []);
            event.target.value = "";
            if (files.length) void upload(files);
          }}
        />
        <button
          type="button"
          onClick={() => fileRef.current?.click()}
          className={buttonClass({ variant: "secondary", size: "sm" })}
        >
          <Upload aria-hidden className="mr-1.5 inline size-3.5 align-[-3px]" />
          Upload
        </button>
      </div>

      {assets.status === "loading" && <Skeleton className="h-24" />}
      {assets.status === "error" && <p className="text-sm text-muted">{assets.error.message}</p>}

      {assets.status === "ready" &&
        (assets.data.length === 0 && uploading === 0 ? (
          <p className="text-sm text-muted">
            Nothing here yet. Upload a logo or photos, and images the agent makes will appear alongside them.
          </p>
        ) : (
          <ul className="grid grid-cols-[repeat(auto-fill,minmax(min(140px,100%),1fr))] gap-3">
            {assets.data.map((asset) => (
              <li key={asset.id} className="group/asset relative">
                <div className="aspect-square overflow-hidden rounded-xl border border-line-2 bg-surface-2">
                  {asset.mime.startsWith("image/") ? (
                    // Time-limited signed URLs on a host unknown at build time.
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={asset.url} alt={asset.name} loading="lazy" className="size-full object-cover" />
                  ) : (
                    <span className="flex size-full items-center justify-center px-2 text-center text-[11px] font-semibold text-muted-3">
                      {asset.mime.split("/").pop()?.toUpperCase()}
                    </span>
                  )}
                </div>
                <button
                  type="button"
                  onClick={() => setConfirming(asset)}
                  aria-label={`Delete ${asset.name}`}
                  className="absolute top-2 right-2 cursor-pointer rounded-lg bg-chip px-1.5 py-1 text-muted opacity-0 backdrop-blur-sm transition-opacity group-hover/asset:opacity-100 focus-visible:opacity-100 hover:text-fg"
                >
                  <Trash2 aria-hidden className="size-3.5" />
                </button>
                <p className="mt-1.5 truncate text-[12px] font-semibold text-fg-2" title={asset.name}>
                  {asset.name}
                </p>
                <p className="text-[11px] text-muted-3">{formatSize(asset.size_bytes)}</p>
              </li>
            ))}
            {uploading > 0 && (
              <li className="flex aspect-square items-center justify-center rounded-xl border border-dashed border-line-2">
                <Spinner />
              </li>
            )}
          </ul>
        ))}

      {confirming && (
        <Dialog
          title={`Delete ${confirming.name}?`}
          description="The app will no longer be able to serve this file. It cannot be undone."
          size="sm"
          onClose={() => setConfirming(null)}
        >
          <div className="flex justify-end gap-2.5 px-5 py-4">
            <button
              type="button"
              onClick={() => setConfirming(null)}
              className={buttonClass({ variant: "secondary", size: "sm" })}
            >
              Cancel
            </button>
            <button type="button" onClick={() => void remove(confirming)} className={buttonClass({ size: "sm" })}>
              Delete
            </button>
          </div>
        </Dialog>
      )}
    </>
  );
}
