"""Capability and live-state gates for coordinator config writes."""

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
    ConfigSnapshot,
    NarwalCommandError,
    SetConfigField,
    SetConfigPatch,
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
    upload_configuration: bool = True,
    robot_awake: bool = True,
    state_fields: dict[str, object] | None = None,
) -> NarwalCoordinator:
    robot_state = {"working_status": WorkingStatus.STANDBY}
    robot_state.update(state_fields or {})
    state = NarwalState(
        device_info=DeviceInfo(
            product_key=product_key,
            firmware_version="v99.99.99.99",
        ),
        capabilities={
            int(Capability.UPLOAD_CONFIGURATION): 1
        }
        if upload_configuration
        else {},
        **robot_state,
    )
    client = SimpleNamespace(
        state=state,
        topic_prefix=f"/{product_key}",
        robot_awake=robot_awake,
        wake=AsyncMock(return_value=True),
        get_status=AsyncMock(),
        set_config_patch=AsyncMock(),
    )
    coordinator = NarwalCoordinator.__new__(NarwalCoordinator)
    coordinator.client = client
    coordinator.action_lock = asyncio.Lock()
    coordinator.async_set_updated_data = MagicMock()
    return coordinator


@pytest.mark.parametrize(
    ("product_key", "upload_configuration"),
    [
        ("QxMSPG6VSO", True),
        (_AX15_PRODUCT_KEY, False),
    ],
)
async def test_config_write_rejects_unsupported_profile_before_wake(
    product_key: str,
    upload_configuration: bool,
) -> None:
    coordinator = _coordinator(
        product_key=product_key,
        upload_configuration=upload_configuration,
        robot_awake=False,
    )

    with pytest.raises(
        NarwalCommandError,
        match="AX15.*UPLOAD_CONFIGURATION",
    ):
        await coordinator.async_set_config(
            SetConfigField.CHILD_LOCK_ENABLED,
            True,
        )

    coordinator.client.wake.assert_not_awaited()
    coordinator.client.get_status.assert_not_awaited()
    coordinator.client.set_config_patch.assert_not_awaited()


@pytest.mark.parametrize(
    "state_fields",
    [
        {"working_status": WorkingStatus.CLEANING},
        {
            "working_status": WorkingStatus.CLEANING,
            "is_paused": True,
        },
        {
            "working_status": WorkingStatus.CLEANING,
            "is_returning_to_dock": True,
            "dock_sub_state": 2,
        },
        {"station_activity": 1},
    ],
)
async def test_config_write_rejects_active_robot_tasks_after_status_refresh(
    state_fields: dict[str, object],
) -> None:
    coordinator = _coordinator(state_fields=state_fields)

    with pytest.raises(NarwalCommandError, match="blocked during"):
        await coordinator.async_set_config(
            SetConfigField.CHILD_LOCK_ENABLED,
            True,
        )

    coordinator.client.get_status.assert_awaited_once_with(
        full_update=True
    )
    coordinator.client.set_config_patch.assert_not_awaited()


async def test_config_write_fails_when_robot_cannot_be_woken() -> None:
    coordinator = _coordinator(robot_awake=False)
    coordinator.client.wake.return_value = False

    with pytest.raises(NarwalCommandError, match="Could not wake"):
        await coordinator.async_set_config(
            SetConfigField.CHILD_LOCK_ENABLED,
            True,
        )

    coordinator.client.wake.assert_awaited_once_with(timeout=10.0)
    coordinator.client.get_status.assert_not_awaited()
    coordinator.client.set_config_patch.assert_not_awaited()


async def test_config_write_allows_a_stale_pause_overlay_after_docking() -> None:
    coordinator = _coordinator(
        state_fields={
            "working_status": WorkingStatus.CLEANING,
            "is_paused": True,
            "dock_sub_state": 1,
        }
    )

    await coordinator.async_set_config(
        SetConfigField.CHILD_LOCK_ENABLED,
        True,
    )

    coordinator.client.set_config_patch.assert_awaited_once()


async def test_config_write_success_wakes_refreshes_and_updates_coordinator() -> None:
    coordinator = _coordinator(robot_awake=False)
    snapshot = ConfigSnapshot(
        values={SetConfigField.CHILD_LOCK_ENABLED: True},
        raw_fields={7: 1},
    )
    coordinator.client.set_config_patch.return_value = snapshot

    result = await coordinator.async_set_config(
        SetConfigField.CHILD_LOCK_ENABLED,
        True,
    )

    assert result is snapshot
    coordinator.client.wake.assert_awaited_once_with(timeout=10.0)
    coordinator.client.get_status.assert_awaited_once_with(
        full_update=True
    )
    coordinator.client.set_config_patch.assert_awaited_once_with(
        SetConfigPatch(
            SetConfigField.CHILD_LOCK_ENABLED,
            True,
        )
    )
    coordinator.async_set_updated_data.assert_called_once_with(
        coordinator.client.state
    )
