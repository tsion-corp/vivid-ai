# Recipe: restaurant (ordering app for one restaurant, cafe, bakery or small chain)

Tabs: Menu (the home), Orders, Rewards (only if the spec has loyalty), Profile. Stack:
item detail, checkout, order tracking. Sheets: item options, cart, pickup or delivery.
Owner area in app/(admin): live orders board, menu availability, opening hours.

Menu: header with the restaurant name, open status computed from hours ("Open · closes
10pm" or "Opens 8am tomorrow"), a pickup or delivery switch with the address or branch;
a sticky row of section chips that scrolls the SectionList to Starters, Mains, Grills,
Drinks, Desserts; rows with name, one-line description, price, tags (spicy, vegan),
thumbnail on the right, and a round + button that adds straight away or opens the options
sheet for items with choices.

Item: large photo, name, description, required choices (size, protein) as radio rows,
optional extras as checkbox rows with prices, a note field, a quantity stepper, a
pinned "Add 2 · ₦9,000".

Cart and checkout: a floating "View cart · 3 items · ₦21,500" bar above the tab bar
whenever the cart has items; the cart sheet with lines and steppers; checkout with
pickup time slots within opening hours or delivery zone and fee, phone, payment choice,
Place order.

Order tracking: a status timeline (Received, Preparing, Ready or On the way, Done) with
the estimated time, the order lines, the branch's phone and WhatsApp; Orders tab lists
current first, past below with "Order again".

Owner: a board of live orders by status (segmented: New · Preparing · Ready), each with
lines, time and one button to move it on with a haptic; menu items with an available
toggle; hours.

Data: sections, items (name, description, price, tags, options, photo, available), orders
(lines with options, type, slot, zone, status, timeline), hours, zones.

Minimums for a first build: 5 sections with 20 to 30 items, at least 10 item photos in one
style, options sheet working, cart bar, checkout to tracking, Orders with Order again,
owner board moving orders through their states.

Signature: A floating glass tab bar; dish cards that press with a spring; the order tracker's steps filling one by one with springs and a success haptic when it is ready.
