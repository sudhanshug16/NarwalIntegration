"""Persistent numeric configuration for Narwal robots."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import NarwalConfigEntry
from .coordinator import NarwalCoordinator
from .dynamic_entities import setup_dynamic_entities
from .entity import NarwalEntity
from .narwal_client.config import SetConfigField


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NarwalConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the robot volume control when present in its live config."""
    coordinator = entry.runtime_data

    def discover():
        snapshot = coordinator.client.state.config_snapshot
        if (
            coordinator.device_profile.config_writes_enabled
            and snapshot is not None
            and SetConfigField.VOLUME_PERCENTAGE in snapshot.values
        ):
            yield (
                "robot_volume",
                lambda: NarwalVolumeNumber(coordinator),
            )

    setup_dynamic_entities(
        entry,
        coordinator,
        async_add_entities,
        discover,
    )


class NarwalVolumeNumber(NarwalEntity, NumberEntity):
    """Robot speaker volume backed by ``config/set`` field 1."""

    _attr_translation_key = "robot_volume"
    _attr_icon = "mdi:volume-high"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator: NarwalCoordinator) -> None:
        """Initialize the volume number."""
        super().__init__(coordinator)
        device_id = coordinator.config_entry.data["device_id"]
        self._attr_unique_id = f"{device_id}_robot_volume"

    @property
    def available(self) -> bool:
        """Return whether volume remains present and writable."""
        if not super().available or not self.coordinator.device_profile.config_writes_enabled:
            return False
        snapshot = self.coordinator.client.state.config_snapshot
        return (
            snapshot is not None
            and SetConfigField.VOLUME_PERCENTAGE in snapshot.values
        )

    @property
    def native_value(self) -> float | None:
        """Return the latest read-back volume."""
        snapshot = self.coordinator.client.state.config_snapshot
        if snapshot is None:
            return None
        value = snapshot.values.get(SetConfigField.VOLUME_PERCENTAGE)
        return float(value) if type(value) is int else None

    async def async_set_native_value(self, value: float) -> None:
        """Set integer percent volume and require exact read-back."""
        rounded = round(value)
        if value != rounded:
            raise HomeAssistantError("Narwal volume must be a whole percentage")
        if not self.available:
            raise HomeAssistantError("Narwal volume is not currently available")
        try:
            await self.coordinator.async_set_config(
                SetConfigField.VOLUME_PERCENTAGE,
                rounded,
            )
        except Exception as err:
            raise HomeAssistantError(
                "Narwal did not confirm the requested volume"
            ) from err
