"""Shared pickup settings and checkout invariants."""
from urllib.parse import urlparse


class PickupUnavailable(ValueError):
    """Pickup is disabled or has incomplete public instructions."""


def validate_settings(settings: dict) -> str | None:
    """Return the first invalid field, or None when settings are usable."""
    if not settings.get("enabled"):
        return None
    for field in ("address", "map_url"):
        if not str(settings.get(field) or "").strip():
            return field
    parsed = urlparse(str(settings.get("map_url") or "").strip())
    if parsed.scheme != "https" or not parsed.netloc:
        return "map_url"
    return None


def public_config(settings: dict | None) -> dict:
    """Expose complete customer instructions only when they are valid."""
    values = settings or {}
    enabled = bool(values.get("enabled")) and validate_settings(values) is None
    return {
        "enabled": enabled,
        "address": str(values.get("address") or "") if enabled else "",
        "map_url": str(values.get("map_url") or "") if enabled else "",
        "fee": 0,
    }


def checkout_values(body: dict, settings: dict | None) -> dict:
    """Derive collection details on the server; ignore client address/fee/pin."""
    if body.get("delivery_method") != "pickup":
        return {"address": body.get("address"), "latitude": body.get("latitude"),
                "longitude": body.get("longitude"), "fee": None,
                "pickup_map_url": None}
    config = public_config(settings)
    if not config["enabled"]:
        raise PickupUnavailable("pickup is not available")
    return {"address": config["address"], "latitude": None, "longitude": None,
            "fee": 0, "pickup_map_url": config["map_url"]}
