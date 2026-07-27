"""Narwal robot vacuum client library — local WebSocket API."""

from .capabilities import (
    Capability,
    CapabilityMap,
    capability_enabled,
    named_capabilities,
)
from .client import NarwalClient, NarwalCommandError, NarwalConnectionError
from .config import ConfigSnapshot, SetConfigField, SetConfigPatch
from .const import (
    CleaningRoute,
    CommandResult,
    FanLevel,
    ManualControlMode,
    MopHumidity,
    MopStrengthLevel,
    TelecontrolStatus,
    WorkingStatus,
    WorkMode,
)
from .consumables import (
    ConsumableInfoPayload,
    ConsumableMaintainItem,
    ConsumableReplaceItem,
    GetConsumableInfoResponse,
)
from .device_metadata import (
    FirmwareVersionResponse,
    GetCurrentVoiceInfoResponse,
    GetLanguageResponse,
    GetSupportedLanguagesResponse,
    VoiceInfo,
)
from .history import (
    CleanReportSubmit,
    GetCleanTimeLineResponse,
    RobotEventNode,
    TimeLineParam,
    TimeLineStatus,
)
from .map_inventory import (
    CheckMapUpdateInfoResponse,
    GetAllReducedMapsResponse,
    GetEditableMapResponse,
    MapRequestFormat,
    StaticMapPayload,
)
from .models import CommandResponse, DeviceInfo, MapData, MapDisplayData, NarwalState, RoomInfo
from .plan import CleanPlan, CleanPlansResponse, CurrentPlanResponse, PlanCodecError
from .protocol import NarwalHeader, NarwalProperties, build_frame, parse_frame
from .schedule import (
    CleanSchedule,
    CleanScheduleParam,
    Crontab,
    GetCleanSchedulesResponse,
    ScheduleCodecError,
)
from .task import CurrentCleanTask
from .telecontrol import (
    Point,
    PointNaviPlanTraj,
    PoseData,
    TelecontrolCodecError,
)

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
    "CleanPlan",
    "CleanPlansResponse",
    "CleanReportSubmit",
    "CleanSchedule",
    "CleanScheduleParam",
    "ConsumableInfoPayload",
    "ConsumableMaintainItem",
    "ConsumableReplaceItem",
    "ConfigSnapshot",
    "CurrentCleanTask",
    "CurrentPlanResponse",
    "Crontab",
    "DeviceInfo",
    "FanLevel",
    "FirmwareVersionResponse",
    "GetAllReducedMapsResponse",
    "MapData",
    "MapDisplayData",
    "MapRequestFormat",
    "ManualControlMode",
    "MopHumidity",
    "MopStrengthLevel",
    "NarwalHeader",
    "NarwalProperties",
    "GetCleanSchedulesResponse",
    "GetConsumableInfoResponse",
    "GetCurrentVoiceInfoResponse",
    "GetCleanTimeLineResponse",
    "GetEditableMapResponse",
    "GetLanguageResponse",
    "GetSupportedLanguagesResponse",
    "Point",
    "PointNaviPlanTraj",
    "PlanCodecError",
    "PoseData",
    "RoomInfo",
    "RobotEventNode",
    "StaticMapPayload",
    "CheckMapUpdateInfoResponse",
    "ScheduleCodecError",
    "SetConfigField",
    "SetConfigPatch",
    "TelecontrolCodecError",
    "TelecontrolStatus",
    "TimeLineParam",
    "TimeLineStatus",
    "VoiceInfo",
    "WorkMode",
    "WorkingStatus",
    "build_frame",
    "parse_frame",
]
