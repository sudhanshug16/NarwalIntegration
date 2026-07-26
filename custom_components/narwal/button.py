"""Button entities for Narwal station maintenance actions."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import NarwalConfigEntry
from .coordinator import NarwalCoordinator
from .entity import NarwalEntity
from .narwal_client import (
    Capability,
    CommandResponse,
    CommandResult,
    capability_enabled,
)


@dataclass(frozen=True, kw_only=True)
class NarwalButtonEntityDescription(ButtonEntityDescription):
    """Description for a Narwal action button."""

    action: str
    icon: str
    required_feature: Capability | None = None


BUTTON_DESCRIPTIONS: tuple[NarwalButtonEntityDescription, ...] = (
    NarwalButtonEntityDescription(
        key="empty_dustbin",
        translation_key="empty_dustbin",
        action="empty_dustbin",
        icon="mdi:delete-empty",
    ),
    NarwalButtonEntityDescription(
        key="wash_mop",
        translation_key="wash_mop",
        action="wash_mop",
        icon="mdi:waves-arrow-up",
    ),
    NarwalButtonEntityDescription(
        key="dry_mop",
        translation_key="dry_mop",
        action="dry_mop",
        icon="mdi:fan",
    ),
    NarwalButtonEntityDescription(
        key="wash_and_dry_mop",
        translation_key="wash_and_dry_mop",
        action="wash_and_dry_mop",
        icon="mdi:creation",
        entity_registry_enabled_default=False,
    ),
    NarwalButtonEntityDescription(
        key="dry_dust_bin",
        translation_key="dry_dust_bin",
        action="dry_dust_bag",
        icon="mdi:air-filter",
        required_feature=Capability.TEMP_HUMIDITY_DETECTION_FOR_DRY_DUST_BAG,
    ),
    NarwalButtonEntityDescription(
        key="dry_dock_bag",
        translation_key="dry_dock_bag",
        action="dry_station_bag",
        icon="mdi:shield-sun-outline",
        required_feature=Capability.DRY_STATION_BAG,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NarwalConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Narwal button entities."""
    coordinator = entry.runtime_data
    capabilities = coordinator.client.state.capabilities
    allowed_actions = coordinator.device_profile.station_actions
    async_add_entities(
        NarwalActionButton(coordinator, description)
        for description in BUTTON_DESCRIPTIONS
        if description.action in allowed_actions
        if description.required_feature is None
        or capability_enabled(capabilities, description.required_feature)
    )


class NarwalActionButton(NarwalEntity, ButtonEntity):
    """Button entity for a dock/station maintenance command."""

    entity_description: NarwalButtonEntityDescription

    def __init__(
        self,
        coordinator: NarwalCoordinator,
        description: NarwalButtonEntityDescription,
    ) -> None:
        """Initialize the button."""
        super().__init__(coordinator)
        self.entity_description = description
        device_id = coordinator.config_entry.data["device_id"]
        self._attr_unique_id = f"{device_id}_{description.key}"
        self._attr_icon = description.icon

    @property
    def available(self) -> bool:
        """Return True when the robot is docked and can run station actions."""
        if not super().available:
            return False
        if self.entity_description.action not in (
            self.coordinator.device_profile.station_actions
        ):
            return False
        state = self.coordinator.data
        if state is None:
            return False
        feature = self.entity_description.required_feature
        if (
            feature is not None
            and not capability_enabled(state.capabilities, feature)
        ):
            return False
        return state.is_docked

    async def async_press(self) -> None:
        """Run the Narwal station action."""
        client = self.coordinator.client
        if not client.robot_awake:
            await client.wake(timeout=10.0)

        command: Callable[[], Awaitable[CommandResponse]] = getattr(
            client,
            self.entity_description.action,
        )
        response = await command()
        if (
            self.entity_description.action == "wash_mop"
            and response.not_applicable
            and capability_enabled(
                client.state.capabilities,
                Capability.WASH_MOP_BY_ROBOT_STATUS,
            )
        ):
            response = await client.wash_mop_by_robot_status()
        if not response.result_known:
            raise HomeAssistantError(
                "Narwal response contained no action result code; "
                "physical state is unconfirmed"
            )
        if not response.success:
            try:
                result_name = CommandResult(response.result_code).name
            except ValueError:
                result_name = f"UNKNOWN({response.result_code})"
            raise HomeAssistantError(
                f"Narwal {self.entity_description.key} failed: {result_name}"
            )

        if self.entity_description.action in ("dry_mop", "wash_and_dry_mop"):
            await client.get_dry_mop_remain_time()

        self.coordinator.async_set_updated_data(client.state)
