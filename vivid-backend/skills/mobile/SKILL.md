---
name: mobile
description: How to make an Expo (React Native) app look and feel like a native iOS and Android app a real business would ship, rather than a website squeezed onto a phone. Applies to every turn of a mobile project.
---

# Mobile design method

You are building an app a real business puts in its customers' pockets, next to apps
made by teams of fifty. A screen is finished when someone holding the phone in one hand,
on a bus, understands it in three seconds and can do the main thing with their thumb, on a
390pt iPhone and a 412dp Android, in light and dark mode, with large text turned on.

A phone app is not a small website. There is no header nav, no footer, no hero banner, no
hover, no "scroll down to learn more". There are tabs for places, stacks for depth, sheets
for quick tasks, and lists for almost everything. Build with those.

## Structure: tabs, stacks and sheets
- Two to five tabs for the places people return to every day (Home, Search or Browse,
  Orders or Bookings, Profile). A tab is a place, never an action: "New post" is a button,
  not a tab. Five is the ceiling; four is usually better.
- Every tab has an Ionicons icon, outline when inactive and filled when active, and a
  one-word label. The active tint is the primary colour; inactive is muted.
- Depth is a stack pushed from a tab: list, then detail, then an edit or checkout step.
  Stack screens have a native header with a title and back button. Never more than three
  levels deep from a tab.
- Quick, self-contained tasks open as a sheet (`presentation: "formSheet"` with detents,
  or `"modal"` for full-height forms): filters, add to cart options, add an item, sign in,
  share. A sheet has one job, a clear close or done, and returns the user where they were.
- The first screen of the first tab is the app's front door: in its first 600pt it says
  what this is (a greeting, the business name or the user's name), shows the one thing
  people come for (today's bookings, the menu, the balance), and offers the main action.
- The owner's tools (managing orders, stock, bookings) are not customer tabs. See Roles.

## Layout and spacing
- Screen gutter px-4 (16pt) on every screen, the same everywhere. Section gaps gap-6 or
  mt-6; items inside a card gap-2 or gap-3. Spacing on a 4pt grid: 4/8/12/16/20/24/32/48.
- Safe areas are not optional: content never sits under the status bar, the notch, the
  Dynamic Island, the Android camera cutout or the home indicator. Use SafeAreaView with
  the edges no navigator covers, or `useSafeAreaInsets()` for custom headers and pinned
  bottom bars (`style={{ paddingBottom: insets.bottom + 12 }}`).
- Lists are FlatList or SectionList, always: `keyExtractor`, `contentContainerClassName`
  for the gutter, `ItemSeparatorComponent` or `gap`, `ListHeaderComponent` for what sits
  above the list (search, chips, a summary card), `ListEmptyComponent`. A screen whose body
  is a list is ONE FlatList with a header, not a ScrollView wrapping a list.
- Horizontal rails (categories, featured items) are horizontal FlatLists with
  `showsHorizontalScrollIndicator={false}`, a fixed item width (w-40, w-64) and the gutter as
  `contentContainerClassName="px-4 gap-3"`, so the last card peeks at the edge.
- Forms: KeyboardAvoidingView (`behavior={Platform.OS === "ios" ? "padding" : undefined}`)
  around a ScrollView with `keyboardShouldPersistTaps="handled"`; the submit button stays
  reachable above the keyboard.
- Pinned bottom actions (Add to cart, Book, Pay, Continue) sit in a bar above the home
  indicator with a top border or blur, a full-width button, and the price or summary on it
  ("Add to cart · ₦12,500"). The scroll content gets bottom padding so nothing hides under it.
- Grids of products or photos: FlatList with `numColumns={2}`, `columnWrapperClassName="gap-3"`,
  items `flex-1`, never fixed percentages.

## Type
- Use the system font (San Francisco on iOS, Roboto on Android) for body text unless the
  brand needs character; then pick a pairing from the fonts reference and load it with
  `@expo-google-fonts/*` and `useFonts` in app/_layout.tsx. The display face goes on
  large titles and prices only.
- Scale: large title text-3xl font-bold (the first screen of a tab), screen title
  text-xl font-semibold, section title text-lg font-semibold, body text-base, secondary
  text-sm, caption text-xs. Nothing else.
- Line length is fine on phones; line height is not: body `leading-6`, titles `leading-tight`.
- Respect Dynamic Type and Android font scale: never `allowFontScaling={false}`; let rows
  grow in height; use `numberOfLines` with an ellipsis for titles in cards and rows.
- Numbers that change (prices, counts, timers) use `tabular-nums` (`fontVariant: ["tabular-nums"]`)
  so they do not jiggle.

## Colour and theme
- Pick one palette from the palettes table by audience and put it in tailwind.config.js
  as the theme tokens: background, foreground, card, muted, border, primary and
  primary-foreground, each with its dark value. Use hex or rgb there (NativeWind does not
  read oklch on phones): convert the palette's values.
- Every surface uses tokens with their `dark:` pair (`bg-background dark:bg-background-dark`).
  A literal `bg-white` or `text-black` is a dark-mode bug.
- One accent: the primary colour carries the main button, the active tab, links, and one
  highlight per screen. Status colours only for status: green for success/paid, amber
  for pending, red for errors and destructive actions, each as a tinted pill
  (`bg-green-500/15 text-green-700 dark:text-green-400`).
- Dark mode is a first-class design: backgrounds near-black not pure black (#0b0b0f),
  cards one step lighter (#16161c), borders subtle (#26262e), text off-white (#ececf1).
- The status bar follows the screen: `<StatusBar style="auto" />`, or `"light"` over a dark
  hero image.

## Imagery
- Every image has a fixed aspect ratio (`aspect-square`, `aspect-[4/3]`, `aspect-video`),
  `contentFit="cover"`, rounded corners matching the cards (rounded-2xl), and a placeholder
  colour (`placeholder={{ blurhash }}` or a `bg-card` wrapper). Use expo-image, never the
  bare React Native Image for remote pictures.
- Uploaded files are the product: show them large on detail screens (full-bleed
  `aspect-square` or `aspect-[4/5]` at the top) and as thumbnails in lists (w-16 h-16 or
  w-20 h-20 rounded-xl).
- No upload for a product, a person or a place? Make one with generate_image, one per item,
  with the same setting phrase in every prompt so the set looks like one catalogue ("on a
  light grey studio surface, soft light, three-quarter view"). Never ship a grey box or a
  require() of a file that does not exist (that crashes the app).
- People: the apps are for Nigeria. Every generated picture with a person shows Black
  Africans and the prompt says so ("a smiling Black Nigerian woman in her thirties holding
  a phone"). Avatars in seeded data use initials on a tinted circle when there is no photo.
- The logo is the app icon. If the user uploaded one, it goes at assets/icon.png and
  assets/adaptive-icon.png (square, opaque, the mark centred with margin) and in the app
  at h-8 where the brand shows. If not, make one with generate_image kind=logo: a bold,
  simple symbol that reads at 60px on a home screen, in the palette's colours, no text.
  The builder writes the icon files from it.
- Illustrations (kind=illustration) for onboarding and empty states; one style for the app.

## Components and states
Build the kit in components/ui first (see the components reference) and use it
everywhere: Screen, Button, Card, ListRow, TextField, EmptyState, Skeleton, Badge, Avatar,
SectionHeader. Consistency is what makes an app feel designed.
- One primary button per screen. Secondary actions are outline or plain text buttons.
  Buttons say what happens ("Book for 2pm", "Pay ₦12,500", not "Submit", "OK").
- Every screen that loads shows a skeleton of its real layout (not a spinner in the middle
  of a white screen); every list has an empty state with an illustration or icon, one line
  and the action that fills it; every failure shows what went wrong in plain words with a
  Retry.
- Every action gets feedback within 100ms: a pressed state, a haptic for meaningful
  actions (add to cart, like, complete, pay), then a confirmation (a banner, a check, the
  item appearing in the list). Destructive actions confirm with `Alert.alert` naming what is
  lost, and offer Undo where they can.
- Pull to refresh on every list that comes from a server. Optimistic updates for likes,
  cart, toggles and reorders; roll back with a message on failure.
- Search: a TextField with a search icon at the top of the list, filtering as you type,
  with a clear button, and chips for filters under it.
- Numbers: prices in the spec's currency and formatted (₦12,500 via
  `Intl.NumberFormat("en-NG", { style: "currency", currency: "NGN", maximumFractionDigits: 0 })`),
  dates relative when recent ("2h ago", "Tomorrow, 2:00 PM").

## Touch and gestures
- Every tappable thing is at least 44x44pt; small icons get `hitSlop={10}`. Rows are
  tappable across their full width.
- Pressed feedback on everything that can be pressed: `active:opacity-70` on rows and
  cards, a subtle scale (0.97) on buttons and product cards.
- Swipe actions on rows where people manage many items (delete a cart line, archive, mark
  done) with react-native-gesture-handler's Swipeable, always with a visible alternative
  (an edit mode or a menu), because swipes are not discoverable.
- No hover states; nothing is only discoverable by long-press. Long-press can add a
  context menu, never hold the only way to do something.
- Android back: every sheet and modal closes with the hardware back button (expo-router
  does this; custom overlays must handle it).

## Roles: customers never see the owner's tools
- A business app has two audiences. The customer tabs carry customer places only. The
  owner's area (orders to fulfil, bookings, stock, menu editor) is a separate route group,
  app/(admin)/, reached from a row in the Profile tab ("Manage the shop") that only owners
  see, and it has its own tabs or a dashboard screen.
- Without a backend, gate the owner's area with a PIN screen, remember it with
  expo-secure-store, and tell the user in the final reply that this keeps customers out
  but is not real security until a backend is linked.
- With Supabase, the gate is real: Supabase auth, a profiles table with a role, row level
  security, and a guard (`Stack.Protected`) on the admin group. Hiding a row is not security.
- The owner's screens look like a tool: dense lists, status pills, segmented filters
  (New · Preparing · Ready · Done), and one-tap state changes with a haptic. The customer
  screens look like a shop.

## Sign-in, onboarding and permissions
- Do not put sign-in in front of browsing. Let people look first; ask them to sign in at
  the moment it matters (checkout, booking, posting), in a sheet, then continue where they
  were.
- Onboarding, if the spec needs one: at most three swipeable screens with an illustration,
  a headline and one line each, Skip on every screen, shown once (AsyncStorage flag).
- Ask for a permission (camera, photos, location, notifications) only when the user taps
  the thing that needs it, after a one-line explanation of why; handle "denied" with a
  sentence and a button to `Linking.openSettings()`.

## Accessibility
- Every icon-only button has `accessibilityLabel` and `accessibilityRole="button"`.
  Images that carry meaning have `accessibilityLabel`; decorative ones do not.
- Text contrast at least 4.5:1 in both themes; never convey status by colour alone (the
  pill also has a word).
- Group a card's content (`accessible` on the Pressable) so a screen reader reads one
  sentence per card, not ten fragments.

## Performance
- FlatList for anything that can grow past twenty items; pass `initialNumToRender`,
  `windowSize` and memoised row components (`React.memo`) for long lists; keep
  `renderItem` stable with `useCallback`.
- expo-image with `cachePolicy="memory-disk"` for remote pictures; generated and uploaded
  images are local requires and already fast.
- No heavy work in render; derive lists with `useMemo`. Never setState in a loop.

## Every app ships with
- app.json: the real app name (`expo.name`, short enough for a home screen: at most 12
  characters shows untruncated), a slug, `ios.bundleIdentifier` and `android.package`
  left as the builder set them, the splash background in the palette's background colour.
- The icon from the logo (the builder writes it when a logo is generated; for an
  uploaded logo, write assets/icon.png and assets/adaptive-icon.png from it with run_command).
- A launch that never shows a white flash: hide the splash screen after fonts and the
  first data load (`SplashScreen.preventAutoHideAsync()` then `hideAsync()`).
- A Profile or More tab with: the account (or Sign in), settings that matter (notifications,
  appearance if the app overrides the system), contact and support (a WhatsApp link for
  Nigerian businesses: `Linking.openURL("https://wa.me/234...")`), and the app version.

## Copy
- Titles say what the screen is for ("Your orders", "Book a table"), not what it is
  ("Orders screen"). Buttons say what happens. Empty states say what to do next.
- Short: phone screens punish long sentences. One line of help text at most under a
  heading.
- Nigerian context when the spec is Nigerian: naira, WhatsApp as the contact channel,
  local places (Lekki, Wuse 2, Ikeja), phone formats like 0803 123 4567, delivery by
  area and fee.

## Things that crash in Expo Go
The user tries the app in Expo Go on their own phone; a crash there is a broken app.
- Never import expo-notifications directly: loading it throws on Android in Expo Go.
  Reminders go through lib/notify.ts (the native-apis reference), which loads it lazily
  and only where it works.
- No packages with their own native code outside the Expo SDK (the builder refuses them).
- Guard device-only calls with `Platform.OS !== "web"` so the browser preview renders too.

## Before you finish a screen
Check, in this order: it renders on a 390pt phone without anything clipped, overlapping
or under the notch or home indicator; dark mode has no white boxes or black text on black;
the main action is visible without scrolling; every list has loading, empty and error
states; every image has an aspect ratio and its file exists; every tappable thing gives
feedback; text still fits with a larger font; nothing says placeholder, TODO or lorem ipsum;
no DOM elements, window, document or localStorage anywhere.
