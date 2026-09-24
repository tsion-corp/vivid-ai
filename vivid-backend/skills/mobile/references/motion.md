# Motion on phones

Native apps feel alive because things answer the finger and settle into place with
physics, not because things fly in. Every screen gets the baseline; each app gets one or
two signature moments; nothing loops except loading and one ambient background at most.

Use react-native-reanimated 4 and react-native-gesture-handler (both in the template).
Never pin or upgrade them by hand; if something is missing, `npx expo install`.

## The motion vocabulary (use these numbers)
- Spatial springs (position, scale, rotation) may overshoot a little:
  `{ damping: 16, stiffness: 220 }`; a snappier press `{ damping: 15, stiffness: 300 }`.
- Effect changes (opacity, colour) never bounce: `withTiming(v, { duration: 200 })`.
- Entrances 240 to 320ms, 40 to 60ms stagger, capped at 8 items so long lists never wait.
- Nothing delays content more than 300ms. Motion never blocks a tap.
- Layout (entering/exiting) animations use `.duration()` with easing, **never
  `.springify()`**: springified layout animations do not run in the web preview.
  `withSpring` on shared values is fine everywhere.
- Build animation builders outside components (or in `useMemo`).
- Reduced motion: Reanimated's entering animations follow the system setting; for your
  own loops check `useReducedMotion()` and render the final state.

## Baseline on every screen
1. **Press feedback** on every Pressable: cards and primary buttons scale to 0.97 with a
   spring and a light haptic (`PressableScale` in the components kit); rows dim
   (`active:opacity-70`).
2. **Entrances** for the first content of a screen and for list rows:
```tsx
import Animated, { FadeInDown, FadeOut, LinearTransition, Easing } from "react-native-reanimated";
const enter = (i: number) => FadeInDown.duration(280).delay(Math.min(i, 8) * 45).easing(Easing.out(Easing.cubic));

<Animated.View entering={enter(index)} exiting={FadeOut.duration(160)} layout={LinearTransition.duration(220)}>
  <ProductCard product={item} />
</Animated.View>
```
   **NativeWind's `className` does nothing on Reanimated's `Animated.View`**: styles on an
   Animated.View are `style` objects; put `className` on a plain View inside it.
3. **Lists that change** slide into place (`layout={LinearTransition}` on rows, or
   `itemLayoutAnimation` on an `Animated.FlatList`): removing a cart line, completing a task.
4. **State changes transition** instead of snapping, with Reanimated's CSS transitions
   (they work on iOS, Android and web):
```tsx
<Animated.View style={{ width: 52, height: 32, borderRadius: 16, padding: 3,
  alignItems: on ? "flex-end" : "flex-start", backgroundColor: on ? "#16a34a" : "#d4d4d8",
  transitionProperty: "backgroundColor", transitionDuration: 200 }}>
  <Animated.View layout={LinearTransition.duration(180)} style={{ width: 26, height: 26, borderRadius: 13, backgroundColor: "#fff" }} />
</Animated.View>
```
   Good for toggles, selected chips, expanding cards (`height`/`width`), tab pills.
5. **Haptics paired with motion** (always guard `Platform.OS !== "web"`):
   - `selectionAsync()` when a toggle, chip, segment or picker changes.
   - `impactAsync(Light)` on a press that does something (add, like, next).
   - `impactAsync(Medium)` when a drag snaps or a card is swiped away.
   - `notificationAsync(Success)` on completion (paid, booked, done); `Error` on a failure.

## Micro-interactions to copy (components/motion/)

### AnimatedTabBar: a floating glass tab bar with a sliding pill
```tsx
// components/motion/AnimatedTabBar.tsx — in app/(tabs)/_layout.tsx:
// <Tabs screenOptions={{ headerShown: false }}
//   tabBar={(p) => <AnimatedTabBar {...p} icons={{ index: "home", shop: "bag", cart: "cart", profile: "person" }} />}>
import { Tabs } from "expo-router";
import type { ComponentProps } from "react";
import { BlurView } from "expo-blur";
import * as Haptics from "expo-haptics";
import { Ionicons } from "@expo/vector-icons";
import { useState } from "react";
import { Platform, Pressable, Text, View } from "react-native";
import Animated, { useAnimatedStyle, withSpring } from "react-native-reanimated";
import { useSafeAreaInsets } from "react-native-safe-area-context";

const PRIMARY = "#e8590c"; // the palette's primary
type BottomTabBarProps = Parameters<NonNullable<ComponentProps<typeof Tabs>["tabBar"]>>[0];

export function AnimatedTabBar({ state, descriptors, navigation, icons }:
  BottomTabBarProps & { icons: Record<string, string> }) {
  const insets = useSafeAreaInsets();
  const [w, setW] = useState(0);
  const slot = w / state.routes.length;
  const pill = useAnimatedStyle(() => ({
    width: slot - 8, transform: [{ translateX: withSpring(state.index * slot + 4, { damping: 18, stiffness: 220 }) }],
  }));
  return (
    <View style={{ position: "absolute", left: 16, right: 16, bottom: Math.max(insets.bottom, 12) }}>
      <BlurView intensity={60} tint="systemChromeMaterial"
        style={{ borderRadius: 28, overflow: "hidden", boxShadow: "0 10px 30px rgba(0,0,0,0.15)" }}>
        <View className="h-16 flex-row items-center border border-black/5 dark:border-white/10" style={{ borderRadius: 28 }}
          onLayout={(e) => setW(e.nativeEvent.layout.width)}>
          {w > 0 && <Animated.View style={[{ position: "absolute", top: 8, height: 48, borderRadius: 24,
            backgroundColor: PRIMARY + "22" }, pill]} />}
          {state.routes.map((route, i) => {
            const focused = state.index === i;
            const { options } = descriptors[route.key];
            const icon = icons[route.name] ?? "ellipse";
            return (
              <Pressable key={route.key} className="flex-1 items-center gap-0.5" accessibilityRole="tab"
                accessibilityState={{ selected: focused }} accessibilityLabel={options.title}
                onPress={() => {
                  if (!focused) { if (Platform.OS !== "web") Haptics.selectionAsync(); navigation.navigate(route.name); }
                }}>
                <View>
                  <Ionicons name={(focused ? icon : `${icon}-outline`) as any} size={22}
                    color={focused ? PRIMARY : "#8e8e93"} />
                  {options.tabBarBadge ? (
                    <View className="absolute -right-2.5 -top-1 min-w-4 items-center rounded-full bg-primary px-1">
                      <Text className="text-[10px] font-bold text-primary-foreground">{options.tabBarBadge}</Text>
                    </View>) : null}
                </View>
                <Text className={`text-[11px] ${focused ? "font-semibold text-primary" : "text-muted dark:text-muted-dark"}`}>{options.title}</Text>
              </Pressable>
            );
          })}
        </View>
      </BlurView>
    </View>
  );
}
```
Icons are Ionicons base names (the outline variant shows when inactive), keyed by route
name; each tab screen sets `options={{ title: "Home" }}`. Add bottom padding (about 96)
to every tab screen's scroll content so nothing hides under the floating bar. Badges
(cart count) go on the icon as a small pill with the bump animation below.

### Collapsing large-title header (one detail screen or the Home tab)
```tsx
const y = useSharedValue(0);
const onScroll = useAnimatedScrollHandler((e) => { y.value = e.contentOffset.y; });
const heroStyle = useAnimatedStyle(() => ({
  transform: [
    { translateY: interpolate(y.value, [-200, 0, 200], [-100, 0, 60], Extrapolation.CLAMP) },
    { scale: interpolate(y.value, [-200, 0], [2, 1], Extrapolation.CLAMP) },   // stretch on pull-down
  ],
}));
const barStyle = useAnimatedStyle(() => ({ opacity: interpolate(y.value, [80, 140], [0, 1], Extrapolation.CLAMP) }));
// <Animated.ScrollView onScroll={onScroll} scrollEventThrottle={16}>, the photo in an
// Animated.View with heroStyle; a BlurView header bar with barStyle holding the small title.
```

### Number that counts to its new value (balances, totals, streaks)
```tsx
export function useCountTo(target: number, ms = 800) {
  const [n, setN] = useState(target);
  const from = useRef(target);
  useEffect(() => {
    const start = Date.now(), a = from.current;
    const id = setInterval(() => {
      const t = Math.min(1, (Date.now() - start) / ms), e = 1 - Math.pow(1 - t, 3);
      setN(Math.round(a + (target - a) * e));
      if (t === 1) { clearInterval(id); from.current = target; }
    }, 16);
    return () => clearInterval(id);
  }, [target]);
  return n;
}
// <Text style={{ fontVariant: ["tabular-nums"] }}>{money(useCountTo(balance))}</Text>
```

### Success check (order placed, paid, booked, habit done)
```tsx
const s = useSharedValue(0);
useEffect(() => {
  s.value = withSequence(withSpring(1.15, { damping: 10, stiffness: 200 }), withSpring(1));
  if (Platform.OS !== "web") Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
}, []);
const style = useAnimatedStyle(() => ({ transform: [{ scale: s.value }], opacity: Math.min(1, s.value * 2) }));
// <Animated.View style={style}><View className="h-24 w-24 items-center justify-center rounded-full bg-green-500/15">
//   <Ionicons name="checkmark" size={48} color="#16a34a" /></View></Animated.View>
// then the title and the reference fade in (FadeInDown.delay(200)).
```

### Badge bump, heart pop, add-to-cart
- Cart badge: `scale.value = withSequence(withSpring(1.3), withSpring(1))` whenever the
  count changes, plus a light haptic.
- Favourite: the heart scales 0 → 1.2 → 1, filled in the accent colour, with the icon
  swapped; unliking just fades.
- Add to cart: the button label cross-fades to "Added ✓" for 1.2s (FadeIn/FadeOut on the
  label), the badge bumps.

### Progress ring (goals, streaks, delivery steps)
`react-native-svg` Circle with `strokeDasharray = circumference` and an animated
`strokeDashoffset` via `useAnimatedProps` on `Animated.createAnimatedComponent(Circle)`,
`withTiming(target, { duration: 700 })`, round line caps, the value in the middle.

### Swipe cards (discovery, matching, flash cards)
```tsx
const x = useSharedValue(0);
const pan = Gesture.Pan()
  .onChange((e) => { x.value += e.changeX; })
  .onEnd((e) => {
    if (Math.abs(x.value) > width * 0.3 || Math.abs(e.velocityX) > 800) {
      x.value = withSpring(Math.sign(x.value || e.velocityX) * width * 1.5, { velocity: e.velocityX });
      runOnJS(onSwipe)(x.value > 0 ? "right" : "left");
    } else x.value = withSpring(0);
  });
const card = useAnimatedStyle(() => ({
  transform: [{ translateX: x.value }, { rotate: `${interpolate(x.value, [-width, width], [-12, 12])}deg` }],
}));
// <GestureDetector gesture={pan}><Animated.View style={card}>…</Animated.View></GestureDetector>
```
Always pair swipes with visible buttons (✕ and ♥) that do the same thing.

### Skeleton shimmer
Blocks shaped like the real content, rounded-lg, pulsing opacity with a CSS animation:
```tsx
<Animated.View style={{ animationName: { from: { opacity: 0.45 }, to: { opacity: 1 } }, animationDuration: "900ms",
  animationIterationCount: "infinite", animationDirection: "alternate" }}>
  <View className="h-4 w-2/3 rounded-lg bg-border dark:bg-border-dark" />
</Animated.View>
```

## Signature moments (pick one or two per app, from the recipe)
- Shop: add-to-cart badge bump and the product image lifting into a 3D tilt on the detail.
- Food and delivery: an order tracker whose steps fill one by one with springs.
- Wallet and fintech: the balance counting to its value, a card that flips to show details.
- Fitness and habits: the progress ring filling and a success check on completion.
- Booking and events: the time chip sliding into the selected state, a ticket that flips.
- Community and dating: swipe cards, a heart pop.

## Never
Animating every element on every screen, delays over 300ms before content, bouncing
opacity or colour, confetti for routine actions, parallax on lists, `.springify()` layout
animations, shared-element transitions (experimental and broken on web), Moti (built for
Reanimated 3; breaks on 4), Lottie unless the user supplies a file.
