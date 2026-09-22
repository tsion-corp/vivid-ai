"use client";

import { Markdown } from "@/components/ui/markdown";
import { Skeleton } from "@/components/ui/skeleton";
import { getUsage, key } from "@/lib/api/endpoints";
import type { Project } from "@/lib/api/types";
import { useResource } from "@/lib/api/use-resource";
import { AnalyticsPanel } from "./analytics-panel";
import { AssetList } from "./asset-list";
import { DeployList } from "./deploy-list";

/**
 * The "More" tab.
 *
 * This used to be nine placeholder panels. Only what the API can actually
 * answer survives — files, deploys, usage, and the two documents the planning
 * phase produced.
 */
export function ProjectDetails({ project }: { project: Project }) {
  const usage = useResource(key.usage(project.id), () => getUsage(project.id));

  return (
    <div className="flex flex-col gap-4">
      <Section title="Usage">
        {usage.status === "loading" && <Skeleton className="h-16" />}
        {usage.status === "error" && <p className="text-sm text-muted">{usage.error.message}</p>}
        {usage.status === "ready" && (
          <dl className="grid grid-cols-2 gap-x-4 sm:grid-cols-4">
            <Stat label="Model calls" value={usage.data.model_calls.toLocaleString()} />
            <Stat label="Tokens" value={usage.data.tokens.toLocaleString()} />
            <Stat label="Sandbox" value={`${Math.round(usage.data.sandbox_seconds / 60)} min`} />
            <Stat label="Cost" value={`$${usage.data.cost_usd.toFixed(2)}`} />
          </dl>
        )}
      </Section>

      <Section title="Visitors">
        <AnalyticsPanel project={project} />
      </Section>

      <Section title="Files">
        <AssetList projectId={project.id} />
      </Section>

      <Section title="Deploys">
        <DeployList projectId={project.id} />
      </Section>

      {project.brief_md && (
        <Section title="Brief">
          <Markdown>{project.brief_md}</Markdown>
        </Section>
      )}

      {project.spec_md && (
        <Section title="Spec">
          <Markdown>{project.spec_md}</Markdown>
        </Section>
      )}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="overflow-hidden rounded-2xl border border-line-2 bg-surface">
      <h2 className="border-b border-line px-4 py-3 text-sm font-bold text-fg">{title}</h2>
      <div className="px-4 py-3.5">{children}</div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="py-1">
      <dt className="text-[11px] font-semibold tracking-[0.08em] text-muted-3 uppercase">{label}</dt>
      <dd className="mt-0.5 text-base font-bold text-fg">{value}</dd>
    </div>
  );
}
