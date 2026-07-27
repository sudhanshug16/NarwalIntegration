"""Schema-backed protobuf bodies for Narwal telecontrol.

The recovered APK registers ``Point.x``, ``Point.y``, and ``PoseData.theta``
with protobuf field type ``0x100``. Its bundled protobuf runtime dispatches
``0x100`` to ``_writeFloat`` (four-byte fixed32), while ``0x80`` dispatches to
``_writeDouble``. Keeping that distinction explicit prevents Dart's use of
``double`` for both source-level numeric APIs from being mistaken for a
protobuf ``double`` wire field.
"""

from __future__ import annotations

import math
import struct
from collections.abc import Iterable
from dataclasses import dataclass

_WIRE_VARINT = 0
_WIRE_FIXED64 = 1
_WIRE_LENGTH_DELIMITED = 2
_WIRE_FIXED32 = 5
_INT32_MIN = -(1 << 31)
_INT32_MAX = (1 << 31) - 1
_UINT64_MASK = (1 << 64) - 1


class TelecontrolCodecError(ValueError):
    """Raised when a telecontrol value or protobuf body is invalid."""


@dataclass(frozen=True, slots=True)
class Point:
    """A protobuf ``Point`` with float32 x/y coordinates."""

    x: float
    y: float


@dataclass(frozen=True, slots=True)
class PoseData:
    """A protobuf ``PoseData`` containing a location and float32 heading."""

    location: Point
    theta: float


@dataclass(frozen=True, slots=True)
class PointNaviPlanTraj:
    """Decoded ``PointNaviPlanTraj`` broadcast."""

    plan_traj: tuple[Point, ...]

    @property
    def points(self) -> tuple[Point, ...]:
        """Return the planned trajectory under a generic name."""
        return self.plan_traj


def _encode_varint(value: int) -> bytes:
    """Encode an already-validated unsigned 64-bit protobuf varint."""
    encoded = bytearray()
    while value >= 0x80:
        encoded.append((value & 0x7F) | 0x80)
        value >>= 7
    encoded.append(value)
    return bytes(encoded)


def _validated_int32(value: int, *, context: str) -> int:
    """Validate an int32 without accepting booleans as integers."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{context} must be an integer")
    if not _INT32_MIN <= value <= _INT32_MAX:
        raise TelecontrolCodecError(
            f"{context} out of int32 range: {value} "
            f"(expected {_INT32_MIN}..{_INT32_MAX})"
        )
    return value


def _encode_int32_field(field_number: int, value: int, *, context: str) -> bytes:
    """Encode a protobuf int32, including ten-byte negative values."""
    validated = _validated_int32(value, context=context)
    wire_value = validated & _UINT64_MASK
    return _encode_varint(field_number << 3) + _encode_varint(wire_value)


def _encode_float32(value: float, *, context: str) -> bytes:
    """Validate and encode one finite IEEE-754 little-endian float32."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{context} must be a real number")

    converted = float(value)
    if not math.isfinite(converted):
        raise TelecontrolCodecError(f"{context} must be finite")
    try:
        encoded = struct.pack("<f", converted)
    except (OverflowError, struct.error) as exc:
        raise TelecontrolCodecError(
            f"{context} is outside finite float32 range"
        ) from exc
    if not math.isfinite(struct.unpack("<f", encoded)[0]):
        raise TelecontrolCodecError(
            f"{context} is outside finite float32 range"
        )
    return encoded


def _encode_point(point: Point, *, context: str) -> bytes:
    """Encode ``Point { float x = 1; float y = 2; }``."""
    if not isinstance(point, Point):
        raise TypeError(f"{context} must be Point")
    return (
        b"\x0d"
        + _encode_float32(point.x, context=f"{context}.x")
        + b"\x15"
        + _encode_float32(point.y, context=f"{context}.y")
    )


def _encode_pose(pose: PoseData, *, context: str) -> bytes:
    """Encode ``PoseData { Point location = 1; float theta = 2; }``."""
    if not isinstance(pose, PoseData):
        raise TypeError(f"{context} must be PoseData")
    point = _encode_point(pose.location, context=f"{context}.location")
    return (
        b"\x0a"
        + _encode_varint(len(point))
        + point
        + b"\x15"
        + _encode_float32(pose.theta, context=f"{context}.theta")
    )


def encode_set_manual_control_mode(mode: int) -> bytes:
    """Encode ``SetManualControlMode.Request`` field 1."""
    return _encode_int32_field(1, mode, context="mode")


def encode_telecontrol_velocity(
    linear_velocity: int,
    angular_velocity: int,
) -> bytes:
    """Encode ``TelecontrolVelocity`` int32 fields 1 and 2."""
    return _encode_int32_field(
        1,
        linear_velocity,
        context="linear_velocity",
    ) + _encode_int32_field(
        2,
        angular_velocity,
        context="angular_velocity",
    )


def encode_point_navi_request(
    *,
    avoid_carpet_mask: int,
    explore_mode: int,
    points: Iterable[PoseData],
) -> bytes:
    """Encode the production APK subset of ``PointNavi.Request``.

    Encoded fields are field 2 ``avoidCarpetMask``, field 4 ``exploreMode``,
    and repeated field 5 ``PoseData``.
    """
    encoded = bytearray(
        _encode_int32_field(
            2,
            avoid_carpet_mask,
            context="avoid_carpet_mask",
        )
    )
    encoded.extend(
        _encode_int32_field(
            4,
            explore_mode,
            context="explore_mode",
        )
    )

    try:
        iterator = iter(points)
    except TypeError as exc:
        raise TypeError("points must be an iterable of PoseData") from exc

    for index, pose in enumerate(iterator):
        encoded_pose = _encode_pose(pose, context=f"points[{index}]")
        encoded.append((5 << 3) | _WIRE_LENGTH_DELIMITED)
        encoded.extend(_encode_varint(len(encoded_pose)))
        encoded.extend(encoded_pose)
    return bytes(encoded)


def encode_cancel_navigation_request() -> bytes:
    """Encode ``CancelTask.Request { taskType: NAVI (3) }``."""
    return _encode_int32_field(1, 3, context="navigation task type")


def _as_bytes(data: bytes | bytearray | memoryview) -> bytes:
    """Normalize a protobuf body without accepting generic iterables."""
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError("PointNaviPlanTraj payload must be bytes-like")
    return bytes(data)


def _decode_varint(
    data: bytes,
    offset: int,
    *,
    context: str,
) -> tuple[int, int]:
    """Decode one bounded protobuf uint64 varint."""
    value = 0
    for index in range(10):
        if offset >= len(data):
            raise TelecontrolCodecError(
                f"Truncated {context} varint at offset {offset}"
            )
        byte = data[offset]
        offset += 1
        if index == 9 and byte > 1:
            raise TelecontrolCodecError(f"{context} varint exceeds 64 bits")
        value |= (byte & 0x7F) << (index * 7)
        if not byte & 0x80:
            return value, offset
    raise TelecontrolCodecError(f"{context} varint exceeds 10 bytes")


def _read_length_delimited(
    data: bytes,
    offset: int,
    *,
    context: str,
) -> tuple[bytes, int]:
    """Read a bounded length-delimited protobuf value."""
    length, value_start = _decode_varint(
        data,
        offset,
        context=f"{context} length",
    )
    available = len(data) - value_start
    if length > available:
        raise TelecontrolCodecError(
            f"Truncated {context}: declared {length} bytes, "
            f"only {available} available"
        )
    value_end = value_start + length
    return data[value_start:value_end], value_end


def _read_float32(
    data: bytes,
    offset: int,
    *,
    context: str,
) -> tuple[float, int]:
    """Read and validate one finite protobuf float."""
    if len(data) - offset < 4:
        raise TelecontrolCodecError(
            f"Truncated {context}: expected 4 float32 bytes"
        )
    value = struct.unpack_from("<f", data, offset)[0]
    if not math.isfinite(value):
        raise TelecontrolCodecError(f"{context} must be finite")
    return value, offset + 4


def _skip_unknown_field(
    data: bytes,
    offset: int,
    wire_type: int,
    *,
    context: str,
) -> int:
    """Skip an unknown protobuf field."""
    if wire_type == _WIRE_VARINT:
        _, offset = _decode_varint(data, offset, context=context)
        return offset
    if wire_type == _WIRE_FIXED64:
        if len(data) - offset < 8:
            raise TelecontrolCodecError(
                f"Truncated {context}: expected 8 fixed64 bytes"
            )
        return offset + 8
    if wire_type == _WIRE_LENGTH_DELIMITED:
        _, offset = _read_length_delimited(data, offset, context=context)
        return offset
    if wire_type == _WIRE_FIXED32:
        if len(data) - offset < 4:
            raise TelecontrolCodecError(
                f"Truncated {context}: expected 4 fixed32 bytes"
            )
        return offset + 4
    raise TelecontrolCodecError(
        f"Unsupported protobuf wire type {wire_type} in {context}"
    )


def _decode_point(data: bytes) -> Point:
    """Decode one trajectory ``Point`` while skipping future fields."""
    x = 0.0
    y = 0.0
    offset = 0

    while offset < len(data):
        key, offset = _decode_varint(
            data,
            offset,
            context="Point field key",
        )
        field_number = key >> 3
        wire_type = key & 0x07
        if field_number == 0:
            raise TelecontrolCodecError(
                "Invalid protobuf field number 0 in Point"
            )

        if field_number in (1, 2):
            if wire_type != _WIRE_FIXED32:
                raise TelecontrolCodecError(
                    f"Point field {field_number} has wire type {wire_type}; "
                    "expected fixed32"
                )
            value, offset = _read_float32(
                data,
                offset,
                context=f"Point field {field_number}",
            )
            if field_number == 1:
                x = value
            else:
                y = value
            continue

        offset = _skip_unknown_field(
            data,
            offset,
            wire_type,
            context=f"Point field {field_number}",
        )

    return Point(x=x, y=y)


def decode_point_navi_plan_traj(
    data: bytes | bytearray | memoryview,
) -> PointNaviPlanTraj:
    """Decode repeated field-1 ``Point`` values from a trajectory."""
    payload = _as_bytes(data)
    points: list[Point] = []
    offset = 0

    while offset < len(payload):
        key, offset = _decode_varint(
            payload,
            offset,
            context="PointNaviPlanTraj field key",
        )
        field_number = key >> 3
        wire_type = key & 0x07
        if field_number == 0:
            raise TelecontrolCodecError(
                "Invalid protobuf field number 0 in PointNaviPlanTraj"
            )

        if field_number == 1:
            if wire_type != _WIRE_LENGTH_DELIMITED:
                raise TelecontrolCodecError(
                    "PointNaviPlanTraj field 1 has wire type "
                    f"{wire_type}; expected length-delimited"
                )
            encoded_point, offset = _read_length_delimited(
                payload,
                offset,
                context="PointNaviPlanTraj field 1",
            )
            points.append(_decode_point(encoded_point))
            continue

        offset = _skip_unknown_field(
            payload,
            offset,
            wire_type,
            context=f"PointNaviPlanTraj field {field_number}",
        )

    return PointNaviPlanTraj(plan_traj=tuple(points))


__all__ = [
    "Point",
    "PointNaviPlanTraj",
    "PoseData",
    "TelecontrolCodecError",
    "decode_point_navi_plan_traj",
    "encode_cancel_navigation_request",
    "encode_point_navi_request",
    "encode_set_manual_control_mode",
    "encode_telecontrol_velocity",
]
