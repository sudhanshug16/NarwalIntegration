"""Tests for APK-recovered firmware, language, and voice metadata codecs."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from narwal_client.config import Language
from narwal_client.device_metadata import (
    DeviceMetadataCodecError,
    FirmwareGroup,
    FirmwareStation,
    FirmwareVersionEntity,
    FirmwareVersionResponse,
    FirmwareVision,
    GetCurrentVoiceInfoResponse,
    GetCurrentVoiceInfoResult,
    GetFirmwareVersionResponse,
    GetLanguageResponse,
    GetLanguageResult,
    GetSupportedLanguagesResponse,
    GetSupportedLanguagesResult,
    RawMetadataField,
    VoiceInfo,
    decode_firmware_group,
    decode_firmware_station,
    decode_firmware_version_entity,
    decode_firmware_version_response,
    decode_firmware_vision,
    decode_get_current_voice_info_response,
    decode_get_firmware_version_response,
    decode_get_language_response,
    decode_get_supported_languages_response,
    decode_voice_info,
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


def _varint_field(number: int, value: int) -> bytes:
    return _varint(number << 3) + _varint(value)


def _bytes_field(number: int, value: bytes) -> bytes:
    return _varint((number << 3) | 2) + _varint(len(value)) + value


def _string_field(number: int, value: str) -> bytes:
    return _bytes_field(number, value.encode())


def _entity_wire(firmware_id: str, version: int, version_text: str) -> bytes:
    return (
        _string_field(1, firmware_id)
        + _varint_field(2, version)
        + _string_field(3, version_text)
    )


def test_recovered_result_enum_values_are_exact() -> None:
    assert {member.name: int(member) for member in GetLanguageResult} == {
        "UNSPECIFIED": 0,
        "SUCCESS": 1,
        "FAILED": 2,
    }
    assert {member.name: int(member) for member in GetSupportedLanguagesResult} == {
        "UNSPECIFIED": 0,
        "SUCCESS": 1,
        "FAILED": 2,
        "LIST_EMPTY": 3,
    }
    assert {member.name: int(member) for member in GetCurrentVoiceInfoResult} == {
        "UNSPECIFIED": 0,
        "SUCCESS": 1,
        "FAILED": 2,
    }


def test_firmware_leaf_uses_exact_string_uint32_string_layout() -> None:
    wire = bytes.fromhex("0a 03 6d 63 75 10 ac 02 1a 05 31 2e 32 2e 33")

    assert decode_firmware_version_entity(wire) == FirmwareVersionEntity(
        "mcu",
        300,
        "1.2.3",
    )


def test_decode_complete_firmware_response_and_all_proven_nested_fields() -> None:
    robot_wire = (
        _bytes_field(1, _entity_wire("robot-mcu", 1, "m1"))
        + _bytes_field(2, _entity_wire("robot-ble", 2, "b2"))
        + _bytes_field(3, _entity_wire("robot-cpu", 3, "c3"))
        + _bytes_field(4, _entity_wire("robot-media", 4, "m4"))
        + _bytes_field(5, _entity_wire("front-sensor", 5, "s5"))
        + _bytes_field(5, _entity_wire("side-sensor", 6, "s6"))
    )
    station_wire = (
        _bytes_field(1, _entity_wire("station-mcu", 11, "sm11"))
        + _bytes_field(2, _entity_wire("station-ble", 12, "sb12"))
        + _bytes_field(3, _entity_wire("station-cpu", 13, "sc13"))
        + _bytes_field(4, _entity_wire("station-media", 14, "sa14"))
        + _bytes_field(5, _entity_wire("station-media-b", 15, "sb15"))
    )
    vision_wire = _bytes_field(1, _entity_wire("vision-ai", 21, "ai21")) + _bytes_field(
        2,
        _entity_wire("vision-cpu", 22, "vc22"),
    )
    payload = (
        _varint_field(1, (1 << 32) - 1)
        + _string_field(2, "AX15-9.9.9")
        + _bytes_field(3, robot_wire)
        + _bytes_field(4, station_wire)
        + _bytes_field(5, vision_wire)
    )

    decoded = decode_firmware_version_response(payload)

    assert decoded.firmware_version == (1 << 32) - 1
    assert decoded.firmware_version_text == "AX15-9.9.9"
    assert decoded.robot == FirmwareGroup(
        FirmwareVersionEntity("robot-mcu", 1, "m1"),
        FirmwareVersionEntity("robot-ble", 2, "b2"),
        FirmwareVersionEntity("robot-cpu", 3, "c3"),
        FirmwareVersionEntity("robot-media", 4, "m4"),
        (
            FirmwareVersionEntity("front-sensor", 5, "s5"),
            FirmwareVersionEntity("side-sensor", 6, "s6"),
        ),
    )
    assert decoded.station == FirmwareStation(
        FirmwareVersionEntity("station-mcu", 11, "sm11"),
        FirmwareVersionEntity("station-ble", 12, "sb12"),
        FirmwareVersionEntity("station-cpu", 13, "sc13"),
        FirmwareVersionEntity("station-media", 14, "sa14"),
        FirmwareVersionEntity("station-media-b", 15, "sb15"),
    )
    assert decoded.vision == FirmwareVision(
        FirmwareVersionEntity("vision-ai", 21, "ai21"),
        FirmwareVersionEntity("vision-cpu", 22, "vc22"),
    )


def test_empty_firmware_messages_preserve_absence() -> None:
    assert decode_firmware_version_entity(b"") == FirmwareVersionEntity()
    assert decode_firmware_group(b"") == FirmwareGroup()
    assert decode_firmware_station(b"") == FirmwareStation()
    assert decode_firmware_vision(b"") == FirmwareVision()
    assert decode_firmware_version_response(b"") == FirmwareVersionResponse()


def test_explicit_firmware_defaults_remain_distinct_from_absence() -> None:
    decoded = decode_firmware_version_response(b"\x08\x00\x12\x00")

    assert decoded == FirmwareVersionResponse(0, "")
    assert decoded == GetFirmwareVersionResponse(0, "")
    assert decode_get_firmware_version_response(b"\x08\x00\x12\x00") == decoded
    assert decoded != FirmwareVersionResponse()


def test_get_language_uses_result_enum_varint_not_service_result_message() -> None:
    decoded = decode_get_language_response(bytes.fromhex("08 01 10 03"))

    assert decoded == GetLanguageResponse(GetLanguageResult.SUCCESS, Language.ENGLISH)


def test_supported_languages_accept_packed_and_unpacked_wire_forms_in_order() -> None:
    payload = (
        _varint_field(1, GetSupportedLanguagesResult.SUCCESS)
        + _bytes_field(2, _varint(3) + _varint(9))
        + _varint_field(2, 15)
        + _bytes_field(2, _varint(14))
    )

    decoded = decode_get_supported_languages_response(payload)

    assert decoded == GetSupportedLanguagesResponse(
        GetSupportedLanguagesResult.SUCCESS,
        (Language.ENGLISH, Language.FRENCH, Language.VIETNAMESE, Language.THAI),
    )


def test_supported_languages_list_empty_is_endpoint_specific() -> None:
    decoded = decode_get_supported_languages_response(b"\x08\x03")

    assert decoded.result is GetSupportedLanguagesResult.LIST_EMPTY
    assert decoded.languages == ()
    assert 3 not in {int(member) for member in GetLanguageResult}
    assert 3 not in {int(member) for member in GetCurrentVoiceInfoResult}


def test_voice_info_uses_four_string_fields_and_accepts_utf8() -> None:
    voice_wire = (
        _string_field(1, "en-IN")
        + _string_field(2, "2026.7")
        + _string_field(3, "Warm voice – हिन्दी")
        + _string_field(4, "timbre-42")
    )
    payload = _varint_field(1, 1) + _bytes_field(2, voice_wire)

    decoded = decode_get_current_voice_info_response(payload)

    assert decoded == GetCurrentVoiceInfoResponse(
        GetCurrentVoiceInfoResult.SUCCESS,
        VoiceInfo("en-IN", "2026.7", "Warm voice – हिन्दी", "timbre-42"),
    )
    assert decode_voice_info(voice_wire) == decoded.voice_info


@pytest.mark.parametrize(
    ("decoder", "payload"),
    [
        (decode_get_language_response, b"\x08\x63"),
        (decode_get_supported_languages_response, b"\x08\x63"),
        (decode_get_current_voice_info_response, b"\x08\x63"),
    ],
)
def test_unknown_future_result_values_are_preserved(
    decoder: object,
    payload: bytes,
) -> None:
    decoded = decoder(payload)  # type: ignore[operator]
    assert decoded.result == 99
    assert type(decoded.result) is int


def test_known_integer_result_constructor_values_normalize_to_enum_members() -> None:
    assert GetLanguageResponse(1).result is GetLanguageResult.SUCCESS
    assert (
        GetSupportedLanguagesResponse(3).result
        is GetSupportedLanguagesResult.LIST_EMPTY
    )
    assert (
        GetCurrentVoiceInfoResponse(2).result is GetCurrentVoiceInfoResult.FAILED
    )


def test_unknown_fields_are_frozen_at_every_nested_level() -> None:
    entity_wire = _entity_wire("mcu", 1, "one") + _varint_field(9, 7)
    group_wire = _bytes_field(1, entity_wire) + _bytes_field(10, b"future")
    response_wire = _bytes_field(3, group_wire) + bytes.fromhex(
        "59 01 02 03 04 05 06 07 08 65 09 0a 0b 0c"
    )

    decoded = decode_firmware_version_response(response_wire)

    assert decoded.robot is not None
    assert decoded.robot.mcu is not None
    assert decoded.robot.mcu.unknown_fields == (RawMetadataField(9, 0, 7),)
    assert decoded.robot.unknown_fields == (RawMetadataField(10, 2, b"future"),)
    assert decoded.unknown_fields == (
        RawMetadataField(11, 1, bytes.fromhex("01 02 03 04 05 06 07 08")),
        RawMetadataField(12, 5, bytes.fromhex("09 0a 0b 0c")),
    )
    with pytest.raises(FrozenInstanceError):
        decoded.robot.mcu.version = 2


def test_repeated_and_unknown_constructor_lists_are_frozen_to_tuples() -> None:
    entity = FirmwareVersionEntity("sensor")
    group = FirmwareGroup(
        sensor_list=[entity],
        unknown_fields=[RawMetadataField(9, 2, bytearray(b"x"))],
    )

    assert group.sensor_list == (entity,)
    assert group.unknown_fields == (RawMetadataField(9, 2, b"x"),)
    assert type(group.sensor_list) is tuple
    assert type(group.unknown_fields) is tuple


@pytest.mark.parametrize(
    "payload",
    [
        b"\x00",  # field number zero
        b"\x0b",  # unsupported start-group wire type
        b"\x08",  # truncated value varint
        b"\x88\x00\x01",  # non-canonical key varint
        b"\x08\x81\x00",  # non-canonical value varint
        b"\x0a\x02x",  # truncated length-delimited value
        b"\x09\x01\x02",  # truncated fixed64
        b"\x0d\x01\x02",  # truncated fixed32
        b"\x08\xff\xff\xff\xff\xff\xff\xff\xff\xff\x02",  # uint64 overflow
    ],
)
def test_malformed_protobuf_is_rejected(payload: bytes) -> None:
    with pytest.raises(DeviceMetadataCodecError):
        decode_firmware_version_response(payload)


@pytest.mark.parametrize(
    ("decoder", "payload"),
    [
        (decode_firmware_version_entity, b"\x08\x01"),
        (decode_firmware_group, b"\x08\x01"),
        (decode_firmware_station, b"\x08\x01"),
        (decode_firmware_vision, b"\x08\x01"),
        (decode_firmware_version_response, b"\x0a\x00"),
        (decode_get_language_response, b"\x0a\x00"),
        (decode_get_supported_languages_response, b"\x0a\x00"),
        (decode_voice_info, b"\x08\x01"),
        (decode_get_current_voice_info_response, b"\x0a\x00"),
    ],
)
def test_known_fields_require_their_exact_wire_types(
    decoder: object,
    payload: bytes,
) -> None:
    with pytest.raises(DeviceMetadataCodecError, match="requires wire type"):
        decoder(payload)  # type: ignore[operator]


@pytest.mark.parametrize(
    ("decoder", "payload"),
    [
        (decode_firmware_version_entity, b"\x0a\x00\x0a\x00"),
        (decode_firmware_group, b"\x0a\x00\x0a\x00"),
        (decode_firmware_station, b"\x0a\x00\x0a\x00"),
        (decode_firmware_vision, b"\x0a\x00\x0a\x00"),
        (decode_firmware_version_response, b"\x08\x00\x08\x01"),
        (decode_get_language_response, b"\x08\x00\x08\x01"),
        (decode_get_supported_languages_response, b"\x08\x00\x08\x01"),
        (decode_voice_info, b"\x0a\x00\x0a\x00"),
        (decode_get_current_voice_info_response, b"\x08\x00\x08\x01"),
    ],
)
def test_duplicate_singular_fields_are_rejected(
    decoder: object,
    payload: bytes,
) -> None:
    with pytest.raises(DeviceMetadataCodecError, match="duplicate singular"):
        decoder(payload)  # type: ignore[operator]


@pytest.mark.parametrize(
    ("decoder", "payload"),
    [
        (decode_firmware_version_entity, b"\x0a\x01\xff"),
        (decode_firmware_version_response, b"\x12\x01\xff"),
        (decode_voice_info, b"\x1a\x01\xff"),
        (
            decode_get_current_voice_info_response,
            _bytes_field(2, b"\x22\x01\xff"),
        ),
    ],
)
def test_invalid_utf8_is_rejected(decoder: object, payload: bytes) -> None:
    with pytest.raises(DeviceMetadataCodecError, match="UTF-8"):
        decoder(payload)  # type: ignore[operator]


def test_uint32_firmware_versions_do_not_accept_uint64_range() -> None:
    overflow = _varint(1 << 32)

    with pytest.raises(DeviceMetadataCodecError, match="exceeds uint32"):
        decode_firmware_version_response(b"\x08" + overflow)
    with pytest.raises(DeviceMetadataCodecError, match="exceeds uint32"):
        decode_firmware_version_entity(b"\x10" + overflow)
    with pytest.raises(DeviceMetadataCodecError, match="between 0"):
        FirmwareVersionResponse(firmware_version=1 << 32)


def test_unknown_language_and_enum_values_outside_int32_are_rejected() -> None:
    with pytest.raises(DeviceMetadataCodecError, match="unknown Language"):
        decode_get_language_response(_varint_field(2, 16))
    with pytest.raises(DeviceMetadataCodecError, match="unknown Language"):
        decode_get_supported_languages_response(_bytes_field(2, _varint(16)))
    with pytest.raises(DeviceMetadataCodecError, match="outside enum int32"):
        decode_get_language_response(_varint_field(1, 1 << 31))


@pytest.mark.parametrize(
    "payload",
    [None, "bytes", 1, [b"x"]],
)
def test_payload_requires_bytes_like(payload: object) -> None:
    with pytest.raises(DeviceMetadataCodecError, match="bytes-like"):
        decode_get_language_response(payload)  # type: ignore[arg-type]


def test_bytearray_and_memoryview_payloads_are_copied_safely() -> None:
    assert decode_get_language_response(bytearray(b"\x08\x01")).result is GetLanguageResult.SUCCESS
    assert (
        decode_get_language_response(memoryview(b"\x08\x02")).result
        is GetLanguageResult.FAILED
    )


@pytest.mark.parametrize(
    "factory",
    [
        lambda: FirmwareVersionEntity(firmware_id=1),  # type: ignore[arg-type]
        lambda: FirmwareVersionEntity(version=True),
        lambda: FirmwareVersionEntity(version=-1),
        lambda: VoiceInfo(language="\ud800"),
        lambda: FirmwareGroup(mcu=VoiceInfo()),  # type: ignore[arg-type]
        lambda: GetLanguageResponse(result=True),
        lambda: GetLanguageResponse(language=3),  # type: ignore[arg-type]
        lambda: GetSupportedLanguagesResponse(languages=(Language.ENGLISH, 4)),  # type: ignore[arg-type]
        lambda: GetCurrentVoiceInfoResponse(voice_info="voice"),  # type: ignore[arg-type]
    ],
)
def test_models_validate_types_ranges_and_utf8(factory: object) -> None:
    with pytest.raises(DeviceMetadataCodecError):
        factory()  # type: ignore[operator]


def test_known_fields_cannot_be_smuggled_into_unknown_fields() -> None:
    with pytest.raises(DeviceMetadataCodecError, match="known"):
        FirmwareVersionEntity(unknown_fields=(RawMetadataField(1, 2, b"x"),))
    with pytest.raises(DeviceMetadataCodecError, match="known"):
        GetCurrentVoiceInfoResponse(
            unknown_fields=(RawMetadataField(2, 2, b"x"),)
        )


@pytest.mark.parametrize(
    "factory",
    [
        lambda: RawMetadataField(0, 0, 0),
        lambda: RawMetadataField(1, 3, b""),
        lambda: RawMetadataField(1, 0, True),
        lambda: RawMetadataField(1, 0, 1 << 64),
        lambda: RawMetadataField(1, 1, b"short"),
        lambda: RawMetadataField(1, 2, "bytes"),
        lambda: RawMetadataField(1, 5, b"short"),
    ],
)
def test_raw_field_validation_is_strict(factory: object) -> None:
    with pytest.raises(DeviceMetadataCodecError):
        factory()  # type: ignore[operator]


def test_package_and_home_assistant_mirrors_are_byte_identical() -> None:
    root = Path(__file__).resolve().parents[1]

    assert (root / "narwal_client/device_metadata.py").read_bytes() == (
        root / "custom_components/narwal/narwal_client/device_metadata.py"
    ).read_bytes()
