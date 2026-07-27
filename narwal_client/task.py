"""Read-only decoding for Narwal's current clean-task response."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any


def _integer(value: object) -> int | None:
    """Return an integer without coercing booleans or arbitrary strings."""
    return value if type(value) is int else None


def _fields(value: object) -> dict[int, object]:
    """Normalize blackboxprotobuf field keys while preserving unknown fields."""
    if not isinstance(value, Mapping):
        return {}
    normalized: dict[int, object] = {}
    for key, field_value in value.items():
        if type(key) is int:
            field_number = key
        elif type(key) is str and key.isdecimal() and str(int(key)) == key:
            field_number = int(key)
        else:
            continue
        if field_number > 0:
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
    return value


def _freeze_fields(fields: Mapping[int, object]) -> Mapping[int, object]:
    """Freeze a normalized protobuf field mapping with its key type intact."""
    return MappingProxyType(
        {field_number: _freeze(value) for field_number, value in fields.items()}
    )


def _text(value: object) -> str:
    """Decode a protobuf string without exposing Python bytes reprs."""
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).decode("utf-8", errors="replace")
    return value if isinstance(value, str) else ""


@dataclass(frozen=True, slots=True)
class CurrentTaskZone:
    """Zone referenced by one clean item."""

    zone_type: int | None
    zone_id: int | None
    raw_fields: Mapping[int, object]


@dataclass(frozen=True, slots=True)
class CurrentTaskParameters:
    """Known per-item CleanParam values plus untouched raw fields."""

    mode: int | None
    fan_level: int | None
    mop_strength: int | None
    mop_humidity: int | None
    sweep_count: int | None
    mop_count: int | None
    synchronized_count: int | None
    overlap_level: int | None
    raw_fields: Mapping[int, object]


@dataclass(frozen=True, slots=True)
class CurrentTaskItem:
    """One room/zone entry in the active CleanTask."""

    zone: CurrentTaskZone
    parameters: CurrentTaskParameters
    order: int | None
    raw_fields: Mapping[int, object]


@dataclass(frozen=True, slots=True)
class CurrentCleanTask:
    """Typed diagnostic view of ``clean/current_clean_task/get``."""

    map_id: int | None
    items: tuple[CurrentTaskItem, ...]
    task_type: int | None
    extra: str
    excluded_room_ids: tuple[int, ...]
    raw_fields: Mapping[int, object]
    service_result: object | None = None


def _decode_item(raw_item: object) -> CurrentTaskItem:
    item = _fields(raw_item)
    zone_fields = _fields(item.get(1))
    parameter_fields = _fields(item.get(2))
    return CurrentTaskItem(
        zone=CurrentTaskZone(
            zone_type=_integer(zone_fields.get(1)),
            zone_id=_integer(zone_fields.get(2)),
            raw_fields=_freeze_fields(zone_fields),
        ),
        parameters=CurrentTaskParameters(
            mode=_integer(parameter_fields.get(1)),
            fan_level=_integer(parameter_fields.get(2)),
            mop_strength=_integer(parameter_fields.get(3)),
            mop_humidity=_integer(parameter_fields.get(4)),
            sweep_count=_integer(parameter_fields.get(5)),
            mop_count=_integer(parameter_fields.get(6)),
            synchronized_count=_integer(parameter_fields.get(7)),
            overlap_level=_integer(parameter_fields.get(8)),
            raw_fields=_freeze_fields(parameter_fields),
        ),
        order=_integer(item.get(3)),
        raw_fields=_freeze_fields(item),
    )


def decode_current_task_response(
    data: Mapping[Any, Any],
) -> CurrentCleanTask:
    """Decode a direct CleanTask or its ServiceResult/field-2 wrapper.

    Only the strict wrapper shape (field 1 is a nested ServiceResult and field
    2 is a nested CleanTask) is unwrapped. Unknown task fields remain available
    in ``raw_fields``.
    """
    outer = _fields(data)
    if isinstance(outer.get(1), Mapping) and isinstance(outer.get(2), Mapping):
        task_fields = _fields(outer[2])
        service_result = _freeze(outer[1])
    else:
        task_fields = outer
        service_result = None

    raw_items = task_fields.get(2, ())
    if isinstance(raw_items, Mapping):
        item_values: tuple[object, ...] = (raw_items,)
    elif isinstance(raw_items, (list, tuple)):
        item_values = tuple(raw_items)
    else:
        item_values = ()

    raw_excluded = task_fields.get(8, ())
    if type(raw_excluded) is int:
        excluded_values: tuple[object, ...] = (raw_excluded,)
    elif isinstance(raw_excluded, (list, tuple)):
        excluded_values = tuple(raw_excluded)
    else:
        excluded_values = ()

    return CurrentCleanTask(
        map_id=_integer(task_fields.get(1)),
        items=tuple(_decode_item(item) for item in item_values),
        task_type=_integer(task_fields.get(5)),
        extra=_text(task_fields.get(4)),
        excluded_room_ids=tuple(
            value for value in excluded_values if type(value) is int
        ),
        raw_fields=_freeze_fields(task_fields),
        service_result=service_result,
    )


def _diagnostic_value(value: object) -> Any:
    """Convert frozen wire values to serializable diagnostics."""
    if isinstance(value, Mapping):
        return {
            str(key): _diagnostic_value(nested)
            for key, nested in value.items()
        }
    if isinstance(value, (tuple, list)):
        return [_diagnostic_value(item) for item in value]
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return value.hex()
    return value


def current_task_attributes(task: CurrentCleanTask) -> dict[str, Any]:
    """Return Home Assistant-safe diagnostic attributes."""
    return {
        "map_id": task.map_id,
        "task_type": task.task_type,
        "extra": task.extra or None,
        "excluded_room_ids": list(task.excluded_room_ids),
        "items": [
            {
                "zone_type": item.zone.zone_type,
                "zone_id": item.zone.zone_id,
                "order": item.order,
                "mode": item.parameters.mode,
                "fan_level": item.parameters.fan_level,
                "mop_strength": item.parameters.mop_strength,
                "mop_humidity": item.parameters.mop_humidity,
                "sweep_count": item.parameters.sweep_count,
                "mop_count": item.parameters.mop_count,
                "synchronized_count": item.parameters.synchronized_count,
                "overlap_level": item.parameters.overlap_level,
            }
            for item in task.items
        ],
        "raw_fields": {
            str(field_number): _diagnostic_value(value)
            for field_number, value in task.raw_fields.items()
        },
        "service_result": _diagnostic_value(task.service_result),
    }


__all__ = [
    "CurrentCleanTask",
    "CurrentTaskItem",
    "CurrentTaskParameters",
    "CurrentTaskZone",
    "current_task_attributes",
    "decode_current_task_response",
]
