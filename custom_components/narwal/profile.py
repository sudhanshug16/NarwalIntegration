"""Model and firmware validation profiles for Narwal operations.

Capability bits describe what firmware advertises.  They are necessary but not
sufficient evidence that a write is safe: write paths additionally require a
model/firmware profile backed by a live validation record.
"""

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

# No exact product-key/firmware capture has yet been tied to a completed
# physical validation record. Keep the normal entity surface closed until one
# is recorded; an app-derived schema alone is not a safety claim.
_VALIDATED_PARAMETERIZED_CLEAN: frozenset[tuple[str, str]] = frozenset()

# The APK and our AX15 read-only probe used this exact firmware. Opt-in permits
# only parameterized room-clean validation; it does not authorize station,
# config, pump, firmware, map-mutation, media, or telecontrol writes.
_EXPERIMENTAL_X10_CLEAN_FIRMWARE = "v01.03.10.03"


@dataclass(frozen=True, slots=True)
class DeviceProfile:
    """Resolved identity, capabilities, and validation state."""

    product_key: str
    firmware_version: str
    display_model: str
    hardware_model: str
    capabilities: CapabilityMap
    experimental_cleaning: bool = False

    @property
    def parameterized_clean_validated(self) -> bool:
        """Return whether CleanTask writes were live-validated."""
        return (
            self.product_key,
            self.firmware_version,
        ) in _VALIDATED_PARAMETERIZED_CLEAN

    @property
    def parameterized_clean_experimental(self) -> bool:
        """Return whether this exact AX15 probe profile was explicitly opted in."""
        return (
            self.experimental_cleaning
            and self.product_key == FREO_X10_PRO_PRODUCT_KEY
            and self.firmware_version == _EXPERIMENTAL_X10_CLEAN_FIRMWARE
        )

    @property
    def parameterized_clean_enabled(self) -> bool:
        """Gate normal CleanTask entities to physically validated profiles."""
        return capability_enabled(
            self.capabilities,
            Capability.MULTI_ZONE_CLEAN,
        ) and self.parameterized_clean_validated

    @property
    def parameterized_clean_validation_enabled(self) -> bool:
        """Allow the one-shot AX15 validation service after explicit opt-in."""
        return capability_enabled(
            self.capabilities,
            Capability.MULTI_ZONE_CLEAN,
        ) and self.parameterized_clean_experimental

    @property
    def station_actions(self) -> frozenset[str]:
        """Return station actions validated for this exact profile.

        No station write has yet passed the required X10/Flow 2 physical
        validation record, so these entities remain absent.
        """
        return frozenset()

    @property
    def config_writes_enabled(self) -> bool:
        """Config writes stay read-only until read/write/read-back validation."""
        return False


def profile_for_client(
    client: Any,
    *,
    experimental_cleaning: bool = False,
) -> DeviceProfile:
    """Resolve a fail-closed profile from live client identity and features."""
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
        experimental_cleaning=experimental_cleaning,
    )


__all__ = [
    "DeviceProfile",
    "FREO_X10_PRO_PRODUCT_KEY",
    "profile_for_client",
]
