"""Expose the bundled Narwal Lovelace control card to Home Assistant."""

from __future__ import annotations

from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

from .const import DOMAIN

CARD_URL = f"/{DOMAIN}/narwal-control-card.js"
CARD_PATH = Path(__file__).parent / "frontend" / "narwal-control-card.js"
DATA_FRONTEND_CARD_REGISTERED = f"{DOMAIN}_frontend_card_registered"


async def async_register_frontend_card(hass: HomeAssistant) -> None:
    """Register the bundled Lovelace card exactly once per HA process.

    The static path deliberately disables cache headers so an updated custom
    integration cannot leave a browser using an older control surface after a
    Home Assistant restart.
    """
    if hass.data.get(DATA_FRONTEND_CARD_REGISTERED):
        return

    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                url_path=CARD_URL,
                path=str(CARD_PATH),
                cache_headers=False,
            )
        ]
    )
    add_extra_js_url(hass, CARD_URL)
    hass.data[DATA_FRONTEND_CARD_REGISTERED] = True
