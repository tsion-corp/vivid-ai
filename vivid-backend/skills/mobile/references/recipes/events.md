# Recipe: events (tickets and schedules for a festival, conference, concert series or venue)

Tabs: Discover, Tickets, Schedule (for a single multi-day event) or Saved, Profile.
Stack: event detail, checkout, ticket detail. Sheets: ticket type and quantity, filters.

Discover: a featured event hero card (cover image, date, venue, price from), category
chips (Music, Comedy, Tech, Food), date filters (Today, This weekend, This month), and a
list of event cards (cover aspect-video, title, date and time, venue, price from, a
"Selling fast" pill when stock is low).

Event detail: cover under a transparent header, title, date and time with Add to calendar,
venue with Open in Maps, lineup or speakers as a rail of avatars, description, ticket types
(Regular, VIP, Table) with price and availability, a pinned "Get tickets · from ₦10,000".

Checkout: ticket types and quantities, attendee name and phone, email for the receipt,
payment (web checkout or pay at the gate), and success with the tickets.

Tickets: each ticket as a card with a large QR code (react-native-qrcode-svg:
`<QRCode value={ticket.code} size={220} />`), event, date, type and attendee; a tip to
turn the brightness up; past tickets below. The owner scans at the gate with expo-camera
(barcode scanning) and marks the ticket used.

Schedule (single event): days as a segmented control, sessions by time with stage and
speaker, save to My schedule with a star and a reminder.

Data: events (title, cover, category, starts, ends, venue, coords, description, lineup),
ticket types (event, name, price, quantity, sold), orders, tickets (code, type, attendee,
used_at), saved.

Minimums for a first build: 12 upcoming events with generated covers across 4 categories,
2 to 3 ticket types each, checkout to working QR tickets, a scanner screen for the owner
that validates and marks tickets used.

Signature: A depth carousel of featured events (cards turn away from the centre), and the ticket as a TiltCard that flips to its QR code.
