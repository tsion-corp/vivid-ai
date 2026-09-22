"use client";

import { useState } from "react";
import { Skeleton } from "@/components/ui/skeleton";
import { getAnalytics, key } from "@/lib/api/endpoints";
import type { AnalyticsBucket, Project } from "@/lib/api/types";
import { useResource } from "@/lib/api/use-resource";
import { cn } from "@/lib/cn";
import { buttonClass } from "@/lib/ui";

const PERIODS = [7, 30, 90] as const;
type Period = (typeof PERIODS)[number];

const dayFormat = new Intl.DateTimeFormat("en", { month: "short", day: "numeric" });
const regionNames = new Intl.DisplayNames("en", { type: "region" });

function countryName(code: string) {
  // Anything the collector could not resolve arrives as a non-region key, and
  // DisplayNames throws on those rather than returning the input.
  try {
    return regionNames.of(code.toUpperCase()) ?? code;
  } catch {
    return code;
  }
}

/**
 * Traffic to the published site.
 *
 * The numbers only exist once a deploy is live and someone has loaded it, so
 * the two ways of having nothing to show are kept apart — "not published" is a
 * thing to go do, "no visits" is a thing to wait for.
 */
export function AnalyticsPanel({ project }: { project: Project }) {
  const [days, setDays] = useState<Period>(30);
  const published = Boolean(project.published_url);
  const analytics = useResource(key.analytics(project.id, days), () => getAnalytics(project.id, days), {
    enabled: published,
  });

  if (!published) {
    return (
      <p className="text-sm text-muted">
        Nothing to measure yet. Publish this app and visits to its live URL will be counted here.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {/* "the site" rather than the host name. Spelling out
          "a-storefront-for-a-sh-bd33ce.vivid-apps.pages.dev" broke at every
          hyphen into four lines on a phone and squeezed the period buttons into
          a column — and a generated subdomain is not something anyone reads
          anyway. The URL is still one tap away, and on the title for anyone who
          wants to see it before they follow it. */}
      <div className="flex flex-wrap items-center gap-2">
        <p className="min-w-0 flex-1 text-[13px] text-muted">
          Visits to{" "}
          <a
            href={project.published_url ?? undefined}
            target="_blank"
            rel="noreferrer noopener"
            title={project.published_url ?? undefined}
            className="font-semibold text-fg-2 underline decoration-line-3 underline-offset-2 transition-colors hover:text-fg"
          >
            the site
          </a>
        </p>
        <div role="group" aria-label="Period" className="flex flex-none gap-1.5">
          {PERIODS.map((period) => (
            <button
              key={period}
              type="button"
              aria-pressed={period === days}
              onClick={() => setDays(period)}
              className={buttonClass({ variant: period === days ? "primary" : "secondary", size: "sm" })}
            >
              {period}d
            </button>
          ))}
        </div>
      </div>

      {analytics.status === "loading" && <Skeleton className="h-40" />}

      {analytics.status === "error" && (
        <div className="flex flex-wrap items-center gap-3">
          <p className="flex-1 text-sm text-muted">{analytics.error.message}</p>
          <button type="button" onClick={analytics.retry} className={buttonClass({ variant: "secondary", size: "sm" })}>
            Try again
          </button>
        </div>
      )}

      {analytics.status === "ready" &&
        (analytics.data.pageviews === 0 ? (
          <p className="text-sm text-muted">
            Published, but nobody has visited yet. Share the link and the first views will show up here.
          </p>
        ) : (
          <>
            <dl className="grid grid-cols-2 gap-x-4">
              <Stat label="Visitors" value={analytics.data.visitors} />
              <Stat label="Pageviews" value={analytics.data.pageviews} />
            </dl>

            <DayBars by_day={analytics.data.by_day} />

            <div className="grid grid-cols-[repeat(auto-fit,minmax(min(260px,100%),1fr))] gap-x-6 gap-y-4">
              <BucketList title="Top pages" buckets={analytics.data.top_pages} />
              <BucketList title="Referrers" buckets={analytics.data.referrers} format={referrerName} />
              <BucketList title="Devices" buckets={analytics.data.devices} format={capitalise} />
              <BucketList title="Countries" buckets={analytics.data.countries} format={countryName} />
            </div>
          </>
        ))}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="py-1">
      <dt className="text-[11px] font-semibold tracking-[0.08em] text-muted-3 uppercase">{label}</dt>
      <dd className="mt-0.5 text-2xl font-bold text-fg">{value.toLocaleString()}</dd>
    </div>
  );
}

function DayBars({ by_day }: { by_day: { date: string; pageviews: number; visitors: number }[] }) {
  if (!by_day.length) return null;

  // Scaled to the busiest day in the range, so a quiet week still reads as a
  // shape rather than a flat line.
  const peak = Math.max(...by_day.map((day) => day.pageviews));

  return (
    <div className="flex h-28 items-end gap-px" role="img" aria-label={`Pageviews per day over ${by_day.length} days`}>
      {by_day.map((day) => {
        const height = peak > 0 ? Math.max((day.pageviews / peak) * 100, day.pageviews > 0 ? 4 : 2) : 2;
        const label = `${dayFormat.format(Date.parse(day.date))}: ${day.pageviews} pageview${
          day.pageviews === 1 ? "" : "s"
        }, ${day.visitors} visitor${day.visitors === 1 ? "" : "s"}`;
        return (
          <div
            key={day.date}
            title={label}
            aria-label={label}
            style={{ height: `${height}%` }}
            className={cn("min-w-0 flex-1 rounded-t-[2px]", day.pageviews > 0 ? "bg-accent" : "bg-surface-2")}
          />
        );
      })}
    </div>
  );
}

function BucketList({
  title,
  buckets,
  format,
}: {
  title: string;
  buckets: AnalyticsBucket[];
  format?: (key: string) => string;
}) {
  const peak = buckets.length ? Math.max(...buckets.map((bucket) => bucket.count)) : 0;

  return (
    <div className="min-w-0">
      <h3 className="text-[11px] font-semibold tracking-[0.08em] text-muted-3 uppercase">{title}</h3>
      {buckets.length === 0 ? (
        <p className="mt-1.5 text-[13px] text-muted">None yet</p>
      ) : (
        <ul className="mt-1.5 flex flex-col gap-1">
          {buckets.map((bucket) => (
            <li key={bucket.key} className="relative flex items-center gap-3 overflow-hidden rounded-md px-1.5 py-1">
              {/* Proportion reads behind the row so the labels keep a single left edge. */}
              <span
                aria-hidden
                style={{ width: `${peak > 0 ? (bucket.count / peak) * 100 : 0}%` }}
                className="absolute inset-y-0 left-0 rounded-md bg-tint"
              />
              <span className="relative min-w-0 flex-1 truncate text-[13px] text-fg-2">
                {format ? format(bucket.key) : bucket.key}
              </span>
              <span className="relative flex-none text-[13px] font-semibold text-fg tabular-nums">
                {bucket.count.toLocaleString()}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function referrerName(key: string) {
  return key === "direct" ? "Direct / none" : key;
}

function capitalise(key: string) {
  return key.charAt(0).toUpperCase() + key.slice(1);
}
