"""Connector providers: per-user integrations that become per-user tools.

Each provider module exposes:
  verify(token, config) -> dict   raises on bad credentials; returns account
                                  info incl. the config to store
  build_tools(connector) -> dict[str, tools.Tool]   credential-bound tools

The pipeline loads a user's connectors each turn and merges their tools into
the planner's roster — a connector is invisible to every other user.
"""
from app.services.connectors import expo, github, google_maps, paystack, supabase

PROVIDERS = {"expo": expo, "github": github, "google_maps": google_maps, "paystack": paystack,
             "supabase": supabase}


def tools_for(connectors) -> dict:
    out = {}
    for c in connectors:
        provider = PROVIDERS.get(c.provider)
        if provider is not None:
            try:
                out.update(provider.build_tools(c))
            except Exception:
                continue
    return out
