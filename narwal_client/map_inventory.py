"""Strict codecs for Narwal's read-only saved/editable map inventory.

The wrapper schemas and scalar wire types in this module come from generated
protobuf metadata recovered from the Narwal Android APK.  ``StaticMapPayload``
is intentionally decoded only through fields already consumed by
``MapData.from_response``.  Every other field remains available in immutable
``raw_fields`` without assigning unproven semantics.
"""

from __future__ import annotations

import math
import struct
from collections.abc import Mapping
from dataclasses import dataclass
from enum import IntEnum
from types import MappingProxyType

from .models import MapData

_INT32_MIN = -(1 << 31)
_INT32_MAX = (1 << 31) - 1
_UINT32_MAX = (1 << 32) - 1
_UINT64_MAX = (1 << 64) - 1


class MapInventoryCodecError(ValueError):
    """Raised when map-inventory input does not match the proven schema."""


class MapRequestFormat(IntEnum):
    """``MapRequestFormat`` values recovered from the APK."""

    COMPRESSED_GRID = 0
    CONTOUR = 1


@dataclass(frozen=True, slots=True)
class GetEditableMapRequest:
    """The APK's ``GetEditableMap.Request``.

    Fields 2 through 4 are deliberately required so a caller cannot silently
    rely on protobuf defaults for data-shape choices.  ``map_id=None`` omits
    optional field 1; an explicit zero remains distinguishable and is encoded.
    """

    include_carpet: bool
    include_floor_plan: bool
    request_format: MapRequestFormat
    map_id: int | None = None

    def __post_init__(self) -> None:
        _validate_get_editable_map_request(self)


@dataclass(frozen=True, slots=True)
class StaticMapPayload:
    """A strict view of one APK ``StaticMapPayload``.

    ``map_data`` reuses the integration's existing parser for its proven
    fields.  ``raw_fields`` retains the complete payload, including unsupported
    fields and alternate map-data oneof members.
    """

    map_data: MapData
    raw_fields: Mapping[int, object]


@dataclass(frozen=True, slots=True)
class EditConfig:
    """Proven ``GetEditableMap.Response.EditConfig`` fields."""

    max_room_nums: int | None
    raw_fields: Mapping[int, object]


@dataclass(frozen=True, slots=True)
class GetAllReducedMapsResponse:
    """Decoded ``GetAllReducedMaps.Response``."""

    result: int | None
    maps: tuple[StaticMapPayload, ...]
    raw_fields: Mapping[int, object]


@dataclass(frozen=True, slots=True)
class GetEditableMapResponse:
    """Decoded ``GetEditableMap.Response``."""

    result: int | None
    map: StaticMapPayload | None
    edit_version: int | None
    edit_config: EditConfig | None
    raw_fields: Mapping[int, object]


@dataclass(frozen=True, slots=True)
class CheckMapUpdateInfoResponse:
    """Decoded ``CheckMapUpdate.Response`` from ``check_map_update_info``."""

    result: bool | None
    map: StaticMapPayload | None
    raw_fields: Mapping[int, object]


def _normalize_fields(value: object, *, context: str) -> dict[int, object]:
    """Normalize canonical blackboxprotobuf keys and reject ambiguous input."""
    if not isinstance(value, Mapping):
        raise MapInventoryCodecError(f"{context} must be a field mapping")

    normalized: dict[int, object] = {}
    for raw_field, field_value in value.items():
        if type(raw_field) is int:
            field_number = raw_field
        elif type(raw_field) is str:
            try:
                field_number = int(raw_field)
            except ValueError as exc:
                raise MapInventoryCodecError(
                    f"{context} field key {raw_field!r} is not numeric"
                ) from exc
            if str(field_number) != raw_field:
                raise MapInventoryCodecError(
                    f"{context} field key {raw_field!r} is not canonical"
                )
        else:
            raise MapInventoryCodecError(
                f"{context} field keys must be int or canonical decimal str"
            )

        if field_number < 1:
            raise MapInventoryCodecError(
                f"{context} field number {field_number} must be positive"
            )
        if field_number in normalized:
            raise MapInventoryCodecError(
                f"{context} contains duplicate field number {field_number}"
            )
        normalized[field_number] = field_value

    return normalized


def _freeze(value: object) -> object:
    """Recursively freeze decoded values retained for diagnostics."""
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
    """Freeze a normalized protobuf field mapping with integer keys."""
    return MappingProxyType(
        {field_number: _freeze(value) for field_number, value in fields.items()}
    )


def _optional_int32(
    fields: Mapping[int, object],
    field_number: int,
    *,
    context: str,
) -> int | None:
    """Decode an optional int32 without coercing booleans or strings."""
    if field_number not in fields:
        return None

    value = fields[field_number]
    if type(value) is not int or not _INT32_MIN <= value <= _INT32_MAX:
        raise MapInventoryCodecError(
            f"{context} must be int32, got {value!r}"
        )
    return value


def _optional_uint(
    fields: Mapping[int, object],
    field_number: int,
    *,
    bits: int,
    context: str,
) -> int | None:
    """Decode an optional uint32/uint64 without coercion."""
    if field_number not in fields:
        return None

    value = fields[field_number]
    maximum = (1 << bits) - 1
    if type(value) is not int or not 0 <= value <= maximum:
        raise MapInventoryCodecError(
            f"{context} must be uint{bits}, got {value!r}"
        )
    return value


def _optional_enum(
    fields: Mapping[int, object],
    field_number: int,
    *,
    context: str,
) -> int | None:
    """Decode an enum while retaining unknown numeric values."""
    if field_number not in fields:
        return None

    value = fields[field_number]
    if type(value) is not int:
        raise MapInventoryCodecError(f"{context} must be an enum integer")
    return value


def _optional_bool(
    fields: Mapping[int, object],
    field_number: int,
    *,
    context: str,
) -> bool | None:
    """Decode a protobuf bool from typed or schema-less output."""
    if field_number not in fields:
        return None

    value = fields[field_number]
    if type(value) is bool:
        return value
    if type(value) is int and value in (0, 1):
        return bool(value)
    raise MapInventoryCodecError(f"{context} must be bool or integer 0/1")


def _optional_bytes(
    fields: Mapping[int, object],
    field_number: int,
    *,
    context: str,
) -> bytes | None:
    """Decode an optional protobuf bytes field."""
    if field_number not in fields:
        return None

    value = fields[field_number]
    if not isinstance(value, (bytes, bytearray, memoryview)):
        raise MapInventoryCodecError(f"{context} must be bytes-like")
    return bytes(value)


def _optional_text(
    fields: Mapping[int, object],
    field_number: int,
    *,
    context: str,
) -> str | bytes | None:
    """Validate an optional protobuf string as strict UTF-8."""
    if field_number not in fields:
        return None

    value = fields[field_number]
    if isinstance(value, str):
        try:
            value.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise MapInventoryCodecError(
                f"{context} must contain valid UTF-8"
            ) from exc
        return value
    if isinstance(value, (bytes, bytearray, memoryview)):
        encoded = bytes(value)
        try:
            encoded.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise MapInventoryCodecError(
                f"{context} must contain valid UTF-8"
            ) from exc
        return encoded
    raise MapInventoryCodecError(f"{context} must be str or UTF-8 bytes")


def _optional_float32_source(
    fields: Mapping[int, object],
    field_number: int,
    *,
    context: str,
) -> int | float | None:
    """Validate blackboxprotobuf's two representations of a float field."""
    if field_number not in fields:
        return None

    value = fields[field_number]
    if type(value) is int:
        if not 0 <= value <= _UINT32_MAX:
            raise MapInventoryCodecError(
                f"{context} fixed32 bits must be uint32"
            )
        return value
    if type(value) is not float or not math.isfinite(value):
        raise MapInventoryCodecError(
            f"{context} must be finite float or uint32 fixed32 bits"
        )
    try:
        packed = struct.pack("<f", value)
    except (OverflowError, struct.error) as exc:
        raise MapInventoryCodecError(
            f"{context} is outside finite float32 range"
        ) from exc
    if not math.isfinite(struct.unpack("<f", packed)[0]):
        raise MapInventoryCodecError(
            f"{context} is outside finite float32 range"
        )
    return value


def _optional_message(
    fields: Mapping[int, object],
    field_number: int,
    *,
    context: str,
) -> dict[int, object] | None:
    """Decode an optional nested message."""
    if field_number not in fields:
        return None
    return _normalize_fields(fields[field_number], context=context)


def _repeated_messages(
    fields: Mapping[int, object],
    field_number: int,
    *,
    context: str,
) -> tuple[dict[int, object], ...]:
    """Normalize a repeated message from blackboxprotobuf output."""
    if field_number not in fields:
        return ()

    value = fields[field_number]
    if isinstance(value, Mapping):
        values: tuple[object, ...] = (value,)
    elif isinstance(value, (list, tuple)):
        values = tuple(value)
    else:
        raise MapInventoryCodecError(
            f"{context} must be a message or message sequence"
        )

    return tuple(
        _normalize_fields(item, context=f"{context}[{index}]")
        for index, item in enumerate(values)
    )


def _string_field(
    output: dict[str, object],
    field_number: int,
    value: object | None,
) -> None:
    """Add one present, validated field to a ``MapData`` parser mapping."""
    if value is not None:
        output[str(field_number)] = value


def _decode_point_for_map(
    fields: Mapping[int, object],
    *,
    context: str,
) -> dict[str, object]:
    point: dict[str, object] = {}
    for field_number, name in ((1, "x"), (2, "y")):
        _string_field(
            point,
            field_number,
            _optional_float32_source(
                fields,
                field_number,
                context=f"{context}.{name}",
            ),
        )
    return point


def _decode_pose_for_map(
    fields: Mapping[int, object],
    *,
    context: str,
) -> dict[str, object]:
    pose: dict[str, object] = {}
    point_fields = _optional_message(
        fields,
        1,
        context=f"{context}.location",
    )
    if point_fields is not None:
        pose["1"] = _decode_point_for_map(
            point_fields,
            context=f"{context}.location",
        )
    _string_field(
        pose,
        2,
        _optional_float32_source(
            fields,
            2,
            context=f"{context}.theta",
        ),
    )
    return pose


def _decode_border_for_map(fields: Mapping[int, object]) -> dict[str, object]:
    border: dict[str, object] = {}
    for field_number, name in (
        (1, "bottom"),
        (2, "top"),
        (3, "left"),
        (4, "right"),
    ):
        _string_field(
            border,
            field_number,
            _optional_int32(
                fields,
                field_number,
                context=f"StaticMapPayload.border.{name}",
            ),
        )
    return border


def _decode_room_for_map(
    fields: Mapping[int, object],
    *,
    index: int,
) -> dict[str, object]:
    room: dict[str, object] = {}
    context = f"StaticMapPayload.roomInfos[{index}]"

    for field_number, name in (
        (1, "roomId"),
        (2, "type"),
        (8, "roomTypeId"),
    ):
        _string_field(
            room,
            field_number,
            _optional_uint(
                fields,
                field_number,
                bits=32,
                context=f"{context}.{name}",
            ),
        )
    _string_field(
        room,
        3,
        _optional_text(
            fields,
            3,
            context=f"{context}.customName",
        ),
    )
    _string_field(
        room,
        4,
        _optional_enum(
            fields,
            4,
            context=f"{context}.texture",
        ),
    )
    return room


def _decode_bounding_box_for_map(
    fields: Mapping[int, object],
    *,
    context: str,
) -> dict[str, object]:
    box: dict[str, object] = {}
    center_fields = _optional_message(
        fields,
        1,
        context=f"{context}.center",
    )
    if center_fields is not None:
        box["1"] = _decode_point_for_map(
            center_fields,
            context=f"{context}.center",
        )
    for field_number, name in ((2, "width"), (3, "height")):
        _string_field(
            box,
            field_number,
            _optional_float32_source(
                fields,
                field_number,
                context=f"{context}.{name}",
            ),
        )
    return box


def _decode_furniture_for_map(
    fields: Mapping[int, object],
    *,
    index: int,
) -> dict[str, object]:
    furniture: dict[str, object] = {}
    context = f"StaticMapPayload.visionData.furnitures[{index}]"
    _string_field(
        furniture,
        1,
        _optional_int32(fields, 1, context=f"{context}.id"),
    )
    _string_field(
        furniture,
        2,
        _optional_uint(
            fields,
            2,
            bits=32,
            context=f"{context}.furnitureType",
        ),
    )
    box_fields = _optional_message(
        fields,
        3,
        context=f"{context}.box",
    )
    if box_fields is not None:
        furniture["3"] = _decode_bounding_box_for_map(
            box_fields,
            context=f"{context}.box",
        )
    _string_field(
        furniture,
        4,
        _optional_float32_source(
            fields,
            4,
            context=f"{context}.angle",
        ),
    )
    return furniture


def _decode_vision_data_for_map(
    fields: Mapping[int, object],
) -> dict[str, object]:
    vision_data: dict[str, object] = {}
    furniture_fields = _repeated_messages(
        fields,
        1,
        context="StaticMapPayload.visionData.furnitures",
    )
    if 1 in fields:
        vision_data["1"] = [
            _decode_furniture_for_map(furniture, index=index)
            for index, furniture in enumerate(furniture_fields)
        ]
    return vision_data


def _decode_static_map_payload(
    raw_payload: object,
    *,
    product_key: str,
    context: str,
) -> StaticMapPayload:
    fields = _normalize_fields(raw_payload, context=context)
    parser_payload: dict[str, object] = {}

    for field_number, name in (
        (1, "mapId"),
        (3, "resolution"),
        (4, "width"),
        (5, "height"),
        (25, "rotateAngle"),
    ):
        _string_field(
            parser_payload,
            field_number,
            _optional_int32(
                fields,
                field_number,
                context=f"StaticMapPayload.{name}",
            ),
        )
    for field_number, bits, name in (
        (2, 32, "mapVersion"),
        (33, 32, "editVersion"),
        (34, 64, "mapGenerateTime"),
    ):
        _string_field(
            parser_payload,
            field_number,
            _optional_uint(
                fields,
                field_number,
                bits=bits,
                context=f"StaticMapPayload.{name}",
            ),
        )

    border_fields = _optional_message(
        fields,
        6,
        context="StaticMapPayload.border",
    )
    if border_fields is not None:
        parser_payload["6"] = _decode_border_for_map(border_fields)

    station_fields = _optional_message(
        fields,
        8,
        context="StaticMapPayload.station",
    )
    if station_fields is not None:
        parser_payload["8"] = _decode_pose_for_map(
            station_fields,
            context="StaticMapPayload.station",
        )

    room_fields = _repeated_messages(
        fields,
        12,
        context="StaticMapPayload.roomInfos",
    )
    if 12 in fields:
        parser_payload["12"] = [
            _decode_room_for_map(room, index=index)
            for index, room in enumerate(room_fields)
        ]

    _string_field(
        parser_payload,
        17,
        _optional_bytes(
            fields,
            17,
            context="StaticMapPayload.mapData",
        ),
    )

    vision_fields = _optional_message(
        fields,
        32,
        context="StaticMapPayload.visionData",
    )
    if vision_fields is not None:
        parser_payload["32"] = _decode_vision_data_for_map(vision_fields)

    return StaticMapPayload(
        map_data=MapData.from_response(
            {"2": parser_payload},
            product_key=product_key,
        ),
        raw_fields=_freeze_fields(fields),
    )


def _validate_product_key(product_key: object) -> str:
    if type(product_key) is not str:
        raise MapInventoryCodecError("product_key must be str")
    return product_key


def _validate_get_editable_map_request(
    request: GetEditableMapRequest,
) -> None:
    if type(request.include_carpet) is not bool:
        raise MapInventoryCodecError("include_carpet must be bool")
    if type(request.include_floor_plan) is not bool:
        raise MapInventoryCodecError("include_floor_plan must be bool")
    if type(request.request_format) is not MapRequestFormat:
        raise MapInventoryCodecError(
            "request_format must be a MapRequestFormat member"
        )
    if request.map_id is not None and (
        type(request.map_id) is not int
        or not 0 <= request.map_id <= _UINT32_MAX
    ):
        raise MapInventoryCodecError(
            f"map_id must be uint32 or None, got {request.map_id!r}"
        )


def _encode_varint(value: int) -> bytes:
    encoded = bytearray()
    while value > 0x7F:
        encoded.append((value & 0x7F) | 0x80)
        value >>= 7
    encoded.append(value)
    return bytes(encoded)


def _encode_varint_field(field_number: int, value: int) -> bytes:
    return _encode_varint(field_number << 3) + _encode_varint(value)


def encode_get_editable_map_request(request: GetEditableMapRequest) -> bytes:
    """Encode an APK-schema ``GetEditableMap.Request`` deterministically."""
    if type(request) is not GetEditableMapRequest:
        raise MapInventoryCodecError(
            "request must be a GetEditableMapRequest"
        )
    _validate_get_editable_map_request(request)

    encoded = bytearray()
    if request.map_id is not None:
        encoded.extend(_encode_varint_field(1, request.map_id))
    encoded.extend(_encode_varint_field(2, int(request.include_carpet)))
    encoded.extend(_encode_varint_field(3, int(request.include_floor_plan)))
    encoded.extend(_encode_varint_field(4, int(request.request_format)))
    return bytes(encoded)


def decode_get_all_reduced_maps_response(
    data: Mapping[object, object],
    *,
    product_key: str = "",
) -> GetAllReducedMapsResponse:
    """Decode the APK's saved/reduced-map inventory response."""
    product_key = _validate_product_key(product_key)
    fields = _normalize_fields(data, context="GetAllReducedMaps.Response")
    maps = _repeated_messages(
        fields,
        2,
        context="GetAllReducedMaps.Response.maps",
    )
    return GetAllReducedMapsResponse(
        result=_optional_enum(
            fields,
            1,
            context="GetAllReducedMaps.Response.result",
        ),
        maps=tuple(
            _decode_static_map_payload(
                raw_map,
                product_key=product_key,
                context=f"GetAllReducedMaps.Response.maps[{index}]",
            )
            for index, raw_map in enumerate(maps)
        ),
        raw_fields=_freeze_fields(fields),
    )


def decode_get_editable_map_response(
    data: Mapping[object, object],
    *,
    product_key: str = "",
) -> GetEditableMapResponse:
    """Decode the APK's editable-map response."""
    product_key = _validate_product_key(product_key)
    fields = _normalize_fields(data, context="GetEditableMap.Response")
    map_fields = _optional_message(
        fields,
        2,
        context="GetEditableMap.Response.map",
    )
    edit_config_fields = _optional_message(
        fields,
        4,
        context="GetEditableMap.Response.editConfig",
    )

    return GetEditableMapResponse(
        result=_optional_enum(
            fields,
            1,
            context="GetEditableMap.Response.result",
        ),
        map=(
            _decode_static_map_payload(
                map_fields,
                product_key=product_key,
                context="GetEditableMap.Response.map",
            )
            if map_fields is not None
            else None
        ),
        edit_version=_optional_uint(
            fields,
            3,
            bits=32,
            context="GetEditableMap.Response.editVersion",
        ),
        edit_config=(
            EditConfig(
                max_room_nums=_optional_uint(
                    edit_config_fields,
                    1,
                    bits=32,
                    context="GetEditableMap.Response.editConfig.maxRoomNums",
                ),
                raw_fields=_freeze_fields(edit_config_fields),
            )
            if edit_config_fields is not None
            else None
        ),
        raw_fields=_freeze_fields(fields),
    )


def decode_check_map_update_info_response(
    data: Mapping[object, object],
    *,
    product_key: str = "",
) -> CheckMapUpdateInfoResponse:
    """Decode ``map/check_map_update_info``'s APK response schema."""
    product_key = _validate_product_key(product_key)
    fields = _normalize_fields(data, context="CheckMapUpdate.Response")
    map_fields = _optional_message(
        fields,
        2,
        context="CheckMapUpdate.Response.map",
    )
    return CheckMapUpdateInfoResponse(
        result=_optional_bool(
            fields,
            1,
            context="CheckMapUpdate.Response.result",
        ),
        map=(
            _decode_static_map_payload(
                map_fields,
                product_key=product_key,
                context="CheckMapUpdate.Response.map",
            )
            if map_fields is not None
            else None
        ),
        raw_fields=_freeze_fields(fields),
    )


__all__ = [
    "CheckMapUpdateInfoResponse",
    "EditConfig",
    "GetAllReducedMapsResponse",
    "GetEditableMapRequest",
    "GetEditableMapResponse",
    "MapInventoryCodecError",
    "MapRequestFormat",
    "StaticMapPayload",
    "decode_check_map_update_info_response",
    "decode_get_all_reduced_maps_response",
    "decode_get_editable_map_response",
    "encode_get_editable_map_request",
]
