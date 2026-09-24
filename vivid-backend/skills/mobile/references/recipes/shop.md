# Recipe: shop (a store's own shopping app: fashion, sneakers, beauty, gadgets, groceries)

Tabs: Home, Shop (browse and search), Cart (with a count badge), Profile. Stack: product
detail, checkout, order detail. Sheets: filters, size and colour options. Owner area in
app/(admin): orders, products, stock.

Home: greeting and delivery area ("Delivering to Lekki · change"), a search field that
opens the Shop tab focused, a promo card (one offer, one image, one button), a horizontal
rail of categories as round image chips, "New in" and "Best sellers" rails of product
cards (image aspect-[4/5], name, price, a heart), and recently viewed.

Shop: search field, category chips, a sort and filter button opening a sheet (price
range, size, colour, in stock), a two-column grid of product cards with pull to refresh
and an empty state for no results ("No sneakers under ₦20,000. Clear the price filter").

Product: full-bleed image carousel (paged horizontal FlatList with dots) under a
transparent header with back, share and favourite; name, price, rating line, a size
selector (chips, disabled when out of stock), colour swatches, quantity stepper,
description, delivery estimate for the user's area, "You may also like" rail; a pinned
bottom bar "Add to cart · ₦48,000" with a haptic and the cart badge bump.

Cart: lines with thumbnail, name, options, quantity stepper, swipe to remove; subtotal,
delivery fee by area, total; a pinned Checkout button. Empty: "Your cart is empty" with a
Start shopping button.

Checkout: delivery or pickup, address and area (fee updates), phone, a note, payment
(pay on delivery or a Paystack web checkout in expo-web-browser as the spec says),
order summary, Place order; success screen with the order number, what happens next and
a WhatsApp link to the store.

Orders (in Profile, or a tab when the spec centres on repeat orders): status pills
(Pending, Confirmed, Out for delivery, Delivered) and a detail with a status timeline.

Data: categories, products (name, price, compare_at price, images, sizes, colours, stock,
category, description, rating), cart, orders (lines, delivery, fee, status, timeline),
favourites, delivery areas with fees.

Minimums for a first build: 6 categories, 16 to 24 products with generated photos in one
consistent style, working cart with quantities and options, checkout to the success
screen, orders list, favourites, owner area with orders and stock toggles.
