# Recipe: directory (find places or people nearby: restaurants, artisans, properties, pharmacies)

Tabs: Explore, Map (when locations matter), Saved, Profile. Stack: listing detail,
reviews, owner's listing editor. Sheets: filters, write a review.

Explore: location line ("Near Yaba · change", with Use my location through expo-location
and a manual area list), search field, category chips with icons, sort (Nearest, Top
rated, Open now), and listing cards (photo aspect-[4/3], name, category, rating with
count, distance, price level, an Open now pill).

Map: react-native-maps with markers for the filtered listings and a horizontal card rail
at the bottom synced to the selected marker; on the web preview a list stands in for the
map.

Listing detail: photo carousel, name, category, rating, open status and hours (expanded
by day), address with Directions, Call and WhatsApp buttons, price range, amenities as
chips, about, reviews with a rating breakdown and Write a review.

Saved: saved listings with notes; recently viewed.

Owners can claim a listing and edit its details, photos and hours (admin group or owner
role).

Data: categories, listings (name, category, photos, coords, area, address, phone, hours,
price level, amenities, about), reviews (listing, author, rating, text, date), saved.

Minimums for a first build: 8 categories, 30 listings across 6 Lagos or Abuja areas with
real-looking addresses and coordinates and generated photos, distance sorting from the
user's location, working filters, reviews with averages, saved listings.
