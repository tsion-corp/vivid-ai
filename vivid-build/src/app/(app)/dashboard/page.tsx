import type { Metadata } from "next";
import { DashboardComposer } from "@/components/app/dashboard-composer";
import { DashboardGreeting } from "@/components/app/dashboard-greeting";
import { DashboardRecents } from "@/components/app/dashboard-recents";

export const metadata: Metadata = {
  title: "Dashboard",
};

export default function DashboardPage() {
  return (
    // `overflow-hidden` here used to clip anything taller than the viewport,
    // which on a phone meant the template cards were simply unreachable. The
    // aurora does its own clipping instead, and `my-auto` keeps the content
    // centred when it fits without preventing a scroll when it doesn't.
    <div className="relative flex min-h-full flex-col items-center px-5 py-8 sm:px-6">
      {/* Anchored to the top of the page rather than the centred content, so it
          reads as light falling on the page and does not move when the recents
          strip changes the content's height. */}
      <div aria-hidden className="aurora" />
      <div className="relative my-auto w-full max-w-[720px] text-center">
        <DashboardGreeting />
        <DashboardComposer />
        <DashboardRecents />
      </div>
    </div>
  );
}
