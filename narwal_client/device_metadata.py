"""Read-only protobuf codecs for Narwal firmware and voice metadata.

The schemas in this module come from generated Dart ``BuilderInfo`` metadata
recovered from the Narwal APK.  Two details differ from earlier protocol notes:

* ``firmwareVersion`` and firmware-entity ``version`` are ``uint32``.  The APK
  uses Dart protobuf field type ``0x8000``; ``uint64`` would be ``0x10000``.
* the language and voice responses use endpoint-specific result *enums* in
  field 1, not a nested ``ServiceResult`` message.

The codecs intentionally expose no request or write encoders.  Known scalar and
nested fields are decoded strictly, while unknown fields are retained as frozen
protobuf values so captures from newer firmware remain inspectable.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from .config import Language

_INT32_MIN = -(1 << 31)
_INT32_MAX = (1 << 31) - 1
_UINT32_MAX = (1 << 32) - 1
_UINT64_MAX = (1 << 64) - 1
_MAX_FIELD_NUMBER = (1 << 29) - 1
_SUPPORTED_WIRE_TYPES = frozenset((0, 1, 2, 5))


class DeviceMetadataCodecError(ValueError):
    """Raised for malformed or schema-invalid metadata protobuf data."""


class GetLanguageResult(IntEnum):
    """``GetLanguage.Response.ResultType`` values recovered from the APK."""

    UNSPECIFIED = 0
    SUCCESS = 1
    FAILED = 2


class GetSupportedLanguagesResult(IntEnum):
    """``GetSupportedLanguages.Response.ResultType`` values from the APK."""

    UNSPECIFIED = 0
    SUCCESS = 1
    FAILED = 2
    LIST_EMPTY = 3


class GetCurrentVoiceInfoResult(IntEnum):
    """``GetCurrentVoiceInfo.Response.ResultType`` values from the APK."""

    UNSPECIFIED = 0
    SUCCESS = 1
    FAILED = 2


@dataclass(frozen=True, slots=True)
class RawMetadataField:
    """One unknown protobuf field retained without interpreting its schema."""

    number: int
    wire_type: int
    value: int | bytes

    def __post_init__(self) -> None:
        if type(self.number) is not int or not 1 <= self.number <= _MAX_FIELD_NUMBER:
            raise DeviceMetadataCodecError(
                f"raw protobuf field number must be between 1 and {_MAX_FIELD_NUMBER}"
            )
        if type(self.wire_type) is not int or self.wire_type not in _SUPPORTED_WIRE_TYPES:
            raise DeviceMetadataCodecError(
                f"raw protobuf field {self.number} has unsupported wire type "
                f"{self.wire_type!r}"
            )

        if self.wire_type == 0:
            if type(self.value) is not int or not 0 <= self.value <= _UINT64_MAX:
                raise DeviceMetadataCodecError(
                    f"raw varint field {self.number} must contain a uint64"
                )
            return

        if not isinstance(self.value, (bytes, bytearray, memoryview)):
            raise DeviceMetadataCodecError(
                f"raw wire-type {self.wire_type} field {self.number} must contain bytes"
            )
        value = bytes(self.value)
        if self.wire_type == 1 and len(value) != 8:
            raise DeviceMetadataCodecError(
                f"raw fixed64 field {self.number} must contain exactly 8 bytes"
            )
        if self.wire_type == 5 and len(value) != 4:
            raise DeviceMetadataCodecError(
                f"raw fixed32 field {self.number} must contain exactly 4 bytes"
            )
        object.__setattr__(self, "value", value)


def _freeze_unknown_fields(
    fields: tuple[RawMetadataField, ...] | list[RawMetadataField],
    *,
    known_fields: frozenset[int],
    context: str,
) -> tuple[RawMetadataField, ...]:
    if not isinstance(fields, (tuple, list)):
        raise DeviceMetadataCodecError(f"{context} unknown_fields must be a tuple or list")
    frozen = tuple(fields)
    for field in frozen:
        if type(field) is not RawMetadataField:
            raise DeviceMetadataCodecError(
                f"{context} unknown_fields entries must be RawMetadataField values"
            )
        if field.number in known_fields:
            raise DeviceMetadataCodecError(
                f"{context} field {field.number} is known and cannot be stored as unknown"
            )
    return frozen


def _validate_optional_string(value: str | None, *, name: str) -> None:
    if value is None:
        return
    if type(value) is not str:
        raise DeviceMetadataCodecError(f"{name} must be str or None")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise DeviceMetadataCodecError(f"{name} must be valid UTF-8") from exc


def _validate_optional_uint32(value: int | None, *, name: str) -> None:
    if value is None:
        return
    if type(value) is not int:
        raise DeviceMetadataCodecError(f"{name} must be int or None")
    if not 0 <= value <= _UINT32_MAX:
        raise DeviceMetadataCodecError(f"{name} must be between 0 and {_UINT32_MAX}")


def _validate_optional_nested(
    value: object | None,
    *,
    expected_type: type,
    name: str,
) -> None:
    if value is not None and type(value) is not expected_type:
        raise DeviceMetadataCodecError(
            f"{name} must be {expected_type.__name__} or None"
        )


def _freeze_typed_tuple(
    values: tuple[object, ...] | list[object],
    *,
    item_type: type,
    context: str,
) -> tuple:
    if not isinstance(values, (tuple, list)):
        raise DeviceMetadataCodecError(f"{context} must be a tuple or list")
    frozen = tuple(values)
    if any(type(value) is not item_type for value in frozen):
        raise DeviceMetadataCodecError(
            f"{context} entries must be {item_type.__name__} values"
        )
    return frozen


def _normalize_result(
    value: IntEnum | int | None,
    *,
    enum_type: type[IntEnum],
    context: str,
) -> IntEnum | int | None:
    if value is None:
        return None
    if type(value) is enum_type:
        return value
    if type(value) is not int:
        raise DeviceMetadataCodecError(
            f"{context} must be a {enum_type.__name__} member, int, or None"
        )
    if not _INT32_MIN <= value <= _INT32_MAX:
        raise DeviceMetadataCodecError(
            f"{context} numeric value must fit protobuf enum int32"
        )
    try:
        return enum_type(value)
    except ValueError:
        # Preserve values introduced by firmware newer than the recovered APK.
        return value


@dataclass(frozen=True, slots=True)
class FirmwareVersionEntity:
    """One firmware component from ``FirmwareVersionEntityMSG``."""

    firmware_id: str | None = None
    version: int | None = None
    version_text: str | None = None
    unknown_fields: tuple[RawMetadataField, ...] = ()

    def __post_init__(self) -> None:
        _validate_optional_string(self.firmware_id, name="FirmwareVersionEntity.firmware_id")
        _validate_optional_uint32(self.version, name="FirmwareVersionEntity.version")
        _validate_optional_string(self.version_text, name="FirmwareVersionEntity.version_text")
        object.__setattr__(
            self,
            "unknown_fields",
            _freeze_unknown_fields(
                self.unknown_fields,
                known_fields=frozenset((1, 2, 3)),
                context="FirmwareVersionEntity",
            ),
        )


@dataclass(frozen=True, slots=True)
class FirmwareGroup:
    """Robot firmware group from ``FirmwareGroupMSG``."""

    mcu: FirmwareVersionEntity | None = None
    ble: FirmwareVersionEntity | None = None
    cpu: FirmwareVersionEntity | None = None
    media: FirmwareVersionEntity | None = None
    sensor_list: tuple[FirmwareVersionEntity, ...] = ()
    unknown_fields: tuple[RawMetadataField, ...] = ()

    def __post_init__(self) -> None:
        for name in ("mcu", "ble", "cpu", "media"):
            _validate_optional_nested(
                getattr(self, name),
                expected_type=FirmwareVersionEntity,
                name=f"FirmwareGroup.{name}",
            )
        object.__setattr__(
            self,
            "sensor_list",
            _freeze_typed_tuple(
                self.sensor_list,
                item_type=FirmwareVersionEntity,
                context="FirmwareGroup.sensor_list",
            ),
        )
        object.__setattr__(
            self,
            "unknown_fields",
            _freeze_unknown_fields(
                self.unknown_fields,
                known_fields=frozenset((1, 2, 3, 4, 5)),
                context="FirmwareGroup",
            ),
        )


@dataclass(frozen=True, slots=True)
class FirmwareStation:
    """Dock firmware group from ``FirmwareStationMSG``."""

    mcu: FirmwareVersionEntity | None = None
    ble: FirmwareVersionEntity | None = None
    cpu: FirmwareVersionEntity | None = None
    media: FirmwareVersionEntity | None = None
    media_b: FirmwareVersionEntity | None = None
    unknown_fields: tuple[RawMetadataField, ...] = ()

    def __post_init__(self) -> None:
        for name in ("mcu", "ble", "cpu", "media", "media_b"):
            _validate_optional_nested(
                getattr(self, name),
                expected_type=FirmwareVersionEntity,
                name=f"FirmwareStation.{name}",
            )
        object.__setattr__(
            self,
            "unknown_fields",
            _freeze_unknown_fields(
                self.unknown_fields,
                known_fields=frozenset((1, 2, 3, 4, 5)),
                context="FirmwareStation",
            ),
        )


@dataclass(frozen=True, slots=True)
class FirmwareVision:
    """Vision firmware group from ``FirmwareVisionMSG``."""

    ai: FirmwareVersionEntity | None = None
    cpu: FirmwareVersionEntity | None = None
    unknown_fields: tuple[RawMetadataField, ...] = ()

    def __post_init__(self) -> None:
        _validate_optional_nested(
            self.ai,
            expected_type=FirmwareVersionEntity,
            name="FirmwareVision.ai",
        )
        _validate_optional_nested(
            self.cpu,
            expected_type=FirmwareVersionEntity,
            name="FirmwareVision.cpu",
        )
        object.__setattr__(
            self,
            "unknown_fields",
            _freeze_unknown_fields(
                self.unknown_fields,
                known_fields=frozenset((1, 2)),
                context="FirmwareVision",
            ),
        )


@dataclass(frozen=True, slots=True)
class FirmwareVersionResponse:
    """Decoded ``common/upgrade/get_firmware_version`` response."""

    firmware_version: int | None = None
    firmware_version_text: str | None = None
    robot: FirmwareGroup | None = None
    station: FirmwareStation | None = None
    vision: FirmwareVision | None = None
    unknown_fields: tuple[RawMetadataField, ...] = ()

    def __post_init__(self) -> None:
        _validate_optional_uint32(
            self.firmware_version,
            name="FirmwareVersionResponse.firmware_version",
        )
        _validate_optional_string(
            self.firmware_version_text,
            name="FirmwareVersionResponse.firmware_version_text",
        )
        _validate_optional_nested(
            self.robot,
            expected_type=FirmwareGroup,
            name="FirmwareVersionResponse.robot",
        )
        _validate_optional_nested(
            self.station,
            expected_type=FirmwareStation,
            name="FirmwareVersionResponse.station",
        )
        _validate_optional_nested(
            self.vision,
            expected_type=FirmwareVision,
            name="FirmwareVersionResponse.vision",
        )
        object.__setattr__(
            self,
            "unknown_fields",
            _freeze_unknown_fields(
                self.unknown_fields,
                known_fields=frozenset((1, 2, 3, 4, 5)),
                context="FirmwareVersionResponse",
            ),
        )


# Endpoint-qualified alias matching the generated ``GetFirmwareVersion.Response``
# message name while retaining the shorter public name used above.
GetFirmwareVersionResponse = FirmwareVersionResponse


@dataclass(frozen=True, slots=True)
class GetLanguageResponse:
    """Decoded ``config/language/get`` response."""

    result: GetLanguageResult | int | None = None
    language: Language | None = None
    unknown_fields: tuple[RawMetadataField, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "result",
            _normalize_result(
                self.result,
                enum_type=GetLanguageResult,
                context="GetLanguageResponse.result",
            ),
        )
        if self.language is not None and type(self.language) is not Language:
            raise DeviceMetadataCodecError(
                "GetLanguageResponse.language must be a Language member or None"
            )
        object.__setattr__(
            self,
            "unknown_fields",
            _freeze_unknown_fields(
                self.unknown_fields,
                known_fields=frozenset((1, 2)),
                context="GetLanguageResponse",
            ),
        )


@dataclass(frozen=True, slots=True)
class GetSupportedLanguagesResponse:
    """Decoded ``config/supported_languages/get`` response."""

    result: GetSupportedLanguagesResult | int | None = None
    languages: tuple[Language, ...] = ()
    unknown_fields: tuple[RawMetadataField, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "result",
            _normalize_result(
                self.result,
                enum_type=GetSupportedLanguagesResult,
                context="GetSupportedLanguagesResponse.result",
            ),
        )
        object.__setattr__(
            self,
            "languages",
            _freeze_typed_tuple(
                self.languages,
                item_type=Language,
                context="GetSupportedLanguagesResponse.languages",
            ),
        )
        object.__setattr__(
            self,
            "unknown_fields",
            _freeze_unknown_fields(
                self.unknown_fields,
                known_fields=frozenset((1, 2)),
                context="GetSupportedLanguagesResponse",
            ),
        )


@dataclass(frozen=True, slots=True)
class VoiceInfo:
    """Decoded ``VoiceInfoMSG`` metadata."""

    language: str | None = None
    version: str | None = None
    describe: str | None = None
    timbre_id: str | None = None
    unknown_fields: tuple[RawMetadataField, ...] = ()

    def __post_init__(self) -> None:
        _validate_optional_string(self.language, name="VoiceInfo.language")
        _validate_optional_string(self.version, name="VoiceInfo.version")
        _validate_optional_string(self.describe, name="VoiceInfo.describe")
        _validate_optional_string(self.timbre_id, name="VoiceInfo.timbre_id")
        object.__setattr__(
            self,
            "unknown_fields",
            _freeze_unknown_fields(
                self.unknown_fields,
                known_fields=frozenset((1, 2, 3, 4)),
                context="VoiceInfo",
            ),
        )


@dataclass(frozen=True, slots=True)
class GetCurrentVoiceInfoResponse:
    """Decoded ``config/language/get_current_voice_info`` response."""

    result: GetCurrentVoiceInfoResult | int | None = None
    voice_info: VoiceInfo | None = None
    unknown_fields: tuple[RawMetadataField, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "result",
            _normalize_result(
                self.result,
                enum_type=GetCurrentVoiceInfoResult,
                context="GetCurrentVoiceInfoResponse.result",
            ),
        )
        _validate_optional_nested(
            self.voice_info,
            expected_type=VoiceInfo,
            name="GetCurrentVoiceInfoResponse.voice_info",
        )
        object.__setattr__(
            self,
            "unknown_fields",
            _freeze_unknown_fields(
                self.unknown_fields,
                known_fields=frozenset((1, 2)),
                context="GetCurrentVoiceInfoResponse",
            ),
        )


def _coerce_payload(
    payload: bytes | bytearray | memoryview,
    *,
    context: str,
) -> bytes:
    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise DeviceMetadataCodecError(f"{context} payload must be bytes-like")
    return bytes(payload)


def _canonical_varint(value: int) -> bytes:
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
            raise DeviceMetadataCodecError("truncated protobuf varint")
        current = data[offset]
        offset += 1
        if byte_index == 9 and current > 1:
            raise DeviceMetadataCodecError("protobuf varint exceeds uint64")
        value |= (current & 0x7F) << (byte_index * 7)
        if current < 0x80:
            if data[start:offset] != _canonical_varint(value):
                raise DeviceMetadataCodecError("non-canonical protobuf varint")
            return value, offset
    raise DeviceMetadataCodecError("protobuf varint is too long")


def _parse_fields(
    payload: bytes | bytearray | memoryview,
    *,
    context: str,
) -> tuple[RawMetadataField, ...]:
    data = _coerce_payload(payload, context=context)
    fields: list[RawMetadataField] = []
    offset = 0
    while offset < len(data):
        key, offset = _decode_varint(data, offset)
        number = key >> 3
        wire_type = key & 0x07
        if not 1 <= number <= _MAX_FIELD_NUMBER:
            raise DeviceMetadataCodecError(
                f"{context} protobuf field number {number} is invalid"
            )
        if wire_type not in _SUPPORTED_WIRE_TYPES:
            raise DeviceMetadataCodecError(
                f"{context} field {number} has unsupported wire type {wire_type}"
            )

        value: int | bytes
        if wire_type == 0:
            value, offset = _decode_varint(data, offset)
        elif wire_type == 1:
            end = offset + 8
            if end > len(data):
                raise DeviceMetadataCodecError(
                    f"{context} fixed64 field {number} is truncated"
                )
            value = data[offset:end]
            offset = end
        elif wire_type == 2:
            length, offset = _decode_varint(data, offset)
            end = offset + length
            if end > len(data):
                raise DeviceMetadataCodecError(
                    f"{context} length-delimited field {number} is truncated"
                )
            value = data[offset:end]
            offset = end
        else:
            end = offset + 4
            if end > len(data):
                raise DeviceMetadataCodecError(
                    f"{context} fixed32 field {number} is truncated"
                )
            value = data[offset:end]
            offset = end

        fields.append(RawMetadataField(number, wire_type, value))
    return tuple(fields)


def _expect_wire(
    field: RawMetadataField,
    expected: int | tuple[int, ...],
    *,
    context: str,
) -> None:
    expected_types = (expected,) if isinstance(expected, int) else expected
    if field.wire_type not in expected_types:
        expected_text = " or ".join(str(item) for item in expected_types)
        raise DeviceMetadataCodecError(
            f"{context} field {field.number} requires wire type {expected_text}, "
            f"got {field.wire_type}"
        )


def _mark_singular(
    seen: set[int],
    field: RawMetadataField,
    *,
    context: str,
) -> None:
    if field.number in seen:
        raise DeviceMetadataCodecError(
            f"{context} contains duplicate singular field {field.number}"
        )
    seen.add(field.number)


def _wire_varint(field: RawMetadataField) -> int:
    assert type(field.value) is int
    return field.value


def _wire_bytes(field: RawMetadataField) -> bytes:
    assert type(field.value) is bytes
    return field.value


def _decode_uint32(value: int, *, name: str) -> int:
    if value > _UINT32_MAX:
        raise DeviceMetadataCodecError(f"{name} protobuf value exceeds uint32")
    return value


def _decode_enum_int32(value: int, *, name: str) -> int:
    if value <= _INT32_MAX:
        return value
    if value >= (1 << 64) + _INT32_MIN:
        return value - (1 << 64)
    raise DeviceMetadataCodecError(f"{name} protobuf value is outside enum int32 range")


def _decode_string(field: RawMetadataField, *, name: str) -> str:
    try:
        return _wire_bytes(field).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DeviceMetadataCodecError(f"{name} is not valid UTF-8") from exc


def _decode_known_result(
    field: RawMetadataField,
    *,
    enum_type: type[IntEnum],
    name: str,
) -> IntEnum | int:
    raw = _decode_enum_int32(_wire_varint(field), name=name)
    try:
        return enum_type(raw)
    except ValueError:
        return raw


def _decode_language(field: RawMetadataField, *, name: str) -> Language:
    raw = _decode_enum_int32(_wire_varint(field), name=name)
    try:
        return Language(raw)
    except ValueError as exc:
        raise DeviceMetadataCodecError(f"unknown Language value {raw}") from exc


def decode_firmware_version_entity(
    payload: bytes | bytearray | memoryview,
) -> FirmwareVersionEntity:
    """Decode ``FirmwareVersionEntityMSG``."""
    firmware_id: str | None = None
    version: int | None = None
    version_text: str | None = None
    unknown: list[RawMetadataField] = []
    seen: set[int] = set()
    context = "FirmwareVersionEntity"
    for field in _parse_fields(payload, context=context):
        if field.number == 1:
            _expect_wire(field, 2, context=context)
            _mark_singular(seen, field, context=context)
            firmware_id = _decode_string(field, name=f"{context}.firmware_id")
        elif field.number == 2:
            _expect_wire(field, 0, context=context)
            _mark_singular(seen, field, context=context)
            version = _decode_uint32(
                _wire_varint(field),
                name=f"{context}.version",
            )
        elif field.number == 3:
            _expect_wire(field, 2, context=context)
            _mark_singular(seen, field, context=context)
            version_text = _decode_string(field, name=f"{context}.version_text")
        else:
            unknown.append(field)
    return FirmwareVersionEntity(firmware_id, version, version_text, tuple(unknown))


def decode_firmware_group(
    payload: bytes | bytearray | memoryview,
) -> FirmwareGroup:
    """Decode robot ``FirmwareGroupMSG``."""
    values: dict[int, FirmwareVersionEntity] = {}
    sensors: list[FirmwareVersionEntity] = []
    unknown: list[RawMetadataField] = []
    seen: set[int] = set()
    context = "FirmwareGroup"
    for field in _parse_fields(payload, context=context):
        if field.number in (1, 2, 3, 4):
            _expect_wire(field, 2, context=context)
            _mark_singular(seen, field, context=context)
            values[field.number] = decode_firmware_version_entity(_wire_bytes(field))
        elif field.number == 5:
            _expect_wire(field, 2, context=context)
            sensors.append(decode_firmware_version_entity(_wire_bytes(field)))
        else:
            unknown.append(field)
    return FirmwareGroup(
        values.get(1),
        values.get(2),
        values.get(3),
        values.get(4),
        tuple(sensors),
        tuple(unknown),
    )


def decode_firmware_station(
    payload: bytes | bytearray | memoryview,
) -> FirmwareStation:
    """Decode ``FirmwareStationMSG``."""
    values: dict[int, FirmwareVersionEntity] = {}
    unknown: list[RawMetadataField] = []
    seen: set[int] = set()
    context = "FirmwareStation"
    for field in _parse_fields(payload, context=context):
        if field.number in (1, 2, 3, 4, 5):
            _expect_wire(field, 2, context=context)
            _mark_singular(seen, field, context=context)
            values[field.number] = decode_firmware_version_entity(_wire_bytes(field))
        else:
            unknown.append(field)
    return FirmwareStation(
        values.get(1),
        values.get(2),
        values.get(3),
        values.get(4),
        values.get(5),
        tuple(unknown),
    )


def decode_firmware_vision(
    payload: bytes | bytearray | memoryview,
) -> FirmwareVision:
    """Decode ``FirmwareVisionMSG``."""
    values: dict[int, FirmwareVersionEntity] = {}
    unknown: list[RawMetadataField] = []
    seen: set[int] = set()
    context = "FirmwareVision"
    for field in _parse_fields(payload, context=context):
        if field.number in (1, 2):
            _expect_wire(field, 2, context=context)
            _mark_singular(seen, field, context=context)
            values[field.number] = decode_firmware_version_entity(_wire_bytes(field))
        else:
            unknown.append(field)
    return FirmwareVision(values.get(1), values.get(2), tuple(unknown))


def decode_firmware_version_response(
    payload: bytes | bytearray | memoryview,
) -> FirmwareVersionResponse:
    """Decode ``common/upgrade/get_firmware_version`` response data."""
    firmware_version: int | None = None
    firmware_version_text: str | None = None
    robot: FirmwareGroup | None = None
    station: FirmwareStation | None = None
    vision: FirmwareVision | None = None
    unknown: list[RawMetadataField] = []
    seen: set[int] = set()
    context = "FirmwareVersionResponse"
    for field in _parse_fields(payload, context=context):
        if field.number == 1:
            _expect_wire(field, 0, context=context)
            _mark_singular(seen, field, context=context)
            firmware_version = _decode_uint32(
                _wire_varint(field),
                name=f"{context}.firmware_version",
            )
        elif field.number == 2:
            _expect_wire(field, 2, context=context)
            _mark_singular(seen, field, context=context)
            firmware_version_text = _decode_string(
                field,
                name=f"{context}.firmware_version_text",
            )
        elif field.number == 3:
            _expect_wire(field, 2, context=context)
            _mark_singular(seen, field, context=context)
            robot = decode_firmware_group(_wire_bytes(field))
        elif field.number == 4:
            _expect_wire(field, 2, context=context)
            _mark_singular(seen, field, context=context)
            station = decode_firmware_station(_wire_bytes(field))
        elif field.number == 5:
            _expect_wire(field, 2, context=context)
            _mark_singular(seen, field, context=context)
            vision = decode_firmware_vision(_wire_bytes(field))
        else:
            unknown.append(field)
    return FirmwareVersionResponse(
        firmware_version,
        firmware_version_text,
        robot,
        station,
        vision,
        tuple(unknown),
    )


def decode_get_firmware_version_response(
    payload: bytes | bytearray | memoryview,
) -> GetFirmwareVersionResponse:
    """Decode ``common/upgrade/get_firmware_version`` response data."""
    return decode_firmware_version_response(payload)


def decode_get_language_response(
    payload: bytes | bytearray | memoryview,
) -> GetLanguageResponse:
    """Decode ``config/language/get`` response data."""
    result: GetLanguageResult | int | None = None
    language: Language | None = None
    unknown: list[RawMetadataField] = []
    seen: set[int] = set()
    context = "GetLanguageResponse"
    for field in _parse_fields(payload, context=context):
        if field.number == 1:
            _expect_wire(field, 0, context=context)
            _mark_singular(seen, field, context=context)
            result = _decode_known_result(
                field,
                enum_type=GetLanguageResult,
                name=f"{context}.result",
            )
        elif field.number == 2:
            _expect_wire(field, 0, context=context)
            _mark_singular(seen, field, context=context)
            language = _decode_language(field, name=f"{context}.language")
        else:
            unknown.append(field)
    return GetLanguageResponse(result, language, tuple(unknown))


def _decode_packed_languages(data: bytes, *, context: str) -> tuple[Language, ...]:
    languages: list[Language] = []
    offset = 0
    while offset < len(data):
        raw, offset = _decode_varint(data, offset)
        field = RawMetadataField(2, 0, raw)
        languages.append(_decode_language(field, name=f"{context}.languages"))
    return tuple(languages)


def decode_get_supported_languages_response(
    payload: bytes | bytearray | memoryview,
) -> GetSupportedLanguagesResponse:
    """Decode ``config/supported_languages/get`` response data."""
    result: GetSupportedLanguagesResult | int | None = None
    languages: list[Language] = []
    unknown: list[RawMetadataField] = []
    seen: set[int] = set()
    context = "GetSupportedLanguagesResponse"
    for field in _parse_fields(payload, context=context):
        if field.number == 1:
            _expect_wire(field, 0, context=context)
            _mark_singular(seen, field, context=context)
            result = _decode_known_result(
                field,
                enum_type=GetSupportedLanguagesResult,
                name=f"{context}.result",
            )
        elif field.number == 2:
            _expect_wire(field, (0, 2), context=context)
            if field.wire_type == 0:
                languages.append(_decode_language(field, name=f"{context}.languages"))
            else:
                languages.extend(
                    _decode_packed_languages(_wire_bytes(field), context=context)
                )
        else:
            unknown.append(field)
    return GetSupportedLanguagesResponse(result, tuple(languages), tuple(unknown))


def decode_voice_info(
    payload: bytes | bytearray | memoryview,
) -> VoiceInfo:
    """Decode ``VoiceInfoMSG``."""
    values: dict[int, str] = {}
    unknown: list[RawMetadataField] = []
    seen: set[int] = set()
    context = "VoiceInfo"
    names = {
        1: "language",
        2: "version",
        3: "describe",
        4: "timbre_id",
    }
    for field in _parse_fields(payload, context=context):
        if field.number in names:
            _expect_wire(field, 2, context=context)
            _mark_singular(seen, field, context=context)
            values[field.number] = _decode_string(
                field,
                name=f"{context}.{names[field.number]}",
            )
        else:
            unknown.append(field)
    return VoiceInfo(
        values.get(1),
        values.get(2),
        values.get(3),
        values.get(4),
        tuple(unknown),
    )


def decode_get_current_voice_info_response(
    payload: bytes | bytearray | memoryview,
) -> GetCurrentVoiceInfoResponse:
    """Decode ``config/language/get_current_voice_info`` response data."""
    result: GetCurrentVoiceInfoResult | int | None = None
    voice_info: VoiceInfo | None = None
    unknown: list[RawMetadataField] = []
    seen: set[int] = set()
    context = "GetCurrentVoiceInfoResponse"
    for field in _parse_fields(payload, context=context):
        if field.number == 1:
            _expect_wire(field, 0, context=context)
            _mark_singular(seen, field, context=context)
            result = _decode_known_result(
                field,
                enum_type=GetCurrentVoiceInfoResult,
                name=f"{context}.result",
            )
        elif field.number == 2:
            _expect_wire(field, 2, context=context)
            _mark_singular(seen, field, context=context)
            voice_info = decode_voice_info(_wire_bytes(field))
        else:
            unknown.append(field)
    return GetCurrentVoiceInfoResponse(result, voice_info, tuple(unknown))
