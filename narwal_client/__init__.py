"""Narwal robot vacuum client library — local WebSocket API."""

from .capabilities import (
    Capability,
    CapabilityMap,
    capability_enabled,
    named_capabilities,
)
from .client import NarwalClient, NarwalCommandError, NarwalConnectionError
from .config import ConfigSnapshot, SetConfigField
from .const import (
    CleaningRoute,
    CommandResult,
    FanLevel,
    MopHumidity,
    MopStrengthLevel,
    WorkingStatus,
    WorkMode,
)
from .models import CommandResponse, DeviceInfo, MapData, MapDisplayData, NarwalState, RoomInfo
from .protocol import NarwalHeader, NarwalProperties, build_frame, parse_frame
from .task import CurrentCleanTask

__all__ = [
    "NarwalClient",
    "NarwalCommandError",
    "NarwalConnectionError",
    "NarwalState",
    "Capability",
    "CapabilityMap",
    "capability_enabled",
    "named_capabilities",
    "CommandResponse",
    "CommandResult",
    "CleaningRoute",
    "ConfigSnapshot",
    "CurrentCleanTask",
    "DeviceInfo",
    "FanLevel",
    "MapData",
    "MapDisplayData",
    "MopHumidity",
    "MopStrengthLevel",
    "NarwalHeader",
    "NarwalProperties",
    "RoomInfo",
    "SetConfigField",
    "WorkMode",
    "WorkingStatus",
    "build_frame",
    "parse_frame",
]
