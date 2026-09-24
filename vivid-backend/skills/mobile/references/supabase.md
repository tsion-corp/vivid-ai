# Supabase in the app

The template has the client at lib/supabase.ts. It reads EXPO_PUBLIC_SUPABASE_URL and
EXPO_PUBLIC_SUPABASE_ANON_KEY (the builder writes them to .env), keeps the session in
AsyncStorage and refreshes it while the app is in the foreground:

```ts
import { supabase, supabaseConfigured } from "@/lib/supabase";
```
The app logic skill above (profiles, roles, policies, lifecycles as SQL functions) applies
exactly as it does to a website; this is how its pieces look in a phone app.

## The auth context
```tsx
// lib/auth.tsx
import type { Session } from "@supabase/supabase-js";

type Profile = { id: string; full_name: string | null; phone: string | null; role: "customer" | "owner" | "staff" };
const AuthCtx = createContext<{ session: Session | null; profile: Profile | null; loading: boolean;
  signOut: () => Promise<void>; refreshProfile: () => Promise<void> } | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [loading, setLoading] = useState(true);

  const loadProfile = async (s: Session | null) => {
    if (!s) return setProfile(null);
    const { data } = await supabase.from("profiles").select("*").eq("id", s.user.id).single();
    setProfile(data);
  };
  useEffect(() => {
    supabase.auth.getSession().then(async ({ data }) => {
      setSession(data.session); await loadProfile(data.session); setLoading(false);
    });
    const { data: sub } = supabase.auth.onAuthStateChange((_e, s) => { setSession(s); loadProfile(s); });
    return () => sub.subscription.unsubscribe();
  }, []);

  return (
    <AuthCtx.Provider value={{ session, profile, loading,
      signOut: async () => { await supabase.auth.signOut(); },
      refreshProfile: () => loadProfile(session) }}>
      {children}
    </AuthCtx.Provider>
  );
}
export const useAuth = () => useContext(AuthCtx)!;
```
app/_layout.tsx keeps the splash screen until `loading` is false and guards the owner
group with `<Stack.Protected guard={profile?.role === "owner"}>`.

## Sign-in on a phone
- Email one-time code is the smoothest: screen one asks for the email and calls
  `supabase.auth.signInWithOtp({ email, options: { shouldCreateUser: true } })`; screen two
  is a six-digit code field (`keyboardType="number-pad"`, `textContentType="oneTimeCode"`,
  `autoComplete="one-time-code"` so iOS offers the code from Mail) that calls
  `supabase.auth.verifyOtp({ email, token, type: "email" })`. Magic links that open a
  browser do not come back into Expo Go; do not use them.
- Email and password is fine when the spec says so; add "Forgot password" with the OTP
  reset (`resetPasswordForEmail` then `verifyOtp({ type: "recovery" })` and `updateUser`).
- After sign-in, a new user completes their profile (name, phone) once, then returns to
  what they were doing.
- Sign out lives in the Profile tab, with a confirmation.

## Data
- One hook per resource (`useOrders()`) returning `{ data, loading, error, refresh }`;
  `useFocusEffect` refreshes lists that change elsewhere.
- Owners see live orders with realtime:
```tsx
useEffect(() => {
  const ch = supabase.channel("orders")
    .on("postgres_changes", { event: "*", schema: "public", table: "orders" }, () => refresh())
    .subscribe();
  return () => { supabase.removeChannel(ch); };
}, []);
```
- State changes (accept an order, mark ready) go through the lifecycle SQL function with
  `supabase.rpc("advance_order", { order_id })`, never a client-side status write.

## Photos users upload
```ts
const uri = await pickPhoto();                    // native-apis reference
const body = await (await fetch(uri)).arrayBuffer();
const path = `${session.user.id}/${Date.now()}.jpg`;
const { error } = await supabase.storage.from("photos").upload(path, body, { contentType: "image/jpeg" });
const { data } = supabase.storage.from("photos").getPublicUrl(path);
```
Create the bucket and its policies in a migration (owner-only write to their folder).

## Never
The service key in the app, a password table of your own, a role read from AsyncStorage
instead of the profiles table, or a screen that assumes the session exists without the guard.
