# 3D on the web (three.js through React Three Fiber)

A real 3D scene is the boldest thing a page can do, so it is used once, in the hero or a
product viewer, and only when the brand earns it: crypto and token launches, NFT drops,
agencies and portfolios, tech products, gadgets, luxury goods, or when the user asks for
3D. Everything else uses the CSS tilt and shader from the patterns file.

## Setup
```
npm install three @react-three/fiber @react-three/drei
npm install -D @types/three
```
Fiber 9 matches React 19. All 3D code lives in `src/components/three/`; pages never
import three directly, only the lazy wrapper.

## The rules
- **One scene per page**, lazy-loaded, mounted only when on screen, with a poster (a
  gradient or a rendered image) shown first and kept when WebGL is missing, the device is
  weak, or reduced motion is on.
- `<Canvas dpr={[1, 1.75]} gl={{ antialias: true, powerPreference: "high-performance" }}>`;
  `frameloop="demand"` for static viewers (render on interaction only), `"always"` only
  while something floats or spins, and never while off-screen.
- Budget: under 100k triangles, textures at most 2048px, GLB models Draco-compressed and
  under 3 MB. Procedural shapes (a torus knot, spheres, a coin, a card) need no model.
- Light the scene with drei's `<Environment preset="city" />` (or "studio" for products)
  plus `<ContactShadows>` under the object: that is what makes it look expensive.
- Materials in the palette: `meshPhysicalMaterial` with `clearcoat` for glossy objects,
  `MeshTransmissionMaterial` for glass (heavy: desktop only), metalness 0.6 to 1 for
  coins and gadgets. Colours are the palette's primary and partner.
- Text stays in HTML over or beside the canvas, never inside WebGL.
- Phones: the scene is smaller, `dpr={1}`, no transmission, no post-processing; below
  640px with a weak GPU, the poster only.

## Hero3D.tsx (lazy wrapper: the only thing pages import)
```tsx
import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { useReducedMotion } from "motion/react";

const Scene = lazy(() => import("./HeroScene"));

function webglOk() {
  try { const c = document.createElement("canvas"); return !!(c.getContext("webgl2") || c.getContext("webgl")); }
  catch { return false; }
}

export function Hero3D({ poster, className }: { poster: React.ReactNode; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [show, setShow] = useState(false);
  const reduce = useReducedMotion();
  useEffect(() => {
    const weak = (navigator as any).hardwareConcurrency <= 4 && window.innerWidth < 640;
    if (reduce || weak || !webglOk() || !ref.current) return;
    const io = new IntersectionObserver(([e]) => e.isIntersecting && setShow(true), { rootMargin: "200px" });
    io.observe(ref.current);
    return () => io.disconnect();
  }, [reduce]);
  return (
    <div ref={ref} className={"relative " + (className ?? "")}>
      {!show && poster}
      {show && <Suspense fallback={poster}><Scene /></Suspense>}
    </div>
  );
}
```

## HeroScene.tsx: a floating object that follows the pointer
```tsx
import { Canvas, useFrame } from "@react-three/fiber";
import { ContactShadows, Environment, Float, RoundedBox } from "@react-three/drei";
import { useRef } from "react";
import * as THREE from "three";

function Thing() {
  const ref = useRef<THREE.Group>(null!);
  useFrame(({ pointer }, dt) => {
    // ease toward the pointer: the object turns to look at you
    ref.current.rotation.y = THREE.MathUtils.damp(ref.current.rotation.y, pointer.x * 0.5, 4, dt);
    ref.current.rotation.x = THREE.MathUtils.damp(ref.current.rotation.x, -pointer.y * 0.3, 4, dt);
  });
  return (
    <group ref={ref}>
      <Float speed={1.4} rotationIntensity={0.4} floatIntensity={0.8}>
        {/* A card, a coin, a phone, a gem: model the brand's object from primitives */}
        <RoundedBox args={[3.2, 2, 0.08]} radius={0.12} smoothness={6}>
          <meshPhysicalMaterial color="#1d4ed8" metalness={0.4} roughness={0.25} clearcoat={1} clearcoatRoughness={0.1} />
        </RoundedBox>
      </Float>
    </group>
  );
}

export default function HeroScene() {
  return (
    <Canvas dpr={[1, 1.75]} camera={{ position: [0, 0, 6], fov: 35 }} className="!h-[420px] md:!h-[560px]">
      <ambientLight intensity={0.4} />
      <Thing />
      <ContactShadows position={[0, -1.6, 0]} opacity={0.35} blur={2.5} scale={10} />
      <Environment preset="city" />
    </Canvas>
  );
}
```
Ideas by brand, all from drei primitives, no model files:
- Fintech and wallets: the bank card above with the logo as a decal, or stacked cards.
- Crypto, token launch: a metallic coin (`<Cylinder args={[1.4, 1.4, 0.18, 64]}>`, metalness
  1, roughness 0.2) spinning slowly with the token mark on its face.
- NFT drop: the artwork on a thin glossy slab that tilts toward the pointer.
- Agencies and portfolios: `<MeshDistortMaterial>` on a sphere or a torus knot, in the
  palette's colours, gently distorting; or `<Text3D>` of one short word.
- Tech and SaaS: a floating phone or laptop frame (RoundedBox) with the `ProductMockup`
  screenshot as its screen texture (`useTexture`).

## ProductViewer.tsx: drag to turn a product (shops with GLB models)
```tsx
import { Canvas } from "@react-three/fiber";
import { Center, ContactShadows, Environment, PresentationControls, useGLTF } from "@react-three/drei";

function Model({ url }: { url: string }) { const { scene } = useGLTF(url); return <primitive object={scene} />; }

export default function ProductViewer({ url }: { url: string }) {
  return (
    <Canvas frameloop="demand" dpr={[1, 1.75]} camera={{ position: [0, 0, 4], fov: 40 }} className="aspect-square">
      <PresentationControls global snap polar={[-0.2, 0.3]} azimuth={[-Math.PI / 2, Math.PI / 2]}>
        <Center><Model url={url} /></Center>
      </PresentationControls>
      <ContactShadows position={[0, -1, 0]} opacity={0.4} blur={2} />
      <Environment preset="studio" />
    </Canvas>
  );
}
```
Only when the user supplies GLB files (or asks for a generated simple product); photos
stay the default for shops. Preload with `useGLTF.preload(url)` on hover of the card.

## Scroll-driven 3D
Drive the scene from the page scroll instead of animating it on its own: read
`useScroll` from motion in the page, pass the progress (0 to 1) as a prop, and set the
rotation or camera position in `useFrame` with `THREE.MathUtils.damp`. Never use drei's
`ScrollControls` (it takes over the page's scroll).

## Before you finish
The poster shows first and the page is complete without WebGL; the canvas has a fixed
height (no layout jump); nothing renders while off-screen; the Lighthouse main thread
stays calm on a phone (`dpr` capped, no transmission there); the build still passes
`npx tsc --noEmit`.
