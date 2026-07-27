"""Persistent configuration switches for Narwal robots."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import NarwalConfigEntry
from .coordinator import NarwalCoordinator
from .dynamic_entities import setup_dynamic_entities
from .entity import NarwalEntity
from .narwal_client import Capability, capability_enabled
from .narwal_client.config import SetConfigField


@dataclass(frozen=True, kw_only=True)
class NarwalConfigSwitchEntityDescription(SwitchEntityDescription):
    """Describes one Boolean Narwal configuration field."""

    config_field: SetConfigField
    icon: str
    required_feature: Capability | None = None


SWITCH_DESCRIPTIONS: tuple[NarwalConfigSwitchEntityDescription, ...] = (
    NarwalConfigSwitchEntityDescription(
        key="child_lock",
        translation_key="child_lock",
        entity_category=EntityCategory.CONFIG,
        config_field=SetConfigField.CHILD_LOCK_ENABLED,
        icon="mdi:account-lock-outline",
    ),
    NarwalConfigSwitchEntityDescription(
        key="clean_carpets",
        translation_key="clean_carpets",
        entity_category=EntityCategory.CONFIG,
        config_field=SetConfigField.CLEAN_CARPET_ENABLED,
        icon="mdi:rug",
        required_feature=Capability.CARPET_CLEAN_SETTING,
    ),
    NarwalConfigSwitchEntityDescription(
        key="smart_clean_detection",
        translation_key="smart_clean_detection",
        entity_category=EntityCategory.CONFIG,
        config_field=SetConfigField.SMART_CLEAN_DETECTION_ENABLED,
        icon="mdi:auto-fix",
    ),
    NarwalConfigSwitchEntityDescription(
        key="pet_mode",
        translation_key="pet_mode",
        entity_category=EntityCategory.CONFIG,
        config_field=SetConfigField.PET_MODE,
        icon="mdi:paw",
        required_feature=Capability.PET_MODE,
    ),
    NarwalConfigSwitchEntityDescription(
        key="smart_deep_clean",
        translation_key="smart_deep_clean",
        entity_category=EntityCategory.CONFIG,
        config_field=SetConfigField.SMART_DEEP_CLEAN_ENABLED,
        icon="mdi:creation",
    ),
    NarwalConfigSwitchEntityDescription(
        key="moisture_proof_mop_pad",
        translation_key="moisture_proof_mop_pad",
        entity_category=EntityCategory.CONFIG,
        config_field=SetConfigField.MOISTURE_PROOF_PAD_PROTECT_ENABLED,
        icon="mdi:water-off",
    ),
    NarwalConfigSwitchEntityDescription(
        key="dust_collection",
        translation_key="dust_collection",
        entity_category=EntityCategory.CONFIG,
        config_field=SetConfigField.DUST_GATHERING_ENABLED,
        icon="mdi:delete-empty",
    ),
    NarwalConfigSwitchEntityDescription(
        key="smart_dust_collection",
        translation_key="smart_dust_collection",
        entity_category=EntityCategory.CONFIG,
        config_field=SetConfigField.SMART_DUST_GATHERING_ENABLED,
        icon="mdi:delete-clock",
        required_feature=Capability.DUST_SENSOR,
    ),
    NarwalConfigSwitchEntityDescription(
        key="return_to_main_map",
        translation_key="return_to_main_map",
        entity_category=EntityCategory.CONFIG,
        config_field=SetConfigField.SWITCH_BACK_TO_MAIN_MAP_AFTER_TEMP_MAP_CLEAN,
        icon="mdi:map-marker-path",
        required_feature=Capability.APP_UPDATE_MAP,
    ),
    NarwalConfigSwitchEntityDescription(
        key="quiet_dust_collection",
        translation_key="quiet_dust_collection",
        entity_category=EntityCategory.CONFIG,
        config_field=SetConfigField.QUIET_DUST_GATHERING_ENABLED,
        icon="mdi:volume-low",
        required_feature=Capability.QUIET_DUST_GATHERING,
    ),
    NarwalConfigSwitchEntityDescription(
        key="dry_robot_bag",
        translation_key="dry_robot_bag",
        entity_category=EntityCategory.CONFIG,
        config_field=SetConfigField.DRY_ROBOT_BAG_ENABLED,
        icon="mdi:air-filter",
        required_feature=Capability.TEMP_HUMIDITY_DETECTION_FOR_DRY_DUST_BAG,
    ),
    NarwalConfigSwitchEntityDescription(
        key="hot_water_wash",
        translation_key="hot_water_wash",
        entity_category=EntityCategory.CONFIG,
        config_field=SetConfigField.HOT_WATER_WASH_ENABLED,
        icon="mdi:water-thermometer",
        required_feature=Capability.HOT_WATER_WASH,
    ),
    NarwalConfigSwitchEntityDescription(
        key="massive_dirty_deep_clean",
        translation_key="massive_dirty_deep_clean",
        entity_category=EntityCategory.CONFIG,
        config_field=SetConfigField.MASSIVE_DIRTY_DEEP_CLEAN_ENABLE,
        icon="mdi:spray-bottle",
        required_feature=Capability.CLEAN_TASK_MASSIVE_DIRTY_CLEAN,
    ),
    NarwalConfigSwitchEntityDescription(
        key="speech_control",
        translation_key="speech_control",
        entity_category=EntityCategory.CONFIG,
        config_field=SetConfigField.SPEECH_CONTROL_ENABLED,
        icon="mdi:account-voice",
        required_feature=Capability.SPEECH,
    ),
    NarwalConfigSwitchEntityDescription(
        key="off_dock_auto_poweroff",
        translation_key="off_dock_auto_poweroff",
        entity_category=EntityCategory.CONFIG,
        config_field=SetConfigField.AUTOMATIC_POWEROFF_WHEN_DISCHARGING,
        icon="mdi:power-sleep",
        required_feature=Capability.AUTOMATIC_POWEROFF_WHEN_DISCHARGING,
    ),
    NarwalConfigSwitchEntityDescription(
        key="ai_voice_effects",
        translation_key="ai_voice_effects",
        entity_category=EntityCategory.CONFIG,
        config_field=SetConfigField.AI_VOICE_SOUND_EFFECT_ENABLED,
        icon="mdi:account-voice",
        required_feature=Capability.AI_VOICE_SOUND_EFFECT,
    ),
    NarwalConfigSwitchEntityDescription(
        key="ai_waiting_effects",
        translation_key="ai_waiting_effects",
        entity_category=EntityCategory.CONFIG,
        config_field=SetConfigField.AI_VOICE_SOUND_EFFECT_FOR_WAITING_ENABLED,
        icon="mdi:message-processing-outline",
        required_feature=Capability.AI_VOICE_SOUND_EFFECT_FOR_WAITING,
    ),
    NarwalConfigSwitchEntityDescription(
        key="all_things_recognition",
        translation_key="all_things_recognition",
        entity_category=EntityCategory.CONFIG,
        config_field=SetConfigField.ALL_THINGS_RECOGNITION_ENABLED,
        icon="mdi:eye-outline",
        required_feature=Capability.ALL_THINGS_RECOGNITION,
    ),
    NarwalConfigSwitchEntityDescription(
        key="precious_item_guard",
        translation_key="precious_item_guard",
        entity_category=EntityCategory.CONFIG,
        config_field=SetConfigField.PRECIOUS_ITEM_GUARD_ENABLED,
        icon="mdi:shield-star-outline",
        required_feature=Capability.PRECIOUS_ITEM_GUARD,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NarwalConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up snapshot- and capability-backed configuration switches."""
    coordinator = entry.runtime_data

    def discover():
        if not coordinator.device_profile.config_writes_enabled:
            return
        snapshot = coordinator.client.state.config_snapshot
        if snapshot is None:
            return
        capabilities = coordinator.client.state.capabilities
        for description in SWITCH_DESCRIPTIONS:
            if description.config_field not in snapshot.values:
                continue
            if (
                description.required_feature is not None
                and not capability_enabled(
                    capabilities,
                    description.required_feature,
                )
            ):
                continue
            yield (
                description.key,
                lambda description=description: NarwalConfigSwitch(
                    coordinator,
                    description,
                ),
            )

    setup_dynamic_entities(
        entry,
        coordinator,
        async_add_entities,
        discover,
    )


class NarwalConfigSwitch(NarwalEntity, SwitchEntity):
    """Switch backed by a single-setting ``config/set`` patch."""

    entity_description: NarwalConfigSwitchEntityDescription

    def __init__(
        self,
        coordinator: NarwalCoordinator,
        description: NarwalConfigSwitchEntityDescription,
    ) -> None:
        """Initialize the configuration switch."""
        super().__init__(coordinator)
        self.entity_description = description
        device_id = coordinator.config_entry.data["device_id"]
        self._attr_unique_id = f"{device_id}_{description.key}"
        self._attr_icon = description.icon

    @property
    def available(self) -> bool:
        """Return whether the live profile and config snapshot support this field."""
        if not super().available or not self.coordinator.device_profile.config_writes_enabled:
            return False
        snapshot = self.coordinator.client.state.config_snapshot
        if snapshot is None or self.entity_description.config_field not in snapshot.values:
            return False
        feature = self.entity_description.required_feature
        return feature is None or capability_enabled(
            self.coordinator.client.state.capabilities,
            feature,
        )

    @property
    def is_on(self) -> bool | None:
        """Return the latest read-back value."""
        snapshot = self.coordinator.client.state.config_snapshot
        if snapshot is None:
            return None
        value = snapshot.values.get(self.entity_description.config_field)
        return value if type(value) is bool else None

    async def _async_set(self, enabled: bool) -> None:
        """Write and verify one Boolean setting."""
        if not self.available:
            raise HomeAssistantError(
                f"Narwal {self.entity_description.key} is not currently available"
            )
        try:
            await self.coordinator.async_set_config(
                self.entity_description.config_field,
                enabled,
            )
        except Exception as err:
            raise HomeAssistantError(
                f"Narwal did not confirm {self.entity_description.key}"
            ) from err

    async def async_turn_on(self, **kwargs) -> None:
        """Enable the setting."""
        await self._async_set(True)

    async def async_turn_off(self, **kwargs) -> None:
        """Disable the setting."""
        await self._async_set(False)
