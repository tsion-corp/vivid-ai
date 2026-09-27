# The phone menu

On phones the header's links go behind a menu button, and that menu is a designed
screen, not a dropdown. Never use the dropdown-menu component for site navigation: a
small floating list of words under the icon, with no current page, no action and 40 px
rows, is what a default looks like, and it reads as unfinished. The dropdown menu is for
the account menu and row actions only.

## What it is
- A full-height sheet over the page (a Radix Dialog, so focus is trapped, Escape and the
  back gesture close it and the page behind does not scroll), sliding down from the
  header or in from the right, over a dimmed, blurred page. The site's own header row
  stays at the top of the sheet: logo left, the close button exactly where the menu
  button was, so the icon morphs in place (three lines to an X).
- Links are big and few: text-3xl font-display font-semibold tracking-tight, one per
  row, at least 56 px tall, separated by space, not by grey dividers. The current page is
  marked (the primary colour and a small dot or bar, plus `aria-current="page"`).
  They arrive with a short stagger (40 ms apart, 12 px rise), under 300 ms in total.
- The bottom of the sheet, pinned above the safe area: the primary action as a full-width
  button (the same one the header shows), then the secondary one (Log in) as a ghost
  button, then one line of real contact (WhatsApp, phone, or the city) or the social
  icons. Signed in: the account's name and "Sign out" here instead of Log in.
- It closes on a link tap, on route change, on Escape, and on the X. It has the page's
  own background (bg-background), not a white card on a cream page.
- Design it for the recipe: an editorial site gets serif links and a quiet sheet; a bold
  or dark one gets a full-colour sheet in the primary with light text; a platform keeps
  the two-tone palette with the bright partner colour on the action.

## The component (adapt the look; keep the behaviour)

```tsx
// src/components/MobileMenu.tsx
import * as Dialog from "@radix-ui/react-dialog";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type Item = { label: string; to: string };

export function MobileMenu({ items, action, logo }: {
  items: Item[];
  action: { label: string; to: string };
  logo: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const { pathname } = useLocation();
  const reduce = useReducedMotion();
  useEffect(() => setOpen(false), [pathname]);

  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger asChild>
        <button type="button" aria-label="Open menu"
          className="relative grid size-11 cursor-pointer place-items-center rounded-full md:hidden">
          <MenuIcon open={open} />
        </button>
      </Dialog.Trigger>
      <AnimatePresence>
        {open && (
          <Dialog.Portal forceMount>
            <Dialog.Overlay asChild forceMount>
              <motion.div className="fixed inset-0 z-50 bg-foreground/30 backdrop-blur-sm"
                initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} />
            </Dialog.Overlay>
            <Dialog.Content asChild forceMount aria-describedby={undefined}>
              <motion.div
                className="fixed inset-x-0 top-0 z-50 flex max-h-dvh min-h-[70dvh] flex-col rounded-b-3xl bg-background px-5 pb-[max(1.5rem,env(safe-area-inset-bottom))] shadow-2xl"
                initial={reduce ? { opacity: 0 } : { y: "-100%" }}
                animate={reduce ? { opacity: 1 } : { y: 0 }}
                exit={reduce ? { opacity: 0 } : { y: "-100%" }}
                transition={{ type: "spring", damping: 32, stiffness: 320 }}>
                <Dialog.Title className="sr-only">Menu</Dialog.Title>
                <div className="flex h-16 items-center justify-between">
                  {logo}
                  <Dialog.Close className="grid size-11 cursor-pointer place-items-center rounded-full" aria-label="Close menu">
                    <MenuIcon open />
                  </Dialog.Close>
                </div>
                <nav className="mt-6 flex flex-col">
                  {items.map((item, i) => {
                    const current = pathname === item.to;
                    return (
                      <motion.div key={item.to}
                        initial={reduce ? false : { opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}
                        transition={{ delay: 0.06 + i * 0.04, duration: 0.25 }}>
                        <Link to={item.to} aria-current={current ? "page" : undefined}
                          className={cn("flex min-h-14 items-center gap-3 font-display text-3xl font-semibold tracking-tight",
                            current ? "text-primary" : "text-foreground")}>
                          {item.label}
                          {current && <span className="size-2 rounded-full bg-primary" />}
                        </Link>
                      </motion.div>
                    );
                  })}
                </nav>
                <div className="mt-auto flex flex-col gap-3 pt-10">
                  <Button asChild size="lg" className="h-12 rounded-full text-base">
                    <Link to={action.to}>{action.label}</Link>
                  </Button>
                  {/* Log in (ghost), or the signed-in name and Sign out, then one line of contact. */}
                </div>
              </motion.div>
            </Dialog.Content>
          </Dialog.Portal>
        )}
      </AnimatePresence>
    </Dialog.Root>
  );
}

/** Three lines that become an X. */
function MenuIcon({ open }: { open: boolean }) {
  const line = "absolute left-1/2 h-0.5 w-5 -translate-x-1/2 rounded-full bg-current transition-all duration-200";
  return (
    <span className="relative block size-5" aria-hidden>
      <span className={cn(line, open ? "top-1/2 rotate-45" : "top-[5px]")} />
      <span className={cn(line, "top-1/2 -translate-y-1/2", open && "opacity-0")} />
      <span className={cn(line, open ? "top-1/2 -rotate-45" : "bottom-[5px]")} />
    </span>
  );
}
```

- The header keeps its own row on phones: logo, the primary action as a compact pill when
  it fits, and this menu. At md and up the menu is hidden and the links show inline.
- A one-page site without routes: items point at `#sections` with plain `<a>`, and each
  link's onClick closes the sheet (`setOpen(false)`) before the scroll.
- Check it at 375 px wide: nothing clipped, the action visible without scrolling, the
  close button in the same spot as the menu button.
