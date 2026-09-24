# Fonts in the app

The system font (San Francisco, Roboto) is a good default for body text on phones and
costs nothing. Add a display face when the brand needs character: install its package with
`npx expo install @expo-google-fonts/<family> expo-font` and load it in app/_layout.tsx
before hiding the splash screen.

| pairing | display (titles, prices) | body | feel |
|---|---|---|---|
| system | system bold | system | utility, fintech, tools |
| grotesk | Space Grotesk 700 | system | sneakers, street, youth |
| editorial | Fraunces 600 | system | bakery, restaurants, craft |
| luxe | Playfair Display 700 | system | salons, beauty, hotels |
| rounded | Nunito 800 | Nunito 400/600 | community, kids, learning |
| geometric | Outfit 700 | Outfit 400/500 | events, startups, fitness |
| modern | Inter Tight 700 | Inter 400/500/600 | platforms, logistics |
| bold | Sora 700 | system | sport, bold offers |

## Loading
```tsx
import { useFonts, SpaceGrotesk_700Bold } from "@expo-google-fonts/space-grotesk";

const [loaded] = useFonts({ SpaceGrotesk_700Bold });
useEffect(() => { if (loaded && ready) SplashScreen.hideAsync(); }, [loaded, ready]);
if (!loaded) return null;
```

## Using them with NativeWind
On phones a font file is one weight: `font-bold` does not make a regular face bold. Name
each weight as its own family in tailwind.config.js and use the family, not a weight class,
with that face:
```js
theme: { extend: { fontFamily: {
  display: ["SpaceGrotesk_700Bold"],
  body: ["Inter_400Regular"], "body-medium": ["Inter_500Medium"], "body-semibold": ["Inter_600SemiBold"],
} } }
```
`<Text className="font-display text-3xl">`: no `font-bold` next to a custom family.
Two families at most; the system font counts as one.
