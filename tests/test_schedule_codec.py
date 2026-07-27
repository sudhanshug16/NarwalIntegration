"""Tests for the APK-recovered Narwal clean-schedule protobuf schema."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from narwal_client.schedule import (
    AddCleanScheduleRequest,
    AddCleanScheduleResponse,
    CleanMode,
    CleanSchedule,
    CleanScheduleParam,
    Crontab,
    DeleteCleanSchedulesRequest,
    DeleteCleanSchedulesResponse,
    GetCleanSchedulesRequest,
    GetCleanSchedulesResponse,
    RawProtobufField,
    ScheduleCodecError,
    ScheduleError,
    ScheduleErrorCode,
    UpdateCleanScheduleRequest,
    UpdateCleanScheduleResponse,
    decode_add_clean_schedule_request,
    decode_add_clean_schedule_response,
    decode_clean_schedule,
    decode_clean_schedule_param,
    decode_crontab,
    decode_delete_clean_schedules_request,
    decode_delete_clean_schedules_response,
    decode_get_clean_schedules_request,
    decode_get_clean_schedules_response,
    decode_schedule_error_code,
    decode_update_clean_schedule_request,
    decode_update_clean_schedule_response,
    encode_add_clean_schedule_request,
    encode_add_clean_schedule_response,
    encode_clean_schedule,
    encode_clean_schedule_param,
    encode_crontab,
    encode_delete_clean_schedules_request,
    encode_delete_clean_schedules_response,
    encode_get_clean_schedules_request,
    encode_get_clean_schedules_response,
    encode_schedule_error_code,
    encode_update_clean_schedule_request,
    encode_update_clean_schedule_response,
)

CRONTAB = Crontab("0 9 * * 1", 15, True)
PARAMETER = CleanScheduleParam(
    CRONTAB,
    300,
    CleanMode.SWEEP_THEN_MOP,
    True,
    "Night",
)
SCHEDULE = CleanSchedule(7, PARAMETER)
SUCCESS = ScheduleErrorCode(ScheduleError.SUCCESS, "ok")

CRONTAB_WIRE = bytes.fromhex("0a 09 30 20 39 20 2a 20 2a 20 31 10 0f 18 01")
PARAMETER_WIRE = bytes.fromhex(
    "0a 0f 0a 09 30 20 39 20 2a 20 2a 20 31 10 0f 18 01 10 ac 02 18 05 20 01 2a 05 4e 69 67 68 74"
)
SCHEDULE_WIRE = bytes.fromhex(
    "08 07 12 1f "
    "0a 0f 0a 09 30 20 39 20 2a 20 2a 20 31 10 0f 18 01 "
    "10 ac 02 18 05 20 01 2a 05 4e 69 67 68 74"
)
SUCCESS_WIRE = bytes.fromhex("08 01 12 02 6f 6b")


def test_recovered_enum_values_are_exact() -> None:
    assert {member.name: int(member) for member in ScheduleError} == {
        "UNSPECIFIED": 0,
        "SUCCESS": 1,
        "UNKNOWN_FAILURE": 2,
        "CLEAN_PLAN_MISSED": 3,
        "TASK_ID_NOT_EXIST": 4,
        "DATABASE_FULL": 5,
        "PARAMETER_ERROR": 6,
        "INTERNAL_ERROR": 7,
    }
    assert {member.name: int(member) for member in CleanMode} == {
        "UNSPECIFIED": 0,
        "SMART": 1,
        "SWEEP": 2,
        "MOP": 3,
        "SWEEP_AND_MOP_SYNC": 4,
        "SWEEP_THEN_MOP": 5,
        "COMPOSITE": 6,
    }


@pytest.mark.parametrize(
    ("value", "encoder", "decoder", "wire"),
    [
        (CRONTAB, encode_crontab, decode_crontab, CRONTAB_WIRE),
        (
            PARAMETER,
            encode_clean_schedule_param,
            decode_clean_schedule_param,
            PARAMETER_WIRE,
        ),
        (SCHEDULE, encode_clean_schedule, decode_clean_schedule, SCHEDULE_WIRE),
        (
            SUCCESS,
            encode_schedule_error_code,
            decode_schedule_error_code,
            SUCCESS_WIRE,
        ),
    ],
)
def test_nested_messages_use_exact_wire_layout(
    value: object,
    encoder: Callable[[object], bytes],
    decoder: Callable[[bytes], object],
    wire: bytes,
) -> None:
    assert encoder(value) == wire
    assert decoder(wire) == value


@pytest.mark.parametrize(
    ("value", "encoder", "decoder", "wire"),
    [
        (
            GetCleanSchedulesRequest(),
            encode_get_clean_schedules_request,
            decode_get_clean_schedules_request,
            b"",
        ),
        (
            GetCleanSchedulesResponse(SUCCESS, (SCHEDULE,)),
            encode_get_clean_schedules_response,
            decode_get_clean_schedules_response,
            bytes.fromhex(
                "0a 06 08 01 12 02 6f 6b 12 23 "
                "08 07 12 1f "
                "0a 0f 0a 09 30 20 39 20 2a 20 2a 20 31 10 0f 18 01 "
                "10 ac 02 18 05 20 01 2a 05 4e 69 67 68 74"
            ),
        ),
        (
            AddCleanScheduleRequest(PARAMETER),
            encode_add_clean_schedule_request,
            decode_add_clean_schedule_request,
            bytes.fromhex(
                "0a 1f "
                "0a 0f 0a 09 30 20 39 20 2a 20 2a 20 31 10 0f 18 01 "
                "10 ac 02 18 05 20 01 2a 05 4e 69 67 68 74"
            ),
        ),
        (
            AddCleanScheduleResponse(SUCCESS, 300),
            encode_add_clean_schedule_response,
            decode_add_clean_schedule_response,
            bytes.fromhex("0a 06 08 01 12 02 6f 6b 10 ac 02"),
        ),
        (
            UpdateCleanScheduleRequest(SCHEDULE),
            encode_update_clean_schedule_request,
            decode_update_clean_schedule_request,
            bytes.fromhex(
                "0a 23 08 07 12 1f "
                "0a 0f 0a 09 30 20 39 20 2a 20 2a 20 31 10 0f 18 01 "
                "10 ac 02 18 05 20 01 2a 05 4e 69 67 68 74"
            ),
        ),
        (
            UpdateCleanScheduleResponse(SUCCESS),
            encode_update_clean_schedule_response,
            decode_update_clean_schedule_response,
            bytes.fromhex("0a 06 08 01 12 02 6f 6b"),
        ),
        (
            DeleteCleanSchedulesRequest((1, 300, (1 << 32) - 1)),
            encode_delete_clean_schedules_request,
            decode_delete_clean_schedules_request,
            bytes.fromhex("0a 08 01 ac 02 ff ff ff ff 0f"),
        ),
        (
            DeleteCleanSchedulesResponse(SUCCESS),
            encode_delete_clean_schedules_response,
            decode_delete_clean_schedules_response,
            bytes.fromhex("0a 06 08 01 12 02 6f 6b"),
        ),
    ],
)
def test_operation_messages_use_exact_wire_layout(
    value: object,
    encoder: Callable[[object], bytes],
    decoder: Callable[[bytes], object],
    wire: bytes,
) -> None:
    assert encoder(value) == wire
    assert decoder(wire) == value


def test_get_response_decodes_repeated_schedule_list() -> None:
    response = GetCleanSchedulesResponse(
        ScheduleErrorCode(ScheduleError.SUCCESS),
        (
            CleanSchedule(1, CleanScheduleParam(clean_plan_id=10)),
            CleanSchedule(2, CleanScheduleParam(clean_plan_id=20)),
        ),
    )

    decoded = decode_get_clean_schedules_response(encode_get_clean_schedules_response(response))

    assert decoded == response
    assert decoded.clean_schedules[0].task_id == 1
    assert decoded.clean_schedules[1].clean_schedule_param is not None
    assert decoded.clean_schedules[1].clean_schedule_param.clean_plan_id == 20


def test_scalar_presence_distinguishes_absent_and_explicit_defaults() -> None:
    explicit = Crontab("", 0, False)
    wire = bytes.fromhex("0a 00 10 00 18 00")

    assert encode_crontab(Crontab()) == b""
    assert decode_crontab(b"") == Crontab()
    assert encode_crontab(explicit) == wire
    assert decode_crontab(wire) == explicit
    assert (
        encode_clean_schedule_param(CleanScheduleParam(clean_mode=CleanMode.UNSPECIFIED))
        == b"\x18\x00"
    )


@pytest.mark.parametrize("value", [-(1 << 31), -1, 0, (1 << 31) - 1])
def test_reminding_time_supports_the_full_recovered_int32_range(value: int) -> None:
    crontab = Crontab(reminding_time=value)
    assert decode_crontab(encode_crontab(crontab)) == crontab


def test_negative_int32_uses_sign_extended_ten_byte_varint() -> None:
    wire = bytes.fromhex("10 ff ff ff ff ff ff ff ff ff 01")
    assert encode_crontab(Crontab(reminding_time=-1)) == wire
    assert decode_crontab(wire) == Crontab(reminding_time=-1)


def test_delete_accepts_unpacked_uint32_for_protobuf_compatibility() -> None:
    decoded = decode_delete_clean_schedules_request(bytes.fromhex("08 01 08 ac 02"))

    assert decoded == DeleteCleanSchedulesRequest((1, 300))
    assert encode_delete_clean_schedules_request(decoded) == bytes.fromhex("0a 03 01 ac 02")


def test_unknown_fields_are_immutable_and_reencoded() -> None:
    payload = bytes.fromhex(
        "0a 06 08 01 12 02 6f 6b 10 ac 02 48 07 52 01 78 59 01 02 03 04 05 06 07 08 65 09 0a 0b 0c"
    )

    decoded = decode_add_clean_schedule_response(payload)

    assert decoded.task_id == 300
    assert decoded.unknown_fields == (
        RawProtobufField(9, 0, 7),
        RawProtobufField(10, 2, b"x"),
        RawProtobufField(11, 1, bytes.fromhex("01 02 03 04 05 06 07 08")),
        RawProtobufField(12, 5, bytes.fromhex("09 0a 0b 0c")),
    )
    assert encode_add_clean_schedule_response(decoded) == payload


def test_nested_unknown_fields_survive_operation_round_trip() -> None:
    unknown = RawProtobufField(9, 0, 42)
    request = AddCleanScheduleRequest(
        CleanScheduleParam(
            crontab=Crontab(
                cron="0 1 * * *",
                unknown_fields=(unknown,),
            ),
            clean_plan_id=4,
            unknown_fields=(RawProtobufField(8, 2, b"future"),),
        )
    )

    assert decode_add_clean_schedule_request(encode_add_clean_schedule_request(request)) == request


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (lambda: Crontab(reminding_time=-(1 << 31) - 1), "reminding_time"),
        (lambda: Crontab(reminding_time=1 << 31), "reminding_time"),
        (lambda: CleanSchedule(task_id=-1), "task_id"),
        (lambda: CleanSchedule(task_id=1 << 32), "task_id"),
        (lambda: CleanScheduleParam(clean_plan_id=True), "clean_plan_id"),
        (lambda: CleanScheduleParam(clean_mode=3), "CleanMode"),
        (lambda: CleanScheduleParam(is_custom_plan=1), "is_custom_plan"),
        (lambda: Crontab(enabled=1), "enabled"),
        (lambda: Crontab(cron=b"cron"), "cron"),
        (lambda: DeleteCleanSchedulesRequest((None,)), "task_id"),
        (
            lambda: ScheduleErrorCode(code=1),
            "ScheduleError",
        ),
        (
            lambda: RawProtobufField(0, 0, 1),
            "field number",
        ),
        (
            lambda: RawProtobufField(9, 3, b""),
            "unsupported wire type",
        ),
        (
            lambda: RawProtobufField(9, 1, b"short"),
            "exactly 8 bytes",
        ),
    ],
)
def test_models_reject_invalid_types_and_ranges(
    factory: Callable[[], object],
    message: str,
) -> None:
    with pytest.raises(ScheduleCodecError, match=message):
        factory()


@pytest.mark.parametrize(
    ("decoder", "payload", "message"),
    [
        (decode_crontab, b"\x10\x80", "truncated"),
        (decode_crontab, b"\x10\x80\x00", "non-canonical"),
        (decode_crontab, b"\x00", "field number 0"),
        (decode_crontab, b"\x0b", "unsupported wire type 3"),
        (decode_crontab, b"\x0a\x02x", "truncated"),
        (decode_crontab, b"\x0a\x01\xff", "valid UTF-8"),
        (decode_crontab, b"\x18\x02", "must be 0 or 1"),
        (decode_crontab, b"\x0a\x00\x0a\x00", "duplicate singular"),
        (
            decode_crontab,
            bytes.fromhex("10 80 80 80 80 08"),
            "outside int32",
        ),
        (
            decode_crontab,
            bytes.fromhex("10 ff ff ff ff 0f"),
            "outside int32",
        ),
        (
            decode_clean_schedule_param,
            bytes.fromhex("10 80 80 80 80 10"),
            "exceeds uint32",
        ),
        (
            decode_clean_schedule_param,
            bytes.fromhex("18 07"),
            "unknown CleanMode",
        ),
        (
            decode_clean_schedule_param,
            bytes.fromhex("20 02"),
            "must be 0 or 1",
        ),
        (
            decode_schedule_error_code,
            bytes.fromhex("08 08"),
            "unknown ScheduleError",
        ),
        (
            decode_clean_schedule,
            bytes.fromhex("0a 00"),
            "requires wire type 0",
        ),
        (
            decode_delete_clean_schedules_request,
            bytes.fromhex("0a 05 80 80 80 80 10"),
            "exceeds uint32",
        ),
    ],
)
def test_decoders_reject_malformed_or_schema_invalid_wire(
    decoder: Callable[[bytes], object],
    payload: bytes,
    message: str,
) -> None:
    with pytest.raises(ScheduleCodecError, match=message):
        decoder(payload)


def test_decoders_accept_other_bytes_like_inputs() -> None:
    expected = Crontab(enabled=True)
    assert decode_crontab(bytearray(b"\x18\x01")) == expected
    assert decode_crontab(memoryview(b"\x18\x01")) == expected


def test_decoder_rejects_non_bytes_input() -> None:
    with pytest.raises(ScheduleCodecError, match="bytes-like"):
        decode_crontab("18 01")  # type: ignore[arg-type]


def test_unknown_fields_cannot_shadow_known_fields() -> None:
    with pytest.raises(ScheduleCodecError, match="known"):
        Crontab(unknown_fields=(RawProtobufField(1, 2, b"x"),))


def test_repeated_inputs_are_frozen() -> None:
    schedules = [SCHEDULE]
    response = GetCleanSchedulesResponse(clean_schedules=schedules)
    schedules.append(CleanSchedule(8))

    assert response.clean_schedules == (SCHEDULE,)
    with pytest.raises(FrozenInstanceError):
        response.error_code = SUCCESS  # type: ignore[misc]


def test_home_assistant_codec_is_an_exact_mirror() -> None:
    repository = Path(__file__).resolve().parents[1]
    package_codec = repository / "narwal_client" / "schedule.py"
    integration_codec = (
        repository / "custom_components" / "narwal" / "narwal_client" / "schedule.py"
    )
    assert integration_codec.read_bytes() == package_codec.read_bytes()
