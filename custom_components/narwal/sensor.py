"""Sensor entities for Narwal vacuum."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfArea, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import NarwalConfigEntry
from .coordinator import NarwalCoordinator
from .dynamic_entities import setup_dynamic_entities
from .entity import NarwalEntity
from .narwal_client import NarwalState, WorkingStatus, named_capabilities
from .narwal_client.config import config_snapshot_attributes
from .narwal_client.task import current_task_attributes


@dataclass(frozen=True, kw_only=True)
class NarwalSensorEntityDescription(SensorEntityDescription):
    """Describes a Narwal sensor entity."""

    value_fn: Callable[[NarwalState], float | str | None]


def _has_active_cleaning_metrics(state: NarwalState) -> bool:
    return state.is_cleaning or state.has_recent_active_working_status


def _station_task(state: NarwalState) -> str | None:
    """Return the active dock task."""
    if not state.is_station_active:
        return None
    if state.station_activity == 1:
        return "emptying_dustbin"
    if state.station_activity in (2, 3):
        return "washing_mop"
    if state.dry_mop_remaining_time is not None and state.dry_mop_remaining_time > 0:
        return "drying_mop"
    if state.station_activity == 4:
        return "drying_or_disinfecting"
    return "station_active"


SENSOR_DESCRIPTIONS: tuple[NarwalSensorEntityDescription, ...] = (
    NarwalSensorEntityDescription(
        key="battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        # battery_level comes from field 2 (real-time SOC as float32)
        value_fn=lambda state: state.battery_level if state.battery_level > 0 else None,
    ),
    NarwalSensorEntityDescription(
        key="cleaning_area",
        translation_key="cleaning_area",
        native_unit_of_measurement=UnitOfArea.SQUARE_METERS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda state: round(state.cleaning_area / 10000, 2)
        if state.cleaning_area > 0 and _has_active_cleaning_metrics(state)
        else None,
    ),
    NarwalSensorEntityDescription(
        key="cleaning_time",
        translation_key="cleaning_time",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda state: state.cleaning_time
        if state.cleaning_time > 0 and _has_active_cleaning_metrics(state)
        else None,
    ),
    NarwalSensorEntityDescription(
        key="task_progress",
        translation_key="task_progress",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda state: state.task_progress_percent
        if state.task_progress_percent is not None and _has_active_cleaning_metrics(state)
        else None,
    ),
    NarwalSensorEntityDescription(
        key="current_room",
        translation_key="current_room",
        value_fn=lambda state: state.current_room_name
        if state.current_room_name and _has_active_cleaning_metrics(state)
        else None,
    ),
    NarwalSensorEntityDescription(
        key="station_task",
        translation_key="station_task",
        device_class=SensorDeviceClass.ENUM,
        options=[
            "emptying_dustbin",
            "washing_mop",
            "drying_mop",
            "drying_or_disinfecting",
            "station_active",
        ],
        value_fn=_station_task,
    ),
    NarwalSensorEntityDescription(
        key="dry_mop_remaining_time",
        translation_key="dry_mop_remaining_time",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda state: state.dry_mop_remaining_time
        if state.is_station_active
        and state.dry_mop_remaining_time is not None
        and state.dry_mop_remaining_time > 0
        else None,
    ),
    NarwalSensorEntityDescription(
        key="firmware_version",
        translation_key="firmware_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda state: state.firmware_version or None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NarwalConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Narwal sensor entities."""
    coordinator = entry.runtime_data

    def discover():
        for description in SENSOR_DESCRIPTIONS:
            yield (
                description.key,
                lambda description=description: NarwalSensor(
                    coordinator,
                    description,
                ),
            )
        yield ("charging_state", lambda: NarwalChargingStateSensor(coordinator))
        yield ("task_status", lambda: NarwalTaskStatusSensor(coordinator))
        yield ("capabilities", lambda: NarwalCapabilitiesSensor(coordinator))
        yield ("config_snapshot", lambda: NarwalConfigSnapshotSensor(coordinator))
        yield ("current_clean_task", lambda: NarwalCurrentTaskSensor(coordinator))
        yield ("protocol_profile", lambda: NarwalProtocolProfileSensor(coordinator))

        profile = coordinator.device_profile
        if profile.clean_plan_inventory_enabled:
            yield ("clean_plans", lambda: NarwalCleanPlansSensor(coordinator))
        if profile.schedule_inventory_enabled:
            yield (
                "clean_schedules",
                lambda: NarwalCleanSchedulesSensor(coordinator),
            )
        if profile.consumable_inventory_enabled:
            yield (
                "consumable_categories",
                lambda: NarwalConsumableCategoriesSensor(coordinator),
            )
        if (
            profile.saved_map_inventory_enabled
            or profile.editable_map_inventory_enabled
            or profile.map_update_inventory_enabled
        ):
            yield ("map_inventory", lambda: NarwalMapInventorySensor(coordinator))
        if (
            profile.firmware_inventory_enabled
            or profile.language_inventory_enabled
            or profile.voice_inventory_enabled
        ):
            yield (
                "device_metadata",
                lambda: NarwalDeviceMetadataSensor(coordinator),
            )
        if profile.history_inventory_enabled:
            yield (
                "clean_timeline",
                lambda: NarwalCleanTimelineSensor(coordinator),
            )

    setup_dynamic_entities(
        entry,
        coordinator,
        async_add_entities,
        discover,
    )


class NarwalSensor(NarwalEntity, SensorEntity):
    """A Narwal sensor entity."""

    entity_description: NarwalSensorEntityDescription

    def __init__(
        self,
        coordinator: NarwalCoordinator,
        description: NarwalSensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        device_id = coordinator.config_entry.data["device_id"]
        self._attr_unique_id = f"{device_id}_{description.key}"

    @property
    def native_value(self) -> float | str | None:
        """Return the sensor value."""
        state = self.coordinator.data
        if state is None:
            return None
        return self.entity_description.value_fn(state)

class NarwalChargingStateSensor(NarwalEntity, SensorEntity):
    """Sensor showing charging state: Charging, Fully Charged, or unavailable."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_translation_key = "charging_state"
    _attr_options = ["charging", "fully_charged", "not_charging"]

    def __init__(self, coordinator: NarwalCoordinator) -> None:
        """Initialize the charging state sensor."""
        super().__init__(coordinator)
        device_id = coordinator.config_entry.data["device_id"]
        self._attr_unique_id = f"{device_id}_charging_state"

    @property
    def native_value(self) -> str | None:
        """Return charging state.

        Returns None (unavailable) when not docked.
        """
        state = self.coordinator.data
        if state is None:
            return None
        if not state.is_docked:
            return "not_charging"
        if state.battery_level >= 100:
            return "fully_charged"
        return "charging"

    @property
    def icon(self) -> str:
        """Return icon based on charging state."""
        if self.native_value == "fully_charged":
            return "mdi:battery"
        if self.native_value == "charging":
            return "mdi:battery-charging"
        if self.native_value == "not_charging":
            return "mdi:battery-off-outline"
        return "mdi:battery-unknown"


class NarwalTaskStatusSensor(NarwalEntity, SensorEntity):
    """Sensor showing the active cleaning or dock task state."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_translation_key = "task_status"
    _attr_options = [
        "cleaning",
        "returning",
        "paused",
        "station_active",
        "docked",
        "idle",
        "error",
        "unknown",
    ]

    def __init__(self, coordinator: NarwalCoordinator) -> None:
        """Initialize the task status sensor."""
        super().__init__(coordinator)
        device_id = coordinator.config_entry.data["device_id"]
        self._attr_unique_id = f"{device_id}_task_status"

    @property
    def native_value(self) -> str | None:
        """Return the active task status."""
        state = self.coordinator.data
        if state is None:
            return None
        is_cleaning_status = state.working_status in (
            WorkingStatus.CLEANING,
            WorkingStatus.CLEANING_V2,
            WorkingStatus.CLEANING_ALT,
            WorkingStatus.CLEANING_FLOW2,
        ) or state.has_recent_active_working_status
        if state.working_status == WorkingStatus.ERROR:
            return "error"
        if state.is_station_active:
            return "station_active"
        if state.is_docked:
            return "docked"
        if state.is_paused and is_cleaning_status:
            return "paused"
        if (
            state.working_status == WorkingStatus.TASK_COMPLETED
            or state.is_returning
        ):
            return "returning"
        if state.is_cleaning:
            return "cleaning"
        if state.working_status == WorkingStatus.STANDBY:
            return "idle"
        return "unknown"

    @property
    def icon(self) -> str:
        """Return icon based on task status."""
        value = self.native_value
        if value == "station_active":
            return "mdi:home-automation"
        if value == "cleaning":
            return "mdi:robot-vacuum"
        if value == "returning":
            return "mdi:home-import-outline"
        if value == "paused":
            return "mdi:pause"
        if value == "error":
            return "mdi:alert-circle-outline"
        return "mdi:information-outline"


class NarwalCapabilitiesSensor(NarwalEntity, SensorEntity):
    """Diagnostic inventory of capabilities advertised by the robot."""

    _attr_translation_key = "capabilities"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:list-status"

    def __init__(self, coordinator: NarwalCoordinator) -> None:
        """Initialize the capability inventory sensor."""
        super().__init__(coordinator)
        device_id = coordinator.config_entry.data["device_id"]
        self._attr_unique_id = f"{device_id}_capabilities"

    @property
    def native_value(self) -> int | None:
        """Return the number of explicitly advertised feature fields."""
        state = self.coordinator.data
        if state is None or not state.capabilities_fetched:
            return None
        return len(state.capabilities)

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Expose stable names and exact raw field values for diagnostics."""
        state = self.coordinator.data
        if state is None:
            return {}
        return {
            "fetch_completed": state.capabilities_fetched,
            "advertised": named_capabilities(state.capabilities),
            "raw_fields": {
                str(feature_id): value
                for feature_id, value in sorted(state.capabilities.items())
            },
        }


class NarwalConfigSnapshotSensor(NarwalEntity, SensorEntity):
    """Read-only configuration snapshot decoded from config/get."""

    _attr_translation_key = "config_snapshot"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:tune-variant"

    def __init__(self, coordinator: NarwalCoordinator) -> None:
        super().__init__(coordinator)
        device_id = coordinator.config_entry.data["device_id"]
        self._attr_unique_id = f"{device_id}_config_snapshot"

    @property
    def native_value(self) -> int | None:
        state = self.coordinator.data
        if state is None or state.config_snapshot is None:
            return None
        return len(state.config_snapshot.values)

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        state = self.coordinator.data
        if state is None or state.config_snapshot is None:
            return {}
        return config_snapshot_attributes(state.config_snapshot)


class NarwalCurrentTaskSensor(NarwalEntity, SensorEntity):
    """Read-only view of the robot's cached current CleanTask."""

    _attr_translation_key = "current_clean_task"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:clipboard-text-clock-outline"

    def __init__(self, coordinator: NarwalCoordinator) -> None:
        super().__init__(coordinator)
        device_id = coordinator.config_entry.data["device_id"]
        self._attr_unique_id = f"{device_id}_current_clean_task"

    @property
    def native_value(self) -> int | None:
        state = self.coordinator.data
        if state is None or state.current_clean_task is None:
            return None
        return state.current_clean_task.task_type

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        state = self.coordinator.data
        if state is None or state.current_clean_task is None:
            return {}
        return current_task_attributes(state.current_clean_task)


class NarwalProtocolProfileSensor(NarwalEntity, SensorEntity):
    """Resolved identity and operation-profile diagnostics."""

    _attr_translation_key = "protocol_profile"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:shield-search"

    def __init__(self, coordinator: NarwalCoordinator) -> None:
        super().__init__(coordinator)
        device_id = coordinator.config_entry.data["device_id"]
        self._attr_unique_id = f"{device_id}_protocol_profile"

    @property
    def native_value(self) -> str:
        return self.coordinator.device_profile.hardware_model

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        state = self.coordinator.data
        profile = self.coordinator.device_profile
        return {
            "product_key": profile.product_key,
            "firmware_version": profile.firmware_version,
            "display_model": profile.display_model,
            "parameterized_clean_enabled": profile.parameterized_clean_enabled,
            "telecontrol_enabled": profile.telecontrol_enabled,
            "station_actions": sorted(profile.station_actions),
            "config_writes_enabled": profile.config_writes_enabled,
            "clean_plan_inventory_enabled": profile.clean_plan_inventory_enabled,
            "schedule_inventory_enabled": profile.schedule_inventory_enabled,
            "saved_map_inventory_enabled": profile.saved_map_inventory_enabled,
            "editable_map_inventory_enabled": profile.editable_map_inventory_enabled,
            "map_update_inventory_enabled": profile.map_update_inventory_enabled,
            "consumable_inventory_enabled": profile.consumable_inventory_enabled,
            "firmware_inventory_enabled": profile.firmware_inventory_enabled,
            "language_inventory_enabled": profile.language_inventory_enabled,
            "voice_inventory_enabled": profile.voice_inventory_enabled,
            "history_inventory_enabled": profile.history_inventory_enabled,
            "raw_working_status": (
                state.raw_working_status_value if state is not None else None
            ),
        }


class NarwalCleanPlansSensor(NarwalEntity, SensorEntity):
    """Read-only inventory of saved and current official-app cleaning plans."""

    _attr_translation_key = "clean_plans"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:clipboard-list-outline"

    def __init__(self, coordinator: NarwalCoordinator) -> None:
        super().__init__(coordinator)
        device_id = coordinator.config_entry.data["device_id"]
        self._attr_unique_id = f"{device_id}_clean_plans"

    @property
    def native_value(self) -> int:
        """Return the number of cached saved plans."""
        return len(self.coordinator.client.state.clean_plans)

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Expose stable, compact plan metadata without opaque geometry."""
        state = self.coordinator.client.state
        current = state.current_clean_plan
        return {
            "current_plan_id": current.plan_id if current is not None else None,
            "plans": [
                {
                    "id": plan.plan_id,
                    "map_id": plan.map_id,
                    "clean_mode": plan.clean_mode,
                    "custom": plan.is_custom_plan,
                    "name": plan.custom_name,
                    "shown_in_station": plan.shown_in_station,
                    "perform_times": plan.perform_times,
                    "order": plan.order,
                    "area_count": len(plan.area_options),
                }
                for plan in state.clean_plans
            ],
        }


class NarwalCleanSchedulesSensor(NarwalEntity, SensorEntity):
    """Read-only inventory of local cleaning schedules."""

    _attr_translation_key = "clean_schedules"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator: NarwalCoordinator) -> None:
        super().__init__(coordinator)
        device_id = coordinator.config_entry.data["device_id"]
        self._attr_unique_id = f"{device_id}_clean_schedules"

    @property
    def native_value(self) -> int:
        """Return the number of cached schedules."""
        return len(self.coordinator.client.state.clean_schedules)

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Expose the APK-proven schedule fields without interpreting cron."""
        return {
            "schedules": [
                {
                    "task_id": schedule.task_id,
                    "cron": (
                        parameter.crontab.cron
                        if parameter is not None and parameter.crontab is not None
                        else None
                    ),
                    "reminding_time": (
                        parameter.crontab.reminding_time
                        if parameter is not None and parameter.crontab is not None
                        else None
                    ),
                    "enabled": (
                        parameter.crontab.enabled
                        if parameter is not None and parameter.crontab is not None
                        else None
                    ),
                    "clean_plan_id": (
                        parameter.clean_plan_id if parameter is not None else None
                    ),
                    "clean_mode": (
                        int(parameter.clean_mode)
                        if parameter is not None and parameter.clean_mode is not None
                        else None
                    ),
                    "custom": (
                        parameter.is_custom_plan if parameter is not None else None
                    ),
                    "name": parameter.custom_name if parameter is not None else None,
                }
                for schedule in self.coordinator.client.state.clean_schedules
                for parameter in (schedule.clean_schedule_param,)
            ]
        }


class NarwalConsumableCategoriesSensor(NarwalEntity, SensorEntity):
    """Local category inventory; this does not claim remaining-life telemetry."""

    _attr_translation_key = "consumable_categories"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:tools"

    def __init__(self, coordinator: NarwalCoordinator) -> None:
        super().__init__(coordinator)
        device_id = coordinator.config_entry.data["device_id"]
        self._attr_unique_id = f"{device_id}_consumable_categories"

    @property
    def native_value(self) -> int | None:
        """Return the total locally advertised category count."""
        info = self.coordinator.client.state.consumable_info
        if info is None:
            return None
        return len(info.maintain_items) + len(info.replace_items)

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Expose category names while preserving future unknown numbers."""
        info = self.coordinator.client.state.consumable_info
        if info is None:
            return {}

        def display(value) -> str | int:
            return value.name.lower() if hasattr(value, "name") else int(value)

        return {
            "remaining_life_available_locally": False,
            "maintenance_categories": [
                display(value) for value in info.maintain_items
            ],
            "replacement_categories": [
                display(value) for value in info.replace_items
            ],
        }


class NarwalMapInventorySensor(NarwalEntity, SensorEntity):
    """Read-only saved/editable map and supplementary-update metadata."""

    _attr_translation_key = "map_inventory"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:map-search-outline"

    def __init__(self, coordinator: NarwalCoordinator) -> None:
        super().__init__(coordinator)
        device_id = coordinator.config_entry.data["device_id"]
        self._attr_unique_id = f"{device_id}_map_inventory"

    @property
    def native_value(self) -> int | None:
        state = self.coordinator.client.state
        if not state.saved_maps_fetched:
            return None
        return len(state.saved_maps)

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        state = self.coordinator.client.state

        def summary(map_data) -> dict[str, object]:
            return {
                "map_id": map_data.map_id,
                "map_version": map_data.map_version,
                "edit_version": map_data.edit_version,
                "generation_time": map_data.generation_time,
                "width": map_data.width,
                "height": map_data.height,
                "room_count": len(map_data.rooms),
                "furniture_count": len(map_data.obstacles),
            }

        editable = state.editable_map
        editable_map = (
            summary(editable.map.map_data)
            if editable is not None and editable.map is not None
            else None
        )
        if editable_map is not None:
            editable_map["max_room_count"] = (
                editable.edit_config.max_room_nums
                if editable.edit_config is not None
                else None
            )
            editable_map["response_edit_version"] = editable.edit_version

        return {
            "saved_maps_fetched": state.saved_maps_fetched,
            "saved_maps": [summary(item.map_data) for item in state.saved_maps],
            "editable_map_fetched": state.editable_map_fetched,
            "editable_map": editable_map,
            "supplementary_update_fetched": state.map_update_info_fetched,
            "supplementary_update_available": (
                state.map_update_info.result
                if state.map_update_info is not None
                else None
            ),
        }


def _metadata_enum(value: object) -> str | int | None:
    """Return a stable serializable name for a known or future enum."""
    if value is None:
        return None
    if hasattr(value, "name"):
        return str(value.name).lower()
    return int(value)


def _firmware_entity(entity) -> dict[str, object] | None:
    if entity is None:
        return None
    return {
        "id": entity.firmware_id,
        "version": entity.version,
        "version_text": entity.version_text,
    }


class NarwalDeviceMetadataSensor(NarwalEntity, SensorEntity):
    """Firmware hierarchy plus language and current voice-package diagnostics."""

    _attr_translation_key = "device_metadata"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:robot-vacuum-variant"

    def __init__(self, coordinator: NarwalCoordinator) -> None:
        super().__init__(coordinator)
        device_id = coordinator.config_entry.data["device_id"]
        self._attr_unique_id = f"{device_id}_device_metadata"

    @property
    def native_value(self) -> str | None:
        state = self.coordinator.client.state
        firmware = state.firmware_metadata
        if firmware is not None and firmware.firmware_version_text:
            return firmware.firmware_version_text
        return state.firmware_version or None

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        state = self.coordinator.client.state
        firmware = state.firmware_metadata
        robot = firmware.robot if firmware is not None else None
        station = firmware.station if firmware is not None else None
        vision = firmware.vision if firmware is not None else None
        language = state.configured_language
        supported = state.supported_languages
        voice_response = state.current_voice_info
        voice = voice_response.voice_info if voice_response is not None else None
        return {
            "firmware_version_code": (
                firmware.firmware_version if firmware is not None else None
            ),
            "robot_firmware": (
                {
                    "mcu": _firmware_entity(robot.mcu),
                    "ble": _firmware_entity(robot.ble),
                    "cpu": _firmware_entity(robot.cpu),
                    "media": _firmware_entity(robot.media),
                    "sensors": [
                        _firmware_entity(item) for item in robot.sensor_list
                    ],
                }
                if robot is not None
                else None
            ),
            "station_firmware": (
                {
                    "mcu": _firmware_entity(station.mcu),
                    "ble": _firmware_entity(station.ble),
                    "cpu": _firmware_entity(station.cpu),
                    "media": _firmware_entity(station.media),
                    "media_b": _firmware_entity(station.media_b),
                }
                if station is not None
                else None
            ),
            "vision_firmware": (
                {
                    "ai": _firmware_entity(vision.ai),
                    "cpu": _firmware_entity(vision.cpu),
                }
                if vision is not None
                else None
            ),
            "configured_language": (
                _metadata_enum(language.language) if language is not None else None
            ),
            "configured_language_result": (
                _metadata_enum(language.result) if language is not None else None
            ),
            "supported_languages": (
                [_metadata_enum(item) for item in supported.languages]
                if supported is not None
                else []
            ),
            "supported_languages_result": (
                _metadata_enum(supported.result) if supported is not None else None
            ),
            "voice_result": (
                _metadata_enum(voice_response.result)
                if voice_response is not None
                else None
            ),
            "voice": (
                {
                    "language": voice.language,
                    "version": voice.version,
                    "description": voice.describe,
                    "timbre_id": voice.timbre_id,
                }
                if voice is not None
                else None
            ),
        }


class NarwalCleanTimelineSensor(NarwalEntity, SensorEntity):
    """Read-only local cleaning-task timeline used by the official app."""

    _attr_translation_key = "clean_timeline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:timeline-clock-outline"

    def __init__(self, coordinator: NarwalCoordinator) -> None:
        super().__init__(coordinator)
        device_id = coordinator.config_entry.data["device_id"]
        self._attr_unique_id = f"{device_id}_clean_timeline"

    @property
    def native_value(self) -> int | None:
        response = self.coordinator.client.state.clean_timeline
        if response is None or response.timeline_status is None:
            return None
        return len(response.timeline_status.event_nodes)

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        response = self.coordinator.client.state.clean_timeline
        if response is None:
            return {}
        nodes = (
            response.timeline_status.event_nodes
            if response.timeline_status is not None
            else ()
        )
        return {
            "result_code": response.result_code,
            "event_count": len(nodes),
            "recent_events": [
                {
                    "event_time": node.event_time,
                    "primary_task": node.primary_task,
                    "secondary_self_check": node.secondary_self_check,
                    "task_result": node.task_result,
                    "is_primary_node": node.is_primary_node,
                    "node_key": node.node_key,
                    "has_secondary_clean_event": (
                        node.secondary_clean_event is not None
                    ),
                    "has_error_code": node.error_code is not None,
                }
                for node in nodes[-20:]
            ],
        }
