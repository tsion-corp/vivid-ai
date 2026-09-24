# The component kit

Build these in components/ui/ on the first build and use them on every screen. They use
the theme tokens from tailwind.config.js, so light and dark mode come for free. Adapt the
radius and weights to the palette, not the structure.

## Screen
```tsx
// components/ui/Screen.tsx
import { ScrollView, View, type ScrollViewProps } from "react-native";
import { SafeAreaView, type Edge } from "react-native-safe-area-context";

type Props = ScrollViewProps & { scroll?: boolean; edges?: Edge[] };

export function Screen({ scroll = true, edges = ["top"], children, contentContainerClassName, ...rest }: Props) {
  return (
    <SafeAreaView edges={edges} className="flex-1 bg-background dark:bg-background-dark">
      {scroll ? (
        <ScrollView
          contentContainerClassName={`px-4 pb-10 gap-6 ${contentContainerClassName ?? ""}`}
          keyboardShouldPersistTaps="handled"
          {...rest}>
          {children}
        </ScrollView>
      ) : (
        <View className="flex-1">{children}</View>
      )}
    </SafeAreaView>
  );
}
```
A stack screen with a native header uses `edges={[]}` (the header covers the top); a tab's
root screen uses `["top"]`. List screens use `scroll={false}` and put their FlatList inside.

## Button
```tsx
// components/ui/Button.tsx
import * as Haptics from "expo-haptics";
import { ActivityIndicator, Platform, Pressable, Text, type PressableProps } from "react-native";

type Variant = "primary" | "secondary" | "ghost" | "destructive";
const base = "h-12 flex-row items-center justify-center gap-2 rounded-xl px-5 active:opacity-80";
const variants: Record<Variant, string> = {
  primary: "bg-primary",
  secondary: "border border-border bg-card dark:border-border-dark dark:bg-card-dark",
  ghost: "",
  destructive: "bg-red-600",
};
const labels: Record<Variant, string> = {
  primary: "text-primary-foreground",
  secondary: "text-foreground dark:text-foreground-dark",
  ghost: "text-primary",
  destructive: "text-white",
};

export function Button({ title, variant = "primary", loading, haptic = true, className, onPress, disabled, ...rest }:
  PressableProps & { title: string; variant?: Variant; loading?: boolean; haptic?: boolean; className?: string }) {
  return (
    <Pressable
      accessibilityRole="button"
      disabled={disabled || loading}
      onPress={(e) => {
        if (haptic && Platform.OS !== "web") Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
        onPress?.(e);
      }}
      className={`${base} ${variants[variant]} ${disabled ? "opacity-50" : ""} ${className ?? ""}`}
      {...rest}>
      {loading ? <ActivityIndicator color={variant === "primary" ? "#fff" : undefined} /> :
        <Text className={`text-base font-semibold ${labels[variant]}`}>{title}</Text>}
    </Pressable>
  );
}
```

## Card, ListRow, SectionHeader
```tsx
export function Card({ className, ...rest }: ViewProps & { className?: string }) {
  return <View className={`rounded-2xl border border-border bg-card p-4 dark:border-border-dark dark:bg-card-dark ${className ?? ""}`} {...rest} />;
}

export function ListRow({ title, subtitle, left, right, onPress }: {
  title: string; subtitle?: string; left?: React.ReactNode; right?: React.ReactNode; onPress?: () => void }) {
  return (
    <Pressable onPress={onPress} accessible accessibilityRole={onPress ? "button" : undefined}
      className="min-h-14 flex-row items-center gap-3 py-3 active:opacity-70">
      {left}
      <View className="flex-1">
        <Text numberOfLines={1} className="text-base font-medium text-foreground dark:text-foreground-dark">{title}</Text>
        {subtitle ? <Text numberOfLines={2} className="text-sm text-muted dark:text-muted-dark">{subtitle}</Text> : null}
      </View>
      {right ?? (onPress ? <Ionicons name="chevron-forward" size={18} color="#9a9aa6" /> : null)}
    </Pressable>
  );
}

export function SectionHeader({ title, action, onAction }: { title: string; action?: string; onAction?: () => void }) {
  return (
    <View className="mb-3 flex-row items-end justify-between">
      <Text className="text-lg font-semibold text-foreground dark:text-foreground-dark">{title}</Text>
      {action ? <Pressable hitSlop={10} onPress={onAction}><Text className="text-sm font-medium text-primary">{action}</Text></Pressable> : null}
    </View>
  );
}
```

## TextField
```tsx
export function TextField({ label, error, hint, ...rest }: TextInputProps & { label: string; error?: string; hint?: string }) {
  return (
    <View className="gap-1.5">
      <Text className="text-sm font-medium text-foreground dark:text-foreground-dark">{label}</Text>
      <TextInput
        placeholderTextColor="#9a9aa6"
        className={`h-12 rounded-xl border bg-card px-4 text-base text-foreground dark:bg-card-dark dark:text-foreground-dark ${error ? "border-red-500" : "border-border dark:border-border-dark"}`}
        {...rest}
      />
      {error ? <Text className="text-sm text-red-600">{error}</Text> :
        hint ? <Text className="text-sm text-muted dark:text-muted-dark">{hint}</Text> : null}
    </View>
  );
}
```
Set the right keyboard and autofill on every field: `keyboardType="phone-pad"` +
`textContentType="telephoneNumber"` + `autoComplete="tel"` for phones, `"email-address"` +
`autoCapitalize="none"` for email, `"number-pad"` for codes (`textContentType="oneTimeCode"`),
`secureTextEntry` for passwords. Chain fields with `returnKeyType="next"` and `onSubmitEditing`.

## EmptyState, Skeleton, Badge, Avatar
```tsx
export function EmptyState({ icon, title, body, action, onAction }: {
  icon: keyof typeof Ionicons.glyphMap; title: string; body?: string; action?: string; onAction?: () => void }) {
  return (
    <View className="items-center gap-3 px-8 py-16">
      <View className="h-16 w-16 items-center justify-center rounded-full bg-primary/10">
        <Ionicons name={icon} size={28} color="#e8590c" />
      </View>
      <Text className="text-center text-lg font-semibold text-foreground dark:text-foreground-dark">{title}</Text>
      {body ? <Text className="text-center text-base text-muted dark:text-muted-dark">{body}</Text> : null}
      {action ? <Button title={action} onPress={onAction} className="mt-2" /> : null}
    </View>
  );
}

// A pulsing block the shape of the real content; compose rows from it.
export function Skeleton({ className }: { className?: string }) {
  const opacity = useSharedValue(0.5);
  useEffect(() => { opacity.value = withRepeat(withTiming(1, { duration: 700 }), -1, true); }, []);
  const style = useAnimatedStyle(() => ({ opacity: opacity.value }));
  return <Animated.View style={style}><View className={`rounded-lg bg-border dark:bg-border-dark ${className ?? ""}`} /></Animated.View>;
}

const tones = {
  success: "bg-green-500/15 text-green-700 dark:text-green-400",
  warning: "bg-amber-500/15 text-amber-700 dark:text-amber-400",
  danger: "bg-red-500/15 text-red-700 dark:text-red-400",
  neutral: "bg-muted/15 text-muted dark:text-muted-dark",
} as const;
export function Badge({ label, tone = "neutral" }: { label: string; tone?: keyof typeof tones }) {
  const [bg, ...text] = tones[tone].split(" ");
  return <View className={`self-start rounded-full px-2.5 py-1 ${bg}`}><Text className={`text-xs font-semibold ${text.join(" ")}`}>{label}</Text></View>;
}

export function Avatar({ name, uri, size = 40 }: { name: string; uri?: string; size?: number }) {
  const initials = name.split(" ").map((p) => p[0]).slice(0, 2).join("").toUpperCase();
  return uri ? <Image source={{ uri }} style={{ width: size, height: size, borderRadius: size / 2 }} /> : (
    <View style={{ width: size, height: size, borderRadius: size / 2 }} className="items-center justify-center bg-primary/15">
      <Text className="font-semibold text-primary">{initials}</Text>
    </View>
  );
}
```

## Pinned bottom bar
```tsx
export function BottomBar({ children }: { children: React.ReactNode }) {
  const insets = useSafeAreaInsets();
  return (
    <View style={{ paddingBottom: Math.max(insets.bottom, 12) }}
      className="border-t border-border bg-background px-4 pt-3 dark:border-border-dark dark:bg-background-dark">
      {children}
    </View>
  );
}
```
The screen's FlatList or ScrollView sits in a `flex-1` View above it, so nothing scrolls under it.

## Segmented control and chips
Filters with two to four options are a segmented control (a row of equal Pressables in a
rounded-xl bg-card track, the selected one bg-background with a shadow); longer or
optional filters are chips in a horizontal ScrollView (rounded-full, border, selected =
bg-primary with primary-foreground text). Both give a selection haptic on change.

## Money and time helpers (lib/format.ts)
```ts
export const money = (n: number, currency = "NGN") =>
  new Intl.NumberFormat("en-NG", { style: "currency", currency, maximumFractionDigits: 0 }).format(n);

export function ago(date: string | Date) {
  const s = (Date.now() - new Date(date).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return new Date(date).toLocaleDateString("en-NG", { day: "numeric", month: "short" });
}
```
