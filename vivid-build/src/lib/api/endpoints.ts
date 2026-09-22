"use client";

import { API, api } from "./client";
import { invalidate } from "./cache";
import type {
  Analytics,
  ApiKey,
  Asset,
  Connector,
  ConnectorProvider,
  CreatedApiKey,
  FileContent,
  Project,
  PreviewInfo,
  Publish,
  Snapshot,
  StoredMessage,
  Usage,
  User,
} from "./types";

/** Cache keys. One place, so an invalidation can never drift from a subscription. */
export const key = {
  projects: "projects",
  project: (id: string) => `project:${id}`,
  messages: (id: string) => `messages:${id}`,
  preview: (id: string) => `preview:${id}`,
  files: (id: string) => `files:${id}`,
  file: (id: string, path: string) => `file:${id}:${path}`,
  snapshots: (id: string) => `snapshots:${id}`,
  publishes: (id: string) => `publishes:${id}`,
  assets: (id: string) => `assets:${id}`,
  usage: (id: string) => `usage:${id}`,
  analytics: (id: string, days: number) => `analytics:${id}:${days}`,
  connectors: "connectors",
  apiKeys: "api-keys",
};

const project = (id: string) => `/builder/projects/${id}`;

/* ------------------------------------------------------------------ account */

export const renameMe = (name: string) => api.patch<User>("/auth/me", { name });

/* ----------------------------------------------------------------- projects */

export const listProjects = () => api.get<Project[]>("/builder/projects");
export const getProject = (id: string) => api.get<Project>(project(id));

/**
 * Create a project.
 *
 * Pass no name and the plan fills one in from the spec — the app's own name,
 * which the published URL slug then follows. We used to send the first six
 * words of the prompt, which is why projects were called things like "A
 * delivery tracking page for a". A name the user actually typed is kept.
 */
export async function createProject(name: string | null = null, skipPlan = false) {
  const created = await api.post<Project>("/builder/projects", {
    ...(name ? { name } : {}),
    skip_plan: skipPlan,
  });
  invalidate(key.projects);
  return created;
}

export async function updateProject(
  id: string,
  patch: { name?: string; spec_md?: string; fullstack?: boolean; recipe?: string },
) {
  const updated = await api.patch<Project>(project(id), patch);
  invalidate(key.projects);
  invalidate(key.project(id));
  return updated;
}

export async function deleteProject(id: string) {
  await api.del<void>(project(id));
  invalidate(key.projects);
}

/** Flips the project from plan mode to build mode. */
export async function startBuild(id: string) {
  const updated = await api.post<Project>(`${project(id)}/build`);
  invalidate(key.project(id));
  return updated;
}

export const cancelTurn = (id: string) => api.post<{ cancelled: boolean }>(`${project(id)}/cancel`);

/* --------------------------------------------------------- thread & preview */

export const listMessages = (id: string) => api.get<StoredMessage[]>(`${project(id)}/messages`);

/** Also keeps the sandbox alive; a 503 sandbox_unavailable means "call again". */
export const getPreview = (id: string) => api.get<PreviewInfo>(`${project(id)}/preview`);

export const listFiles = (id: string) => api.get<{ files: string[] }>(`${project(id)}/files`);

const filePath = (path: string) => path.split("/").map(encodeURIComponent).join("/");

export const readFile = (id: string, path: string) =>
  api.get<FileContent>(`${project(id)}/files/${filePath(path)}`);

/**
 * The bytes, with a real content type.
 *
 * Not usable as an `<img src>`: the route needs a bearer token either way —
 * relayed or direct — and an `<img>` request never passes through `authFetch`.
 * The code browser renders binaries from the `content_base64` it already has
 * instead. Kept for callers that can carry the header themselves.
 */
export const rawFileUrl = (id: string, path: string) =>
  `${API}${project(id)}/files/${filePath(path)}?raw=1`;
export const getLogs = (id: string, lines = 100) =>
  api.get<{ lines: string[] }>(`${project(id)}/logs?lines=${lines}`);

/* ----------------------------------------------------------------- versions */

export const listSnapshots = (id: string) => api.get<Snapshot[]>(`${project(id)}/snapshots`);

/** Saves a version outside a turn. Rarely needed — every changing turn saves one. */
export async function takeSnapshot(id: string) {
  const snapshot = await api.post<Snapshot>(`${project(id)}/snapshots`);
  invalidate(key.snapshots(id));
  return snapshot;
}

export async function restoreSnapshot(id: string, seq: number) {
  const snapshot = await api.post<Snapshot>(`${project(id)}/snapshots/${seq}/restore`);
  invalidate(key.snapshots(id));
  invalidate(key.preview(id));
  invalidate(key.files(id));
  return snapshot;
}

export async function undo(id: string) {
  const snapshot = await api.post<Snapshot>(`${project(id)}/undo`);
  invalidate(key.snapshots(id));
  invalidate(key.preview(id));
  invalidate(key.files(id));
  return snapshot;
}

/* ------------------------------------------------------------------ publish */

export async function publish(id: string) {
  const created = await api.post<Publish>(`${project(id)}/publish`);
  invalidate(key.publishes(id));
  return created;
}

export const listPublishes = (id: string) => api.get<Publish[]>(`${project(id)}/publishes`);
export const getPublish = (id: string, publishId: string) =>
  api.get<Publish>(`${project(id)}/publishes/${publishId}`);

/* ------------------------------------------------------------------- assets */

export const listAssets = (id: string) => api.get<Asset[]>(`${project(id)}/assets`);

export async function uploadAsset(id: string, file: File) {
  const form = new FormData();
  form.append("file", file);
  const asset = await api.upload<Asset>(`${project(id)}/assets`, form);
  invalidate(key.assets(id));
  return asset;
}

export async function deleteAsset(id: string, assetId: string) {
  await api.del<void>(`${project(id)}/assets/${assetId}`);
  invalidate(key.assets(id));
}

/* --------------------------------------------------------------- connectors */

export const listConnectors = () => api.get<Connector[]>("/connectors");

export async function addConnector(body: {
  provider: ConnectorProvider;
  token: string;
  public_key?: string;
}) {
  const connector = await api.post<Connector>("/connectors", body);
  invalidate(key.connectors);
  return connector;
}

export async function removeConnector(connectorId: string) {
  await api.del<void>(`/connectors/${connectorId}`);
  invalidate(key.connectors);
}

export const supabaseAuthorizeUrl = () => api.get<{ url: string }>("/connectors/supabase/authorize");

/**
 * Three shapes, per §9, in descending order of what the agent can then do:
 * `{project_ref}` alone uses the account connection and unlocks migration,
 * edge-function and secret tools; adding `anon_key` (no connector) only puts
 * the keys in the app's env; adding `database_url` as well lets the builder
 * apply migrations itself, so accounts and /admin work without the connector.
 */
export async function linkSupabase(
  id: string,
  body: { project_ref: string; url?: string; anon_key?: string; database_url?: string },
) {
  const updated = await api.post<Project>(`${project(id)}/supabase`, body);
  invalidate(key.project(id));
  return updated;
}

export async function unlinkSupabase(id: string) {
  await api.del<void>(`${project(id)}/supabase`);
  invalidate(key.project(id));
}

export async function enablePayments(id: string) {
  const updated = await api.post<Project>(`${project(id)}/payments`);
  invalidate(key.project(id));
  return updated;
}

export async function disablePayments(id: string) {
  await api.del<void>(`${project(id)}/payments`);
  invalidate(key.project(id));
}

export async function enableMaps(id: string) {
  const updated = await api.post<Project>(`${project(id)}/maps`);
  invalidate(key.project(id));
  return updated;
}

export async function disableMaps(id: string) {
  await api.del<void>(`${project(id)}/maps`);
  invalidate(key.project(id));
}

/* -------------------------------------------------------------------- usage */

export const getUsage = (id: string) => api.get<Usage>(`${project(id)}/usage`);

/** Empty until the site is published and visited. */
export const getAnalytics = (id: string, days = 30) =>
  api.get<Analytics>(`${project(id)}/analytics?days=${days}`);

/* ----------------------------------------------------------------- api keys */

export const listApiKeys = () => api.get<ApiKey[]>("/keys");

/** The full key is in this response only; it cannot be read back. */
export async function createApiKey(name: string) {
  const created = await api.post<CreatedApiKey>("/keys", { name });
  invalidate(key.apiKeys);
  return created;
}

export async function revokeApiKey(id: string) {
  await api.del<void>(`/keys/${id}`);
  invalidate(key.apiKeys);
}
