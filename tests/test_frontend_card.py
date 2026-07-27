"""Tests for registration of the bundled Narwal Lovelace control card."""

# ruff: noqa: E402

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import tests.ha_stubs

tests.ha_stubs.install()

from custom_components.narwal.frontend_card import (
    CARD_PATH,
    CARD_URL,
    DATA_FRONTEND_CARD_REGISTERED,
    async_register_frontend_card,
)


async def test_frontend_card_registers_static_module_once() -> None:
    """The card asset is available to the frontend once per HA process."""
    register_static_paths = AsyncMock()
    hass = SimpleNamespace(
        data={},
        http=SimpleNamespace(async_register_static_paths=register_static_paths),
    )

    with patch("custom_components.narwal.frontend_card.add_extra_js_url") as add_extra_js_url:
        await async_register_frontend_card(hass)
        await async_register_frontend_card(hass)

    register_static_paths.assert_awaited_once()
    static_path = register_static_paths.await_args.args[0][0]
    assert static_path.url_path == CARD_URL
    assert static_path.path == str(CARD_PATH)
    assert static_path.cache_headers is False
    add_extra_js_url.assert_called_once_with(hass, CARD_URL)
    assert hass.data[DATA_FRONTEND_CARD_REGISTERED] is True


async def test_frontend_card_can_retry_after_static_registration_failure() -> None:
    """Do not record registration until the static path is actually ready."""
    register_static_paths = AsyncMock(side_effect=RuntimeError("temporary failure"))
    hass = SimpleNamespace(
        data={},
        http=SimpleNamespace(async_register_static_paths=register_static_paths),
    )

    with patch("custom_components.narwal.frontend_card.add_extra_js_url"):
        try:
            await async_register_frontend_card(hass)
        except RuntimeError as err:
            assert str(err) == "temporary failure"
        else:
            raise AssertionError("static registration failure should propagate")

    assert DATA_FRONTEND_CARD_REGISTERED not in hass.data
