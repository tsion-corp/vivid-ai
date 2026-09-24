# Recipe: booking (appointments with a salon, barber, clinic, tutor, studio, mechanic)

Tabs: Home, Book, Appointments, Profile. Stack: service detail, staff detail, booking
flow steps, appointment detail. Owner area in app/(admin): today's schedule, all bookings,
services, availability.

Home: the business name and a short promise, the next appointment card if there is one
(date, time, service, staff, Directions, Reschedule), popular services as cards with
duration and price, the team as a rail of avatars, reviews, the address with an Open in
Maps link and hours.

Book flow (a stack of small screens with "Step 1 of 4" in the header): choose a service
(grouped list with duration and price), choose a professional or "Anyone", choose a day
(a horizontal strip of the next 14 days with weekday and date, unavailable days dimmed)
and a time (chips of free slots computed from hours, duration and existing bookings),
then details (name, phone, note) and confirm with the summary and price. Success screen
with Add to calendar (expo-calendar) and a reminder (expo-notifications, an hour before).

Appointments: Upcoming and Past as a segmented control; each card with status pill;
detail with Reschedule (back into the flow with the service kept) and Cancel with a
confirmation and the cancellation rule.

Owner: today's schedule as a timeline by staff member, tap a booking to mark arrived,
done or no-show; availability per weekday; services editor.

Data: services (name, category, duration, price, description), staff (name, photo,
services, working hours), bookings (service, staff, start, end, customer, phone, status,
note), business hours, blocked dates.

Minimums for a first build: 10 to 14 services in 3 to 4 categories, 4 staff with generated
portraits (Black Nigerian professionals), real slot computation with no double bookings,
the full flow to the success screen, reminders scheduled, owner schedule working.
