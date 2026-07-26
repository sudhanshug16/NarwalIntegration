"""Tests for feature-list normalization and capability gating."""

from __future__ import annotations

from narwal_client.capabilities import (
    Capability,
    capability_enabled,
    capability_name,
    named_capabilities,
    normalize_feature_response,
)


def test_direct_feature_response_is_normalized() -> None:
    features = normalize_feature_response({"1": 1, "24": 1, "49": 2, "80": 0})

    assert features == {1: 1, 24: 1, 49: 2, 80: 0}
    assert capability_enabled(features, Capability.AVOID_MODE_CONFIG)
    assert not capability_enabled(features, Capability.DRY_STATION_BAG)


def test_strict_service_result_wrapper_is_unwrapped() -> None:
    features = normalize_feature_response(
        {
            "1": 1,
            "2": {"1": 1, "5": 1, "24": 1, "66": 1},
        }
    )

    assert features == {1: 1, 5: 1, 24: 1, 66: 1}


def test_repeated_and_byte_values_are_preserved_conservatively() -> None:
    features = normalize_feature_response(
        {"49": b"2", "106": [3, 8, b"13"], "bad": 1, "112": 1}
    )

    assert features == {49: 2, 106: (3, 8, 13), 112: 1}
    assert capability_enabled(features, Capability.SUPPORTED_PET_OBS_LABELS)


def test_nested_unknown_values_are_not_treated_as_enabled() -> None:
    assert normalize_feature_response({"24": {"unexpected": 1}}) == {}


def test_direct_response_is_not_replaced_by_larger_nested_message() -> None:
    features = normalize_feature_response(
        {
            "1": 1,
            "2": 1,
            "200": {"1": 1, "5": 1, "24": 1, "66": 1},
        }
    )

    assert features == {1: 1, 2: 1}


def test_field_two_is_not_unwrapped_without_exact_service_result_wrapper() -> None:
    features = normalize_feature_response(
        {
            "1": 1,
            "2": {"24": 1, "66": 1},
            "3": 1,
        }
    )

    assert features == {1: 1, 3: 1}


def test_unknown_positive_fields_are_preserved_and_gated_by_number() -> None:
    features = normalize_feature_response(
        {
            "0": 1,
            "-1": 1,
            "112": 1,
            "300": [2, b"4"],
        }
    )

    assert features == {112: 1, 300: (2, 4)}
    assert capability_enabled(features, 112)
    assert capability_enabled(features, 300)


def test_named_capabilities_are_stable_and_ordered() -> None:
    named = named_capabilities({112: 1, 100: 3, 24: 1})

    assert named == {
        "avoid_mode_config": 1,
        "station_light_ctrl": 3,
        "unknown_112": 1,
    }
    assert capability_name(999) == "unknown_999"
