"""The Expo connector: the user's own Expo access token, so the mobile apps
the builder makes are built on their EAS account (their build quota, their
signing credentials) instead of Vivid's, which is billed per build.

The user makes the token at expo.dev (Account settings, Access tokens). It
never enters a project's sandbox; builds run in a throwaway one
(app/builder/app_build.py). Verified by asking Expo who it belongs to.
"""
from app.builder import expo


async def verify(token: str, config: dict | None = None) -> dict:
    token = (token or "").strip()
    if len(token) < 20:
        raise ValueError("paste an Expo access token (expo.dev, Account settings, Access tokens)")
    try:
        me = await expo.whoami(token)
    except expo.ExpoError as e:
        raise ValueError(str(e))
    accounts = me["accounts"] or [me["username"]]
    return {"login": me["username"], "mode": "authenticated",
            "config": {"username": me["username"], "accounts": accounts,
                       # Builds go to the personal account unless the user picks another.
                       "owner": me["username"] if me["username"] in accounts else accounts[0]}}


def build_tools(connector) -> dict:
    return {}
