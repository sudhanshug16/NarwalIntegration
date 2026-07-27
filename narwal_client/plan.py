"""Strict read-only decoders for Narwal clean-plan responses.

The field identities and wire types in this module come from the official
Android app's generated protobuf metadata. Nested area-option messages remain
opaque until their individual schemas are implemented.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType


class PlanCodecError(ValueError):
    """Raised when a clean-plan response does not match its proven schema."""


def _normalize_fields(value: object, *, context: str) -> dict[int, object]:
    """Normalize canonical blackboxprotobuf keys and reject ambiguous input."""
    if not isinstance(value, Mapping):
        raise PlanCodecError(f"{context} must be a field mapping")

    normalized: dict[int, object] = {}
    for raw_field, field_value in value.items():
        if type(raw_field) is int:
            field_number = raw_field
        elif type(raw_field) is str:
            try:
                field_number = int(raw_field)
            except ValueError as exc:
                raise PlanCodecError(
                    f"{context} field key {raw_field!r} is not numeric"
                ) from exc
            if str(field_number) != raw_field:
                raise PlanCodecError(
                    f"{context} field key {raw_field!r} is not canonical"
                )
        else:
            raise PlanCodecError(
                f"{context} field keys must be int or canonical decimal str"
            )

        if field_number < 1:
            raise PlanCodecError(
                f"{context} field number {field_number} must be positive"
            )
        if field_number in normalized:
            raise PlanCodecError(
                f"{context} contains duplicate field number {field_number}"
            )
        normalized[field_number] = field_value

    return normalized


def _freeze(value: object) -> object:
    """Recursively freeze decoded values retained for diagnostics."""
    if isinstance(value, Mapping):
        return MappingProxyType(
            {key: _freeze(nested) for key, nested in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, (bytearray, memoryview)):
        return bytes(value)
    if isinstance(value, set):
        return frozenset(_freeze(item) for item in value)
    return value


def _freeze_fields(fields: Mapping[int, object]) -> Mapping[int, object]:
    """Freeze a normalized protobuf field mapping with integer keys."""
    return MappingProxyType(
        {field_number: _freeze(value) for field_number, value in fields.items()}
    )


def _optional_uint(
    fields: Mapping[int, object],
    field_number: int,
    *,
    bits: int,
    context: str,
) -> int | None:
    """Decode an optional uint32/uint64 without coercion."""
    if field_number not in fields:
        return None

    value = fields[field_number]
    maximum = (1 << bits) - 1
    if type(value) is not int or not 0 <= value <= maximum:
        raise PlanCodecError(
            f"{context} must be uint{bits}, got {value!r}"
        )
    return value


def _optional_enum(
    fields: Mapping[int, object],
    field_number: int,
    *,
    context: str,
) -> int | None:
    """Decode an optional enum value while preserving unknown numeric members."""
    if field_number not in fields:
        return None

    value = fields[field_number]
    if type(value) is not int:
        raise PlanCodecError(f"{context} must be an enum integer")
    return value


def _optional_bool(
    fields: Mapping[int, object],
    field_number: int,
    *,
    context: str,
) -> bool | None:
    """Decode an optional protobuf bool from typed or schema-less output."""
    if field_number not in fields:
        return None

    value = fields[field_number]
    if type(value) is bool:
        return value
    if type(value) is int and value in (0, 1):
        return bool(value)
    raise PlanCodecError(f"{context} must be bool or integer 0/1")


def _optional_text(
    fields: Mapping[int, object],
    field_number: int,
    *,
    context: str,
) -> str | None:
    """Decode an optional protobuf string as strict UTF-8."""
    if field_number not in fields:
        return None

    value = fields[field_number]
    if isinstance(value, str):
        return value
    if isinstance(value, (bytes, bytearray, memoryview)):
        try:
            return bytes(value).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise PlanCodecError(f"{context} must contain valid UTF-8") from exc
    raise PlanCodecError(f"{context} must be str or UTF-8 bytes")


def _optional_message(
    fields: Mapping[int, object],
    field_number: int,
    *,
    context: str,
) -> dict[int, object] | None:
    """Decode an optional nested message without assigning field semantics."""
    if field_number not in fields:
        return None
    return _normalize_fields(fields[field_number], context=context)


def _repeated_messages(
    fields: Mapping[int, object],
    field_number: int,
    *,
    context: str,
) -> tuple[dict[int, object], ...]:
    """Normalize a repeated message field from blackboxprotobuf output."""
    if field_number not in fields:
        return ()

    value = fields[field_number]
    if isinstance(value, Mapping):
        values: tuple[object, ...] = (value,)
    elif isinstance(value, (list, tuple)):
        values = tuple(value)
    else:
        raise PlanCodecError(f"{context} must be a message or message sequence")

    return tuple(
        _normalize_fields(item, context=f"{context}[{index}]")
        for index, item in enumerate(values)
    )


@dataclass(frozen=True, slots=True)
class CleanTaskParam:
    """Proven fields from ``CleanTaskParam``."""

    enable_smart_clean: bool | None
    enable_smart_deep_clean: bool | None
    raw_fields: Mapping[int, object]


@dataclass(frozen=True, slots=True)
class CleanAreaOption:
    """Proven top-level fields from ``CleanAreaOption``."""

    zone_id: int | None
    clean_zone_type: int | None
    clean_zone_area: Mapping[int, object] | None
    sweep_area_option: Mapping[int, object] | None
    mop_area_option: Mapping[int, object] | None
    sweep_mop_sync_area_option: Mapping[int, object] | None
    sweep_then_mop_area_option: Mapping[int, object] | None
    raw_fields: Mapping[int, object]


@dataclass(frozen=True, slots=True)
class CleanPlan:
    """A clean plan decoded from the APK-proven protobuf schema."""

    plan_id: int | None
    map_id: int | None
    clean_mode: int | None
    is_custom_plan: bool | None
    custom_name: str | None
    shown_in_station: bool | None
    perform_times: int | None
    order: int | None
    area_options: tuple[CleanAreaOption, ...]
    task_parameters: CleanTaskParam | None
    raw_fields: Mapping[int, object]


@dataclass(frozen=True, slots=True)
class CurrentPlanResponse:
    """Decoded ``clean/cur_plan/get`` response."""

    result_code: int | None
    plan: CleanPlan | None
    raw_fields: Mapping[int, object]


@dataclass(frozen=True, slots=True)
class CleanPlansResponse:
    """Decoded ``clean/plan/get`` response."""

    result_code: int | None
    plans: tuple[CleanPlan, ...]
    raw_fields: Mapping[int, object]


def _decode_task_parameters(fields: Mapping[int, object]) -> CleanTaskParam:
    return CleanTaskParam(
        enable_smart_clean=_optional_bool(
            fields,
            1,
            context="CleanTaskParam.enableSmartClean",
        ),
        enable_smart_deep_clean=_optional_bool(
            fields,
            2,
            context="CleanTaskParam.enableSmartDeepClean",
        ),
        raw_fields=_freeze_fields(fields),
    )


def _decode_area_option(fields: Mapping[int, object]) -> CleanAreaOption:
    opaque_messages = {
        field_number: _optional_message(
            fields,
            field_number,
            context=f"CleanAreaOption.{field_name}",
        )
        for field_number, field_name in (
            (3, "cleanZoneArea"),
            (4, "sweepAreaOption"),
            (5, "mopAreaOption"),
            (6, "sweepMopSyncAreaOption"),
            (7, "sweepThenMopAreaOption"),
        )
    }
    return CleanAreaOption(
        zone_id=_optional_uint(
            fields,
            1,
            bits=64,
            context="CleanAreaOption.zoneId",
        ),
        clean_zone_type=_optional_enum(
            fields,
            2,
            context="CleanAreaOption.cleanZoneType",
        ),
        clean_zone_area=(
            _freeze_fields(opaque_messages[3])
            if opaque_messages[3] is not None
            else None
        ),
        sweep_area_option=(
            _freeze_fields(opaque_messages[4])
            if opaque_messages[4] is not None
            else None
        ),
        mop_area_option=(
            _freeze_fields(opaque_messages[5])
            if opaque_messages[5] is not None
            else None
        ),
        sweep_mop_sync_area_option=(
            _freeze_fields(opaque_messages[6])
            if opaque_messages[6] is not None
            else None
        ),
        sweep_then_mop_area_option=(
            _freeze_fields(opaque_messages[7])
            if opaque_messages[7] is not None
            else None
        ),
        raw_fields=_freeze_fields(fields),
    )


def _decode_clean_plan(fields: Mapping[int, object]) -> CleanPlan:
    area_options = _repeated_messages(
        fields,
        9,
        context="CleanPlan.cleanAreaOptions",
    )
    task_parameter_fields = _optional_message(
        fields,
        10,
        context="CleanPlan.cleanParam",
    )
    return CleanPlan(
        plan_id=_optional_uint(
            fields,
            1,
            bits=32,
            context="CleanPlan.id",
        ),
        map_id=_optional_uint(
            fields,
            2,
            bits=32,
            context="CleanPlan.mapId",
        ),
        clean_mode=_optional_enum(
            fields,
            3,
            context="CleanPlan.cleanMode",
        ),
        is_custom_plan=_optional_bool(
            fields,
            4,
            context="CleanPlan.isCustomPlan",
        ),
        custom_name=_optional_text(
            fields,
            5,
            context="CleanPlan.customName",
        ),
        shown_in_station=_optional_bool(
            fields,
            6,
            context="CleanPlan.shownInStation",
        ),
        perform_times=_optional_uint(
            fields,
            7,
            bits=32,
            context="CleanPlan.performTimes",
        ),
        order=_optional_uint(
            fields,
            8,
            bits=32,
            context="CleanPlan.order",
        ),
        area_options=tuple(
            _decode_area_option(area_fields) for area_fields in area_options
        ),
        task_parameters=(
            _decode_task_parameters(task_parameter_fields)
            if task_parameter_fields is not None
            else None
        ),
        raw_fields=_freeze_fields(fields),
    )


def decode_current_plan_response(data: Mapping[object, object]) -> CurrentPlanResponse:
    """Decode an APK-schema ``clean/cur_plan/get`` response."""
    fields = _normalize_fields(data, context="GetCurPlan.Response")
    plan_fields = _optional_message(
        fields,
        2,
        context="GetCurPlan.Response.cleanPlan",
    )
    return CurrentPlanResponse(
        result_code=_optional_enum(
            fields,
            1,
            context="GetCurPlan.Response.result",
        ),
        plan=(
            _decode_clean_plan(plan_fields)
            if plan_fields is not None
            else None
        ),
        raw_fields=_freeze_fields(fields),
    )


def decode_clean_plans_response(data: Mapping[object, object]) -> CleanPlansResponse:
    """Decode an APK-schema ``clean/plan/get`` response."""
    fields = _normalize_fields(data, context="GetCleanPlans.Response")
    plan_fields = _repeated_messages(
        fields,
        2,
        context="GetCleanPlans.Response.cleanPlans",
    )
    return CleanPlansResponse(
        result_code=_optional_enum(
            fields,
            1,
            context="GetCleanPlans.Response.result",
        ),
        plans=tuple(_decode_clean_plan(plan) for plan in plan_fields),
        raw_fields=_freeze_fields(fields),
    )


__all__ = [
    "CleanAreaOption",
    "CleanPlan",
    "CleanPlansResponse",
    "CleanTaskParam",
    "CurrentPlanResponse",
    "PlanCodecError",
    "decode_clean_plans_response",
    "decode_current_plan_response",
]
