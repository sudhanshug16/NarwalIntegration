"""Tests for strict, read-only consumables inventory decoding."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from narwal_client.consumables import (
    ConsumableInfoPayload,
    ConsumableMaintainItem,
    ConsumableRawField,
    ConsumableReplaceItem,
    ConsumablesCodecError,
    decode_consumable_info_payload,
    decode_get_consumable_info_response,
)


def _varint(value: int) -> bytes:
    if value < 0:
        value += 1 << 64
    encoded = bytearray()
    while value > 0x7F:
        encoded.append((value & 0x7F) | 0x80)
        value >>= 7
    encoded.append(value)
    return bytes(encoded)


def _field(number: int, wire_type: int, value: int | bytes) -> bytes:
    encoded = _varint((number << 3) | wire_type)
    if wire_type == 0:
        assert type(value) is int
        return encoded + _varint(value)
    assert type(value) is bytes
    if wire_type == 2:
        return encoded + _varint(len(value)) + value
    return encoded + value


def _response(info: bytes, *unknown: bytes) -> bytes:
    return _field(1, 2, info) + b"".join(unknown)


def test_apk_proven_maintenance_enum_names_and_values() -> None:
    assert {name: int(value) for name, value in ConsumableMaintainItem.__members__.items()} == {
        "UNSPECIFIED": 0,
        "DUST_BOX": 1,
        "DUST_FILTER": 2,
        "DIRTY_WATER": 3,
        "WASH_RIBS": 4,
        "SMART_MODULE_FILTER": 5,
        "UNIVERSAL_WHEEL": 6,
        "CLIFF_SENSOR": 7,
        "SIDE_DISTANCE_SENSOR": 8,
        "WATER_TANK_SPONGE": 9,
        "ANTI_WINDING_BRUSH": 10,
        "SMART_MODULE_SPONGE": 11,
        "DUST_CONTAINER": 20,
    }


def test_apk_proven_replacement_enum_names_and_values() -> None:
    assert {name: int(value) for name, value in ConsumableReplaceItem.__members__.items()} == {
        "UNSPECIFIED": 0,
        "DUST_FILTER": 1,
        "MOP": 2,
        "SIDE_BRUSH": 3,
        "CLEAR_WATER_FILTER": 4,
        "ROLLER_BRUSH": 5,
        "DETERGENT": 6,
        "SMART_MODULE_FILTER": 7,
        "DUST_BAG": 8,
        "STATION_BAG": 20,
        "SILVER_IONS": 21,
        "CURING_AGENT": 22,
        "HEAVY_DETERGENT": 23,
        "INNER_DUST_BOX": 24,
    }


def test_decodes_mixed_packed_and_unpacked_inventory_in_wire_order() -> None:
    packed_maintain = b"".join(
        _varint(value) for value in (2, 20, 300, -1)
    )
    packed_replace = b"".join(_varint(value) for value in (0, 21, 24, 19))
    info = b"".join(
        (
            _field(1, 0, 1),
            _field(1, 2, packed_maintain),
            _field(1, 0, 4),
            _field(2, 2, packed_replace),
            _field(2, 0, 7),
        )
    )

    decoded = decode_get_consumable_info_response(_response(info))

    assert decoded.consumable_info is not None
    assert decoded.consumable_info.maintain_items == (
        ConsumableMaintainItem.DUST_BOX,
        ConsumableMaintainItem.DUST_FILTER,
        ConsumableMaintainItem.DUST_CONTAINER,
        300,
        -1,
        ConsumableMaintainItem.WASH_RIBS,
    )
    assert [type(value) for value in decoded.consumable_info.maintain_items] == [
        ConsumableMaintainItem,
        ConsumableMaintainItem,
        ConsumableMaintainItem,
        int,
        int,
        ConsumableMaintainItem,
    ]
    assert decoded.consumable_info.replace_items == (
        ConsumableReplaceItem.UNSPECIFIED,
        ConsumableReplaceItem.SILVER_IONS,
        ConsumableReplaceItem.INNER_DUST_BOX,
        19,
        ConsumableReplaceItem.SMART_MODULE_FILTER,
    )
    assert type(decoded.consumable_info.replace_items[3]) is int


def test_missing_and_empty_inventory_are_distinct() -> None:
    missing = decode_get_consumable_info_response(b"")
    empty = decode_get_consumable_info_response(_response(b""))

    assert missing.consumable_info is None
    assert empty.consumable_info == ConsumableInfoPayload()


def test_unknown_fields_preserve_wire_identity_and_are_frozen() -> None:
    info = b"".join(
        (
            _field(1, 0, 1),
            _field(9, 0, (1 << 64) - 1),
            _field(10, 2, b"future"),
            _field(11, 1, bytes.fromhex("01 02 03 04 05 06 07 08")),
            _field(12, 5, bytes.fromhex("09 0a 0b 0c")),
        )
    )
    response_unknown = _field(8, 2, b"response future")

    decoded = decode_get_consumable_info_response(
        _response(info, response_unknown)
    )

    assert decoded.unknown_fields == (
        ConsumableRawField(8, 2, b"response future"),
    )
    assert decoded.consumable_info is not None
    assert decoded.consumable_info.unknown_fields == (
        ConsumableRawField(9, 0, (1 << 64) - 1),
        ConsumableRawField(10, 2, b"future"),
        ConsumableRawField(
            11,
            1,
            bytes.fromhex("01 02 03 04 05 06 07 08"),
        ),
        ConsumableRawField(12, 5, bytes.fromhex("09 0a 0b 0c")),
    )

    with pytest.raises(FrozenInstanceError):
        decoded.consumable_info = None  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        decoded.consumable_info.unknown_fields[0].value = 1  # type: ignore[misc]


def test_bytes_like_inputs_are_accepted_and_copied() -> None:
    data = bytearray(_field(1, 0, 1))

    from_bytearray = decode_consumable_info_payload(data)
    from_memoryview = decode_consumable_info_payload(memoryview(data))
    data[:] = b""

    assert from_bytearray.maintain_items == (ConsumableMaintainItem.DUST_BOX,)
    assert from_memoryview == from_bytearray


def test_model_constructors_freeze_lists_and_normalize_known_ints() -> None:
    maintain: list[ConsumableMaintainItem | int] = [1, 300]
    replace: list[ConsumableReplaceItem | int] = [21, 19]
    unknown = [ConsumableRawField(9, 2, bytearray(b"future"))]

    payload = ConsumableInfoPayload(maintain, replace, unknown)
    maintain.append(2)
    replace.append(2)
    unknown.clear()

    assert payload.maintain_items == (ConsumableMaintainItem.DUST_BOX, 300)
    assert payload.replace_items == (ConsumableReplaceItem.SILVER_IONS, 19)
    assert payload.unknown_fields == (ConsumableRawField(9, 2, b"future"),)


@pytest.mark.parametrize(
    ("decoder", "payload", "message"),
    [
        (decode_get_consumable_info_response, b"\x80", "truncated"),
        (decode_get_consumable_info_response, b"\x88\x00\x00", "non-canonical"),
        (
            decode_get_consumable_info_response,
            b"\xff\xff\xff\xff\xff\xff\xff\xff\xff\x02",
            "exceeds uint64",
        ),
        (decode_get_consumable_info_response, b"\x00", "field number 0"),
        (decode_get_consumable_info_response, b"\x0b", "unsupported wire type 3"),
        (decode_get_consumable_info_response, b"\x0c", "unsupported wire type 4"),
        (decode_get_consumable_info_response, b"\x0e", "unsupported wire type 6"),
        (decode_get_consumable_info_response, b"\x0f", "unsupported wire type 7"),
        (decode_get_consumable_info_response, b"\x09\x00", "fixed64"),
        (decode_get_consumable_info_response, b"\x0d\x00", "fixed32"),
        (decode_get_consumable_info_response, b"\x0a\x02\x00", "length-delimited"),
        (decode_get_consumable_info_response, b"\x08\x00", "requires wire type 2"),
        (
            decode_get_consumable_info_response,
            _response(b"") + _response(b""),
            "duplicate",
        ),
        (decode_consumable_info_payload, b"\x09" + b"\x00" * 8, "wire type"),
        (decode_consumable_info_payload, b"\x15" + b"\x00" * 4, "wire type"),
        (decode_consumable_info_payload, b"\x0a\x01\x80", "truncated"),
        (decode_consumable_info_payload, b"\x0a\x02\x81\x00", "non-canonical"),
        (
            decode_consumable_info_payload,
            _field(1, 0, 1 << 31),
            "outside int32",
        ),
        (
            decode_consumable_info_payload,
            _field(2, 0, 1 << 63),
            "outside int32",
        ),
        (
            decode_consumable_info_payload,
            _field(1, 2, _varint(1 << 31)),
            "outside int32",
        ),
    ],
)
def test_malformed_wire_fails_closed(
    decoder: Callable[[bytes], object],
    payload: bytes,
    message: str,
) -> None:
    with pytest.raises(ConsumablesCodecError, match=message):
        decoder(payload)


def test_non_bytes_input_fails_closed() -> None:
    with pytest.raises(ConsumablesCodecError, match="bytes-like"):
        decode_get_consumable_info_response("not bytes")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "factory",
    [
        lambda: ConsumableInfoPayload(maintain_items=[True]),
        lambda: ConsumableInfoPayload(replace_items=[1 << 31]),
        lambda: ConsumableInfoPayload(
            unknown_fields=[ConsumableRawField(1, 0, 1)]
        ),
        lambda: ConsumableRawField(0, 0, 1),
        lambda: ConsumableRawField(3, 3, b""),
        lambda: ConsumableRawField(3, 1, b"short"),
        lambda: ConsumableRawField(3, 5, b"short"),
    ],
)
def test_invalid_model_values_fail_closed(factory: Callable[[], object]) -> None:
    with pytest.raises(ConsumablesCodecError):
        factory()


def test_root_and_vendored_consumables_codecs_are_byte_identical() -> None:
    root = Path(__file__).resolve().parents[1]

    assert (root / "narwal_client" / "consumables.py").read_bytes() == (
        root
        / "custom_components"
        / "narwal"
        / "narwal_client"
        / "consumables.py"
    ).read_bytes()
