"""Capability and live-state gates for schedule enabled-state control."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import tests.ha_stubs

tests.ha_stubs.install()

from custom_components.narwal.coordinator import NarwalCoordinator  # noqa: E402
from custom_components.narwal.narwal_client import (  # noqa: E402
    Capability,
    GetCleanSchedulesResponse,
    NarwalCommandError,
)
from custom_components.narwal.narwal_client.const import WorkingStatus  # noqa: E402
from custom_components.narwal.narwal_client.models import (  # noqa: E402
    DeviceInfo,
    NarwalState,
)

_AX15_PRODUCT_KEY = "CNbforyZWI"


def _coordinator(
    *,
    product_key: str = _AX15_PRODUCT_KEY,
    schedule_capability: bool = True,
    robot_awake: bool = True,
    state_fields: dict[str, object] | None = None,
) -> NarwalCoordinator:
    robot_state = {"working_status": WorkingStatus.STANDBY}
    robot_state.update(state_fields or {})
    state = NarwalState(
        device_info=DeviceInfo(product_key=product_key),
        capabilities=(
            {int(Capability.CONFIGURABLE_CYCLE_SCHEDULE_TASK): 1}
            if schedule_capability
            else {}
        ),
        **robot_state,
    )
    client = SimpleNamespace(
        state=state,
        topic_prefix=f"/{product_key}",
        robot_awake=robot_awake,
        wake=AsyncMock(return_value=True),
        get_status=AsyncMock(),
        set_clean_schedule_enabled=AsyncMock(
            return_value=GetCleanSchedulesResponse()
        ),
    )
    coordinator = NarwalCoordinator.__new__(NarwalCoordinator)
    coordinator.client = client
    coordinator.action_lock = asyncio.Lock()
    coordinator.async_set_updated_data = MagicMock()
    return coordinator


@pytest.mark.parametrize(
    ("product_key", "schedule_capability"),
    [
        ("QxMSPG6VSO", True),
        (_AX15_PRODUCT_KEY, False),
    ],
)
async def test_schedule_toggle_rejects_unsupported_profiles(
    product_key: str,
    schedule_capability: bool,
) -> None:
    coordinator = _coordinator(
        product_key=product_key,
        schedule_capability=schedule_capability,
        robot_awake=False,
    )

    with pytest.raises(NarwalCommandError, match="not available"):
        await coordinator.async_set_schedule_enabled(42, False)

    coordinator.client.wake.assert_not_awaited()
    coordinator.client.get_status.assert_not_awaited()


@pytest.mark.parametrize(
    "state_fields",
    [
        {"working_status": WorkingStatus.CLEANING},
        {"working_status": WorkingStatus.CLEANING, "is_paused": True},
        {
            "working_status": WorkingStatus.CLEANING,
            "is_returning_to_dock": True,
            "dock_sub_state": 2,
        },
        {"station_activity": 1},
    ],
)
async def test_schedule_toggle_rejects_active_tasks(
    state_fields: dict[str, object],
) -> None:
    coordinator = _coordinator(state_fields=state_fields)

    with pytest.raises(NarwalCommandError, match="blocked during"):
        await coordinator.async_set_schedule_enabled(42, False)

    coordinator.client.set_clean_schedule_enabled.assert_not_awaited()


async def test_schedule_toggle_wakes_refreshes_and_updates_coordinator() -> None:
    coordinator = _coordinator(robot_awake=False)
    expected = GetCleanSchedulesResponse()
    coordinator.client.set_clean_schedule_enabled.return_value = expected

    result = await coordinator.async_set_schedule_enabled(42, False)

    assert result is expected
    coordinator.client.wake.assert_awaited_once_with(timeout=10.0)
    coordinator.client.get_status.assert_awaited_once_with(full_update=True)
    coordinator.client.set_clean_schedule_enabled.assert_awaited_once_with(
        42,
        False,
    )
    coordinator.async_set_updated_data.assert_called_once_with(
        coordinator.client.state
    )


async def test_schedule_toggle_allows_a_stale_pause_overlay_after_docking() -> None:
    coordinator = _coordinator(
        state_fields={
            "working_status": WorkingStatus.CLEANING,
            "is_paused": True,
            "dock_sub_state": 1,
        }
    )

    await coordinator.async_set_schedule_enabled(42, False)

    coordinator.client.set_clean_schedule_enabled.assert_awaited_once_with(
        42,
        False,
    )
