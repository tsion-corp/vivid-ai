# Motion patterns to copy

All under `src/components/motion/`. Reuse as written; change values only where the skill
gives a range.

## Reveal.tsx (entrances, stagger, split lines)
```tsx
import { motion, useReducedMotion } from "motion/react";
import type { ReactNode } from "react";

const EASE = [0.22, 1, 0.36, 1] as const;

export function Reveal({ children, delay = 0, y = 24, className }: {
  children: ReactNode; delay?: number; y?: number; className?: string;
}) {
  const reduce = useReducedMotion();
  if (reduce) return <div className={className}>{children}</div>;
  return (
    <motion.div className={className} initial={{ opacity: 0, y }} whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-80px" }} transition={{ duration: 0.7, delay, ease: EASE }}>
      {children}
    </motion.div>
  );
}

export function RevealGroup({ children, stagger = 0.06, className }: {
  children: ReactNode; stagger?: number; className?: string;
}) {
  const reduce = useReducedMotion();
  return (
    <motion.div className={className} initial={reduce ? false : "hidden"} whileInView="show"
      viewport={{ once: true, margin: "-80px" }}
      variants={{ hidden: {}, show: { transition: { staggerChildren: stagger } } }}>
      {children}
    </motion.div>
  );
}

export function RevealItem({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <motion.div className={className}
      variants={{ hidden: { opacity: 0, y: 24 }, show: { opacity: 1, y: 0, transition: { duration: 0.7, ease: EASE } } }}>
      {children}
    </motion.div>
  );
}

/** A headline revealed line by line out of a clip mask. Pass the lines yourself. */
export function SplitLines({ lines, className, delay = 0 }: { lines: string[]; className?: string; delay?: number }) {
  const reduce = useReducedMotion();
  return (
    <span className={className}>
      {lines.map((line, i) => (
        <span key={i} className="block overflow-hidden">
          <motion.span className="block" initial={reduce ? false : { y: "110%" }} animate={{ y: 0 }}
            transition={{ duration: 0.8, delay: delay + i * 0.1, ease: EASE }}>
            {line}
          </motion.span>
        </span>
      ))}
    </span>
  );
}
```

## Hover language (use on buttons and cards)
```tsx
import { motion } from "motion/react";
export const lift = { whileHover: { y: -4 }, whileTap: { scale: 0.98 }, transition: { duration: 0.2 } };
export const press = { whileHover: { y: -1 }, whileTap: { scale: 0.98 }, transition: { duration: 0.15 } };
// <motion.div {...lift} className="rounded-2xl ..."> around a card; <motion.button {...press}> for buttons
```
Image zoom inside a card: wrap the `<img>` in `overflow-hidden rounded-xl` and give the img
`transition-transform duration-[600ms] group-hover:scale-[1.04]` with `group` on the card.

## NavPill (sliding active indicator)
```tsx
import { motion } from "motion/react";
import { NavLink } from "react-router-dom";
export function NavItem({ to, children }: { to: string; children: React.ReactNode }) {
  return (
    <NavLink to={to} className="relative px-3 py-2 text-sm font-medium">
      {({ isActive }) => (<>
        {isActive && <motion.span layoutId="nav-pill" className="absolute inset-0 rounded-full bg-primary/10"
          transition={{ type: "spring", stiffness: 500, damping: 40 }} />}
        <span className="relative">{children}</span>
      </>)}
    </NavLink>
  );
}
```

## Parallax.tsx (hero layers)
```tsx
import { motion, useReducedMotion, useScroll, useTransform } from "motion/react";
import { useRef, type ReactNode } from "react";
export function ParallaxHero({ children }: { children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  return <div ref={ref} className="relative overflow-x-clip">{children}</div>;
}
export function Layer({ speed = 0.5, children, className }: { speed?: number; children: ReactNode; className?: string }) {
  const reduce = useReducedMotion();
  const { scrollY } = useScroll();
  const y = useTransform(scrollY, [0, 600], [0, -40 * speed]);
  const isPhone = typeof window !== "undefined" && window.matchMedia("(max-width: 640px)").matches;
  if (reduce || isPhone) return <div className={className}>{children}</div>;
  return <motion.div style={{ y }} className={className}>{children}</motion.div>;
}
```

## TiltCard.tsx (3D tilt toward the pointer, with glare and depth layers)
```tsx
import { motion, useMotionTemplate, useMotionValue, useReducedMotion, useSpring, useTransform } from "motion/react";
import type { ReactNode } from "react";

export function TiltCard({ children, max = 8, className }: { children: ReactNode; max?: number; className?: string }) {
  const reduce = useReducedMotion();
  const x = useMotionValue(0.5), y = useMotionValue(0.5);
  const cfg = { stiffness: 180, damping: 18 };
  const rx = useSpring(useTransform(y, [0, 1], [max, -max]), cfg);
  const ry = useSpring(useTransform(x, [0, 1], [-max, max]), cfg);
  const gx = useTransform(x, (v) => `${v * 100}%`), gy = useTransform(y, (v) => `${v * 100}%`);
  const glare = useMotionTemplate`radial-gradient(420px circle at ${gx} ${gy}, rgb(255 255 255 / 0.22), transparent 55%)`;
  if (reduce) return <div className={className}>{children}</div>;
  return (
    <div style={{ perspective: 1000 }} className="group">
      <motion.div className={"relative [transform-style:preserve-3d] will-change-transform " + (className ?? "")}
        style={{ rotateX: rx, rotateY: ry }}
        onPointerMove={(e) => { if (e.pointerType !== "mouse") return; const r = e.currentTarget.getBoundingClientRect();
          x.set((e.clientX - r.left) / r.width); y.set((e.clientY - r.top) / r.height); }}
        onPointerLeave={() => { x.set(0.5); y.set(0.5); }}>
        {children}
        <motion.div aria-hidden style={{ background: glare }}
          className="pointer-events-none absolute inset-0 rounded-[inherit] opacity-0 transition-opacity duration-300 group-hover:opacity-100" />
      </motion.div>
    </div>
  );
}
// Depth inside the card: <div style={{ transform: "translateZ(40px)" }}> on the title or
// product image makes it float above the card's face. Give the card its rounded corner
// and overflow-hidden on an inner wrapper, not on the tilting element.
```

## Micro-interactions (src/components/motion/Micro.tsx)
```tsx
import { AnimatePresence, animate, motion, useInView, useMotionValue, useTransform } from "motion/react";
import { Check, Copy } from "lucide-react";
import { useEffect, useRef, useState } from "react";

/** A number that counts to its value when it enters, and to each new value after. */
export function AnimatedNumber({ value, format = (n: number) => n.toLocaleString("en-NG") }: {
  value: number; format?: (n: number) => string }) {
  const ref = useRef<HTMLSpanElement>(null);
  const inView = useInView(ref, { once: true });
  const mv = useMotionValue(0);
  const text = useTransform(mv, (v) => format(Math.round(v)));
  useEffect(() => { if (inView) { const c = animate(mv, value, { duration: 1.2, ease: [0.22, 1, 0.36, 1] }); return c.stop; } }, [inView, value]);
  return <motion.span ref={ref} className="tabular-nums">{text}</motion.span>;
}

/** Copy with an icon that pops into a check. */
export function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [done, setDone] = useState(false);
  return (
    <button type="button" className="inline-flex h-9 items-center gap-1.5 rounded-full border px-3 text-sm font-medium"
      onClick={async () => { await navigator.clipboard.writeText(text); setDone(true); setTimeout(() => setDone(false), 1500); }}>
      <AnimatePresence mode="wait" initial={false}>
        <motion.span key={done ? "y" : "n"} initial={{ scale: 0.5, opacity: 0 }} animate={{ scale: 1, opacity: 1 }}
          exit={{ scale: 0.5, opacity: 0 }} transition={{ type: "spring", stiffness: 500, damping: 25 }}>
          {done ? <Check className="h-4 w-4 text-green-600" /> : <Copy className="h-4 w-4" />}
        </motion.span>
      </AnimatePresence>
      {done ? "Copied" : label}
    </button>
  );
}

/** A button that shows its work: label, then spinner, then a check. */
export function ActionButton({ onAction, children, className }: {
  onAction: () => Promise<unknown>; children: React.ReactNode; className?: string }) {
  const [state, setState] = useState<"idle" | "busy" | "done">("idle");
  return (
    <motion.button layout type="button" disabled={state === "busy"} whileTap={{ scale: 0.97 }}
      className={"inline-flex h-11 items-center justify-center gap-2 rounded-full bg-primary px-5 font-medium text-primary-foreground " + (className ?? "")}
      onClick={async () => { setState("busy"); try { await onAction(); setState("done"); setTimeout(() => setState("idle"), 1600); } catch { setState("idle"); } }}>
      <AnimatePresence mode="popLayout" initial={false}>
        <motion.span key={state} initial={{ y: 10, opacity: 0 }} animate={{ y: 0, opacity: 1 }} exit={{ y: -10, opacity: 0 }}
          transition={{ duration: 0.18 }} className="inline-flex items-center gap-2">
          {state === "busy" ? <span className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
            : state === "done" ? <><Check className="h-4 w-4" /> Done</> : children}
        </motion.span>
      </AnimatePresence>
    </motion.button>
  );
}

/** A check that draws itself: form sent, order placed, paid. */
export function SuccessCheck({ size = 72 }: { size?: number }) {
  return (
    <motion.svg width={size} height={size} viewBox="0 0 52 52" initial="hidden" animate="show" className="text-green-600">
      <motion.circle cx="26" cy="26" r="24" fill="none" stroke="currentColor" strokeWidth="3"
        variants={{ hidden: { pathLength: 0 }, show: { pathLength: 1, transition: { duration: 0.5 } } }} />
      <motion.path d="M15 27l7 7 15-15" fill="none" stroke="currentColor" strokeWidth="3.5" strokeLinecap="round" strokeLinejoin="round"
        variants={{ hidden: { pathLength: 0 }, show: { pathLength: 1, transition: { delay: 0.4, duration: 0.35 } } }} />
    </motion.svg>
  );
}

/** Shake a field once when it fails: <motion.div animate={shake ? SHAKE : {}} key={attempt}> */
export const SHAKE = { x: [0, -6, 6, -4, 4, 0], transition: { duration: 0.35 } };

/** Toggle with a spring thumb. */
export function Toggle({ on, onChange, label }: { on: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button type="button" role="switch" aria-checked={on} aria-label={label} onClick={() => onChange(!on)}
      className={"flex h-7 w-12 items-center rounded-full p-1 transition-colors " + (on ? "justify-end bg-primary" : "justify-start bg-muted")}>
      <motion.span layout transition={{ type: "spring", stiffness: 600, damping: 32 }} className="h-5 w-5 rounded-full bg-white shadow" />
    </button>
  );
}
```
Tabs and segmented controls use the NavPill pattern (`layoutId`) for their active
background. Lists wrap rows in `<AnimatePresence initial={false}>` with
`<motion.li layout initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, height: 0 }}>`.

## MeshGradient.tsx (the calm animated backdrop)
```tsx
import { motion, useReducedMotion } from "motion/react";
const BLOBS = [
  { c: "bg-primary/40", pos: "-left-24 -top-24", size: "h-[28rem] w-[28rem]", d: 26 },
  { c: "bg-accent/40", pos: "right-[-6rem] top-10", size: "h-[24rem] w-[24rem]", d: 32 },
  { c: "bg-primary/25", pos: "left-1/3 bottom-[-8rem]", size: "h-[22rem] w-[22rem]", d: 38 },
];
export function MeshGradient() {
  const reduce = useReducedMotion();
  return (
    <div aria-hidden className="pointer-events-none absolute inset-0 -z-10 overflow-hidden">
      {BLOBS.map((b, i) => (
        <motion.div key={i} className={`absolute rounded-full blur-3xl ${b.c} ${b.pos} ${b.size}`}
          animate={reduce ? undefined : { x: [0, 60, -30, 0], y: [0, -40, 30, 0], scale: [1, 1.1, 0.95, 1] }}
          transition={{ duration: b.d, repeat: Infinity, ease: "easeInOut" }} />
      ))}
    </div>
  );
}
```
Put `<Grain />` over it. Text sits on it directly only when the contrast holds; otherwise
on a `bg-background/70 backdrop-blur` panel.

## Magnetic.tsx (hero buttons only, desktop)
```tsx
import { motion, useMotionValue, useSpring } from "motion/react";
import type { ReactNode } from "react";
export function Magnetic({ children, range = 12 }: { children: ReactNode; range?: number }) {
  const x = useMotionValue(0), y = useMotionValue(0);
  const sx = useSpring(x, { stiffness: 300, damping: 20 }), sy = useSpring(y, { stiffness: 300, damping: 20 });
  return (
    <motion.div style={{ x: sx, y: sy }} className="inline-block"
      onPointerMove={(e) => { const r = e.currentTarget.getBoundingClientRect();
        x.set(((e.clientX - r.left) / r.width - 0.5) * range * 2); y.set(((e.clientY - r.top) / r.height - 0.5) * range * 2); }}
      onPointerLeave={() => { x.set(0); y.set(0); }}>
      {children}
    </motion.div>
  );
}
```

## useCountUp.ts and PinnedFeatures.tsx (GSAP + ScrollTrigger)
In components, prefer `useGSAP(() => { … }, { scope: ref })` from `@gsap/react`: it
reverts everything on unmount. The effects below show the same cleanup by hand.
```ts
import { useEffect, useRef } from "react";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
gsap.registerPlugin(ScrollTrigger);

export function useCountUp(value: number, formatter: (n: number) => string = (n) => n.toLocaleString("en-NG")) {
  const ref = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    const el = ref.current; if (!el) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) { el.textContent = formatter(value); return; }
    const obj = { n: 0 };
    const tween = gsap.to(obj, { n: value, duration: 1.4, ease: "power2.out",
      onUpdate: () => { el.textContent = formatter(Math.round(obj.n)); },
      scrollTrigger: { trigger: el, start: "top 85%", once: true } });
    return () => { tween.scrollTrigger?.kill(); tween.kill(); };
  }, [value, formatter]);
  return ref;
}
```
```tsx
// Pinned: the mockup stays while captions swap. Desktop only; phones get a stacked list.
useEffect(() => {
  if (!window.matchMedia("(min-width: 1024px)").matches) return;
  const ctx = gsap.context(() => {
    const tl = gsap.timeline({ scrollTrigger: { trigger: section.current, start: "top top",
      end: "+=300%", pin: true, scrub: 0.6, snap: 1 / (steps.length - 1) } });
    steps.forEach((_, i) => {
      if (i > 0) tl.to(captions.current[i - 1], { opacity: 0.3, y: -8 }).to(captions.current[i], { opacity: 1, y: 0 }, "<")
                  .to(frames.current[i - 1], { opacity: 0 }, "<").to(frames.current[i], { opacity: 1 }, "<");
    });
  }, section);
  return () => ctx.revert();
}, []);
```

## Grain.tsx, Glow.tsx, Glitter.tsx, CursorGlow.tsx
```tsx
export function Grain() {
  return <div aria-hidden className="pointer-events-none fixed inset-0 z-[1] opacity-[0.06] mix-blend-multiply dark:mix-blend-soft-light"
    style={{ backgroundImage: `url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='200' height='200'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/></filter><rect width='100%' height='100%' filter='url(%23n)' opacity='0.9'/></svg>")` }} />;
}

import { motion, useReducedMotion } from "motion/react";
export function Glow({ className }: { className?: string }) {
  const reduce = useReducedMotion();
  const drift = reduce ? {} : { animate: { x: [0, 40, 0], y: [0, -30, 0] }, transition: { duration: 12, repeat: Infinity, repeatType: "mirror" as const, ease: "easeInOut" } };
  return (
    <div aria-hidden className={"pointer-events-none absolute inset-0 -z-10 overflow-hidden " + (className ?? "")}>
      <motion.div {...drift} className="absolute -left-20 top-10 h-72 w-72 rounded-full bg-primary/30 blur-3xl" />
      <motion.div {...drift} className="absolute right-0 top-40 h-80 w-80 rounded-full bg-accent/30 blur-3xl" />
    </div>
  );
}

export function Glitter({ count = 8 }: { count?: number }) {
  const reduce = useReducedMotion();
  if (reduce) return null;
  const stars = Array.from({ length: count }, (_, i) => ({ i, left: (i * 37) % 100, top: (i * 53) % 100, d: 2 + (i % 3) }));
  return (
    <div aria-hidden className="pointer-events-none absolute inset-0 hidden md:block">
      {stars.map((s) => (
        <motion.span key={s.i} className="absolute h-1.5 w-1.5 rounded-full bg-accent"
          style={{ left: `${s.left}%`, top: `${s.top}%` }}
          animate={{ opacity: [0, 1, 0], scale: [0.4, 1.2, 0.4] }}
          transition={{ duration: s.d, repeat: Infinity, delay: s.i * 0.4, ease: "easeInOut" }} />
      ))}
    </div>
  );
}

export function CursorGlow() {                      // dark themes, desktop only
  const [pos, setPos] = useState({ x: -1000, y: -1000 });
  useEffect(() => { const h = (e: PointerEvent) => setPos({ x: e.clientX, y: e.clientY });
    window.addEventListener("pointermove", h); return () => window.removeEventListener("pointermove", h); }, []);
  return <div aria-hidden className="pointer-events-none fixed inset-0 z-[1] hidden md:block"
    style={{ background: `radial-gradient(400px at ${pos.x}px ${pos.y}px, rgb(255 255 255 / 0.06), transparent 70%)` }} />;
}
```

## ShaderBackdrop.tsx (WebGL, no library)
```tsx
import { useEffect, useRef } from "react";
const VERT = `attribute vec2 p; void main(){ gl_Position = vec4(p, 0.0, 1.0); }`;
const FRAG = `precision highp float; uniform float u_time; uniform vec2 u_res; uniform vec3 u_c1; uniform vec3 u_c2;
float hash(vec2 p){ return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float noise(vec2 p){ vec2 i = floor(p), f = fract(p); f = f*f*(3.0-2.0*f);
  return mix(mix(hash(i), hash(i+vec2(1,0)), f.x), mix(hash(i+vec2(0,1)), hash(i+vec2(1,1)), f.x), f.y); }
float fbm(vec2 p){ float v = 0.0, a = 0.5; for(int i=0;i<5;i++){ v += a*noise(p); p *= 2.0; a *= 0.5; } return v; }
void main(){ vec2 uv = gl_FragCoord.xy / u_res; uv.x *= u_res.x / u_res.y; float t = u_time * 0.05;
  vec2 q = vec2(fbm(uv + t), fbm(uv + vec2(5.2, 1.3) - t));
  float n = fbm(uv + 2.0 * q + vec2(1.7, 9.2)); vec3 col = mix(u_c1, u_c2, smoothstep(0.2, 0.8, n));
  gl_FragColor = vec4(col, 1.0); }`;

export function ShaderBackdrop({ c1 = [0.11, 0.2, 0.35], c2 = [0.85, 0.55, 0.2], className }: {
  c1?: [number, number, number]; c2?: [number, number, number]; className?: string;
}) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const canvas = ref.current; if (!canvas) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const gl = canvas.getContext("webgl", { antialias: false, alpha: false }); if (!gl) return;
    const sh = (t: number, s: string) => { const o = gl.createShader(t)!; gl.shaderSource(o, s); gl.compileShader(o); return o; };
    const prog = gl.createProgram()!; gl.attachShader(prog, sh(gl.VERTEX_SHADER, VERT)); gl.attachShader(prog, sh(gl.FRAGMENT_SHADER, FRAG));
    gl.linkProgram(prog); gl.useProgram(prog);
    const buf = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
    const p = gl.getAttribLocation(prog, "p"); gl.enableVertexAttribArray(p); gl.vertexAttribPointer(p, 2, gl.FLOAT, false, 0, 0);
    const uT = gl.getUniformLocation(prog, "u_time"), uR = gl.getUniformLocation(prog, "u_res");
    gl.uniform3fv(gl.getUniformLocation(prog, "u_c1"), c1); gl.uniform3fv(gl.getUniformLocation(prog, "u_c2"), c2);
    let raf = 0, last = 0, visible = true;
    const io = new IntersectionObserver(([e]) => { visible = e.isIntersecting; }); io.observe(canvas);
    const resize = () => { const d = Math.min(devicePixelRatio, 1.5); canvas.width = canvas.clientWidth * d; canvas.height = canvas.clientHeight * d; gl.viewport(0, 0, canvas.width, canvas.height); };
    resize(); window.addEventListener("resize", resize);
    const frame = (t: number) => { raf = requestAnimationFrame(frame); if (!visible || t - last < 33) return; last = t;
      gl.uniform1f(uT, t / 1000); gl.uniform2f(uR, canvas.width, canvas.height); gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4); };
    raf = requestAnimationFrame(frame);
    return () => { cancelAnimationFrame(raf); io.disconnect(); window.removeEventListener("resize", resize); };
  }, [c1, c2]);
  return <canvas ref={ref} aria-hidden className={"absolute inset-0 -z-10 h-full w-full bg-gradient-to-br from-primary to-accent " + (className ?? "")} />;
}
```
The gradient classes are the fallback when WebGL is off. Colours are the palette's primary
and partner as 0 to 1 RGB. Keep text on a solid or `bg-background/80 backdrop-blur` layer.

## PageTransition.tsx (routes)
```tsx
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useEffect } from "react";
import { useLocation, useOutlet } from "react-router-dom";
export function PageTransition() {
  const location = useLocation(); const outlet = useOutlet(); const reduce = useReducedMotion();
  useEffect(() => { window.scrollTo({ top: 0 }); }, [location.pathname]);
  if (reduce) return <>{outlet}</>;
  return (
    <AnimatePresence mode="wait">
      <motion.div key={location.pathname} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -8 }} transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}>
        {outlet}
      </motion.div>
    </AnimatePresence>
  );
}
```
Use it as the element of the customer layout route; keep admin routes outside it.

## Marquee (CSS only)
```css
@keyframes marquee { from { transform: translateX(0); } to { transform: translateX(-50%); } }
.marquee { display: flex; width: max-content; animation: marquee 40s linear infinite; }
.marquee:hover { animation-play-state: paused; }
@media (prefers-reduced-motion: reduce) { .marquee { animation: none; } }
```
Render the items twice inside `.marquee` so the loop is seamless.

## Fonts in index.html
```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Manrope:wght@400..800&family=Fraunces:ital,opsz,wght@0,9..144,300..700;1,9..144,300..700&display=swap" rel="stylesheet">
```
```css
h1, h2, h3 { font-feature-settings: "ss01", "cv11"; text-wrap: balance; }
```
