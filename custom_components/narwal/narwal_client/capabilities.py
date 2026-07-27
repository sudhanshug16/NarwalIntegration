"""Narwal device capability identifiers and response normalization.

The mobile application exposes one feature-list protobuf shared by many robot
families.  A field being known here does not mean a specific robot supports it:
only fields advertised by ``common/get_feature_list`` are enabled.
"""

from __future__ import annotations

from enum import IntEnum
from typing import Any


class Capability(IntEnum):
    """Field numbers in the app's 111-field feature-list message."""

    MULTI_MAP = 1
    MAP_ROTATION = 2
    CARPET_CLEAN_SETTING = 3
    FURNITURE = 4
    CORNER_CLEAN = 5
    PET_MODE = 6
    OVERLAP_ADJUST = 7
    STATION_CLEAN_MODE = 8
    ROOM_FORBIDDEN = 9
    OPERATE_LANGUAGE = 10
    UPLOAD_CONFIGURATION = 11
    CARPET_REGION_MODIFY = 12
    ROTATE_ROOM_TEXTURE = 13
    PUBLISH_UPGRADE_STATUS = 14
    GET_FIRMWARE_VERSION = 15
    MULTI_LAYER_MAP = 16
    SET_CUSTOM_VOICE = 17
    FLOOR_TEXTURE_TATAMI_AND_MARBLE = 18
    CUSTOMIZE_SMART_CLEAN_PARAM = 19
    MAINTAIN_FLOOR = 20
    QUIET_DUST_GATHERING = 21
    PARALLEL_TASK = 22
    SCHEDULED_MAINTAIN_FLOOR_TASK = 23
    AVOID_MODE_CONFIG = 24
    HEAVY_DIRTY_CLEAN = 25
    BUILD_NEW_MAP_AND_CLEAN = 26
    RECALL_ON_MAP_WITHOUT_STATION = 27
    SPEECH_ARGOT = 28
    APP_UPDATE_MAP = 29
    FLOOR_PLAN_EDIT = 30
    MULTI_ZONE_CLEAN = 31
    AUTOMATIC_POWEROFF_WHEN_DISCHARGING = 32
    VALLEY_CHARGING = 33
    DRY_MOP_AUTO_RESUME = 34
    HEAVY_DIRTY_CLEAN_BY_FREQUENCY = 35
    ROBOT_WATER_TANK_PUMP_CONTROL = 36
    BASE_BOARD_CLEAN = 37
    SINGLE_DRY_MOP = 38
    SEG_ROOM_CROSS_OBSTACLES = 39
    SEG_ROOM_CROSS_DOOR = 40
    VIDEO_CRUISE_TASK = 41
    AI_VOICE_SOUND_EFFECT = 42
    MASSIVE_DEEP_CLEAN = 43
    TEMP_HUMIDITY_DETECTION_FOR_DRY_DUST_BAG = 44
    SCHEDULED_TASK_EXECUTE_ONCE = 45
    OBJECT_EXPLORE = 46
    STOP_CLEAN_TASK = 47
    CUSTOM_CLEAN_ORDER_CONFIGURE = 48
    NARSH_VERSION = 49
    MULTIMAP_CUSTOM_CLEAN_ORDER_CONFIGURE = 50
    AI_VOICE_SOUND_EFFECT_FOR_WAITING = 51
    FLEXIBLE_MOP = 52
    BATTERY_HEALTH_INFO = 53
    VIDEO_STREAMING = 54
    CLEAN_TASK_MASSIVE_DIRTY_CLEAN = 55
    PET_ICON_TYPE_SETTING = 56
    DUST_SENSOR = 57
    CHINESE_WAKE_WORD = 58
    PET_HEAT_AREA = 59
    TELECONTROL_HEARTBEAT = 60
    PET_FURNITURE_HEAT_AREA_EXPANSION = 61
    AGORA_VIDEO_STREAMING = 62
    VIDEO_STREAMING_HAS_LDC = 63
    PUMP_TROUBLESHOOTING = 64
    HOT_WATER_WASH = 65
    WASH_MOP_BY_ROBOT_STATUS = 66
    STREAMING_ACTIVE_SHORTCUT = 67
    MAP_CONFIGURATION = 68
    CONSUMABLES_ON_CLOUD = 69
    ROBOT_WATER_TANK = 70
    EDIT_NOT_CURRENT_MAP = 71
    MAP_DISTINCT_CONFIGURATION = 72
    ROBOT_WATER_TANK_AUTO_FILL = 73
    CLEAN_WITH_BUILDING_MAP = 74
    CARPET_CLEAN_PRIORITY_CONFIG = 75
    CARPET_DEEP_CLEAN = 76
    DIRECT_DEV_OPTION_KEY_MAPPING_INTERFACE = 77
    CONFIGURABLE_CYCLE_SCHEDULE_TASK = 78
    TRACK_MOP = 79
    DRY_STATION_BAG = 80
    VISION_OBS_FEATURE = 81
    OBS_AVOID_FEATURE = 82
    SPEECH = 83
    USER_SET_THRESHOLD = 84
    NAVO_INTELLIGENCE_AGENT = 85
    MATERIAL_COLOR_MODIFY = 86
    ISS_MAP_UPDATE = 87
    TEASE_PET = 88
    MULTI_REPLENISH = 89
    MULTI_MAP_20 = 90
    SEARCH_PET = 91
    NO_STATION_MAP_ROOM_CLEAN_PARAM = 92
    NEW_OBS_RECOGNITION = 93
    ALL_THINGS_RECOGNITION = 94
    PRECIOUS_ITEM_GUARD = 95
    BABY_MODE = 96
    BACK_WASH_IN_NO_STATION_MAP = 97
    NAVO_CLEAN = 98
    MAX_AMBIENT_LIGHT_CTRL_TYPE = 99
    STATION_LIGHT_CTRL = 100
    AGORA_VIDEO_STREAMING_TYPE = 101
    NO_CARPET_AREA = 102
    SLOPE = 103
    VIRTUAL_WALL = 104
    DISABLE_SWITCH_MAP_BUTTON = 105
    SUPPORTED_PET_OBS_LABELS = 106
    NEW_OBS_UPLOAD_LOGIC = 107
    DISPLAY_FRAME_INFO = 108
    INDIVIDUAL_CARPET_CONFIG = 109
    CUSTOM_CARPET_SHAPE = 110
    IGNORE_CARPET_WHEN_EXPLORE = 111


type CapabilityValue = int | tuple[int, ...]
type CapabilityMap = dict[int, CapabilityValue]


def capability_name(feature_id: int) -> str:
    """Return a stable snake-case name for a capability field."""
    try:
        return Capability(feature_id).name.lower()
    except ValueError:
        return f"unknown_{feature_id}"


def capability_enabled(
    capabilities: CapabilityMap,
    feature: Capability | int,
) -> bool:
    """Return whether a device explicitly advertises a feature."""
    value = capabilities.get(int(feature), 0)
    if isinstance(value, tuple):
        return bool(value)
    return value != 0


def _normalize_value(value: Any) -> CapabilityValue | None:
    """Normalize blackboxprotobuf scalar/repeated values."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, (bytes, bytearray)):
        try:
            return int(bytes(value).decode("ascii"))
        except (UnicodeDecodeError, ValueError):
            return None
    if isinstance(value, list):
        normalized: list[int] = []
        for item in value:
            item_value = _normalize_value(item)
            if isinstance(item_value, int):
                normalized.append(item_value)
        return tuple(normalized)
    return None


def normalize_feature_response(data: dict[str, Any]) -> CapabilityMap:
    """Normalize a direct feature response or a strict legacy wrapper.

    The current APK defines ``GetFeatureList.Response`` as the feature message
    itself, so the top-level mapping is authoritative.  Some older firmware has
    reportedly wrapped that message as field 2 after a field 1
    ``ServiceResult`` enum.  We unwrap only that exact two-field shape; looking
    for the largest nested dictionary can mistake unrelated nested diagnostics
    for the device's advertised feature set.

    Positive fields outside the APK's currently known 1-111 range are retained
    for diagnostics and forward compatibility.  They remain addressable by
    numeric ID and receive an ``unknown_<id>`` display name.
    """
    feature_data = data
    if len(data) == 2:
        try:
            outer_fields = {int(key): value for key, value in data.items()}
        except (TypeError, ValueError):
            outer_fields = {}

        service_result = outer_fields.get(1)
        nested_features = outer_fields.get(2)
        if (
            len(outer_fields) == 2
            and set(outer_fields) == {1, 2}
            and type(service_result) is int
            and 0 <= service_result <= 32
            and isinstance(nested_features, dict)
        ):
            feature_data = nested_features

    normalized: CapabilityMap = {}
    for raw_key, raw_value in feature_data.items():
        try:
            feature_id = int(raw_key)
        except (TypeError, ValueError):
            continue
        if feature_id < 1:
            continue
        value = _normalize_value(raw_value)
        if value is not None:
            normalized[feature_id] = value
    return normalized


def named_capabilities(capabilities: CapabilityMap) -> dict[str, CapabilityValue]:
    """Return an ordered, human-readable capability mapping."""
    return {
        capability_name(feature_id): capabilities[feature_id]
        for feature_id in sorted(capabilities)
    }
