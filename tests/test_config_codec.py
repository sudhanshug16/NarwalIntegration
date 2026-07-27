"""Tests for conservative Narwal GetConfig and SetConfig codecs."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from narwal_client.config import (
    GET_CONFIG_FIELD_TO_SET_CONFIG_FIELD,
    SET_CONFIG_FIELD_SPECS,
    AvoidMode,
    CarpetCleanOption,
    CarpetCleanPriorityOption,
    CarpetDeepCleanOption,
    CleanMode,
    CleanMopFrequency,
    ConfigCodecError,
    ConfigSnapshot,
    CornerCleanMode,
    DryMopStrength,
    GetConfigField,
    Language,
    SetConfigField,
    SetConfigPatch,
    StationLightCtrlType,
    config_snapshot_attributes,
    decode_get_config_response,
    decode_set_config_patch,
    encode_set_config_patch,
)

PATCH_CASES = [
    (SetConfigField.VOLUME_PERCENTAGE, 100, bytes.fromhex("08 64")),
    (SetConfigField.LANGUAGE, Language.ENGLISH, bytes.fromhex("10 03")),
    (SetConfigField.CHILD_LOCK_ENABLED, True, bytes.fromhex("40 01")),
    (SetConfigField.CLEAN_CARPET_ENABLED, False, bytes.fromhex("48 00")),
    (SetConfigField.SMART_CLEAN_DETECTION_ENABLED, True, bytes.fromhex("60 01")),
    (
        SetConfigField.DRY_MOP_STRENGTH,
        DryMopStrength.SMART,
        bytes.fromhex("68 03"),
    ),
    (
        SetConfigField.CLEAN_MOP_FREQUENCY,
        CleanMopFrequency.DEEP,
        bytes.fromhex("70 03"),
    ),
    (
        SetConfigField.CARPET_CLEAN_OPTION,
        CarpetCleanOption.AVOID,
        bytes.fromhex("78 04"),
    ),
    (
        SetConfigField.SWITCH_BACK_TO_MAIN_MAP_AFTER_TEMP_MAP_CLEAN,
        False,
        bytes.fromhex("a0 01 00"),
    ),
    (
        SetConfigField.STATION_CLEAN_MODE,
        CleanMode.MOP,
        bytes.fromhex("a8 01 03"),
    ),
    (SetConfigField.PET_MODE, True, bytes.fromhex("b0 01 01")),
    (SetConfigField.SMART_DEEP_CLEAN_ENABLED, False, bytes.fromhex("b8 01 00")),
    (
        SetConfigField.MOISTURE_PROOF_PAD_PROTECT_ENABLED,
        True,
        bytes.fromhex("d0 01 01"),
    ),
    (SetConfigField.DUST_GATHERING_ENABLED, True, bytes.fromhex("d8 01 01")),
    (SetConfigField.SMART_DUST_GATHERING_ENABLED, False, bytes.fromhex("e0 01 00")),
    (SetConfigField.QUIET_DUST_GATHERING_ENABLED, True, bytes.fromhex("f0 01 01")),
    (SetConfigField.DRY_ROBOT_BAG_ENABLED, False, bytes.fromhex("f8 01 00")),
    (SetConfigField.HOT_WATER_WASH_ENABLED, False, bytes.fromhex("80 02 00")),
    (SetConfigField.MASSIVE_DIRTY_DEEP_CLEAN_ENABLE, True, bytes.fromhex("88 02 01")),
    (SetConfigField.AVOID_MODE, AvoidMode.SAFER, bytes.fromhex("90 02 02")),
    (SetConfigField.ROBOT_CLEAN_MODE, CleanMode.COMPOSITE, bytes.fromhex("98 02 06")),
    (SetConfigField.SPEECH_CONTROL_ENABLED, True, bytes.fromhex("a0 02 01")),
    (
        SetConfigField.AUTOMATIC_POWEROFF_WHEN_DISCHARGING,
        False,
        bytes.fromhex("a8 02 00"),
    ),
    (
        SetConfigField.AI_VOICE_SOUND_EFFECT_ENABLED,
        True,
        bytes.fromhex("b8 02 01"),
    ),
    (
        SetConfigField.AI_VOICE_SOUND_EFFECT_FOR_WAITING_ENABLED,
        False,
        bytes.fromhex("c0 02 00"),
    ),
    (
        SetConfigField.CORNER_CLEAN_MODE,
        CornerCleanMode.ROTATE_ROBOT,
        bytes.fromhex("c8 02 02"),
    ),
    (
        SetConfigField.CARPET_CLEAN_PRIORITY_OPTION,
        CarpetCleanPriorityOption.CARPET_FIRST,
        bytes.fromhex("e8 02 02"),
    ),
    (
        SetConfigField.CARPET_DEEP_CLEAN_OPTION,
        CarpetDeepCleanOption.ENABLE,
        bytes.fromhex("f0 02 02"),
    ),
    (SetConfigField.ALL_THINGS_RECOGNITION_ENABLED, True, bytes.fromhex("f8 02 01")),
    (SetConfigField.PRECIOUS_ITEM_GUARD_ENABLED, False, bytes.fromhex("80 03 00")),
    (
        SetConfigField.STATION_LIGHT_CTRL_TYPE,
        StationLightCtrlType.ON,
        bytes.fromhex("88 03 02"),
    ),
]


EXPECTED_SCHEMA = {
    1: "volumePercentage",
    2: "language",
    8: "childLockEnabled",
    9: "cleanCarpetEnabled",
    12: "smartCleanDetectionEnabled",
    13: "dryMopStrength",
    14: "cleanMopFreq",
    15: "carpetCleanOption",
    20: "switchBackToMainMapAfterTempMapClean",
    21: "stationCleanMode",
    22: "petMode",
    23: "smartDeepCleanEnabled",
    26: "moistureProofPadProtectEnabled",
    27: "dustGatheringEnabled",
    28: "smartDustGatheringEnabled",
    30: "quietDustGatheringEnabled",
    31: "dryRobotBagEnabled",
    32: "hotWaterWashEnabled",
    33: "massiveDirtyDeepCleanEnable",
    34: "avoidMode",
    35: "robotCleanMode",
    36: "speechControlEnabled",
    37: "automaticPoweroffWhenDischarging",
    39: "aiVoiceSoundEffectEnabled",
    40: "aiVoiceSoundEffectForWaitingEnabled",
    41: "cornerCleanMode",
    45: "carpetCleanPriorityOption",
    46: "carpetDeepCleanOption",
    47: "allThingsRecognitionEnabled",
    48: "preciousItemGuardEnabled",
    49: "stationLightCtrlType",
}

GET_CONFIG_CASES = [
    (GetConfigField.VOLUME_PERCENTAGE, SetConfigField.VOLUME_PERCENTAGE, 67, 67),
    (GetConfigField.LANGUAGE, SetConfigField.LANGUAGE, 3, Language.ENGLISH),
    (GetConfigField.CHILD_LOCK_ENABLED, SetConfigField.CHILD_LOCK_ENABLED, 1, True),
    (GetConfigField.CLEAN_CARPET_ENABLED, SetConfigField.CLEAN_CARPET_ENABLED, 0, False),
    (
        GetConfigField.SMART_CLEAN_DETECTION_ENABLED,
        SetConfigField.SMART_CLEAN_DETECTION_ENABLED,
        1,
        True,
    ),
    (
        GetConfigField.DRY_MOP_STRENGTH,
        SetConfigField.DRY_MOP_STRENGTH,
        3,
        DryMopStrength.SMART,
    ),
    (
        GetConfigField.CLEAN_MOP_FREQUENCY,
        SetConfigField.CLEAN_MOP_FREQUENCY,
        2,
        CleanMopFrequency.NORMAL,
    ),
    (
        GetConfigField.CARPET_CLEAN_OPTION,
        SetConfigField.CARPET_CLEAN_OPTION,
        4,
        CarpetCleanOption.AVOID,
    ),
    (
        GetConfigField.SWITCH_BACK_TO_MAIN_MAP_AFTER_TEMP_MAP_CLEAN,
        SetConfigField.SWITCH_BACK_TO_MAIN_MAP_AFTER_TEMP_MAP_CLEAN,
        0,
        False,
    ),
    (
        GetConfigField.STATION_CLEAN_MODE,
        SetConfigField.STATION_CLEAN_MODE,
        3,
        CleanMode.MOP,
    ),
    (GetConfigField.PET_MODE, SetConfigField.PET_MODE, 1, True),
    (
        GetConfigField.SMART_DEEP_CLEAN_ENABLED,
        SetConfigField.SMART_DEEP_CLEAN_ENABLED,
        0,
        False,
    ),
    (
        GetConfigField.MOISTURE_PROOF_PAD_PROTECT_ENABLED,
        SetConfigField.MOISTURE_PROOF_PAD_PROTECT_ENABLED,
        1,
        True,
    ),
    (
        GetConfigField.DUST_GATHERING_ENABLED,
        SetConfigField.DUST_GATHERING_ENABLED,
        1,
        True,
    ),
    (
        GetConfigField.DRY_ROBOT_BAG_ENABLED,
        SetConfigField.DRY_ROBOT_BAG_ENABLED,
        0,
        False,
    ),
    (
        GetConfigField.SMART_DUST_GATHERING_ENABLED,
        SetConfigField.SMART_DUST_GATHERING_ENABLED,
        0,
        False,
    ),
    (
        GetConfigField.QUIET_DUST_GATHERING_ENABLED,
        SetConfigField.QUIET_DUST_GATHERING_ENABLED,
        1,
        True,
    ),
    (
        GetConfigField.HOT_WATER_WASH_ENABLED,
        SetConfigField.HOT_WATER_WASH_ENABLED,
        0,
        False,
    ),
    (
        GetConfigField.MASSIVE_DIRTY_DEEP_CLEAN_ENABLE,
        SetConfigField.MASSIVE_DIRTY_DEEP_CLEAN_ENABLE,
        1,
        True,
    ),
    (
        GetConfigField.AVOID_MODE,
        SetConfigField.AVOID_MODE,
        2,
        AvoidMode.SAFER,
    ),
    (
        GetConfigField.ROBOT_CLEAN_MODE,
        SetConfigField.ROBOT_CLEAN_MODE,
        6,
        CleanMode.COMPOSITE,
    ),
    (
        GetConfigField.SPEECH_CONTROL_ENABLED,
        SetConfigField.SPEECH_CONTROL_ENABLED,
        1,
        True,
    ),
    (
        GetConfigField.AUTOMATIC_POWEROFF_WHEN_DISCHARGING,
        SetConfigField.AUTOMATIC_POWEROFF_WHEN_DISCHARGING,
        0,
        False,
    ),
    (
        GetConfigField.AI_VOICE_SOUND_EFFECT_ENABLED,
        SetConfigField.AI_VOICE_SOUND_EFFECT_ENABLED,
        1,
        True,
    ),
    (
        GetConfigField.AI_VOICE_SOUND_EFFECT_FOR_WAITING_ENABLED,
        SetConfigField.AI_VOICE_SOUND_EFFECT_FOR_WAITING_ENABLED,
        0,
        False,
    ),
    (
        GetConfigField.CORNER_CLEAN_MODE,
        SetConfigField.CORNER_CLEAN_MODE,
        2,
        CornerCleanMode.ROTATE_ROBOT,
    ),
    (
        GetConfigField.CARPET_CLEAN_PRIORITY_OPTION,
        SetConfigField.CARPET_CLEAN_PRIORITY_OPTION,
        2,
        CarpetCleanPriorityOption.CARPET_FIRST,
    ),
    (
        GetConfigField.CARPET_DEEP_CLEAN_OPTION,
        SetConfigField.CARPET_DEEP_CLEAN_OPTION,
        2,
        CarpetDeepCleanOption.ENABLE,
    ),
    (
        GetConfigField.ALL_THINGS_RECOGNITION_ENABLED,
        SetConfigField.ALL_THINGS_RECOGNITION_ENABLED,
        1,
        True,
    ),
    (
        GetConfigField.PRECIOUS_ITEM_GUARD_ENABLED,
        SetConfigField.PRECIOUS_ITEM_GUARD_ENABLED,
        0,
        False,
    ),
    (
        GetConfigField.STATION_LIGHT_CTRL_TYPE,
        SetConfigField.STATION_LIGHT_CTRL_TYPE,
        2,
        StationLightCtrlType.ON,
    ),
]

EXPECTED_GET_TO_SET_SCHEMA = {
    1: 1,
    2: 2,
    7: 8,
    8: 9,
    11: 12,
    12: 13,
    13: 14,
    15: 15,
    20: 20,
    21: 21,
    22: 22,
    23: 23,
    26: 26,
    27: 27,
    28: 28,
    30: 30,
    31: 31,
    32: 32,
    33: 33,
    34: 34,
    35: 35,
    36: 36,
    37: 37,
    39: 39,
    40: 40,
    41: 41,
    46: 45,
    47: 46,
    49: 47,
    50: 48,
    51: 49,
}


def test_schema_uses_exact_set_request_fields() -> None:
    actual = {
        int(field): spec.protobuf_name for field, spec in SET_CONFIG_FIELD_SPECS.items()
    }
    assert actual == EXPECTED_SCHEMA


def test_schema_uses_exact_get_response_to_set_request_mapping() -> None:
    actual = {
        int(get_field): int(set_field)
        for get_field, set_field in GET_CONFIG_FIELD_TO_SET_CONFIG_FIELD.items()
    }
    assert actual == EXPECTED_GET_TO_SET_SCHEMA


@pytest.mark.parametrize(("field", "value", "expected"), PATCH_CASES)
def test_encode_exact_wire_bytes(
    field: SetConfigField,
    value: bool | int,
    expected: bytes,
) -> None:
    patch = SetConfigPatch(field, value)
    assert encode_set_config_patch(patch) == expected
    assert encode_set_config_patch(patch) == expected


@pytest.mark.parametrize(("field", "value", "payload"), PATCH_CASES)
def test_round_trip_preserves_typed_patch(
    field: SetConfigField,
    value: bool | int,
    payload: bytes,
) -> None:
    decoded = decode_set_config_patch(payload)
    assert decoded == SetConfigPatch(field, value)
    assert type(decoded.value) is type(value)


def test_decode_accepts_other_bytes_like_inputs() -> None:
    expected = SetConfigPatch(SetConfigField.CHILD_LOCK_ENABLED, True)
    assert decode_set_config_patch(bytearray(b"\x40\x01")) == expected
    assert decode_set_config_patch(memoryview(b"\x40\x01")) == expected


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        (SetConfigField.VOLUME_PERCENTAGE, True, "requires int"),
        (SetConfigField.VOLUME_PERCENTAGE, 1.0, "requires int"),
        (SetConfigField.VOLUME_PERCENTAGE, "50", "requires int"),
        (SetConfigField.CHILD_LOCK_ENABLED, 1, "requires bool"),
        (SetConfigField.CHILD_LOCK_ENABLED, "true", "requires bool"),
        (SetConfigField.AVOID_MODE, 1, "requires AvoidMode"),
        (SetConfigField.AVOID_MODE, CleanMode.SMART, "requires AvoidMode"),
        (SetConfigField.LANGUAGE, 3, "requires Language"),
        (
            SetConfigField.DRY_MOP_STRENGTH,
            CleanMopFrequency.NORMAL,
            "requires DryMopStrength",
        ),
        (
            SetConfigField.CLEAN_MOP_FREQUENCY,
            DryMopStrength.STRONG,
            "requires CleanMopFrequency",
        ),
        (
            SetConfigField.CARPET_CLEAN_OPTION,
            CleanMode.MOP,
            "requires CarpetCleanOption",
        ),
        (SetConfigField.STATION_CLEAN_MODE, 3, "requires CleanMode"),
    ],
)
def test_patch_rejects_wrong_python_types(
    field: SetConfigField,
    value: object,
    message: str,
) -> None:
    with pytest.raises(ConfigCodecError, match=message):
        SetConfigPatch(field, value)  # type: ignore[arg-type]


@pytest.mark.parametrize("value", [-1, 101])
def test_volume_rejects_values_outside_percentage_range(value: int) -> None:
    with pytest.raises(ConfigCodecError, match="between 0 and 100"):
        SetConfigPatch(SetConfigField.VOLUME_PERCENTAGE, value)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        (SetConfigField.LANGUAGE, Language.UNSPECIFIED),
        (SetConfigField.DRY_MOP_STRENGTH, DryMopStrength.UNSPECIFIED),
        (SetConfigField.CLEAN_MOP_FREQUENCY, CleanMopFrequency.UNSPECIFIED),
        (SetConfigField.CARPET_CLEAN_OPTION, CarpetCleanOption.UNSPECIFIED),
        (SetConfigField.STATION_CLEAN_MODE, CleanMode.UNSPECIFIED),
        (SetConfigField.AVOID_MODE, AvoidMode.UNSPECIFIED),
        (SetConfigField.ROBOT_CLEAN_MODE, CleanMode.UNSPECIFIED),
        (SetConfigField.CORNER_CLEAN_MODE, CornerCleanMode.UNSPECIFIED),
        (
            SetConfigField.CARPET_CLEAN_PRIORITY_OPTION,
            CarpetCleanPriorityOption.UNSPECIFIED,
        ),
        (SetConfigField.CARPET_DEEP_CLEAN_OPTION, CarpetDeepCleanOption.UNSPECIFIED),
        (SetConfigField.STATION_LIGHT_CTRL_TYPE, StationLightCtrlType.UNSPECIFIED),
    ],
)
def test_patch_rejects_unspecified_enum_values(
    field: SetConfigField,
    value: int,
) -> None:
    with pytest.raises(ConfigCodecError, match="between 1"):
        SetConfigPatch(field, value)


def test_patch_requires_field_enum_not_raw_get_response_number() -> None:
    with pytest.raises(ConfigCodecError, match="SetConfigField"):
        SetConfigPatch(7, True)  # type: ignore[arg-type]


def test_patch_is_immutable() -> None:
    patch = SetConfigPatch(SetConfigField.CHILD_LOCK_ENABLED, True)
    with pytest.raises(FrozenInstanceError):
        patch.value = False  # type: ignore[misc]


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (b"", "cannot be empty"),
        (b"\x80", "truncated"),
        (b"\x08", "truncated"),
        (b"\x00\x01", "field number 0"),
        (b"\x0a\x00", "wire type 2"),
        (b"\x38\x01", "unsupported SetConfig field 7"),
        (b"\x40\x02", "must be 0 or 1"),
        (bytes.fromhex("10 10"), "unknown Language"),
        (bytes.fromhex("10 00"), "between 1 and 15"),
        (bytes.fromhex("68 04"), "unknown DryMopStrength"),
        (bytes.fromhex("68 00"), "between 1 and 3"),
        (bytes.fromhex("70 04"), "unknown CleanMopFrequency"),
        (bytes.fromhex("70 00"), "between 1 and 3"),
        (bytes.fromhex("78 05"), "unknown CarpetCleanOption"),
        (bytes.fromhex("78 00"), "between 1 and 4"),
        (bytes.fromhex("a8 01 07"), "unknown CleanMode"),
        (bytes.fromhex("a8 01 00"), "between 1 and 6"),
        (bytes.fromhex("d0 01 02"), "must be 0 or 1"),
        (bytes.fromhex("90 02 04"), "unknown AvoidMode"),
        (bytes.fromhex("90 02 00"), "between 1 and 3"),
        (bytes.fromhex("88 00 01"), "non-canonical"),
        (bytes.fromhex("08 81 00"), "non-canonical"),
        (bytes.fromhex("08 32 40 01"), "exactly one field"),
        (bytes.fromhex("40 01 40 00"), "exactly one field"),
    ],
)
def test_decode_rejects_malformed_or_unsafe_payloads(payload: bytes, message: str) -> None:
    with pytest.raises(ConfigCodecError, match=message):
        decode_set_config_patch(payload)


def test_decode_rejects_non_bytes_input() -> None:
    with pytest.raises(ConfigCodecError, match="bytes-like"):
        decode_set_config_patch("40 01")  # type: ignore[arg-type]


def test_encode_requires_validated_patch_dataclass() -> None:
    with pytest.raises(ConfigCodecError, match="SetConfigPatch"):
        encode_set_config_patch((SetConfigField.CHILD_LOCK_ENABLED, True))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("response_field", "set_field", "raw_value", "expected"),
    GET_CONFIG_CASES,
)
def test_decode_direct_get_config_values_are_typed(
    response_field: GetConfigField,
    set_field: SetConfigField,
    raw_value: object,
    expected: object,
) -> None:
    snapshot = decode_get_config_response({str(int(response_field)): raw_value})

    assert type(snapshot) is ConfigSnapshot
    assert snapshot.values == {set_field: expected}
    assert type(snapshot.values[set_field]) is type(expected)
    assert snapshot.raw_fields == {int(response_field): raw_value}
    assert snapshot.service_result is None


def test_decode_uses_response_numbers_not_neighboring_setter_numbers() -> None:
    snapshot = decode_get_config_response(
        {
            "45": 2,
            "46": 2,
            "47": 1,
            "48": [{"1": 3, "2": b"hello"}],
            "49": 1,
            "50": 0,
            "51": 2,
        }
    )

    assert snapshot.values == {
        SetConfigField.CARPET_CLEAN_PRIORITY_OPTION: (
            CarpetCleanPriorityOption.CARPET_FIRST
        ),
        SetConfigField.CARPET_DEEP_CLEAN_OPTION: CarpetDeepCleanOption.DISABLE,
        SetConfigField.ALL_THINGS_RECOGNITION_ENABLED: True,
        SetConfigField.PRECIOUS_ITEM_GUARD_ENABLED: False,
        SetConfigField.STATION_LIGHT_CTRL_TYPE: StationLightCtrlType.ON,
    }
    assert 45 in snapshot.raw_fields
    assert 48 in snapshot.raw_fields
    assert SetConfigField.ALL_THINGS_RECOGNITION_ENABLED in snapshot.values
    assert SetConfigField.PRECIOUS_ITEM_GUARD_ENABLED in snapshot.values


def test_decode_unwraps_response_field_two_and_separates_service_result() -> None:
    service_result = {"1": 1, "2": bytearray(b"ok")}
    snapshot = decode_get_config_response(
        {
            "1": service_result,
            "2": {
                "1": 55,
                "2": 3,
                "7": 1,
                "34": 2,
            },
        }
    )

    assert snapshot.values == {
        SetConfigField.VOLUME_PERCENTAGE: 55,
        SetConfigField.LANGUAGE: Language.ENGLISH,
        SetConfigField.CHILD_LOCK_ENABLED: True,
        SetConfigField.AVOID_MODE: AvoidMode.SAFER,
    }
    assert snapshot.raw_fields == {1: 55, 2: 3, 7: 1, 34: 2}
    assert snapshot.service_result == {"1": 1, "2": b"ok"}


def test_nested_field_two_is_wrapper_even_with_scalar_service_result() -> None:
    snapshot = decode_get_config_response({"1": 6, "2": {"7": 1}})

    assert snapshot.values == {SetConfigField.CHILD_LOCK_ENABLED: True}
    assert snapshot.raw_fields == {7: 1}
    assert snapshot.service_result == 6


def test_direct_config_scalar_language_field_is_decoded_not_treated_as_wrapper() -> None:
    snapshot = decode_get_config_response({"1": 52, "2": 3, "7": 1})

    assert snapshot.values == {
        SetConfigField.VOLUME_PERCENTAGE: 52,
        SetConfigField.LANGUAGE: Language.ENGLISH,
        SetConfigField.CHILD_LOCK_ENABLED: True,
    }
    assert snapshot.raw_fields == {1: 52, 2: 3, 7: 1}
    assert snapshot.service_result is None


def test_new_config_fields_are_exposed_as_typed_attributes() -> None:
    snapshot = decode_get_config_response(
        {
            "2": {
                "2": 3,
                "12": 3,
                "13": 2,
                "15": 4,
                "21": 3,
                "26": 1,
                "31": 0,
                "36": 1,
                "37": 0,
                "39": 1,
                "40": 0,
            }
        }
    )

    attributes = config_snapshot_attributes(snapshot)

    assert attributes["typed_values"] == {
        "language": 3,
        "dryMopStrength": 3,
        "cleanMopFreq": 2,
        "carpetCleanOption": 4,
        "stationCleanMode": 3,
        "moistureProofPadProtectEnabled": True,
        "dryRobotBagEnabled": False,
        "speechControlEnabled": True,
        "automaticPoweroffWhenDischarging": False,
        "aiVoiceSoundEffectEnabled": True,
        "aiVoiceSoundEffectForWaitingEnabled": False,
    }
    assert attributes["enum_names"] == {
        "language": "english",
        "dryMopStrength": "smart",
        "cleanMopFreq": "normal",
        "carpetCleanOption": "avoid",
        "stationCleanMode": "mop",
    }


def test_absent_protobuf_default_fields_are_not_synthesized() -> None:
    snapshot = decode_get_config_response({"2": {}})

    assert snapshot.values == {}
    assert snapshot.raw_fields == {}
    assert config_snapshot_attributes(snapshot)["typed_values"] == {}


def test_unknown_fields_are_deeply_frozen_and_preserved_raw() -> None:
    nested_unknown = {"1": [bytearray(b"a"), {"2": memoryview(b"b")}]}
    snapshot = decode_get_config_response(
        {
            "2": 0,
            "48": [{"1": 3, "2": b"hello"}],
            "99": nested_unknown,
        }
    )
    nested_unknown["1"].append(b"later")

    assert snapshot.values == {}
    assert snapshot.raw_fields[2] == 0
    assert snapshot.raw_fields[48] == ({"1": 3, "2": b"hello"},)
    assert snapshot.raw_fields[99] == {"1": (b"a", {"2": b"b"})}
    with pytest.raises(TypeError):
        snapshot.raw_fields[99]["new"] = 1  # type: ignore[index]


@pytest.mark.parametrize(
    ("response_field", "raw_value", "set_field"),
    [
        (1, True, SetConfigField.VOLUME_PERCENTAGE),
        (1, -1, SetConfigField.VOLUME_PERCENTAGE),
        (1, 101, SetConfigField.VOLUME_PERCENTAGE),
        (1, "50", SetConfigField.VOLUME_PERCENTAGE),
        (2, 0, SetConfigField.LANGUAGE),
        (2, 16, SetConfigField.LANGUAGE),
        (2, True, SetConfigField.LANGUAGE),
        (7, 2, SetConfigField.CHILD_LOCK_ENABLED),
        (7, "1", SetConfigField.CHILD_LOCK_ENABLED),
        (7, b"1", SetConfigField.CHILD_LOCK_ENABLED),
        (12, 0, SetConfigField.DRY_MOP_STRENGTH),
        (12, 4, SetConfigField.DRY_MOP_STRENGTH),
        (13, 0, SetConfigField.CLEAN_MOP_FREQUENCY),
        (13, 4, SetConfigField.CLEAN_MOP_FREQUENCY),
        (15, 0, SetConfigField.CARPET_CLEAN_OPTION),
        (15, 5, SetConfigField.CARPET_CLEAN_OPTION),
        (21, 0, SetConfigField.STATION_CLEAN_MODE),
        (21, 7, SetConfigField.STATION_CLEAN_MODE),
        (26, 2, SetConfigField.MOISTURE_PROOF_PAD_PROTECT_ENABLED),
        (34, 0, SetConfigField.AVOID_MODE),
        (34, 4, SetConfigField.AVOID_MODE),
        (34, True, SetConfigField.AVOID_MODE),
        (34, CleanMode.SMART, SetConfigField.AVOID_MODE),
        (35, 7, SetConfigField.ROBOT_CLEAN_MODE),
        (46, 0, SetConfigField.CARPET_CLEAN_PRIORITY_OPTION),
        (46, 3, SetConfigField.CARPET_CLEAN_PRIORITY_OPTION),
        (51, 0, SetConfigField.STATION_LIGHT_CTRL_TYPE),
        (51, 3, SetConfigField.STATION_LIGHT_CTRL_TYPE),
        (51, {"1": 2}, SetConfigField.STATION_LIGHT_CTRL_TYPE),
    ],
)
def test_malformed_supported_values_remain_raw_and_are_not_promoted(
    response_field: int,
    raw_value: object,
    set_field: SetConfigField,
) -> None:
    snapshot = decode_get_config_response({response_field: raw_value})

    assert set_field not in snapshot.values
    assert snapshot.raw_fields[response_field] == raw_value


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ([], "must be a mapping"),
        ({"not-a-field": 1}, "is not numeric"),
        ({"01": 1}, "is not canonical"),
        ({"0": 1}, "must be positive"),
        ({"1": 1, 1: 2}, "duplicate field number 1"),
        ({"2": {"nested": 1}}, "is not numeric"),
    ],
)
def test_get_config_rejects_malformed_mapping_shapes(
    data: object,
    message: str,
) -> None:
    with pytest.raises(ConfigCodecError, match=message):
        decode_get_config_response(data)  # type: ignore[arg-type]


def test_config_snapshot_mappings_and_attributes_are_immutable() -> None:
    snapshot = decode_get_config_response({"1": 42, "7": 1, "52": [1, 2]})

    with pytest.raises(FrozenInstanceError):
        snapshot.service_result = 1  # type: ignore[misc]
    with pytest.raises(TypeError):
        snapshot.values[SetConfigField.VOLUME_PERCENTAGE] = 5  # type: ignore[index]
    with pytest.raises(TypeError):
        snapshot.raw_fields[52] = (3,)  # type: ignore[index]
    assert snapshot.raw_fields[52] == (1, 2)


def test_home_assistant_codec_is_an_exact_mirror() -> None:
    repository = Path(__file__).resolve().parents[1]
    package_codec = repository / "narwal_client" / "config.py"
    integration_codec = (
        repository / "custom_components" / "narwal" / "narwal_client" / "config.py"
    )
    assert integration_codec.read_bytes() == package_codec.read_bytes()
