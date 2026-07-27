"""Station maintenance buttons fail closed around dock activity."""

# ruff: noqa: E402

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import tests.ha_stubs

tests.ha_stubs.install()

from homeassistant.exceptions import HomeAssistantError

from custom_components.narwal.button import (
    BUTTON_DESCRIPTIONS,
    NarwalActionButton,
)
from custom_components.narwal.narwal_client import CommandResult


def _entity(*, docked: bool, station_active: bool):
    state = SimpleNamespace(
        is_docked=docked,
        is_station_active=station_active,
        capabilities={},
        firmware_version="v01.03.10.03",
    )
    client = SimpleNamespace(
        robot_awake=True,
        state=state,
        get_status=AsyncMock(),
        empty_dustbin=AsyncMock(
            return_value=SimpleNamespace(
                result_known=True,
                result_code=CommandResult.SUCCESS,
                success=True,
            )
        ),
    )
    coordinator = SimpleNamespace(
        client=client,
        data=state,
        last_update_success=True,
        action_lock=asyncio.Lock(),
        config_entry=SimpleNamespace(
            data={"device_id": "ax15-id"},
            title="Freo X10 Pro",
        ),
        device_profile=SimpleNamespace(
            display_model="Narwal Freo X10 Pro",
            hardware_model="AX15",
            station_actions=frozenset({"empty_dustbin"}),
        ),
        async_set_updated_data=MagicMock(),
    )
    description = next(
        item for item in BUTTON_DESCRIPTIONS if item.key == "empty_dustbin"
    )
    return NarwalActionButton(coordinator, description), client


def test_station_button_is_unavailable_during_active_station_task() -> None:
    entity, _ = _entity(docked=True, station_active=True)

    assert not entity.available


def test_station_button_refreshes_and_rejects_active_station_task() -> None:
    entity, client = _entity(docked=True, station_active=True)

    with pytest.raises(HomeAssistantError, match="current station task"):
        asyncio.run(entity.async_press())

    client.get_status.assert_awaited_once_with(full_update=True)
    client.empty_dustbin.assert_not_awaited()


def test_station_button_refreshes_before_safe_command() -> None:
    entity, client = _entity(docked=True, station_active=False)

    asyncio.run(entity.async_press())

    client.get_status.assert_awaited_once_with(full_update=True)
    client.empty_dustbin.assert_awaited_once_with()


def test_station_button_rejects_owned_point_navigation_after_refresh() -> None:
    entity, client = _entity(docked=True, station_active=False)
    client.point_navigation_active = True

    with pytest.raises(HomeAssistantError, match="Point navigation is already active"):
        asyncio.run(entity.async_press())

    client.get_status.assert_awaited_once_with(full_update=True)
    client.empty_dustbin.assert_not_awaited()


def test_concurrent_station_button_press_fails_instead_of_queueing() -> None:
    async def exercise() -> None:
        entity, client = _entity(docked=True, station_active=False)
        refresh_started = asyncio.Event()
        release_refresh = asyncio.Event()

        async def blocked_refresh(*, full_update: bool) -> None:
            assert full_update
            refresh_started.set()
            await release_refresh.wait()

        client.get_status.side_effect = blocked_refresh
        first_press = asyncio.create_task(entity.async_press())
        await refresh_started.wait()

        with pytest.raises(HomeAssistantError, match="already being started"):
            await entity.async_press()

        client.empty_dustbin.assert_not_awaited()
        release_refresh.set()
        await first_press
        client.empty_dustbin.assert_awaited_once_with()

    asyncio.run(exercise())


def test_station_action_fails_while_a_nonstation_action_owns_shared_lock() -> None:
    async def exercise() -> None:
        entity, client = _entity(docked=True, station_active=False)

        async with entity.coordinator.action_lock:
            with pytest.raises(HomeAssistantError, match="Another Narwal action"):
                await entity.async_press()

        client.get_status.assert_not_awaited()
        client.empty_dustbin.assert_not_awaited()

    asyncio.run(exercise())
