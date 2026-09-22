"use client";

import { Check, Copy, KeyRound, Trash2 } from "lucide-react";
import { useState } from "react";
import { Dialog } from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import { createApiKey, key, listApiKeys, revokeApiKey } from "@/lib/api/endpoints";
import type { ApiKey, CreatedApiKey } from "@/lib/api/types";
import { useResource } from "@/lib/api/use-resource";
import { cn } from "@/lib/cn";
import { buttonClass } from "@/lib/ui";
import { inputClass } from "./field";
import { PageHeader } from "./page-header";
import { RowValue, SettingRow, SettingRows } from "./setting-row";
import { SettingsSection } from "./settings-section";

const dateFormat = new Intl.DateTimeFormat("en", { dateStyle: "medium" });
const timeFormat = new Intl.DateTimeFormat("en", { dateStyle: "medium", timeStyle: "short" });

/**
 * API keys.
 *
 * The server hands back the full secret exactly once, in the create response,
 * so the whole screen is shaped around that one moment: the new key gets its
 * own panel that outlives nothing — it lives in React state and is dropped when
 * dismissed. Nothing here writes it to storage, a URL or the console.
 */
export function ApiKeySettings() {
  const { toast } = useToast();
  const allKeys = useResource(key.apiKeys, () => listApiKeys());

  /**
   * A revoked key is not a key.
   *
   * `GET /keys` keeps listing them after a successful `DELETE` — the key stops
   * working immediately, but the row stays. Showing it would tell the user that
   * revoking had failed, when it had not.
   */
  const keys =
    allKeys.status === "ready"
      ? { ...allKeys, data: allKeys.data.filter((item) => !item.revoked_at) }
      : allKeys;
  const [name, setName] = useState("");
  const [created, setCreated] = useState<CreatedApiKey | null>(null);
  const [confirming, setConfirming] = useState<ApiKey | null>(null);
  const [busy, setBusy] = useState(false);

  const create = async () => {
    const trimmed = name.trim();
    if (!trimmed) return;
    setBusy(true);
    try {
      setCreated(await createApiKey(trimmed));
      setName("");
      keys.refresh();
      toast("Key created");
    } catch (error) {
      toast(error instanceof Error ? error.message : "Could not create that key", "warn");
    } finally {
      setBusy(false);
    }
  };

  const revoke = async (target: ApiKey) => {
    setBusy(true);
    try {
      await revokeApiKey(target.id);
      keys.refresh();
      toast("Key revoked");
    } catch (error) {
      toast(error instanceof Error ? error.message : "Could not revoke that key", "warn");
    } finally {
      setBusy(false);
      setConfirming(null);
    }
  };

  return (
    <>
      <PageHeader title="API keys" description="Programmatic access to your projects, for scripts and CLIs." />

      {created && <NewKeyPanel created={created} onDismiss={() => setCreated(null)} />}

      <SettingsSection
        title="Create a key"
        description="Name it after whatever will hold it, so you know what breaks when you revoke it."
      >
        <div className="flex flex-wrap gap-2.5">
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") void create();
            }}
            placeholder="Deploy script"
            maxLength={80}
            autoComplete="off"
            spellCheck={false}
            className={cn(inputClass, "min-w-[200px] flex-1")}
          />
          <button
            type="button"
            disabled={busy || !name.trim()}
            onClick={() => void create()}
            className={buttonClass({ size: "sm", className: "disabled:cursor-not-allowed disabled:opacity-50" })}
          >
            Create key
          </button>
        </div>
        <p className="mt-2.5 text-xs leading-[1.5] text-muted-3">
          Send it as <code className="text-fg-2">Authorization: Bearer vivid_…</code> on every <code>/v1</code> route,
          exactly like an access token. Keys never expire — revoking is the only way to end one.
        </p>
      </SettingsSection>

      <SettingsSection title="Your keys">
        {keys.status === "loading" && <Skeleton className="h-24" />}

        {keys.status === "error" && (
          <div className="py-6 text-center">
            <p className="text-sm text-muted">{keys.error.message}</p>
            <button
              type="button"
              onClick={keys.retry}
              className={buttonClass({ variant: "secondary", size: "sm", className: "mt-3" })}
            >
              Try again
            </button>
          </div>
        )}

        {keys.status === "ready" &&
          (keys.data.length === 0 ? (
            <div className="px-2 py-8 text-center">
              <KeyRound aria-hidden className="mx-auto size-5 text-muted-3" />
              <p className="mt-2.5 text-sm font-semibold text-fg">No keys yet</p>
              <p className="mx-auto mt-1.5 max-w-[46ch] text-[13px] leading-[1.5] text-muted">
                A key lets a script, a CLI or a CI job call the API as you, without a browser sign-in. It never expires,
                so it keeps working until you revoke it here.
              </p>
            </div>
          ) : (
            <SettingRows>
              {keys.data.map((item) => (
                <SettingRow
                  key={item.id}
                  label={
                    <>
                      <span className="min-w-0 truncate">{item.name}</span>
                      <code className="rounded-md bg-surface-2 px-1.5 py-0.5 font-mono text-[11px] font-semibold text-muted-2">
                        {item.prefix}…
                      </code>
                    </>
                  }
                  description={
                    <>
                      Created {dateFormat.format(Date.parse(item.created_at))} ·{" "}
                      {item.last_used_at
                        ? `Last used ${timeFormat.format(Date.parse(item.last_used_at))}`
                        : "Never used"}
                    </>
                  }
                  action={
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => setConfirming(item)}
                      className="flex cursor-pointer items-center gap-1.5 rounded-lg border border-line-2 px-2.5 py-1.5 text-[12px] font-semibold text-fg-2 transition-colors hover:border-line-3 hover:text-warn disabled:opacity-50"
                    >
                      <Trash2 aria-hidden className="size-3.5" />
                      Revoke
                    </button>
                  }
                />
              ))}
            </SettingRows>
          ))}

        {keys.status === "ready" && keys.data.length > 0 && (
          <SettingRows className="mt-3 border-t border-line pt-3">
            <SettingRow
              label="Lost a key?"
              description="There is no way to read one back. Create a replacement, move it into place, then revoke the old one."
              action={<RowValue>Shown once only</RowValue>}
            />
          </SettingRows>
        )}
      </SettingsSection>

      {confirming && (
        <Dialog
          title={`Revoke “${confirming.name}”?`}
          description="Anything still using this key starts failing immediately, and it cannot be restored."
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
            <button
              type="button"
              disabled={busy}
              onClick={() => void revoke(confirming)}
              className={buttonClass({ size: "sm", className: "disabled:opacity-50" })}
            >
              Revoke
            </button>
          </div>
        </Dialog>
      )}
    </>
  );
}

/**
 * The one sighting of the secret. Rendered read-only so it is easy to select
 * but impossible to edit, and with autocomplete off so no password manager or
 * form-filler ever sees it.
 */
function NewKeyPanel({ created, onDismiss }: { created: CreatedApiKey; onDismiss: () => void }) {
  const { toast } = useToast();
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(created.key);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      // writeText throws outside a secure context and when permission is denied.
      toast("Could not copy — select the key and copy it by hand", "warn");
    }
  };

  return (
    <section className="overflow-hidden rounded-2xl border border-warn/40 bg-surface">
      <div className="border-b border-line px-4 py-3">
        <h2 className="text-sm font-bold tracking-[-0.01em] text-warn">Copy “{created.name}” now</h2>
        <p className="mt-0.5 text-[13px] leading-[1.5] text-muted">
          This is the only time the full key is shown. Once you dismiss this panel it is gone — not stored here, and not
          retrievable from the API.
        </p>
      </div>

      <div className="px-4 py-4">
        <div className="flex flex-wrap gap-2.5">
          <input
            value={created.key}
            readOnly
            autoComplete="off"
            spellCheck={false}
            aria-label="Your new API key"
            onFocus={(event) => event.target.select()}
            className={cn(inputClass, "min-w-[200px] flex-1 font-mono text-[12px]")}
          />
          <button type="button" onClick={() => void copy()} className={buttonClass({ size: "sm" })}>
            {copied ? <Check aria-hidden className="size-3.5" /> : <Copy aria-hidden className="size-3.5" />}
            {copied ? "Copied" : "Copy"}
          </button>
        </div>
        <p className="mt-2.5 text-xs leading-[1.5] text-muted-3">
          Put it in <code className="text-fg-2">Authorization: Bearer {created.prefix}…</code> on your requests, and keep
          it somewhere secret — anyone holding it can act as you.
        </p>
      </div>

      <div className="flex justify-end border-t border-line bg-bg-2 px-4 py-2.5">
        <button type="button" onClick={onDismiss} className={buttonClass({ variant: "secondary", size: "sm" })}>
          I&rsquo;ve saved it
        </button>
      </div>
    </section>
  );
}
