"""Model profiles for Narwal operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .narwal_client import Capability, CapabilityMap, capability_enabled

FREO_X10_PRO_PRODUCT_KEY = "CNbforyZWI"

_PRODUCT_MODELS: dict[str, tuple[str, str]] = {
    "QoEsI5qYXO": ("Narwal Flow", "AX12"),
    "QxMSPG6VSO": ("Narwal Flow 2", "Flow 2"),
    "iSuVlI1If2": ("Narwal Flow 2", "Flow 2"),
    "DrzDKQ0MU8": ("Narwal Freo Z10 Ultra", "CX4"),
    FREO_X10_PRO_PRODUCT_KEY: ("Narwal Freo X10 Pro", "AX15"),
    "3rIGshGNAj": ("Narwal Freo X Plus", "BX1"),
}


@dataclass(frozen=True, slots=True)
class DeviceProfile:
    """Resolved identity and advertised capabilities."""

    product_key: str
    firmware_version: str
    display_model: str
    hardware_model: str
    capabilities: CapabilityMap

    @property
    def parameterized_clean_enabled(self) -> bool:
        """Expose full clean parameters on capable Freo X10 Pro robots."""
        return self.product_key == FREO_X10_PRO_PRODUCT_KEY and capability_enabled(
            self.capabilities,
            Capability.MULTI_ZONE_CLEAN,
        )

    @property
    def telecontrol_enabled(self) -> bool:
        """Expose bounded official-app telecontrol on capable AX15 robots."""
        return self.product_key == FREO_X10_PRO_PRODUCT_KEY and capability_enabled(
            self.capabilities,
            Capability.TELECONTROL_HEARTBEAT,
        )

    @property
    def station_actions(self) -> frozenset[str]:
        """Return normal dock actions exposed for Freo X10 Pro."""
        if self.product_key != FREO_X10_PRO_PRODUCT_KEY:
            return frozenset()
        return frozenset(
            {
                "empty_dustbin",
                "wash_mop",
                "dry_mop",
                "wash_and_dry_mop",
                "dry_dust_bag",
                "dry_station_bag",
            }
        )

    @property
    def config_writes_enabled(self) -> bool:
        """Expose verified config writes on capable AX15 robots."""
        return self.product_key == FREO_X10_PRO_PRODUCT_KEY and capability_enabled(
            self.capabilities,
            Capability.UPLOAD_CONFIGURATION,
        )

    @property
    def clean_plan_inventory_enabled(self) -> bool:
        """Return whether saved/current clean-plan reads match the AX15 surface."""
        return self.product_key == FREO_X10_PRO_PRODUCT_KEY and capability_enabled(
            self.capabilities,
            Capability.MULTIMAP_CUSTOM_CLEAN_ORDER_CONFIGURE,
        )

    @property
    def schedule_inventory_enabled(self) -> bool:
        """Return whether this AX15 advertises either modern schedule feature."""
        return self.product_key == FREO_X10_PRO_PRODUCT_KEY and (
            capability_enabled(
                self.capabilities,
                Capability.SCHEDULED_TASK_EXECUTE_ONCE,
            )
            or capability_enabled(
                self.capabilities,
                Capability.CONFIGURABLE_CYCLE_SCHEDULE_TASK,
            )
        )

    @property
    def saved_map_inventory_enabled(self) -> bool:
        """Return whether the device advertises multiple saved maps."""
        return self.product_key == FREO_X10_PRO_PRODUCT_KEY and capability_enabled(
            self.capabilities,
            Capability.MULTI_MAP,
        )

    @property
    def editable_map_inventory_enabled(self) -> bool:
        """Return whether the device advertises editable floor-plan metadata."""
        return self.product_key == FREO_X10_PRO_PRODUCT_KEY and capability_enabled(
            self.capabilities,
            Capability.FLOOR_PLAN_EDIT,
        )

    @property
    def map_update_inventory_enabled(self) -> bool:
        """Return whether supplementary map-update reads are advertised."""
        return self.product_key == FREO_X10_PRO_PRODUCT_KEY and capability_enabled(
            self.capabilities,
            Capability.APP_UPDATE_MAP,
        )

    @property
    def consumable_inventory_enabled(self) -> bool:
        """Return whether the AX15 advertises its consumables surface."""
        return self.product_key == FREO_X10_PRO_PRODUCT_KEY and capability_enabled(
            self.capabilities,
            Capability.CONSUMABLES_ON_CLOUD,
        )

    @property
    def firmware_inventory_enabled(self) -> bool:
        """Return whether the AX15 advertises component firmware reads."""
        return self.product_key == FREO_X10_PRO_PRODUCT_KEY and capability_enabled(
            self.capabilities,
            Capability.GET_FIRMWARE_VERSION,
        )

    @property
    def language_inventory_enabled(self) -> bool:
        """Return whether the AX15 advertises language metadata."""
        return self.product_key == FREO_X10_PRO_PRODUCT_KEY and capability_enabled(
            self.capabilities,
            Capability.OPERATE_LANGUAGE,
        )

    @property
    def voice_inventory_enabled(self) -> bool:
        """Return whether the AX15 advertises official voice-package metadata."""
        return self.product_key == FREO_X10_PRO_PRODUCT_KEY and capability_enabled(
            self.capabilities,
            Capability.SET_CUSTOM_VOICE,
        )

    @property
    def history_inventory_enabled(self) -> bool:
        """Return whether the APK-proven local timeline applies to this model."""
        return self.product_key == FREO_X10_PRO_PRODUCT_KEY


def profile_for_client(
    client: Any,
) -> DeviceProfile:
    """Resolve a profile from live client identity and features."""
    state = client.state
    info = state.device_info
    product_key = ""
    firmware_version = ""
    if info is not None:
        product_key = info.product_key or ""
        firmware_version = info.firmware_version or ""
    if not product_key:
        product_key = str(getattr(client, "topic_prefix", "")).lstrip("/")
    if not firmware_version:
        firmware_version = state.firmware_version or ""

    display_model, hardware_model = _PRODUCT_MODELS.get(
        product_key,
        ("Narwal robot vacuum", product_key or "Unknown"),
    )
    return DeviceProfile(
        product_key=product_key,
        firmware_version=firmware_version,
        display_model=display_model,
        hardware_model=hardware_model,
        capabilities=state.capabilities,
    )


__all__ = [
    "DeviceProfile",
    "FREO_X10_PRO_PRODUCT_KEY",
    "profile_for_client",
]
