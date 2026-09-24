# Navigation with Expo Router

Files under app/ are routes. The template already has:

```
app/_layout.tsx          root Stack; global.css, providers, fonts, splash
app/(tabs)/_layout.tsx   the tab bar
app/(tabs)/index.tsx     the first tab
app/+not-found.tsx       unknown routes
public/index.html        the web preview's page (keep the vivid:editor block)
```

A typical first build grows it to:

```
app/_layout.tsx                  Stack: (tabs), details, sheets, (admin), sign-in
app/(tabs)/_layout.tsx           Home, Browse, Orders, Profile
app/(tabs)/index.tsx
app/(tabs)/browse.tsx
app/(tabs)/orders.tsx
app/(tabs)/profile.tsx
app/product/[id].tsx             detail, pushed from any tab
app/cart.tsx                     sheet
app/checkout.tsx                 stack screen after the cart
app/sign-in.tsx                  sheet, opened when an action needs an account
app/(admin)/_layout.tsx          the owner's area, guarded
app/(admin)/index.tsx            owner dashboard
app/(admin)/orders/[id].tsx
```

## The root stack
```tsx
// app/_layout.tsx
import "../global.css";
import { Stack } from "expo-router";
import * as SplashScreen from "expo-splash-screen";
import { StatusBar } from "expo-status-bar";
import { SafeAreaProvider } from "react-native-safe-area-context";
import { StoreProvider, useStore } from "@/lib/store";

SplashScreen.preventAutoHideAsync();

function RootStack() {
  const { ready, isOwner } = useStore();
  useEffect(() => { if (ready) SplashScreen.hideAsync(); }, [ready]);
  if (!ready) return null;
  return (
    <Stack screenOptions={{ headerBackTitle: "Back", headerShadowVisible: false }}>
      <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
      <Stack.Screen name="product/[id]" options={{ title: "" }} />
      <Stack.Screen name="cart" options={{ presentation: "formSheet", sheetAllowedDetents: [0.6, 1],
        sheetGrabberVisible: true, title: "Your cart" }} />
      <Stack.Screen name="sign-in" options={{ presentation: "modal", title: "Sign in" }} />
      <Stack.Protected guard={isOwner}>
        <Stack.Screen name="(admin)" options={{ headerShown: false }} />
      </Stack.Protected>
    </Stack>
  );
}

export default function RootLayout() {
  return (
    <SafeAreaProvider>
      <StoreProvider><RootStack /></StoreProvider>
      <StatusBar style="auto" />
    </SafeAreaProvider>
  );
}
```
`Stack.Protected` removes the guarded routes while its guard is false: links to them fall
back to the first screen, so owners-only screens can never be reached by customers.

## Tabs
```tsx
// app/(tabs)/_layout.tsx
import { Tabs } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { useColorScheme } from "react-native";

type Icon = keyof typeof Ionicons.glyphMap;
const tab = (title: string, icon: string) => ({
  title,
  tabBarIcon: ({ color, focused }: { color: string; focused: boolean }) =>
    <Ionicons name={(focused ? icon : `${icon}-outline`) as Icon} size={24} color={color} />,
});

export default function TabLayout() {
  const dark = useColorScheme() === "dark";
  return (
    <Tabs screenOptions={{
      headerShown: false,
      tabBarActiveTintColor: "#e8590c",
      tabBarInactiveTintColor: dark ? "#9a9aa6" : "#6b6b76",
      tabBarStyle: { backgroundColor: dark ? "#0b0b0f" : "#ffffff", borderTopColor: dark ? "#26262e" : "#e6e6ea" },
    }}>
      <Tabs.Screen name="index" options={tab("Home", "home")} />
      <Tabs.Screen name="browse" options={tab("Browse", "search")} />
      <Tabs.Screen name="orders" options={{ ...tab("Orders", "receipt"), tabBarBadge: undefined }} />
      <Tabs.Screen name="profile" options={tab("Profile", "person")} />
    </Tabs>
  );
}
```
A badge on a tab (`tabBarBadge: cartCount || undefined`) for counts that need attention.
Icons must exist in Ionicons in both forms (`home`/`home-outline`); check the name.

## Stack screens and params
- `app/product/[id].tsx`: read the id with `const { id } = useLocalSearchParams<{ id: string }>()`.
- Link to it: `<Link href={{ pathname: "/product/[id]", params: { id: p.id } }} asChild><Pressable>…</Pressable></Link>`,
  or `router.push({ pathname: "/product/[id]", params: { id } })` from a handler.
- Title and header buttons from inside the screen, once the data is known:
  `<Stack.Screen options={{ title: product.name, headerRight: () => <ShareButton /> }} />`.
- A header over a full-bleed photo: `headerTransparent: true, headerTitle: ""` and a
  round translucent back button; the photo starts under the status bar.
- Large titles on iOS lists: `headerLargeTitle: true` with the list as the screen's
  first child (`contentInsetAdjustmentBehavior="automatic"` on the FlatList).
- Back: `router.back()`. After finishing a flow (order placed, booking confirmed) go to
  the result and clear the flow: `router.dismissAll(); router.push("/orders/abc")`, or
  `router.replace("/(tabs)/orders")`.

## Sheets and modals
- `presentation: "formSheet"` with `sheetAllowedDetents: [0.5, 1]` and
  `sheetGrabberVisible: true` for quick tasks (cart, filters, options). On Android and
  the web it shows as a modal; design it to work full height too.
- `presentation: "modal"` for full forms (sign in, new listing, edit profile), with a
  Cancel on the left and Save on the right in the header (`headerLeft`, `headerRight`).
- Pass data back by writing to the store, not through params.

## Flows that span screens
Checkout, booking and sign-up are a stack of small screens (one question each) or one
scrolling screen with sections, never a long single form with twenty fields. Keep the
flow's draft in the store so going back keeps what was typed. Show progress in the
header ("Step 2 of 3") for flows longer than two screens.

## Deep links and sharing
The app's scheme is in app.json (`scheme`). Share links to detail screens with
`Linking.createURL("/product/" + id)`; expo-router opens them on the right screen.
