"""Narwal Robot Vacuum integration for Home Assistant."""

from __future__ import annotations

import logging
import math
from typing import TypeAlias

import voluptuous as vol
from homeassistant.auth.permissions.const import POLICY_CONTROL
from homeassistant.components.vacuum import DOMAIN as VACUUM_DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_AREA_ID, ATTR_DEVICE_ID, ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import (
    ConfigEntryNotReady,
    HomeAssistantError,
    Unauthorized,
    UnknownUser,
)
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import service

from .const import (
    CONF_MODEL,
    CONF_PRODUCT_KEY,
    DOMAIN,
    PLATFORMS,
    SERVICE_CLEAN_ROOMS,
    SERVICE_DRIVE,
    SERVICE_GO_TO,
    SERVICE_SET_SCHEDULE_ENABLED,
    SERVICE_STOP_NAVIGATION,
    SERVICE_STOP_TELECONTROL,
)
from .coordinator import NarwalCoordinator, active_telecontrol_reason
from .narwal_client import (
    Capability,
    CleaningRoute,
    CommandResult,
    FanLevel,
    ManualControlMode,
    MopHumidity,
    MopStrengthLevel,
    NarwalCommandError,
    NarwalConnectionError,
    TelecontrolStatus,
    WorkingStatus,
    WorkMode,
    capability_enabled,
)

_LOGGER = logging.getLogger(__name__)

NarwalConfigEntry: TypeAlias = ConfigEntry[NarwalCoordinator]


FIELD_ROOMS = "rooms"
FIELD_MODE = "mode"
FIELD_SUCTION = "suction"
FIELD_WATER = "water"
FIELD_MOP_STRENGTH = "mop_strength"
FIELD_PASSES = "passes"
FIELD_ROUTE = "route"
FIELD_LINEAR_VELOCITY = "linear_velocity"
FIELD_ANGULAR_VELOCITY = "angular_velocity"
FIELD_DURATION_MS = "duration_ms"
FIELD_NORMALIZED_X = "x"
FIELD_NORMALIZED_Y = "y"
FIELD_MAP_REVISION = "map_revision"
FIELD_SCHEDULE_TASK_ID = "task_id"
FIELD_ENABLED = "enabled"

WORK_MODE_OPTIONS: dict[str, WorkMode] = {
    "vacuum": WorkMode.VACUUM,
    "mop": WorkMode.MOP,
    "vacuum_then_mop": WorkMode.VACUUM_THEN_MOP,
    "vacuum_and_mop": WorkMode.VACUUM_AND_MOP,
}
SUCTION_OPTIONS: dict[str, FanLevel] = {
    "ai": FanLevel.UNSPECIFIED,
    "quiet": FanLevel.MUTE,
    "standard": FanLevel.NORMAL,
    "strong": FanLevel.STRONG,
    "super_powerful": FanLevel.DEEP,
    "ultra_powerful": FanLevel.SUPER,
}
WATER_OPTIONS: dict[str, MopHumidity] = {
    "dry": MopHumidity.DRY,
    "normal": MopHumidity.NORMAL,
    "wet": MopHumidity.WET,
}
MOP_STRENGTH_OPTIONS: dict[str, MopStrengthLevel] = {
    "normal": MopStrengthLevel.NORMAL,
    "high": MopStrengthLevel.HIGH,
}
ROUTE_OPTIONS: dict[str, CleaningRoute] = {
    "standard": CleaningRoute.STANDARD,
    "meticulous": CleaningRoute.METICULOUS,
}

CLEAN_ROOMS_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_ENTITY_ID): cv.entity_ids,
        vol.Optional(ATTR_DEVICE_ID): cv.ensure_list,
        vol.Optional(ATTR_AREA_ID): cv.ensure_list,
        vol.Required(FIELD_ROOMS): cv.ensure_list,
        vol.Optional(FIELD_MODE, default="vacuum_and_mop"): vol.In(WORK_MODE_OPTIONS),
        vol.Optional(FIELD_SUCTION, default="standard"): vol.In(SUCTION_OPTIONS),
        vol.Optional(FIELD_WATER, default="normal"): vol.In(WATER_OPTIONS),
        vol.Optional(FIELD_MOP_STRENGTH, default="normal"): vol.In(MOP_STRENGTH_OPTIONS),
        vol.Optional(FIELD_PASSES, default=1): vol.All(vol.Coerce(int), vol.Range(min=1, max=3)),
        vol.Optional(FIELD_ROUTE): vol.In(ROUTE_OPTIONS),
    }
)


def _normalized_coordinate(value: object) -> float:
    """Validate a normalized map-image coordinate in the half-open [0, 1) range."""
    if isinstance(value, bool):
        raise vol.Invalid("coordinate must be a real number")
    try:
        coordinate = float(value)
    except (TypeError, ValueError) as err:
        raise vol.Invalid("coordinate must be a real number") from err
    if not math.isfinite(coordinate) or not 0 <= coordinate < 1:
        raise vol.Invalid("coordinate must be finite and between 0 (inclusive) and 1 (exclusive)")
    return coordinate


def _strict_boolean(value: object) -> bool:
    """Accept only a real boolean for state-changing schedule calls."""
    if type(value) is not bool:
        raise vol.Invalid("enabled must be true or false")
    return value


def _bounded_integer(
    value: object,
    *,
    name: str,
    minimum: int,
    maximum: int,
) -> int:
    """Validate a bounded integer without silently truncating numeric input."""
    if type(value) is int:
        parsed = value
    elif type(value) is float and math.isfinite(value) and value.is_integer():
        parsed = int(value)
    elif type(value) is str:
        try:
            parsed = int(value.strip(), 10)
        except ValueError as err:
            raise vol.Invalid(f"{name} must be an integer") from err
    else:
        raise vol.Invalid(f"{name} must be an integer")
    if not minimum <= parsed <= maximum:
        raise vol.Invalid(
            f"{name} must be between {minimum} and {maximum}"
        )
    return parsed


TELECONTROL_TARGET_SCHEMA = {
    vol.Optional(ATTR_ENTITY_ID): cv.entity_ids,
    vol.Optional(ATTR_DEVICE_ID): cv.ensure_list,
    vol.Optional(ATTR_AREA_ID): cv.ensure_list,
}

DRIVE_SCHEMA = vol.Schema(
    {
        **TELECONTROL_TARGET_SCHEMA,
        vol.Required(FIELD_LINEAR_VELOCITY): lambda value: _bounded_integer(
            value,
            name=FIELD_LINEAR_VELOCITY,
            minimum=-10,
            maximum=10,
        ),
        vol.Required(FIELD_ANGULAR_VELOCITY): lambda value: _bounded_integer(
            value,
            name=FIELD_ANGULAR_VELOCITY,
            minimum=-10,
            maximum=10,
        ),
        vol.Optional(FIELD_DURATION_MS, default=250): lambda value: _bounded_integer(
            value,
            name=FIELD_DURATION_MS,
            minimum=100,
            maximum=500,
        ),
    }
)

GO_TO_SCHEMA = vol.Schema(
    {
        **TELECONTROL_TARGET_SCHEMA,
        vol.Required(FIELD_NORMALIZED_X): _normalized_coordinate,
        vol.Required(FIELD_NORMALIZED_Y): _normalized_coordinate,
        vol.Required(FIELD_MAP_REVISION): str,
    }
)

STOP_TELECONTROL_SCHEMA = vol.Schema(TELECONTROL_TARGET_SCHEMA)

SET_SCHEDULE_ENABLED_SCHEMA = vol.Schema(
    {
        **TELECONTROL_TARGET_SCHEMA,
        vol.Required(FIELD_SCHEDULE_TASK_ID): lambda value: _bounded_integer(
            value,
            name=FIELD_SCHEDULE_TASK_ID,
            minimum=0,
            maximum=(1 << 32) - 1,
        ),
        vol.Required(FIELD_ENABLED): _strict_boolean,
    }
)


def _normalise_room_ids(raw_rooms: list) -> list[int]:
    """Return room IDs from HA service data."""
    room_ids: list[int] = []
    for item in raw_rooms:
        if isinstance(item, str):
            cleaned = item.strip().strip("[]")
            if cleaned.lower() == "all":
                continue
            values = cleaned.replace(",", " ").split()
            room_ids.extend(int(value) for value in values if value)
        else:
            room_ids.append(int(item))
    return room_ids


def _rooms_requested_all(raw_rooms: list) -> bool:
    """Return True if a service call requests all current map rooms."""
    return any(isinstance(item, str) and item.strip().lower() == "all" for item in raw_rooms)


async def _async_room_ids_for_coordinator(
    coordinator: NarwalCoordinator,
    raw_rooms: list,
) -> list[int]:
    """Resolve configured service rooms for a single Narwal coordinator."""
    if not _rooms_requested_all(raw_rooms):
        return _normalise_room_ids(raw_rooms)

    state = coordinator.client.state
    if state.map_data is None:
        await coordinator.client.get_map()
    if state.map_data is None:
        return []
    return [room.room_id for room in state.map_data.rooms if room.room_id > 0]


def _domain_data(hass: HomeAssistant) -> dict:
    """Return Narwal domain runtime data."""
    return hass.data.setdefault(DOMAIN, {})


async def _async_get_service_coordinators(
    hass: HomeAssistant,
    entity_ids: list[str] | None,
) -> list[NarwalCoordinator]:
    """Resolve service entity IDs to Narwal coordinators."""
    data = _domain_data(hass)
    if not entity_ids:
        raise HomeAssistantError("Target a Narwal vacuum")

    registry = er.async_get(hass)
    coordinators: list[NarwalCoordinator] = []
    for entity_id in entity_ids:
        registry_entry = registry.async_get(entity_id)
        if registry_entry is None or registry_entry.config_entry_id is None:
            continue
        coordinator = data.get(registry_entry.config_entry_id)
        if not isinstance(coordinator, NarwalCoordinator):
            continue
        if coordinator not in coordinators:
            coordinators.append(coordinator)
    if not coordinators:
        raise HomeAssistantError("Target does not contain a Narwal entity")
    return coordinators


async def _async_validate_clean_rooms_targets(
    hass: HomeAssistant,
    call,
    entity_ids: list[str],
) -> list[str]:
    """Validate clean-room target domains and user permissions."""
    registry = er.async_get(hass)
    vacuum_entity_ids: list[str] = []
    for entity_id in entity_ids:
        registry_entry = registry.async_get(entity_id)
        if (
            entity_id.startswith(f"{VACUUM_DOMAIN}.")
            and registry_entry is not None
            and registry_entry.platform == DOMAIN
        ):
            vacuum_entity_ids.append(entity_id)

    direct_entity_ids = call.data.get(ATTR_ENTITY_ID, [])
    if isinstance(direct_entity_ids, str):
        direct_entity_ids = [direct_entity_ids]
    direct_entity_ids = [
        entity_id
        for entity_id in direct_entity_ids
        if entity_id != "all" and not entity_id.startswith("group.")
    ]
    if any(entity_id not in vacuum_entity_ids for entity_id in direct_entity_ids):
        raise HomeAssistantError("Target must be a Narwal vacuum entity")

    user_id = call.context.user_id
    if not user_id:
        return vacuum_entity_ids
    user = await hass.auth.async_get_user(user_id)
    if user is None:
        raise UnknownUser(context=call.context, user_id=user_id)
    if user.is_admin:
        return vacuum_entity_ids
    for entity_id in vacuum_entity_ids:
        if not user.permissions.check_entity(entity_id, POLICY_CONTROL):
            raise Unauthorized(
                context=call.context,
                entity_id=entity_id,
                permission=POLICY_CONTROL,
            )
    return vacuum_entity_ids


async def _async_single_narwal_coordinator(
    hass: HomeAssistant,
    call,
) -> NarwalCoordinator:
    """Resolve and authorize exactly one Narwal vacuum target."""
    entity_ids = list(await service.async_extract_entity_ids(call))
    if not entity_ids and any(
        key in call.data for key in (ATTR_ENTITY_ID, ATTR_DEVICE_ID, ATTR_AREA_ID)
    ):
        raise HomeAssistantError("Target does not contain a Narwal entity")
    entity_ids = await _async_validate_clean_rooms_targets(hass, call, entity_ids)
    coordinators = await _async_get_service_coordinators(hass, entity_ids)
    if len(coordinators) != 1:
        raise HomeAssistantError("Target exactly one Narwal vacuum")
    return coordinators[0]


async def _async_single_telecontrol_coordinator(
    hass: HomeAssistant,
    call,
) -> NarwalCoordinator:
    """Resolve, authorize, and capability-check one Narwal vacuum target."""
    coordinator = await _async_single_narwal_coordinator(hass, call)
    if not coordinator.telecontrol_enabled:
        raise HomeAssistantError(
            "Telecontrol is not available for this model and advertised capability set"
        )
    return coordinator


async def _async_prepare_motion(coordinator: NarwalCoordinator) -> None:
    """Refresh state and reject motion while another robot task owns movement."""
    client = coordinator.client
    try:
        if not client.robot_awake:
            await client.wake(timeout=10.0)
        await client.get_status(full_update=True)
    except Exception as err:
        raise HomeAssistantError(
            "Could not confirm the robot's current state"
        ) from err

    state = client.state
    if state.working_status in (WorkingStatus.UNKNOWN, WorkingStatus.ERROR):
        raise HomeAssistantError(
            f"Robot state does not permit telecontrol: {state.working_status.name}"
        )
    if (
        state.is_cleaning
        or state.is_paused_during_active_task
        or state.is_returning
    ):
        raise HomeAssistantError(
            "Stop the current cleaning or return-to-dock task before telecontrol"
        )
    if state.is_station_active:
        raise HomeAssistantError(
            "Wait for the base-station task to finish before telecontrol"
        )
    if (
        client.manual_control_active
        or client.manual_control_state != int(ManualControlMode.OFF)
    ):
        raise HomeAssistantError(
            "Manual control is already active; call stop_telecontrol first"
        )
    if (
        client.point_navigation_active
        or client.telecontrol_status == int(TelecontrolStatus.POINT_NAVI)
    ):
        raise HomeAssistantError(
            "Point navigation is already active; call stop_navigation first"
        )


def _exclusive_action_lock(
    coordinator: NarwalCoordinator,
    action: str,
):
    """Claim one physical action slot, translating its error for HA callers."""
    try:
        return coordinator.exclusive_action_lock(action)
    except NarwalCommandError as err:
        raise HomeAssistantError(str(err)) from err


def _raise_for_command_result(action: str, response) -> None:
    """Raise a Home Assistant error unless an action returned a known success."""
    if not response.result_known:
        raise HomeAssistantError(f"Narwal {action} returned an unconfirmed response")
    if response.result_code == CommandResult.SUCCESS:
        return
    try:
        result_name = CommandResult(response.result_code).name
    except ValueError:
        result_name = f"UNKNOWN({response.result_code})"
    raise HomeAssistantError(
        f"Narwal {action} failed: {result_name} ({response.result_code})"
    )


def _async_register_services(hass: HomeAssistant) -> None:
    """Register Narwal domain services."""

    async def async_clean_rooms_for_coordinator(
        coordinator: NarwalCoordinator,
        call,
    ) -> None:
        """Run one room-clean start while owning the physical action slot."""
        async with _exclusive_action_lock(coordinator, "start room cleaning"):
            if not coordinator.parameterized_clean_enabled:
                raise HomeAssistantError(
                    "Parameterized cleaning is not available for this model "
                    "and advertised capability set."
                )
            client = coordinator.client
            if not client.robot_awake:
                await client.wake(timeout=10.0)
            try:
                await client.get_status(full_update=True)
            except Exception as err:
                raise HomeAssistantError(
                    "Could not confirm the robot state before room cleaning"
                ) from err
            if client.state.is_station_active:
                raise HomeAssistantError(
                    "Wait for the base-station task to finish before room cleaning"
                )
            if reason := active_telecontrol_reason(client):
                raise HomeAssistantError(reason)
            if FIELD_ROUTE in call.data and not capability_enabled(
                client.state.capabilities,
                Capability.OVERLAP_ADJUST,
            ):
                raise HomeAssistantError(
                    "Cleaning route selection is not advertised by this robot"
                )
            room_ids = await _async_room_ids_for_coordinator(
                coordinator,
                call.data[FIELD_ROOMS],
            )
            if not room_ids:
                raise HomeAssistantError("At least one room must be selected")
            resp = await client.start_rooms(
                room_ids,
                work_mode=WORK_MODE_OPTIONS[call.data[FIELD_MODE]],
                fan=SUCTION_OPTIONS[call.data[FIELD_SUCTION]],
                water=WATER_OPTIONS[call.data[FIELD_WATER]],
                mop_strength=MOP_STRENGTH_OPTIONS[call.data[FIELD_MOP_STRENGTH]],
                passes=call.data[FIELD_PASSES],
                route=ROUTE_OPTIONS[call.data[FIELD_ROUTE]]
                if FIELD_ROUTE in call.data
                else None,
            )
            if not resp.result_known:
                result_name = "UNCONFIRMED_RESPONSE"
            else:
                try:
                    result_name = CommandResult(resp.result_code).name
                except ValueError:
                    result_name = f"UNKNOWN({resp.result_code})"
            _LOGGER.info(
                "Clean rooms response: %s (code=%s), rooms=%s",
                result_name,
                resp.result_code,
                room_ids,
            )
            if not resp.result_known:
                _LOGGER.warning(
                    "The parameterized clean response did not include an action "
                    "result code; physical behavior must be verified directly"
                )
            elif resp.result_code != CommandResult.SUCCESS:
                raise HomeAssistantError(
                    f"Narwal room clean failed: {result_name} ({resp.result_code})"
                )
            coordinator.async_set_updated_data(client.state)

    async def async_clean_rooms(call) -> None:
        entity_ids = list(await service.async_extract_entity_ids(call))
        if not entity_ids and any(
            key in call.data for key in (ATTR_ENTITY_ID, ATTR_DEVICE_ID, ATTR_AREA_ID)
        ):
            raise HomeAssistantError("Target does not contain a Narwal entity")
        entity_ids = await _async_validate_clean_rooms_targets(hass, call, entity_ids)
        coordinators = await _async_get_service_coordinators(
            hass,
            entity_ids,
        )
        for coordinator in coordinators:
            await async_clean_rooms_for_coordinator(coordinator, call)

    async def async_drive_for_coordinator(
        coordinator: NarwalCoordinator,
        call,
    ) -> None:
        """Run one bounded drive pulse while holding the physical action slot."""
        async with _exclusive_action_lock(coordinator, "drive the robot"):
            client = coordinator.client
            stop_generation = client.telecontrol_stop_generation
            await _async_prepare_motion(coordinator)
            if client.state.is_docked:
                raise HomeAssistantError(
                    "Joystick driving is blocked while the robot is on its dock; "
                    "use Go to for autonomous navigation"
                )
            linear_velocity = call.data[FIELD_LINEAR_VELOCITY]
            angular_velocity = call.data[FIELD_ANGULAR_VELOCITY]
            if linear_velocity == 0 and angular_velocity == 0:
                raise HomeAssistantError(
                    "At least one joystick velocity component must be non-zero"
                )
            try:
                response = await client.manual_control_pulse(
                    linear_velocity,
                    angular_velocity,
                    duration=call.data[FIELD_DURATION_MS] / 1000,
                    expected_generation=stop_generation,
                )
            except Exception as err:
                raise HomeAssistantError(
                    "Narwal joystick pulse failed; the client attempted its dead-man stop"
                ) from err
            _raise_for_command_result("joystick pulse", response)
            coordinator.async_set_updated_data(coordinator.client.state)

    async def async_drive(call) -> None:
        coordinator = await _async_single_telecontrol_coordinator(hass, call)
        await async_drive_for_coordinator(coordinator, call)

    async def async_go_to_for_coordinator(
        coordinator: NarwalCoordinator,
        call,
    ) -> None:
        """Run one point-navigation request while holding the action slot."""
        async with _exclusive_action_lock(coordinator, "start point navigation"):
            client = coordinator.client
            stop_generation = client.telecontrol_stop_generation
            await _async_prepare_motion(coordinator)
            try:
                await client.get_map()
            except Exception as err:
                raise HomeAssistantError(
                    "Could not refresh the map before navigation"
                ) from err
            map_data = client.state.map_data
            if map_data is None:
                raise HomeAssistantError("No active Narwal map is available")
            current_revision = map_data.navigation_revision()
            if current_revision is None:
                raise HomeAssistantError(
                    "The active map does not contain valid navigation geometry"
                )
            if call.data[FIELD_MAP_REVISION] != current_revision:
                raise HomeAssistantError(
                    "The map changed after this destination was selected; "
                    "refresh the map and choose the point again"
                )
            normalized_x = call.data[FIELD_NORMALIZED_X]
            normalized_y = call.data[FIELD_NORMALIZED_Y]
            grid = map_data.image_to_grid_cell(
                normalized_x * map_data.width,
                normalized_y * map_data.height,
            )
            destination = map_data.normalized_image_to_world(
                normalized_x,
                normalized_y,
            )
            if grid is None or destination is None:
                raise HomeAssistantError("Destination is outside the active map")
            if not map_data.is_navigation_target_clear(
                *grid,
                clearance_cells=1,
                reject_furniture=True,
            ):
                raise HomeAssistantError(
                    "Destination is not a clear mapped floor point"
                )
            try:
                response = await client.start_point_navigation(
                    *destination,
                    expected_generation=stop_generation,
                )
            except Exception as err:
                raise HomeAssistantError("Narwal point navigation failed") from err
            _raise_for_command_result("point navigation", response)
            coordinator.async_set_updated_data(client.state)

    async def async_go_to(call) -> None:
        coordinator = await _async_single_telecontrol_coordinator(hass, call)
        await async_go_to_for_coordinator(coordinator, call)

    async def async_stop_navigation(call) -> None:
        coordinator = await _async_single_telecontrol_coordinator(hass, call)
        try:
            response = await coordinator.client.cancel_point_navigation()
        except Exception as err:
            raise HomeAssistantError(
                "Narwal point-navigation stop failed"
            ) from err
        _raise_for_command_result("point-navigation stop", response)
        coordinator.async_set_updated_data(coordinator.client.state)

    async def async_stop_telecontrol(call) -> None:
        coordinator = await _async_single_telecontrol_coordinator(hass, call)
        try:
            await coordinator.client.emergency_stop_telecontrol()
        except Exception as err:
            raise HomeAssistantError(
                "Narwal emergency stop was not fully confirmed"
            ) from err
        coordinator.async_set_updated_data(coordinator.client.state)

    async def async_set_schedule_enabled(call) -> None:
        coordinator = await _async_single_narwal_coordinator(hass, call)
        try:
            await coordinator.async_set_schedule_enabled(
                call.data[FIELD_SCHEDULE_TASK_ID],
                call.data[FIELD_ENABLED],
            )
        except Exception as err:
            raise HomeAssistantError(
                "Narwal schedule enabled-state update was not confirmed"
            ) from err

    hass.services.async_register(
        DOMAIN,
        SERVICE_CLEAN_ROOMS,
        async_clean_rooms,
        schema=CLEAN_ROOMS_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_DRIVE,
        async_drive,
        schema=DRIVE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GO_TO,
        async_go_to,
        schema=GO_TO_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_STOP_NAVIGATION,
        async_stop_navigation,
        schema=STOP_TELECONTROL_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_STOP_TELECONTROL,
        async_stop_telecontrol,
        schema=STOP_TELECONTROL_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_SCHEDULE_ENABLED,
        async_set_schedule_enabled,
        schema=SET_SCHEDULE_ENABLED_SCHEMA,
    )


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up Narwal services."""
    _async_register_services(hass)
    return True


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate old config entries to version 2 (add product_key)."""
    if config_entry.version < 2:
        _LOGGER.info(
            "Migrating Narwal config entry from version %d to 2",
            config_entry.version,
        )
        new_data = {**config_entry.data}
        if CONF_PRODUCT_KEY not in new_data:
            new_data[CONF_PRODUCT_KEY] = "QoEsI5qYXO"
        if CONF_MODEL not in new_data:
            new_data[CONF_MODEL] = "Narwal Flow"
        hass.config_entries.async_update_entry(
            config_entry, data=new_data, version=2,
        )
        _LOGGER.info("Migration complete: product_key=%s", new_data[CONF_PRODUCT_KEY])
    return True


async def async_setup_entry(hass: HomeAssistant, entry: NarwalConfigEntry) -> bool:
    """Set up Narwal from a config entry."""
    coordinator = NarwalCoordinator(hass, entry)
    try:
        await coordinator.async_setup()
    except NarwalConnectionError as err:
        raise ConfigEntryNotReady(
            f"Cannot connect to Narwal vacuum at {entry.data['host']}: {err}"
        ) from err

    entry.runtime_data = coordinator
    data = _domain_data(hass)
    data[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: NarwalConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        await entry.runtime_data.async_shutdown()
        data = _domain_data(hass)
        data.pop(entry.entry_id, None)

    return unload_ok
