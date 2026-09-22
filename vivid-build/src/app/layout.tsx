import type { Metadata, Viewport } from "next";
import { AuthModalProvider } from "@/components/auth/auth-modal-provider";
import { NetworkToast } from "@/components/ui/network-toast";
import { SessionProvider } from "@/lib/api/session";
import { Plus_Jakarta_Sans } from "next/font/google";
import { themeInitScript } from "@/lib/theme";
import "./globals.css";

const jakarta = Plus_Jakarta_Sans({
  variable: "--font-jakarta",
  subsets: ["latin"],
  display: "swap",
});

export const metadata: Metadata = {
  // Absolute base for the opengraph-image and icon URLs Next generates from files in app/.
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL ?? "https://vividbuild.dev"),
  title: {
    default: "VividBuild · Describe it once. Ship it for real.",
    template: "%s · VividBuild",
  },
  description:
    "VividBuild turns a plain-language prompt into a reviewed spec, tested code and a production deploy, including dapps on Ark-Konstellation.",
};

export const viewport: Viewport = {
  themeColor: "#0a0b0d",
};

// Chrome lives in the route group layouts: (marketing) has the site header/footer, (app) the product shell.
// Session and the sign-in modal are mounted here rather than per-group, so the
// app, the onboarding flow and the standalone preview route can all reach them.
export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    // data-theme is rewritten before paint by themeInitScript, hence suppressHydrationWarning.
    <html lang="en" data-theme="dark" suppressHydrationWarning className={jakarta.variable}>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeInitScript }} />
      </head>
      <body className="font-sans antialiased">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:fixed focus:top-3 focus:left-3 focus:z-300 focus:rounded-full focus:bg-surface focus:px-4 focus:py-2 focus:text-fg"
        >
          Skip to content
        </a>
        <SessionProvider>
          <AuthModalProvider>{children}</AuthModalProvider>
        </SessionProvider>
        {/* Outside the providers: a connection warning must not depend on a
            session, and it is as relevant on the marketing pages as in the app. */}
        <NetworkToast />
      </body>
    </html>
  );
}
