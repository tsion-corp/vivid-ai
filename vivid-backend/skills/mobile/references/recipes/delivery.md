# Recipe: delivery (send packages or errands: customer, rider and dispatcher roles)

This is a platform with three roles; it is full-stack by nature. Customers send, riders
deliver, a dispatcher or owner assigns and watches. One app, the role decides the tabs
(the root layout routes to (customer), (rider) or (admin) groups after sign-in).

Customer tabs: Send, Deliveries, Profile. Send flow: pickup and drop-off addresses (with
areas and a map preview on phones), package size chips (Small, Medium, Large with
examples), a note for the rider, the price computed from the areas and size, payment
choice, Book. Tracking: status timeline (Requested, Assigned, Picked up, On the way,
Delivered), the rider's name, photo, phone and WhatsApp once assigned, a proof-of-delivery
photo at the end, and Rate the rider.

Rider tabs: Jobs, Earnings, Profile. Jobs: available jobs near them (area, distance,
price, size) with Accept; the active job with the next step as one big button (Arrived at
pickup, Picked up, Delivered with a photo); an online and offline switch in the header.
Earnings: today, this week, a list of completed jobs.

Dispatcher (admin): a live board of jobs by status, assign a rider from a list of online
riders, riders list with online status and today's jobs.

Data: profiles (role: customer, rider, admin), deliveries (customer, rider, pickup,
dropoff, areas, size, price, status, timeline, proof photo, rating), areas with prices,
rider status.

Minimums for a first build: price table for at least 10 Lagos areas, 12 seeded deliveries
across every status, the full customer flow to tracking, rider flow through every step
with haptics, dispatcher assigning, status changes through one lifecycle SQL function,
realtime updates on tracking and the board.

Signature: A live tracker card whose progress line and step dots fill with springs as the status changes; the ETA counts down in tabular numbers; a success check on delivery.
