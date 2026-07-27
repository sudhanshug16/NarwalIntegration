"""Tests for strict, read-only clean-plan response decoding."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import pytest

from narwal_client.plan import (
    PlanCodecError,
    decode_clean_plans_response,
    decode_current_plan_response,
)


def test_decodes_current_plan_from_proven_schema_and_preserves_unknowns() -> None:
    response = decode_current_plan_response(
        {
            "1": 0,
            "2": {
                "1": 42,
                "2": 314,
                "3": 99,
                "4": 1,
                "5": b"Evening clean",
                "6": False,
                "7": 12,
                "8": 7,
                "9": {
                    "1": 11,
                    "2": 99,
                    "3": {"1": b"opaque geometry", "88": [1, 2]},
                    "4": {"2": 3},
                    "77": b"future area field",
                },
                "10": {
                    "1": 1,
                    "2": False,
                    "90": {"1": b"future task field"},
                },
                "111": {"1": bytearray(b"future plan field")},
            },
            "200": {"1": b"future response field"},
        }
    )

    assert response.result_code == 0
    assert response.plan is not None
    assert response.plan.plan_id == 42
    assert response.plan.map_id == 314
    assert response.plan.clean_mode == 99
    assert response.plan.is_custom_plan is True
    assert response.plan.custom_name == "Evening clean"
    assert response.plan.shown_in_station is False
    assert response.plan.perform_times == 12
    assert response.plan.order == 7

    area = response.plan.area_options[0]
    assert area.zone_id == 11
    assert area.clean_zone_type == 99
    assert area.clean_zone_area == {1: b"opaque geometry", 88: (1, 2)}
    assert area.sweep_area_option == {2: 3}
    assert area.raw_fields[77] == b"future area field"

    parameters = response.plan.task_parameters
    assert parameters is not None
    assert parameters.enable_smart_clean is True
    assert parameters.enable_smart_deep_clean is False
    assert 90 in parameters.raw_fields
    assert 111 in response.plan.raw_fields
    assert 200 in response.raw_fields


def test_decodes_repeated_clean_plans() -> None:
    response = decode_clean_plans_response(
        {
            1: 1,
            2: [
                {1: 10, 2: 100, 9: []},
                {1: 20, 2: 200, 10: {1: 0, 2: 1}},
            ],
        }
    )

    assert response.result_code == 1
    assert [plan.plan_id for plan in response.plans] == [10, 20]
    assert response.plans[0].area_options == ()
    assert response.plans[1].task_parameters is not None
    assert response.plans[1].task_parameters.enable_smart_clean is False
    assert response.plans[1].task_parameters.enable_smart_deep_clean is True


def test_accepts_singleton_mapping_for_schema_less_repeated_fields() -> None:
    response = decode_clean_plans_response(
        {
            2: {
                1: 10,
                9: {
                    1: 3,
                    2: 1,
                },
            }
        }
    )

    assert len(response.plans) == 1
    assert response.plans[0].plan_id == 10
    assert len(response.plans[0].area_options) == 1
    assert response.plans[0].area_options[0].zone_id == 3


def test_absent_optional_plan_fields_are_not_invented() -> None:
    current = decode_current_plan_response({1: 0})
    plans = decode_clean_plans_response({1: 0})

    assert current.plan is None
    assert plans.plans == ()


def test_decoded_values_and_raw_fields_are_immutable() -> None:
    response = decode_current_plan_response(
        {
            2: {
                1: 1,
                9: {1: 2, 3: {1: bytearray(b"opaque")}},
                99: {"1": [bytearray(b"future")]},
            }
        }
    )
    assert response.plan is not None

    with pytest.raises(FrozenInstanceError):
        response.plan.plan_id = 2  # type: ignore[misc]
    with pytest.raises(TypeError):
        response.raw_fields[3] = "new"  # type: ignore[index]
    with pytest.raises(TypeError):
        response.plan.raw_fields[99]["1"] = "new"  # type: ignore[index]
    with pytest.raises(TypeError):
        response.plan.area_options[0].clean_zone_area[1] = b"new"  # type: ignore[index]

    assert response.plan.raw_fields[99]["1"] == (b"future",)
    assert response.plan.area_options[0].clean_zone_area == {1: b"opaque"}


@pytest.mark.parametrize(
    ("decoder", "payload"),
    [
        (decode_current_plan_response, []),
        (decode_current_plan_response, {True: 0}),
        (decode_current_plan_response, {"01": 0}),
        (decode_current_plan_response, {1: 0, "1": 1}),
        (decode_current_plan_response, {1: True}),
        (decode_current_plan_response, {2: b"not a message"}),
        (decode_current_plan_response, {2: {1: True}}),
        (decode_current_plan_response, {2: {1: -1}}),
        (decode_current_plan_response, {2: {1: 1 << 32}}),
        (decode_current_plan_response, {2: {2: 1 << 32}}),
        (decode_current_plan_response, {2: {7: 1 << 32}}),
        (decode_current_plan_response, {2: {2: "not uint64"}}),
        (decode_current_plan_response, {2: {3: True}}),
        (decode_current_plan_response, {2: {4: 2}}),
        (decode_current_plan_response, {2: {5: b"\xff"}}),
        (decode_current_plan_response, {2: {6: "not bool"}}),
        (decode_current_plan_response, {2: {7: -1}}),
        (decode_current_plan_response, {2: {8: 1 << 32}}),
        (decode_current_plan_response, {2: {9: 3}}),
        (decode_current_plan_response, {2: {9: [3]}}),
        (decode_current_plan_response, {2: {9: {1: True}}}),
        (decode_current_plan_response, {2: {9: {2: True}}}),
        (decode_current_plan_response, {2: {9: {3: "not a message"}}}),
        (decode_current_plan_response, {2: {10: "not a message"}}),
        (decode_current_plan_response, {2: {10: {1: 2}}}),
        (decode_clean_plans_response, {1: True}),
        (decode_clean_plans_response, {2: b"not a repeated message"}),
        (decode_clean_plans_response, {2: [{1: 1}, b"not a plan"]}),
    ],
)
def test_malformed_known_fields_fail_closed(
    decoder: Callable[[Any], object],
    payload: object,
) -> None:
    with pytest.raises(PlanCodecError):
        decoder(payload)


def test_unknown_numeric_fields_are_preserved_without_guessing_their_types() -> None:
    response = decode_current_plan_response(
        {
            1: 777,
            2: {
                3: -123,
                99: object(),
            },
        }
    )

    assert response.result_code == 777
    assert response.plan is not None
    assert response.plan.clean_mode == -123
    assert 99 in response.plan.raw_fields


def test_root_and_vendored_plan_codecs_are_byte_identical() -> None:
    root = Path(__file__).parents[1]

    assert (root / "narwal_client" / "plan.py").read_bytes() == (
        root / "custom_components" / "narwal" / "narwal_client" / "plan.py"
    ).read_bytes()
