"""Strict read-only decoders for Narwal's local timeline and clean report.

These schemas describe robot-local protocol messages. They do not establish
the semantics, retention, or API shape of Narwal's separate cloud history.
Nested report/event messages remain opaque until their own schemas are added.
"""

from __future__ import annotations

import struct
from collections.abc import Mapping
from dataclasses import dataclass
from enum import IntEnum
from types import MappingProxyType

_INT32_MIN = -(1 << 31)
_INT32_MAX = (1 << 31) - 1
_INT64_MIN = -(1 << 63)
_INT64_MAX = (1 << 63) - 1
_UINT32_MAX = (1 << 32) - 1
_UINT64_MAX = (1 << 64) - 1


class HistoryCodecError(ValueError):
    """Raised when a timeline or clean-report value violates its schema."""


class TimeLineParam(IntEnum):
    """APK-defined history-window request values."""

    UNSPECIFIED = 0
    ONE = 1
    THREE = 2
    ALL = 3


CLEAN_REPORT_REPEATED_MESSAGE_FIELDS: Mapping[int, str] = MappingProxyType(
    {
        11: "cleanParams",
        13: "cleanTimes",
        15: "cleanEventMsgs",
        16: "roomCleanEvents",
        17: "carpetChangeEvents",
        20: "robotTrappedPoints",
        24: "subRoomInfos",
        30: "exceptionInfoList",
        32: "visionDirtyList",
        36: "uncleanedZones",
    }
)

CLEAN_REPORT_SINGULAR_MESSAGE_FIELDS: Mapping[int, str] = MappingProxyType(
    {
        12: "map",
        25: "initCleanParam",
        26: "timeLineStatus",
        28: "cleanTask",
        31: "imageResources",
        40: "restoreTaskInfo",
        42: "exceptionVideoResources",
    }
)


def _normalize_fields(value: object, *, context: str) -> dict[int, object]:
    """Normalize canonical blackboxprotobuf keys and reject ambiguity."""
    if not isinstance(value, Mapping):
        raise HistoryCodecError(f"{context} must be a field mapping")

    normalized: dict[int, object] = {}
    for raw_field, field_value in value.items():
        if type(raw_field) is int:
            field_number = raw_field
        elif type(raw_field) is str:
            try:
                field_number = int(raw_field)
            except ValueError as exc:
                raise HistoryCodecError(
                    f"{context} field key {raw_field!r} is not numeric"
                ) from exc
            if str(field_number) != raw_field:
                raise HistoryCodecError(
                    f"{context} field key {raw_field!r} is not canonical"
                )
        else:
            raise HistoryCodecError(
                f"{context} field keys must be int or canonical decimal str"
            )

        if field_number < 1:
            raise HistoryCodecError(
                f"{context} field number {field_number} must be positive"
            )
        if field_number in normalized:
            raise HistoryCodecError(
                f"{context} contains duplicate field number {field_number}"
            )
        normalized[field_number] = field_value
    return normalized


def _freeze(value: object) -> object:
    """Recursively freeze retained decoded values."""
    if isinstance(value, Mapping):
        return MappingProxyType(
            {key: _freeze(nested) for key, nested in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, (bytearray, memoryview)):
        return bytes(value)
    if isinstance(value, set):
        return frozenset(_freeze(item) for item in value)
    return value


def _freeze_fields(fields: Mapping[int, object]) -> Mapping[int, object]:
    return MappingProxyType(
        {field_number: _freeze(value) for field_number, value in fields.items()}
    )


def _decode_enum_value(value: object, *, context: str) -> int:
    """Decode an enum's signed int32 value from typed or schema-less output."""
    if type(value) is not int:
        raise HistoryCodecError(f"{context} must be an enum integer")
    if _INT32_MIN <= value <= _INT32_MAX:
        return value
    if (1 << 64) + _INT32_MIN <= value <= _UINT64_MAX:
        return value - (1 << 64)
    raise HistoryCodecError(f"{context} is outside the protobuf int32 range")


def _optional_enum(
    fields: Mapping[int, object],
    field_number: int,
    *,
    context: str,
) -> int | None:
    if field_number not in fields:
        return None
    return _decode_enum_value(fields[field_number], context=context)


def _optional_int64(
    fields: Mapping[int, object],
    field_number: int,
    *,
    context: str,
) -> int | None:
    if field_number not in fields:
        return None

    value = fields[field_number]
    if type(value) is not int:
        raise HistoryCodecError(f"{context} must be int64")
    if _INT64_MIN <= value <= _INT64_MAX:
        return value
    if 1 << 63 <= value <= _UINT64_MAX:
        return value - (1 << 64)
    raise HistoryCodecError(f"{context} is outside the protobuf int64 range")


def _optional_uint(
    fields: Mapping[int, object],
    field_number: int,
    *,
    bits: int,
    context: str,
) -> int | None:
    if field_number not in fields:
        return None

    value = fields[field_number]
    maximum = (1 << bits) - 1
    if type(value) is not int or not 0 <= value <= maximum:
        raise HistoryCodecError(
            f"{context} must be uint{bits}, got {value!r}"
        )
    return value


def _optional_bool(
    fields: Mapping[int, object],
    field_number: int,
    *,
    context: str,
) -> bool | None:
    if field_number not in fields:
        return None

    value = fields[field_number]
    if type(value) is bool:
        return value
    if type(value) is int and value in (0, 1):
        return bool(value)
    raise HistoryCodecError(f"{context} must be bool or integer 0/1")


def _optional_text(
    fields: Mapping[int, object],
    field_number: int,
    *,
    context: str,
) -> str | None:
    if field_number not in fields:
        return None

    value = fields[field_number]
    if type(value) is str:
        return value
    if isinstance(value, (bytes, bytearray, memoryview)):
        try:
            return bytes(value).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HistoryCodecError(f"{context} must contain valid UTF-8") from exc
    raise HistoryCodecError(f"{context} must be str or UTF-8 bytes")


def _optional_float32(
    fields: Mapping[int, object],
    field_number: int,
    *,
    context: str,
) -> float | None:
    """Decode a protobuf float or schema-less fixed32 bit pattern."""
    if field_number not in fields:
        return None

    value = fields[field_number]
    if type(value) is float:
        return value
    if type(value) is int and 0 <= value <= _UINT32_MAX:
        return struct.unpack("<f", struct.pack("<I", value))[0]
    raise HistoryCodecError(
        f"{context} must be float or an unsigned fixed32 bit pattern"
    )


def _optional_message(
    fields: Mapping[int, object],
    field_number: int,
    *,
    context: str,
) -> dict[int, object] | None:
    if field_number not in fields:
        return None
    return _normalize_fields(fields[field_number], context=context)


def _repeated_messages(
    fields: Mapping[int, object],
    field_number: int,
    *,
    context: str,
) -> tuple[dict[int, object], ...]:
    if field_number not in fields:
        return ()

    value = fields[field_number]
    if isinstance(value, Mapping):
        values: tuple[object, ...] = (value,)
    elif isinstance(value, (list, tuple)):
        values = tuple(value)
    else:
        raise HistoryCodecError(
            f"{context} must be a message or message sequence"
        )
    return tuple(
        _normalize_fields(item, context=f"{context}[{index}]")
        for index, item in enumerate(values)
    )


def _encode_varint_for_validation(value: int) -> bytes:
    encoded = bytearray()
    while value > 0x7F:
        encoded.append((value & 0x7F) | 0x80)
        value >>= 7
    encoded.append(value)
    return bytes(encoded)


def _decode_packed_varint(
    data: bytes,
    offset: int,
    *,
    context: str,
) -> tuple[int, int]:
    start = offset
    value = 0
    for byte_index in range(10):
        if offset >= len(data):
            raise HistoryCodecError(f"{context} contains a truncated packed varint")
        current = data[offset]
        offset += 1
        if byte_index == 9 and current > 1:
            raise HistoryCodecError(f"{context} packed varint exceeds uint64")
        value |= (current & 0x7F) << (byte_index * 7)
        if current < 0x80:
            if data[start:offset] != _encode_varint_for_validation(value):
                raise HistoryCodecError(
                    f"{context} contains a non-canonical packed varint"
                )
            return value, offset
    raise HistoryCodecError(f"{context} packed varint is too long")


def _uint32_value(value: object, *, context: str) -> int:
    if type(value) is not int or not 0 <= value <= _UINT32_MAX:
        raise HistoryCodecError(f"{context} entry must be uint32")
    return value


def _repeated_uint32(
    fields: Mapping[int, object],
    field_number: int,
    *,
    context: str,
) -> tuple[int, ...]:
    """Decode repeated uint32 from typed, unpacked, or packed output."""
    if field_number not in fields:
        return ()

    value = fields[field_number]
    if type(value) is int:
        return (_uint32_value(value, context=context),)
    if isinstance(value, (list, tuple)):
        return tuple(_uint32_value(item, context=context) for item in value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        packed = bytes(value)
        values: list[int] = []
        offset = 0
        while offset < len(packed):
            item, offset = _decode_packed_varint(
                packed,
                offset,
                context=context,
            )
            values.append(_uint32_value(item, context=context))
        return tuple(values)
    raise HistoryCodecError(
        f"{context} must be uint32, a uint32 sequence, or packed bytes"
    )


@dataclass(frozen=True, slots=True)
class RobotEventNode:
    """Proven top-level fields of one local robot timeline node."""

    event_time: int | None
    primary_task: int | None
    secondary_clean_event: Mapping[int, object] | None
    secondary_self_check: int | None
    task_result: int | None
    error_code: Mapping[int, object] | None
    is_primary_node: bool | None
    node_key: int | None
    raw_fields: Mapping[int, object]


@dataclass(frozen=True, slots=True)
class TimeLineStatus:
    """Robot-local timeline status containing event nodes."""

    event_nodes: tuple[RobotEventNode, ...]
    raw_fields: Mapping[int, object]


@dataclass(frozen=True, slots=True)
class GetCleanTimeLineResponse:
    """Decoded ``info/get_clean_time_line`` response."""

    result_code: int | None
    timeline_status: TimeLineStatus | None
    raw_fields: Mapping[int, object]


@dataclass(frozen=True, slots=True)
class CleanReportSubmit:
    """Scalar view of local ``/report/clean_report`` with opaque messages."""

    percent: int | None
    area: float | None
    duration: int | None
    region_type: int | None
    task_type: int | None
    start_time: int | None
    end_time: int | None
    task_result: int | None
    room_order: tuple[int, ...]
    clean_trigger_type: int | None
    trajectory_start_indices: tuple[int, ...]
    max_dirty_level: int | None
    error_code: int | None
    mission_id: int | None
    carpet_updated: bool | None
    is_continued_task: bool | None
    schedule_task_id: str | None
    debug_detail: str | None
    heavy_dirty_room_updated: bool | None
    schedule_task_result: int | None
    up_obstacle_detected: bool | None
    clean_with_mapping_result: int | None
    type_for_pause_too_long_end: int | None
    scenario_error_code: int | None
    tz_offset: str | None
    nested_fields: Mapping[int, object]
    raw_fields: Mapping[int, object]


def _decode_robot_event_node(fields: Mapping[int, object]) -> RobotEventNode:
    secondary_clean_event = _optional_message(
        fields,
        3,
        context="RobotEventNode.secondaryCleanEvent",
    )
    error_code = _optional_message(
        fields,
        6,
        context="RobotEventNode.errorCode",
    )
    return RobotEventNode(
        event_time=_optional_int64(
            fields,
            1,
            context="RobotEventNode.eventTime",
        ),
        primary_task=_optional_enum(
            fields,
            2,
            context="RobotEventNode.primaryTask",
        ),
        secondary_clean_event=(
            _freeze_fields(secondary_clean_event)
            if secondary_clean_event is not None
            else None
        ),
        secondary_self_check=_optional_enum(
            fields,
            4,
            context="RobotEventNode.secondarySelfCheck",
        ),
        task_result=_optional_enum(
            fields,
            5,
            context="RobotEventNode.taskResult",
        ),
        error_code=(
            _freeze_fields(error_code) if error_code is not None else None
        ),
        is_primary_node=_optional_bool(
            fields,
            7,
            context="RobotEventNode.isPrimaryNode",
        ),
        node_key=_optional_uint(
            fields,
            8,
            bits=64,
            context="RobotEventNode.nodeKey",
        ),
        raw_fields=_freeze_fields(fields),
    )


def _decode_timeline_status(fields: Mapping[int, object]) -> TimeLineStatus:
    event_fields = _repeated_messages(
        fields,
        1,
        context="TimeLineStatus.robotEventList",
    )
    return TimeLineStatus(
        event_nodes=tuple(
            _decode_robot_event_node(node_fields)
            for node_fields in event_fields
        ),
        raw_fields=_freeze_fields(fields),
    )


def decode_get_clean_time_line_response(
    data: Mapping[object, object],
) -> GetCleanTimeLineResponse:
    """Decode the robot-local clean timeline response."""
    fields = _normalize_fields(data, context="GetCleanTimeLine.Response")
    timeline_fields = _optional_message(
        fields,
        2,
        context="GetCleanTimeLine.Response.timeLineStatus",
    )
    return GetCleanTimeLineResponse(
        result_code=_optional_enum(
            fields,
            1,
            context="GetCleanTimeLine.Response.result",
        ),
        timeline_status=(
            _decode_timeline_status(timeline_fields)
            if timeline_fields is not None
            else None
        ),
        raw_fields=_freeze_fields(fields),
    )


def encode_get_clean_time_line_request(
    parameter: TimeLineParam = TimeLineParam.ALL,
) -> bytes:
    """Encode the official app's one-field timeline request."""
    if type(parameter) is not TimeLineParam:
        raise HistoryCodecError("parameter must be a TimeLineParam member")
    return b"\x08" + bytes((int(parameter),))


def _decode_clean_report_nested_fields(
    fields: Mapping[int, object],
) -> Mapping[int, object]:
    nested: dict[int, object] = {}
    for field_number, field_name in CLEAN_REPORT_SINGULAR_MESSAGE_FIELDS.items():
        message = _optional_message(
            fields,
            field_number,
            context=f"CleanReportSubmit.{field_name}",
        )
        if message is not None:
            nested[field_number] = _freeze_fields(message)

    for field_number, field_name in CLEAN_REPORT_REPEATED_MESSAGE_FIELDS.items():
        if field_number not in fields:
            continue
        messages = _repeated_messages(
            fields,
            field_number,
            context=f"CleanReportSubmit.{field_name}",
        )
        nested[field_number] = tuple(_freeze_fields(message) for message in messages)
    return MappingProxyType(nested)


def decode_clean_report_submit(
    data: Mapping[object, object],
) -> CleanReportSubmit:
    """Decode proven top-level fields from local ``/report/clean_report``."""
    fields = _normalize_fields(data, context="CleanReportSubmit")
    return CleanReportSubmit(
        percent=_optional_uint(
            fields,
            1,
            bits=32,
            context="CleanReportSubmit.percent",
        ),
        area=_optional_float32(
            fields,
            2,
            context="CleanReportSubmit.area",
        ),
        duration=_optional_uint(
            fields,
            3,
            bits=32,
            context="CleanReportSubmit.duration",
        ),
        region_type=_optional_enum(
            fields,
            4,
            context="CleanReportSubmit.regionType",
        ),
        task_type=_optional_enum(
            fields,
            5,
            context="CleanReportSubmit.taskType",
        ),
        start_time=_optional_uint(
            fields,
            6,
            bits=32,
            context="CleanReportSubmit.startTime",
        ),
        end_time=_optional_uint(
            fields,
            7,
            bits=32,
            context="CleanReportSubmit.endTime",
        ),
        task_result=_optional_enum(
            fields,
            8,
            context="CleanReportSubmit.taskRes",
        ),
        room_order=_repeated_uint32(
            fields,
            9,
            context="CleanReportSubmit.roomOrder",
        ),
        clean_trigger_type=_optional_enum(
            fields,
            10,
            context="CleanReportSubmit.cleanTriggerType",
        ),
        trajectory_start_indices=_repeated_uint32(
            fields,
            14,
            context="CleanReportSubmit.trajectoryStartIndices",
        ),
        max_dirty_level=_optional_uint(
            fields,
            18,
            bits=32,
            context="CleanReportSubmit.maxDirtyLevel",
        ),
        error_code=_optional_uint(
            fields,
            19,
            bits=32,
            context="CleanReportSubmit.errorCode",
        ),
        mission_id=_optional_uint(
            fields,
            21,
            bits=64,
            context="CleanReportSubmit.missionId",
        ),
        carpet_updated=_optional_bool(
            fields,
            22,
            context="CleanReportSubmit.carpetUpdated",
        ),
        is_continued_task=_optional_bool(
            fields,
            23,
            context="CleanReportSubmit.isContinuedTask",
        ),
        schedule_task_id=_optional_text(
            fields,
            29,
            context="CleanReportSubmit.scheduleTaskId",
        ),
        debug_detail=_optional_text(
            fields,
            33,
            context="CleanReportSubmit.debugDetail",
        ),
        heavy_dirty_room_updated=_optional_bool(
            fields,
            34,
            context="CleanReportSubmit.heavyDirtyRoomUpdated",
        ),
        schedule_task_result=_optional_enum(
            fields,
            35,
            context="CleanReportSubmit.scheduleTaskResult",
        ),
        up_obstacle_detected=_optional_bool(
            fields,
            37,
            context="CleanReportSubmit.upObstacleDetected",
        ),
        clean_with_mapping_result=_optional_enum(
            fields,
            38,
            context="CleanReportSubmit.cleanWithMappingResult",
        ),
        type_for_pause_too_long_end=_optional_enum(
            fields,
            39,
            context="CleanReportSubmit.typeForPauseTooLongEnd",
        ),
        scenario_error_code=_optional_uint(
            fields,
            41,
            bits=32,
            context="CleanReportSubmit.scenarioErrorCode",
        ),
        tz_offset=_optional_text(
            fields,
            43,
            context="CleanReportSubmit.tzOffset",
        ),
        nested_fields=_decode_clean_report_nested_fields(fields),
        raw_fields=_freeze_fields(fields),
    )


__all__ = [
    "CLEAN_REPORT_REPEATED_MESSAGE_FIELDS",
    "CLEAN_REPORT_SINGULAR_MESSAGE_FIELDS",
    "CleanReportSubmit",
    "GetCleanTimeLineResponse",
    "HistoryCodecError",
    "RobotEventNode",
    "TimeLineStatus",
    "TimeLineParam",
    "decode_clean_report_submit",
    "decode_get_clean_time_line_response",
    "encode_get_clean_time_line_request",
]
