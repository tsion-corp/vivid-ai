"use client";

import {
  ArrowLeft,
  ChevronDown,
  ChevronRight,
  PanelLeftClose,
  PanelLeftOpen,
  Folder,
  LayoutDashboard,
  LogOut,
  Palette,
  PanelsTopLeft,
  Plug,
  Search,
  Settings,
  Sparkles,
  Star,
  User,
  Users,
  Wallet,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useMemo, type ReactNode } from "react";
import { LogoMark } from "@/components/brand/logo";
import { ThemeToggle } from "@/components/layout/theme-toggle";
import { Menu } from "@/components/ui/menu";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/cn";
import { useProjects } from "@/lib/api/hooks";
import { useSession } from "@/lib/api/session";
import { useCommandPalette } from "./command-palette";
import { useConnectors } from "./connectors-provider";
import { DEFAULT_ACCOUNT } from "./data";

const RECENTS_LIMIT = 3;

// 13px, not 14: the sidebar is chrome, and at the same size as page content it
// competed with it. The tighter row also fits the recents list on a short screen.
const itemClass = (active: boolean, collapsed = false) =>
  cn(
    "flex w-full cursor-pointer items-center gap-2.5 rounded-[10px] py-2 text-left text-[13px] font-semibold transition-colors",
    collapsed ? "justify-center px-0" : "justify-between px-3",
    active ? "bg-surface-2 text-fg" : "text-muted hover:bg-surface hover:text-fg",
  );

/** Sidebar contents, shared by the desktop rail and the mobile drawer. */
export function AppSidebar({
  onNavigate,
  collapsed = false,
  onToggleCollapsed,
}: {
  onNavigate?: () => void;
  /** Icon-only rail. Only the desktop shell passes this. */
  collapsed?: boolean;
  onToggleCollapsed?: () => void;
}) {
  const pathname = usePathname();
  const search = useSearchParams().toString();
  const router = useRouter();
  const projectsSnapshot = useProjects();
  const { user, signOut } = useSession();
  const { openPalette } = useCommandPalette();
  const { openConnectors } = useConnectors();

  // The cap belongs here, not in the store: a snapshot getter that slices
  // returns a new array every call and re-renders forever.
  const recents = useMemo(
    () => (projectsSnapshot.status === "ready" ? projectsSnapshot.data.slice(0, RECENTS_LIMIT) : []),
    [projectsSnapshot],
  );

  const teamName = user?.name ? `${user.name.split(" ")[0]}'s team` : DEFAULT_ACCOUNT.team;
  const initial = (user?.name || user?.email || DEFAULT_ACCOUNT.firstName).charAt(0).toUpperCase();
  // No plan field on the account yet, so the upgrade card always shows.
  const plan = "free";

  return (
    <div
      className={cn(
        "flex h-full flex-col gap-[22px] py-[18px]",
        collapsed ? "px-2.5" : "px-3.5",
      )}
    >
      <div className={cn("flex items-center gap-2", collapsed ? "flex-col" : "px-1.5")}>
        <Link
          href="/"
          onClick={onNavigate}
          aria-label="VividBuild"
          className="flex min-w-0 flex-1 items-center gap-2.5 text-fg"
        >
          <LogoMark />
          {!collapsed && <span className="text-base font-extrabold tracking-[-0.03em]">VividBuild</span>}
        </Link>
        {onToggleCollapsed && (
          <button
            type="button"
            onClick={onToggleCollapsed}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            className="flex flex-none cursor-pointer items-center rounded-lg p-1.5 text-muted-2 transition-colors hover:bg-surface hover:text-fg"
          >
            {collapsed ? (
              <PanelLeftOpen aria-hidden className="size-4" />
            ) : (
              <PanelLeftClose aria-hidden className="size-4" />
            )}
          </button>
        )}
      </div>

      <Menu
        ariaLabel="Account and team"
        label={
          <span
            title={collapsed ? teamName : undefined}
            className={cn(
              "flex items-center gap-[9px] rounded-xl border border-line-2 bg-surface text-[13px] font-semibold transition-colors hover:border-line-3",
              collapsed ? "justify-center p-[9px]" : "px-3 py-[11px]",
            )}
          >
            {user?.avatar_url ? (
              // Served from per-account hosts, so next/image's remotePatterns
              // cannot cover them.
              // eslint-disable-next-line @next/next/no-img-element
              <img src={user.avatar_url} alt="" className="size-5 flex-none rounded-md object-cover" />
            ) : (
              <span
                aria-hidden
                className="flex size-5 flex-none items-center justify-center rounded-md bg-btn text-[11px] font-extrabold text-btn-fg"
              >
                {initial}
              </span>
            )}
            {!collapsed && (
              <>
                <span className="min-w-0 flex-1 truncate text-left">{teamName}</span>
                <ChevronDown aria-hidden className="size-3.5 flex-none text-muted-2" />
              </>
            )}
          </span>
        }
        items={[
          { label: "Settings", icon: <Settings className="size-4" />, onSelect: () => router.push("/settings/account") },
          { label: "Workspace", icon: <PanelsTopLeft className="size-4" />, onSelect: () => router.push("/settings/workspace") },
          { label: "People", icon: <Users className="size-4" />, onSelect: () => router.push("/settings/people") },
          {
            label: "Plans & credit usage",
            icon: <Wallet className="size-4" />,
            onSelect: () => router.push("/settings/billing"),
          },
          { label: "Appearance", icon: <Palette className="size-4" />, onSelect: () => router.push("/settings/appearance") },
          { type: "divider" },
          { label: "Back to website", icon: <ArrowLeft className="size-4" />, onSelect: () => router.push("/") },
          {
            label: "Sign out",
            icon: <LogOut className="size-4" />,
            danger: true,
            onSelect: () => {
              signOut();
              router.push("/");
            },
          },
        ]}
      />

      {/*
        Only the middle scrolls. Scrolling the whole column meant that on a
        short viewport the Recents list pushed the footer — theme toggle and
        Sign out — past the bottom edge, and because `mt-auto` overflow is not
        counted as scrollable, there was no way to scroll it back into view.
        A scroll container also clips on both axes, which is why the collapsed
        rail (short, fixed height) opts out so its flyouts can escape.
      */}
      <div
        className={cn(
          "no-scrollbar flex min-h-0 flex-1 flex-col gap-[22px]",
          collapsed ? "overflow-visible" : "overflow-y-auto",
        )}
      >
      <nav aria-label="App" className="flex flex-col gap-[3px]">
        <Link
          href="/dashboard"
          onClick={onNavigate}
          aria-current={pathname === "/dashboard" ? "page" : undefined}
          title={collapsed ? "Dashboard" : undefined}
          className={itemClass(pathname === "/dashboard", collapsed)}
        >
          <LayoutDashboard aria-hidden className="size-4 flex-none" />
          {!collapsed && <span className="flex-1">Dashboard</span>}
        </Link>
        <button
          type="button"
          onClick={() => {
            onNavigate?.();
            openPalette();
          }}
          title={collapsed ? "Search" : undefined}
          className={itemClass(false, collapsed)}
        >
          <Search aria-hidden className="size-4 flex-none" />
          {!collapsed && (
            <>
              <span className="flex-1">Search</span>
              <kbd className="font-sans text-[11px] text-muted-3">⌘K</kbd>
            </>
          )}
        </button>
        <button
          type="button"
          onClick={() => {
            onNavigate?.();
            openConnectors();
          }}
          title={collapsed ? "Connectors" : undefined}
          className={itemClass(false, collapsed)}
        >
          <Plug aria-hidden className="size-4 flex-none" />
          {!collapsed && <span className="flex-1">Connectors</span>}
        </button>
      </nav>

      <SidebarGroup title="Projects" collapsed={collapsed}>
        {[
          { href: "/projects", label: "All projects", Icon: Folder },
          { href: "/projects?filter=starred", label: "Starred", Icon: Star },
          { href: "/projects?filter=mine", label: "Owned by me", Icon: User },
        ].map((link) => {
          const active = pathname + (search ? `?${search}` : "") === link.href;
          return (
            <Link
              key={link.href}
              href={link.href}
              onClick={onNavigate}
              aria-current={active ? "page" : undefined}
              title={collapsed ? link.label : undefined}
              className={itemClass(active, collapsed)}
            >
              <link.Icon aria-hidden className="size-4 flex-none" />
              {!collapsed && <span className="flex-1 truncate">{link.label}</span>}
            </Link>
          );
        })}
      </SidebarGroup>

      {!collapsed && (
      <SidebarGroup title="Recents">
        {projectsSnapshot.status !== "ready" ? (
          <div className="flex flex-col gap-2 px-3 py-1">
            <Skeleton className="h-4 w-4/5" />
            <Skeleton className="h-4 w-3/5" />
          </div>
        ) : recents.length ? (
          recents.map((project) => {
            const href = `/projects/${project.id}`;
            return (
              <Link
                key={project.id}
                href={href}
                onClick={onNavigate}
                aria-current={pathname === href ? "page" : undefined}
                className={itemClass(pathname === href)}
              >
                <PanelsTopLeft aria-hidden className="size-4 flex-none text-muted-3" />
                <span className="flex-1 truncate">{project.name}</span>
              </Link>
            );
          })
        ) : (
          <p className="px-3 text-[13px] text-muted-3">No recent projects</p>
        )}
      </SidebarGroup>
      )}
      </div>

      <div className={cn("flex flex-none flex-col gap-3", collapsed && "items-center")}>
        {plan === "free" &&
          (collapsed ? (
            <Link
              href="/settings/billing"
              onClick={onNavigate}
              aria-label="Upgrade to Pro"
              title="Upgrade to Pro"
              className="flex size-9 items-center justify-center rounded-xl bg-[#5b4bf5] text-white ring-1 ring-white/15 transition-colors ring-inset hover:bg-[#6a5aff]"
            >
              <Sparkles aria-hidden className="size-4" />
            </Link>
          ) : (
          <Link
            href="/settings/billing"
            onClick={onNavigate}
            // One flat accent colour — the only saturated surface in the app,
            // so it carries the eye without a gradient doing the work.
            className="group block rounded-2xl bg-[#5b4bf5] p-4 ring-1 ring-white/15 transition-colors duration-200 ring-inset hover:bg-[#6a5aff]"
          >
            <span className="flex items-center gap-2">
              <span className="flex size-7 flex-none items-center justify-center rounded-[9px] bg-white/15 ring-1 ring-white/25 ring-inset">
                <Sparkles aria-hidden className="size-[15px] text-white" />
              </span>
              <span className="text-sm font-extrabold tracking-[-0.01em] text-white">Upgrade to Pro</span>
              <ChevronRight
                aria-hidden
                className="ml-auto size-4 flex-none text-white/60 transition-transform duration-200 group-hover:translate-x-0.5 group-hover:text-white"
              />
            </span>

            <span className="mt-2.5 block text-xs leading-[1.5] text-white/80">
              Code export, custom domains and unlimited projects.
            </span>
          </Link>
          ))}
        <ThemeToggle compact={collapsed} className={collapsed ? undefined : "self-start"} />
      </div>
    </div>
  );
}

function SidebarGroup({
  title,
  children,
  collapsed = false,
}: {
  title: string;
  children: ReactNode;
  collapsed?: boolean;
}) {
  return (
    <div>
      <h2
        className={cn(
          "mb-2 px-3 text-[11px] font-bold tracking-[0.12em] text-muted-3 uppercase",
          collapsed && "sr-only",
        )}
      >
        {title}
      </h2>
      <div className="flex flex-col gap-[3px]">{children}</div>
    </div>
  );
}
