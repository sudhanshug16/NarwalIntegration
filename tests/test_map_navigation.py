"""Safety-focused tests for raw-map point-navigation geometry."""

from __future__ import annotations

import math
import struct
import zlib
from dataclasses import replace

import pytest

from narwal_client.models import (
    MapBorder,
    MapCellType,
    MapData,
    ObstacleInfo,
    RoomInfo,
    classify_map_pixel,
)


def _encode_varint(value: int) -> bytes:
    result = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            result.append(byte | 0x80)
        else:
            result.append(byte)
            return bytes(result)


def _compressed_grid(values: list[int]) -> bytes:
    packed = b"".join(_encode_varint(value) for value in values)
    return zlib.compress(b"\x0a" + _encode_varint(len(packed)) + packed)


def _float32_bits(value: float) -> int:
    return struct.unpack("I", struct.pack("f", value))[0]


def _geometry_map(**overrides: object) -> MapData:
    values: dict[str, object] = {
        "width": 3,
        "height": 3,
        "resolution": 60,
        "compressed_map": _compressed_grid([(1 << 8)] * 9),
        "origin_x": 0,
        "origin_y": 0,
        "border_top": 2,
        "border_right": 2,
        "map_id": 11,
        "map_version": 12,
        "edit_version": 13,
        "generation_time": 14,
        "rotate_angle": 0,
    }
    values.update(overrides)
    return MapData(**values)


def test_static_map_schema_and_real_border_fixture() -> None:
    decoded = {
        "2": {
            "1": 123,
            "2": 456,
            "3": 60,
            "4": 341,
            "5": 494,
            "6": {"1": -341, "2": 152, "3": -280, "4": 60},
            "8": {
                "1": {
                    "1": _float32_bits(-8.0188),
                    "2": _float32_bits(0.221),
                },
                "2": _float32_bits(0.036),
            },
            "17": b"map-bytes",
            "25": 90,
            "33": 944,
            "34": 1_740_000_000,
        }
    }

    map_data = MapData.from_response(decoded)

    assert map_data.map_id == 123
    assert map_data.map_version == 456
    assert map_data.border == MapBorder(
        bottom=-341,
        top=152,
        left=-280,
        right=60,
    )
    assert map_data.border.is_valid_for(341, 494)
    assert map_data.origin_x == -280
    assert map_data.origin_y == -341
    assert map_data.rotate_angle == 90
    assert map_data.edit_version == 944
    assert map_data.area == 944
    assert map_data.generation_time == 1_740_000_000
    assert map_data.created_at == 1_740_000_000
    assert map_data.dock_x == pytest.approx(271.9812, abs=1e-4)
    assert map_data.dock_y == pytest.approx(341.221, abs=1e-4)


def test_existing_map_data_positional_order_is_unchanged() -> None:
    map_data = MapData(
        10,
        20,
        5,
        [],
        b"map",
        200,
        1234,
        1.5,
        2.5,
        3,
        4,
        [],
        {"source": "test"},
        99,
    )

    assert map_data.map_id == 99
    assert map_data.map_version == 0
    assert map_data.border_top == 0
    assert map_data.edit_version == 0


def test_world_grid_and_unrotated_image_corner_transforms() -> None:
    map_data = MapData(
        width=341,
        height=494,
        resolution=60,
        origin_x=-280,
        origin_y=-341,
        border_top=152,
        border_right=60,
        rotate_angle=270,
    )

    assert map_data.world_to_grid(-280, -341) == (0, 0)
    assert map_data.world_to_grid(60, 152) == (340, 493)
    assert map_data.grid_to_world(0, 0) == (-280, -341)
    assert map_data.grid_to_world(340, 493) == (60, 152)
    assert map_data.grid_to_image(0, 493) == (0, 0)
    assert map_data.grid_to_image(340, 0) == (340, 493)
    assert map_data.image_to_grid_cell(0, 0) == (0, 493)
    assert map_data.image_to_grid_cell(340, 493) == (340, 0)

    world = (-8.0188, 0.221)
    grid = map_data.world_to_grid(*world)
    assert grid == pytest.approx((271.9812, 341.221))
    assert grid is not None
    assert map_data.grid_to_world(*grid) == pytest.approx(world)


def test_normalized_image_coordinates_are_scale_independent() -> None:
    map_data = _geometry_map()
    grid_x = 1
    grid_y = 0
    image_row = map_data.height - 1 - grid_y
    normalized_x = (grid_x + 0.5) / map_data.width
    normalized_y = (image_row + 0.5) / map_data.height

    expected_world = map_data.grid_to_world(grid_x, grid_y)
    assert map_data.normalized_image_to_world(normalized_x, normalized_y) == expected_world

    for scale in (1, 4):
        image = map_data.grid_to_image(grid_x, grid_y, scale)
        assert image is not None
        assert map_data.image_to_grid_cell(
            image[0] + scale - 0.01,
            image[1] + scale - 0.01,
            scale,
        ) == (grid_x, grid_y)


def test_normalized_image_top_left_and_bottom_right() -> None:
    map_data = _geometry_map(origin_x=-10, origin_y=-20, border_right=-8, border_top=-18)
    below_one = math.nextafter(1.0, 0.0)

    assert map_data.normalized_image_to_world(0, 0) == (-10, -18)
    assert map_data.normalized_image_to_world(below_one, below_one) == (-8, -20)


@pytest.mark.parametrize(
    ("normalized_x", "normalized_y"),
    [
        (-0.001, 0.5),
        (0.5, -0.001),
        (1.0, 0.5),
        (0.5, 1.0),
        (math.nan, 0.5),
        (0.5, math.inf),
    ],
)
def test_normalized_image_rejects_invalid_or_nonfinite_edges(
    normalized_x: float, normalized_y: float
) -> None:
    assert _geometry_map().normalized_image_to_world(normalized_x, normalized_y) is None


def test_transforms_fail_closed_for_invalid_border_and_coordinates() -> None:
    invalid = _geometry_map(border_top=3)

    assert not invalid.has_valid_navigation_geometry()
    assert invalid.navigation_revision() is None
    assert invalid.world_to_grid(0, 0) is None
    assert invalid.grid_to_world(0, 0) is None
    assert invalid.grid_to_image(0, 0) is None
    assert invalid.image_to_grid_cell(0, 0) is None

    valid = _geometry_map()
    assert valid.world_to_grid(math.nan, 0) is None
    assert valid.world_to_grid(3, 0) is None
    assert valid.grid_to_world(math.inf, 0) is None
    assert valid.grid_to_world(3, 0) is None
    assert valid.grid_to_image(0, 0, 0) is None
    assert valid.image_to_grid_cell(3, 0) is None
    assert valid.image_to_grid_cell(0, 3) is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0, MapCellType.UNKNOWN),
        (0x20, MapCellType.UNASSIGNED_FLOOR),
        (0x28, MapCellType.OBSTACLE),
        ((1 << 8) | 0x08, MapCellType.OBSTACLE),
        ((1 << 8) | 0x10, MapCellType.WALL),
        (1 << 8, MapCellType.ROOM_FLOOR),
    ],
)
def test_exact_map_pixel_classification(value: int, expected: MapCellType) -> None:
    assert classify_map_pixel(value) is expected


def test_grid_classification_and_clearance_fail_closed() -> None:
    floor = 1 << 8
    values = [floor] * 25
    values[0] = 0
    values[1] = 0x20
    values[2] = 0x28
    values[3] = floor | 0x10
    map_data = _geometry_map(
        width=5,
        height=5,
        border_top=4,
        border_right=4,
        compressed_map=_compressed_grid(values),
    )

    assert map_data.classify_grid_cell(0, 0) is MapCellType.UNKNOWN
    assert map_data.classify_grid_cell(1, 0) is MapCellType.UNASSIGNED_FLOOR
    assert map_data.classify_grid_cell(2, 0) is MapCellType.OBSTACLE
    assert map_data.classify_grid_cell(3, 0) is MapCellType.WALL
    assert map_data.classify_grid_cell(2, 2) is MapCellType.ROOM_FLOOR
    assert map_data.is_navigation_target_clear(2, 2, clearance_cells=1)
    assert not map_data.is_navigation_target_clear(0, 0)
    assert not map_data.is_navigation_target_clear(0, 1, clearance_cells=1)

    blocked = values.copy()
    blocked[2 * 5 + 3] = floor | 0x10
    map_data.compressed_map = _compressed_grid(blocked)
    assert not map_data.is_navigation_target_clear(2, 2, clearance_cells=1)

    map_data.compressed_map = _compressed_grid(values[:-1])
    assert map_data.classify_grid_cell(2, 2) is None
    assert not map_data.is_navigation_target_clear(2, 2)


def test_room_markers_follow_rendered_image_orientation_and_floor_only() -> None:
    """Room markers use the PNG's flipped Y axis and exclude non-floor cells."""
    room_1 = 1 << 8
    room_2 = 2 << 8
    room_3 = 3 << 8
    map_data = _geometry_map(
        width=4,
        height=3,
        border_top=2,
        border_right=3,
        # Rows are raw map grid coordinates, from bottom (y=0) to top (y=2).
        compressed_map=_compressed_grid(
            [
                room_1,
                0,
                room_1,
                room_1 | 0x10,
                room_1 | 0x08,
                room_2,
                room_2,
                room_3,
                room_3,
                room_2,
                room_1,
                0x20,
            ]
        ),
        rooms=[
            RoomInfo(room_id=1, name="Living room"),
            RoomInfo(room_id=2, room_sub_type=4),
            RoomInfo(room_id=4, name="No floor"),
        ],
    )

    assert map_data.room_markers() == [
        {
            "id": 1,
            "name": "Living room",
            # Raw floor centroid is (1, 0); rendered image is vertically flipped.
            "x": 0.375,
            "y": pytest.approx(5 / 6),
            "area_cells": 3,
        },
        {
            "id": 2,
            "name": "Kitchen",
            # Raw floor centroid is (1, 1), so image-space y is also 1.
            "x": 0.375,
            "y": 0.5,
            "area_cells": 3,
        },
    ]


@pytest.mark.parametrize(
    "overrides",
    [
        {"border_top": 3},
        {"compressed_map": _compressed_grid([(1 << 8)] * 8)},
        {"compressed_map": b""},
    ],
)
def test_room_markers_fail_closed_for_invalid_map_data(
    overrides: dict[str, object],
) -> None:
    map_data = _geometry_map(
        rooms=[RoomInfo(room_id=1, name="Living room")],
        **overrides,
    )

    assert map_data.room_markers() == []


def test_navigation_clearance_optionally_rejects_furniture() -> None:
    obstacle = ObstacleInfo(
        id=1,
        center_x=2,
        center_y=2,
        width=2,
        height=2,
        angle=45,
    )
    map_data = _geometry_map(
        width=5,
        height=5,
        border_top=4,
        border_right=4,
        compressed_map=_compressed_grid([(1 << 8)] * 25),
        obstacles=[obstacle],
    )

    assert not map_data.is_navigation_target_clear(2, 2)
    assert map_data.is_navigation_target_clear(2, 2, reject_furniture=False)
    assert map_data.is_navigation_target_clear(4, 4)
    assert not map_data.is_navigation_target_clear(4, 4, clearance_cells=1)


def test_navigation_revision_is_stable_and_sha256() -> None:
    first = _geometry_map()
    second = _geometry_map()

    assert first.navigation_revision() == second.navigation_revision()
    assert first.navigation_revision() is not None
    assert len(first.navigation_revision() or "") == 64


@pytest.mark.parametrize(
    "changed",
    [
        {"map_id": 99},
        {"map_version": 99},
        {"edit_version": 99},
        {"generation_time": 99},
        {"resolution": 50},
        {"rotate_angle": 90},
        {"compressed_map": _compressed_grid([(2 << 8)] * 9)},
        {"width": 4, "border_right": 3, "compressed_map": _compressed_grid([(1 << 8)] * 12)},
        {
            "height": 4,
            "border_top": 3,
            "compressed_map": _compressed_grid([(1 << 8)] * 12),
        },
        {"origin_x": 1, "border_right": 3},
        {"origin_y": 1, "border_top": 3},
    ],
)
def test_navigation_revision_changes_with_every_relevant_input(
    changed: dict[str, object],
) -> None:
    original = _geometry_map()
    updated = replace(original, **changed)

    assert updated.navigation_revision() is not None
    assert updated.navigation_revision() != original.navigation_revision()
