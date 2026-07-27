"""Schema-level tests for Narwal telecontrol protobuf bodies."""

from __future__ import annotations

import math
import struct

import pytest

from narwal_client.telecontrol import (
    Point,
    PoseData,
    TelecontrolCodecError,
    decode_point_navi_plan_traj,
    encode_cancel_navigation_request,
    encode_point_navi_request,
    encode_set_manual_control_mode,
    encode_telecontrol_velocity,
)


def test_manual_control_mode_exact_fixture() -> None:
    assert encode_set_manual_control_mode(1) == b"\x08\x01"


def test_velocity_exact_signed_int32_fixture_has_only_two_fields() -> None:
    assert encode_telecontrol_velocity(5, -1) == bytes.fromhex(
        "08 05 "
        "10 ff ff ff ff ff ff ff ff ff 01"
    )
    assert encode_telecontrol_velocity(0, 0) == b"\x08\x00\x10\x00"


def test_point_navigation_exact_float32_fixture() -> None:
    payload = encode_point_navi_request(
        avoid_carpet_mask=0,
        explore_mode=2,
        points=(
            PoseData(
                location=Point(x=1.5, y=-2.5),
                theta=0.25,
            ),
        ),
    )

    assert payload == bytes.fromhex(
        "10 00 "  # field 2: avoidCarpetMask
        "20 02 "  # field 4: exploreMode
        "2a 11 "  # field 5: PoseData, 17 bytes
        "0a 0a "  # PoseData field 1: Point, 10 bytes
        "0d 00 00 c0 3f "  # Point field 1: x=1.5, fixed32
        "15 00 00 20 c0 "  # Point field 2: y=-2.5, fixed32
        "15 00 00 80 3e"  # PoseData field 2: theta=0.25, fixed32
    )
    # A fixed64/double version would use wire tags 0x09/0x11 and be longer.
    assert b"\x09" not in payload
    assert len(payload) == 23


def test_point_navigation_repeats_field_five_for_each_pose() -> None:
    payload = encode_point_navi_request(
        avoid_carpet_mask=1,
        explore_mode=2,
        points=(
            PoseData(Point(1.0, 2.0), 0.0),
            PoseData(Point(3.0, 4.0), 0.5),
        ),
    )

    assert payload.count(b"\x2a\x11") == 2


def test_cancel_navigation_exact_typed_fixture() -> None:
    # CancelTaskType.NAVI is enum value 3.
    assert encode_cancel_navigation_request() == b"\x08\x03"


def test_trajectory_decodes_float32_points_and_unknown_fields() -> None:
    payload = bytes.fromhex(
        "10 09 "  # unknown varint field 2
        "0a 0a "
        "0d 00 00 c0 3f "
        "15 00 00 20 c0 "
        "1d 00 00 80 3f "  # unknown fixed32 field 3
        "0a 0a "
        "0d 00 00 40 40 "
        "15 00 00 80 40"
    )

    trajectory = decode_point_navi_plan_traj(payload)

    assert trajectory.plan_traj == (
        Point(x=1.5, y=-2.5),
        Point(x=3.0, y=4.0),
    )
    assert trajectory.points is trajectory.plan_traj


def test_trajectory_rejects_double_wire_type_for_point_coordinate() -> None:
    fixed64_point = b"\x09" + struct.pack("<d", 1.5)
    payload = b"\x0a" + bytes((len(fixed64_point),)) + fixed64_point

    with pytest.raises(TelecontrolCodecError, match="expected fixed32"):
        decode_point_navi_plan_traj(payload)


@pytest.mark.parametrize(
    ("call", "error_type", "match"),
    [
        (
            lambda: encode_set_manual_control_mode(True),
            TypeError,
            "mode must be an integer",
        ),
        (
            lambda: encode_telecontrol_velocity(1 << 31, 0),
            TelecontrolCodecError,
            "out of int32 range",
        ),
        (
            lambda: encode_point_navi_request(
                avoid_carpet_mask=0,
                explore_mode=2,
                points=(PoseData(Point(math.inf, 0.0), 0.0),),
            ),
            TelecontrolCodecError,
            "must be finite",
        ),
        (
            lambda: encode_point_navi_request(
                avoid_carpet_mask=0,
                explore_mode=2,
                points=(PoseData(Point(3.5e38, 0.0), 0.0),),
            ),
            TelecontrolCodecError,
            "outside finite float32 range",
        ),
        (
            lambda: decode_point_navi_plan_traj(b"\x0a\x0a\x0d\x00"),
            TelecontrolCodecError,
            "Truncated",
        ),
        (
            lambda: decode_point_navi_plan_traj("not-bytes"),  # type: ignore[arg-type]
            TypeError,
            "bytes-like",
        ),
    ],
)
def test_codec_validation(call, error_type, match: str) -> None:
    with pytest.raises(error_type, match=match):
        call()
