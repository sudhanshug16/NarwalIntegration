"""Conservative codecs for a safe subset of Narwal configuration.

Set operations encode and decode the protobuf body only. They deliberately
support single-setting patches so callers cannot accidentally serialize default
values for settings they did not intend to change.

Get operations consume blackboxprotobuf-decoded mappings. Get response numbers
are mapped explicitly to their corresponding setter identities because the
request and response schemas differ.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import IntEnum
from types import MappingProxyType
from typing import Any


class ConfigCodecError(ValueError):
    """Raised for invalid, unsupported, or malformed configuration patches."""


class SetConfigField(IntEnum):
    """Supported ``SetConfig.Request`` field numbers."""

    VOLUME_PERCENTAGE = 1
    LANGUAGE = 2
    CHILD_LOCK_ENABLED = 8
    CLEAN_CARPET_ENABLED = 9
    SMART_CLEAN_DETECTION_ENABLED = 12
    DRY_MOP_STRENGTH = 13
    CLEAN_MOP_FREQUENCY = 14
    CARPET_CLEAN_OPTION = 15
    SWITCH_BACK_TO_MAIN_MAP_AFTER_TEMP_MAP_CLEAN = 20
    STATION_CLEAN_MODE = 21
    PET_MODE = 22
    SMART_DEEP_CLEAN_ENABLED = 23
    MOISTURE_PROOF_PAD_PROTECT_ENABLED = 26
    DUST_GATHERING_ENABLED = 27
    SMART_DUST_GATHERING_ENABLED = 28
    QUIET_DUST_GATHERING_ENABLED = 30
    DRY_ROBOT_BAG_ENABLED = 31
    HOT_WATER_WASH_ENABLED = 32
    MASSIVE_DIRTY_DEEP_CLEAN_ENABLE = 33
    AVOID_MODE = 34
    ROBOT_CLEAN_MODE = 35
    SPEECH_CONTROL_ENABLED = 36
    AUTOMATIC_POWEROFF_WHEN_DISCHARGING = 37
    AI_VOICE_SOUND_EFFECT_ENABLED = 39
    AI_VOICE_SOUND_EFFECT_FOR_WAITING_ENABLED = 40
    CORNER_CLEAN_MODE = 41
    CARPET_CLEAN_PRIORITY_OPTION = 45
    CARPET_DEEP_CLEAN_OPTION = 46
    ALL_THINGS_RECOGNITION_ENABLED = 47
    PRECIOUS_ITEM_GUARD_ENABLED = 48
    STATION_LIGHT_CTRL_TYPE = 49


class GetConfigField(IntEnum):
    """Supported ``GetConfig.Response.Config`` field numbers."""

    VOLUME_PERCENTAGE = 1
    LANGUAGE = 2
    CHILD_LOCK_ENABLED = 7
    CLEAN_CARPET_ENABLED = 8
    SMART_CLEAN_DETECTION_ENABLED = 11
    DRY_MOP_STRENGTH = 12
    CLEAN_MOP_FREQUENCY = 13
    CARPET_CLEAN_OPTION = 15
    SWITCH_BACK_TO_MAIN_MAP_AFTER_TEMP_MAP_CLEAN = 20
    STATION_CLEAN_MODE = 21
    PET_MODE = 22
    SMART_DEEP_CLEAN_ENABLED = 23
    MOISTURE_PROOF_PAD_PROTECT_ENABLED = 26
    DUST_GATHERING_ENABLED = 27
    SMART_DUST_GATHERING_ENABLED = 28
    QUIET_DUST_GATHERING_ENABLED = 30
    DRY_ROBOT_BAG_ENABLED = 31
    HOT_WATER_WASH_ENABLED = 32
    MASSIVE_DIRTY_DEEP_CLEAN_ENABLE = 33
    AVOID_MODE = 34
    ROBOT_CLEAN_MODE = 35
    SPEECH_CONTROL_ENABLED = 36
    AUTOMATIC_POWEROFF_WHEN_DISCHARGING = 37
    AI_VOICE_SOUND_EFFECT_ENABLED = 39
    AI_VOICE_SOUND_EFFECT_FOR_WAITING_ENABLED = 40
    CORNER_CLEAN_MODE = 41
    CARPET_CLEAN_PRIORITY_OPTION = 46
    CARPET_DEEP_CLEAN_OPTION = 47
    ALL_THINGS_RECOGNITION_ENABLED = 49
    PRECIOUS_ITEM_GUARD_ENABLED = 50
    STATION_LIGHT_CTRL_TYPE = 51


class AvoidMode(IntEnum):
    """Obstacle-avoidance configuration values."""

    UNSPECIFIED = 0
    SMART = 1
    SAFER = 2
    OFF = 3


class Language(IntEnum):
    """Robot voice-language values recovered from the APK."""

    UNSPECIFIED = 0
    SIMPLIFIED_CHINESE = 1
    TRADITIONAL_CHINESE = 2
    ENGLISH = 3
    KOREAN = 4
    JAPANESE = 5
    GERMAN = 6
    HEBREW = 7
    ITALIAN = 8
    FRENCH = 9
    SPANISH = 10
    RUSSIAN = 11
    POLISH = 12
    TURKISH = 13
    THAI = 14
    VIETNAMESE = 15


class DryMopStrength(IntEnum):
    """Mop-drying strength values."""

    UNSPECIFIED = 0
    QUIET = 1
    STRONG = 2
    SMART = 3


class CleanMopFrequency(IntEnum):
    """Mop-cleaning frequency values."""

    UNSPECIFIED = 0
    EFFICIENT = 1
    NORMAL = 2
    DEEP = 3


class CarpetCleanOption(IntEnum):
    """Carpet behavior values."""

    UNSPECIFIED = 0
    ACROSS = 1
    PRESSURE = 2
    IGNORE = 3
    AVOID = 4


class CleanMode(IntEnum):
    """Robot cleaning-mode configuration values."""

    UNSPECIFIED = 0
    SMART = 1
    SWEEP = 2
    MOP = 3
    SWEEP_AND_MOP_SYNC = 4
    SWEEP_THEN_MOP = 5
    COMPOSITE = 6


class CornerCleanMode(IntEnum):
    """Corner-cleaning configuration values."""

    UNSPECIFIED = 0
    FLEXIBLE_MOP = 1
    ROTATE_ROBOT = 2
    DISABLED = 3


class CarpetCleanPriorityOption(IntEnum):
    """Carpet-cleaning priority values."""

    UNSPECIFIED = 0
    DEFAULT = 1
    CARPET_FIRST = 2


class CarpetDeepCleanOption(IntEnum):
    """Carpet deep-clean values."""

    UNSPECIFIED = 0
    DISABLE = 1
    ENABLE = 2


class StationLightCtrlType(IntEnum):
    """Station-light configuration values."""

    UNSPECIFIED = 0
    OFF = 1
    ON = 2


@dataclass(frozen=True, slots=True)
class SetConfigFieldSpec:
    """Schema metadata for one supported setter field."""

    protobuf_name: str
    value_type: type[int] | type[bool] | type[IntEnum]
    minimum: int
    maximum: int


_FIELD_SPECS = {
    SetConfigField.VOLUME_PERCENTAGE: SetConfigFieldSpec(
        "volumePercentage", int, 0, 100
    ),
    SetConfigField.LANGUAGE: SetConfigFieldSpec("language", Language, 1, 15),
    SetConfigField.CHILD_LOCK_ENABLED: SetConfigFieldSpec(
        "childLockEnabled", bool, 0, 1
    ),
    SetConfigField.CLEAN_CARPET_ENABLED: SetConfigFieldSpec(
        "cleanCarpetEnabled", bool, 0, 1
    ),
    SetConfigField.SMART_CLEAN_DETECTION_ENABLED: SetConfigFieldSpec(
        "smartCleanDetectionEnabled", bool, 0, 1
    ),
    SetConfigField.DRY_MOP_STRENGTH: SetConfigFieldSpec(
        "dryMopStrength", DryMopStrength, 1, 3
    ),
    SetConfigField.CLEAN_MOP_FREQUENCY: SetConfigFieldSpec(
        "cleanMopFreq", CleanMopFrequency, 1, 3
    ),
    SetConfigField.CARPET_CLEAN_OPTION: SetConfigFieldSpec(
        "carpetCleanOption", CarpetCleanOption, 1, 4
    ),
    SetConfigField.SWITCH_BACK_TO_MAIN_MAP_AFTER_TEMP_MAP_CLEAN: SetConfigFieldSpec(
        "switchBackToMainMapAfterTempMapClean", bool, 0, 1
    ),
    SetConfigField.STATION_CLEAN_MODE: SetConfigFieldSpec(
        "stationCleanMode", CleanMode, 1, 6
    ),
    SetConfigField.PET_MODE: SetConfigFieldSpec("petMode", bool, 0, 1),
    SetConfigField.SMART_DEEP_CLEAN_ENABLED: SetConfigFieldSpec(
        "smartDeepCleanEnabled", bool, 0, 1
    ),
    SetConfigField.MOISTURE_PROOF_PAD_PROTECT_ENABLED: SetConfigFieldSpec(
        "moistureProofPadProtectEnabled", bool, 0, 1
    ),
    SetConfigField.DUST_GATHERING_ENABLED: SetConfigFieldSpec(
        "dustGatheringEnabled", bool, 0, 1
    ),
    SetConfigField.SMART_DUST_GATHERING_ENABLED: SetConfigFieldSpec(
        "smartDustGatheringEnabled", bool, 0, 1
    ),
    SetConfigField.QUIET_DUST_GATHERING_ENABLED: SetConfigFieldSpec(
        "quietDustGatheringEnabled", bool, 0, 1
    ),
    SetConfigField.DRY_ROBOT_BAG_ENABLED: SetConfigFieldSpec(
        "dryRobotBagEnabled", bool, 0, 1
    ),
    SetConfigField.HOT_WATER_WASH_ENABLED: SetConfigFieldSpec(
        "hotWaterWashEnabled", bool, 0, 1
    ),
    SetConfigField.MASSIVE_DIRTY_DEEP_CLEAN_ENABLE: SetConfigFieldSpec(
        "massiveDirtyDeepCleanEnable", bool, 0, 1
    ),
    SetConfigField.AVOID_MODE: SetConfigFieldSpec("avoidMode", AvoidMode, 1, 3),
    SetConfigField.ROBOT_CLEAN_MODE: SetConfigFieldSpec(
        "robotCleanMode", CleanMode, 1, 6
    ),
    SetConfigField.SPEECH_CONTROL_ENABLED: SetConfigFieldSpec(
        "speechControlEnabled", bool, 0, 1
    ),
    SetConfigField.AUTOMATIC_POWEROFF_WHEN_DISCHARGING: SetConfigFieldSpec(
        "automaticPoweroffWhenDischarging", bool, 0, 1
    ),
    SetConfigField.AI_VOICE_SOUND_EFFECT_ENABLED: SetConfigFieldSpec(
        "aiVoiceSoundEffectEnabled", bool, 0, 1
    ),
    SetConfigField.AI_VOICE_SOUND_EFFECT_FOR_WAITING_ENABLED: SetConfigFieldSpec(
        "aiVoiceSoundEffectForWaitingEnabled", bool, 0, 1
    ),
    SetConfigField.CORNER_CLEAN_MODE: SetConfigFieldSpec(
        "cornerCleanMode", CornerCleanMode, 1, 3
    ),
    SetConfigField.CARPET_CLEAN_PRIORITY_OPTION: SetConfigFieldSpec(
        "carpetCleanPriorityOption", CarpetCleanPriorityOption, 1, 2
    ),
    SetConfigField.CARPET_DEEP_CLEAN_OPTION: SetConfigFieldSpec(
        "carpetDeepCleanOption", CarpetDeepCleanOption, 1, 2
    ),
    SetConfigField.ALL_THINGS_RECOGNITION_ENABLED: SetConfigFieldSpec(
        "allThingsRecognitionEnabled", bool, 0, 1
    ),
    SetConfigField.PRECIOUS_ITEM_GUARD_ENABLED: SetConfigFieldSpec(
        "preciousItemGuardEnabled", bool, 0, 1
    ),
    SetConfigField.STATION_LIGHT_CTRL_TYPE: SetConfigFieldSpec(
        "stationLightCtrlType", StationLightCtrlType, 1, 2
    ),
}

SET_CONFIG_FIELD_SPECS: Mapping[SetConfigField, SetConfigFieldSpec] = MappingProxyType(
    _FIELD_SPECS
)

_GET_TO_SET_FIELDS = {
    GetConfigField.VOLUME_PERCENTAGE: SetConfigField.VOLUME_PERCENTAGE,
    GetConfigField.LANGUAGE: SetConfigField.LANGUAGE,
    GetConfigField.CHILD_LOCK_ENABLED: SetConfigField.CHILD_LOCK_ENABLED,
    GetConfigField.CLEAN_CARPET_ENABLED: SetConfigField.CLEAN_CARPET_ENABLED,
    GetConfigField.SMART_CLEAN_DETECTION_ENABLED: (
        SetConfigField.SMART_CLEAN_DETECTION_ENABLED
    ),
    GetConfigField.DRY_MOP_STRENGTH: SetConfigField.DRY_MOP_STRENGTH,
    GetConfigField.CLEAN_MOP_FREQUENCY: SetConfigField.CLEAN_MOP_FREQUENCY,
    GetConfigField.CARPET_CLEAN_OPTION: SetConfigField.CARPET_CLEAN_OPTION,
    GetConfigField.SWITCH_BACK_TO_MAIN_MAP_AFTER_TEMP_MAP_CLEAN: (
        SetConfigField.SWITCH_BACK_TO_MAIN_MAP_AFTER_TEMP_MAP_CLEAN
    ),
    GetConfigField.STATION_CLEAN_MODE: SetConfigField.STATION_CLEAN_MODE,
    GetConfigField.PET_MODE: SetConfigField.PET_MODE,
    GetConfigField.SMART_DEEP_CLEAN_ENABLED: SetConfigField.SMART_DEEP_CLEAN_ENABLED,
    GetConfigField.MOISTURE_PROOF_PAD_PROTECT_ENABLED: (
        SetConfigField.MOISTURE_PROOF_PAD_PROTECT_ENABLED
    ),
    GetConfigField.DUST_GATHERING_ENABLED: SetConfigField.DUST_GATHERING_ENABLED,
    GetConfigField.SMART_DUST_GATHERING_ENABLED: (
        SetConfigField.SMART_DUST_GATHERING_ENABLED
    ),
    GetConfigField.QUIET_DUST_GATHERING_ENABLED: (
        SetConfigField.QUIET_DUST_GATHERING_ENABLED
    ),
    GetConfigField.DRY_ROBOT_BAG_ENABLED: SetConfigField.DRY_ROBOT_BAG_ENABLED,
    GetConfigField.HOT_WATER_WASH_ENABLED: SetConfigField.HOT_WATER_WASH_ENABLED,
    GetConfigField.MASSIVE_DIRTY_DEEP_CLEAN_ENABLE: (
        SetConfigField.MASSIVE_DIRTY_DEEP_CLEAN_ENABLE
    ),
    GetConfigField.AVOID_MODE: SetConfigField.AVOID_MODE,
    GetConfigField.ROBOT_CLEAN_MODE: SetConfigField.ROBOT_CLEAN_MODE,
    GetConfigField.SPEECH_CONTROL_ENABLED: SetConfigField.SPEECH_CONTROL_ENABLED,
    GetConfigField.AUTOMATIC_POWEROFF_WHEN_DISCHARGING: (
        SetConfigField.AUTOMATIC_POWEROFF_WHEN_DISCHARGING
    ),
    GetConfigField.AI_VOICE_SOUND_EFFECT_ENABLED: (
        SetConfigField.AI_VOICE_SOUND_EFFECT_ENABLED
    ),
    GetConfigField.AI_VOICE_SOUND_EFFECT_FOR_WAITING_ENABLED: (
        SetConfigField.AI_VOICE_SOUND_EFFECT_FOR_WAITING_ENABLED
    ),
    GetConfigField.CORNER_CLEAN_MODE: SetConfigField.CORNER_CLEAN_MODE,
    GetConfigField.CARPET_CLEAN_PRIORITY_OPTION: (
        SetConfigField.CARPET_CLEAN_PRIORITY_OPTION
    ),
    GetConfigField.CARPET_DEEP_CLEAN_OPTION: SetConfigField.CARPET_DEEP_CLEAN_OPTION,
    GetConfigField.ALL_THINGS_RECOGNITION_ENABLED: (
        SetConfigField.ALL_THINGS_RECOGNITION_ENABLED
    ),
    GetConfigField.PRECIOUS_ITEM_GUARD_ENABLED: (
        SetConfigField.PRECIOUS_ITEM_GUARD_ENABLED
    ),
    GetConfigField.STATION_LIGHT_CTRL_TYPE: SetConfigField.STATION_LIGHT_CTRL_TYPE,
}

GET_CONFIG_FIELD_TO_SET_CONFIG_FIELD: Mapping[GetConfigField, SetConfigField] = (
    MappingProxyType(_GET_TO_SET_FIELDS)
)


@dataclass(frozen=True, slots=True)
class SetConfigPatch:
    """A validated patch that changes exactly one robot setting."""

    field: SetConfigField
    value: bool | int | IntEnum

    def __post_init__(self) -> None:
        _validate_value(self.field, self.value)

    @property
    def raw_value(self) -> int:
        """Return the validated integer value used on the protobuf wire."""
        return int(self.value)


@dataclass(frozen=True, slots=True)
class ConfigSnapshot:
    """Immutable typed and raw values from ``GetConfig.Response.Config``.

    ``values`` uses setter identities so a caller can construct a new,
    separately validated single-setting patch without ever reusing a response
    field number. ``raw_fields`` preserves every normalized response field,
    including unsupported and malformed values. ``service_result`` is kept
    separate when the input was a response wrapper.
    """

    values: Mapping[SetConfigField, bool | int | IntEnum]
    raw_fields: Mapping[int, object]
    service_result: object | None = None

    def __post_init__(self) -> None:
        typed_values: dict[SetConfigField, bool | int | IntEnum] = {}
        for config_field, value in self.values.items():
            _validate_value(config_field, value)
            typed_values[config_field] = value

        frozen_raw_fields: dict[int, object] = {}
        for response_field, raw_value in self.raw_fields.items():
            if type(response_field) is not int or response_field < 1:
                raise ConfigCodecError(
                    "raw GetConfig response field numbers must be positive integers"
                )
            frozen_raw_fields[response_field] = _freeze_raw_value(raw_value)

        object.__setattr__(self, "values", MappingProxyType(typed_values))
        object.__setattr__(self, "raw_fields", MappingProxyType(frozen_raw_fields))
        object.__setattr__(
            self,
            "service_result",
            _freeze_raw_value(self.service_result),
        )


def _validate_value(field: SetConfigField, value: bool | int | IntEnum) -> None:
    if type(field) is not SetConfigField:
        raise ConfigCodecError("field must be a SetConfigField member")

    spec = SET_CONFIG_FIELD_SPECS[field]
    if spec.value_type is bool:
        if type(value) is not bool:
            raise ConfigCodecError(
                f"{spec.protobuf_name} requires bool, got {type(value).__name__}"
            )
    elif spec.value_type is int:
        if type(value) is not int:
            raise ConfigCodecError(f"{spec.protobuf_name} requires int, got {type(value).__name__}")
    elif type(value) is not spec.value_type:
        raise ConfigCodecError(
            f"{spec.protobuf_name} requires {spec.value_type.__name__}, "
            f"got {type(value).__name__}"
        )

    raw_value = int(value)
    if not spec.minimum <= raw_value <= spec.maximum:
        raise ConfigCodecError(
            f"{spec.protobuf_name} must be between {spec.minimum} and "
            f"{spec.maximum}, got {raw_value}"
        )


def _freeze_raw_value(value: object) -> object:
    """Recursively freeze blackboxprotobuf-compatible values."""
    if isinstance(value, Mapping):
        return MappingProxyType(
            {key: _freeze_raw_value(nested) for key, nested in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_raw_value(item) for item in value)
    if isinstance(value, (bytearray, memoryview)):
        return bytes(value)
    if isinstance(value, set):
        return frozenset(_freeze_raw_value(item) for item in value)
    return value


def _normalize_decoded_fields(
    data: Mapping[object, object],
    *,
    context: str,
) -> dict[int, object]:
    """Normalize integer and canonical decimal blackboxprotobuf field keys."""
    normalized: dict[int, object] = {}
    for raw_field, value in data.items():
        if type(raw_field) is int:
            field_number = raw_field
        elif type(raw_field) is str:
            try:
                field_number = int(raw_field)
            except ValueError as exc:
                raise ConfigCodecError(
                    f"{context} field key {raw_field!r} is not numeric"
                ) from exc
            if str(field_number) != raw_field:
                raise ConfigCodecError(
                    f"{context} field key {raw_field!r} is not canonical"
                )
        else:
            raise ConfigCodecError(
                f"{context} field keys must be int or canonical decimal str"
            )

        if field_number < 1:
            raise ConfigCodecError(
                f"{context} field number {field_number} must be positive"
            )
        if field_number in normalized:
            raise ConfigCodecError(
                f"{context} contains duplicate field number {field_number}"
            )
        normalized[field_number] = value
    return normalized


def _decode_snapshot_value(
    field: SetConfigField,
    raw_value: object,
) -> bool | int | IntEnum | None:
    """Return a typed safe value, or ``None`` when raw data is not trustworthy."""
    spec = SET_CONFIG_FIELD_SPECS[field]
    if spec.value_type is bool:
        if type(raw_value) is bool:
            return raw_value
        if type(raw_value) is int and raw_value in (0, 1):
            return bool(raw_value)
        return None

    if type(raw_value) is not int:
        return None
    if not spec.minimum <= raw_value <= spec.maximum:
        return None
    if spec.value_type is int:
        return raw_value

    try:
        return spec.value_type(raw_value)
    except ValueError:
        return None


def _encode_varint(value: int) -> bytes:
    if value < 0:
        raise ConfigCodecError("protobuf varints cannot encode negative values")

    encoded = bytearray()
    while value > 0x7F:
        encoded.append((value & 0x7F) | 0x80)
        value >>= 7
    encoded.append(value)
    return bytes(encoded)


def _decode_varint(data: bytes, offset: int) -> tuple[int, int]:
    start = offset
    value = 0

    for byte_index in range(10):
        if offset >= len(data):
            raise ConfigCodecError("truncated protobuf varint")

        current = data[offset]
        offset += 1

        if byte_index == 9 and current > 1:
            raise ConfigCodecError("protobuf varint exceeds uint64")

        value |= (current & 0x7F) << (byte_index * 7)
        if current < 0x80:
            if data[start:offset] != _encode_varint(value):
                raise ConfigCodecError("non-canonical protobuf varint")
            return value, offset

    raise ConfigCodecError("protobuf varint is too long")


def encode_set_config_patch(patch: SetConfigPatch) -> bytes:
    """Encode one validated ``SetConfig.Request`` field deterministically."""
    if type(patch) is not SetConfigPatch:
        raise ConfigCodecError("patch must be a SetConfigPatch")

    field_key = (int(patch.field) << 3) | 0
    return _encode_varint(field_key) + _encode_varint(patch.raw_value)


def decode_set_config_patch(payload: bytes | bytearray | memoryview) -> SetConfigPatch:
    """Decode one supported canonical ``SetConfig.Request`` field.

    Unknown fields, non-varint wire types, duplicate fields, and multi-setting
    messages are rejected rather than partially decoded.
    """
    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise ConfigCodecError("payload must be bytes-like")

    data = bytes(payload)
    if not data:
        raise ConfigCodecError("SetConfig patch payload cannot be empty")

    field_key, offset = _decode_varint(data, 0)
    field_number = field_key >> 3
    wire_type = field_key & 0x07

    if field_number == 0:
        raise ConfigCodecError("protobuf field number 0 is invalid")
    if wire_type != 0:
        raise ConfigCodecError(
            f"unsupported wire type {wire_type} for SetConfig field {field_number}"
        )

    try:
        field = SetConfigField(field_number)
    except ValueError as exc:
        raise ConfigCodecError(f"unsupported SetConfig field {field_number}") from exc

    raw_value, offset = _decode_varint(data, offset)
    if offset != len(data):
        raise ConfigCodecError("SetConfig patch must contain exactly one field")

    spec = SET_CONFIG_FIELD_SPECS[field]
    if spec.value_type is bool:
        if raw_value not in (0, 1):
            raise ConfigCodecError(
                f"{spec.protobuf_name} Boolean wire value must be 0 or 1, got {raw_value}"
            )
        value: bool | int | IntEnum = bool(raw_value)
    elif spec.value_type is int:
        value = raw_value
    else:
        try:
            value = spec.value_type(raw_value)
        except ValueError as exc:
            raise ConfigCodecError(
                f"unknown {spec.value_type.__name__} value {raw_value}"
            ) from exc

    return SetConfigPatch(field=field, value=value)


def decode_get_config_response(data: Mapping[Any, Any]) -> ConfigSnapshot:
    """Decode a direct config mapping or a ``GetConfig.Response`` mapping.

    The response wrapper is identified only by a nested field 2. In the direct
    ``Config`` message, field 2 is the scalar ``Language`` enum, so this does
    not misclassify a valid direct config mapping. ServiceResult field 1 is
    never inspected as configuration.

    Unsupported fields and invalid values remain in ``raw_fields`` and are
    omitted from ``values`` rather than being coerced to a truthy or enum value.
    """
    if not isinstance(data, Mapping):
        raise ConfigCodecError("GetConfig response must be a mapping")

    outer_fields = _normalize_decoded_fields(data, context="GetConfig response")
    nested_config = outer_fields.get(2)
    if isinstance(nested_config, Mapping):
        config_fields = _normalize_decoded_fields(
            nested_config,
            context="GetConfig Response.Config",
        )
        service_result = outer_fields.get(1)
    else:
        config_fields = outer_fields
        service_result = None

    values: dict[SetConfigField, bool | int | IntEnum] = {}
    for response_field, raw_value in config_fields.items():
        try:
            get_field = GetConfigField(response_field)
        except ValueError:
            continue

        set_field = GET_CONFIG_FIELD_TO_SET_CONFIG_FIELD[get_field]
        value = _decode_snapshot_value(set_field, raw_value)
        if value is not None:
            values[set_field] = value

    return ConfigSnapshot(
        values=values,
        raw_fields=config_fields,
        service_result=service_result,
    )


def _diagnostic_value(value: object) -> Any:
    """Convert frozen wire values to Home Assistant-safe attributes."""
    if isinstance(value, Mapping):
        return {
            str(key): _diagnostic_value(nested)
            for key, nested in value.items()
        }
    if isinstance(value, (tuple, list)):
        return [_diagnostic_value(item) for item in value]
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return value.hex()
    if isinstance(value, IntEnum):
        return int(value)
    return value


def config_snapshot_attributes(snapshot: ConfigSnapshot) -> dict[str, Any]:
    """Return typed and raw read-only config diagnostics."""
    typed: dict[str, object] = {}
    enum_names: dict[str, str] = {}
    for field, value in snapshot.values.items():
        name = SET_CONFIG_FIELD_SPECS[field].protobuf_name
        typed[name] = int(value) if isinstance(value, IntEnum) else value
        if isinstance(value, IntEnum):
            enum_names[name] = value.name.lower()
    return {
        "typed_values": typed,
        "enum_names": enum_names,
        "raw_fields": {
            str(field_number): _diagnostic_value(value)
            for field_number, value in snapshot.raw_fields.items()
        },
        "service_result": _diagnostic_value(snapshot.service_result),
    }


__all__ = [
    "GET_CONFIG_FIELD_TO_SET_CONFIG_FIELD",
    "SET_CONFIG_FIELD_SPECS",
    "AvoidMode",
    "CarpetCleanOption",
    "CarpetCleanPriorityOption",
    "CarpetDeepCleanOption",
    "CleanMopFrequency",
    "CleanMode",
    "ConfigSnapshot",
    "ConfigCodecError",
    "CornerCleanMode",
    "DryMopStrength",
    "GetConfigField",
    "Language",
    "SetConfigField",
    "SetConfigFieldSpec",
    "SetConfigPatch",
    "StationLightCtrlType",
    "config_snapshot_attributes",
    "decode_get_config_response",
    "decode_set_config_patch",
    "encode_set_config_patch",
]
