"""Tests for strict local cleaning timeline/report decoders."""

from __future__ import annotations

import struct
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import pytest

from narwal_client.history import (
    CLEAN_REPORT_REPEATED_MESSAGE_FIELDS,
    CLEAN_REPORT_SINGULAR_MESSAGE_FIELDS,
    HistoryCodecError,
    TimeLineParam,
    decode_clean_report_submit,
    decode_get_clean_time_line_response,
    encode_get_clean_time_line_request,
)


def _varint(value: int) -> bytes:
    encoded = bytearray()
    while value > 0x7F:
        encoded.append((value & 0x7F) | 0x80)
        value >>= 7
    encoded.append(value)
    return bytes(encoded)


def test_decodes_robot_local_timeline_without_assigning_time_units() -> None:
    response = decode_get_clean_time_line_response(
        {
            "1": 0,
            "2": {
                "1": [
                    {
                        "1": (1 << 64) - 1,
                        "2": 99,
                        "3": {"1": b"opaque clean event", "90": [1, 2]},
                        "4": 6,
                        "5": (1 << 64) - 1,
                        "6": {"1": 321, "80": {"1": b"opaque error"}},
                        "7": 1,
                        "8": (1 << 64) - 1,
                        "77": b"future node field",
                    },
                    {
                        "1": 1_700_000_000,
                        "2": 1,
                        "7": False,
                        "8": 42,
                    },
                ],
                "50": b"future timeline field",
            },
            "99": {"1": b"future response field"},
        }
    )

    assert response.result_code == 0
    assert response.timeline_status is not None
    assert len(response.timeline_status.event_nodes) == 2

    node = response.timeline_status.event_nodes[0]
    assert node.event_time == -1
    assert node.primary_task == 99
    assert node.secondary_clean_event == {
        1: b"opaque clean event",
        90: (1, 2),
    }
    assert node.secondary_self_check == 6
    assert node.task_result == -1
    assert node.error_code == {1: 321, 80: {"1": b"opaque error"}}
    assert node.is_primary_node is True
    assert node.node_key == (1 << 64) - 1
    assert node.raw_fields[77] == b"future node field"
    assert response.timeline_status.raw_fields[50] == b"future timeline field"
    assert 99 in response.raw_fields


def test_timeline_accepts_schema_less_singleton_repeated_message() -> None:
    response = decode_get_clean_time_line_response(
        {
            2: {
                1: {
                    1: 123,
                    8: 456,
                }
            }
        }
    )

    assert response.timeline_status is not None
    assert len(response.timeline_status.event_nodes) == 1
    assert response.timeline_status.event_nodes[0].event_time == 123


def test_absent_and_empty_timeline_status_are_distinct() -> None:
    absent = decode_get_clean_time_line_response({1: 0})
    empty = decode_get_clean_time_line_response({1: 0, 2: {}})

    assert absent.timeline_status is None
    assert empty.timeline_status is not None
    assert empty.timeline_status.event_nodes == ()


def test_timeline_values_are_deeply_immutable() -> None:
    response = decode_get_clean_time_line_response(
        {2: {1: {3: {1: bytearray(b"opaque")}, 90: {"1": [b"x"]}}}}
    )
    assert response.timeline_status is not None
    node = response.timeline_status.event_nodes[0]
    assert node.secondary_clean_event is not None

    with pytest.raises(FrozenInstanceError):
        node.event_time = 1  # type: ignore[misc]
    with pytest.raises(TypeError):
        node.secondary_clean_event[1] = b"changed"  # type: ignore[index]
    with pytest.raises(TypeError):
        node.raw_fields[90]["1"] = []  # type: ignore[index]


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {True: 1},
        {"01": 1},
        {1: 0, "1": 1},
        {1: True},
        {1: 1 << 31},
        {2: b"not a message"},
        {2: {1: b"not repeated messages"}},
        {2: {1: [b"not a node"]}},
        {2: {1: {1: True}}},
        {2: {1: {1: -(1 << 63) - 1}}},
        {2: {1: {1: 1 << 64}}},
        {2: {1: {2: True}}},
        {2: {1: {2: 1 << 31}}},
        {2: {1: {3: b"not a message"}}},
        {2: {1: {4: True}}},
        {2: {1: {5: 1 << 31}}},
        {2: {1: {6: b"not a message"}}},
        {2: {1: {7: 2}}},
        {2: {1: {8: -1}}},
        {2: {1: {8: True}}},
        {2: {1: {8: 1 << 64}}},
    ],
)
def test_malformed_timeline_fields_fail_closed(payload: object) -> None:
    with pytest.raises(HistoryCodecError):
        decode_get_clean_time_line_response(payload)  # type: ignore[arg-type]


def test_clean_report_nested_field_catalog_matches_descriptor() -> None:
    assert dict(CLEAN_REPORT_REPEATED_MESSAGE_FIELDS) == {
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
    assert dict(CLEAN_REPORT_SINGULAR_MESSAGE_FIELDS) == {
        12: "map",
        25: "initCleanParam",
        26: "timeLineStatus",
        28: "cleanTask",
        31: "imageResources",
        40: "restoreTaskInfo",
        42: "exceptionVideoResources",
    }


def test_decodes_all_proven_clean_report_scalars() -> None:
    area_bits = struct.unpack("<I", struct.pack("<f", 12.5))[0]
    report = decode_clean_report_submit(
        {
            "1": (1 << 32) - 1,
            "2": area_bits,
            "3": 3600,
            "4": 2,
            "5": 6,
            "6": 1_700_000_000,
            "7": 1_700_003_600,
            "8": 4,
            "9": _varint(1) + _varint(300),
            "10": 11,
            "14": [0, 10, (1 << 32) - 1],
            "18": 5,
            "19": 1234,
            "21": (1 << 64) - 1,
            "22": 1,
            "23": False,
            "29": b"schedule-123",
            "33": "diagnostic",
            "34": 0,
            "35": 32,
            "37": True,
            "38": 3,
            "39": 2,
            "41": (1 << 32) - 1,
            "43": b"+05:30",
            "27": {"1": b"future unknown field"},
        }
    )

    assert report.percent == (1 << 32) - 1
    assert report.area == 12.5
    assert report.duration == 3600
    assert report.region_type == 2
    assert report.task_type == 6
    assert report.start_time == 1_700_000_000
    assert report.end_time == 1_700_003_600
    assert report.task_result == 4
    assert report.room_order == (1, 300)
    assert report.clean_trigger_type == 11
    assert report.trajectory_start_indices == (0, 10, (1 << 32) - 1)
    assert report.max_dirty_level == 5
    assert report.error_code == 1234
    assert report.mission_id == (1 << 64) - 1
    assert report.carpet_updated is True
    assert report.is_continued_task is False
    assert report.schedule_task_id == "schedule-123"
    assert report.debug_detail == "diagnostic"
    assert report.heavy_dirty_room_updated is False
    assert report.schedule_task_result == 32
    assert report.up_obstacle_detected is True
    assert report.clean_with_mapping_result == 3
    assert report.type_for_pause_too_long_end == 2
    assert report.scenario_error_code == (1 << 32) - 1
    assert report.tz_offset == "+05:30"
    assert 27 in report.raw_fields


def test_clean_report_accepts_typed_float_and_unpacked_uint_singleton() -> None:
    report = decode_clean_report_submit({2: 0.25, 9: 7, 14: ()})

    assert report.area == 0.25
    assert report.room_order == (7,)
    assert report.trajectory_start_indices == ()


def test_clean_report_preserves_all_nested_messages_as_opaque() -> None:
    payload: dict[int, Any] = {}
    for field_number in CLEAN_REPORT_SINGULAR_MESSAGE_FIELDS:
        payload[field_number] = {"1": b"opaque", "99": [1, 2]}
    for field_number in CLEAN_REPORT_REPEATED_MESSAGE_FIELDS:
        payload[field_number] = [
            {"1": b"first"},
            {"2": {"1": b"second"}},
        ]

    report = decode_clean_report_submit(payload)

    assert set(report.nested_fields) == (
        set(CLEAN_REPORT_SINGULAR_MESSAGE_FIELDS)
        | set(CLEAN_REPORT_REPEATED_MESSAGE_FIELDS)
    )
    for field_number in CLEAN_REPORT_SINGULAR_MESSAGE_FIELDS:
        assert report.nested_fields[field_number] == {
            1: b"opaque",
            99: (1, 2),
        }
    for field_number in CLEAN_REPORT_REPEATED_MESSAGE_FIELDS:
        assert report.nested_fields[field_number] == (
            {1: b"first"},
            {2: {"1": b"second"}},
        )

    with pytest.raises(TypeError):
        report.nested_fields[12][1] = b"changed"  # type: ignore[index]
    with pytest.raises(TypeError):
        report.raw_fields[12]["1"] = b"changed"  # type: ignore[index]


def test_repeated_report_message_accepts_schema_less_singleton() -> None:
    report = decode_clean_report_submit({11: {"1": b"one"}})

    assert report.nested_fields[11] == ({1: b"one"},)


def test_empty_clean_report_does_not_invent_values() -> None:
    report = decode_clean_report_submit({})

    assert report.percent is None
    assert report.area is None
    assert report.room_order == ()
    assert report.trajectory_start_indices == ()
    assert report.nested_fields == {}
    assert report.raw_fields == {}


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {True: 1},
        {"01": 1},
        {1: 0, "1": 1},
        {1: True},
        {1: -1},
        {1: 1 << 32},
        {2: "not float"},
        {2: -1},
        {2: 1 << 32},
        {3: True},
        {4: True},
        {4: 1 << 31},
        {6: -1},
        {8: "not enum"},
        {9: True},
        {9: [1, True]},
        {9: b"\x80"},
        {9: b"\x81\x00"},
        {9: _varint(1 << 32)},
        {14: "not repeated uint32"},
        {18: -1},
        {19: 1 << 32},
        {21: -1},
        {21: True},
        {21: 1 << 64},
        {22: 2},
        {23: "not bool"},
        {29: b"\xff"},
        {33: 12},
        {34: 2},
        {35: True},
        {37: 2},
        {38: 1 << 31},
        {39: "not enum"},
        {41: 1 << 32},
        {43: b"\xff"},
        {12: b"not a message"},
        {11: b"not repeated messages"},
        {11: [{"1": 1}, b"not a message"]},
    ],
)
def test_malformed_clean_report_fields_fail_closed(payload: object) -> None:
    with pytest.raises(HistoryCodecError):
        decode_clean_report_submit(payload)  # type: ignore[arg-type]


def test_root_and_vendored_history_codecs_are_byte_identical() -> None:
    root = Path(__file__).resolve().parents[1]

    assert (root / "narwal_client" / "history.py").read_bytes() == (
        root / "custom_components" / "narwal" / "narwal_client" / "history.py"
    ).read_bytes()


def test_timeline_request_matches_the_official_app_default_all_window() -> None:
    assert encode_get_clean_time_line_request() == b"\x08\x03"
    assert encode_get_clean_time_line_request(TimeLineParam.ONE) == b"\x08\x01"
    with pytest.raises(HistoryCodecError, match="TimeLineParam"):
        encode_get_clean_time_line_request(3)  # type: ignore[arg-type]
