# Motion on phones

Native apps feel alive because things respond to the finger and settle into place, not
because things fly in. The budget: press feedback on everything, entrances for lists and
the first content of a screen, layout animation when lists change, one signature moment
(adding to cart, completing a habit, a payment success). Nothing loops except loading.

Use react-native-reanimated (in the template). Keep durations 150 to 300ms, springs with
damping 15 to 20. Respect reduced motion: Reanimated's entering animations follow the
system setting (`ReduceMotion.System`) by default; do not override it.

## Entrances
```tsx
import Animated, { FadeInDown, FadeIn, LinearTransition } from "react-native-reanimated";

// List rows cascade in once, 40ms apart, capped so long lists do not wait.
<Animated.View entering={FadeInDown.delay(Math.min(index, 8) * 40).duration(280)}>
  <ProductCard product={item} />
</Animated.View>
```
Put `className` on a plain View inside the Animated.View and the animation on the
Animated.View, so NativeWind and Reanimated never fight over the same style.

## Lists that change
`itemLayoutAnimation={LinearTransition}` on an `Animated.FlatList`, or `layout={LinearTransition}`
on each row, so removing a cart line or completing a task slides the others into place
instead of jumping. Removed rows use `exiting={FadeOut.duration(180)}`.

## Press feedback
```tsx
const scale = useSharedValue(1);
const style = useAnimatedStyle(() => ({ transform: [{ scale: scale.value }] }));
<Pressable onPressIn={() => (scale.value = withSpring(0.97))} onPressOut={() => (scale.value = withSpring(1))}>
  <Animated.View style={style}>…</Animated.View>
</Pressable>
```
Cards and primary buttons scale; rows only dim (`active:opacity-70`).

## Signature moments
- Add to cart: the button's label changes to "Added" with a check for 1.2s, the cart tab
  badge bumps (scale 1 → 1.3 → 1 spring), a light haptic.
- Complete (a habit, a task, a delivery): the check fills with a spring, the row fades to
  done, a success haptic; a streak or progress ring animates to its new value
  (`withTiming` on an SVG circle's strokeDashoffset through `useAnimatedProps`).
- Success screens (order placed, booking confirmed): a large check that scales in, the
  reference number, what happens next, and a single button back to the app.

## Headers that react to scroll
A detail screen with a photo: the photo scales up slightly on pull-down and the header
background fades in as the title scrolls under it (`useAnimatedScrollHandler` with
`interpolate` on `scrollY`). One such screen per app is enough.

## Never
Animating every element on every screen, delays longer than 300ms before content, motion
that blocks a tap, confetti for routine actions, parallax on lists.
