# Depth, glass and 3D on phones

Flat apps look generated. Premium apps have layers: an opaque content layer (lists, cards,
media) and a floating functional layer (tab bar, headers, pinned actions, sheets) made of
blur, with soft shadows and one piece of real 3D where it earns its place. Everything
here runs in Expo Go, on device and in the web preview.

## Surfaces and elevation (every app)
Three levels, used the same way on every screen:
- **Base**: the screen background (`bg-background`).
- **Raised**: cards and list groups. Light mode: `bg-card`, a hairline border
  (`border-black/5`) and a soft, large shadow. Dark mode: no shadow; a lighter surface
  (`#1c1c1e` on `#0b0b0f`) and a `border-white/10` hairline.
- **Floating**: the tab bar, headers over content, pinned bottom bars, FABs, sheets.
  Blur (`BlurView`) plus a stronger shadow.

```tsx
// lib/elevation.ts — React Native's boxShadow style works on iOS, Android and web.
export const shadow = {
  raised: { boxShadow: "0 1px 2px rgba(0,0,0,0.04), 0 8px 24px rgba(0,0,0,0.08)" },
  floating: { boxShadow: "0 12px 32px rgba(0,0,0,0.16)" },
  glow: (hex: string) => ({ borderRadius: 999, boxShadow: `0 10px 30px ${hex}55` }),   // the primary pill button only
};
// const dark = useColorScheme() === "dark"; <View style={dark ? undefined : shadow.raised} …>
```
Primary buttons get the accent glow (`shadow.glow(primary)`) in light mode: the one
coloured shadow on the screen.

## Shape contrast
Uniform 8px corners everywhere look like a template. Mix:
- Very round: buttons and chips are pills (`rounded-full`); sheets 28 at the top; the
  floating tab bar 28.
- Medium: cards and images 20 to 24 (`rounded-3xl` for hero cards, `rounded-2xl` for
  list cards).
- Tight: inputs and small thumbnails 12 (`rounded-xl`).

## Glass (the functional layer only)
```tsx
import { BlurView } from "expo-blur";
<BlurView intensity={50} tint="systemChromeMaterial" style={{ borderRadius: 24, overflow: "hidden" }}>…</BlurView>
```
- Use it for the tab bar, a header that content scrolls under, pinned bottom bars, and
  floating buttons over photos (a round `BlurView` behind the back and heart icons on a
  product photo). Never on every card: glass everywhere flattens hierarchy.
- `overflow: "hidden"` is what makes the radius work. Text on glass is foreground at
  full strength, never muted.
- iOS 26 Liquid Glass is optional polish: `npx expo install expo-glass-effect`, then
  `isLiquidGlassAvailable() ? <GlassView …> : <BlurView …>`. The fallback is required.

## Atmosphere: gradients and light
- A tinted gradient behind the hero of Home or a detail screen only, hue shift within 30°
  of the primary (`expo-linear-gradient`, primary at 18% fading to the background).
- A soft mesh: two or three blurred SVG circles behind the header, in the primary and its
  partner colour, at 20 to 35% opacity:
```tsx
import Svg, { Circle, Defs, RadialGradient, Stop } from "react-native-svg";
<Svg style={{ position: "absolute", inset: 0 }} pointerEvents="none">
  <Defs>
    <RadialGradient id="a" cx="20%" cy="10%" r="60%"><Stop offset="0" stopColor={primary} stopOpacity="0.35" /><Stop offset="1" stopColor={primary} stopOpacity="0" /></RadialGradient>
    <RadialGradient id="b" cx="90%" cy="30%" r="50%"><Stop offset="0" stopColor={partner} stopOpacity="0.25" /><Stop offset="1" stopColor={partner} stopOpacity="0" /></RadialGradient>
  </Defs>
  <Circle cx="20%" cy="10%" r="70%" fill="url(#a)" /><Circle cx="90%" cy="30%" r="60%" fill="url(#b)" />
</Svg>
```
- Dark themes: a single glow behind the hero number or card (the primary at 25% in a
  radial gradient) makes the screen feel lit rather than black.
- Never a full-screen purple-to-blue gradient; never a gradient behind body text.

## 3D with perspective (the real 3D for generated apps)
Perspective transforms run on the UI thread on device and as CSS 3D on the web. Put
`perspective` first in the transform array, keep rotations within ±12°.

### TiltCard: a card that tilts toward the finger and lights up
The hero object of a screen: a bank card, a ticket, a product photo, a membership pass.
```tsx
// components/motion/TiltCard.tsx
import { Gesture, GestureDetector } from "react-native-gesture-handler";
import Animated, { interpolate, useAnimatedStyle, useSharedValue, withSpring } from "react-native-reanimated";
import { LinearGradient } from "expo-linear-gradient";

export function TiltCard({ children, max = 10 }: { children: React.ReactNode; max?: number }) {
  const rx = useSharedValue(0), ry = useSharedValue(0), w = useSharedValue(1), h = useSharedValue(1);
  const spring = { damping: 15, stiffness: 180 };
  const pan = Gesture.Pan().minDistance(0)
    .onBegin((e) => { ry.value = withSpring((e.x / w.value - 0.5) * 2 * max, spring); rx.value = withSpring(-(e.y / h.value - 0.5) * 2 * max, spring); })
    .onChange((e) => { ry.value = (e.x / w.value - 0.5) * 2 * max; rx.value = -(e.y / h.value - 0.5) * 2 * max; })
    .onFinalize(() => { rx.value = withSpring(0, spring); ry.value = withSpring(0, spring); });
  const card = useAnimatedStyle(() => ({
    transform: [{ perspective: 800 }, { rotateX: `${rx.value}deg` }, { rotateY: `${ry.value}deg` },
                { scale: withSpring(rx.value || ry.value ? 1.03 : 1, spring) }],
  }));
  const glare = useAnimatedStyle(() => ({
    opacity: interpolate(Math.abs(rx.value) + Math.abs(ry.value), [0, max * 2], [0, 0.35]),
    transform: [{ translateX: ry.value * 6 }, { translateY: -rx.value * 6 }],
  }));
  return (
    <GestureDetector gesture={pan}>
      <Animated.View style={card}
        onLayout={(e) => { w.value = e.nativeEvent.layout.width; h.value = e.nativeEvent.layout.height; }}>
        {children}
        <Animated.View pointerEvents="none" style={[{ position: "absolute", inset: -40 }, glare]}>
          <LinearGradient colors={["rgba(255,255,255,0.0)", "rgba(255,255,255,0.8)", "rgba(255,255,255,0.0)"]}
            start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }} style={{ flex: 1 }} />
        </Animated.View>
      </Animated.View>
    </GestureDetector>
  );
}
```
Wrap the content in `overflow-hidden rounded-3xl` inside the TiltCard so the glare stays
inside the card. A pan inside a ScrollView: add `.activeOffsetX([-8, 8])` if the page
must still scroll vertically over it. The root layout wraps everything in `<GestureHandlerRootView style={{ flex: 1 }}>`
(the navigation reference's root stack); without it gestures do nothing.

### FlipCard: front and back (a bank card's details, a ticket's QR, a flash card)
```tsx
const flip = useSharedValue(0); // 0 front, 1 back
const front = useAnimatedStyle(() => ({ backfaceVisibility: "hidden",
  transform: [{ perspective: 1000 }, { rotateY: `${interpolate(flip.value, [0, 1], [0, 180])}deg` }] }));
const back = useAnimatedStyle(() => ({ backfaceVisibility: "hidden", position: "absolute", inset: 0,
  transform: [{ perspective: 1000 }, { rotateY: `${interpolate(flip.value, [0, 1], [180, 360])}deg` }] }));
// onPress: flip.value = withSpring(flip.value ? 0 : 1, { damping: 16, stiffness: 120 }) + a light haptic
```

### Carousel with depth (featured items, onboarding, plans)
A horizontal `Animated.FlatList` with `snapToInterval={itemW + gap}` and
`decelerationRate="fast"`. Each item reads the scroll position and turns away as it
leaves the centre:
```tsx
const style = useAnimatedStyle(() => {
  const p = (scrollX.value - index * itemW) / itemW;           // -1 … 0 … 1
  return { transform: [{ perspective: 900 }, { rotateY: `${interpolate(p, [-1, 0, 1], [-18, 0, 18], Extrapolation.CLAMP)}deg` },
                       { scale: interpolate(Math.abs(p), [0, 1], [1, 0.9], Extrapolation.CLAMP) }],
           opacity: interpolate(Math.abs(p), [0, 1], [1, 0.6], Extrapolation.CLAMP) };
});
```

### Layered parallax on a hero card
Inside a TiltCard, give the layers different depths: the background image moves opposite
the tilt (`translateX: -ry * 1.5`), the foreground product or text moves with it
(`translateX: ry * 1.5`). This reads as real depth with no 3D engine.

### Device tilt (optional enhancement)
`expo-sensors` DeviceMotion can drive the same shared values so a card follows the phone:
`npx expo install expo-sensors`, `DeviceMotion.setUpdateInterval(16)`, clamp to ±10°,
smooth with `withSpring`, and only when `await DeviceMotion.isAvailableAsync()` and
`Platform.OS !== "web"`. The touch tilt must work without it.

## What not to use
- `three`, `@react-three/fiber`, `expo-gl` scenes: unreliable in Expo Go and the web
  preview. Real 3D in these apps is perspective transforms.
- `@shopify/react-native-skia` only when an effect truly needs a shader and the user asked
  for it: on the web preview it needs CanvasKit loaded first (`WithSkiaWeb`).
- Glass on content cards, more than one coloured shadow per screen, rotations over 15°,
  3D on list rows. One 3D hero per screen at most, and not on every screen.
