# Recipe: wallet (personal finance: budgets, expenses, savings goals, a cooperative's member app)

This is a money tracker unless the spec says otherwise: it records money, it does not
move it. Never pretend to send real money; a transfer screen in a demo says it is a
demo.

Tabs: Home, Activity, Budgets (or Savings), Profile. Stack: transaction detail, add
transaction, goal detail. Sheets: add expense, category picker, filters.

Home: balance card (total across accounts, tap to hide with a haptic, tabular numbers),
quick actions as a row of round icon buttons (Add expense, Add income, Transfer between
accounts, Goals), this month's spending vs budget as a progress bar, a spending by
category donut (react-native-svg), the latest five transactions.

Activity: SectionList grouped by day ("Today", "Yesterday", "Mon 12 Aug") with category
icon, merchant, note, amount (red for spend, green for income), search and filters
(category, account, date range) in a sheet; swipe to delete with undo.

Add transaction: a big amount field with a number pad feel (`keyboardType="decimal-pad"`),
category chips with icons, account, date, note, optional receipt photo (image picker).

Budgets: a card per category with spent of limit and a bar that turns amber at 80% and red
over; savings goals with a ring, target date and "₦5,000 a week gets you there".

Security: an optional PIN lock on open (expo-secure-store), with Face ID or fingerprint
through expo-local-authentication where the device offers it (Expo Go on iPhones falls
back to the passcode; a real build gets Face ID). Hiding the balance in the app switcher
is out of scope unless asked.

Data: accounts (name, type, balance), categories (name, icon, colour, budget),
transactions (amount, type, category, account, date, note, receipt), goals (name, target,
saved, date).

Minimums for a first build: 3 accounts, 12 categories with icons, 60 seeded transactions
over two months so charts are real, working add and delete, budgets with thresholds,
2 savings goals, amounts formatted in naira with tabular numbers.
