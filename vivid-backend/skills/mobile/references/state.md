# App state and data on the phone

Without a backend, the app's data lives on the phone in AsyncStorage and is seeded on
first launch, so the app is full and useful the moment it opens. The data layer lives in
lib/ behind a small API, so linking Supabase later swaps the implementation, not the screens.

## Shape
- lib/types.ts: the types (Product, Order, Booking…), matching the spec's Data model.
- lib/seed.ts: the seed data, at least eight realistic items per list, with names, prices
  in naira, descriptions, categories, and an image each (required files under assets/).
- lib/store.tsx: a context with a reducer, persisted to AsyncStorage, that exposes the
  data, derived values and actions. Screens call actions; they never touch AsyncStorage.
- lib/format.ts: money, dates, phone numbers.

## The store
```tsx
// lib/store.tsx
import AsyncStorage from "@react-native-async-storage/async-storage";
import { createContext, useContext, useEffect, useMemo, useReducer, useState } from "react";
import { seed } from "./seed";
import type { CartLine, Order, Product } from "./types";

const KEY = "app-state-v1";   // bump the version when the shape changes

type State = { products: Product[]; cart: CartLine[]; orders: Order[]; favourites: string[] };
type Action =
  | { type: "load"; state: State }
  | { type: "add"; productId: string; qty?: number }
  | { type: "setQty"; productId: string; qty: number }
  | { type: "placeOrder"; order: Order }
  | { type: "toggleFavourite"; productId: string };

function reducer(state: State, a: Action): State {
  switch (a.type) {
    case "load": return a.state;
    case "add": {
      const line = state.cart.find((l) => l.productId === a.productId);
      const cart = line
        ? state.cart.map((l) => l.productId === a.productId ? { ...l, qty: l.qty + (a.qty ?? 1) } : l)
        : [...state.cart, { productId: a.productId, qty: a.qty ?? 1 }];
      return { ...state, cart };
    }
    case "setQty":
      return { ...state, cart: state.cart.flatMap((l) =>
        l.productId !== a.productId ? [l] : a.qty > 0 ? [{ ...l, qty: a.qty }] : []) };
    case "placeOrder": return { ...state, cart: [], orders: [a.order, ...state.orders] };
    case "toggleFavourite": {
      const has = state.favourites.includes(a.productId);
      return { ...state, favourites: has ? state.favourites.filter((f) => f !== a.productId)
                                          : [...state.favourites, a.productId] };
    }
  }
}

const Ctx = createContext<ReturnType<typeof useProvideStore> | null>(null);

function useProvideStore() {
  const [state, dispatch] = useReducer(reducer, seed);
  const [ready, setReady] = useState(false);
  useEffect(() => {
    AsyncStorage.getItem(KEY)
      .then((raw) => { if (raw) dispatch({ type: "load", state: { ...seed, ...JSON.parse(raw) } }); })
      .catch(() => {})
      .finally(() => setReady(true));
  }, []);
  useEffect(() => {
    if (ready) AsyncStorage.setItem(KEY, JSON.stringify(state)).catch(() => {});
  }, [state, ready]);

  const cartTotal = useMemo(() => state.cart.reduce((sum, l) =>
    sum + (state.products.find((p) => p.id === l.productId)?.price ?? 0) * l.qty, 0), [state]);
  return { ...state, ready, cartTotal, dispatch };
}

export function StoreProvider({ children }: { children: React.ReactNode }) {
  const value = useProvideStore();
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useStore() {
  const v = useContext(Ctx);
  if (!v) throw new Error("useStore outside StoreProvider");
  return v;
}
```
Seeded catalogue data (products, menu, services) should come from lib/seed.ts on every
launch, not only the first, so edits to the seed show up: persist only what the user
changes (cart, orders, favourites, their own records) and merge.

## Server data (with a backend)
- Wrap reads in a hook per resource (`useProducts()`, `useOrders()`) that returns
  `{ data, loading, error, refresh }`; screens render skeleton, error with Retry, empty,
  or the list from those four values.
- Mutations are optimistic: update the local list first, call the server, roll back and
  show the error on failure.
- Refresh on pull, on focus of the screen (`useFocusEffect` from expo-router) for lists
  that change elsewhere, and on realtime events where the spec needs live updates
  (orders for an owner).
- @tanstack/react-query is fine (pure JS) when the app has many server lists; a small app
  does not need it.

## Offline
```tsx
import { useNetInfo } from "@react-native-community/netinfo";
const { isConnected } = useNetInfo();
{isConnected === false && <Banner tone="warning" text="You're offline. Showing saved data." />}
```
Apps with server data cache the last good response in AsyncStorage and show it offline;
actions that need the server are disabled with a reason while offline.

## Forms
Keep form state local (`useState` per field or one object), validate on submit and on
blur after the first submit, show the error under the field, disable the submit button
only while submitting (never because the form is incomplete: tapping it shows what is
missing). Phone numbers: accept 0803..., +234..., and spaces; store as +234....
