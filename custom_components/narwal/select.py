"""Select entities for Narwal vacuum controls."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import NarwalConfigEntry
from .const import (
    FAN_SPEED_LIST,
)
from .coordinator import NarwalCoordinator
from .dynamic_entities import setup_dynamic_entities
from .entity import NarwalEntity
from .narwal_client import Capability, WorkingStatus, capability_enabled
from .narwal_client.config import (
    AvoidMode,
    CarpetCleanOption,
    CarpetCleanPriorityOption,
    CarpetDeepCleanOption,
    CleanMode,
    CleanMopFrequency,
    CornerCleanMode,
    DryMopStrength,
    Language,
    SetConfigField,
    StationLightCtrlType,
)

MODE_OPTIONS = ("Vacuum", "Mop", "Vacuum then mop", "Vacuum and mop")
DEFAULT_MODE = "Vacuum and mop"
SUCTION_OPTIONS = ("AI", *FAN_SPEED_LIST)
WATER_OPTIONS = ("Dry", "Normal", "Wet")
SCRUB_OPTIONS = ("Normal", "High")
ROUTE_OPTIONS = ("Standard", "Meticulous")
PASSES_OPTIONS = ("1", "2", "3")

ACTIVE_CLEANING_STATUSES = (
    WorkingStatus.CLEANING,
    WorkingStatus.CLEANING_V2,
    WorkingStatus.CLEANING_ALT,
    WorkingStatus.CLEANING_FLOW2,
)

MOP_MODES = {"Mop", "Vacuum then mop", "Vacuum and mop"}
VACUUM_MODES = {"Vacuum", "Vacuum then mop", "Vacuum and mop"}
START_ONLY_SETTINGS = {"mode", "suction", "water", "scrub", "route", "passes"}

RUNTIME_SUCTION_KEY = "runtime_suction"
RUNTIME_WATER_KEY = "runtime_water"

SETTING_KEYS = {
    "mode",
    "suction",
    "water",
    "scrub",
    "route",
    "passes",
}

@dataclass(frozen=True, kw_only=True)
class NarwalSettingSelectEntityDescription(SelectEntityDescription):
    """Describes a Narwal setting select."""

    setting_key: str
    setting_options: tuple[str, ...]
    default_option: str
    icon: str
    required_feature: Capability | None = None


SETTING_SELECT_DESCRIPTIONS: tuple[NarwalSettingSelectEntityDescription, ...] = (
    NarwalSettingSelectEntityDescription(
        key="mode",
        setting_key="mode",
        translation_key="mode",
        setting_options=MODE_OPTIONS,
        default_option=DEFAULT_MODE,
        icon="mdi:robot-vacuum",
    ),
    NarwalSettingSelectEntityDescription(
        key=RUNTIME_SUCTION_KEY,
        setting_key="suction",
        translation_key="suction",
        setting_options=SUCTION_OPTIONS,
        default_option="Normal",
        icon="mdi:fan",
    ),
    NarwalSettingSelectEntityDescription(
        key=RUNTIME_WATER_KEY,
        setting_key="water",
        translation_key="water",
        setting_options=WATER_OPTIONS,
        default_option="Normal",
        icon="mdi:water",
    ),
    NarwalSettingSelectEntityDescription(
        key="scrub",
        setting_key="scrub",
        translation_key="scrub",
        setting_options=SCRUB_OPTIONS,
        default_option="Normal",
        icon="mdi:brush",
    ),
    NarwalSettingSelectEntityDescription(
        key="route",
        setting_key="route",
        translation_key="route",
        setting_options=ROUTE_OPTIONS,
        default_option="Standard",
        icon="mdi:routes",
        required_feature=Capability.OVERLAP_ADJUST,
    ),
    NarwalSettingSelectEntityDescription(
        key="passes",
        setting_key="passes",
        translation_key="passes",
        setting_options=PASSES_OPTIONS,
        default_option="1",
        icon="mdi:counter",
    ),
)


@dataclass(frozen=True, kw_only=True)
class NarwalConfigSelectEntityDescription(SelectEntityDescription):
    """Describes a persistent Narwal configuration select."""

    config_field: SetConfigField
    option_values: tuple[tuple[str, IntEnum], ...]
    icon: str
    required_feature: Capability | None = None


CONFIG_SELECT_DESCRIPTIONS: tuple[NarwalConfigSelectEntityDescription, ...] = (
    NarwalConfigSelectEntityDescription(
        key="robot_language",
        translation_key="robot_language",
        entity_category=EntityCategory.CONFIG,
        config_field=SetConfigField.LANGUAGE,
        option_values=(
            ("Simplified Chinese", Language.SIMPLIFIED_CHINESE),
            ("Traditional Chinese", Language.TRADITIONAL_CHINESE),
            ("English", Language.ENGLISH),
            ("Korean", Language.KOREAN),
            ("Japanese", Language.JAPANESE),
            ("German", Language.GERMAN),
            ("Hebrew", Language.HEBREW),
            ("Italian", Language.ITALIAN),
            ("French", Language.FRENCH),
            ("Spanish", Language.SPANISH),
            ("Russian", Language.RUSSIAN),
            ("Polish", Language.POLISH),
            ("Turkish", Language.TURKISH),
            ("Thai", Language.THAI),
            ("Vietnamese", Language.VIETNAMESE),
        ),
        icon="mdi:translate",
        required_feature=Capability.OPERATE_LANGUAGE,
    ),
    NarwalConfigSelectEntityDescription(
        key="dry_mop_strength",
        translation_key="dry_mop_strength",
        entity_category=EntityCategory.CONFIG,
        config_field=SetConfigField.DRY_MOP_STRENGTH,
        option_values=(
            ("Quiet", DryMopStrength.QUIET),
            ("Strong", DryMopStrength.STRONG),
            ("Smart", DryMopStrength.SMART),
        ),
        icon="mdi:fan-speed-1",
    ),
    NarwalConfigSelectEntityDescription(
        key="mop_wash_frequency",
        translation_key="mop_wash_frequency",
        entity_category=EntityCategory.CONFIG,
        config_field=SetConfigField.CLEAN_MOP_FREQUENCY,
        option_values=(
            ("Efficient", CleanMopFrequency.EFFICIENT),
            ("Normal", CleanMopFrequency.NORMAL),
            ("Deep", CleanMopFrequency.DEEP),
        ),
        icon="mdi:waves-arrow-up",
    ),
    NarwalConfigSelectEntityDescription(
        key="carpet_behavior",
        translation_key="carpet_behavior",
        entity_category=EntityCategory.CONFIG,
        config_field=SetConfigField.CARPET_CLEAN_OPTION,
        option_values=(
            ("Cross carpet", CarpetCleanOption.ACROSS),
            ("Pressurized carpet clean", CarpetCleanOption.PRESSURE),
            ("Ignore carpet", CarpetCleanOption.IGNORE),
            ("Avoid carpet", CarpetCleanOption.AVOID),
        ),
        icon="mdi:rug",
        required_feature=Capability.CARPET_CLEAN_SETTING,
    ),
    NarwalConfigSelectEntityDescription(
        key="station_clean_mode",
        translation_key="station_clean_mode",
        entity_category=EntityCategory.CONFIG,
        config_field=SetConfigField.STATION_CLEAN_MODE,
        option_values=(
            ("Smart", CleanMode.SMART),
            ("Vacuum", CleanMode.SWEEP),
            ("Mop", CleanMode.MOP),
            ("Vacuum and mop", CleanMode.SWEEP_AND_MOP_SYNC),
            ("Vacuum then mop", CleanMode.SWEEP_THEN_MOP),
            ("Composite", CleanMode.COMPOSITE),
        ),
        icon="mdi:home-floor-g",
        required_feature=Capability.STATION_CLEAN_MODE,
    ),
    NarwalConfigSelectEntityDescription(
        key="robot_clean_mode",
        translation_key="robot_clean_mode",
        entity_category=EntityCategory.CONFIG,
        config_field=SetConfigField.ROBOT_CLEAN_MODE,
        option_values=(
            ("Smart", CleanMode.SMART),
            ("Vacuum", CleanMode.SWEEP),
            ("Mop", CleanMode.MOP),
            ("Vacuum and mop", CleanMode.SWEEP_AND_MOP_SYNC),
            ("Vacuum then mop", CleanMode.SWEEP_THEN_MOP),
            ("Composite", CleanMode.COMPOSITE),
        ),
        icon="mdi:robot-vacuum",
        required_feature=Capability.CUSTOMIZE_SMART_CLEAN_PARAM,
    ),
    NarwalConfigSelectEntityDescription(
        key="obstacle_avoidance",
        translation_key="obstacle_avoidance",
        entity_category=EntityCategory.CONFIG,
        config_field=SetConfigField.AVOID_MODE,
        option_values=(
            ("Smart", AvoidMode.SMART),
            ("Safer", AvoidMode.SAFER),
        ),
        icon="mdi:shield-check-outline",
        required_feature=Capability.AVOID_MODE_CONFIG,
    ),
    NarwalConfigSelectEntityDescription(
        key="corner_cleaning",
        translation_key="corner_cleaning",
        entity_category=EntityCategory.CONFIG,
        config_field=SetConfigField.CORNER_CLEAN_MODE,
        option_values=(
            ("Flexible mop", CornerCleanMode.FLEXIBLE_MOP),
            ("Rotate robot", CornerCleanMode.ROTATE_ROBOT),
            ("Disabled", CornerCleanMode.DISABLED),
        ),
        icon="mdi:wall-sconce-flat-outline",
        required_feature=Capability.CORNER_CLEAN,
    ),
    NarwalConfigSelectEntityDescription(
        key="carpet_clean_priority",
        translation_key="carpet_clean_priority",
        entity_category=EntityCategory.CONFIG,
        config_field=SetConfigField.CARPET_CLEAN_PRIORITY_OPTION,
        option_values=(
            ("Default", CarpetCleanPriorityOption.DEFAULT),
            ("Carpet first", CarpetCleanPriorityOption.CARPET_FIRST),
        ),
        icon="mdi:order-bool-ascending-variant",
        required_feature=Capability.CARPET_CLEAN_PRIORITY_CONFIG,
    ),
    NarwalConfigSelectEntityDescription(
        key="carpet_deep_clean",
        translation_key="carpet_deep_clean",
        entity_category=EntityCategory.CONFIG,
        config_field=SetConfigField.CARPET_DEEP_CLEAN_OPTION,
        option_values=(
            ("Disabled", CarpetDeepCleanOption.DISABLE),
            ("Enabled", CarpetDeepCleanOption.ENABLE),
        ),
        icon="mdi:rug",
        required_feature=Capability.CARPET_DEEP_CLEAN,
    ),
    NarwalConfigSelectEntityDescription(
        key="station_light",
        translation_key="station_light",
        entity_category=EntityCategory.CONFIG,
        config_field=SetConfigField.STATION_LIGHT_CTRL_TYPE,
        option_values=(
            ("Off", StationLightCtrlType.OFF),
            ("On", StationLightCtrlType.ON),
        ),
        icon="mdi:lightbulb",
        required_feature=Capability.STATION_LIGHT_CTRL,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NarwalConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Narwal select entities."""
    coordinator = entry.runtime_data

    def discover():
        capabilities = coordinator.client.state.capabilities
        if coordinator.parameterized_clean_enabled:
            for description in SETTING_SELECT_DESCRIPTIONS:
                if (
                    description.required_feature is None
                    or capability_enabled(
                        capabilities,
                        description.required_feature,
                    )
                ):
                    yield (
                        f"setting:{description.key}",
                        lambda description=description: NarwalSettingSelect(
                            coordinator,
                            description,
                        ),
                    )
        snapshot = coordinator.client.state.config_snapshot
        if coordinator.device_profile.config_writes_enabled and snapshot is not None:
            for description in CONFIG_SELECT_DESCRIPTIONS:
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
                    f"config:{description.key}",
                    lambda description=description: NarwalConfigSelect(
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


class NarwalSettingSelect(NarwalEntity, SelectEntity, RestoreEntity):
    """Select entity for Narwal start settings and supported runtime controls."""

    entity_description: NarwalSettingSelectEntityDescription

    def __init__(
        self,
        coordinator: NarwalCoordinator,
        description: NarwalSettingSelectEntityDescription,
    ) -> None:
        """Initialize the select."""
        super().__init__(coordinator)
        self.entity_description = description
        device_id = coordinator.config_entry.data["device_id"]
        self._attr_unique_id = f"{device_id}_{description.key}"
        self._attr_icon = description.icon
        self._attr_options = description.setting_options

    @property
    def _settings(self) -> dict[str, str]:
        """Return coordinator-backed selected options."""
        return self.coordinator.select_options

    async def async_added_to_hass(self) -> None:
        """Restore the last selected option."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state in self.options:
            self._settings[self.entity_description.setting_key] = last_state.state
            return
        self._settings.setdefault(
            self.entity_description.setting_key,
            self._default_option,
        )

    @property
    def _default_option(self) -> str:
        """Return the default option."""
        return self.entity_description.default_option

    @property
    def current_option(self) -> str | None:
        """Return the current selected option."""
        return self._settings.get(
            self.entity_description.setting_key,
            self._default_option,
        )

    @property
    def available(self) -> bool:
        """Return True when the setting can be changed."""
        if not super().available:
            return False

        feature = self.entity_description.required_feature
        state = self.coordinator.data
        if (
            feature is not None
            and state is not None
            and not capability_enabled(state.capabilities, feature)
        ):
            return False

        mode = self._selected_mode
        key = self.entity_description.setting_key
        if key == "water" and mode not in MOP_MODES:
            return False
        if key == "scrub" and mode not in MOP_MODES:
            return False
        if key == "suction" and mode not in VACUUM_MODES:
            return False
        return not (
            key in START_ONLY_SETTINGS and self._is_cleaning_or_paused
        )

    @property
    def _selected_mode(self) -> str:
        """Return the selected clean mode."""
        return self._settings.get("mode", DEFAULT_MODE)

    @property
    def _is_cleaning_or_paused(self) -> bool:
        """Return True while the robot is in an active clean session."""
        state = self.coordinator.data
        if state is None:
            return False
        return (
            state.working_status in ACTIVE_CLEANING_STATUSES
            or state.has_recent_active_working_status
        ) and not state.is_docked and not state.is_returning

    async def async_select_option(self, option: str) -> None:
        """Apply a setting option."""
        if option not in self.options:
            raise HomeAssistantError(f"Unsupported Narwal option: {option}")

        key = self.entity_description.setting_key
        if key == "water" and self._selected_mode not in MOP_MODES:
            raise HomeAssistantError("Water level is not available in vacuum-only mode")
        if key == "scrub" and self._selected_mode not in MOP_MODES:
            raise HomeAssistantError("Scrub level is not available in vacuum-only mode")
        if key == "suction" and self._selected_mode not in VACUUM_MODES:
            raise HomeAssistantError("Suction is not available in mop-only mode")
        if key in START_ONLY_SETTINGS and self._is_cleaning_or_paused:
            raise HomeAssistantError("This Narwal setting cannot be changed mid-clean")
        if key == "suction" and option == "AI" and self._is_cleaning_or_paused:
            raise HomeAssistantError("AI suction cannot be selected mid-clean")

        self._settings[key] = option
        self.async_write_ha_state()


class NarwalConfigSelect(NarwalEntity, SelectEntity):
    """Select backed by one persistent ``config/set`` field."""

    entity_description: NarwalConfigSelectEntityDescription

    def __init__(
        self,
        coordinator: NarwalCoordinator,
        description: NarwalConfigSelectEntityDescription,
    ) -> None:
        """Initialize the persistent select."""
        super().__init__(coordinator)
        self.entity_description = description
        device_id = coordinator.config_entry.data["device_id"]
        self._attr_unique_id = f"{device_id}_{description.key}"
        self._attr_icon = description.icon
        self._attr_options = [option for option, _ in description.option_values]

    @property
    def available(self) -> bool:
        """Return whether the setting remains capability- and snapshot-backed."""
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
    def current_option(self) -> str | None:
        """Return the option represented by the latest read-back snapshot."""
        snapshot = self.coordinator.client.state.config_snapshot
        if snapshot is None:
            return None
        current = snapshot.values.get(self.entity_description.config_field)
        return next(
            (
                option
                for option, value in self.entity_description.option_values
                if value == current
            ),
            None,
        )

    async def async_select_option(self, option: str) -> None:
        """Write one persistent setting and require exact read-back."""
        values = dict(self.entity_description.option_values)
        if option not in values:
            raise HomeAssistantError(f"Unsupported Narwal option: {option}")
        if not self.available:
            raise HomeAssistantError(
                f"Narwal {self.entity_description.key} is not currently available"
            )
        try:
            await self.coordinator.async_set_config(
                self.entity_description.config_field,
                values[option],
            )
        except Exception as err:
            raise HomeAssistantError(
                f"Narwal did not confirm {self.entity_description.key}"
            ) from err
