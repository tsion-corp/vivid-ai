"""Subscription plans for the app builder: Free, Pro and Team, with token
allowances per rolling window and per month, paid from the wallet.

catalog.py defines the plans (all numbers from settings); usage.py sums
what a user or team has used; gate.py decides whether a turn or a new
project may start and settles a turn's overage against extra tokens;
subscriptions.py subscribes, renews and cancels.
"""
