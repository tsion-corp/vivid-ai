# Recipe: fitness (habits, workouts, health goals, a gym's member app)

Tabs: Today, Plans (or Workouts), Progress, Profile. Stack: workout detail, active
workout, exercise detail, habit editor. Sheets: log an entry, add a habit.

Today: a greeting with the date, a progress ring for today's goal (animated to its
value), the day's habits as checkable rows (tap to complete with a spring check and a
success haptic, streak count on each), today's workout card with duration, level and a
Start button, water or steps counters with + buttons.

Workout detail: hero image, duration, level, equipment, the list of exercises with sets,
reps or time, and Start. Active workout: one exercise at a time, big timer or rep count,
rest countdown between sets with a haptic at the end, Next, Pause and End with a summary.

Progress: weekly and monthly charts drawn with react-native-svg (bars for workouts per
week, a line for weight), streak calendar (a month grid with done days filled), personal
records, and a history list.

Habits: create with a name, icon, colour, days of the week and a reminder time (a local
notification through lib/notify.ts); edit and archive with swipe actions.

Data: habits (name, icon, colour, schedule, reminder), entries (habit, date, done),
workouts (name, level, duration, exercises), exercises (name, sets, reps or seconds,
rest, how-to), sessions (workout, date, duration, completed), measurements.

Minimums for a first build: 6 seeded habits with two weeks of history so charts and streaks
look alive, 8 workouts with 5 to 8 exercises each and generated photos, working active
workout with timers, charts on Progress, reminders scheduled.

Signature: A progress ring that fills with a spring for today's goal, a success check with a haptic when a workout or habit is completed, and a streak count that bumps.
