"""Strict read-only protobuf codec for Narwal consumables inventory.

The message fields and enum identities in this module were recovered from the
official Android app's generated protobuf metadata and AOT object table.
Unknown enum numbers remain integers so future values are never mislabeled.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

_INT32_MIN = -(1 << 31)
_INT32_MAX = (1 << 31) - 1
_UINT64_MAX = (1 << 64) - 1
_MAX_FIELD_NUMBER = (1 << 29) - 1
_SUPPORTED_WIRE_TYPES = frozenset((0, 1, 2, 5))


class ConsumablesCodecError(ValueError):
    """Raised for malformed or schema-invalid consumables protobuf data."""


class ConsumableMaintainItem(IntEnum):
    """APK-proven ``ConsumableMaintainItem`` values."""

    UNSPECIFIED = 0
    DUST_BOX = 1
    DUST_FILTER = 2
    DIRTY_WATER = 3
    WASH_RIBS = 4
    SMART_MODULE_FILTER = 5
    UNIVERSAL_WHEEL = 6
    CLIFF_SENSOR = 7
    SIDE_DISTANCE_SENSOR = 8
    WATER_TANK_SPONGE = 9
    ANTI_WINDING_BRUSH = 10
    SMART_MODULE_SPONGE = 11
    DUST_CONTAINER = 20


class ConsumableReplaceItem(IntEnum):
    """APK-proven ``ConsumableReplaceItem`` values."""

    UNSPECIFIED = 0
    DUST_FILTER = 1
    MOP = 2
    SIDE_BRUSH = 3
    CLEAR_WATER_FILTER = 4
    ROLLER_BRUSH = 5
    DETERGENT = 6
    SMART_MODULE_FILTER = 7
    DUST_BAG = 8
    STATION_BAG = 20
    SILVER_IONS = 21
    CURING_AGENT = 22
    HEAVY_DETERGENT = 23
    INNER_DUST_BOX = 24


@dataclass(frozen=True, slots=True)
class ConsumableRawField:
    """One unsupported protobuf field retained with its wire identity."""

    number: int
    wire_type: int
    value: int | bytes

    def __post_init__(self) -> None:
        if type(self.number) is not int or not 1 <= self.number <= _MAX_FIELD_NUMBER:
            raise ConsumablesCodecError(
                f"raw protobuf field number must be between 1 and {_MAX_FIELD_NUMBER}"
            )
        if type(self.wire_type) is not int or self.wire_type not in _SUPPORTED_WIRE_TYPES:
            raise ConsumablesCodecError(
                f"raw protobuf field {self.number} has unsupported wire type "
                f"{self.wire_type!r}"
            )

        if self.wire_type == 0:
            if type(self.value) is not int or not 0 <= self.value <= _UINT64_MAX:
                raise ConsumablesCodecError(
                    f"raw varint field {self.number} must contain a uint64"
                )
            return

        if not isinstance(self.value, (bytes, bytearray, memoryview)):
            raise ConsumablesCodecError(
                f"raw wire-type {self.wire_type} field {self.number} must contain bytes"
            )
        value = bytes(self.value)
        if self.wire_type == 1 and len(value) != 8:
            raise ConsumablesCodecError(
                f"raw fixed64 field {self.number} must contain exactly 8 bytes"
            )
        if self.wire_type == 5 and len(value) != 4:
            raise ConsumablesCodecError(
                f"raw fixed32 field {self.number} must contain exactly 4 bytes"
            )
        object.__setattr__(self, "value", value)


MaintainItemValue = ConsumableMaintainItem | int
ReplaceItemValue = ConsumableReplaceItem | int


def _freeze_unknown_fields(
    fields: tuple[ConsumableRawField, ...] | list[ConsumableRawField],
    *,
    known_fields: frozenset[int],
    context: str,
) -> tuple[ConsumableRawField, ...]:
    if not isinstance(fields, (tuple, list)):
        raise ConsumablesCodecError(f"{context}.unknown_fields must be a tuple or list")
    frozen = tuple(fields)
    for field in frozen:
        if type(field) is not ConsumableRawField:
            raise ConsumablesCodecError(
                f"{context}.unknown_fields entries must be ConsumableRawField values"
            )
        if field.number in known_fields:
            raise ConsumablesCodecError(
                f"{context} field {field.number} is known and cannot be stored as unknown"
            )
    return frozen


def _validate_signed_int32(value: object, *, context: str) -> int:
    if type(value) is not int or not _INT32_MIN <= value <= _INT32_MAX:
        raise ConsumablesCodecError(f"{context} must be an int32")
    return value


def _maintain_item(value: int) -> MaintainItemValue:
    try:
        return ConsumableMaintainItem(value)
    except ValueError:
        return value


def _replace_item(value: int) -> ReplaceItemValue:
    try:
        return ConsumableReplaceItem(value)
    except ValueError:
        return value


def _freeze_maintain_items(
    values: tuple[MaintainItemValue, ...] | list[MaintainItemValue],
) -> tuple[MaintainItemValue, ...]:
    if not isinstance(values, (tuple, list)):
        raise ConsumablesCodecError(
            "ConsumableInfoPayload.maintain_items must be a tuple or list"
        )
    frozen: list[MaintainItemValue] = []
    for value in values:
        if type(value) is ConsumableMaintainItem:
            frozen.append(value)
            continue
        raw_value = _validate_signed_int32(
            value,
            context="ConsumableInfoPayload.maintain_items entry",
        )
        frozen.append(_maintain_item(raw_value))
    return tuple(frozen)


def _freeze_replace_items(
    values: tuple[ReplaceItemValue, ...] | list[ReplaceItemValue],
) -> tuple[ReplaceItemValue, ...]:
    if not isinstance(values, (tuple, list)):
        raise ConsumablesCodecError(
            "ConsumableInfoPayload.replace_items must be a tuple or list"
        )
    frozen: list[ReplaceItemValue] = []
    for value in values:
        if type(value) is ConsumableReplaceItem:
            frozen.append(value)
            continue
        raw_value = _validate_signed_int32(
            value,
            context="ConsumableInfoPayload.replace_items entry",
        )
        frozen.append(_replace_item(raw_value))
    return tuple(frozen)


@dataclass(frozen=True, slots=True)
class ConsumableInfoPayload:
    """Decoded consumables inventory payload."""

    maintain_items: tuple[MaintainItemValue, ...] = ()
    replace_items: tuple[ReplaceItemValue, ...] = ()
    unknown_fields: tuple[ConsumableRawField, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "maintain_items",
            _freeze_maintain_items(self.maintain_items),
        )
        object.__setattr__(
            self,
            "replace_items",
            _freeze_replace_items(self.replace_items),
        )
        object.__setattr__(
            self,
            "unknown_fields",
            _freeze_unknown_fields(
                self.unknown_fields,
                known_fields=frozenset((1, 2)),
                context="ConsumableInfoPayload",
            ),
        )


@dataclass(frozen=True, slots=True)
class GetConsumableInfoResponse:
    """Decoded ``GetConsumableInfo.Response``."""

    consumable_info: ConsumableInfoPayload | None = None
    unknown_fields: tuple[ConsumableRawField, ...] = ()

    def __post_init__(self) -> None:
        if (
            self.consumable_info is not None
            and type(self.consumable_info) is not ConsumableInfoPayload
        ):
            raise ConsumablesCodecError(
                "GetConsumableInfoResponse.consumable_info must be "
                "ConsumableInfoPayload or None"
            )
        object.__setattr__(
            self,
            "unknown_fields",
            _freeze_unknown_fields(
                self.unknown_fields,
                known_fields=frozenset((1,)),
                context="GetConsumableInfoResponse",
            ),
        )


def _coerce_payload(
    payload: bytes | bytearray | memoryview,
    *,
    context: str,
) -> bytes:
    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise ConsumablesCodecError(f"{context} payload must be bytes-like")
    return bytes(payload)


def _encode_varint_for_validation(value: int) -> bytes:
    encoded = bytearray()
    while value > 0x7F:
        encoded.append((value & 0x7F) | 0x80)
        value >>= 7
    encoded.append(value)
    return bytes(encoded)


def _decode_varint(data: bytes, offset: int, *, context: str) -> tuple[int, int]:
    start = offset
    value = 0
    for byte_index in range(10):
        if offset >= len(data):
            raise ConsumablesCodecError(f"{context} contains a truncated protobuf varint")
        current = data[offset]
        offset += 1
        if byte_index == 9 and current > 1:
            raise ConsumablesCodecError(f"{context} protobuf varint exceeds uint64")
        value |= (current & 0x7F) << (byte_index * 7)
        if current < 0x80:
            if data[start:offset] != _encode_varint_for_validation(value):
                raise ConsumablesCodecError(
                    f"{context} contains a non-canonical protobuf varint"
                )
            return value, offset
    raise ConsumablesCodecError(f"{context} protobuf varint is too long")


def _parse_fields(
    payload: bytes | bytearray | memoryview,
    *,
    context: str,
) -> tuple[ConsumableRawField, ...]:
    data = _coerce_payload(payload, context=context)
    fields: list[ConsumableRawField] = []
    offset = 0
    while offset < len(data):
        key, offset = _decode_varint(data, offset, context=context)
        number = key >> 3
        wire_type = key & 0x07
        if not 1 <= number <= _MAX_FIELD_NUMBER:
            raise ConsumablesCodecError(
                f"{context} protobuf field number {number} is invalid"
            )
        if wire_type not in _SUPPORTED_WIRE_TYPES:
            raise ConsumablesCodecError(
                f"{context} field {number} has unsupported wire type {wire_type}"
            )

        value: int | bytes
        if wire_type == 0:
            value, offset = _decode_varint(data, offset, context=context)
        elif wire_type == 1:
            end = offset + 8
            if end > len(data):
                raise ConsumablesCodecError(
                    f"{context} fixed64 field {number} is truncated"
                )
            value = data[offset:end]
            offset = end
        elif wire_type == 2:
            length, offset = _decode_varint(data, offset, context=context)
            end = offset + length
            if end > len(data):
                raise ConsumablesCodecError(
                    f"{context} length-delimited field {number} is truncated"
                )
            value = data[offset:end]
            offset = end
        else:
            end = offset + 4
            if end > len(data):
                raise ConsumablesCodecError(
                    f"{context} fixed32 field {number} is truncated"
                )
            value = data[offset:end]
            offset = end

        fields.append(ConsumableRawField(number, wire_type, value))
    return tuple(fields)


def _wire_varint(field: ConsumableRawField) -> int:
    assert type(field.value) is int
    return field.value


def _wire_bytes(field: ConsumableRawField) -> bytes:
    assert type(field.value) is bytes
    return field.value


def _expect_wire(
    field: ConsumableRawField,
    expected: int | tuple[int, ...],
    *,
    context: str,
) -> None:
    expected_types = (expected,) if isinstance(expected, int) else expected
    if field.wire_type not in expected_types:
        expected_text = " or ".join(str(item) for item in expected_types)
        raise ConsumablesCodecError(
            f"{context} field {field.number} requires wire type {expected_text}, "
            f"got {field.wire_type}"
        )


def _decode_enum_int32(value: int, *, context: str) -> int:
    if value <= _INT32_MAX:
        return value
    if value >= (1 << 64) + _INT32_MIN:
        return value - (1 << 64)
    raise ConsumablesCodecError(f"{context} protobuf value is outside int32 range")


def _decode_repeated_enums(
    field: ConsumableRawField,
    *,
    context: str,
) -> tuple[int, ...]:
    _expect_wire(field, (0, 2), context=context)
    if field.wire_type == 0:
        return (
            _decode_enum_int32(
                _wire_varint(field),
                context=context,
            ),
        )

    packed = _wire_bytes(field)
    values: list[int] = []
    offset = 0
    while offset < len(packed):
        value, offset = _decode_varint(packed, offset, context=context)
        values.append(_decode_enum_int32(value, context=context))
    return tuple(values)


def decode_consumable_info_payload(
    payload: bytes | bytearray | memoryview,
) -> ConsumableInfoPayload:
    """Decode packed or unpacked consumable enum inventories."""
    maintain_items: list[MaintainItemValue] = []
    replace_items: list[ReplaceItemValue] = []
    unknown_fields: list[ConsumableRawField] = []

    for field in _parse_fields(payload, context="ConsumableInfoPayload"):
        if field.number == 1:
            maintain_items.extend(
                _maintain_item(value)
                for value in _decode_repeated_enums(
                    field,
                    context="ConsumableInfoPayload.maintainItems",
                )
            )
        elif field.number == 2:
            replace_items.extend(
                _replace_item(value)
                for value in _decode_repeated_enums(
                    field,
                    context="ConsumableInfoPayload.replaceItems",
                )
            )
        else:
            unknown_fields.append(field)

    return ConsumableInfoPayload(
        maintain_items=tuple(maintain_items),
        replace_items=tuple(replace_items),
        unknown_fields=tuple(unknown_fields),
    )


def decode_get_consumable_info_response(
    payload: bytes | bytearray | memoryview,
) -> GetConsumableInfoResponse:
    """Decode the APK-schema ``GetConsumableInfo.Response``."""
    consumable_info: ConsumableInfoPayload | None = None
    unknown_fields: list[ConsumableRawField] = []

    for field in _parse_fields(payload, context="GetConsumableInfo.Response"):
        if field.number != 1:
            unknown_fields.append(field)
            continue
        _expect_wire(field, 2, context="GetConsumableInfo.Response")
        if consumable_info is not None:
            raise ConsumablesCodecError(
                "GetConsumableInfo.Response contains duplicate consumableInfo"
            )
        consumable_info = decode_consumable_info_payload(_wire_bytes(field))

    return GetConsumableInfoResponse(
        consumable_info=consumable_info,
        unknown_fields=tuple(unknown_fields),
    )


__all__ = [
    "ConsumableInfoPayload",
    "ConsumableMaintainItem",
    "ConsumableRawField",
    "ConsumableReplaceItem",
    "ConsumablesCodecError",
    "GetConsumableInfoResponse",
    "MaintainItemValue",
    "ReplaceItemValue",
    "decode_consumable_info_payload",
    "decode_get_consumable_info_response",
]
