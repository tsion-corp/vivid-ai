# Device features (all run in Expo Go)

Install each with `npx expo install <pkg>` before importing it. The template already has
expo-haptics, expo-image, expo-linear-gradient, expo-blur, expo-web-browser, expo-font,
expo-splash-screen, @expo/vector-icons, react-native-reanimated, react-native-gesture-handler,
react-native-safe-area-context, react-native-svg and AsyncStorage.

| Need | Package | Notes |
|---|---|---|
| Pick a photo | expo-image-picker | library and camera in one API |
| Scan or custom camera | expo-camera | `CameraView`, barcode scanning built in |
| Location | expo-location | foreground only |
| Reminders | expo-notifications | ONLY through lib/notify.ts below: importing it crashes Expo Go on Android |
| Haptics | expo-haptics | in the template |
| Share | react-native `Share`, expo-sharing | text and links with Share; files with expo-sharing |
| Open a website | expo-web-browser | in-app browser; Linking for tel:, mailto:, wa.me, maps |
| Secrets on device | expo-secure-store | PINs and tokens only |
| Files | expo-file-system | the app's own documents directory |
| Contacts | expo-contacts | read only what is needed |
| Calendar | expo-calendar | add a booking to the calendar |
| Clipboard | expo-clipboard | copy a code or an account number |
| Audio and video | expo-audio, expo-video | |
| Maps | react-native-maps | Apple Maps on iOS, Google Maps on Android |
| Connectivity | @react-native-community/netinfo | offline banner |
| Blur and gradients | expo-blur, expo-linear-gradient | in the template |
| Charts and drawing | react-native-svg (in the template) | draw small charts with Path and Rect |
| Swipe rows | react-native-gesture-handler | `ReanimatedSwipeable` |
| Dates | pure JS: date-fns | `npx expo install date-fns` |

## The permission pattern
Ask when the user taps the feature, explain once, handle every answer:
```tsx
import * as ImagePicker from "expo-image-picker";
import { Alert, Linking } from "react-native";

export async function pickPhoto(): Promise<string | null> {
  const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
  if (!perm.granted) {
    Alert.alert("Photos are off", "Allow photo access in Settings to add a picture.", [
      { text: "Not now", style: "cancel" },
      { text: "Open Settings", onPress: () => Linking.openSettings() },
    ]);
    return null;
  }
  const result = await ImagePicker.launchImageLibraryAsync({
    mediaTypes: ["images"], allowsEditing: true, aspect: [1, 1], quality: 0.8,
  });
  return result.canceled ? null : result.assets[0].uri;
}
```
The camera is the same with `requestCameraPermissionsAsync` and `launchCameraAsync`.

## Location
```tsx
import * as Location from "expo-location";

const { status } = await Location.requestForegroundPermissionsAsync();
if (status !== "granted") return setError("Turn on location to see places near you.");
const here = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced });
const [place] = await Location.reverseGeocodeAsync(here.coords); // place.city, place.district
```
Always offer a manual choice (a list of areas) next to "Use my location".

## Local notifications (reminders)
**Never `import ... from "expo-notifications"` anywhere.** Since SDK 53, merely loading
that package inside Expo Go on Android throws ("push notifications were removed from
Expo Go") and the screen that imported it never renders. Expo Go is how the user tries
the app, so the package is loaded lazily, only where it can work, from one file:

```ts
// lib/notify.ts: the only place the app touches expo-notifications.
import Constants, { ExecutionEnvironment } from "expo-constants";
import { Platform } from "react-native";

type Notifications = typeof import("expo-notifications");

/** Expo Go on Android cannot load the module at all; the web preview has no notifications. */
export const notificationsAvailable =
  Platform.OS !== "web" &&
  !(Platform.OS === "android" && Constants.executionEnvironment === ExecutionEnvironment.StoreClient);

let cached: Notifications | null = null;
function load(): Notifications | null {
  if (!notificationsAvailable) return null;
  if (!cached) {
    // require, not import: the module is only evaluated here, when it is safe.
    cached = require("expo-notifications") as Notifications;
    cached.setNotificationHandler({
      handleNotification: async () => ({ shouldShowBanner: true, shouldShowList: true,
        shouldPlaySound: false, shouldSetBadge: false }),
    });
  }
  return cached;
}

export async function remind(title: string, body: string, date: Date): Promise<boolean> {
  const N = load();
  if (!N) return false;
  const { granted } = await N.requestPermissionsAsync();
  if (!granted) return false;
  await N.scheduleNotificationAsync({
    content: { title, body },
    trigger: { type: N.SchedulableTriggerInputTypes.DATE, date },
  });
  return true;
}
```
Screens import `remind` and `notificationsAvailable` from `@/lib/notify`, never the package.
When `notificationsAvailable` is false, the reminder control still shows, with one line:
"Reminders work in the installed app." Daily habits use `{ type: N.SchedulableTriggerInputTypes.DAILY,
hour, minute }`. Remote push (from a server) needs a real build; say so if the spec asks for it
and use local reminders in this version.

## Haptics vocabulary
- `Haptics.selectionAsync()`: changing a tab-like choice, chips, steppers, toggles.
- `Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light)`: pressing a primary button,
  adding to cart, liking.
- `Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success)`: an order placed,
  a payment done, a habit completed. `Warning` and `Error` for failures.
Never on scroll, never on every keypress. Guard with `Platform.OS !== "web"`.

## Maps
```tsx
import MapView, { Marker } from "react-native-maps";
<MapView className="h-64 w-full rounded-2xl"
  initialRegion={{ latitude: 6.4474, longitude: 3.4553, latitudeDelta: 0.05, longitudeDelta: 0.05 }}>
  {places.map((p) => <Marker key={p.id} coordinate={p.coords} title={p.name} />)}
</MapView>
```
Maps do not render in the web preview: on `Platform.OS === "web"` show a static card with
the address and an "Open in Maps" link instead, so the preview never breaks.

## Links out
- Call: `Linking.openURL("tel:+2348031234567")`.
- WhatsApp: `Linking.openURL("https://wa.me/2348031234567?text=" + encodeURIComponent(msg))`.
- Directions: `Linking.openURL(Platform.select({ ios: `maps:?daddr=${q}`, default: `geo:0,0?q=${q}` }))`.
- A website or a web checkout: `WebBrowser.openBrowserAsync(url)`.

## Not available here (refused by the builder)
Stripe's and Paystack's native SDKs, in-app purchases, Bluetooth, NFC, background
location, health data, widgets, and any package whose README says it needs a development
build or does not work in Expo Go. Offer the closest path (a Paystack checkout page in
expo-web-browser for payments) and tell the user in one sentence what a later native
build would add.

## The web preview
The user also watches the app in a browser. Guard device-only calls with
`Platform.OS === "web"` (haptics, camera, notifications, maps, secure store) so the preview
never crashes; show a sensible stand-in there.
