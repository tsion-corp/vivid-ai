import { cn } from "@/lib/cn";

/**
 * Placeholder block shown while the store hydrates.
 *
 * globals.css force-disables animation under prefers-reduced-motion, so the
 * shimmer degrades to a flat block on its own.
 */
export function Skeleton({ className }: { className?: string }) {
  return <span aria-hidden className={cn("block animate-pulse rounded-md bg-surface-2", className)} />;
}

export function ProjectCardSkeleton() {
  return (
    <div className="rounded-2xl border border-line-2 bg-surface p-4">
      <Skeleton className="h-24 rounded-xl" />
      <Skeleton className="mt-3.5 h-4 w-1/2" />
      <Skeleton className="mt-2 h-3 w-4/5" />
      <Skeleton className="mt-2 h-3 w-24" />
    </div>
  );
}

export function ProjectGridSkeleton({ count = 6 }: { count?: number }) {
  return (
    <div className="grid grid-cols-[repeat(auto-fit,minmax(min(260px,100%),1fr))] gap-3">
      {Array.from({ length: count }, (_, i) => (
        <ProjectCardSkeleton key={i} />
      ))}
    </div>
  );
}

export function WorkspaceSkeleton() {
  return (
    <div className="flex min-h-0 flex-1">
      <div className="hidden min-w-0 flex-1 flex-col border-r border-line lg:flex">
        <div className="border-b border-line px-[18px] py-3.5">
          <Skeleton className="h-5 w-40" />
        </div>
        <div className="flex flex-col gap-4 p-[18px]">
          <Skeleton className="h-10 w-2/3 self-end rounded-2xl" />
          <Skeleton className="h-4 w-24" />
          <Skeleton className="h-16 rounded-2xl" />
          <Skeleton className="h-40 rounded-2xl" />
        </div>
      </div>
      <div className="min-w-0 flex-1 bg-bg-2 lg:flex-[1.15]">
        <div className="flex gap-2 border-b border-line px-4 py-3">
          {/* Keyed by position, not by the width: the widths repeat, and a
              duplicate key lets React drop one of the pills. These are fixed,
              decorative and never reorder, so the index is the identity. */}
          {["w-20", "w-16", "w-20", "w-16"].map((width, index) => (
            <Skeleton key={index} className={`h-9 rounded-full ${width}`} />
          ))}
        </div>
        <div className="p-[18px]">
          <Skeleton className="h-[320px] rounded-2xl" />
        </div>
      </div>
    </div>
  );
}
