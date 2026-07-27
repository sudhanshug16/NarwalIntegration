"""Typed protobuf codecs for Narwal clean schedules.

The field numbers and scalar types in this module come from the generated Dart
protobuf metadata recovered from the Narwal APK.  Scalar fields use ``None`` to
represent absence, which keeps an explicitly encoded protobuf default distinct
from a field that was not present on the wire.

Only schema-level validation is applied.  The APK did not prove cron grammar or
cross-field rules between clean plan IDs, clean modes, and custom plan fields,
so this module deliberately does not invent those constraints.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from .config import CleanMode

_INT32_MIN = -(1 << 31)
_INT32_MAX = (1 << 31) - 1
_UINT32_MAX = (1 << 32) - 1
_UINT64_MAX = (1 << 64) - 1
_MAX_FIELD_NUMBER = (1 << 29) - 1
_SUPPORTED_WIRE_TYPES = frozenset((0, 1, 2, 5))


class ScheduleCodecError(ValueError):
    """Raised for malformed or schema-invalid schedule protobuf data."""


class ScheduleError(IntEnum):
    """``ScheduleErrorCode.ErrorCode`` values recovered from the APK."""

    UNSPECIFIED = 0
    SUCCESS = 1
    UNKNOWN_FAILURE = 2
    CLEAN_PLAN_MISSED = 3
    TASK_ID_NOT_EXIST = 4
    DATABASE_FULL = 5
    PARAMETER_ERROR = 6
    INTERNAL_ERROR = 7


@dataclass(frozen=True, slots=True)
class RawProtobufField:
    """One unsupported protobuf field retained for semantic re-encoding."""

    number: int
    wire_type: int
    value: int | bytes

    def __post_init__(self) -> None:
        if type(self.number) is not int or not 1 <= self.number <= _MAX_FIELD_NUMBER:
            raise ScheduleCodecError(
                f"raw protobuf field number must be between 1 and {_MAX_FIELD_NUMBER}"
            )
        if type(self.wire_type) is not int or self.wire_type not in _SUPPORTED_WIRE_TYPES:
            raise ScheduleCodecError(
                f"raw protobuf field {self.number} has unsupported wire type {self.wire_type!r}"
            )

        if self.wire_type == 0:
            if type(self.value) is not int or not 0 <= self.value <= _UINT64_MAX:
                raise ScheduleCodecError(f"raw varint field {self.number} must contain a uint64")
            return

        if not isinstance(self.value, (bytes, bytearray, memoryview)):
            raise ScheduleCodecError(
                f"raw wire-type {self.wire_type} field {self.number} must contain bytes"
            )
        value = bytes(self.value)
        if self.wire_type == 1 and len(value) != 8:
            raise ScheduleCodecError(
                f"raw fixed64 field {self.number} must contain exactly 8 bytes"
            )
        if self.wire_type == 5 and len(value) != 4:
            raise ScheduleCodecError(
                f"raw fixed32 field {self.number} must contain exactly 4 bytes"
            )
        object.__setattr__(self, "value", value)


def _freeze_unknown_fields(
    fields: tuple[RawProtobufField, ...] | list[RawProtobufField],
    *,
    known_fields: frozenset[int],
    context: str,
) -> tuple[RawProtobufField, ...]:
    if not isinstance(fields, (tuple, list)):
        raise ScheduleCodecError(f"{context} unknown_fields must be a tuple or list")

    frozen = tuple(fields)
    for field in frozen:
        if type(field) is not RawProtobufField:
            raise ScheduleCodecError(
                f"{context} unknown_fields entries must be RawProtobufField values"
            )
        if field.number in known_fields:
            raise ScheduleCodecError(
                f"{context} field {field.number} is known and cannot be stored as unknown"
            )
    return frozen


def _freeze_typed_tuple(
    values: tuple[object, ...] | list[object],
    *,
    item_type: type,
    context: str,
) -> tuple:
    if not isinstance(values, (tuple, list)):
        raise ScheduleCodecError(f"{context} must be a tuple or list")
    frozen = tuple(values)
    if any(type(value) is not item_type for value in frozen):
        raise ScheduleCodecError(f"{context} entries must be {item_type.__name__} values")
    return frozen


def _validate_optional_string(value: str | None, *, name: str) -> None:
    if value is None:
        return
    if type(value) is not str:
        raise ScheduleCodecError(f"{name} must be str or None")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ScheduleCodecError(f"{name} must be valid UTF-8") from exc


def _validate_optional_int32(value: int | None, *, name: str) -> None:
    if value is None:
        return
    if type(value) is not int:
        raise ScheduleCodecError(f"{name} must be int or None")
    if not _INT32_MIN <= value <= _INT32_MAX:
        raise ScheduleCodecError(f"{name} must be between {_INT32_MIN} and {_INT32_MAX}")


def _validate_optional_uint32(value: int | None, *, name: str) -> None:
    if value is None:
        return
    if type(value) is not int:
        raise ScheduleCodecError(f"{name} must be int or None")
    if not 0 <= value <= _UINT32_MAX:
        raise ScheduleCodecError(f"{name} must be between 0 and {_UINT32_MAX}")


def _validate_optional_bool(value: bool | None, *, name: str) -> None:
    if value is not None and type(value) is not bool:
        raise ScheduleCodecError(f"{name} must be bool or None")


def _validate_optional_clean_mode(value: CleanMode | None) -> None:
    if value is not None and type(value) is not CleanMode:
        raise ScheduleCodecError("clean_mode must be a CleanMode member or None")


@dataclass(frozen=True, slots=True)
class Crontab:
    """The APK's ``Crontab`` schedule message."""

    cron: str | None = None
    reminding_time: int | None = None
    enabled: bool | None = None
    unknown_fields: tuple[RawProtobufField, ...] = ()

    def __post_init__(self) -> None:
        _validate_optional_string(self.cron, name="cron")
        _validate_optional_int32(self.reminding_time, name="reminding_time")
        _validate_optional_bool(self.enabled, name="enabled")
        object.__setattr__(
            self,
            "unknown_fields",
            _freeze_unknown_fields(
                self.unknown_fields,
                known_fields=frozenset((1, 2, 3)),
                context="Crontab",
            ),
        )


@dataclass(frozen=True, slots=True)
class CleanScheduleParam:
    """The APK's ``CleanScheduleParam`` message."""

    crontab: Crontab | None = None
    clean_plan_id: int | None = None
    clean_mode: CleanMode | None = None
    is_custom_plan: bool | None = None
    custom_name: str | None = None
    unknown_fields: tuple[RawProtobufField, ...] = ()

    def __post_init__(self) -> None:
        if self.crontab is not None and type(self.crontab) is not Crontab:
            raise ScheduleCodecError("crontab must be Crontab or None")
        _validate_optional_uint32(self.clean_plan_id, name="clean_plan_id")
        _validate_optional_clean_mode(self.clean_mode)
        _validate_optional_bool(self.is_custom_plan, name="is_custom_plan")
        _validate_optional_string(self.custom_name, name="custom_name")
        object.__setattr__(
            self,
            "unknown_fields",
            _freeze_unknown_fields(
                self.unknown_fields,
                known_fields=frozenset((1, 2, 3, 4, 5)),
                context="CleanScheduleParam",
            ),
        )


@dataclass(frozen=True, slots=True)
class CleanSchedule:
    """One scheduled clean task."""

    task_id: int | None = None
    clean_schedule_param: CleanScheduleParam | None = None
    unknown_fields: tuple[RawProtobufField, ...] = ()

    def __post_init__(self) -> None:
        _validate_optional_uint32(self.task_id, name="task_id")
        if (
            self.clean_schedule_param is not None
            and type(self.clean_schedule_param) is not CleanScheduleParam
        ):
            raise ScheduleCodecError("clean_schedule_param must be CleanScheduleParam or None")
        object.__setattr__(
            self,
            "unknown_fields",
            _freeze_unknown_fields(
                self.unknown_fields,
                known_fields=frozenset((1, 2)),
                context="CleanSchedule",
            ),
        )


@dataclass(frozen=True, slots=True)
class ScheduleErrorCode:
    """The APK's schedule result message and optional diagnostic text."""

    code: ScheduleError | None = None
    message: str | None = None
    unknown_fields: tuple[RawProtobufField, ...] = ()

    def __post_init__(self) -> None:
        if self.code is not None and type(self.code) is not ScheduleError:
            raise ScheduleCodecError(
                "ScheduleErrorCode.code must be a ScheduleError member or None"
            )
        _validate_optional_string(self.message, name="ScheduleErrorCode.message")
        object.__setattr__(
            self,
            "unknown_fields",
            _freeze_unknown_fields(
                self.unknown_fields,
                known_fields=frozenset((1, 2)),
                context="ScheduleErrorCode",
            ),
        )


@dataclass(frozen=True, slots=True)
class GetCleanSchedulesRequest:
    """``GetCleanSchedules.Request``; the recovered schema has no known fields."""

    unknown_fields: tuple[RawProtobufField, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "unknown_fields",
            _freeze_unknown_fields(
                self.unknown_fields,
                known_fields=frozenset(),
                context="GetCleanSchedulesRequest",
            ),
        )


@dataclass(frozen=True, slots=True)
class GetCleanSchedulesResponse:
    """``GetCleanSchedules.Response``."""

    error_code: ScheduleErrorCode | None = None
    clean_schedules: tuple[CleanSchedule, ...] = ()
    unknown_fields: tuple[RawProtobufField, ...] = ()

    def __post_init__(self) -> None:
        if self.error_code is not None and type(self.error_code) is not ScheduleErrorCode:
            raise ScheduleCodecError(
                "GetCleanSchedulesResponse.error_code must be ScheduleErrorCode or None"
            )
        object.__setattr__(
            self,
            "clean_schedules",
            _freeze_typed_tuple(
                self.clean_schedules,
                item_type=CleanSchedule,
                context="clean_schedules",
            ),
        )
        object.__setattr__(
            self,
            "unknown_fields",
            _freeze_unknown_fields(
                self.unknown_fields,
                known_fields=frozenset((1, 2)),
                context="GetCleanSchedulesResponse",
            ),
        )


@dataclass(frozen=True, slots=True)
class AddCleanScheduleRequest:
    """``AddCleanSchedule.Request``."""

    clean_schedule_param: CleanScheduleParam | None = None
    unknown_fields: tuple[RawProtobufField, ...] = ()

    def __post_init__(self) -> None:
        if (
            self.clean_schedule_param is not None
            and type(self.clean_schedule_param) is not CleanScheduleParam
        ):
            raise ScheduleCodecError(
                "AddCleanScheduleRequest.clean_schedule_param must be CleanScheduleParam or None"
            )
        object.__setattr__(
            self,
            "unknown_fields",
            _freeze_unknown_fields(
                self.unknown_fields,
                known_fields=frozenset((1,)),
                context="AddCleanScheduleRequest",
            ),
        )


@dataclass(frozen=True, slots=True)
class AddCleanScheduleResponse:
    """``AddCleanSchedule.Response``."""

    error_code: ScheduleErrorCode | None = None
    task_id: int | None = None
    unknown_fields: tuple[RawProtobufField, ...] = ()

    def __post_init__(self) -> None:
        if self.error_code is not None and type(self.error_code) is not ScheduleErrorCode:
            raise ScheduleCodecError(
                "AddCleanScheduleResponse.error_code must be ScheduleErrorCode or None"
            )
        _validate_optional_uint32(self.task_id, name="task_id")
        object.__setattr__(
            self,
            "unknown_fields",
            _freeze_unknown_fields(
                self.unknown_fields,
                known_fields=frozenset((1, 2)),
                context="AddCleanScheduleResponse",
            ),
        )


@dataclass(frozen=True, slots=True)
class UpdateCleanScheduleRequest:
    """``UpdateCleanSchedule.Request``."""

    clean_schedule: CleanSchedule | None = None
    unknown_fields: tuple[RawProtobufField, ...] = ()

    def __post_init__(self) -> None:
        if self.clean_schedule is not None and type(self.clean_schedule) is not CleanSchedule:
            raise ScheduleCodecError(
                "UpdateCleanScheduleRequest.clean_schedule must be CleanSchedule or None"
            )
        object.__setattr__(
            self,
            "unknown_fields",
            _freeze_unknown_fields(
                self.unknown_fields,
                known_fields=frozenset((1,)),
                context="UpdateCleanScheduleRequest",
            ),
        )


@dataclass(frozen=True, slots=True)
class UpdateCleanScheduleResponse:
    """``UpdateCleanSchedule.Response``."""

    error_code: ScheduleErrorCode | None = None
    unknown_fields: tuple[RawProtobufField, ...] = ()

    def __post_init__(self) -> None:
        if self.error_code is not None and type(self.error_code) is not ScheduleErrorCode:
            raise ScheduleCodecError(
                "UpdateCleanScheduleResponse.error_code must be ScheduleErrorCode or None"
            )
        object.__setattr__(
            self,
            "unknown_fields",
            _freeze_unknown_fields(
                self.unknown_fields,
                known_fields=frozenset((1,)),
                context="UpdateCleanScheduleResponse",
            ),
        )


@dataclass(frozen=True, slots=True)
class DeleteCleanSchedulesRequest:
    """``DeleteCleanSchedules.Request`` with packed ``uint32`` task IDs."""

    task_ids: tuple[int, ...] = ()
    unknown_fields: tuple[RawProtobufField, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.task_ids, (tuple, list)):
            raise ScheduleCodecError("task_ids must be a tuple or list")
        task_ids = tuple(self.task_ids)
        for task_id in task_ids:
            if task_id is None:
                raise ScheduleCodecError("task_id must be int")
            _validate_optional_uint32(task_id, name="task_id")
        object.__setattr__(self, "task_ids", task_ids)
        object.__setattr__(
            self,
            "unknown_fields",
            _freeze_unknown_fields(
                self.unknown_fields,
                known_fields=frozenset((1,)),
                context="DeleteCleanSchedulesRequest",
            ),
        )


@dataclass(frozen=True, slots=True)
class DeleteCleanSchedulesResponse:
    """``DeleteCleanSchedules.Response``."""

    error_code: ScheduleErrorCode | None = None
    unknown_fields: tuple[RawProtobufField, ...] = ()

    def __post_init__(self) -> None:
        if self.error_code is not None and type(self.error_code) is not ScheduleErrorCode:
            raise ScheduleCodecError(
                "DeleteCleanSchedulesResponse.error_code must be ScheduleErrorCode or None"
            )
        object.__setattr__(
            self,
            "unknown_fields",
            _freeze_unknown_fields(
                self.unknown_fields,
                known_fields=frozenset((1,)),
                context="DeleteCleanSchedulesResponse",
            ),
        )


def _coerce_payload(
    payload: bytes | bytearray | memoryview,
    *,
    context: str,
) -> bytes:
    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise ScheduleCodecError(f"{context} payload must be bytes-like")
    return bytes(payload)


def _encode_varint(value: int) -> bytes:
    if type(value) is not int or not 0 <= value <= _UINT64_MAX:
        raise ScheduleCodecError("protobuf varint value must be a uint64")

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
            raise ScheduleCodecError("truncated protobuf varint")
        current = data[offset]
        offset += 1
        if byte_index == 9 and current > 1:
            raise ScheduleCodecError("protobuf varint exceeds uint64")
        value |= (current & 0x7F) << (byte_index * 7)
        if current < 0x80:
            if data[start:offset] != _encode_varint(value):
                raise ScheduleCodecError("non-canonical protobuf varint")
            return value, offset
    raise ScheduleCodecError("protobuf varint is too long")


def _encode_int32(value: int) -> bytes:
    if value < 0:
        value += 1 << 64
    return _encode_varint(value)


def _decode_int32(value: int, *, name: str) -> int:
    if value <= _INT32_MAX:
        return value
    if value >= (1 << 64) + _INT32_MIN:
        return value - (1 << 64)
    raise ScheduleCodecError(f"{name} protobuf value is outside int32 range")


def _decode_uint32(value: int, *, name: str) -> int:
    if value > _UINT32_MAX:
        raise ScheduleCodecError(f"{name} protobuf value exceeds uint32")
    return value


def _parse_fields(
    payload: bytes | bytearray | memoryview,
    *,
    context: str,
) -> tuple[RawProtobufField, ...]:
    data = _coerce_payload(payload, context=context)
    fields: list[RawProtobufField] = []
    offset = 0
    while offset < len(data):
        key, offset = _decode_varint(data, offset)
        number = key >> 3
        wire_type = key & 0x07
        if not 1 <= number <= _MAX_FIELD_NUMBER:
            raise ScheduleCodecError(f"{context} protobuf field number {number} is invalid")
        if wire_type not in _SUPPORTED_WIRE_TYPES:
            raise ScheduleCodecError(
                f"{context} field {number} has unsupported wire type {wire_type}"
            )

        value: int | bytes
        if wire_type == 0:
            value, offset = _decode_varint(data, offset)
        elif wire_type == 1:
            end = offset + 8
            if end > len(data):
                raise ScheduleCodecError(f"{context} fixed64 field {number} is truncated")
            value = data[offset:end]
            offset = end
        elif wire_type == 2:
            length, offset = _decode_varint(data, offset)
            end = offset + length
            if end > len(data):
                raise ScheduleCodecError(f"{context} length-delimited field {number} is truncated")
            value = data[offset:end]
            offset = end
        else:
            end = offset + 4
            if end > len(data):
                raise ScheduleCodecError(f"{context} fixed32 field {number} is truncated")
            value = data[offset:end]
            offset = end

        fields.append(RawProtobufField(number, wire_type, value))
    return tuple(fields)


def _encode_raw_field(field: RawProtobufField) -> bytes:
    key = _encode_varint((field.number << 3) | field.wire_type)
    if field.wire_type == 0:
        assert type(field.value) is int
        return key + _encode_varint(field.value)
    assert type(field.value) is bytes
    if field.wire_type == 2:
        return key + _encode_varint(len(field.value)) + field.value
    return key + field.value


def _encode_unknown_fields(fields: tuple[RawProtobufField, ...]) -> bytes:
    return b"".join(_encode_raw_field(field) for field in fields)


def _field_varint(number: int, value: int) -> bytes:
    return _encode_varint(number << 3) + _encode_varint(value)


def _field_int32(number: int, value: int) -> bytes:
    return _encode_varint(number << 3) + _encode_int32(value)


def _field_bytes(number: int, value: bytes) -> bytes:
    return _encode_varint((number << 3) | 2) + _encode_varint(len(value)) + value


def _field_string(number: int, value: str) -> bytes:
    return _field_bytes(number, value.encode("utf-8"))


def _expect_wire(
    field: RawProtobufField,
    expected: int | tuple[int, ...],
    *,
    context: str,
) -> None:
    expected_types: tuple[int, ...] = (expected,) if isinstance(expected, int) else expected
    if field.wire_type not in expected_types:
        expected_text = " or ".join(str(item) for item in expected_types)
        raise ScheduleCodecError(
            f"{context} field {field.number} requires wire type {expected_text}, "
            f"got {field.wire_type}"
        )


def _mark_singular(seen: set[int], field: RawProtobufField, *, context: str) -> None:
    if field.number in seen:
        raise ScheduleCodecError(f"{context} contains duplicate singular field {field.number}")
    seen.add(field.number)


def _wire_varint(field: RawProtobufField) -> int:
    assert type(field.value) is int
    return field.value


def _wire_bytes(field: RawProtobufField) -> bytes:
    assert type(field.value) is bytes
    return field.value


def encode_crontab(value: Crontab) -> bytes:
    """Encode a ``Crontab`` message deterministically."""
    if type(value) is not Crontab:
        raise ScheduleCodecError("value must be Crontab")
    encoded = bytearray()
    if value.cron is not None:
        encoded.extend(_field_string(1, value.cron))
    if value.reminding_time is not None:
        encoded.extend(_field_int32(2, value.reminding_time))
    if value.enabled is not None:
        encoded.extend(_field_varint(3, int(value.enabled)))
    encoded.extend(_encode_unknown_fields(value.unknown_fields))
    return bytes(encoded)


def decode_crontab(payload: bytes | bytearray | memoryview) -> Crontab:
    """Decode a ``Crontab`` message."""
    cron: str | None = None
    reminding_time: int | None = None
    enabled: bool | None = None
    unknown: list[RawProtobufField] = []
    seen: set[int] = set()
    for field in _parse_fields(payload, context="Crontab"):
        if field.number == 1:
            _expect_wire(field, 2, context="Crontab")
            _mark_singular(seen, field, context="Crontab")
            try:
                cron = _wire_bytes(field).decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ScheduleCodecError("Crontab.cron is not valid UTF-8") from exc
        elif field.number == 2:
            _expect_wire(field, 0, context="Crontab")
            _mark_singular(seen, field, context="Crontab")
            reminding_time = _decode_int32(
                _wire_varint(field),
                name="Crontab.reminding_time",
            )
        elif field.number == 3:
            _expect_wire(field, 0, context="Crontab")
            _mark_singular(seen, field, context="Crontab")
            raw_enabled = _wire_varint(field)
            if raw_enabled not in (0, 1):
                raise ScheduleCodecError(
                    f"Crontab.enabled Boolean wire value must be 0 or 1, got {raw_enabled}"
                )
            enabled = bool(raw_enabled)
        else:
            unknown.append(field)
    return Crontab(cron, reminding_time, enabled, tuple(unknown))


def encode_clean_schedule_param(value: CleanScheduleParam) -> bytes:
    """Encode a ``CleanScheduleParam`` message deterministically."""
    if type(value) is not CleanScheduleParam:
        raise ScheduleCodecError("value must be CleanScheduleParam")
    encoded = bytearray()
    if value.crontab is not None:
        encoded.extend(_field_bytes(1, encode_crontab(value.crontab)))
    if value.clean_plan_id is not None:
        encoded.extend(_field_varint(2, value.clean_plan_id))
    if value.clean_mode is not None:
        encoded.extend(_field_varint(3, int(value.clean_mode)))
    if value.is_custom_plan is not None:
        encoded.extend(_field_varint(4, int(value.is_custom_plan)))
    if value.custom_name is not None:
        encoded.extend(_field_string(5, value.custom_name))
    encoded.extend(_encode_unknown_fields(value.unknown_fields))
    return bytes(encoded)


def decode_clean_schedule_param(
    payload: bytes | bytearray | memoryview,
) -> CleanScheduleParam:
    """Decode a ``CleanScheduleParam`` message."""
    crontab: Crontab | None = None
    clean_plan_id: int | None = None
    clean_mode: CleanMode | None = None
    is_custom_plan: bool | None = None
    custom_name: str | None = None
    unknown: list[RawProtobufField] = []
    seen: set[int] = set()
    for field in _parse_fields(payload, context="CleanScheduleParam"):
        if field.number == 1:
            _expect_wire(field, 2, context="CleanScheduleParam")
            _mark_singular(seen, field, context="CleanScheduleParam")
            crontab = decode_crontab(_wire_bytes(field))
        elif field.number == 2:
            _expect_wire(field, 0, context="CleanScheduleParam")
            _mark_singular(seen, field, context="CleanScheduleParam")
            clean_plan_id = _decode_uint32(
                _wire_varint(field),
                name="CleanScheduleParam.clean_plan_id",
            )
        elif field.number == 3:
            _expect_wire(field, 0, context="CleanScheduleParam")
            _mark_singular(seen, field, context="CleanScheduleParam")
            raw_mode = _wire_varint(field)
            try:
                clean_mode = CleanMode(raw_mode)
            except ValueError as exc:
                raise ScheduleCodecError(f"unknown CleanMode value {raw_mode}") from exc
        elif field.number == 4:
            _expect_wire(field, 0, context="CleanScheduleParam")
            _mark_singular(seen, field, context="CleanScheduleParam")
            raw_custom = _wire_varint(field)
            if raw_custom not in (0, 1):
                raise ScheduleCodecError(
                    "CleanScheduleParam.is_custom_plan Boolean wire value must "
                    f"be 0 or 1, got {raw_custom}"
                )
            is_custom_plan = bool(raw_custom)
        elif field.number == 5:
            _expect_wire(field, 2, context="CleanScheduleParam")
            _mark_singular(seen, field, context="CleanScheduleParam")
            try:
                custom_name = _wire_bytes(field).decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ScheduleCodecError(
                    "CleanScheduleParam.custom_name is not valid UTF-8"
                ) from exc
        else:
            unknown.append(field)
    return CleanScheduleParam(
        crontab,
        clean_plan_id,
        clean_mode,
        is_custom_plan,
        custom_name,
        tuple(unknown),
    )


def encode_clean_schedule(value: CleanSchedule) -> bytes:
    """Encode one ``CleanSchedule`` message deterministically."""
    if type(value) is not CleanSchedule:
        raise ScheduleCodecError("value must be CleanSchedule")
    encoded = bytearray()
    if value.task_id is not None:
        encoded.extend(_field_varint(1, value.task_id))
    if value.clean_schedule_param is not None:
        encoded.extend(
            _field_bytes(
                2,
                encode_clean_schedule_param(value.clean_schedule_param),
            )
        )
    encoded.extend(_encode_unknown_fields(value.unknown_fields))
    return bytes(encoded)


def decode_clean_schedule(
    payload: bytes | bytearray | memoryview,
) -> CleanSchedule:
    """Decode one ``CleanSchedule`` message."""
    task_id: int | None = None
    parameter: CleanScheduleParam | None = None
    unknown: list[RawProtobufField] = []
    seen: set[int] = set()
    for field in _parse_fields(payload, context="CleanSchedule"):
        if field.number == 1:
            _expect_wire(field, 0, context="CleanSchedule")
            _mark_singular(seen, field, context="CleanSchedule")
            task_id = _decode_uint32(
                _wire_varint(field),
                name="CleanSchedule.task_id",
            )
        elif field.number == 2:
            _expect_wire(field, 2, context="CleanSchedule")
            _mark_singular(seen, field, context="CleanSchedule")
            parameter = decode_clean_schedule_param(_wire_bytes(field))
        else:
            unknown.append(field)
    return CleanSchedule(task_id, parameter, tuple(unknown))


def encode_schedule_error_code(value: ScheduleErrorCode) -> bytes:
    """Encode a ``ScheduleErrorCode`` message deterministically."""
    if type(value) is not ScheduleErrorCode:
        raise ScheduleCodecError("value must be ScheduleErrorCode")
    encoded = bytearray()
    if value.code is not None:
        encoded.extend(_field_varint(1, int(value.code)))
    if value.message is not None:
        encoded.extend(_field_string(2, value.message))
    encoded.extend(_encode_unknown_fields(value.unknown_fields))
    return bytes(encoded)


def decode_schedule_error_code(
    payload: bytes | bytearray | memoryview,
) -> ScheduleErrorCode:
    """Decode a ``ScheduleErrorCode`` message."""
    code: ScheduleError | None = None
    message: str | None = None
    unknown: list[RawProtobufField] = []
    seen: set[int] = set()
    for field in _parse_fields(payload, context="ScheduleErrorCode"):
        if field.number == 1:
            _expect_wire(field, 0, context="ScheduleErrorCode")
            _mark_singular(seen, field, context="ScheduleErrorCode")
            raw_code = _wire_varint(field)
            try:
                code = ScheduleError(raw_code)
            except ValueError as exc:
                raise ScheduleCodecError(f"unknown ScheduleError value {raw_code}") from exc
        elif field.number == 2:
            _expect_wire(field, 2, context="ScheduleErrorCode")
            _mark_singular(seen, field, context="ScheduleErrorCode")
            try:
                message = _wire_bytes(field).decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ScheduleCodecError("ScheduleErrorCode.message is not valid UTF-8") from exc
        else:
            unknown.append(field)
    return ScheduleErrorCode(code, message, tuple(unknown))


def encode_get_clean_schedules_request(value: GetCleanSchedulesRequest) -> bytes:
    """Encode ``GetCleanSchedules.Request``."""
    if type(value) is not GetCleanSchedulesRequest:
        raise ScheduleCodecError("value must be GetCleanSchedulesRequest")
    return _encode_unknown_fields(value.unknown_fields)


def decode_get_clean_schedules_request(
    payload: bytes | bytearray | memoryview,
) -> GetCleanSchedulesRequest:
    """Decode ``GetCleanSchedules.Request`` and retain future fields."""
    return GetCleanSchedulesRequest(_parse_fields(payload, context="GetCleanSchedulesRequest"))


def encode_get_clean_schedules_response(value: GetCleanSchedulesResponse) -> bytes:
    """Encode ``GetCleanSchedules.Response``."""
    if type(value) is not GetCleanSchedulesResponse:
        raise ScheduleCodecError("value must be GetCleanSchedulesResponse")
    encoded = bytearray()
    if value.error_code is not None:
        encoded.extend(_field_bytes(1, encode_schedule_error_code(value.error_code)))
    for schedule in value.clean_schedules:
        encoded.extend(_field_bytes(2, encode_clean_schedule(schedule)))
    encoded.extend(_encode_unknown_fields(value.unknown_fields))
    return bytes(encoded)


def decode_get_clean_schedules_response(
    payload: bytes | bytearray | memoryview,
) -> GetCleanSchedulesResponse:
    """Decode ``GetCleanSchedules.Response``."""
    error_code: ScheduleErrorCode | None = None
    schedules: list[CleanSchedule] = []
    unknown: list[RawProtobufField] = []
    seen: set[int] = set()
    for field in _parse_fields(payload, context="GetCleanSchedulesResponse"):
        if field.number == 1:
            _expect_wire(field, 2, context="GetCleanSchedulesResponse")
            _mark_singular(seen, field, context="GetCleanSchedulesResponse")
            error_code = decode_schedule_error_code(_wire_bytes(field))
        elif field.number == 2:
            _expect_wire(field, 2, context="GetCleanSchedulesResponse")
            schedules.append(decode_clean_schedule(_wire_bytes(field)))
        else:
            unknown.append(field)
    return GetCleanSchedulesResponse(error_code, tuple(schedules), tuple(unknown))


def encode_add_clean_schedule_request(value: AddCleanScheduleRequest) -> bytes:
    """Encode ``AddCleanSchedule.Request``."""
    if type(value) is not AddCleanScheduleRequest:
        raise ScheduleCodecError("value must be AddCleanScheduleRequest")
    encoded = bytearray()
    if value.clean_schedule_param is not None:
        encoded.extend(
            _field_bytes(
                1,
                encode_clean_schedule_param(value.clean_schedule_param),
            )
        )
    encoded.extend(_encode_unknown_fields(value.unknown_fields))
    return bytes(encoded)


def decode_add_clean_schedule_request(
    payload: bytes | bytearray | memoryview,
) -> AddCleanScheduleRequest:
    """Decode ``AddCleanSchedule.Request``."""
    parameter: CleanScheduleParam | None = None
    unknown: list[RawProtobufField] = []
    seen: set[int] = set()
    for field in _parse_fields(payload, context="AddCleanScheduleRequest"):
        if field.number == 1:
            _expect_wire(field, 2, context="AddCleanScheduleRequest")
            _mark_singular(seen, field, context="AddCleanScheduleRequest")
            parameter = decode_clean_schedule_param(_wire_bytes(field))
        else:
            unknown.append(field)
    return AddCleanScheduleRequest(parameter, tuple(unknown))


def encode_add_clean_schedule_response(value: AddCleanScheduleResponse) -> bytes:
    """Encode ``AddCleanSchedule.Response``."""
    if type(value) is not AddCleanScheduleResponse:
        raise ScheduleCodecError("value must be AddCleanScheduleResponse")
    encoded = bytearray()
    if value.error_code is not None:
        encoded.extend(_field_bytes(1, encode_schedule_error_code(value.error_code)))
    if value.task_id is not None:
        encoded.extend(_field_varint(2, value.task_id))
    encoded.extend(_encode_unknown_fields(value.unknown_fields))
    return bytes(encoded)


def decode_add_clean_schedule_response(
    payload: bytes | bytearray | memoryview,
) -> AddCleanScheduleResponse:
    """Decode ``AddCleanSchedule.Response``."""
    error_code: ScheduleErrorCode | None = None
    task_id: int | None = None
    unknown: list[RawProtobufField] = []
    seen: set[int] = set()
    for field in _parse_fields(payload, context="AddCleanScheduleResponse"):
        if field.number == 1:
            _expect_wire(field, 2, context="AddCleanScheduleResponse")
            _mark_singular(seen, field, context="AddCleanScheduleResponse")
            error_code = decode_schedule_error_code(_wire_bytes(field))
        elif field.number == 2:
            _expect_wire(field, 0, context="AddCleanScheduleResponse")
            _mark_singular(seen, field, context="AddCleanScheduleResponse")
            task_id = _decode_uint32(
                _wire_varint(field),
                name="AddCleanScheduleResponse.task_id",
            )
        else:
            unknown.append(field)
    return AddCleanScheduleResponse(error_code, task_id, tuple(unknown))


def encode_update_clean_schedule_request(
    value: UpdateCleanScheduleRequest,
) -> bytes:
    """Encode ``UpdateCleanSchedule.Request``."""
    if type(value) is not UpdateCleanScheduleRequest:
        raise ScheduleCodecError("value must be UpdateCleanScheduleRequest")
    encoded = bytearray()
    if value.clean_schedule is not None:
        encoded.extend(_field_bytes(1, encode_clean_schedule(value.clean_schedule)))
    encoded.extend(_encode_unknown_fields(value.unknown_fields))
    return bytes(encoded)


def decode_update_clean_schedule_request(
    payload: bytes | bytearray | memoryview,
) -> UpdateCleanScheduleRequest:
    """Decode ``UpdateCleanSchedule.Request``."""
    schedule: CleanSchedule | None = None
    unknown: list[RawProtobufField] = []
    seen: set[int] = set()
    for field in _parse_fields(payload, context="UpdateCleanScheduleRequest"):
        if field.number == 1:
            _expect_wire(field, 2, context="UpdateCleanScheduleRequest")
            _mark_singular(seen, field, context="UpdateCleanScheduleRequest")
            schedule = decode_clean_schedule(_wire_bytes(field))
        else:
            unknown.append(field)
    return UpdateCleanScheduleRequest(schedule, tuple(unknown))


def encode_update_clean_schedule_response(
    value: UpdateCleanScheduleResponse,
) -> bytes:
    """Encode ``UpdateCleanSchedule.Response``."""
    if type(value) is not UpdateCleanScheduleResponse:
        raise ScheduleCodecError("value must be UpdateCleanScheduleResponse")
    encoded = bytearray()
    if value.error_code is not None:
        encoded.extend(_field_bytes(1, encode_schedule_error_code(value.error_code)))
    encoded.extend(_encode_unknown_fields(value.unknown_fields))
    return bytes(encoded)


def decode_update_clean_schedule_response(
    payload: bytes | bytearray | memoryview,
) -> UpdateCleanScheduleResponse:
    """Decode ``UpdateCleanSchedule.Response``."""
    error_code: ScheduleErrorCode | None = None
    unknown: list[RawProtobufField] = []
    seen: set[int] = set()
    for field in _parse_fields(payload, context="UpdateCleanScheduleResponse"):
        if field.number == 1:
            _expect_wire(field, 2, context="UpdateCleanScheduleResponse")
            _mark_singular(seen, field, context="UpdateCleanScheduleResponse")
            error_code = decode_schedule_error_code(_wire_bytes(field))
        else:
            unknown.append(field)
    return UpdateCleanScheduleResponse(error_code, tuple(unknown))


def encode_delete_clean_schedules_request(
    value: DeleteCleanSchedulesRequest,
) -> bytes:
    """Encode ``DeleteCleanSchedules.Request`` with canonical packed IDs."""
    if type(value) is not DeleteCleanSchedulesRequest:
        raise ScheduleCodecError("value must be DeleteCleanSchedulesRequest")
    encoded = bytearray()
    if value.task_ids:
        packed = b"".join(_encode_varint(task_id) for task_id in value.task_ids)
        encoded.extend(_field_bytes(1, packed))
    encoded.extend(_encode_unknown_fields(value.unknown_fields))
    return bytes(encoded)


def decode_delete_clean_schedules_request(
    payload: bytes | bytearray | memoryview,
) -> DeleteCleanSchedulesRequest:
    """Decode packed or protobuf-compatible unpacked schedule task IDs."""
    task_ids: list[int] = []
    unknown: list[RawProtobufField] = []
    for field in _parse_fields(payload, context="DeleteCleanSchedulesRequest"):
        if field.number != 1:
            unknown.append(field)
            continue
        _expect_wire(field, (0, 2), context="DeleteCleanSchedulesRequest")
        if field.wire_type == 0:
            task_ids.append(
                _decode_uint32(
                    _wire_varint(field),
                    name="DeleteCleanSchedulesRequest.task_id",
                )
            )
            continue

        packed = _wire_bytes(field)
        offset = 0
        while offset < len(packed):
            task_id, offset = _decode_varint(packed, offset)
            task_ids.append(
                _decode_uint32(
                    task_id,
                    name="DeleteCleanSchedulesRequest.task_id",
                )
            )
    return DeleteCleanSchedulesRequest(tuple(task_ids), tuple(unknown))


def encode_delete_clean_schedules_response(
    value: DeleteCleanSchedulesResponse,
) -> bytes:
    """Encode ``DeleteCleanSchedules.Response``."""
    if type(value) is not DeleteCleanSchedulesResponse:
        raise ScheduleCodecError("value must be DeleteCleanSchedulesResponse")
    encoded = bytearray()
    if value.error_code is not None:
        encoded.extend(_field_bytes(1, encode_schedule_error_code(value.error_code)))
    encoded.extend(_encode_unknown_fields(value.unknown_fields))
    return bytes(encoded)


def decode_delete_clean_schedules_response(
    payload: bytes | bytearray | memoryview,
) -> DeleteCleanSchedulesResponse:
    """Decode ``DeleteCleanSchedules.Response``."""
    error_code: ScheduleErrorCode | None = None
    unknown: list[RawProtobufField] = []
    seen: set[int] = set()
    for field in _parse_fields(payload, context="DeleteCleanSchedulesResponse"):
        if field.number == 1:
            _expect_wire(field, 2, context="DeleteCleanSchedulesResponse")
            _mark_singular(seen, field, context="DeleteCleanSchedulesResponse")
            error_code = decode_schedule_error_code(_wire_bytes(field))
        else:
            unknown.append(field)
    return DeleteCleanSchedulesResponse(error_code, tuple(unknown))


__all__ = [
    "AddCleanScheduleRequest",
    "AddCleanScheduleResponse",
    "CleanMode",
    "CleanSchedule",
    "CleanScheduleParam",
    "Crontab",
    "DeleteCleanSchedulesRequest",
    "DeleteCleanSchedulesResponse",
    "GetCleanSchedulesRequest",
    "GetCleanSchedulesResponse",
    "RawProtobufField",
    "ScheduleCodecError",
    "ScheduleError",
    "ScheduleErrorCode",
    "UpdateCleanScheduleRequest",
    "UpdateCleanScheduleResponse",
    "decode_add_clean_schedule_request",
    "decode_add_clean_schedule_response",
    "decode_clean_schedule",
    "decode_clean_schedule_param",
    "decode_crontab",
    "decode_delete_clean_schedules_request",
    "decode_delete_clean_schedules_response",
    "decode_get_clean_schedules_request",
    "decode_get_clean_schedules_response",
    "decode_schedule_error_code",
    "decode_update_clean_schedule_request",
    "decode_update_clean_schedule_response",
    "encode_add_clean_schedule_request",
    "encode_add_clean_schedule_response",
    "encode_clean_schedule",
    "encode_clean_schedule_param",
    "encode_crontab",
    "encode_delete_clean_schedules_request",
    "encode_delete_clean_schedules_response",
    "encode_get_clean_schedules_request",
    "encode_get_clean_schedules_response",
    "encode_schedule_error_code",
    "encode_update_clean_schedule_request",
    "encode_update_clean_schedule_response",
]
