"""Tests for strict saved/editable map inventory codecs."""

from __future__ import annotations

import struct
from collections.abc import Callable
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import pytest

from narwal_client.map_inventory import (
    GetEditableMapRequest,
    MapInventoryCodecError,
    MapRequestFormat,
    decode_check_map_update_info_response,
    decode_get_all_reduced_maps_response,
    decode_get_editable_map_response,
    encode_get_editable_map_request,
)


def _float32_bits(value: float) -> int:
    return struct.unpack("<I", struct.pack("<f", value))[0]


def _static_map_fixture(map_id: int = 17) -> dict[str, object]:
    return {
        "1": map_id,
        "2": 3,
        "3": 5,
        "4": 2,
        "5": 2,
        "6": {
            "1": 100,
            "2": 101,
            "3": 200,
            "4": 201,
            "90": b"future border field",
        },
        "8": {
            "1": {
                "1": _float32_bits(200.5),
                "2": _float32_bits(100.5),
            },
            "2": _float32_bits(0.25),
        },
        "12": {
            "1": 7,
            "2": 6,
            "3": b"Kitchen",
            "4": 1,
            "8": 2,
            "91": b"future room field",
        },
        "17": bytearray(b"\x01\x02\x03"),
        "25": 90,
        "32": {
            "1": {
                "1": 4,
                "2": 14,
                "3": {
                    "1": {
                        "1": _float32_bits(205.0),
                        "2": _float32_bits(105.0),
                    },
                    "2": _float32_bits(8.0),
                    "3": _float32_bits(4.0),
                },
                "4": _float32_bits(45.0),
                "92": b"future furniture field",
            },
            "93": b"future vision field",
        },
        "33": 8,
        "34": 1 << 40,
        "99": {"1": bytearray(b"future map field")},
    }


def test_map_request_format_values_match_apk_enum() -> None:
    assert int(MapRequestFormat.COMPRESSED_GRID) == 0
    assert int(MapRequestFormat.CONTOUR) == 1


def test_encodes_get_editable_map_request_exactly() -> None:
    request = GetEditableMapRequest(
        map_id=300,
        include_carpet=True,
        include_floor_plan=False,
        request_format=MapRequestFormat.CONTOUR,
    )

    assert encode_get_editable_map_request(request) == bytes.fromhex(
        "08 ac 02 "  # field 1: mapId=300
        "10 01 "  # field 2: include carpet
        "18 00 "  # field 3: do not include floor-plan data
        "20 01"  # field 4: contour
    )


def test_get_editable_map_request_omits_only_absent_map_id() -> None:
    request = GetEditableMapRequest(
        include_carpet=False,
        include_floor_plan=True,
        request_format=MapRequestFormat.COMPRESSED_GRID,
    )

    assert encode_get_editable_map_request(request) == bytes.fromhex(
        "10 00 18 01 20 00"
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {
            "include_carpet": 1,
            "include_floor_plan": False,
            "request_format": MapRequestFormat.COMPRESSED_GRID,
        },
        {
            "include_carpet": False,
            "include_floor_plan": 0,
            "request_format": MapRequestFormat.COMPRESSED_GRID,
        },
        {
            "include_carpet": False,
            "include_floor_plan": False,
            "request_format": 0,
        },
        {
            "include_carpet": False,
            "include_floor_plan": False,
            "request_format": MapRequestFormat.COMPRESSED_GRID,
            "map_id": True,
        },
        {
            "include_carpet": False,
            "include_floor_plan": False,
            "request_format": MapRequestFormat.COMPRESSED_GRID,
            "map_id": -1,
        },
        {
            "include_carpet": False,
            "include_floor_plan": False,
            "request_format": MapRequestFormat.COMPRESSED_GRID,
            "map_id": 1 << 32,
        },
    ],
)
def test_get_editable_map_request_rejects_invalid_values(
    kwargs: dict[str, Any],
) -> None:
    with pytest.raises(MapInventoryCodecError):
        GetEditableMapRequest(**kwargs)


def test_encoder_requires_typed_request() -> None:
    with pytest.raises(MapInventoryCodecError, match="GetEditableMapRequest"):
        encode_get_editable_map_request(object())  # type: ignore[arg-type]


def test_decodes_reduced_map_inventory_with_existing_map_parser() -> None:
    response = decode_get_all_reduced_maps_response(
        {
            "1": 0,
            "2": [
                _static_map_fixture(),
                {"1": 18, "2": 4},
            ],
            "200": {"1": bytearray(b"future response field")},
        },
        product_key="AX15-product",
    )

    assert response.result == 0
    assert len(response.maps) == 2

    saved_map = response.maps[0]
    map_data = saved_map.map_data
    assert map_data.map_id == 17
    assert map_data.map_version == 3
    assert map_data.edit_version == 8
    assert map_data.generation_time == 1 << 40
    assert map_data.resolution == 5
    assert map_data.width == 2
    assert map_data.height == 2
    assert map_data.origin_x == 200
    assert map_data.origin_y == 100
    assert map_data.border_top == 101
    assert map_data.border_right == 201
    assert map_data.rotate_angle == 90
    assert map_data.compressed_map == b"\x01\x02\x03"
    assert map_data.dock_x == pytest.approx(0.5)
    assert map_data.dock_y == pytest.approx(0.5)

    assert len(map_data.rooms) == 1
    assert map_data.rooms[0].room_id == 7
    assert map_data.rooms[0].name == "Kitchen"
    assert map_data.rooms[0].room_sub_type == 6
    assert map_data.rooms[0].category == 1
    assert map_data.rooms[0].instance_index == 2
    assert map_data.rooms[0].model_key == "AX15-product"

    assert len(map_data.obstacles) == 1
    assert map_data.obstacles[0].id == 4
    assert map_data.obstacles[0].type_id == 14
    assert map_data.obstacles[0].center_x == pytest.approx(205.0)
    assert map_data.obstacles[0].center_y == pytest.approx(105.0)
    assert map_data.obstacles[0].width == pytest.approx(8.0)
    assert map_data.obstacles[0].height == pytest.approx(4.0)
    assert map_data.obstacles[0].angle == pytest.approx(45.0)

    assert response.maps[1].map_data.map_id == 18
    assert saved_map.raw_fields[99]["1"] == b"future map field"
    assert saved_map.raw_fields[6]["90"] == b"future border field"
    assert saved_map.raw_fields[12]["91"] == b"future room field"
    assert response.raw_fields[200]["1"] == b"future response field"


def test_accepts_singleton_mapping_for_repeated_maps_and_rooms() -> None:
    response = decode_get_all_reduced_maps_response(
        {
            2: {
                1: 9,
                12: {
                    1: 3,
                    3: b"Office",
                },
            }
        }
    )

    assert len(response.maps) == 1
    assert response.maps[0].map_data.map_id == 9
    assert [room.name for room in response.maps[0].map_data.rooms] == ["Office"]


def test_decodes_editable_map_metadata_and_edit_config() -> None:
    response = decode_get_editable_map_response(
        {
            1: 1,
            2: _static_map_fixture(22),
            3: 15,
            4: {
                1: 30,
                9: {"1": bytearray(b"future edit setting")},
            },
            201: b"future response field",
        }
    )

    assert response.result == 1
    assert response.map is not None
    assert response.map.map_data.map_id == 22
    assert response.edit_version == 15
    assert response.edit_config is not None
    assert response.edit_config.max_room_nums == 30
    assert response.edit_config.raw_fields[9]["1"] == b"future edit setting"
    assert response.raw_fields[201] == b"future response field"


def test_absent_editable_map_fields_are_not_invented() -> None:
    response = decode_get_editable_map_response({1: 0})

    assert response.result == 0
    assert response.map is None
    assert response.edit_version is None
    assert response.edit_config is None


@pytest.mark.parametrize(
    ("raw_result", "expected"),
    [
        (True, True),
        (False, False),
        (1, True),
        (0, False),
    ],
)
def test_decodes_check_map_update_bool_from_typed_or_schema_less_output(
    raw_result: bool | int,
    expected: bool,
) -> None:
    response = decode_check_map_update_info_response(
        {
            1: raw_result,
            2: {"1": 44},
            88: {"1": b"future response field"},
        }
    )

    assert response.result is expected
    assert response.map is not None
    assert response.map.map_data.map_id == 44
    assert response.raw_fields[88]["1"] == b"future response field"


def test_raw_fields_and_response_values_are_immutable() -> None:
    response = decode_get_editable_map_response(
        {
            2: {
                1: 7,
                99: {"1": [bytearray(b"future")]},
            },
            4: {1: 10},
        }
    )
    assert response.map is not None

    with pytest.raises(FrozenInstanceError):
        response.edit_version = 3  # type: ignore[misc]
    with pytest.raises(TypeError):
        response.raw_fields[7] = "new"  # type: ignore[index]
    with pytest.raises(TypeError):
        response.map.raw_fields[99]["1"] = "new"  # type: ignore[index]
    with pytest.raises(TypeError):
        response.edit_config.raw_fields[1] = 3  # type: ignore[union-attr,index]

    assert response.map.raw_fields[99]["1"] == (b"future",)


@pytest.mark.parametrize(
    ("decoder", "payload"),
    [
        (decode_get_all_reduced_maps_response, []),
        (decode_get_all_reduced_maps_response, {True: 0}),
        (decode_get_all_reduced_maps_response, {"01": 0}),
        (decode_get_all_reduced_maps_response, {1: 0, "1": 1}),
        (decode_get_all_reduced_maps_response, {1: True}),
        (decode_get_all_reduced_maps_response, {2: b"not maps"}),
        (decode_get_all_reduced_maps_response, {2: [{1: 1}, b"not a map"]}),
        (decode_get_all_reduced_maps_response, {2: {1: True}}),
        (decode_get_all_reduced_maps_response, {2: {1: 1 << 31}}),
        (decode_get_all_reduced_maps_response, {2: {2: -1}}),
        (decode_get_all_reduced_maps_response, {2: {3: "5"}}),
        (decode_get_all_reduced_maps_response, {2: {6: b"not border"}}),
        (decode_get_all_reduced_maps_response, {2: {6: {1: True}}}),
        (decode_get_all_reduced_maps_response, {2: {8: {1: "not point"}}}),
        (
            decode_get_all_reduced_maps_response,
            {2: {8: {1: {1: float("inf")}}}},
        ),
        (decode_get_all_reduced_maps_response, {2: {12: 3}}),
        (decode_get_all_reduced_maps_response, {2: {12: [{3: b"\xff"}]}}),
        (decode_get_all_reduced_maps_response, {2: {17: "not bytes"}}),
        (decode_get_all_reduced_maps_response, {2: {32: b"not vision"}}),
        (
            decode_get_all_reduced_maps_response,
            {2: {32: {1: [{3: {2: "not width"}}]}}},
        ),
        (decode_get_editable_map_response, {2: b"not a map"}),
        (decode_get_editable_map_response, {3: True}),
        (decode_get_editable_map_response, {3: -1}),
        (decode_get_editable_map_response, {4: b"not edit config"}),
        (decode_get_editable_map_response, {4: {1: True}}),
        (decode_get_editable_map_response, {4: {1: 1 << 32}}),
        (decode_check_map_update_info_response, {1: 2}),
        (decode_check_map_update_info_response, {1: "true"}),
        (decode_check_map_update_info_response, {2: b"not a map"}),
    ],
)
def test_malformed_known_fields_fail_closed(
    decoder: Callable[[Any], object],
    payload: object,
) -> None:
    with pytest.raises(MapInventoryCodecError):
        decoder(payload)


def test_unknown_fields_and_unknown_enum_values_are_preserved() -> None:
    marker = object()
    response = decode_get_all_reduced_maps_response(
        {
            1: 777,
            2: {
                1: 4,
                199: marker,
            },
        }
    )

    assert response.result == 777
    assert response.maps[0].raw_fields[199] is marker


def test_product_key_must_be_text() -> None:
    with pytest.raises(MapInventoryCodecError, match="product_key"):
        decode_get_all_reduced_maps_response({}, product_key=3)  # type: ignore[arg-type]


def test_root_and_vendored_map_inventory_codecs_are_byte_identical() -> None:
    root = Path(__file__).parents[1]

    assert (root / "narwal_client" / "map_inventory.py").read_bytes() == (
        root
        / "custom_components"
        / "narwal"
        / "narwal_client"
        / "map_inventory.py"
    ).read_bytes()
