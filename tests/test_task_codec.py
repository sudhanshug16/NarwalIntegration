"""Tests for read-only current CleanTask decoding."""

from narwal_client.task import current_task_attributes, decode_current_task_response


def test_decodes_wrapped_current_task_and_items() -> None:
    decoded = {
        "1": {"1": 1},
        "2": {
            "1": 42,
            "2": [
                {
                    "1": {"1": 1, "2": 9},
                    "2": {
                        "1": 4,
                        "2": 3,
                        "3": 2,
                        "4": 2,
                        "7": 2,
                        "8": 2,
                    },
                    "3": 1,
                    "99": b"future",
                },
                {
                    "1": {"1": 1, "2": 11},
                    "2": {"1": 4},
                    "3": 2,
                },
            ],
            "4": b"official-app",
            "5": 4,
            "8": [13, 17],
            "112": 7,
        },
    }

    task = decode_current_task_response(decoded)

    assert task.map_id == 42
    assert task.task_type == 4
    assert task.extra == "official-app"
    assert task.excluded_room_ids == (13, 17)
    assert [item.zone.zone_id for item in task.items] == [9, 11]
    assert task.items[0].parameters.synchronized_count == 2
    assert task.items[0].parameters.overlap_level == 2
    assert task.raw_fields[112] == 7
    assert task.items[0].raw_fields[99] == b"future"
    assert task.service_result == {"1": 1}


def test_direct_task_is_not_confused_with_response_wrapper() -> None:
    task = decode_current_task_response(
        {
            "1": 8,
            "2": {"1": {"1": 1, "2": 4}, "2": {"1": 2}, "3": 1},
            "5": 1,
        }
    )

    assert task.map_id == 8
    assert len(task.items) == 1
    assert task.items[0].zone.zone_id == 4
    assert task.service_result is None


def test_unknown_and_malformed_values_remain_diagnostic_only() -> None:
    task = decode_current_task_response(
        {
            "1": "not-an-int",
            "2": [{"1": {"2": True}, "2": {"2": "max"}}],
            "5": True,
            "120": {"1": b"unknown"},
        }
    )

    assert task.map_id is None
    assert task.task_type is None
    assert task.items[0].zone.zone_id is None
    assert task.items[0].parameters.fan_level is None
    assert task.raw_fields[120] == {"1": b"unknown"}


def test_home_assistant_attributes_are_stable_and_human_readable() -> None:
    task = decode_current_task_response(
        {"1": 5, "2": {"1": {"1": 1, "2": 3}, "2": {"1": 4}}, "5": 4}
    )

    attributes = current_task_attributes(task)

    assert attributes["map_id"] == 5
    assert attributes["items"][0]["zone_id"] == 3
    assert attributes["items"][0]["mode"] == 4
    assert attributes["raw_fields"]["5"] == 4
