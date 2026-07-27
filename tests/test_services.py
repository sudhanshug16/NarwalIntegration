"""Tests for Narwal integration services."""

# ruff: noqa: E402

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, MagicMock, patch
from unittest.mock import call as mock_call

import pytest

import tests.ha_stubs

tests.ha_stubs.install()

import voluptuous as vol
from homeassistant.exceptions import HomeAssistantError, Unauthorized
from homeassistant.helpers import service

from custom_components.narwal import (
    FIELD_ANGULAR_VELOCITY,
    FIELD_DURATION_MS,
    FIELD_ENABLED,
    FIELD_LINEAR_VELOCITY,
    FIELD_MAP_REVISION,
    FIELD_MODE,
    FIELD_MOP_STRENGTH,
    FIELD_NORMALIZED_X,
    FIELD_NORMALIZED_Y,
    FIELD_PASSES,
    FIELD_ROOMS,
    FIELD_SCHEDULE_TASK_ID,
    FIELD_SUCTION,
    FIELD_WATER,
    _async_get_service_coordinators,
    _async_prepare_motion,
    _async_register_services,
    _async_validate_clean_rooms_targets,
    _bounded_integer,
    async_setup,
)
from custom_components.narwal.const import (
    DOMAIN,
    SERVICE_CLEAN_ROOMS,
    SERVICE_DRIVE,
    SERVICE_GO_TO,
    SERVICE_SET_SCHEDULE_ENABLED,
    SERVICE_STOP_NAVIGATION,
    SERVICE_STOP_TELECONTROL,
)
from custom_components.narwal.button import (
    BUTTON_DESCRIPTIONS,
    NarwalActionButton,
)
from custom_components.narwal.coordinator import NarwalCoordinator
from custom_components.narwal.narwal_client import CommandResult
from custom_components.narwal.narwal_client.client import NarwalClient
from custom_components.narwal.narwal_client.const import (
    TOPIC_CMD_CANCEL,
    TOPIC_CMD_POINT_NAVI,
    TOPIC_CMD_SET_MANUAL_CONTROL_MODE,
    ManualControlMode,
    TelecontrolStatus,
    WorkingStatus,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (-10, -10),
        (0, 0),
        (10, 10),
        (4.0, 4),
        (" 7 ", 7),
    ],
)
def test_bounded_integer_accepts_only_exact_integers(
    value: object,
    expected: int,
) -> None:
    assert (
        _bounded_integer(
            value,
            name="velocity",
            minimum=-10,
            maximum=10,
        )
        == expected
    )


@pytest.mark.parametrize(
    "value",
    [True, False, 1.5, float("nan"), float("inf"), "1.0", "", None],
)
def test_bounded_integer_rejects_coercion_and_non_finite_values(
    value: object,
) -> None:
    with pytest.raises(vol.Invalid, match="must be an integer"):
        _bounded_integer(
            value,
            name="velocity",
            minimum=-10,
            maximum=10,
        )


@pytest.mark.parametrize("value", [-11, 11])
def test_bounded_integer_rejects_out_of_range_values(value: int) -> None:
    with pytest.raises(vol.Invalid, match="between -10 and 10"):
        _bounded_integer(
            value,
            name="velocity",
            minimum=-10,
            maximum=10,
        )


@pytest.mark.parametrize(
    ("manual_active", "manual_state", "navigation_active", "message"),
    [
        (True, ManualControlMode.OFF, False, "Manual control is already active"),
        (False, ManualControlMode.JOYSTICK, False, "Manual control is already active"),
        (False, ManualControlMode.OFF, True, "Point navigation is already active"),
    ],
)
async def test_prepare_motion_rejects_existing_telecontrol_ownership(
    manual_active: bool,
    manual_state: ManualControlMode,
    navigation_active: bool,
    message: str,
) -> None:
    state = SimpleNamespace(
        working_status=WorkingStatus.STANDBY,
        is_cleaning=False,
        is_paused=False,
        is_paused_during_active_task=False,
        is_returning=False,
        is_station_active=False,
    )
    client = SimpleNamespace(
        robot_awake=True,
        state=state,
        get_status=AsyncMock(),
        manual_control_active=manual_active,
        manual_control_state=int(manual_state),
        point_navigation_active=navigation_active,
        telecontrol_status=int(TelecontrolStatus.UNSPECIFIED),
    )

    with pytest.raises(HomeAssistantError, match=message):
        await _async_prepare_motion(SimpleNamespace(client=client))

    client.get_status.assert_awaited_once_with(full_update=True)


async def test_prepare_motion_allows_a_docked_stale_pause_overlay() -> None:
    state = SimpleNamespace(
        working_status=WorkingStatus.CLEANING,
        is_cleaning=False,
        is_paused=True,
        is_paused_during_active_task=False,
        is_returning=False,
        is_station_active=False,
    )
    client = SimpleNamespace(
        robot_awake=True,
        state=state,
        get_status=AsyncMock(),
        manual_control_active=False,
        manual_control_state=int(ManualControlMode.OFF),
        point_navigation_active=False,
        telecontrol_status=int(TelecontrolStatus.UNSPECIFIED),
    )

    await _async_prepare_motion(SimpleNamespace(client=client))

    client.get_status.assert_awaited_once_with(full_update=True)


async def test_prepare_motion_rejects_observed_unowned_point_navigation() -> None:
    state = SimpleNamespace(
        working_status=WorkingStatus.STANDBY,
        is_cleaning=False,
        is_paused_during_active_task=False,
        is_returning=False,
        is_station_active=False,
    )
    client = SimpleNamespace(
        robot_awake=True,
        state=state,
        get_status=AsyncMock(),
        manual_control_active=False,
        manual_control_state=int(ManualControlMode.OFF),
        point_navigation_active=False,
        telecontrol_status=int(TelecontrolStatus.POINT_NAVI),
    )

    with pytest.raises(HomeAssistantError, match="Point navigation is already active"):
        await _async_prepare_motion(SimpleNamespace(client=client))


def _registered_handler(hass: MagicMock, service_name: str):
    """Return a service handler registered under ``service_name``."""
    for registered in hass.services.async_register.call_args_list:
        if registered.args[0:2] == (DOMAIN, service_name):
            return registered.args[2]
    raise AssertionError(f"Service was not registered: {service_name}")


def _physical_action_coordinator(**values: object) -> SimpleNamespace:
    """Create a service-test coordinator with the production action guard."""
    lock = asyncio.Lock()
    return SimpleNamespace(
        exclusive_action_lock=lambda _action: lock,
        action_lock=lock,
        **values,
    )


def test_clean_rooms_awaits_entity_target_extraction() -> None:
    hass = MagicMock()
    client = SimpleNamespace(
        robot_awake=True,
        state=SimpleNamespace(
            capabilities={},
            is_station_active=False,
        ),
        get_status=AsyncMock(),
        start_rooms=AsyncMock(
            return_value=SimpleNamespace(
                result_code=CommandResult.SUCCESS,
                result_known=True,
            )
        ),
    )
    coordinator = _physical_action_coordinator(
        client=client,
        async_set_updated_data=MagicMock(),
        parameterized_clean_enabled=True,
    )
    call = SimpleNamespace(
        context=SimpleNamespace(user_id=None),
        data={
            "entity_id": ["vacuum.flow_2"],
            FIELD_ROOMS: [1],
            FIELD_MODE: "vacuum",
            FIELD_SUCTION: "standard",
            FIELD_WATER: "normal",
            FIELD_MOP_STRENGTH: "normal",
            FIELD_PASSES: 1,
        },
    )

    _async_register_services(hass)
    handler = _registered_handler(hass, SERVICE_CLEAN_ROOMS)

    with (
        patch(
            "custom_components.narwal._async_get_service_coordinators",
            new=AsyncMock(return_value=[coordinator]),
        ),
        patch(
            "custom_components.narwal._async_room_ids_for_coordinator",
            new=AsyncMock(return_value=[1]),
        ),
        patch(
            "custom_components.narwal._async_validate_clean_rooms_targets",
            new=AsyncMock(return_value=["vacuum.flow_2"]),
        ),
    ):
        asyncio.run(handler(call))

    service.async_extract_entity_ids.assert_awaited_once_with(call)
    client.start_rooms.assert_awaited_once()
    assert (
        mock_call(
            DOMAIN,
            SERVICE_CLEAN_ROOMS,
            handler,
            schema=ANY,
        )
        in hass.services.async_register.call_args_list
    )


async def test_services_are_registered_during_integration_setup() -> None:
    hass = MagicMock()

    assert await async_setup(hass, {}) is True

    assert {
        registered.args[1]
        for registered in hass.services.async_register.call_args_list
    } == {
        SERVICE_CLEAN_ROOMS,
        SERVICE_DRIVE,
        SERVICE_GO_TO,
        SERVICE_SET_SCHEDULE_ENABLED,
        SERVICE_STOP_NAVIGATION,
        SERVICE_STOP_TELECONTROL,
    }


async def test_clean_rooms_requires_an_explicit_target() -> None:
    hass = MagicMock()
    hass.data = {DOMAIN: {"entry": NarwalCoordinator.__new__(NarwalCoordinator)}}

    with pytest.raises(HomeAssistantError, match="Target a Narwal vacuum"):
        await _async_get_service_coordinators(hass, [])


def test_clean_rooms_requires_a_supported_profile() -> None:
    hass = MagicMock()
    coordinator = _physical_action_coordinator(
        parameterized_clean_enabled=False,
        client=MagicMock(),
    )
    call = SimpleNamespace(
        context=SimpleNamespace(user_id=None),
        data={
            "entity_id": ["vacuum.flow_2"],
            FIELD_ROOMS: [1],
            FIELD_MODE: "vacuum",
            FIELD_SUCTION: "standard",
            FIELD_WATER: "normal",
            FIELD_MOP_STRENGTH: "normal",
            FIELD_PASSES: 1,
        },
    )

    _async_register_services(hass)
    handler = _registered_handler(hass, SERVICE_CLEAN_ROOMS)

    with (
        patch(
            "custom_components.narwal._async_get_service_coordinators",
            new=AsyncMock(return_value=[coordinator]),
        ),
        patch(
            "custom_components.narwal._async_validate_clean_rooms_targets",
            new=AsyncMock(return_value=["vacuum.flow_2"]),
        ),
        pytest.raises(HomeAssistantError, match="not available"),
    ):
        asyncio.run(handler(call))


def test_clean_rooms_rejects_unadvertised_route_override() -> None:
    hass = MagicMock()
    client = SimpleNamespace(
        robot_awake=True,
        state=SimpleNamespace(
            capabilities={},
            is_station_active=False,
        ),
        get_status=AsyncMock(),
        start_rooms=AsyncMock(),
    )
    coordinator = _physical_action_coordinator(
        client=client,
        parameterized_clean_enabled=True,
    )
    call = SimpleNamespace(
        context=SimpleNamespace(user_id=None),
        data={
            "entity_id": ["vacuum.freo_x10_pro"],
            FIELD_ROOMS: [1],
            FIELD_MODE: "vacuum",
            FIELD_SUCTION: "standard",
            FIELD_WATER: "normal",
            FIELD_MOP_STRENGTH: "normal",
            FIELD_PASSES: 1,
            "route": "meticulous",
        },
    )

    _async_register_services(hass)
    handler = _registered_handler(hass, SERVICE_CLEAN_ROOMS)

    with (
        patch(
            "custom_components.narwal._async_get_service_coordinators",
            new=AsyncMock(return_value=[coordinator]),
        ),
        patch(
            "custom_components.narwal._async_validate_clean_rooms_targets",
            new=AsyncMock(return_value=["vacuum.freo_x10_pro"]),
        ),
        pytest.raises(HomeAssistantError, match="route selection is not advertised"),
    ):
        asyncio.run(handler(call))

    client.start_rooms.assert_not_awaited()


async def test_clean_rooms_rejects_unauthorized_target() -> None:
    hass = MagicMock()
    registry = MagicMock()
    registry.async_get.return_value = SimpleNamespace(platform=DOMAIN)
    user = SimpleNamespace(
        is_admin=False,
        permissions=SimpleNamespace(check_entity=MagicMock(return_value=False)),
    )
    hass.auth.async_get_user = AsyncMock(return_value=user)
    call = SimpleNamespace(
        context=SimpleNamespace(user_id="restricted-user"),
        data={"entity_id": ["vacuum.flow_2"]},
    )

    with (
        patch("custom_components.narwal.er.async_get", return_value=registry),
        pytest.raises(Unauthorized),
    ):
        await _async_validate_clean_rooms_targets(
            hass, call, ["vacuum.flow_2"]
        )

    user.permissions.check_entity.assert_called_once_with(
        "vacuum.flow_2", "control"
    )


async def test_clean_rooms_rejects_non_vacuum_target() -> None:
    hass = MagicMock()
    registry = MagicMock()
    registry.async_get.return_value = SimpleNamespace(platform=DOMAIN)
    call = SimpleNamespace(
        context=SimpleNamespace(user_id=None),
        data={"entity_id": ["sensor.flow_2_battery"]},
    )

    with (
        patch("custom_components.narwal.er.async_get", return_value=registry),
        pytest.raises(HomeAssistantError, match="Narwal vacuum entity"),
    ):
        await _async_validate_clean_rooms_targets(
            hass, call, ["sensor.flow_2_battery"]
        )


async def test_clean_rooms_filters_indirect_non_vacuum_targets() -> None:
    hass = MagicMock()
    registry = MagicMock()
    registry.async_get.side_effect = {
        "vacuum.flow_2": SimpleNamespace(platform=DOMAIN),
        "sensor.flow_2_battery": SimpleNamespace(platform=DOMAIN),
    }.get
    call = SimpleNamespace(
        context=SimpleNamespace(user_id=None),
        data={"device_id": ["flow-2-device"]},
    )

    with patch("custom_components.narwal.er.async_get", return_value=registry):
        entity_ids = await _async_validate_clean_rooms_targets(
            hass,
            call,
            ["sensor.flow_2_battery", "vacuum.flow_2"],
        )

    assert entity_ids == ["vacuum.flow_2"]


def test_drive_sends_one_bounded_dead_man_pulse() -> None:
    hass = MagicMock()
    state = SimpleNamespace(is_docked=False)
    client = SimpleNamespace(
        state=state,
        telecontrol_stop_generation=7,
        manual_control_pulse=AsyncMock(
            return_value=SimpleNamespace(
                result_code=CommandResult.SUCCESS,
                result_known=True,
            )
        ),
    )
    coordinator = _physical_action_coordinator(
        client=client,
        async_set_updated_data=MagicMock(),
    )
    call_data = {
        "entity_id": ["vacuum.freo_x10_pro"],
        FIELD_LINEAR_VELOCITY: 4,
        FIELD_ANGULAR_VELOCITY: -2,
        FIELD_DURATION_MS: 300,
    }
    service_call = SimpleNamespace(data=call_data)

    _async_register_services(hass)
    handler = _registered_handler(hass, SERVICE_DRIVE)

    with (
        patch(
            "custom_components.narwal._async_single_telecontrol_coordinator",
            new=AsyncMock(return_value=coordinator),
        ),
        patch(
            "custom_components.narwal._async_prepare_motion",
            new=AsyncMock(),
        ),
    ):
        asyncio.run(handler(service_call))

    client.manual_control_pulse.assert_awaited_once_with(
        4,
        -2,
        duration=0.3,
        expected_generation=7,
    )
    coordinator.async_set_updated_data.assert_called_once_with(state)


def test_drive_rejects_motion_while_docked() -> None:
    hass = MagicMock()
    client = SimpleNamespace(
        state=SimpleNamespace(is_docked=True),
        telecontrol_stop_generation=0,
        manual_control_pulse=AsyncMock(),
    )
    coordinator = _physical_action_coordinator(client=client)
    service_call = SimpleNamespace(
        data={
            FIELD_LINEAR_VELOCITY: 1,
            FIELD_ANGULAR_VELOCITY: 0,
            FIELD_DURATION_MS: 250,
        }
    )

    _async_register_services(hass)
    handler = _registered_handler(hass, SERVICE_DRIVE)

    with (
        patch(
            "custom_components.narwal._async_single_telecontrol_coordinator",
            new=AsyncMock(return_value=coordinator),
        ),
        patch(
            "custom_components.narwal._async_prepare_motion",
            new=AsyncMock(),
        ),
        pytest.raises(HomeAssistantError, match="blocked while the robot is on its dock"),
    ):
        asyncio.run(handler(service_call))

    client.manual_control_pulse.assert_not_awaited()


def test_drive_stop_during_preflight_invalidates_motion() -> None:
    hass = MagicMock()
    client = NarwalClient("127.0.0.1")
    client.send_command = AsyncMock(
        return_value=SimpleNamespace(
            result_code=CommandResult.SUCCESS,
            result_known=True,
        )
    )
    client._publish_command = AsyncMock()
    coordinator = _physical_action_coordinator(
        client=client,
        async_set_updated_data=MagicMock(),
    )
    service_call = SimpleNamespace(
        data={
            FIELD_LINEAR_VELOCITY: 1,
            FIELD_ANGULAR_VELOCITY: 0,
            FIELD_DURATION_MS: 250,
        }
    )

    async def stop_during_preflight(_coordinator) -> None:
        await client.cancel_point_navigation()

    _async_register_services(hass)
    handler = _registered_handler(hass, SERVICE_DRIVE)

    with (
        patch(
            "custom_components.narwal._async_single_telecontrol_coordinator",
            new=AsyncMock(return_value=coordinator),
        ),
        patch(
            "custom_components.narwal._async_prepare_motion",
            new=AsyncMock(side_effect=stop_during_preflight),
        ),
        pytest.raises(HomeAssistantError, match="joystick pulse failed"),
    ):
        asyncio.run(handler(service_call))

    assert [one_call.args[0] for one_call in client.send_command.await_args_list] == [
        TOPIC_CMD_CANCEL
    ]
    client._publish_command.assert_not_awaited()


def test_go_to_requires_current_map_revision_and_clear_floor() -> None:
    hass = MagicMock()
    map_data = SimpleNamespace(
        width=100,
        height=80,
        navigation_revision=MagicMock(return_value="current-revision"),
        image_to_grid_cell=MagicMock(return_value=(25, 59)),
        normalized_image_to_world=MagicMock(return_value=(1025.0, 2059.0)),
        is_navigation_target_clear=MagicMock(return_value=True),
    )
    state = SimpleNamespace(map_data=map_data)
    client = SimpleNamespace(
        state=state,
        telecontrol_stop_generation=11,
        get_map=AsyncMock(),
        start_point_navigation=AsyncMock(
            return_value=SimpleNamespace(
                result_code=CommandResult.SUCCESS,
                result_known=True,
            )
        ),
    )
    coordinator = _physical_action_coordinator(
        client=client,
        async_set_updated_data=MagicMock(),
    )
    service_call = SimpleNamespace(
        data={
            FIELD_NORMALIZED_X: 0.25,
            FIELD_NORMALIZED_Y: 0.25,
            FIELD_MAP_REVISION: "current-revision",
        }
    )

    _async_register_services(hass)
    handler = _registered_handler(hass, SERVICE_GO_TO)

    with (
        patch(
            "custom_components.narwal._async_single_telecontrol_coordinator",
            new=AsyncMock(return_value=coordinator),
        ),
        patch(
            "custom_components.narwal._async_prepare_motion",
            new=AsyncMock(),
        ),
    ):
        asyncio.run(handler(service_call))

    client.get_map.assert_awaited_once_with()
    map_data.image_to_grid_cell.assert_called_once_with(25.0, 20.0)
    map_data.normalized_image_to_world.assert_called_once_with(0.25, 0.25)
    map_data.is_navigation_target_clear.assert_called_once_with(
        25,
        59,
        clearance_cells=1,
        reject_furniture=True,
    )
    client.start_point_navigation.assert_awaited_once_with(
        1025.0,
        2059.0,
        expected_generation=11,
    )


def test_point_navigation_ack_blocks_a_station_action_after_startup() -> None:
    """A completed Go to startup keeps dock actions blocked during navigation.

    The shared action lock only protects the short point-navigation startup
    transaction. This covers the essential follow-on guard: once a successful
    navigation acknowledgement releases that lock, a dock button must still
    refuse to start a station cycle until navigation is explicitly stopped.
    """
    hass = MagicMock()
    map_data = SimpleNamespace(
        width=100,
        height=80,
        navigation_revision=MagicMock(return_value="current-revision"),
        image_to_grid_cell=MagicMock(return_value=(25, 59)),
        normalized_image_to_world=MagicMock(return_value=(1025.0, 2059.0)),
        is_navigation_target_clear=MagicMock(return_value=True),
    )
    state = SimpleNamespace(
        map_data=map_data,
        is_docked=True,
        is_station_active=False,
        capabilities={},
        firmware_version="v01.03.10.03",
    )
    client = SimpleNamespace(
        state=state,
        robot_awake=True,
        telecontrol_stop_generation=11,
        manual_control_active=False,
        manual_control_state=int(ManualControlMode.OFF),
        point_navigation_active=False,
        telecontrol_status=int(TelecontrolStatus.UNSPECIFIED),
        get_map=AsyncMock(),
        get_status=AsyncMock(),
        empty_dustbin=AsyncMock(),
    )

    async def acknowledged_navigation(*_args, **_kwargs):
        client.point_navigation_active = True
        return SimpleNamespace(
            result_code=CommandResult.SUCCESS,
            result_known=True,
        )

    client.start_point_navigation = AsyncMock(side_effect=acknowledged_navigation)
    coordinator = _physical_action_coordinator(
        client=client,
        data=state,
        last_update_success=True,
        async_set_updated_data=MagicMock(),
        config_entry=SimpleNamespace(
            data={"device_id": "ax15-id"},
            title="Freo X10 Pro",
        ),
        device_profile=SimpleNamespace(
            display_model="Narwal Freo X10 Pro",
            hardware_model="AX15",
            station_actions=frozenset({"empty_dustbin"}),
        ),
    )
    service_call = SimpleNamespace(
        data={
            FIELD_NORMALIZED_X: 0.25,
            FIELD_NORMALIZED_Y: 0.25,
            FIELD_MAP_REVISION: "current-revision",
        }
    )

    _async_register_services(hass)
    go_to = _registered_handler(hass, SERVICE_GO_TO)
    with (
        patch(
            "custom_components.narwal._async_single_telecontrol_coordinator",
            new=AsyncMock(return_value=coordinator),
        ),
        patch(
            "custom_components.narwal._async_prepare_motion",
            new=AsyncMock(),
        ),
    ):
        asyncio.run(go_to(service_call))

    description = next(
        item for item in BUTTON_DESCRIPTIONS if item.key == "empty_dustbin"
    )
    station_button = NarwalActionButton(coordinator, description)
    with pytest.raises(HomeAssistantError, match="Point navigation is active"):
        asyncio.run(station_button.async_press())

    client.start_point_navigation.assert_awaited_once()
    client.get_status.assert_awaited_once_with(full_update=True)
    client.empty_dustbin.assert_not_awaited()


def test_go_to_rejects_a_stale_map_revision() -> None:
    hass = MagicMock()
    map_data = SimpleNamespace(
        navigation_revision=MagicMock(return_value="new-revision"),
    )
    client = SimpleNamespace(
        state=SimpleNamespace(map_data=map_data),
        telecontrol_stop_generation=0,
        get_map=AsyncMock(),
        start_point_navigation=AsyncMock(),
    )
    coordinator = _physical_action_coordinator(client=client)
    service_call = SimpleNamespace(
        data={
            FIELD_NORMALIZED_X: 0.5,
            FIELD_NORMALIZED_Y: 0.5,
            FIELD_MAP_REVISION: "old-revision",
        }
    )

    _async_register_services(hass)
    handler = _registered_handler(hass, SERVICE_GO_TO)

    with (
        patch(
            "custom_components.narwal._async_single_telecontrol_coordinator",
            new=AsyncMock(return_value=coordinator),
        ),
        patch(
            "custom_components.narwal._async_prepare_motion",
            new=AsyncMock(),
        ),
        pytest.raises(HomeAssistantError, match="map changed"),
    ):
        asyncio.run(handler(service_call))

    client.start_point_navigation.assert_not_awaited()


def test_go_to_stop_during_map_refresh_invalidates_navigation() -> None:
    hass = MagicMock()
    map_data = SimpleNamespace(
        width=100,
        height=80,
        navigation_revision=MagicMock(return_value="current-revision"),
        image_to_grid_cell=MagicMock(return_value=(25, 59)),
        normalized_image_to_world=MagicMock(return_value=(1025.0, 2059.0)),
        is_navigation_target_clear=MagicMock(return_value=True),
    )
    client = NarwalClient("127.0.0.1")
    client.state.map_data = map_data
    client.send_command = AsyncMock(
        return_value=SimpleNamespace(
            result_code=CommandResult.SUCCESS,
            result_known=True,
        )
    )
    client._publish_command = AsyncMock()

    async def stop_during_map_refresh():
        await client.cancel_point_navigation()
        return map_data

    client.get_map = AsyncMock(side_effect=stop_during_map_refresh)
    coordinator = _physical_action_coordinator(
        client=client,
        async_set_updated_data=MagicMock(),
    )
    service_call = SimpleNamespace(
        data={
            FIELD_NORMALIZED_X: 0.25,
            FIELD_NORMALIZED_Y: 0.25,
            FIELD_MAP_REVISION: "current-revision",
        }
    )

    _async_register_services(hass)
    handler = _registered_handler(hass, SERVICE_GO_TO)

    with (
        patch(
            "custom_components.narwal._async_single_telecontrol_coordinator",
            new=AsyncMock(return_value=coordinator),
        ),
        patch(
            "custom_components.narwal._async_prepare_motion",
            new=AsyncMock(),
        ),
        pytest.raises(HomeAssistantError, match="point navigation failed"),
    ):
        asyncio.run(handler(service_call))

    topics = [one_call.args[0] for one_call in client.send_command.await_args_list]
    assert topics == [TOPIC_CMD_CANCEL]
    assert TOPIC_CMD_POINT_NAVI not in topics
    assert TOPIC_CMD_SET_MANUAL_CONTROL_MODE not in topics
    client._publish_command.assert_not_awaited()


@pytest.mark.parametrize(
    ("service_name", "client_method"),
    [
        (SERVICE_STOP_NAVIGATION, "cancel_point_navigation"),
        (SERVICE_STOP_TELECONTROL, "emergency_stop_telecontrol"),
    ],
)
def test_telecontrol_stop_services(
    service_name: str,
    client_method: str,
) -> None:
    hass = MagicMock()
    method = AsyncMock()
    if client_method == "cancel_point_navigation":
        method.return_value = SimpleNamespace(
            result_code=CommandResult.SUCCESS,
            result_known=True,
        )
    client = SimpleNamespace(
        state=MagicMock(),
        **{client_method: method},
    )
    coordinator = SimpleNamespace(
        client=client,
        async_set_updated_data=MagicMock(),
    )

    _async_register_services(hass)
    handler = _registered_handler(hass, service_name)

    with patch(
        "custom_components.narwal._async_single_telecontrol_coordinator",
        new=AsyncMock(return_value=coordinator),
    ):
        asyncio.run(handler(SimpleNamespace(data={})))

    method.assert_awaited_once_with()
    coordinator.async_set_updated_data.assert_called_once_with(client.state)


def test_set_schedule_enabled_calls_confirmed_coordinator_update() -> None:
    hass = MagicMock()
    coordinator = SimpleNamespace(
        async_set_schedule_enabled=AsyncMock(),
    )
    service_call = SimpleNamespace(
        data={
            FIELD_SCHEDULE_TASK_ID: 42,
            FIELD_ENABLED: False,
        }
    )

    _async_register_services(hass)
    handler = _registered_handler(hass, SERVICE_SET_SCHEDULE_ENABLED)

    with patch(
        "custom_components.narwal._async_single_narwal_coordinator",
        new=AsyncMock(return_value=coordinator),
    ):
        asyncio.run(handler(service_call))

    coordinator.async_set_schedule_enabled.assert_awaited_once_with(42, False)


@pytest.mark.parametrize("direct_target", ["all", "group.vacuums"])
async def test_clean_rooms_accepts_expanded_targets(direct_target: str) -> None:
    """Expanded all and group targets validate their resolved Narwal entities."""
    hass = MagicMock()
    registry = MagicMock()
    registry.async_get.return_value = SimpleNamespace(platform=DOMAIN)
    call = SimpleNamespace(
        context=SimpleNamespace(user_id=None),
        data={"entity_id": [direct_target]},
    )

    with patch("custom_components.narwal.er.async_get", return_value=registry):
        entity_ids = await _async_validate_clean_rooms_targets(
            hass,
            call,
            ["vacuum.flow_2"],
        )

    assert entity_ids == ["vacuum.flow_2"]
